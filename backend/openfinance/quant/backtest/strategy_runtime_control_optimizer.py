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


class StrategyRuntimeRejectedOrder(BaseModel):
    time: str | None = None
    instrument: str | None = None
    side: str | None = None
    qty: float | None = None
    reason: str | None = None
    reason_code: str | None = None
    user_friendly_msg: str | None = None
    reason_msg: str | None = None


class StrategyRuntimeOptimizerDiagnostic(BaseModel):
    time: str | None = None
    optimizer: str | None = None
    symbol: str | None = None
    signal: float | None = None
    raw_target_exposure: float | None = None
    optimized_weight: float | None = None
    gross_target: float | None = None
    budget_deviation_l1: float | None = None
    asset_count: int = 0


class StrategyRuntimeCircuitBreakerInterval(BaseModel):
    start: str | None = None
    end: str | None = None
    reason: str | None = None


class StrategyRuntimeBudgetDetail(BaseModel):
    mean_l1: float | None = None
    max_l1: float | None = None
    observations: int = 0
    latest_time: str | None = None
    latest_deviation_l1: float | None = None
    latest_target_budget: dict[str, float] = Field(default_factory=dict)
    latest_achieved_budget: dict[str, float] = Field(default_factory=dict)


class StrategyRuntimeRiskContributionPoint(BaseModel):
    time: str | None = None
    deviation_l1: float | None = None
    target_budget: dict[str, float] = Field(default_factory=dict)
    achieved_budget: dict[str, float] = Field(default_factory=dict)
    weights: dict[str, float] = Field(default_factory=dict)


class StrategyRuntimeControlOptimizerDetails(BaseModel):
    schema_version: str = "strategy_runtime_control_optimizer.v1"
    detail_object: Literal["BacktestReport", "MarketCompareRow", "RobustnessVariant", "RestoreReportHeader"] = "BacktestReport"
    rejected_orders: list[StrategyRuntimeRejectedOrder] = Field(default_factory=list)
    optimizer_diagnostics: list[StrategyRuntimeOptimizerDiagnostic] = Field(default_factory=list)
    circuit_breaker_intervals: list[StrategyRuntimeCircuitBreakerInterval] = Field(default_factory=list)
    budget_detail: StrategyRuntimeBudgetDetail = Field(default_factory=StrategyRuntimeBudgetDetail)
    risk_contribution_points: list[StrategyRuntimeRiskContributionPoint] = Field(default_factory=list)
    summary: str = ""


def parse_strategy_runtime_control_optimizer_details(
    raw: StrategyRuntimeControlOptimizerDetails | dict[str, Any] | None,
) -> StrategyRuntimeControlOptimizerDetails | None:
    if raw is None:
        return None
    if isinstance(raw, StrategyRuntimeControlOptimizerDetails):
        return raw
    if not isinstance(raw, dict):
        return None
    try:
        return StrategyRuntimeControlOptimizerDetails.model_validate(raw)
    except ValidationError:
        return None


def resolve_strategy_runtime_control_optimizer_details(
    *,
    detail_object: Literal["BacktestReport", "MarketCompareRow", "RobustnessVariant", "RestoreReportHeader"],
    details: StrategyRuntimeControlOptimizerDetails | dict[str, Any] | None,
    diagnostics: dict[str, Any] | None,
) -> StrategyRuntimeControlOptimizerDetails:
    parsed = parse_strategy_runtime_control_optimizer_details(details)
    if parsed is not None and parsed.detail_object == detail_object:
        return parsed
    return build_strategy_runtime_control_optimizer_details(
        detail_object=detail_object,
        diagnostics=diagnostics,
    )


def _build_rejected_orders(rows: Any) -> list[StrategyRuntimeRejectedOrder]:
    if not isinstance(rows, list):
        return []
    out: list[StrategyRuntimeRejectedOrder] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        reason = str(row.get("reason") or row.get("reason_code") or "").strip()
        if not reason:
            continue
        out.append(
            StrategyRuntimeRejectedOrder(
                time=str(row.get("time") or "").strip() or None,
                instrument=str(row.get("instrument") or "").strip() or None,
                side=str(row.get("side") or "").strip() or None,
                qty=_to_float(row.get("qty")),
                reason=str(row.get("reason") or "").strip() or None,
                reason_code=str(row.get("reason_code") or "").strip() or None,
                user_friendly_msg=str(row.get("user_friendly_msg") or "").strip() or None,
                reason_msg=str(row.get("reason_msg") or "").strip() or None,
            )
        )
    return out


def _build_optimizer_diagnostics(rows: Any) -> list[StrategyRuntimeOptimizerDiagnostic]:
    if not isinstance(rows, list):
        return []
    out: list[StrategyRuntimeOptimizerDiagnostic] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        optimizer = str(row.get("optimizer") or "").strip()
        if not optimizer:
            continue
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        assets = details.get("assets") if isinstance(details.get("assets"), list) else []
        out.append(
            StrategyRuntimeOptimizerDiagnostic(
                time=str(row.get("time") or "").strip() or None,
                optimizer=optimizer,
                symbol=str(row.get("symbol") or "").strip() or None,
                signal=_to_float(row.get("signal")),
                raw_target_exposure=_to_float(row.get("raw_target_exposure")),
                optimized_weight=_to_float(row.get("optimized_weight")),
                gross_target=_to_float(row.get("gross_target")),
                budget_deviation_l1=_to_float(details.get("budget_deviation_l1")),
                asset_count=len(assets),
            )
        )
    return out


def _build_circuit_breaker_intervals(rows: Any) -> list[StrategyRuntimeCircuitBreakerInterval]:
    if not isinstance(rows, list):
        return []
    return [
        StrategyRuntimeCircuitBreakerInterval(
            start=str(row.get("start") or "").strip() or None,
            end=str(row.get("end") or "").strip() or None,
            reason=str(row.get("reason") or "").strip() or None,
        )
        for row in rows
        if isinstance(row, dict) and str(row.get("start") or row.get("reason") or "").strip()
    ]


def _build_risk_contribution_points(rows: Any) -> list[StrategyRuntimeRiskContributionPoint]:
    if not isinstance(rows, list):
        return []
    out: list[StrategyRuntimeRiskContributionPoint] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            StrategyRuntimeRiskContributionPoint(
                time=str(row.get("time") or "").strip() or None,
                deviation_l1=_to_float(row.get("deviation_l1")),
                target_budget=_typed_float_map(row.get("target_budget")),
                achieved_budget=_typed_float_map(row.get("achieved_budget")),
                weights=_typed_float_map(row.get("weights")),
            )
        )
    return out


def build_strategy_runtime_control_optimizer_details(
    *,
    detail_object: Literal["BacktestReport", "MarketCompareRow", "RobustnessVariant", "RestoreReportHeader"],
    diagnostics: dict[str, Any] | None,
) -> StrategyRuntimeControlOptimizerDetails:
    payload = diagnostics if isinstance(diagnostics, dict) else {}
    risk_management = payload.get("risk_management") if isinstance(payload.get("risk_management"), dict) else {}
    circuit_breaker = (
        risk_management.get("circuit_breaker") if isinstance(risk_management.get("circuit_breaker"), dict) else {}
    )
    budget_deviation = payload.get("budget_deviation") if isinstance(payload.get("budget_deviation"), dict) else {}
    risk_contribution_points = _build_risk_contribution_points(payload.get("risk_contribution_ts"))
    latest_point = risk_contribution_points[-1] if risk_contribution_points else None
    budget_detail = StrategyRuntimeBudgetDetail(
        mean_l1=_to_float(budget_deviation.get("mean_l1")),
        max_l1=_to_float(budget_deviation.get("max_l1")),
        observations=_to_int(budget_deviation.get("observations")) or 0,
        latest_time=latest_point.time if latest_point is not None else None,
        latest_deviation_l1=latest_point.deviation_l1 if latest_point is not None else None,
        latest_target_budget=dict(latest_point.target_budget) if latest_point is not None else {},
        latest_achieved_budget=dict(latest_point.achieved_budget) if latest_point is not None else {},
    )
    rejected_orders = _build_rejected_orders(payload.get("rejected_orders"))
    optimizer_diagnostics = _build_optimizer_diagnostics(payload.get("optimizer_diagnostics"))
    circuit_breaker_intervals = _build_circuit_breaker_intervals(circuit_breaker.get("trigger_intervals"))

    summary_parts: list[str] = []
    if rejected_orders:
        summary_parts.append(f"rejected_orders={len(rejected_orders)}")
    if optimizer_diagnostics:
        summary_parts.append(f"optimizer_steps={len(optimizer_diagnostics)}")
        last_optimizer = optimizer_diagnostics[-1].optimizer
        if last_optimizer:
            summary_parts.append(f"last_optimizer={last_optimizer}")
    if circuit_breaker_intervals:
        summary_parts.append(f"circuit_breaker_intervals={len(circuit_breaker_intervals)}")
    if budget_detail.observations:
        summary_parts.append(f"budget_obs={budget_detail.observations}")
    if risk_contribution_points:
        summary_parts.append(f"risk_points={len(risk_contribution_points)}")

    return StrategyRuntimeControlOptimizerDetails(
        detail_object=detail_object,
        rejected_orders=rejected_orders,
        optimizer_diagnostics=optimizer_diagnostics,
        circuit_breaker_intervals=circuit_breaker_intervals,
        budget_detail=budget_detail,
        risk_contribution_points=risk_contribution_points,
        summary="; ".join(summary_parts),
    )
