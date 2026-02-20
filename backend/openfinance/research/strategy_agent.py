import json
import re
from typing import Any

from pydantic import BaseModel, Field

from openfinance.llm.provider import LLMProviderRegistry


class StrategyDecisionCandidate(BaseModel):
    name: str
    spec: dict[str, Any] = Field(default_factory=dict)
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    expected_failure_regimes: list[str] = Field(default_factory=list)
    cost_profile: str = ""
    why_not_selected: str = ""


class StrategyDecisionSelected(BaseModel):
    name: str
    spec: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    tradeoff_summary: str = ""


class StrategyDecision(BaseModel):
    candidates: list[StrategyDecisionCandidate] = Field(default_factory=list)
    selected: StrategyDecisionSelected
    llm_mode: str = "rule_fallback"


class StrategyAgent:
    def __init__(self, llm_registry: LLMProviderRegistry) -> None:
        self.llm_registry = llm_registry

    def decide(
        self,
        *,
        question: str,
        market: str,
        research_plan: dict[str, Any],
        factor_health_report: dict[str, Any],
        constraints: dict[str, Any],
        market_rules: dict[str, Any],
        risk_budget: str,
        variant: dict[str, Any],
    ) -> StrategyDecision:
        fallback = self._fallback_decision(
            question=question,
            market=market,
            research_plan=research_plan,
            factor_health_report=factor_health_report,
            constraints=constraints,
            market_rules=market_rules,
            risk_budget=risk_budget,
            variant=variant,
        )
        llm = self.llm_registry.get()
        prompt = (
            "Return strict JSON only.\n"
            "Required output schema:\n"
            "{"
            '"candidates":[{'
            '"name":str,'
            '"spec":object,'
            '"pros":[str],'
            '"cons":[str],'
            '"risks":[str],'
            '"expected_failure_regimes":[str],'
            '"cost_profile":str,'
            '"why_not_selected":str'
            "}],"
            '"selected":{"name":str,"spec":object,"rationale":str,"tradeoff_summary":str}'
            "}\n"
            "At least two candidates are required: Risk Budget and Equal Weight.\n"
            "Focus on trade-offs under market microstructure constraints.\n"
            f"question: {question}\n"
            f"market: {market}\n"
            f"market_rules: {json.dumps(market_rules, ensure_ascii=False)}\n"
            f"constraints: {json.dumps(constraints, ensure_ascii=False)}\n"
            f"risk_budget: {risk_budget}\n"
            f"variant: {json.dumps(variant, ensure_ascii=False)}\n"
            f"factor_health_report: {json.dumps(factor_health_report, ensure_ascii=False)}\n"
            f"fallback_draft: {fallback.model_dump_json(ensure_ascii=False)}"
        )
        response = llm.complete(prompt, max_tokens=680, temperature=0.15)
        payload = self._extract_json(response.content)
        if not isinstance(payload, dict):
            return fallback
        try:
            parsed = StrategyDecision.model_validate(
                {
                    "candidates": payload.get("candidates", []),
                    "selected": payload.get("selected", {}),
                    "llm_mode": response.mode,
                }
            )
        except ValueError:
            return fallback
        if len(parsed.candidates) < 2:
            return fallback
        return parsed

    def _fallback_decision(
        self,
        *,
        question: str,
        market: str,
        research_plan: dict[str, Any],
        factor_health_report: dict[str, Any],
        constraints: dict[str, Any],
        market_rules: dict[str, Any],
        risk_budget: str,
        variant: dict[str, Any],
    ) -> StrategyDecision:
        market_key = str(market).upper()
        t_plus_one = bool(market_rules.get("t_plus_one", False))
        lot_size = float(market_rules.get("lot_size", 1.0) or 1.0)
        is_24x7 = bool(market_rules.get("is_24x7", False))
        oos_gap = float(
            factor_health_report.get(
                "oos_gap",
                abs(float(factor_health_report.get("in_sample_ic_mean", 0.0)) - float(factor_health_report.get("out_sample_ic_mean", 0.0))),
            )
            or 0.0
        )
        turnover = float(factor_health_report.get("turnover_proxy", 0.0) or 0.0)
        coverage = float(factor_health_report.get("coverage", 1.0) or 1.0)
        drawdown_target = float(constraints.get("max_drawdown_target", 0.1) or 0.1)

        base_rebalance = str(variant.get("rebalance", "weekly")).lower()
        base_lookback = int(variant.get("lookback_days", 20) or 20)
        base_threshold = float(variant.get("signal_threshold", 0.0) or 0.0)
        base_max_position = float(variant.get("max_position", 0.12) or 0.12)
        base_family = str(variant.get("strategy_family", "trend"))

        rb_rebalance = base_rebalance
        if market_key == "CN" and base_rebalance in {"intraday", "hourly"}:
            rb_rebalance = "daily"
        ew_rebalance = "weekly" if market_key == "CN" and base_rebalance in {"intraday", "daily"} else base_rebalance

        risk_budget_spec = {
            "strategy_family": base_family,
            "position_sizing": "risk_budget",
            "risk_budget": risk_budget or "vol_target_10pct",
            "rebalance": rb_rebalance,
            "lookback_days": base_lookback,
            "signal_threshold": base_threshold,
            "max_position": round(max(0.05, min(0.3, base_max_position)), 4),
        }
        equal_weight_spec = {
            "strategy_family": base_family,
            "position_sizing": "equal_weight",
            "risk_budget": "equal_weight",
            "rebalance": ew_rebalance,
            "lookback_days": base_lookback,
            "signal_threshold": base_threshold,
            "max_position": round(max(0.05, min(0.25, base_max_position * 0.9)), 4),
        }

        market_risk_hint = (
            "CN T+1 + lot-size/session constraints increase execution drift."
            if market_key == "CN"
            else "US allows more flexible turnover with lower microstructure friction."
        )
        regime_hint = (
            "high-volatility and correlation spikes can break static sizing"
            if drawdown_target <= 0.1 or oos_gap >= 0.03
            else "stable regime but monitor crowding and cost shock"
        )
        equal_weight_rejection = (
            "Not selected because static equal weights cannot react to volatility concentration under current constraints."
        )
        risk_budget_rejection = (
            "Not selected because complexity and estimation noise may outweigh benefit when signal dispersion is stable."
        )

        candidates = [
            StrategyDecisionCandidate(
                name="RiskBudgetAllocator",
                spec=risk_budget_spec,
                pros=[
                    "Controls concentration by targeting risk contribution.",
                    f"Better drawdown discipline under oos_gap={oos_gap:.3f}.",
                    f"Market-aware sizing: {market_risk_hint}",
                ],
                cons=[
                    "Needs covariance/risk estimation each rebalance.",
                    "More moving parts and model risk than equal-weight.",
                ],
                risks=[
                    "Covariance instability during regime breaks.",
                    "Execution slippage when turnover spikes unexpectedly.",
                ],
                expected_failure_regimes=[
                    "high_correlation_breakdown",
                    "liquidity_crunch",
                    "frequent_gap_moves",
                ],
                cost_profile=f"moderate_to_high (turnover={turnover:.3f})",
                why_not_selected=risk_budget_rejection,
            ),
            StrategyDecisionCandidate(
                name="EqualWeightAllocator",
                spec=equal_weight_spec,
                pros=[
                    "Simple and transparent implementation.",
                    "Lower model dependency and fewer estimation errors.",
                    "Operationally robust when factor spread is stable.",
                ],
                cons=[
                    "No dynamic risk budget; can over-allocate to volatile names.",
                    f"Less adaptive to drawdown target={drawdown_target:.3f}.",
                    f"Sensitive to market microstructure constraints (lot_size={lot_size:.0f}, t_plus_one={t_plus_one}).",
                ],
                risks=[
                    "Tail drawdown in volatility regime shifts.",
                    "Cost drag when rebalancing coarse lots.",
                ],
                expected_failure_regimes=[
                    "high_volatility_regime",
                    "trend_reversal_whipsaw",
                    "microstructure_friction",
                ],
                cost_profile=f"low_to_moderate (coverage={coverage:.3f})",
                why_not_selected=equal_weight_rejection,
            ),
        ]

        choose_risk_budget = (
            t_plus_one
            or (oos_gap >= 0.03)
            or (turnover >= 0.25)
            or (drawdown_target <= 0.1)
        )
        if choose_risk_budget:
            selected = StrategyDecisionSelected(
                name="RiskBudgetAllocator",
                spec=risk_budget_spec,
                rationale=(
                    "Selected Risk Budget rather than Equal Weight. "
                    "Why not Equal Weight: current drawdown and regime constraints require dynamic "
                    "risk-contribution control."
                ),
                tradeoff_summary=(
                    "Trade-off: higher model complexity in exchange for better drawdown and regime control. "
                    f"market={market_key}, t_plus_one={t_plus_one}, is_24x7={is_24x7}; {regime_hint}"
                ),
            )
            candidates[1].why_not_selected = equal_weight_rejection
        else:
            selected = StrategyDecisionSelected(
                name="EqualWeightAllocator",
                spec=equal_weight_spec,
                rationale=(
                    "Selected Equal Weight over Risk Budget because current factor health is stable and cost-aware simplicity wins."
                ),
                tradeoff_summary=(
                    "Trade-off: simpler execution and lower implementation risk, "
                    f"but weaker downside control if volatility regime changes; market={market_key}."
                ),
            )
            candidates[0].why_not_selected = risk_budget_rejection

        # Keep objective trace in narrative so different questions/markets naturally diverge.
        objectives = research_plan.get("objectives", [])
        if isinstance(objectives, list) and objectives:
            selected.tradeoff_summary = f"{selected.tradeoff_summary} objectives={', '.join(str(v) for v in objectives[:4])}."
        if question.strip():
            selected.tradeoff_summary = f"{selected.tradeoff_summary} question_scope={question[:80]}."

        return StrategyDecision(candidates=candidates, selected=selected, llm_mode="rule_fallback")

    def _extract_json(self, text: str) -> dict[str, Any] | None:
        if not text:
            return None
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return None
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

