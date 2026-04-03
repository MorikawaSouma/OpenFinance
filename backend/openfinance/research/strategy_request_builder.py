from typing import Any

from openfinance.quant.backtest.evaluation_plan import (
    BacktestEvaluationPlan,
    BacktestEvaluationWindow,
    FactorVersionRef,
    StrategyBacktestRequestInputProfile,
    backtest_evaluation_plan_payload,
    parse_backtest_evaluation_plan,
)
from openfinance.quant.backtest.report import BacktestRequest, CostModel
from openfinance.research.strategy_compilation import StrategyCompileRuntimeContext, StrategyCompilationPlan
from openfinance.research.strategy_decision import StrategyDecision
from openfinance.research.strategy_validation import StrategyValidationResult

def build_strategy_backtest_request_input_profile(
    *,
    runtime_context: StrategyCompileRuntimeContext,
) -> StrategyBacktestRequestInputProfile:
    mode = str(runtime_context.provenance_mode or "pipeline_managed")
    summary = (
        f"BacktestRequest defaults assembled from normalized {mode.replace('_', ' ')} compile-entry inputs. "
        "Dataset binding, window, execution model, run_time_utc, and cost defaults come from the shared runtime "
        "context before executable request creation."
    )
    return StrategyBacktestRequestInputProfile(
        provenance_mode=mode,
        summary=summary,
    )


def _normalize_factor_version_refs(
    rows: list[FactorVersionRef | dict[str, Any]] | None,
) -> list[FactorVersionRef]:
    normalized: list[FactorVersionRef] = []
    for row in rows or []:
        if isinstance(row, FactorVersionRef):
            normalized.append(row.model_copy(deep=True))
            continue
        normalized.append(FactorVersionRef.model_validate(row))
    return normalized


def build_strategy_backtest_request(
    *,
    strategy_id: str,
    strategy_version: str,
    market: str,
    runtime_context: StrategyCompileRuntimeContext,
    constraints: dict[str, Any] | None = None,
    factor_versions: list[FactorVersionRef | dict[str, Any]] | None = None,
    evaluation_plan: BacktestEvaluationPlan | dict[str, Any] | None = None,
    strategy_decision: StrategyDecision | None = None,
    strategy_validation: StrategyValidationResult | None = None,
    strategy_compilation: StrategyCompilationPlan | None = None,
) -> BacktestRequest:
    normalized_constraints = dict(constraints or {})
    normalized_execution_model = (
        str(normalized_constraints.get("execution_model") or runtime_context.execution_model or "next_open").strip().lower()
        or "next_open"
    )
    normalized_run_time_utc = (
        str(normalized_constraints.get("run_time_utc") or runtime_context.run_time_utc or "16:00").strip()
        or "16:00"
    )
    normalized_constraints.setdefault("execution_model", normalized_execution_model)
    normalized_constraints.setdefault("run_time_utc", normalized_run_time_utc)
    if runtime_context.auto_round_lot is not None:
        normalized_constraints.setdefault("auto_round_lot", bool(runtime_context.auto_round_lot))

    normalized_factor_versions = _normalize_factor_version_refs(factor_versions)
    existing_evaluation_payload = backtest_evaluation_plan_payload(evaluation_plan)
    normalized_evaluation_plan = parse_backtest_evaluation_plan(existing_evaluation_payload) or BacktestEvaluationPlan()
    normalized_evaluation_plan = normalized_evaluation_plan.model_copy(
        update={
            "request_input_profile": build_strategy_backtest_request_input_profile(runtime_context=runtime_context),
            "evidence_refs": (
                list(runtime_context.evidence_refs)
                if runtime_context.evidence_refs
                else list(normalized_evaluation_plan.evidence_refs)
            ),
            "strategy_decision": strategy_decision or normalized_evaluation_plan.strategy_decision,
            "strategy_validation": strategy_validation or normalized_evaluation_plan.strategy_validation,
            "strategy_compilation": strategy_compilation or normalized_evaluation_plan.strategy_compilation,
            "factor_versions": normalized_factor_versions or list(normalized_evaluation_plan.factor_versions),
        },
        deep=True,
    )
    if normalized_evaluation_plan.window is None:
        normalized_evaluation_plan = normalized_evaluation_plan.model_copy(
            update={"window": BacktestEvaluationWindow(start=runtime_context.start, end=runtime_context.end)},
            deep=True,
        )
    final_factor_versions = normalized_factor_versions or list(normalized_evaluation_plan.factor_versions)

    return BacktestRequest(
        dataset_version=runtime_context.dataset_version,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        market=market,
        start=runtime_context.start,
        end=runtime_context.end,
        execution_model=normalized_execution_model,
        cost_model=CostModel(
            commission_bps=float(runtime_context.commission_bps or 0.0),
            slippage_bps=float(runtime_context.slippage_bps or 0.0),
        ),
        factor_versions=final_factor_versions,
        constraints=normalized_constraints,
        evaluation_plan=normalized_evaluation_plan,
    )
