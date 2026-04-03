from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from openfinance.quant.backtest.strategy_trace import StrategyTraceArtifact, parse_strategy_trace_artifact


class StrategyRuntimeMetricSnapshot(BaseModel):
    total_return: float | None = None
    sharpe: float | None = None
    max_drawdown: float | None = None
    volatility: float | None = None
    trade_count: int | None = None
    turnover: float | None = None
    cost_drag: float | None = None
    reject_count: int | None = None
    risk_scale: float | None = None


class StrategyRuntimeOutcomeSummary(BaseModel):
    schema_version: str = "strategy_runtime_outcome_summary.v1"
    summary_object: Literal["BacktestReport", "MarketCompareRow", "RestoreReportHeader", "RobustnessBase"] = "BacktestReport"
    run_id: str | None = None
    dataset_version: str = ""
    market: str = ""
    strategy_version: str = ""
    metrics: StrategyRuntimeMetricSnapshot = Field(default_factory=StrategyRuntimeMetricSnapshot)
    compile_ready: bool | None = None
    factor_lineage_count: int = 0
    evidence_ref_count: int = 0
    warning_count: int = 0
    highest_warning_severity: str | None = None
    summary: str = ""


class StrategyCompareOutcomeSummary(BaseModel):
    schema_version: str = "strategy_compare_outcome_summary.v1"
    summary_object: Literal["MultiMarketCompareResponse"] = "MultiMarketCompareResponse"
    compare_id: str
    baseline_market: str
    market_count: int
    warning_count: int = 0
    best_market_by_sharpe: str | None = None
    worst_market_by_drawdown: str | None = None
    rows: list[StrategyRuntimeOutcomeSummary] = Field(default_factory=list)
    summary: str = ""


class StrategyRobustnessOutcomeSummary(BaseModel):
    schema_version: str = "strategy_robustness_outcome_summary.v1"
    summary_object: Literal["RobustnessReport"] = "RobustnessReport"
    robustness_id: str
    market: str
    variant_count: int
    sharpe_std: float
    mdd_worst_case: float
    stability_score: float
    worst_case_source_type: str | None = None
    worst_case_run_id: str | None = None
    base_runtime_summary: StrategyRuntimeOutcomeSummary | None = None
    summary: str = ""


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def parse_strategy_runtime_outcome_summary(
    raw: StrategyRuntimeOutcomeSummary | dict[str, Any] | None,
) -> StrategyRuntimeOutcomeSummary | None:
    if raw is None:
        return None
    if isinstance(raw, StrategyRuntimeOutcomeSummary):
        return raw
    if not isinstance(raw, dict):
        return None
    try:
        return StrategyRuntimeOutcomeSummary.model_validate(raw)
    except ValidationError:
        return None


def build_strategy_runtime_outcome_summary(
    *,
    summary_object: Literal["BacktestReport", "MarketCompareRow", "RestoreReportHeader", "RobustnessBase"],
    run_id: str | None,
    dataset_version: str,
    market: str,
    strategy_version: str,
    metrics: dict[str, Any],
    strategy_trace: StrategyTraceArtifact | dict[str, Any] | None = None,
    warning_count: int = 0,
    highest_warning_severity: str | None = None,
) -> StrategyRuntimeOutcomeSummary:
    parsed_trace = parse_strategy_trace_artifact(strategy_trace)
    compile_ready = None
    factor_lineage_count = 0
    evidence_ref_count = 0
    if parsed_trace is not None:
        if parsed_trace.strategy_compilation is not None:
            compile_ready = parsed_trace.strategy_compilation.compile_ready
        elif parsed_trace.strategy_validation is not None:
            compile_ready = parsed_trace.strategy_validation.compile_ready
        factor_lineage_count = len(parsed_trace.factor_lineage.factor_versions)
        evidence_ref_count = len(parsed_trace.evaluation_plan.evidence_refs) if parsed_trace.evaluation_plan else 0

    snapshot = StrategyRuntimeMetricSnapshot(
        total_return=_to_float(metrics.get("total_return")),
        sharpe=_to_float(metrics.get("sharpe")),
        max_drawdown=_to_float(metrics.get("max_drawdown")),
        volatility=_to_float(metrics.get("volatility")),
        trade_count=_to_int(metrics.get("trade_count")),
        turnover=_to_float(metrics.get("turnover")),
        cost_drag=_to_float(metrics.get("cost_drag")),
        reject_count=_to_int(metrics.get("reject_count")),
        risk_scale=_to_float(metrics.get("risk_scale")),
    )

    summary_parts = [f"market={market}"]
    if snapshot.sharpe is not None:
        summary_parts.append(f"sharpe={snapshot.sharpe:.4f}")
    if snapshot.max_drawdown is not None:
        summary_parts.append(f"max_drawdown={snapshot.max_drawdown:.4f}")
    if snapshot.trade_count is not None:
        summary_parts.append(f"trade_count={snapshot.trade_count}")
    if compile_ready is not None:
        summary_parts.append(f"compile_ready={'true' if compile_ready else 'false'}")
    if factor_lineage_count:
        summary_parts.append(f"factor_lineage={factor_lineage_count}")
    if warning_count:
        summary_parts.append(f"warnings={warning_count}")

    return StrategyRuntimeOutcomeSummary(
        summary_object=summary_object,
        run_id=run_id,
        dataset_version=dataset_version,
        market=market,
        strategy_version=strategy_version,
        metrics=snapshot,
        compile_ready=compile_ready,
        factor_lineage_count=factor_lineage_count,
        evidence_ref_count=evidence_ref_count,
        warning_count=warning_count,
        highest_warning_severity=highest_warning_severity,
        summary="; ".join(summary_parts),
    )


def build_strategy_compare_outcome_summary(
    *,
    compare_id: str,
    baseline_market: str,
    rows: list[StrategyRuntimeOutcomeSummary],
) -> StrategyCompareOutcomeSummary:
    best_market_by_sharpe: str | None = None
    worst_market_by_drawdown: str | None = None
    sharpe_rows = [row for row in rows if row.metrics.sharpe is not None]
    drawdown_rows = [row for row in rows if row.metrics.max_drawdown is not None]
    if sharpe_rows:
        best_market_by_sharpe = max(sharpe_rows, key=lambda row: row.metrics.sharpe or float("-inf")).market
    if drawdown_rows:
        worst_market_by_drawdown = min(
            drawdown_rows,
            key=lambda row: row.metrics.max_drawdown if row.metrics.max_drawdown is not None else float("inf"),
        ).market
    warning_count = sum(max(0, int(row.warning_count or 0)) for row in rows)
    summary_parts = [f"markets={len(rows)}", f"baseline={baseline_market}"]
    if best_market_by_sharpe:
        summary_parts.append(f"best_sharpe={best_market_by_sharpe}")
    if worst_market_by_drawdown:
        summary_parts.append(f"worst_mdd={worst_market_by_drawdown}")
    if warning_count:
        summary_parts.append(f"warnings={warning_count}")
    return StrategyCompareOutcomeSummary(
        compare_id=compare_id,
        baseline_market=baseline_market,
        market_count=len(rows),
        warning_count=warning_count,
        best_market_by_sharpe=best_market_by_sharpe,
        worst_market_by_drawdown=worst_market_by_drawdown,
        rows=rows,
        summary="; ".join(summary_parts),
    )


def build_strategy_robustness_outcome_summary(
    *,
    robustness_id: str,
    market: str,
    variant_count: int,
    sharpe_std: float,
    mdd_worst_case: float,
    stability_score: float,
    worst_case_source_type: str | None = None,
    worst_case_run_id: str | None = None,
    base_runtime_summary: StrategyRuntimeOutcomeSummary | None = None,
) -> StrategyRobustnessOutcomeSummary:
    summary_parts = [
        f"variants={variant_count}",
        f"stability={stability_score:.4f}",
        f"sharpe_std={sharpe_std:.4f}",
        f"worst_mdd={mdd_worst_case:.4f}",
    ]
    if worst_case_source_type:
        summary_parts.append(f"worst_case={worst_case_source_type}")
    return StrategyRobustnessOutcomeSummary(
        robustness_id=robustness_id,
        market=market,
        variant_count=variant_count,
        sharpe_std=sharpe_std,
        mdd_worst_case=mdd_worst_case,
        stability_score=stability_score,
        worst_case_source_type=worst_case_source_type,
        worst_case_run_id=worst_case_run_id,
        base_runtime_summary=base_runtime_summary,
        summary="; ".join(summary_parts),
    )
