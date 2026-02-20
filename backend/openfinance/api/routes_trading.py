from functools import lru_cache

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from openfinance.core.audit import FileAuditStore
from openfinance.core.config import settings
from openfinance.trading.approval import ApprovalRequest
from openfinance.trading.live import LiveOrderRequest, TradingStatus
from openfinance.trading.paper import PaperOrderRequest, PaperOrderResult
from openfinance.trading.risk import RiskEvent
from openfinance.trading.sim_broker import SimBrokerLog
from openfinance.trading.service import TradingService

router = APIRouter(prefix="/trading", tags=["trading"])


class ToggleRequest(BaseModel):
    enabled: bool


class ApprovalCreateRequest(BaseModel):
    target: str  # live_trading | paper_trading
    use_case: str | None = None
    plan_id: str | None = None
    evidence_pack_id: str | None = None
    session_id: str | None = None
    risk_statement_ack: bool = False


class ApprovalActionRequest(BaseModel):
    actor: str = "admin"


class RiskHeartbeatRequest(BaseModel):
    account_equity: float = Field(gt=0)
    source: str = "manual"
    metrics: dict[str, float | int | str] = Field(default_factory=dict)


@lru_cache(maxsize=1)
def _service() -> TradingService:
    return TradingService(audit_store=FileAuditStore(settings.audit_log_file))


@router.get("/status", response_model=TradingStatus)
def status() -> TradingStatus:
    return _service().status()


@router.post("/kill-switch", response_model=TradingStatus)
def set_kill_switch(payload: ToggleRequest) -> TradingStatus:
    return _service().set_kill_switch(payload.enabled)


@router.post("/live/unlock", response_model=TradingStatus)
def set_live(payload: ToggleRequest) -> TradingStatus:
    return _service().unlock_live(payload.enabled)


@router.post("/paper/control", response_model=TradingStatus)
def set_paper_control(payload: ToggleRequest) -> TradingStatus:
    return _service().set_paper_running(payload.enabled)


@router.post("/risk/heartbeat", response_model=TradingStatus)
def update_risk_heartbeat(payload: RiskHeartbeatRequest) -> TradingStatus:
    return _service().update_account_risk(
        account_equity=payload.account_equity,
        source=payload.source,
        metrics=payload.metrics,
    )


@router.get("/risk/events", response_model=list[RiskEvent])
def list_risk_events(limit: int = 50) -> list[RiskEvent]:
    return _service().list_risk_events(limit=limit)


@router.get("/approvals", response_model=list[ApprovalRequest])
def list_approvals() -> list[ApprovalRequest]:
    return _service().list_approvals()


@router.get("/approvals/{request_id}", response_model=ApprovalRequest)
def get_approval(request_id: str) -> ApprovalRequest:
    row = _service().get_approval(request_id)
    if row is None:
        raise HTTPException(status_code=404, detail="approval request not found")
    return row


@router.post("/approvals/request", response_model=ApprovalRequest)
def request_approval(payload: ApprovalCreateRequest) -> ApprovalRequest:
    target = payload.target.strip().lower()
    if target not in {"live_trading", "paper_trading"}:
        raise HTTPException(status_code=400, detail="target must be live_trading or paper_trading")
    context = {
        "use_case": (payload.use_case or "").strip(),
        "plan_id": (payload.plan_id or "").strip(),
        "evidence_pack_id": (payload.evidence_pack_id or "").strip(),
        "session_id": (payload.session_id or "").strip(),
        "risk_statement_ack": bool(payload.risk_statement_ack),
    }
    return _service().request_unlock(target=target, actor="user", context=context)


@router.post("/approvals/{request_id}/approve", response_model=ApprovalRequest)
def approve_approval(request_id: str, payload: ApprovalActionRequest) -> ApprovalRequest:
    return _service().approve_request(request_id=request_id, actor=payload.actor)


@router.post("/approvals/{request_id}/enable", response_model=ApprovalRequest)
def enable_approval(request_id: str, payload: ApprovalActionRequest) -> ApprovalRequest:
    try:
        return _service().enable_request(request_id=request_id, actor=payload.actor)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex


@router.post("/approvals/{request_id}/revoke", response_model=ApprovalRequest)
def revoke_approval(request_id: str, payload: ApprovalActionRequest) -> ApprovalRequest:
    return _service().revoke_request(request_id=request_id, actor=payload.actor)


def _ensure_traceability(request: PaperOrderRequest) -> None:
    plan_id = (request.plan_id or "").strip()
    evidence_pack_id = (request.evidence_pack_id or "").strip()
    if plan_id or evidence_pack_id:
        return
    raise HTTPException(
        status_code=400,
        detail="Order request must include plan_id or evidence_pack_id for traceability.",
    )


@router.post("/paper/orders", response_model=PaperOrderResult)
def place_paper_order(request: PaperOrderRequest) -> PaperOrderResult:
    _ensure_traceability(request)
    return _service().place_paper_order(request)


@router.post("/live/orders", response_model=PaperOrderResult)
def place_live_order(request: LiveOrderRequest) -> PaperOrderResult:
    _ensure_traceability(request)
    result = _service().place_live_order(request)
    if (not result.accepted) and result.reason not in {"pending_approval"}:
        raise HTTPException(status_code=403, detail=result.reason)
    return result


@router.get("/live/logs", response_model=list[SimBrokerLog])
def list_live_logs(limit: int = 200) -> list[SimBrokerLog]:
    return _service().list_live_logs(limit=limit)
