from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
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


def _to_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    return None


def _typed_float_map(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, float] = {}
    for key, raw in value.items():
        number = _to_float(raw)
        if number is None:
            continue
        text = str(key).strip()
        if not text:
            continue
        out[text] = number
    return out


def _typed_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for raw in value:
        text = str(raw or "").strip()
        if not text or text in out:
            continue
        out.append(text)
    return out


def _merged_asset_keys(*maps: Any) -> list[str]:
    out: list[str] = []
    for value in maps:
        if not isinstance(value, dict):
            continue
        for raw_key in value.keys():
            key = str(raw_key or "").strip()
            if not key or key in out:
                continue
            out.append(key)
    return out


def _gap_by_asset(*, target_budget: dict[str, float], achieved_budget: dict[str, float]) -> dict[str, float]:
    keys = sorted(set(target_budget.keys()) | set(achieved_budget.keys()))
    out: dict[str, float] = {}
    for key in keys:
        out[key] = round(float(achieved_budget.get(key, 0.0)) - float(target_budget.get(key, 0.0)), 8)
    return out


class StrategyRuntimeOptimizerStepDeepDetail(BaseModel):
    time: str | None = None
    optimizer: str | None = None
    method: str | None = None
    asset_count: int = 0
    assets: list[str] = Field(default_factory=list)
    budget_deviation_l1: float | None = None
    loss_final: float | None = None
    raw_weights: dict[str, float] = Field(default_factory=dict)
    target_budget: dict[str, float] = Field(default_factory=dict)
    achieved_budget: dict[str, float] = Field(default_factory=dict)
    direction: dict[str, float] = Field(default_factory=dict)
    covariance_asset_count: int = 0


class StrategyRuntimeCircuitBreakerExecutionSupport(BaseModel):
    drawdown: bool | None = None
    consecutive_losses: bool | None = None
    vol_spike: bool | None = None


class StrategyRuntimeCircuitBreakerIntervalState(BaseModel):
    start: str | None = None
    end: str | None = None
    reason: str | None = None
    rule_type: str | None = None
    threshold: float | None = None
    supported: bool | None = None


class StrategyRuntimeCircuitBreakerState(BaseModel):
    enabled: bool | None = None
    rule_type: str | None = None
    threshold: float | None = None
    trigger_count: int = 0
    stop_trading_triggered: bool | None = None
    execution_support: StrategyRuntimeCircuitBreakerExecutionSupport = Field(
        default_factory=StrategyRuntimeCircuitBreakerExecutionSupport
    )
    intervals: list[StrategyRuntimeCircuitBreakerIntervalState] = Field(default_factory=list)


class StrategyRuntimeBudgetBreakdown(BaseModel):
    mean_l1: float | None = None
    max_l1: float | None = None
    observations: int = 0
    latest_time: str | None = None
    latest_deviation_l1: float | None = None
    latest_gap_by_asset: dict[str, float] = Field(default_factory=dict)
    peak_time: str | None = None
    peak_deviation_l1: float | None = None
    peak_gap_by_asset: dict[str, float] = Field(default_factory=dict)


class StrategyRuntimeRiskContributionSnapshot(BaseModel):
    time: str | None = None
    deviation_l1: float | None = None
    target_budget: dict[str, float] = Field(default_factory=dict)
    achieved_budget: dict[str, float] = Field(default_factory=dict)
    weights: dict[str, float] = Field(default_factory=dict)
    gap_by_asset: dict[str, float] = Field(default_factory=dict)


class StrategyRuntimeRiskContributionBreakdown(BaseModel):
    point_count: int = 0
    latest: StrategyRuntimeRiskContributionSnapshot | None = None
    peak: StrategyRuntimeRiskContributionSnapshot | None = None


class StrategyRuntimeControlActionDeepDetails(BaseModel):
    schema_version: str = "strategy_runtime_control_action_deep.v1"
    detail_object: Literal["BacktestReport", "MarketCompareRow", "RobustnessVariant", "RestoreReportHeader"] = (
        "BacktestReport"
    )
    optimizer_steps: list[StrategyRuntimeOptimizerStepDeepDetail] = Field(default_factory=list)
    circuit_breaker_state: StrategyRuntimeCircuitBreakerState = Field(default_factory=StrategyRuntimeCircuitBreakerState)
    budget_breakdown: StrategyRuntimeBudgetBreakdown = Field(default_factory=StrategyRuntimeBudgetBreakdown)
    risk_contribution_breakdown: StrategyRuntimeRiskContributionBreakdown = Field(
        default_factory=StrategyRuntimeRiskContributionBreakdown
    )
    summary: str = ""


def parse_strategy_runtime_control_action_deep_details(
    raw: StrategyRuntimeControlActionDeepDetails | dict[str, Any] | None,
) -> StrategyRuntimeControlActionDeepDetails | None:
    if raw is None:
        return None
    if isinstance(raw, StrategyRuntimeControlActionDeepDetails):
        return raw
    if not isinstance(raw, dict):
        return None
    try:
        return StrategyRuntimeControlActionDeepDetails.model_validate(raw)
    except ValidationError:
        return None


def resolve_strategy_runtime_control_action_deep_details(
    *,
    detail_object: Literal["BacktestReport", "MarketCompareRow", "RobustnessVariant", "RestoreReportHeader"],
    details: StrategyRuntimeControlActionDeepDetails | dict[str, Any] | None,
    diagnostics: dict[str, Any] | None,
) -> StrategyRuntimeControlActionDeepDetails:
    parsed = parse_strategy_runtime_control_action_deep_details(details)
    if parsed is not None and parsed.detail_object == detail_object:
        return parsed
    return build_strategy_runtime_control_action_deep_details(
        detail_object=detail_object,
        diagnostics=diagnostics,
    )


def _build_optimizer_steps(rows: Any) -> list[StrategyRuntimeOptimizerStepDeepDetail]:
    if not isinstance(rows, list):
        return []
    out: list[StrategyRuntimeOptimizerStepDeepDetail] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        optimizer = str(row.get("optimizer") or "").strip()
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        method = str(details.get("method") or optimizer or "").strip() or None
        target_budget = _typed_float_map(details.get("target_budget"))
        if not target_budget:
            target_budget = _typed_float_map(row.get("risk_budget_vector"))
        achieved_budget = _typed_float_map(details.get("achieved_budget"))
        raw_weights = _typed_float_map(details.get("raw_weights"))
        direction = _typed_float_map(details.get("direction"))
        covariance = row.get("covariance") if isinstance(row.get("covariance"), dict) else {}
        assets = _typed_string_list(details.get("assets"))
        if not assets:
            assets = _merged_asset_keys(
                target_budget,
                achieved_budget,
                raw_weights,
                direction,
                covariance,
            )
        asset_count = len(assets)
        if asset_count == 0:
            asset_count = max(
                len(target_budget),
                len(achieved_budget),
                len(raw_weights),
                len(direction),
                len(covariance),
            )
        if not optimizer and method is None and asset_count == 0:
            continue
        out.append(
            StrategyRuntimeOptimizerStepDeepDetail(
                time=str(row.get("time") or "").strip() or None,
                optimizer=optimizer or None,
                method=method,
                asset_count=asset_count,
                assets=assets,
                budget_deviation_l1=_to_float(details.get("budget_deviation_l1")),
                loss_final=_to_float(details.get("loss_final")),
                raw_weights=raw_weights,
                target_budget=target_budget,
                achieved_budget=achieved_budget,
                direction=direction,
                covariance_asset_count=len(covariance),
            )
        )
    return out


def _build_risk_snapshot(row: Any) -> StrategyRuntimeRiskContributionSnapshot | None:
    if not isinstance(row, dict):
        return None
    target_budget = _typed_float_map(row.get("target_budget"))
    achieved_budget = _typed_float_map(row.get("achieved_budget"))
    weights = _typed_float_map(row.get("weights"))
    deviation_l1 = _to_float(row.get("deviation_l1"))
    if not any([target_budget, achieved_budget, weights, deviation_l1 is not None]):
        return None
    return StrategyRuntimeRiskContributionSnapshot(
        time=str(row.get("time") or "").strip() or None,
        deviation_l1=deviation_l1,
        target_budget=target_budget,
        achieved_budget=achieved_budget,
        weights=weights,
        gap_by_asset=_gap_by_asset(target_budget=target_budget, achieved_budget=achieved_budget),
    )


def _build_risk_contribution_breakdown(rows: Any) -> StrategyRuntimeRiskContributionBreakdown:
    if not isinstance(rows, list):
        return StrategyRuntimeRiskContributionBreakdown()
    snapshots = [snapshot for snapshot in (_build_risk_snapshot(row) for row in rows) if snapshot is not None]
    if not snapshots:
        return StrategyRuntimeRiskContributionBreakdown()
    latest = snapshots[-1]
    peak = max(snapshots, key=lambda item: abs(float(item.deviation_l1 or 0.0)))
    return StrategyRuntimeRiskContributionBreakdown(
        point_count=len(snapshots),
        latest=latest,
        peak=peak,
    )


def _build_circuit_breaker_state(payload: dict[str, Any]) -> StrategyRuntimeCircuitBreakerState:
    risk_management = payload.get("risk_management") if isinstance(payload.get("risk_management"), dict) else {}
    circuit_breaker = (
        risk_management.get("circuit_breaker") if isinstance(risk_management.get("circuit_breaker"), dict) else {}
    )
    rule = circuit_breaker.get("rule") if isinstance(circuit_breaker.get("rule"), dict) else {}
    rule_type = str(rule.get("type") or "").strip() or None
    threshold = _to_float(rule.get("threshold"))
    execution_support_raw = (
        circuit_breaker.get("execution_support") if isinstance(circuit_breaker.get("execution_support"), dict) else {}
    )
    support = StrategyRuntimeCircuitBreakerExecutionSupport(
        drawdown=_to_bool(execution_support_raw.get("drawdown")),
        consecutive_losses=_to_bool(execution_support_raw.get("consecutive_losses")),
        vol_spike=_to_bool(execution_support_raw.get("vol_spike")),
    )
    supported: bool | None = None
    if rule_type == "drawdown":
        supported = support.drawdown
    elif rule_type == "consecutive_losses":
        supported = support.consecutive_losses
    elif rule_type == "vol_spike":
        supported = support.vol_spike
    rows = circuit_breaker.get("trigger_intervals") if isinstance(circuit_breaker.get("trigger_intervals"), list) else []
    intervals = [
        StrategyRuntimeCircuitBreakerIntervalState(
            start=str(row.get("start") or "").strip() or None,
            end=str(row.get("end") or "").strip() or None,
            reason=str(row.get("reason") or "").strip() or None,
            rule_type=rule_type,
            threshold=threshold,
            supported=supported,
        )
        for row in rows
        if isinstance(row, dict) and str(row.get("start") or row.get("reason") or "").strip()
    ]
    return StrategyRuntimeCircuitBreakerState(
        enabled=_to_bool(circuit_breaker.get("enabled")),
        rule_type=rule_type,
        threshold=threshold,
        trigger_count=_to_int(circuit_breaker.get("trigger_count")) or len(intervals),
        stop_trading_triggered=_to_bool(risk_management.get("stop_trading_triggered")),
        execution_support=support,
        intervals=intervals,
    )


def build_strategy_runtime_control_action_deep_details(
    *,
    detail_object: Literal["BacktestReport", "MarketCompareRow", "RobustnessVariant", "RestoreReportHeader"],
    diagnostics: dict[str, Any] | None,
) -> StrategyRuntimeControlActionDeepDetails:
    payload = diagnostics if isinstance(diagnostics, dict) else {}
    optimizer_steps = _build_optimizer_steps(payload.get("optimizer_diagnostics"))
    risk_contribution_breakdown = _build_risk_contribution_breakdown(payload.get("risk_contribution_ts"))
    budget_deviation = payload.get("budget_deviation") if isinstance(payload.get("budget_deviation"), dict) else {}
    latest = risk_contribution_breakdown.latest
    peak = risk_contribution_breakdown.peak
    budget_breakdown = StrategyRuntimeBudgetBreakdown(
        mean_l1=_to_float(budget_deviation.get("mean_l1")),
        max_l1=_to_float(budget_deviation.get("max_l1")),
        observations=_to_int(budget_deviation.get("observations")) or 0,
        latest_time=latest.time if latest is not None else None,
        latest_deviation_l1=latest.deviation_l1 if latest is not None else None,
        latest_gap_by_asset=dict(latest.gap_by_asset) if latest is not None else {},
        peak_time=peak.time if peak is not None else None,
        peak_deviation_l1=peak.deviation_l1 if peak is not None else None,
        peak_gap_by_asset=dict(peak.gap_by_asset) if peak is not None else {},
    )
    circuit_breaker_state = _build_circuit_breaker_state(payload)

    summary_parts: list[str] = []
    if optimizer_steps:
        summary_parts.append(f"optimizer_steps={len(optimizer_steps)}")
        last_method = optimizer_steps[-1].method or optimizer_steps[-1].optimizer
        if last_method:
            summary_parts.append(f"last_method={last_method}")
    if circuit_breaker_state.rule_type:
        rule = f"circuit_breaker={circuit_breaker_state.rule_type}"
        if circuit_breaker_state.threshold is not None:
            rule = f"{rule}@{circuit_breaker_state.threshold}"
        summary_parts.append(rule)
    if budget_breakdown.peak_deviation_l1 is not None:
        summary_parts.append(f"peak_budget_l1={budget_breakdown.peak_deviation_l1}")
    if risk_contribution_breakdown.point_count:
        summary_parts.append(f"risk_points={risk_contribution_breakdown.point_count}")

    return StrategyRuntimeControlActionDeepDetails(
        detail_object=detail_object,
        optimizer_steps=optimizer_steps,
        circuit_breaker_state=circuit_breaker_state,
        budget_breakdown=budget_breakdown,
        risk_contribution_breakdown=risk_contribution_breakdown,
        summary="; ".join(summary_parts),
    )
