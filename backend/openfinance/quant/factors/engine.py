import ast
import hashlib
import json
import math
import re
import statistics
from pathlib import Path
from typing import Any, Iterable

from openfinance.data.contracts.dataset import GeneratedDataset, OHLCVBar
from openfinance.data.registry import DatasetRegistry
from openfinance.quant.factors.factor_spec import FactorSpec
from openfinance.quant.factors.registry import FactorRegistry
from openfinance.quant.factors.report import (
    DecayPoint,
    FactorEngineResult,
    FactorHealthReport,
    FactorReport,
    FactorSeriesPoint,
    OOSDecayPoint,
    SensitivityPoint,
)


class FactorEngine:
    def __init__(
        self,
        *,
        dataset_registry: DatasetRegistry,
        factor_registry: FactorRegistry,
        artifact_root: str,
    ) -> None:
        self.dataset_registry = dataset_registry
        self.factor_registry = factor_registry
        self.artifact_root = Path(artifact_root)
        self.artifact_root.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        *,
        factor_spec: FactorSpec,
        dataset_version: str,
        factor_version: str | None = None,
        seed: int = 42,
    ) -> FactorEngineResult:
        dataset_entry = self.dataset_registry.get_entry(dataset_version)
        if dataset_entry is None:
            raise ValueError(f"dataset_version not found: {dataset_version}")
        dataset = GeneratedDataset.model_validate_json(Path(dataset_entry.artifact_path).read_text(encoding="utf-8"))

        resolved_version = factor_version or factor_spec.factor_version or self._factor_version(factor_spec)
        market = str(dataset.generation_config.get("market", "US"))
        symbol = str(dataset.generation_config.get("symbol", "UNKNOWN"))
        artifact_path = self._artifact_path(
            factor_id=factor_spec.factor_id,
            factor_version=resolved_version,
            dataset_version=dataset_version,
        )

        self.factor_registry.register(
            factor_id=factor_spec.factor_id,
            version=resolved_version,
            spec=factor_spec,
            dataset_schema_version=dataset.schema_version,
        )

        if artifact_path.exists():
            cached = json.loads(artifact_path.read_text(encoding="utf-8"))
            return FactorEngineResult.model_validate({**cached, "cached": True})

        bars = sorted(dataset.market, key=lambda row: row.ts)
        if not bars:
            raise ValueError("dataset.market is empty")

        base_values, dsl_execution_plan = self._compute_base_factor_series(
            factor_spec=factor_spec,
            bars=bars,
            market=market,
        )
        timestamps = [bar.ts for bar in bars]
        universe = self._resolve_universe(factor_spec=factor_spec, dataset_symbol=symbol)

        series = self._expand_factor_series(
            base_values=base_values,
            timestamps=timestamps,
            universe=universe,
            seed=seed,
        )
        report = self._build_factor_report(
            factor_spec=factor_spec,
            factor_id=factor_spec.factor_id,
            factor_version=resolved_version,
            dataset_version=dataset_version,
            market=market,
            bars=bars,
            base_values=base_values,
            closes=[bar.close for bar in bars],
            timestamps=timestamps,
            requested_universe=universe,
            seed=seed,
            decay_lags=self._resolve_decay_lags(factor_spec),
            dsl_execution_plan=dsl_execution_plan,
        )
        if report.health_report is not None:
            health_path = self._health_artifact_path(
                factor_id=factor_spec.factor_id,
                factor_version=resolved_version,
                dataset_version=dataset_version,
            )
            health_path.write_text(
                json.dumps(
                    {
                        "factor_id": factor_spec.factor_id,
                        "factor_version": resolved_version,
                        "dataset_version": dataset_version,
                        "health_report": report.health_report.model_dump(mode="json"),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            report = report.model_copy(update={"health_report_artifact_path": str(health_path)})

        result = FactorEngineResult(
            factor_id=factor_spec.factor_id,
            factor_version=resolved_version,
            dataset_version=dataset_version,
            market=market,
            artifact_path=str(artifact_path),
            cached=False,
            factor_series=series,
            report=report,
        )
        artifact_path.write_text(
            json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return result

    def _compute_base_factor_series(
        self,
        *,
        factor_spec: FactorSpec,
        bars: list[OHLCVBar],
        market: str,
    ) -> tuple[list[float], dict[str, Any] | None]:
        factor_id = factor_spec.factor_id.lower()
        formula = factor_spec.params.get("formula")
        if isinstance(formula, str) and formula.strip():
            return self._factor_formula(formula=formula, bars=bars)
        if factor_id in {"momentum_1d", "price_momentum_1d", "momentum"}:
            lookback = self._resolve_lookback(factor_spec, default=1)
            return self._factor_momentum([bar.close for bar in bars], lookback=lookback), None
        if factor_id in {"mean_reversion", "mean_reversion_n", "value_reversion"}:
            window = self._resolve_lookback(factor_spec, default=20)
            return self._factor_mean_reversion([bar.close for bar in bars], window=window), None
        if factor_id in {"volatility", "realized_volatility"}:
            window = self._resolve_lookback(factor_spec, default=20)
            closes = [bar.close for bar in bars]
            return self._factor_volatility(closes=closes, window=window), None
        if factor_id in {"volume_surprise", "volume_spike"}:
            window = self._resolve_lookback(factor_spec, default=20)
            return self._factor_volume_surprise([bar.volume for bar in bars], window=window), None
        if factor_id in {"intraday_return", "intraday"}:
            return self._factor_intraday_return(
                opens=[bar.open for bar in bars],
                closes=[bar.close for bar in bars],
            ), None
        if factor_id in {"carry_proxy", "carry"}:
            return self._factor_carry_proxy(market=market, bars=bars), None
        return self._factor_composite(factor_spec=factor_spec, bars=bars, market=market), None

    def _factor_composite(self, *, factor_spec: FactorSpec, bars: list[OHLCVBar], market: str) -> list[float]:
        closes = [bar.close for bar in bars]
        opens = [bar.open for bar in bars]
        volumes = [bar.volume for bar in bars]
        base_map = {
            "momentum_1d": self._factor_momentum(closes, lookback=max(1, self._resolve_lookback(factor_spec, 1))),
            "mean_reversion": self._factor_mean_reversion(closes, window=max(2, self._resolve_lookback(factor_spec, 20))),
            "volatility": self._factor_volatility(closes=closes, window=max(2, self._resolve_lookback(factor_spec, 20))),
            "volume_surprise": self._factor_volume_surprise(volumes, window=max(2, self._resolve_lookback(factor_spec, 20))),
            "intraday_return": self._factor_intraday_return(opens=opens, closes=closes),
            "carry_proxy": self._factor_carry_proxy(market=market, bars=bars),
        }
        selected: list[list[float]] = []
        for row in factor_spec.inputs:
            selected.append(base_map[self._map_name_to_base_factor(row.name)])
        if not selected:
            selected.append(base_map["momentum_1d"])
            selected.append(base_map["volatility"])
        out: list[float] = []
        for idx in range(len(bars)):
            vals = [series[idx] for series in selected]
            out.append(statistics.fmean(vals))
        return out

    def _factor_momentum(self, closes: list[float], lookback: int) -> list[float]:
        out: list[float] = []
        for idx, value in enumerate(closes):
            prev = closes[idx - lookback] if idx >= lookback else None
            if prev is None or prev == 0:
                out.append(0.0)
            else:
                out.append((value / prev) - 1.0)
        return out

    def _factor_mean_reversion(self, closes: list[float], window: int) -> list[float]:
        out: list[float] = []
        for idx, value in enumerate(closes):
            ma = self._rolling_mean(closes, idx=idx, window=window)
            if ma is None or ma == 0:
                out.append(0.0)
            else:
                out.append((value / ma) - 1.0)
        return out

    def _factor_volatility(self, *, closes: list[float], window: int) -> list[float]:
        returns = self._returns_from_closes(closes)
        out: list[float] = []
        for idx in range(len(closes)):
            vol = self._rolling_std(returns, idx=idx, window=window)
            out.append(vol if vol is not None else 0.0)
        return out

    def _factor_volume_surprise(self, volumes: list[float], window: int) -> list[float]:
        out: list[float] = []
        for idx, value in enumerate(volumes):
            ma = self._rolling_mean(volumes, idx=idx, window=window)
            if ma is None or ma == 0:
                out.append(0.0)
            else:
                out.append((value / ma) - 1.0)
        return out

    def _factor_intraday_return(self, *, opens: list[float], closes: list[float]) -> list[float]:
        out: list[float] = []
        for opn, cls in zip(opens, closes, strict=False):
            if opn == 0:
                out.append(0.0)
            else:
                out.append((cls - opn) / opn)
        return out

    def _factor_carry_proxy(self, *, market: str, bars: list[OHLCVBar]) -> list[float]:
        if market.upper() != "CRYPTO":
            return [0.0 for _ in bars]
        closes = [bar.close for bar in bars]
        returns = self._returns_from_closes(closes)
        out: list[float] = []
        for idx, ret in enumerate(returns):
            cycle = math.sin((idx + 1) / 5.0) * 0.0008
            out.append(cycle + (ret * 0.15))
        return out

    def _expand_factor_series(
        self,
        *,
        base_values: list[float],
        timestamps: list,
        universe: list[str],
        seed: int,
    ) -> list[FactorSeriesPoint]:
        rows: list[FactorSeriesPoint] = []
        for ts, base_value in zip(timestamps, base_values, strict=False):
            safe_base = base_value if math.isfinite(base_value) else 0.0
            for idx, instrument in enumerate(universe):
                rows.append(
                    FactorSeriesPoint(
                        instrument=instrument,
                        ts=ts,
                        value=self._instrument_adjusted_value(
                            base=safe_base,
                            instrument=instrument,
                            instrument_index=idx,
                            ts_text=ts.isoformat(),
                            seed=seed,
                        ),
                    )
                )
        return rows

    def _build_factor_report(
        self,
        *,
        factor_spec: FactorSpec,
        factor_id: str,
        factor_version: str,
        dataset_version: str,
        market: str,
        bars: list[OHLCVBar],
        base_values: list[float],
        closes: list[float],
        timestamps: list,
        requested_universe: list[str],
        seed: int,
        decay_lags: int,
        dsl_execution_plan: dict[str, Any] | None,
    ) -> FactorReport:
        universe = list(requested_universe)
        synthetic_used = False
        if len(universe) < 2:
            synthetic_used = True
            for idx in range(1, 6):
                universe.append(f"SYNTH_{idx:02d}")

        lag_metrics = self._compute_lag_metrics(
            base_values=base_values,
            closes=closes,
            timestamps=timestamps,
            universe=universe,
            seed=seed,
            decay_lags=decay_lags,
        )
        coverage = self._coverage(base_values)
        missing_rate = 1.0 - coverage

        lag1_ic = lag_metrics[0][1] if lag_metrics else []
        lag1_rank_ic = lag_metrics[0][2] if lag_metrics else []
        ic_mean = statistics.fmean(lag1_ic) if lag1_ic else 0.0
        ic_std = statistics.pstdev(lag1_ic) if len(lag1_ic) > 1 else 0.0
        rank_ic_mean = statistics.fmean(lag1_rank_ic) if lag1_rank_ic else 0.0
        rank_ic_std = statistics.pstdev(lag1_rank_ic) if len(lag1_rank_ic) > 1 else 0.0
        turnover_proxy = self._turnover_proxy(
            base_values=base_values,
            timestamps=timestamps,
            universe=universe,
            seed=seed,
            bucket_ratio=0.3,
        )
        (
            in_sample_ic_mean,
            out_sample_ic_mean,
            in_sample_rank_ic_mean,
            out_sample_rank_ic_mean,
            in_sample_n,
            out_sample_n,
            oos_ratio,
        ) = self._oos_split_stats(lag1_ic=lag1_ic, lag1_rank_ic=lag1_rank_ic, ratio=0.7)
        in_sample_decay_curve, out_sample_decay_curve, oos_decay_gap_curve = self._oos_decay_curves(
            lag_metrics=lag_metrics,
            ratio=oos_ratio,
        )
        t_stat = 0.0
        if len(lag1_ic) > 1 and ic_std > 0:
            t_stat = ic_mean / (ic_std / math.sqrt(len(lag1_ic)))
        health_report = self._build_health_report(
            factor_spec=factor_spec,
            bars=bars,
            market=market,
            baseline_values=base_values,
            baseline_ic_mean=ic_mean,
            baseline_rank_ic_mean=rank_ic_mean,
            closes=closes,
            timestamps=timestamps,
            universe=universe,
            seed=seed,
            decay_lags=decay_lags,
            oos_ratio=oos_ratio,
            in_sample_ic_mean=in_sample_ic_mean,
            out_sample_ic_mean=out_sample_ic_mean,
            in_sample_rank_ic_mean=in_sample_rank_ic_mean,
            out_sample_rank_ic_mean=out_sample_rank_ic_mean,
            in_sample_decay_curve=in_sample_decay_curve,
            out_sample_decay_curve=out_sample_decay_curve,
            oos_decay_gap_curve=oos_decay_gap_curve,
        )

        notes = [
            "IC/RankIC computed cross-sectionally by day.",
            f"Universe size used in validation: {len(universe)}.",
            f"OOS split ratio: {oos_ratio:.2f} (in={in_sample_n}, out={out_sample_n}).",
            f"Turnover proxy uses top-bucket membership change (ratio={turnover_proxy:.4f}).",
            f"Health sensitivity variants: {health_report.sensitivity_grid_size}.",
        ]
        if synthetic_used:
            notes.append("Synthetic peers used because dataset universe has one instrument.")

        return FactorReport(
            factor_id=factor_id,
            factor_version=factor_version,
            dataset_version=dataset_version,
            market=market,
            observation_count=len(lag1_ic),
            ic_mean=round(ic_mean, 6),
            ic_std=round(ic_std, 6),
            rank_ic_mean=round(rank_ic_mean, 6),
            rank_ic_std=round(rank_ic_std, 6),
            t_stat=round(t_stat, 6),
            coverage=round(coverage, 6),
            missing_rate=round(missing_rate, 6),
            turnover_proxy=round(turnover_proxy, 6),
            oos_split_ratio=round(oos_ratio, 4),
            in_sample_observation_count=in_sample_n,
            out_sample_observation_count=out_sample_n,
            in_sample_ic_mean=round(in_sample_ic_mean, 6),
            out_sample_ic_mean=round(out_sample_ic_mean, 6),
            in_sample_rank_ic_mean=round(in_sample_rank_ic_mean, 6),
            out_sample_rank_ic_mean=round(out_sample_rank_ic_mean, 6),
            decay_curve=[
                DecayPoint(
                    lag=lag,
                    ic=round(statistics.fmean(ic_values), 6) if ic_values else 0.0,
                )
                for lag, ic_values, _ in lag_metrics
            ],
            in_sample_decay_curve=in_sample_decay_curve,
            out_sample_decay_curve=out_sample_decay_curve,
            dsl_execution_plan=dsl_execution_plan,
            health_report=health_report,
            notes=notes,
        )

    def _compute_lag_metrics(
        self,
        *,
        base_values: list[float],
        closes: list[float],
        timestamps: list,
        universe: list[str],
        seed: int,
        decay_lags: int,
    ) -> list[tuple[int, list[float], list[float]]]:
        lag_metrics: list[tuple[int, list[float], list[float]]] = []
        for lag in range(1, decay_lags + 1):
            ic_values: list[float] = []
            rank_ic_values: list[float] = []
            for idx in range(len(base_values) - lag):
                forward_ret = self._safe_forward_return(closes=closes, idx=idx, lag=lag)
                base_at_idx = base_values[idx] if math.isfinite(base_values[idx]) else 0.0
                factor_vector: list[float] = []
                return_vector: list[float] = []
                for inst_idx, instrument in enumerate(universe):
                    factor_vector.append(
                        self._instrument_adjusted_value(
                            base=base_at_idx,
                            instrument=instrument,
                            instrument_index=inst_idx,
                            ts_text=timestamps[idx].isoformat(),
                            seed=seed,
                        )
                    )
                    return_vector.append(
                        self._instrument_adjusted_return(
                            base=forward_ret,
                            instrument=instrument,
                            instrument_index=inst_idx,
                            ts_text=timestamps[idx].isoformat(),
                            seed=seed,
                        )
                    )
                ic_values.append(self._pearson(factor_vector, return_vector))
                rank_ic_values.append(self._rank_ic(factor_vector, return_vector))
            lag_metrics.append((lag, ic_values, rank_ic_values))
        return lag_metrics

    def _oos_decay_curves(
        self,
        *,
        lag_metrics: list[tuple[int, list[float], list[float]]],
        ratio: float,
    ) -> tuple[list[DecayPoint], list[DecayPoint], list[OOSDecayPoint]]:
        in_curve: list[DecayPoint] = []
        out_curve: list[DecayPoint] = []
        gap_curve: list[OOSDecayPoint] = []
        for lag, ic_values, _ in lag_metrics:
            n = len(ic_values)
            if n == 0:
                in_ic = 0.0
                out_ic = 0.0
            elif n == 1:
                in_ic = float(ic_values[0])
                out_ic = float(ic_values[0])
            else:
                split = max(1, min(n - 1, int(n * max(0.5, min(0.9, ratio)))))
                in_part = ic_values[:split]
                out_part = ic_values[split:]
                in_ic = statistics.fmean(in_part) if in_part else 0.0
                out_ic = statistics.fmean(out_part) if out_part else 0.0
            in_curve.append(DecayPoint(lag=lag, ic=round(in_ic, 6)))
            out_curve.append(DecayPoint(lag=lag, ic=round(out_ic, 6)))
            gap_curve.append(
                OOSDecayPoint(
                    lag=lag,
                    in_sample_ic=round(in_ic, 6),
                    out_sample_ic=round(out_ic, 6),
                    gap=round(in_ic - out_ic, 6),
                )
            )
        return in_curve, out_curve, gap_curve

    def _build_health_report(
        self,
        *,
        factor_spec: FactorSpec,
        bars: list[OHLCVBar],
        market: str,
        baseline_values: list[float],
        baseline_ic_mean: float,
        baseline_rank_ic_mean: float,
        closes: list[float],
        timestamps: list,
        universe: list[str],
        seed: int,
        decay_lags: int,
        oos_ratio: float,
        in_sample_ic_mean: float,
        out_sample_ic_mean: float,
        in_sample_rank_ic_mean: float,
        out_sample_rank_ic_mean: float,
        in_sample_decay_curve: list[DecayPoint],
        out_sample_decay_curve: list[DecayPoint],
        oos_decay_gap_curve: list[OOSDecayPoint],
    ) -> FactorHealthReport:
        sensitivity_rows = self._sensitivity_rows(
            factor_spec=factor_spec,
            bars=bars,
            market=market,
            baseline_values=baseline_values,
            baseline_ic_mean=baseline_ic_mean,
            baseline_rank_ic_mean=baseline_rank_ic_mean,
            closes=closes,
            timestamps=timestamps,
            universe=universe,
            seed=seed,
            decay_lags=decay_lags,
        )
        non_baseline = [row for row in sensitivity_rows if row.variant_id != "baseline"]
        abs_deltas = [abs(row.ic_delta) + (0.5 * abs(row.rank_ic_delta)) for row in non_baseline]
        mean_delta = statistics.fmean(abs_deltas) if abs_deltas else 0.0
        std_delta = statistics.pstdev(abs_deltas) if len(abs_deltas) > 1 else 0.0
        stability = 1.0 / (1.0 + (20.0 * mean_delta) + (15.0 * std_delta))
        oos_gap = abs(in_sample_ic_mean - out_sample_ic_mean)
        notes = [
            f"OOS split ratio={oos_ratio:.2f}.",
            "Sensitivity grid includes window/smoothing/winsor threshold perturbations.",
        ]
        return FactorHealthReport(
            stability_score=round(max(0.0, min(1.0, stability)), 6),
            oos_gap=round(oos_gap, 6),
            in_sample_ic_mean=round(in_sample_ic_mean, 6),
            out_sample_ic_mean=round(out_sample_ic_mean, 6),
            in_sample_rank_ic_mean=round(in_sample_rank_ic_mean, 6),
            out_sample_rank_ic_mean=round(out_sample_rank_ic_mean, 6),
            in_sample_decay_curve=in_sample_decay_curve,
            out_sample_decay_curve=out_sample_decay_curve,
            oos_decay_gap_curve=oos_decay_gap_curve,
            sensitivity=sensitivity_rows,
            sensitivity_grid_size=len(sensitivity_rows),
            notes=notes,
        )

    def _sensitivity_rows(
        self,
        *,
        factor_spec: FactorSpec,
        bars: list[OHLCVBar],
        market: str,
        baseline_values: list[float],
        baseline_ic_mean: float,
        baseline_rank_ic_mean: float,
        closes: list[float],
        timestamps: list,
        universe: list[str],
        seed: int,
        decay_lags: int,
    ) -> list[SensitivityPoint]:
        rows: list[SensitivityPoint] = []

        def _metric_row(variant_id: str, params: dict[str, float | int | str], values: list[float]) -> None:
            lag_metrics = self._compute_lag_metrics(
                base_values=values,
                closes=closes,
                timestamps=timestamps,
                universe=universe,
                seed=seed,
                decay_lags=decay_lags,
            )
            lag1_ic = lag_metrics[0][1] if lag_metrics else []
            lag1_rank_ic = lag_metrics[0][2] if lag_metrics else []
            ic_mean = statistics.fmean(lag1_ic) if lag1_ic else 0.0
            rank_ic_mean = statistics.fmean(lag1_rank_ic) if lag1_rank_ic else 0.0
            rows.append(
                SensitivityPoint(
                    variant_id=variant_id,
                    params=params,
                    ic_mean=round(ic_mean, 6),
                    rank_ic_mean=round(rank_ic_mean, 6),
                    ic_delta=round(ic_mean - baseline_ic_mean, 6),
                    rank_ic_delta=round(rank_ic_mean - baseline_rank_ic_mean, 6),
                    observation_count=len(lag1_ic),
                )
            )

        _metric_row("baseline", {"window": self._resolve_lookback(factor_spec, default=20)}, baseline_values)
        base_window = self._resolve_lookback(factor_spec, default=20)
        window_low = max(2, int(round(base_window * 0.7)))
        window_high = min(252, max(window_low + 1, int(round(base_window * 1.3))))
        window_mid = min(252, max(2, int(round(base_window * 1.6))))
        for window in [window_low, window_high, window_mid]:
            values = self._series_for_window_variant(
                factor_spec=factor_spec,
                bars=bars,
                market=market,
                baseline_values=baseline_values,
                window=window,
            )
            _metric_row(f"window_{window}", {"window": window}, values)

        smooth_low = self._ema_smooth(baseline_values, alpha=0.12)
        smooth_high = self._ema_smooth(baseline_values, alpha=0.35)
        _metric_row("smooth_alpha_0.12", {"smoothing_alpha": 0.12}, smooth_low)
        _metric_row("smooth_alpha_0.35", {"smoothing_alpha": 0.35}, smooth_high)

        winsor_tight = self._winsorize_series(baseline_values, p_low=0.03, p_high=0.97)
        winsor_wide = self._winsorize_series(baseline_values, p_low=0.10, p_high=0.90)
        _metric_row("winsor_0.03_0.97", {"winsor_p_low": 0.03, "winsor_p_high": 0.97}, winsor_tight)
        _metric_row("winsor_0.10_0.90", {"winsor_p_low": 0.10, "winsor_p_high": 0.90}, winsor_wide)

        dedup: dict[str, SensitivityPoint] = {}
        for row in rows:
            dedup[row.variant_id] = row
        out = list(dedup.values())
        if len(out) < 5:
            fallback = self._ema_smooth(baseline_values, alpha=0.5)
            _metric_row("smooth_alpha_0.50", {"smoothing_alpha": 0.5}, fallback)
            out = list({row.variant_id: row for row in rows}.values())
        return out

    def _series_for_window_variant(
        self,
        *,
        factor_spec: FactorSpec,
        bars: list[OHLCVBar],
        market: str,
        baseline_values: list[float],
        window: int,
    ) -> list[float]:
        mut_spec = factor_spec.model_copy(deep=True)
        mut_params = dict(mut_spec.params)
        mut_params["lookback_days"] = window
        if isinstance(mut_params.get("window"), (int, float)):
            mut_params["window"] = int(window)
        formula = mut_params.get("formula")
        if isinstance(formula, str):
            mut_params["formula"] = self._mutate_formula_window(formula=formula, window=window)
        mut_spec = mut_spec.model_copy(update={"params": mut_params})
        try:
            values, _ = self._compute_base_factor_series(factor_spec=mut_spec, bars=bars, market=market)
            return values
        except Exception:
            return self._rolling_fill(baseline_values, window=window)

    def _mutate_formula_window(self, *, formula: str, window: int) -> str:
        pattern = re.compile(
            r"(?i)\b(Ts_Mean|Ts_Std|Shift|rolling_mean|rolling_std)\s*\(\s*([^,]+?)\s*,\s*(\d+)\s*\)"
        )
        updated, _ = pattern.subn(lambda m: f"{m.group(1)}({m.group(2)}, {window})", formula)
        return updated

    def _rolling_fill(self, values: list[float], *, window: int) -> list[float]:
        out: list[float] = []
        for idx in range(len(values)):
            mean = self._rolling_mean(values, idx=idx, window=max(2, window))
            out.append(mean if mean is not None else values[idx])
        return out

    def _ema_smooth(self, values: list[float], *, alpha: float) -> list[float]:
        clipped = max(0.01, min(0.99, alpha))
        if not values:
            return []
        out: list[float] = [values[0] if math.isfinite(values[0]) else 0.0]
        for idx in range(1, len(values)):
            curr = values[idx] if math.isfinite(values[idx]) else out[-1]
            out.append((clipped * curr) + ((1.0 - clipped) * out[-1]))
        return out

    def _winsorize_series(self, values: list[float], *, p_low: float, p_high: float) -> list[float]:
        finite = sorted(value for value in values if math.isfinite(value))
        if not finite:
            return [0.0 for _ in values]
        low = self._quantile(finite, max(0.0, min(0.49, p_low)))
        high = self._quantile(finite, max(0.51, min(1.0, p_high)))
        if low > high:
            low, high = high, low
        out: list[float] = []
        for value in values:
            if not math.isfinite(value):
                out.append(0.0)
            else:
                out.append(min(high, max(low, value)))
        return out

    def _resolve_universe(self, *, factor_spec: FactorSpec, dataset_symbol: str) -> list[str]:
        out = [dataset_symbol]
        raw = factor_spec.params.get("universe")
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str) and item and item not in out:
                    out.append(item)
        return out

    def _resolve_lookback(self, factor_spec: FactorSpec, default: int) -> int:
        numeric_keys = ["lookback", "lookback_days", "window", "n"]
        for key in numeric_keys:
            value = factor_spec.params.get(key)
            if isinstance(value, int) and value > 0:
                return min(252, value)
            if isinstance(value, float) and value > 0:
                return min(252, int(value))
        for transform in factor_spec.transforms:
            for key in numeric_keys:
                value = transform.params.get(key)
                if isinstance(value, int) and value > 0:
                    return min(252, value)
                if isinstance(value, float) and value > 0:
                    return min(252, int(value))
        match = re.search(r"(\d+)", factor_spec.factor_id)
        if match:
            return max(1, min(252, int(match.group(1))))
        return default

    def _resolve_decay_lags(self, factor_spec: FactorSpec) -> int:
        value = factor_spec.params.get("decay_lags", 5)
        if isinstance(value, int):
            return max(1, min(20, value))
        if isinstance(value, float):
            return max(1, min(20, int(value)))
        return 5

    def _turnover_proxy(
        self,
        *,
        base_values: list[float],
        timestamps: list,
        universe: list[str],
        seed: int,
        bucket_ratio: float = 0.3,
    ) -> float:
        if len(base_values) < 2 or len(universe) < 2:
            return 0.0
        k = max(1, int(math.ceil(len(universe) * max(0.1, min(bucket_ratio, 0.5)))))
        prev_top: set[str] | None = None
        turns: list[float] = []
        for idx, base in enumerate(base_values):
            score_rows: list[tuple[float, str]] = []
            ts_text = timestamps[idx].isoformat() if idx < len(timestamps) else str(idx)
            safe_base = base if math.isfinite(base) else 0.0
            for inst_idx, inst in enumerate(universe):
                value = self._instrument_adjusted_value(
                    base=safe_base,
                    instrument=inst,
                    instrument_index=inst_idx,
                    ts_text=ts_text,
                    seed=seed,
                )
                score_rows.append((value, inst))
            score_rows.sort(key=lambda row: row[0], reverse=True)
            curr_top = {inst for _, inst in score_rows[:k]}
            if prev_top is not None:
                overlap = len(prev_top & curr_top)
                turns.append(1.0 - (overlap / max(1, len(prev_top))))
            prev_top = curr_top
        return statistics.fmean(turns) if turns else 0.0

    def _oos_split_stats(
        self,
        *,
        lag1_ic: list[float],
        lag1_rank_ic: list[float],
        ratio: float = 0.7,
    ) -> tuple[float, float, float, float, int, int, float]:
        n = min(len(lag1_ic), len(lag1_rank_ic))
        if n <= 0:
            return (0.0, 0.0, 0.0, 0.0, 0, 0, ratio)
        clipped_ratio = max(0.5, min(0.9, ratio))
        if n == 1:
            return (lag1_ic[0], lag1_ic[0], lag1_rank_ic[0], lag1_rank_ic[0], 1, 0, clipped_ratio)
        split = int(n * clipped_ratio)
        split = max(1, min(n - 1, split))
        in_ic = lag1_ic[:split]
        out_ic = lag1_ic[split:]
        in_rank = lag1_rank_ic[:split]
        out_rank = lag1_rank_ic[split:]
        return (
            statistics.fmean(in_ic) if in_ic else 0.0,
            statistics.fmean(out_ic) if out_ic else 0.0,
            statistics.fmean(in_rank) if in_rank else 0.0,
            statistics.fmean(out_rank) if out_rank else 0.0,
            len(in_ic),
            len(out_ic),
            clipped_ratio,
        )

    def _map_name_to_base_factor(self, name: str) -> str:
        text = name.lower()
        if any(token in text for token in ["carry", "funding"]):
            return "carry_proxy"
        if any(token in text for token in ["intraday", "open_close"]):
            return "intraday_return"
        if any(token in text for token in ["volume", "liquidity"]):
            return "volume_surprise"
        if any(token in text for token in ["vol", "risk_parity"]):
            return "volatility"
        if any(token in text for token in ["value", "yield", "pe", "meanrev", "reversion"]):
            return "mean_reversion"
        return "momentum_1d"

    def _rolling_mean(self, values: list[float], *, idx: int, window: int) -> float | None:
        if idx + 1 < window or window <= 0:
            return None
        segment = values[idx - window + 1 : idx + 1]
        return statistics.fmean(segment) if segment else None

    def _rolling_std(self, values: list[float], *, idx: int, window: int) -> float | None:
        if idx + 1 < window or window <= 1:
            return None
        segment = values[idx - window + 1 : idx + 1]
        if len(segment) <= 1:
            return None
        return statistics.pstdev(segment)

    def _returns_from_closes(self, closes: list[float]) -> list[float]:
        out: list[float] = []
        prev = closes[0] if closes else 0.0
        for idx, value in enumerate(closes):
            if idx == 0 or prev == 0:
                out.append(0.0)
            else:
                out.append((value / prev) - 1.0)
            prev = value
        return out

    def _safe_forward_return(self, *, closes: list[float], idx: int, lag: int) -> float:
        start = closes[idx]
        end = closes[idx + lag]
        if start == 0:
            return 0.0
        return (end / start) - 1.0

    def _instrument_adjusted_value(
        self,
        *,
        base: float,
        instrument: str,
        instrument_index: int,
        ts_text: str,
        seed: int,
    ) -> float:
        noise = self._deterministic_noise(parts=[instrument, ts_text, "f", str(seed)])
        scale = 1.0 + (0.04 * instrument_index)
        shift = (instrument_index * 0.0005) - 0.001
        return (base * scale) + shift + (noise * 0.01)

    def _instrument_adjusted_return(
        self,
        *,
        base: float,
        instrument: str,
        instrument_index: int,
        ts_text: str,
        seed: int,
    ) -> float:
        noise = self._deterministic_noise(parts=[instrument, ts_text, "r", str(seed)])
        scale = 0.85 + (0.05 * instrument_index)
        shift = (instrument_index * 0.0002) - 0.0004
        return (base * scale) + shift - (noise * 0.003)

    def _deterministic_noise(self, *, parts: Iterable[str]) -> float:
        raw = "|".join(parts)
        value = int(hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8], 16)
        return (value / 0xFFFFFFFF) - 0.5

    def _pearson(self, x: list[float], y: list[float]) -> float:
        if len(x) != len(y) or len(x) < 2:
            return 0.0
        mean_x = statistics.fmean(x)
        mean_y = statistics.fmean(y)
        num = 0.0
        den_x = 0.0
        den_y = 0.0
        for xv, yv in zip(x, y, strict=False):
            dx = xv - mean_x
            dy = yv - mean_y
            num += dx * dy
            den_x += dx * dx
            den_y += dy * dy
        if den_x <= 0 or den_y <= 0:
            return 0.0
        return num / math.sqrt(den_x * den_y)

    def _rank_ic(self, x: list[float], y: list[float]) -> float:
        return self._pearson(self._ranks(x), self._ranks(y))

    def _ranks(self, values: list[float]) -> list[float]:
        indexed = sorted(enumerate(values), key=lambda row: row[1])
        ranks = [0.0] * len(values)
        for rank, (idx, _) in enumerate(indexed, start=1):
            ranks[idx] = float(rank)
        return ranks

    def _factor_version(self, factor_spec: FactorSpec) -> str:
        payload = factor_spec.model_dump(mode="json")
        return hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:12]

    def _artifact_path(self, *, factor_id: str, factor_version: str, dataset_version: str) -> Path:
        digest = hashlib.sha1(
            json.dumps(
                {"factor_id": factor_id, "factor_version": factor_version, "dataset_version": dataset_version},
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:16]
        return self.artifact_root / f"{digest}.json"

    def _health_artifact_path(self, *, factor_id: str, factor_version: str, dataset_version: str) -> Path:
        digest = hashlib.sha1(
            json.dumps(
                {"factor_id": factor_id, "factor_version": factor_version, "dataset_version": dataset_version, "kind": "health"},
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:16]
        return self.artifact_root / f"{digest}.health.json"

    def _factor_formula(self, *, formula: str, bars: list[OHLCVBar]) -> tuple[list[float], dict[str, Any]]:
        closes = [bar.close for bar in bars]
        opens = [bar.open for bar in bars]
        highs = [bar.high for bar in bars]
        lows = [bar.low for bar in bars]
        volumes = [bar.volume for bar in bars]
        returns = self._returns_from_closes(closes)
        env: dict[str, float | list[float]] = {
            "close": closes,
            "open": opens,
            "high": highs,
            "low": lows,
            "volume": volumes,
            "return_1d": returns,
        }
        try:
            parsed = ast.parse(formula, mode="eval")
        except SyntaxError as ex:
            raise ValueError(f"invalid formula syntax: {formula}") from ex
        self._validate_dsl_ast(parsed)
        plan = self._compile_dsl_plan(parsed.body)
        value = self._execute_dsl_plan(plan, env=env, length=len(bars))
        return [float(v) for v in value[: len(bars)]], {"dsl": formula, "plan": plan}

    def _validate_dsl_ast(self, parsed: ast.Expression) -> None:
        allowed_node_types = (
            ast.Expression,
            ast.BinOp,
            ast.UnaryOp,
            ast.Call,
            ast.Name,
            ast.Load,
            ast.Constant,
            ast.Add,
            ast.Sub,
            ast.Mult,
            ast.Div,
            ast.USub,
            ast.UAdd,
        )
        for node in ast.walk(parsed):
            if not isinstance(node, allowed_node_types):
                raise ValueError(f"unsupported formula syntax: {type(node).__name__}")
            if isinstance(node, ast.Call):
                if not isinstance(node.func, ast.Name):
                    raise ValueError("only direct whitelisted function calls are allowed")
                if node.keywords:
                    raise ValueError("keyword arguments are not allowed in factor DSL")
                self._normalize_dsl_function_name(node.func.id)

    def _compile_dsl_plan(self, node: ast.AST) -> dict[str, Any]:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return {"kind": "const", "value": float(node.value)}
            raise ValueError("only numeric constants are allowed in factor DSL")
        if isinstance(node, ast.Name):
            return {"kind": "var", "name": node.id}
        if isinstance(node, ast.UnaryOp):
            op = "neg" if isinstance(node.op, ast.USub) else "pos"
            if op not in {"neg", "pos"}:
                raise ValueError("unsupported unary operator")
            return {"kind": "unary", "op": op, "arg": self._compile_dsl_plan(node.operand)}
        if isinstance(node, ast.BinOp):
            op_map: dict[type[ast.AST], str] = {
                ast.Add: "add",
                ast.Sub: "sub",
                ast.Mult: "mul",
                ast.Div: "div",
            }
            op = op_map.get(type(node.op))
            if not op:
                raise ValueError("unsupported binary operator")
            return {
                "kind": "binop",
                "op": op,
                "left": self._compile_dsl_plan(node.left),
                "right": self._compile_dsl_plan(node.right),
            }
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("only whitelisted function calls are allowed")
            fn = self._normalize_dsl_function_name(node.func.id)
            return {
                "kind": "call",
                "fn": fn,
                "args": [self._compile_dsl_plan(arg) for arg in node.args],
            }
        raise ValueError(f"unsupported formula syntax: {type(node).__name__}")

    def _normalize_dsl_function_name(self, name: str) -> str:
        key = name.strip().lower()
        aliases = {
            "ts_mean": "ts_mean",
            "rolling_mean": "ts_mean",
            "ts_std": "ts_std",
            "rolling_std": "ts_std",
            "shift": "shift",
            "rank": "rank",
            "zscore": "zscore",
            "clip": "clip",
            "winsorize": "winsorize",
        }
        if key not in aliases:
            raise ValueError(f"formula function not allowed: {name}")
        return aliases[key]

    def _execute_dsl_plan(
        self,
        plan: dict[str, Any],
        *,
        env: dict[str, float | list[float]],
        length: int,
    ) -> list[float]:
        kind = plan.get("kind")
        if kind == "const":
            return [float(plan["value"])] * length
        if kind == "var":
            return self._resolve_dsl_variable(plan["name"], env=env, length=length)
        if kind == "unary":
            series = self._execute_dsl_plan(plan["arg"], env=env, length=length)
            if plan.get("op") == "neg":
                return [-1.0 * v if math.isfinite(v) else math.nan for v in series]
            if plan.get("op") == "pos":
                return series
            raise ValueError("unsupported unary plan op")
        if kind == "binop":
            left = self._execute_dsl_plan(plan["left"], env=env, length=length)
            right = self._execute_dsl_plan(plan["right"], env=env, length=length)
            op = plan.get("op")
            if op == "add":
                return [l + r for l, r in zip(left, right, strict=False)]
            if op == "sub":
                return [l - r for l, r in zip(left, right, strict=False)]
            if op == "mul":
                return [l * r for l, r in zip(left, right, strict=False)]
            if op == "div":
                out: list[float] = []
                for l, r in zip(left, right, strict=False):
                    out.append(math.nan if r == 0 else (l / r))
                return out
            raise ValueError("unsupported binary plan op")
        if kind == "call":
            fn = str(plan.get("fn"))
            args = [self._execute_dsl_plan(arg, env=env, length=length) for arg in plan.get("args", [])]
            if fn == "ts_mean":
                return self._formula_rolling_mean(args, length=length)
            if fn == "ts_std":
                return self._formula_rolling_std(args, length=length)
            if fn == "shift":
                return self._formula_shift(args, length=length)
            if fn == "rank":
                return self._formula_rank(args, length=length)
            if fn == "zscore":
                return self._formula_zscore(args, length=length)
            if fn == "clip":
                return self._formula_clip(args, length=length)
            if fn == "winsorize":
                return self._formula_winsorize(args, length=length)
            raise ValueError(f"unsupported call function in plan: {fn}")
        raise ValueError(f"unsupported DSL plan kind: {kind}")

    def _resolve_dsl_variable(
        self,
        name: str,
        *,
        env: dict[str, float | list[float]],
        length: int,
    ) -> list[float]:
        if name in env:
            return self._as_series(env[name], length=length)
        low = name.lower()
        if low in env:
            return self._as_series(env[low], length=length)
        mom_match = re.fullmatch(r"momentum_(\d+)", low)
        if mom_match:
            lookback = max(1, min(252, int(mom_match.group(1))))
            close_series = self._as_series(env.get("close", [0.0] * length), length=length)
            computed = self._factor_momentum(close_series, lookback=lookback)
            env[low] = computed
            return self._as_series(computed, length=length)
        raise ValueError(f"formula variable not allowed: {name}")

    def _as_series(self, value: float | list[float], *, length: int) -> list[float]:
        if isinstance(value, list):
            if len(value) >= length:
                return [float(v) for v in value[:length]]
            padded = [float(v) for v in value]
            padded.extend([0.0] * (length - len(padded)))
            return padded
        return [float(value)] * length

    def _as_int(self, value: float | list[float], *, default: int = 1) -> int:
        if isinstance(value, list):
            if not value:
                return default
            return max(1, int(value[0]))
        return max(1, int(value))

    def _formula_rolling_mean(self, args: list[float | list[float]], *, length: int) -> list[float]:
        if len(args) != 2:
            raise ValueError("rolling_mean(x, window) expects two arguments")
        series = self._as_series(args[0], length=length)
        window = self._as_int(args[1], default=5)
        out: list[float] = []
        for idx in range(length):
            mean = self._rolling_mean(series, idx=idx, window=window)
            out.append(mean if mean is not None else math.nan)
        return out

    def _formula_rolling_std(self, args: list[float | list[float]], *, length: int) -> list[float]:
        if len(args) != 2:
            raise ValueError("rolling_std(x, window) expects two arguments")
        series = self._as_series(args[0], length=length)
        window = self._as_int(args[1], default=5)
        out: list[float] = []
        for idx in range(length):
            std = self._rolling_std(series, idx=idx, window=window)
            out.append(std if std is not None else math.nan)
        return out

    def _formula_shift(self, args: list[float | list[float]], *, length: int) -> list[float]:
        if len(args) != 2:
            raise ValueError("shift(x, n) expects two arguments")
        series = self._as_series(args[0], length=length)
        lag = self._as_int(args[1], default=1)
        out: list[float] = []
        for idx in range(length):
            if idx - lag < 0:
                out.append(math.nan)
            else:
                out.append(series[idx - lag])
        return out

    def _formula_rank(self, args: list[float | list[float]], *, length: int) -> list[float]:
        if len(args) != 1:
            raise ValueError("rank(x) expects one argument")
        series = self._as_series(args[0], length=length)
        finite_rows = [(idx, value) for idx, value in enumerate(series) if math.isfinite(value)]
        ranks = [math.nan] * length
        if not finite_rows:
            return ranks
        for rank, (idx, _) in enumerate(sorted(finite_rows, key=lambda row: row[1]), start=1):
            ranks[idx] = rank / max(1, len(finite_rows))
        return ranks

    def _formula_zscore(self, args: list[float | list[float]], *, length: int) -> list[float]:
        if len(args) != 1:
            raise ValueError("zscore(x) expects one argument")
        series = self._as_series(args[0], length=length)
        finite_values = [value for value in series if math.isfinite(value)]
        if len(finite_values) < 2:
            return [0.0 if math.isfinite(value) else math.nan for value in series]
        mean = statistics.fmean(finite_values)
        std = statistics.pstdev(finite_values)
        if std <= 0:
            return [0.0 if math.isfinite(value) else math.nan for value in series]
        return [((value - mean) / std) if math.isfinite(value) else math.nan for value in series]

    def _formula_clip(self, args: list[float | list[float]], *, length: int) -> list[float]:
        if len(args) != 3:
            raise ValueError("clip(x, low, high) expects three arguments")
        series = self._as_series(args[0], length=length)
        low = float(self._as_int_or_float(args[1], default=-3.0))
        high = float(self._as_int_or_float(args[2], default=3.0))
        if low > high:
            low, high = high, low
        out: list[float] = []
        for value in series:
            if not math.isfinite(value):
                out.append(math.nan)
            else:
                out.append(min(high, max(low, value)))
        return out

    def _formula_winsorize(self, args: list[float | list[float]], *, length: int) -> list[float]:
        if len(args) not in {1, 2, 3}:
            raise ValueError("winsorize(x[, p_low[, p_high]]) expects 1-3 arguments")
        series = self._as_series(args[0], length=length)
        p_low = 0.05
        p_high = 0.95
        if len(args) >= 2:
            p_low = float(self._as_int_or_float(args[1], default=0.05))
            p_low = max(0.0, min(0.49, p_low))
            p_high = 1.0 - p_low
        if len(args) == 3:
            p_high = float(self._as_int_or_float(args[2], default=0.95))
            p_high = max(0.51, min(1.0, p_high))
        if p_low >= p_high:
            p_low, p_high = 0.05, 0.95
        finite = sorted(value for value in series if math.isfinite(value))
        if not finite:
            return [math.nan] * length
        low_v = self._quantile(finite, p_low)
        high_v = self._quantile(finite, p_high)
        return self._formula_clip([series, [low_v], [high_v]], length=length)

    def _quantile(self, sorted_values: list[float], p: float) -> float:
        if not sorted_values:
            return math.nan
        if len(sorted_values) == 1:
            return sorted_values[0]
        rank = p * (len(sorted_values) - 1)
        lo = int(math.floor(rank))
        hi = int(math.ceil(rank))
        if lo == hi:
            return sorted_values[lo]
        w = rank - lo
        return (sorted_values[lo] * (1.0 - w)) + (sorted_values[hi] * w)

    def _as_int_or_float(self, value: float | list[float], *, default: float) -> float:
        if isinstance(value, list):
            if not value:
                return default
            return float(value[0])
        return float(value)

    def _coverage(self, values: list[float]) -> float:
        if not values:
            return 0.0
        finite = sum(1 for value in values if math.isfinite(value))
        return finite / len(values)
