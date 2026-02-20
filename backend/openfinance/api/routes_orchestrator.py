from functools import lru_cache

from fastapi import APIRouter

from openfinance.agents.catalog import build_default_agents
from openfinance.agents.orchestrator import AgentOrchestrator, OrchestratorRequest, OrchestratorResponse
from openfinance.core.audit import FileAuditStore
from openfinance.core.config import settings
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


@router.post("/run", response_model=OrchestratorResponse)
def run_orchestrator(request: OrchestratorRequest) -> OrchestratorResponse:
    return _build_orchestrator().handle(request)
