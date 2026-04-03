from typing import Any

from pydantic import BaseModel, Field


class StrategyProposalSpec(BaseModel):
    strategy_family: str = ""
    rebalance: str = "weekly"
    lookback_days: int = Field(default=20, ge=2, le=252)
    signal_threshold: float = 0.0
    position_sizing: str = "risk_budget"
    risk_budget: str = "vol_target_10pct"
    max_position: float = Field(default=0.12, gt=0.0, lt=1.0)
    leverage_limit: float = 1.0
    auto_round_lot: bool = True
    run_time_utc: str = "16:00"


class StrategyDecisionCandidate(BaseModel):
    name: str = ""
    spec: StrategyProposalSpec = Field(default_factory=StrategyProposalSpec)
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    expected_failure_regimes: list[str] = Field(default_factory=list)
    cost_profile: str = ""
    why_not_selected: str = ""


class StrategyDecisionSelected(BaseModel):
    name: str = ""
    spec: StrategyProposalSpec = Field(default_factory=StrategyProposalSpec)
    rationale: str = ""
    tradeoff_summary: str = ""


class StrategyDecision(BaseModel):
    schema_version: str = "strategy_decision.v1"
    candidates: list[StrategyDecisionCandidate] = Field(default_factory=list)
    selected: StrategyDecisionSelected = Field(default_factory=StrategyDecisionSelected)
    llm_mode: str = "rule_fallback"


def parse_strategy_decision(raw: Any) -> StrategyDecision | None:
    if isinstance(raw, StrategyDecision):
        return raw
    if not isinstance(raw, dict) or not raw:
        return None
    try:
        parsed = StrategyDecision.model_validate(raw)
    except ValueError:
        return None
    if not parsed.selected.name and not parsed.candidates:
        return None
    return parsed
