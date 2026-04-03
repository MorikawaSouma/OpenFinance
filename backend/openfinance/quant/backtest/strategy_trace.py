from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from openfinance.quant.backtest.evaluation_plan import (
    BacktestEvaluationPlan,
    FactorVersionRef,
    parse_backtest_evaluation_plan,
)
from openfinance.research.strategy_compilation import (
    StrategyCompilationPlan,
    parse_strategy_compilation_plan,
)
from openfinance.research.strategy_decision import StrategyDecision, parse_strategy_decision
from openfinance.research.strategy_validation import (
    StrategyValidationResult,
    parse_strategy_validation_result,
)


class StrategyFactorLineageSummary(BaseModel):
    factor_versions: list[FactorVersionRef] = Field(default_factory=list)
    reason: str | None = None


class StrategyTraceArtifact(BaseModel):
    schema_version: str = "strategy_trace_artifact.v1"
    trace_object: Literal["BacktestReport", "BacktestRequest"] = "BacktestReport"
    strategy_decision: StrategyDecision | None = None
    strategy_validation: StrategyValidationResult | None = None
    strategy_compilation: StrategyCompilationPlan | None = None
    evaluation_plan: BacktestEvaluationPlan | None = None
    factor_lineage: StrategyFactorLineageSummary = Field(default_factory=StrategyFactorLineageSummary)
    summary: str = ""


def coerce_factor_version_refs(raw: Any) -> list[FactorVersionRef]:
    rows: list[FactorVersionRef] = []
    seen: set[tuple[str, str]] = set()
    if not isinstance(raw, list):
        return rows
    for item in raw:
        try:
            parsed = item if isinstance(item, FactorVersionRef) else FactorVersionRef.model_validate(item)
        except ValidationError:
            continue
        key = (parsed.factor_id, parsed.version)
        if key in seen:
            continue
        seen.add(key)
        rows.append(parsed)
    return rows


def parse_strategy_trace_artifact(raw: StrategyTraceArtifact | dict[str, Any] | None) -> StrategyTraceArtifact | None:
    if raw is None:
        return None
    if isinstance(raw, StrategyTraceArtifact):
        return raw
    if not isinstance(raw, dict):
        return None
    try:
        return StrategyTraceArtifact.model_validate(raw)
    except ValidationError:
        return None


def strategy_trace_artifact_payload(raw: StrategyTraceArtifact | dict[str, Any] | None) -> dict[str, Any]:
    parsed = parse_strategy_trace_artifact(raw)
    if parsed is not None:
        return parsed.model_dump(mode="json")
    if isinstance(raw, dict):
        return dict(raw)
    return {}


def build_strategy_trace_artifact(
    *,
    trace_object: Literal["BacktestReport", "BacktestRequest"],
    strategy_decision: StrategyDecision | dict[str, Any] | None = None,
    strategy_validation: StrategyValidationResult | dict[str, Any] | None = None,
    strategy_compilation: StrategyCompilationPlan | dict[str, Any] | None = None,
    evaluation_plan: BacktestEvaluationPlan | dict[str, Any] | None = None,
    factor_versions: list[FactorVersionRef] | list[dict[str, Any]] | None = None,
    factor_lineage_reason: str | None = None,
) -> StrategyTraceArtifact | None:
    parsed_evaluation_plan = parse_backtest_evaluation_plan(evaluation_plan)
    parsed_decision = parse_strategy_decision(strategy_decision)
    parsed_validation = parse_strategy_validation_result(strategy_validation)
    parsed_compilation = parse_strategy_compilation_plan(strategy_compilation)
    normalized_factor_versions = coerce_factor_version_refs(factor_versions)

    if parsed_evaluation_plan is not None:
        parsed_decision = parsed_decision or parsed_evaluation_plan.strategy_decision
        parsed_validation = parsed_validation or parsed_evaluation_plan.strategy_validation
        parsed_compilation = parsed_compilation or parsed_evaluation_plan.strategy_compilation
        if not normalized_factor_versions:
            normalized_factor_versions = list(parsed_evaluation_plan.factor_versions)

    if (
        parsed_decision is None
        and parsed_validation is None
        and parsed_compilation is None
        and parsed_evaluation_plan is None
        and not normalized_factor_versions
        and not factor_lineage_reason
    ):
        return None

    summary_parts: list[str] = [f"trace_object={trace_object}"]
    if parsed_validation is not None:
        summary_parts.append(f"validation={parsed_validation.status}")
    if parsed_compilation is not None:
        summary_parts.append(f"compile_ready={parsed_compilation.compile_ready}")
    if parsed_evaluation_plan is not None:
        summary_parts.append(f"evaluation_plan={parsed_evaluation_plan.schema_version}")
    if normalized_factor_versions:
        summary_parts.append(f"factor_versions={len(normalized_factor_versions)}")
    elif factor_lineage_reason:
        summary_parts.append(f"factor_lineage_reason={factor_lineage_reason}")

    return StrategyTraceArtifact(
        trace_object=trace_object,
        strategy_decision=parsed_decision,
        strategy_validation=parsed_validation,
        strategy_compilation=parsed_compilation,
        evaluation_plan=parsed_evaluation_plan,
        factor_lineage=StrategyFactorLineageSummary(
            factor_versions=normalized_factor_versions,
            reason=factor_lineage_reason,
        ),
        summary="; ".join(summary_parts),
    )
