from functools import lru_cache
from threading import Thread
import traceback
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter

from openfinance.agents.catalog import build_default_agents
from openfinance.agents.orchestrator import AgentOrchestrator, OrchestratorRequest, OrchestratorResponse
from openfinance.core.audit import FileAuditStore
from openfinance.core.config import settings
from openfinance.core.events import event_bus
from openfinance.core.tasks import TaskRecord, get_task_manager
from openfinance.data.registry import DatasetRegistry
from openfinance.knowledge.service import build_default_knowledge_service
from openfinance.quant.backtest.run_registry import RunRegistry
from openfinance.tools.registry import build_default_tool_registry

router = APIRouter(prefix="/orchestrator", tags=["orchestrator"])


@lru_cache(maxsize=1)
def _build_orchestrator() -> AgentOrchestrator:
    audit_store = FileAuditStore(settings.audit_log_file)
    dataset_registry = DatasetRegistry(
        registry_file=settings.dataset_registry_file,
        data_root=settings.data_root,
    )
    run_registry = RunRegistry(settings.run_registry_file)
    tool_registry = build_default_tool_registry(
        audit_store=audit_store,
        dataset_registry=dataset_registry,
        run_registry=run_registry,
    )
    knowledge = build_default_knowledge_service()
    return AgentOrchestrator(
        agents=build_default_agents(knowledge_service=knowledge),
        tool_registry=tool_registry,
        audit_store=audit_store,
        knowledge_service=knowledge,
    )


@lru_cache(maxsize=1)
def _task_manager():
    return get_task_manager()


class OrchestratorRunTaskRequest(OrchestratorRequest):
    session_id: str | None = None


def _task_payload(task: TaskRecord, **extra: Any) -> dict[str, Any]:
    payload = {
        "task_id": str(task.task_id),
        "parent_task_id": str(task.parent_task_id) if task.parent_task_id else None,
        "type": task.task_type,
        "status": task.status,
        "progress": task.progress,
        "message": task.message,
        "result_ref": task.result_ref,
        "error": task.error,
        "task": task.model_dump(mode="json"),
    }
    payload.update(extra)
    return payload


def _emit_task_state(event_type: str, trace_id: UUID, task: TaskRecord, *, session_id: str, **extra: Any) -> None:
    event_bus.publish(
        event_type=event_type,
        trace_id=str(trace_id),
        session_id=session_id,
        payload=_task_payload(task, **extra),
    )


@router.post("/run", response_model=OrchestratorResponse)
def run_orchestrator(request: OrchestratorRequest) -> OrchestratorResponse:
    return _build_orchestrator().handle(request)


@router.post("/run/submit", response_model=TaskRecord)
def run_orchestrator_submit(request: OrchestratorRunTaskRequest) -> TaskRecord:
    tm = _task_manager()
    trace_id = uuid4()
    session_id = str(request.session_id or "orchestrator").strip() or "orchestrator"
    parent = tm.create(
        task_type="orchestrator_run",
        message="queued",
        status="queued",
        meta={
            "session_id": session_id,
            "trace_id": str(trace_id),
            "intent": "orchestrator.run",
        },
    )
    _emit_task_state("task.created", trace_id, parent, session_id=session_id, role="parent")

    def _worker() -> None:
        running = tm.update(parent.task_id, status="running", progress=10, message="running orchestrator")
        _emit_task_state("task.progress", trace_id, running, session_id=session_id, role="parent")
        try:
            response = _build_orchestrator().handle(
                OrchestratorRequest.model_validate(request.model_dump())
            )
            done = tm.update(
                parent.task_id,
                status="done",
                progress=100,
                message="orchestrator done",
                result={
                    "trace_id": str(response.trace_id),
                    "summary": response.summary,
                    "outputs_count": len(response.outputs),
                    "orchestrator_response": response.model_dump(mode="json"),
                },
                result_ref={
                    "trace_id": str(response.trace_id),
                    "open_path": f"/chat?restored_trace_id={response.trace_id}",
                },
            )
            _emit_task_state("task.done", trace_id, done, session_id=session_id, role="parent")
        except Exception as ex:
            failed = tm.update(
                parent.task_id,
                status="error",
                progress=100,
                message="orchestrator failed",
                error=str(ex),
                meta={
                    **(tm.get(parent.task_id).meta if tm.get(parent.task_id) else {}),
                    "stacktrace": traceback.format_exc(),
                },
            )
            _emit_task_state(
                "task.error",
                trace_id,
                failed,
                session_id=session_id,
                role="parent",
                error_message=str(ex),
            )

    Thread(target=_worker, daemon=True).start()
    return parent
