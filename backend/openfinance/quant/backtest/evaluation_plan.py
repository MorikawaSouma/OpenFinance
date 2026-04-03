from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from openfinance.research.strategy_compilation import StrategyCompilationPlan
from openfinance.research.strategy_decision import StrategyDecision
from openfinance.research.strategy_validation import StrategyValidationResult


class FactorVersionRef(BaseModel):
    factor_id: str
    version: str


StrategyRequestInputSource = Literal[
    "runtime_context.dataset_version",
    "runtime_context.window",
    "runtime_context.execution_model",
    "runtime_context.run_time_utc",
    "runtime_context.cost_model",
    "builder.constraints",
    "builder.factor_versions",
    "builder.evaluation_plan",
]


class StrategyBacktestRequestInputProfile(BaseModel):
    schema_version: str = "strategy_backtest_request_input_profile.v1"
    profile_id: str = "backtest_request.entry.v1"
    executable_object: Literal["BacktestRequest"] = "BacktestRequest"
    provenance_mode: str = "pipeline_managed"
    dataset_binding_source: StrategyRequestInputSource = "runtime_context.dataset_version"
    window_source: StrategyRequestInputSource = "runtime_context.window"
    execution_model_source: StrategyRequestInputSource = "runtime_context.execution_model"
    run_time_utc_source: StrategyRequestInputSource = "runtime_context.run_time_utc"
    cost_model_source: StrategyRequestInputSource = "runtime_context.cost_model"
    constraints_source: StrategyRequestInputSource = "builder.constraints"
    factor_versions_source: StrategyRequestInputSource = "builder.factor_versions"
    evaluation_plan_source: StrategyRequestInputSource = "builder.evaluation_plan"
    summary: str = ""


class BacktestEvaluationWindow(BaseModel):
    start: str
    end: str


class BacktestEvaluationPlan(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: str = "backtest_evaluation_plan.v1"
    window: BacktestEvaluationWindow | None = None
    stress: list[str] = Field(default_factory=list)
    seed: int | None = None
    evidence_pack_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    factor_id: str | None = None
    factor_version: str | None = None
    factor_versions: list[FactorVersionRef] = Field(default_factory=list)
    factor_artifact_path: str | None = None
    failure_conditions: list[Any] = Field(default_factory=list)
    no_factor_strategy: bool | None = None
    strategy_decision: StrategyDecision | None = None
    strategy_validation: StrategyValidationResult | None = None
    strategy_compilation: StrategyCompilationPlan | None = None
    request_input_profile: StrategyBacktestRequestInputProfile | None = None
    meta_variant_id: str | None = None
    meta_group: str | None = None


def parse_backtest_evaluation_plan(
    raw: BacktestEvaluationPlan | dict[str, Any] | None,
) -> BacktestEvaluationPlan | None:
    if raw is None:
        return None
    if isinstance(raw, BacktestEvaluationPlan):
        return raw
    if not isinstance(raw, dict):
        return None
    try:
        return BacktestEvaluationPlan.model_validate(raw)
    except ValidationError:
        return None


def backtest_evaluation_plan_payload(raw: BacktestEvaluationPlan | dict[str, Any] | None) -> dict[str, Any]:
    parsed = parse_backtest_evaluation_plan(raw)
    if parsed is not None:
        return parsed.model_dump(mode="json")
    if isinstance(raw, dict):
        return dict(raw)
    return {}
