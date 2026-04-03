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


class StrategyRuntimeRiskAction(BaseModel):
    time: str | None = None
    action: str = ""
    detail: str | None = None


class StrategyRuntimeConstraintAction(BaseModel):
    time: str | None = None
    optimizer: str | None = None
    symbol: str | None = None
    action: str = ""
    detail: str | None = None
    instrument: str | None = None
    sector: str | None = None
    before: float | None = None
    after: float | None = None
    before_gross: float | None = None
    after_gross: float | None = None
    net_before: float | None = None
    net_after: float | None = None


class StrategyRuntimeFailureConditionEvent(BaseModel):
    time: str | None = None
    code: str = ""
    level: str = ""
    message: str = ""
    metric_keys: list[str] = Field(default_factory=list)


class StrategyRuntimeRegimePeriod(BaseModel):
    regime: str = ""
    start: str | None = None
    end: str | None = None
    trigger: str | None = None


class StrategyRuntimeActionRegimeDetails(BaseModel):
    schema_version: str = "strategy_runtime_action_regime.v1"
    detail_object: Literal["BacktestReport", "MarketCompareRow", "RobustnessVariant", "RestoreReportHeader"] = "BacktestReport"
    risk_actions: list[StrategyRuntimeRiskAction] = Field(default_factory=list)
    constraint_actions: list[StrategyRuntimeConstraintAction] = Field(default_factory=list)
    failure_condition_events: list[StrategyRuntimeFailureConditionEvent] = Field(default_factory=list)
    regime_periods: list[StrategyRuntimeRegimePeriod] = Field(default_factory=list)
    summary: str = ""


def parse_strategy_runtime_action_regime_details(
    raw: StrategyRuntimeActionRegimeDetails | dict[str, Any] | None,
) -> StrategyRuntimeActionRegimeDetails | None:
    if raw is None:
        return None
    if isinstance(raw, StrategyRuntimeActionRegimeDetails):
        return raw
    if not isinstance(raw, dict):
        return None
    try:
        return StrategyRuntimeActionRegimeDetails.model_validate(raw)
    except ValidationError:
        return None


def resolve_strategy_runtime_action_regime_details(
    *,
    detail_object: Literal["BacktestReport", "MarketCompareRow", "RobustnessVariant", "RestoreReportHeader"],
    details: StrategyRuntimeActionRegimeDetails | dict[str, Any] | None,
    diagnostics: dict[str, Any] | None,
) -> StrategyRuntimeActionRegimeDetails:
    parsed = parse_strategy_runtime_action_regime_details(details)
    if parsed is not None and parsed.detail_object == detail_object:
        return parsed
    return build_strategy_runtime_action_regime_details(
        detail_object=detail_object,
        diagnostics=diagnostics,
    )


def _build_risk_actions(rows: Any) -> list[StrategyRuntimeRiskAction]:
    if not isinstance(rows, list):
        return []
    return [
        StrategyRuntimeRiskAction(
            time=str(row.get("time") or "").strip() or None,
            action=str(row.get("action") or "").strip(),
            detail=str(row.get("detail") or "").strip() or None,
        )
        for row in rows
        if isinstance(row, dict) and str(row.get("action") or "").strip()
    ]


def _build_constraint_actions(rows: Any) -> list[StrategyRuntimeConstraintAction]:
    if not isinstance(rows, list):
        return []
    return [
        StrategyRuntimeConstraintAction(
            time=str(row.get("time") or "").strip() or None,
            optimizer=str(row.get("optimizer") or "").strip() or None,
            symbol=str(row.get("symbol") or "").strip() or None,
            action=str(row.get("action") or "").strip(),
            detail=str(row.get("detail") or "").strip() or None,
            instrument=str(row.get("instrument") or "").strip() or None,
            sector=str(row.get("sector") or "").strip() or None,
            before=_to_float(row.get("before")),
            after=_to_float(row.get("after")),
            before_gross=_to_float(row.get("before_gross")),
            after_gross=_to_float(row.get("after_gross")),
            net_before=_to_float(row.get("net_before")),
            net_after=_to_float(row.get("net_after")),
        )
        for row in rows
        if isinstance(row, dict) and str(row.get("action") or "").strip()
    ]


def _build_failure_condition_events(rows: Any) -> list[StrategyRuntimeFailureConditionEvent]:
    if not isinstance(rows, list):
        return []
    out: list[StrategyRuntimeFailureConditionEvent] = []
    for row in rows:
        if not isinstance(row, dict) or not str(row.get("code") or "").strip():
            continue
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        out.append(
            StrategyRuntimeFailureConditionEvent(
                time=str(row.get("time") or "").strip() or None,
                code=str(row.get("code") or "").strip(),
                level=str(row.get("level") or "").strip(),
                message=str(row.get("message") or "").strip(),
                metric_keys=sorted(str(key) for key in metrics.keys()),
            )
        )
    return out


def _build_regime_periods(rows: Any) -> list[StrategyRuntimeRegimePeriod]:
    if not isinstance(rows, list):
        return []
    return [
        StrategyRuntimeRegimePeriod(
            regime=str(row.get("regime") or "").strip(),
            start=str(row.get("start") or "").strip() or None,
            end=str(row.get("end") or "").strip() or None,
            trigger=str(row.get("trigger") or "").strip() or None,
        )
        for row in rows
        if isinstance(row, dict) and str(row.get("regime") or "").strip()
    ]


def build_strategy_runtime_action_regime_details(
    *,
    detail_object: Literal["BacktestReport", "MarketCompareRow", "RobustnessVariant", "RestoreReportHeader"],
    diagnostics: dict[str, Any] | None,
) -> StrategyRuntimeActionRegimeDetails:
    payload = diagnostics if isinstance(diagnostics, dict) else {}
    failure_checks = payload.get("failure_condition_checks") if isinstance(payload.get("failure_condition_checks"), dict) else {}
    risk_actions = _build_risk_actions(payload.get("risk_actions"))
    constraint_actions = _build_constraint_actions(payload.get("constraint_actions"))
    failure_events = _build_failure_condition_events(failure_checks.get("events"))
    regime_periods = _build_regime_periods(payload.get("regime_periods"))

    summary_parts: list[str] = []
    if risk_actions:
        summary_parts.append(f"risk_actions={len(risk_actions)}")
    if constraint_actions:
        summary_parts.append(f"constraint_actions={len(constraint_actions)}")
    if failure_events:
        summary_parts.append(f"failure_events={len(failure_events)}")
    if regime_periods:
        summary_parts.append(f"regime_periods={len(regime_periods)}")
    if risk_actions:
        summary_parts.append(f"last_risk_action={risk_actions[-1].action}")

    return StrategyRuntimeActionRegimeDetails(
        detail_object=detail_object,
        risk_actions=risk_actions,
        constraint_actions=constraint_actions,
        failure_condition_events=failure_events,
        regime_periods=regime_periods,
        summary="; ".join(summary_parts),
    )
