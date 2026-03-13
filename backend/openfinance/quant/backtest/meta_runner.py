import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from openfinance.data.contracts.dataset import GeneratedDataset, OHLCVBar
from openfinance.quant.backtest.report import BacktestRequest, CostModel
from openfinance.quant.backtest.robustness import (
    RegimeMetric,
    RobustnessReport,
    RobustnessSummary,
    RobustnessVariant,
    StressMetric,
    WorstCaseSummary,
)
from openfinance.quant.backtest.runner import BacktestRunner


@dataclass(frozen=True)
class MetaBacktestConfig:
    cost_multipliers: tuple[float, ...] = (0.5, 1.0, 2.0)
    lookback_values: tuple[int, ...] | None = None
    threshold_values: tuple[float, ...] | None = None
    rebalance_values: tuple[str, ...] | None = None
    min_variants: int = 6
    max_variants: int = 12
    regime_vol_window: int = 20
    stress_shock_return: float = -0.12
    stress_vol_multiplier: float = 2.0


class MetaBacktestRunner:
    def __init__(self, runner: BacktestRunner) -> None:
        self.runner = runner

    def plan_variants(self, request: BacktestRequest, config: MetaBacktestConfig | None = None) -> list[dict[str, Any]]:
        cfg = config or MetaBacktestConfig()
        return self._build_variant_plans(request=request, config=cfg)

    def run(
        self,
        request: BacktestRequest,
        config: MetaBacktestConfig | None = None,
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> RobustnessReport:
        cfg = config or MetaBacktestConfig()
        plans = self.plan_variants(request=request, config=cfg)
        if progress_callback is not None:
            progress_callback(
                {
                    "phase": "variants.planned",
                    "total": len(plans),
                    "plans": [
                        {
                            "variant_id": str(row["variant_id"]),
                            "group": str(row["group"]),
                            "scenario": str(row["scenario"]),
                        }
                        for row in plans
                    ],
                }
            )
        variants: list[RobustnessVariant] = []
        table: list[dict[str, float | int | str]] = []

        for idx, plan in enumerate(plans):
            if progress_callback is not None:
                progress_callback(
                    {
                        "phase": "variant.start",
                        "index": idx + 1,
                        "total": len(plans),
                        "variant_id": str(plan["variant_id"]),
                        "group": str(plan["group"]),
                        "scenario": str(plan["scenario"]),
                    }
                )
            run_request = BacktestRequest(
                dataset_version=request.dataset_version,
                strategy_id=request.strategy_id,
                strategy_version=plan["strategy_version"],
                market=request.market,
                start=request.start,
                end=request.end,
                execution_model=request.execution_model,
                cost_model=CostModel(
                    commission_bps=float(plan["commission_bps"]),
                    slippage_bps=float(plan["slippage_bps"]),
                ),
                factor_versions=list(request.factor_versions),
                constraints=dict(plan["constraints"]),
                evaluation_plan={
                    **dict(request.evaluation_plan),
                    "meta_variant_id": plan["variant_id"],
                    "meta_group": plan["group"],
                },
            )
            report = self.runner.run(run_request)
            metrics = report.metrics
            variant = RobustnessVariant(
                variant_id=str(plan["variant_id"]),
                group=str(plan["group"]),
                scenario=str(plan["scenario"]),
                run_id=str(report.run_id),
                strategy_version=report.strategy_version,
                commission_bps=float(plan["commission_bps"]),
                slippage_bps=float(plan["slippage_bps"]),
                constraints=dict(plan["constraints"]),
                metrics=metrics,
            )
            variants.append(variant)
            table.append(
                {
                    "variant_id": variant.variant_id,
                    "group": variant.group,
                    "scenario": variant.scenario,
                    "run_id": variant.run_id,
                    "commission_bps": round(variant.commission_bps, 6),
                    "slippage_bps": round(variant.slippage_bps, 6),
                    "sharpe": self._metric(metrics, "sharpe"),
                    "max_drawdown": self._metric(metrics, "max_drawdown"),
                    "total_return": self._metric(metrics, "total_return"),
                    "cost_drag": self._metric(metrics, "cost_drag"),
                    "turnover": self._metric(metrics, "turnover"),
                }
            )
            if progress_callback is not None:
                progress_callback(
                    {
                        "phase": "variant.done",
                        "index": idx + 1,
                        "total": len(plans),
                        "variant_id": variant.variant_id,
                        "group": variant.group,
                        "scenario": variant.scenario,
                        "run_id": variant.run_id,
                        "metrics": {
                            "sharpe": self._metric(metrics, "sharpe"),
                            "max_drawdown": self._metric(metrics, "max_drawdown"),
                            "total_return": self._metric(metrics, "total_return"),
                            "cost_drag": self._metric(metrics, "cost_drag"),
                        },
                    }
                )

        summary = self._build_summary(variants)
        if progress_callback is not None:
            progress_callback(
                {
                    "phase": "variants.summary",
                    "completed": len(variants),
                    "total": len(plans),
                    "summary": summary.model_dump(mode="json"),
                }
            )
        base_dataset = self._load_dataset(request.dataset_version)
        if progress_callback is not None:
            progress_callback({"phase": "regime.start"})
        regime_metrics = self._run_regime_slices(request=request, dataset=base_dataset, config=cfg)
        if progress_callback is not None:
            progress_callback({"phase": "regime.done", "count": len(regime_metrics)})
            progress_callback({"phase": "stress.start"})
        stress_metrics = self._run_stress_scenarios(request=request, dataset=base_dataset, config=cfg)
        if progress_callback is not None:
            progress_callback({"phase": "stress.done", "count": len(stress_metrics)})
        worst_case = self._build_worst_case_summary(regime_metrics=regime_metrics, stress_metrics=stress_metrics)
        if progress_callback is not None:
            progress_callback({"phase": "finalize", "worst_case": worst_case.model_dump(mode="json")})
        return RobustnessReport(
            robustness_id=f"rob_{uuid4().hex[:12]}",
            dataset_version=request.dataset_version,
            strategy_id=request.strategy_id,
            strategy_version=request.strategy_version,
            market=request.market,
            variants=variants,
            table=table,
            summary=summary,
            regime_metrics=regime_metrics,
            stress_metrics=stress_metrics,
            worst_case_summary=worst_case,
            base_spec={
                "cost_multipliers": list(cfg.cost_multipliers),
                "lookback_values": list(cfg.lookback_values) if cfg.lookback_values is not None else None,
                "threshold_values": list(cfg.threshold_values) if cfg.threshold_values is not None else None,
                "rebalance_values": list(cfg.rebalance_values) if cfg.rebalance_values is not None else None,
                "min_variants": cfg.min_variants,
                "max_variants": cfg.max_variants,
                "regime_vol_window": cfg.regime_vol_window,
                "stress_shock_return": cfg.stress_shock_return,
                "stress_vol_multiplier": cfg.stress_vol_multiplier,
                "base_constraints": request.constraints,
                "base_cost_model": request.cost_model.model_dump(mode="json"),
            },
        )

    def _load_dataset(self, dataset_version: str) -> GeneratedDataset | None:
        entry = self.runner.dataset_registry.get_entry(dataset_version)
        if entry is None:
            return None
        return GeneratedDataset.model_validate_json(Path(entry.artifact_path).read_text(encoding="utf-8"))

    def _run_regime_slices(
        self,
        *,
        request: BacktestRequest,
        dataset: GeneratedDataset | None,
        config: MetaBacktestConfig,
    ) -> list[RegimeMetric]:
        if dataset is None:
            return []
        detector = RegimeDetector(window=max(5, int(config.regime_vol_window)))
        slices = detector.detect(dataset.market)
        out: list[RegimeMetric] = []
        for regime_id, idxs in slices.items():
            if len(idxs) < 12:
                continue
            sliced = self._slice_dataset(dataset, idxs, suffix=f"regime_{regime_id}")
            ds_entry = self.runner.dataset_registry.register(sliced)
            run_req = request.model_copy(
                update={
                    "dataset_version": ds_entry.dataset_version,
                    "strategy_version": f"{request.strategy_version}__regime_{regime_id}",
                    "evaluation_plan": {
                        **dict(request.evaluation_plan),
                        "meta_variant_id": f"regime_{regime_id}",
                        "meta_group": "regime_slice",
                    },
                },
                deep=True,
            )
            report = self.runner.run(run_req)
            first_ts = sliced.market[0].ts.isoformat() if sliced.market else ""
            last_ts = sliced.market[-1].ts.isoformat() if sliced.market else ""
            out.append(
                RegimeMetric(
                    regime_id=regime_id,
                    label="high_volatility" if regime_id == "high_vol" else "low_volatility",
                    start=first_ts,
                    end=last_ts,
                    bar_count=len(sliced.market),
                    run_id=str(report.run_id),
                    strategy_version=report.strategy_version,
                    dataset_version=ds_entry.dataset_version,
                    metrics=report.metrics,
                )
            )
        return out

    def _run_stress_scenarios(
        self,
        *,
        request: BacktestRequest,
        dataset: GeneratedDataset | None,
        config: MetaBacktestConfig,
    ) -> list[StressMetric]:
        if dataset is None or not self._is_mock_dataset(dataset):
            return []
        scenarios = [
            {
                "stress_id": "shock_once",
                "scenario": "single_day_return_shock",
                "params": {"shock_return": config.stress_shock_return},
                "dataset": self._shock_once_dataset(dataset, shock_return=config.stress_shock_return),
            },
            {
                "stress_id": "vol_x2",
                "scenario": "volatility_multiplier",
                "params": {"vol_multiplier": config.stress_vol_multiplier},
                "dataset": self._vol_multiplier_dataset(dataset, multiplier=config.stress_vol_multiplier),
            },
        ]
        out: list[StressMetric] = []
        for item in scenarios:
            stressed: GeneratedDataset = item["dataset"]
            ds_entry = self.runner.dataset_registry.register(stressed)
            run_req = request.model_copy(
                update={
                    "dataset_version": ds_entry.dataset_version,
                    "strategy_version": f"{request.strategy_version}__{item['stress_id']}",
                    "evaluation_plan": {
                        **dict(request.evaluation_plan),
                        "meta_variant_id": str(item["stress_id"]),
                        "meta_group": "stress_scenario",
                    },
                },
                deep=True,
            )
            report = self.runner.run(run_req)
            out.append(
                StressMetric(
                    stress_id=str(item["stress_id"]),
                    scenario=str(item["scenario"]),
                    run_id=str(report.run_id),
                    strategy_version=report.strategy_version,
                    dataset_version=ds_entry.dataset_version,
                    params={str(k): float(v) if isinstance(v, (int, float)) else str(v) for k, v in dict(item["params"]).items()},
                    metrics=report.metrics,
                )
            )
        return out

    def _build_worst_case_summary(
        self,
        *,
        regime_metrics: list[RegimeMetric],
        stress_metrics: list[StressMetric],
    ) -> WorstCaseSummary:
        rows: list[tuple[str, str, str, dict[str, float | int | str]]] = []
        rows.extend(("regime", row.regime_id, row.run_id, row.metrics) for row in regime_metrics)
        rows.extend(("stress", row.stress_id, row.run_id, row.metrics) for row in stress_metrics)
        if not rows:
            return WorstCaseSummary(explanation="No regime/stress scenarios executed.")

        def _score(metrics: dict[str, float | int | str]) -> tuple[float, float, float]:
            sharpe = self._metric(metrics, "sharpe")
            mdd = self._metric(metrics, "max_drawdown")
            ret = self._metric(metrics, "total_return")
            return (sharpe, -mdd, ret)

        source_type, scenario_id, run_id, metrics = min(rows, key=lambda row: _score(row[3]))
        sharpe = self._metric(metrics, "sharpe")
        mdd = self._metric(metrics, "max_drawdown")
        ret = self._metric(metrics, "total_return")
        return WorstCaseSummary(
            source_type=source_type,
            scenario_id=scenario_id,
            run_id=run_id,
            sharpe=round(sharpe, 6),
            max_drawdown=round(mdd, 6),
            total_return=round(ret, 6),
            explanation=(
                f"Worst case from {source_type} scenario '{scenario_id}' "
                f"(Sharpe={sharpe:.4f}, MDD={mdd:.4f}, Return={ret:.4f})."
            ),
        )

    def _slice_dataset(self, dataset: GeneratedDataset, indices: list[int], *, suffix: str) -> GeneratedDataset:
        selected = [dataset.market[idx] for idx in sorted(set(indices)) if 0 <= idx < len(dataset.market)]
        copied = dataset.model_copy(deep=True)
        copied.market = selected
        copied.dataset_id = f"{dataset.dataset_id}_{suffix}"
        copied.dataset_version = f"{dataset.dataset_version}_{suffix}_{uuid4().hex[:8]}"
        copied.generation_config = {
            **dict(dataset.generation_config),
            "derived_from": dataset.dataset_version,
            "slice_suffix": suffix,
            "slice_size": len(selected),
        }
        return copied

    def _shock_once_dataset(self, dataset: GeneratedDataset, *, shock_return: float) -> GeneratedDataset:
        copied = dataset.model_copy(deep=True)
        bars = copied.market
        if len(bars) < 3:
            copied.dataset_id = f"{dataset.dataset_id}_shock"
            copied.dataset_version = f"{dataset.dataset_version}_shock_{uuid4().hex[:8]}"
            return copied
        idx = max(1, int(len(bars) * 0.55))
        prev_close = bars[idx - 1].close
        new_close = max(0.01, prev_close * (1.0 + shock_return))
        bars[idx].open = prev_close
        bars[idx].close = new_close
        bars[idx].high = max(prev_close, new_close) * 1.01
        bars[idx].low = min(prev_close, new_close) * 0.99
        bars[idx].spread_bps = max(bars[idx].spread_bps, 25.0)
        copied.dataset_id = f"{dataset.dataset_id}_shock_once"
        copied.dataset_version = f"{dataset.dataset_version}_shock_once_{uuid4().hex[:8]}"
        copied.generation_config = {
            **dict(dataset.generation_config),
            "derived_from": dataset.dataset_version,
            "stress": "shock_once",
            "shock_return": shock_return,
        }
        return copied

    def _vol_multiplier_dataset(self, dataset: GeneratedDataset, *, multiplier: float) -> GeneratedDataset:
        copied = dataset.model_copy(deep=True)
        bars = copied.market
        if len(bars) < 3:
            copied.dataset_id = f"{dataset.dataset_id}_vol_mult"
            copied.dataset_version = f"{dataset.dataset_version}_vol_mult_{uuid4().hex[:8]}"
            return copied
        mult = max(1.0, float(multiplier))
        prev_close = bars[0].close
        for idx in range(1, len(bars)):
            base_ret = (bars[idx].close / bars[idx - 1].close) - 1.0 if bars[idx - 1].close > 0 else 0.0
            stressed_ret = base_ret * mult
            next_close = max(0.01, prev_close * (1.0 + stressed_ret))
            bars[idx].open = prev_close
            bars[idx].close = next_close
            bars[idx].high = max(bars[idx].high, max(prev_close, next_close) * (1.0 + 0.01 * mult))
            bars[idx].low = min(bars[idx].low, min(prev_close, next_close) * max(0.7, 1.0 - 0.01 * mult))
            bars[idx].spread_bps = max(bars[idx].spread_bps, 10.0 * mult)
            prev_close = next_close
        copied.dataset_id = f"{dataset.dataset_id}_volx{mult:.2f}"
        copied.dataset_version = f"{dataset.dataset_version}_volx{mult:.2f}_{uuid4().hex[:8]}".replace(".", "_")
        copied.generation_config = {
            **dict(dataset.generation_config),
            "derived_from": dataset.dataset_version,
            "stress": "vol_multiplier",
            "vol_multiplier": mult,
        }
        return copied

    def _is_mock_dataset(self, dataset: GeneratedDataset) -> bool:
        dataset_id = str(dataset.dataset_id).lower()
        if "mock" in dataset_id:
            return True
        cfg = dataset.generation_config
        if isinstance(cfg, dict):
            src = str(cfg.get("source", "")).lower()
            if "mock" in src:
                return True
            nested_id = str(cfg.get("dataset_id", "")).lower()
            if "mock" in nested_id:
                return True
            # MockDataFactory payload has these synthetic-only knobs.
            mock_keys = {
                "missing_rate_target",
                "delayed_rate_target",
                "backfill_rate_target",
                "outlier_rate_target",
                "high_vol_scale",
            }
            if any(key in cfg for key in mock_keys):
                return True
        return False

    def _build_variant_plans(self, *, request: BacktestRequest, config: MetaBacktestConfig) -> list[dict[str, Any]]:
        constraints = dict(request.constraints)
        base_lookback = int(constraints.get("lookback_days", 20) or 20)
        base_threshold = float(constraints.get("signal_threshold", 0.0) or 0.0)
        base_rebalance = str(constraints.get("rebalance", "weekly")).lower()
        base_commission = float(request.cost_model.commission_bps or 0.0)
        base_slippage = float(request.cost_model.slippage_bps or 0.0)
        plans: list[dict[str, Any]] = []

        for mul in config.cost_multipliers:
            m = max(0.0, float(mul))
            plans.append(
                {
                    "variant_id": f"cost_x{self._fmt_multiplier(m)}",
                    "group": "cost_sensitivity",
                    "scenario": f"commission/slippage x {self._fmt_multiplier(m)}",
                    "strategy_version": f"{request.strategy_version}__cost_x{self._fmt_multiplier(m)}",
                    "commission_bps": base_commission * m,
                    "slippage_bps": base_slippage * m,
                    "constraints": dict(constraints),
                }
            )

        lookback_values = self._normalize_lookbacks(config.lookback_values, base_lookback)
        threshold_values = self._normalize_thresholds(config.threshold_values, base_threshold)
        rebalance_values = self._normalize_rebalances(config.rebalance_values, base_rebalance)
        variant_seq = 1
        max_variants = max(config.min_variants, config.max_variants)
        for rebalance in rebalance_values:
            for lookback in lookback_values:
                for threshold in threshold_values:
                    if (
                        rebalance == base_rebalance
                        and lookback == base_lookback
                        and math.isclose(threshold, base_threshold, rel_tol=0.0, abs_tol=1e-12)
                    ):
                        continue
                    if len(plans) >= max_variants:
                        break
                    c = dict(constraints)
                    c["lookback_days"] = lookback
                    c["signal_threshold"] = round(float(threshold), 6)
                    c["rebalance"] = rebalance
                    plans.append(
                        {
                            "variant_id": f"param_{variant_seq:02d}",
                            "group": "param_perturbation",
                            "scenario": f"lookback={lookback}, rebalance={rebalance}, threshold={threshold:.4f}",
                            "strategy_version": f"{request.strategy_version}__param_{variant_seq:02d}",
                            "commission_bps": base_commission,
                            "slippage_bps": base_slippage,
                            "constraints": c,
                        }
                    )
                    variant_seq += 1
                if len(plans) >= max_variants:
                    break
            if len(plans) >= max_variants:
                break

        if len(plans) < config.min_variants:
            fallback = dict(constraints)
            while len(plans) < config.min_variants:
                fallback["lookback_days"] = max(2, base_lookback + len(plans))
                fallback["signal_threshold"] = round(base_threshold + (len(plans) * 0.001), 6)
                variant_id = f"param_fill_{len(plans) + 1:02d}"
                plans.append(
                    {
                        "variant_id": variant_id,
                        "group": "param_perturbation",
                        "scenario": "fallback perturbation",
                        "strategy_version": f"{request.strategy_version}__{variant_id}",
                        "commission_bps": base_commission,
                        "slippage_bps": base_slippage,
                        "constraints": dict(fallback),
                    }
                )
        return plans

    def _build_summary(self, variants: list[RobustnessVariant]) -> RobustnessSummary:
        rows = variants or []
        sharpe_values = [self._metric(row.metrics, "sharpe") for row in rows]
        mdd_values = [self._metric(row.metrics, "max_drawdown") for row in rows]
        ret_values = [self._metric(row.metrics, "total_return") for row in rows]
        sharpe_mean = statistics.fmean(sharpe_values) if sharpe_values else 0.0
        sharpe_std = statistics.pstdev(sharpe_values) if len(sharpe_values) > 1 else 0.0
        mdd_worst = max(mdd_values) if mdd_values else 0.0
        ret_worst = min(ret_values) if ret_values else 0.0

        best_variant_id = ""
        worst_variant_id = ""
        if rows:
            best_variant_id = max(rows, key=lambda row: self._metric(row.metrics, "sharpe")).variant_id
            worst_variant_id = min(rows, key=lambda row: self._metric(row.metrics, "sharpe")).variant_id

        cost_base = next((row for row in rows if row.variant_id == "cost_x1"), None)
        cost_double = next((row for row in rows if row.variant_id == "cost_x2"), None)
        cost_double_impact: dict[str, float | str] = {}
        if cost_base is not None and cost_double is not None:
            cost_double_impact = {
                "baseline_variant_id": cost_base.variant_id,
                "double_cost_variant_id": cost_double.variant_id,
                "sharpe_delta": round(
                    self._metric(cost_double.metrics, "sharpe") - self._metric(cost_base.metrics, "sharpe"),
                    6,
                ),
                "max_drawdown_delta": round(
                    self._metric(cost_double.metrics, "max_drawdown") - self._metric(cost_base.metrics, "max_drawdown"),
                    6,
                ),
                "total_return_delta": round(
                    self._metric(cost_double.metrics, "total_return") - self._metric(cost_base.metrics, "total_return"),
                    6,
                ),
                "cost_drag_delta": round(
                    self._metric(cost_double.metrics, "cost_drag") - self._metric(cost_base.metrics, "cost_drag"),
                    6,
                ),
            }

        sharpe_penalty = max(0.0, sharpe_std) * 30.0
        mdd_penalty = max(0.0, mdd_worst) * 100.0
        stability_score = max(0.0, min(100.0, 100.0 - sharpe_penalty - mdd_penalty))

        return RobustnessSummary(
            variant_count=len(rows),
            sharpe_mean=round(sharpe_mean, 6),
            sharpe_std=round(sharpe_std, 6),
            mdd_worst_case=round(mdd_worst, 6),
            total_return_worst_case=round(ret_worst, 6),
            stability_score=round(stability_score, 6),
            best_variant_id=best_variant_id,
            worst_variant_id=worst_variant_id,
            cost_double_impact=cost_double_impact,
        )

    def _normalize_lookbacks(self, values: tuple[int, ...] | None, base: int) -> list[int]:
        if values is None:
            values = (max(2, round(base * 0.75)), base, min(252, round(base * 1.25)))
        out = sorted({max(2, int(value)) for value in values})
        return out or [max(2, base)]

    def _normalize_thresholds(self, values: tuple[float, ...] | None, base: float) -> list[float]:
        if values is None:
            values = (round(base - 0.005, 6), round(base, 6), round(base + 0.005, 6))
        out = sorted({round(float(value), 6) for value in values})
        return out or [round(base, 6)]

    def _normalize_rebalances(self, values: tuple[str, ...] | None, base: str) -> list[str]:
        allowed = {"daily", "weekly", "biweekly", "monthly"}
        if values is None:
            alt = "daily" if base != "daily" else "weekly"
            values = (base, alt)
        out: list[str] = []
        for value in values:
            key = str(value).strip().lower()
            if key not in allowed:
                continue
            if key not in out:
                out.append(key)
        return out or [base if base in allowed else "weekly"]

    def _metric(self, metrics: dict[str, float | int | str], key: str) -> float:
        value = metrics.get(key)
        return float(value) if isinstance(value, (int, float)) else 0.0

    def _fmt_multiplier(self, value: float) -> str:
        if math.isclose(value, round(value), rel_tol=0.0, abs_tol=1e-9):
            return str(int(round(value)))
        return f"{value:.2f}".rstrip("0").rstrip(".")


class RegimeDetector:
    def __init__(self, window: int = 20) -> None:
        self.window = max(5, int(window))

    def detect(self, bars: list[OHLCVBar]) -> dict[str, list[int]]:
        if not bars:
            return {"low_vol": [], "high_vol": []}
        returns = self._returns([bar.close for bar in bars])
        vol_rows: list[float] = []
        for idx in range(len(returns)):
            start = max(0, idx - self.window + 1)
            seg = returns[start : idx + 1]
            vol_rows.append(statistics.pstdev(seg) if len(seg) > 1 else 0.0)
        med = statistics.median(vol_rows) if vol_rows else 0.0
        low = [idx for idx, vol in enumerate(vol_rows) if vol <= med]
        high = [idx for idx, vol in enumerate(vol_rows) if vol > med]
        if not low or not high:
            half = max(1, len(bars) // 2)
            low = list(range(half))
            high = list(range(half, len(bars)))
        return {"low_vol": low, "high_vol": high}

    def _returns(self, closes: list[float]) -> list[float]:
        out: list[float] = []
        for idx, value in enumerate(closes):
            if idx == 0 or closes[idx - 1] <= 0:
                out.append(0.0)
            else:
                out.append((value / closes[idx - 1]) - 1.0)
        return out
