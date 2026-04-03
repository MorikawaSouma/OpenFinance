from typing import Any, Mapping, Sequence, Literal

from pydantic import BaseModel, Field


class CircuitBreakerRule(BaseModel):
    type: Literal["consecutive_losses", "drawdown", "vol_spike"] = "drawdown"
    threshold: float = Field(default=0.1, ge=0.0)
    cool_down_days: int = Field(default=5, ge=0)


class CircuitBreakerSpec(BaseModel):
    enabled: bool = True
    rule: CircuitBreakerRule = Field(default_factory=CircuitBreakerRule)


class StrategySpec(BaseModel):
    schema_version: str = "strategy_spec.v1"
    strategy_id: str
    strategy_version: str
    plan_id: str | None = None
    experiment_id: str | None = None
    market: str
    strategy_family: str
    rebalance: str
    lookback_days: int
    signal_threshold: float
    position_sizing: str
    risk_budget: str
    max_position: float
    stop_loss: float
    leverage_limit: float
    factor_weights: dict[str, float] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    circuit_breaker: CircuitBreakerSpec = Field(default_factory=CircuitBreakerSpec)
    failure_regimes: list[str] = Field(default_factory=list)
    rationale: str
    evidence_refs: list[str] = Field(default_factory=list)
    simulation_only: bool = True


def normalize_strategy_circuit_breaker(raw: Any, *, drawdown_threshold: float) -> CircuitBreakerSpec:
    enabled = True
    rule_type: Literal["consecutive_losses", "drawdown", "vol_spike"] = "drawdown"
    threshold = max(0.0, float(drawdown_threshold))
    cool_down_days = 5
    if isinstance(raw, dict):
        if isinstance(raw.get("enabled"), bool):
            enabled = bool(raw.get("enabled"))
        raw_rule = raw.get("rule")
        if isinstance(raw_rule, dict):
            raw_type = str(raw_rule.get("type", "drawdown")).strip().lower()
            if raw_type in {"consecutive_losses", "drawdown", "vol_spike"}:
                rule_type = raw_type  # type: ignore[assignment]
            raw_threshold = raw_rule.get("threshold")
            if isinstance(raw_threshold, (int, float)):
                threshold = max(0.0, float(raw_threshold))
            raw_cool_down = raw_rule.get("cool_down_days")
            if isinstance(raw_cool_down, (int, float)):
                cool_down_days = max(0, int(raw_cool_down))
    return CircuitBreakerSpec(
        enabled=enabled,
        rule=CircuitBreakerRule(
            type=rule_type,
            threshold=threshold,
            cool_down_days=cool_down_days,
        ),
    )


def normalize_strategy_failure_regimes(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return ["range_bound_market", "high_correlation_breakdown", "frequent_gap_moves"]
    rows = [str(item).strip() for item in raw if str(item).strip()]
    if not rows:
        return ["range_bound_market", "high_correlation_breakdown", "frequent_gap_moves"]
    return list(dict.fromkeys(rows))[:8]


def build_strategy_spec_from_constraints(
    *,
    strategy_id: str,
    strategy_version: str,
    market: str,
    constraints: Mapping[str, Any] | None = None,
    rationale: str,
    evidence_refs: Sequence[str] | None = None,
    plan_id: str | None = None,
    experiment_id: str | None = None,
    factor_weights: Mapping[str, float] | None = None,
    simulation_only: bool = True,
) -> StrategySpec:
    rows = dict(constraints or {})
    raw_weights = factor_weights if factor_weights is not None else rows.get("factor_weights")
    normalized_weights = (
        {
            str(key): float(value)
            for key, value in raw_weights.items()
            if isinstance(value, (int, float))
        }
        if isinstance(raw_weights, dict)
        else {}
    )
    drawdown_threshold = float(rows.get("max_drawdown_target", 0.1) or 0.1)
    return StrategySpec(
        strategy_id=str(strategy_id),
        strategy_version=str(strategy_version),
        plan_id=plan_id,
        experiment_id=experiment_id,
        market=str(market or "US").upper(),
        strategy_family=str(rows.get("strategy_family", strategy_id)),
        rebalance=str(rows.get("rebalance", "weekly")),
        lookback_days=int(rows.get("lookback_days", 20) or 20),
        signal_threshold=float(rows.get("signal_threshold", 0.0) or 0.0),
        position_sizing=str(rows.get("position_sizing", "risk_budget")),
        risk_budget=str(rows.get("risk_budget", "vol_target_10pct")),
        max_position=float(rows.get("max_position", 0.12) or 0.12),
        stop_loss=float(rows.get("stop_loss", 0.06) or 0.06),
        leverage_limit=float(rows.get("leverage_limit", 1.0) or 1.0),
        factor_weights=normalized_weights,
        constraints=rows,
        circuit_breaker=normalize_strategy_circuit_breaker(
            rows.get("circuit_breaker"),
            drawdown_threshold=drawdown_threshold,
        ),
        failure_regimes=normalize_strategy_failure_regimes(rows.get("failure_regimes")),
        rationale=str(rationale).strip() or "Derived strategy semantics",
        evidence_refs=[str(ref).strip() for ref in (evidence_refs or []) if str(ref).strip()],
        simulation_only=simulation_only,
    )
