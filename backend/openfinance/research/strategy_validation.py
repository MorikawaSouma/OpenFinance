from typing import Any, Literal

from pydantic import BaseModel, Field

from openfinance.research.strategy_decision import StrategyDecision
from openfinance.research.strategy_spec import StrategySpec


ValidationStatus = Literal["ok", "warn", "invalid"]
DecisionStatus = Literal["aligned", "not_provided", "mismatch"]


class StrategyValidationCheck(BaseModel):
    check_id: Literal["spec_fields", "decision_alignment", "evidence_linkage", "compile_boundary"]
    status: ValidationStatus
    detail: str


class StrategyValidationResult(BaseModel):
    schema_version: str = "strategy_validation.v1"
    validated_object: Literal["strategy_spec"] = "strategy_spec"
    strategy_id: str
    strategy_version: str
    market: str
    status: ValidationStatus
    compile_ready: bool
    decision_status: DecisionStatus = "not_provided"
    selected_candidate: str | None = None
    next_output: Literal["BacktestRequest"] = "BacktestRequest"
    summary: str
    checks: list[StrategyValidationCheck] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


def parse_strategy_validation_result(raw: Any) -> StrategyValidationResult | None:
    if isinstance(raw, StrategyValidationResult):
        return raw
    if not isinstance(raw, dict) or not raw:
        return None
    try:
        return StrategyValidationResult.model_validate(raw)
    except ValueError:
        return None


class StrategyValidator:
    def validate_spec(
        self,
        spec: StrategySpec,
        *,
        decision: StrategyDecision | None = None,
    ) -> StrategyValidationResult:
        checks: list[StrategyValidationCheck] = []

        field_issues: list[str] = []
        if not str(spec.strategy_family).strip():
            field_issues.append("strategy_family is empty")
        if not str(spec.rebalance).strip():
            field_issues.append("rebalance is empty")
        if int(spec.lookback_days) < 2:
            field_issues.append("lookback_days must be >= 2")
        if float(spec.max_position) <= 0.0:
            field_issues.append("max_position must be > 0")
        if float(spec.leverage_limit) <= 0.0:
            field_issues.append("leverage_limit must be > 0")
        if float(spec.signal_threshold) < 0.0:
            field_issues.append("signal_threshold should not be negative for current simulation profiles")
        if field_issues:
            checks.append(
                StrategyValidationCheck(
                    check_id="spec_fields",
                    status="invalid",
                    detail="; ".join(field_issues),
                )
            )
        else:
            checks.append(
                StrategyValidationCheck(
                    check_id="spec_fields",
                    status="ok",
                    detail=(
                        f"{spec.strategy_family}/{spec.position_sizing}/{spec.rebalance} "
                        f"fits current simulation profile for market={spec.market}."
                    ),
                )
            )

        evidence_refs = [str(ref).strip() for ref in spec.evidence_refs if str(ref).strip()]
        if evidence_refs:
            checks.append(
                StrategyValidationCheck(
                    check_id="evidence_linkage",
                    status="ok",
                    detail=f"Linked to {len(evidence_refs)} evidence references.",
                )
            )
        else:
            checks.append(
                StrategyValidationCheck(
                    check_id="evidence_linkage",
                    status="warn",
                    detail="No evidence_refs attached to this strategy spec.",
                )
            )

        decision_status: DecisionStatus = "not_provided"
        selected_candidate: str | None = None
        if decision is None:
            checks.append(
                StrategyValidationCheck(
                    check_id="decision_alignment",
                    status="ok",
                    detail="No StrategyDecision artifact provided; validation covers durable strategy semantics only.",
                )
            )
        else:
            selected_candidate = str(decision.selected.name or "").strip() or None
            mismatches: list[str] = []
            selected_spec = decision.selected.spec
            # Decision artifacts own product-facing selection semantics only.
            # Compile-time/runtime overlays such as leverage_limit and stop_loss
            # are applied downstream when producing the executable BacktestRequest.
            decision_owned_pairs = [
                ("strategy_family", str(selected_spec.strategy_family or "").strip(), str(spec.strategy_family or "").strip()),
                ("rebalance", str(selected_spec.rebalance or "").strip(), str(spec.rebalance or "").strip()),
                ("lookback_days", int(selected_spec.lookback_days), int(spec.lookback_days)),
                ("signal_threshold", float(selected_spec.signal_threshold), float(spec.signal_threshold)),
                ("position_sizing", str(selected_spec.position_sizing or "").strip(), str(spec.position_sizing or "").strip()),
                ("risk_budget", str(selected_spec.risk_budget or "").strip(), str(spec.risk_budget or "").strip()),
                ("max_position", round(float(selected_spec.max_position), 6), round(float(spec.max_position), 6)),
            ]
            for field_name, expected_value, actual_value in decision_owned_pairs:
                if expected_value != actual_value:
                    mismatches.append(f"{field_name}: decision={expected_value} spec={actual_value}")
            if mismatches:
                decision_status = "mismatch"
                checks.append(
                    StrategyValidationCheck(
                        check_id="decision_alignment",
                        status="invalid",
                        detail="Selected decision proposal diverges from StrategySpec: " + "; ".join(mismatches),
                    )
                )
            else:
                decision_status = "aligned"
                checks.append(
                    StrategyValidationCheck(
                        check_id="decision_alignment",
                        status="ok",
                        detail=f"Selected proposal {selected_candidate or '-'} matches the durable StrategySpec fields.",
                    )
                )

        compile_ready = not any(check.status == "invalid" for check in checks)
        compile_status = "ok" if compile_ready else "invalid"
        compile_note = (
            (
                "StrategySpec is ready to compile into BacktestRequest; "
                "runtime task state and execution overlays such as leverage_limit/stop_loss remain outside decision alignment."
            )
            if compile_ready
            else (
                "StrategySpec is not compile-ready until invalid validation checks are resolved. "
                "BacktestRequest-specific runtime overlays remain downstream of validation."
            )
        )
        checks.append(
            StrategyValidationCheck(
                check_id="compile_boundary",
                status=compile_status,
                detail=compile_note,
            )
        )

        status = self._rollup_status(checks)
        warning_count = sum(1 for check in checks if check.status == "warn")
        invalid_count = sum(1 for check in checks if check.status == "invalid")
        if invalid_count > 0:
            summary = (
                f"Strategy validation found {invalid_count} invalid checks before compile to BacktestRequest."
            )
        elif warning_count > 0:
            summary = (
                f"Strategy validation is compile-ready with {warning_count} warning checks before BacktestRequest."
            )
        else:
            summary = "Strategy validation passed and is compile-ready for BacktestRequest."
        return StrategyValidationResult(
            strategy_id=spec.strategy_id,
            strategy_version=spec.strategy_version,
            market=str(spec.market or "").upper(),
            status=status,
            compile_ready=compile_ready,
            decision_status=decision_status,
            selected_candidate=selected_candidate,
            summary=summary,
            checks=checks,
            evidence_refs=evidence_refs,
        )

    def _rollup_status(self, checks: list[StrategyValidationCheck]) -> ValidationStatus:
        if any(check.status == "invalid" for check in checks):
            return "invalid"
        if any(check.status == "warn" for check in checks):
            return "warn"
        return "ok"
