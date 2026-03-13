from functools import lru_cache

from fastapi import APIRouter, HTTPException

from openfinance.api.routes_pipeline import PipelineRunTaskRequest, submit_pipeline_run_task
from openfinance.core.audit import FileAuditStore
from openfinance.core.config import settings
from openfinance.core.tasks import TaskRecord
from openfinance.data.registry import DatasetRegistry
from openfinance.quant.backtest.run_registry import RunRegistry
from openfinance.research.pipeline import (
    MigrationPreflightBlockedError,
    PipelineRequest,
    PipelineResponse,
    PlanCreateRequest,
    PlanCreateResponse,
    ResearchPipelineEngine,
    ResearchPlan,
)
from openfinance.research.plan_registry import PlanRegistry

router = APIRouter(tags=["research"])


@lru_cache(maxsize=1)
def _engine() -> ResearchPipelineEngine:
    return ResearchPipelineEngine(
        audit_store=FileAuditStore(settings.audit_log_file),
        dataset_registry=DatasetRegistry(settings.dataset_registry_file, settings.data_root),
        run_registry=RunRegistry(settings.run_registry_file),
        plan_registry=PlanRegistry(settings.plan_registry_file),
    )


@lru_cache(maxsize=1)
def _plan_registry() -> PlanRegistry:
    return PlanRegistry(settings.plan_registry_file)


@router.post("/plan", response_model=PlanCreateResponse)
def create_plan(request: PlanCreateRequest) -> PlanCreateResponse:
    return _engine().create_plan(request)


@router.get("/plan/{plan_id}", response_model=ResearchPlan)
def get_plan(plan_id: str) -> ResearchPlan:
    raw = _plan_registry().get_plan_payload(plan_id)
    if raw is None:
        raise HTTPException(status_code=404, detail="plan not found")
    return ResearchPlan.model_validate(raw)


@router.post("/run", response_model=PipelineResponse)
def run_from_plan(request: PipelineRequest) -> PipelineResponse:
    try:
        return _engine().run(request)
    except MigrationPreflightBlockedError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "message": str(exc),
                "preflight_warnings": [row.model_dump(mode="json") for row in exc.warnings],
                "action_required": "Set migration_preflight_confirmed=true or auto_adjust_for_market_rules=true.",
            },
        ) from exc


@router.post("/run/submit", response_model=TaskRecord)
def run_from_plan_submit(request: PipelineRunTaskRequest) -> TaskRecord:
    return submit_pipeline_run_task(request)
