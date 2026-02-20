from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from openfinance.core.audit import AuditLogEntry, FileAuditStore
from openfinance.core.config import settings
from openfinance.core.events import event_bus
from openfinance.quant.checks import (
    FailureConditionCheckRegistry,
    FailureConditionCheckResult,
    normalize_failure_conditions,
)
from openfinance.trading.approval import ApprovalRequest, ApprovalService
from openfinance.trading.live import LiveTradingEngine, TradingStatus
from openfinance.trading.paper import PaperOrderRequest, PaperOrderResult, PaperTradingEngine
from openfinance.trading.risk import RiskEvent, RiskEventStore, RiskGate, RiskMonitor
from openfinance.trading.sim_broker import SimBrokerAdapter, SimBrokerLog


@dataclass
class TradingControl:
    kill_switch_enabled: bool
    live_enabled: bool
    paper_enabled: bool


class TradingService:
    def __init__(self, audit_store: FileAuditStore) -> None:
        self.audit_store = audit_store
        self.approvals = ApprovalService(settings.approval_db_file)
        self.risk_events = RiskEventStore(settings.risk_events_db_file)
        self.control = TradingControl(
            kill_switch_enabled=settings.kill_switch_enabled,
            live_enabled=settings.enable_live_trading and not settings.live_trading_unlock_required,
            paper_enabled=True,
        )
        self.risk_gate = RiskGate(
            max_order_qty=settings.risk_max_order_qty,
            live_enabled=self.control.live_enabled,
            paper_enabled=self.control.paper_enabled,
            kill_switch_enabled=self.control.kill_switch_enabled,
        )
        self.risk_monitor = RiskMonitor(
            max_account_drawdown=settings.risk_max_account_drawdown,
            abnormal_volatility_threshold=settings.risk_abnormal_volatility_threshold,
            rolling_window=settings.risk_volatility_window,
            warn_ratio=settings.risk_monitor_warn_ratio,
            initial_equity=settings.risk_monitor_initial_equity,
        )
        self._risk_snapshot = self.risk_monitor.snapshot()
        self.failure_check_registry = FailureConditionCheckRegistry.default_registry()
        self.paper_engine = PaperTradingEngine(risk_gate=self.risk_gate)
        self.live_engine = LiveTradingEngine(risk_gate=self.risk_gate)
        self.sim_broker = SimBrokerAdapter()

    def status(self) -> TradingStatus:
        self.approvals.expire_stale()
        live_req = self._latest_trade_enable_request("live_trading")
        paper_req = self._latest_trade_enable_request("paper_trading")
        pending_count = len([row for row in self.approvals.list_requests(limit=500) if row.status == "pending"])
        return TradingStatus(
            mode=settings.trading_mode,
            kill_switch_enabled=self.control.kill_switch_enabled,
            live_trading_enabled=self.control.live_enabled,
            paper_trading_enabled=self.control.paper_enabled,
            risk_max_order_qty=self.risk_gate.max_order_qty,
            live_approval_state=live_req.status if live_req else None,
            paper_approval_state=paper_req.status if paper_req else None,
            pending_approval_count=pending_count,
            current_equity=self._risk_snapshot.account_equity,
            peak_equity=self._risk_snapshot.peak_equity,
            current_drawdown=self._risk_snapshot.current_drawdown,
            current_volatility=self._risk_snapshot.rolling_volatility,
            realized_volatility=self._risk_snapshot.realized_volatility,
            risk_status=self._risk_snapshot.status,
            max_account_drawdown_limit=self._risk_snapshot.max_account_drawdown_limit,
            abnormal_volatility_limit=self._risk_snapshot.abnormal_volatility_limit,
            recent_risk_events=[row.model_dump(mode="json") for row in self.risk_events.list_recent(limit=20)],
        )

    def set_kill_switch(self, enabled: bool) -> TradingStatus:
        self.control.kill_switch_enabled = enabled
        self.risk_gate.kill_switch_enabled = enabled
        if not enabled:
            self._risk_snapshot = self.risk_monitor.clear_blocked()
        self._audit("trading.kill_switch.updated", {"enabled": enabled})
        return self.status()

    def set_paper_running(self, enabled: bool, actor: str = "user") -> TradingStatus:
        self.control.paper_enabled = enabled
        self.risk_gate.paper_enabled = enabled
        self._audit(
            "trading.paper.control.updated",
            {
                "enabled": enabled,
                "actor": actor,
            },
        )
        event_bus.publish(
            event_type="paper.status_changed",
            session_id="trading",
            payload={"enabled": enabled, "actor": actor},
        )
        return self.status()

    def unlock_live(self, enabled: bool) -> TradingStatus:
        if enabled:
            req = self.request_unlock(target="live_trading", actor="user")
            self._audit(
                "risk.approval.requested",
                {
                    "request_id": str(req.request_id),
                    "target": req.target,
                    "action": req.action,
                    "status": req.status,
                    "source": "legacy_live_unlock_endpoint",
                },
            )
        else:
            self.control.live_enabled = False
            self.risk_gate.live_enabled = False
            req = self._latest_trade_enable_request("live_trading")
            if req and req.status in {"pending", "approved", "enabled"}:
                revoked = self.approvals.revoke(req.request_id, actor="user", reason="manual_lock")
                self._audit(
                    "risk.approval.revoked",
                    {
                        "request_id": str(revoked.request_id),
                        "target": revoked.target,
                        "action": revoked.action,
                        "status": revoked.status,
                        "source": "legacy_live_unlock_endpoint",
                    },
                )
                self._emit_approval_status_changed(revoked, actor="user", source="legacy_live_unlock_endpoint")
        self._audit("trading.live.updated", {"enabled": self.control.live_enabled})
        return self.status()

    def list_approvals(self) -> list[ApprovalRequest]:
        self.approvals.expire_stale()
        return self.approvals.list_requests()

    def get_approval(self, request_id: str) -> ApprovalRequest | None:
        self.approvals.expire_stale()
        return self.approvals.get(request_id)

    def request_unlock(self, *, target: str, actor: str = "user", context: dict[str, object] | None = None) -> ApprovalRequest:
        req = self.approvals.ensure_pending_request(
            target=target,
            action="request_trade_enable",
            context={
                "mode": settings.trading_mode,
                **dict(context or {}),
            },
            actor=actor,
        )
        self._audit(
            "risk.approval.requested",
            {
                "request_id": str(req.request_id),
                "target": req.target,
                "action": req.action,
                "status": req.status,
                "actor": actor,
                "context": req.context,
            },
        )
        self._emit_approval_status_changed(req, actor=actor, source="request_unlock")
        return req

    def approve_request(self, *, request_id: str, actor: str = "admin") -> ApprovalRequest:
        req = self.approvals.approve(request_id=request_id, actor=actor, reason="admin_approved")
        self._audit(
            "risk.approval.approved",
            {
                "request_id": str(req.request_id),
                "target": req.target,
                "action": req.action,
                "status": req.status,
                "actor": actor,
            },
        )
        self._emit_approval_status_changed(req, actor=actor, source="approve_request")
        return req

    def enable_request(self, *, request_id: str, actor: str = "admin") -> ApprovalRequest:
        req = self.approvals.enable(request_id=request_id, actor=actor, reason="admin_enabled")
        if req.target == "live_trading":
            # Keep real live disabled by default, but allow simulated-live flow after approval.
            self.control.live_enabled = True
            self.risk_gate.live_enabled = self.control.live_enabled
        self._audit(
            "risk.approval.enabled",
            {
                "request_id": str(req.request_id),
                "target": req.target,
                "action": req.action,
                "status": req.status,
                "actor": actor,
                "live_enabled": self.control.live_enabled,
            },
        )
        self._emit_approval_status_changed(req, actor=actor, source="enable_request")
        return req

    def revoke_request(self, *, request_id: str, actor: str = "admin") -> ApprovalRequest:
        req = self.approvals.revoke(request_id=request_id, actor=actor, reason="admin_revoked")
        if req.target == "live_trading":
            self.control.live_enabled = False
            self.risk_gate.live_enabled = False
        self._audit(
            "risk.approval.revoked",
            {
                "request_id": str(req.request_id),
                "target": req.target,
                "action": req.action,
                "status": req.status,
                "actor": actor,
            },
        )
        self._emit_approval_status_changed(req, actor=actor, source="revoke_request")
        return req

    def place_paper_order(self, request: PaperOrderRequest) -> PaperOrderResult:
        blocked, failure_results = self._evaluate_runtime_failure_conditions(
            request=request,
            source="paper_order",
        )
        if blocked:
            result = PaperOrderResult(
                accepted=False,
                reason="failure_condition_blocked",
                mode="paper",
                status="blocked",
                user_message="Paper trading blocked by runtime failure condition checks; kill switch enabled.",
            )
        else:
            result = self.paper_engine.place_order(request)
        self._update_risk_from_order(request=request, result=result, source="paper")
        self._audit(
            "trading.paper.order",
            {
                "accepted": result.accepted,
                "reason": result.reason,
                "mode": result.mode,
                "instrument_id": request.instrument_id,
                "side": request.side,
                "quantity": request.quantity,
                "order_type": request.order_type,
                "plan_id": request.plan_id,
                "evidence_pack_id": request.evidence_pack_id,
                "failure_results": [row.model_dump(mode="json") for row in failure_results],
            },
        )
        return result

    def place_live_order(self, request: PaperOrderRequest) -> PaperOrderResult:
        risk_decision = self.risk_gate.check_order(quantity=request.quantity, is_live=True)
        if not risk_decision.allowed and risk_decision.reason == "live_trading_disabled":
            approval = self.request_unlock(target="live_trading", actor="user")
            result = PaperOrderResult(
                accepted=False,
                reason="pending_approval",
                mode="live",
                status="pending_approval",
                request_id=str(approval.request_id),
                user_message="高风险交易已提交审批，当前状态为待审批（pending）。",
            )
        elif not risk_decision.allowed:
            result = PaperOrderResult(
                accepted=False,
                reason=risk_decision.reason,
                mode="live",
                status="rejected",
                user_message="订单未通过风险门禁校验。",
            )
        else:
            result = self.sim_broker.submit_and_reconcile(request)
        self._update_risk_from_order(request=request, result=result, source="live")
        self._audit(
            "trading.live.order",
            {
                "accepted": result.accepted,
                "reason": result.reason,
                "mode": result.mode,
                "status": result.status,
                "request_id": result.request_id,
                "order_id": str(result.order_id),
                "instrument_id": request.instrument_id,
                "side": request.side,
                "quantity": request.quantity,
                "order_type": request.order_type,
                "plan_id": request.plan_id,
                "evidence_pack_id": request.evidence_pack_id,
            },
        )
        return result

    def list_live_logs(self, limit: int = 200) -> list[SimBrokerLog]:
        return self.sim_broker.list_logs(limit=limit)

    def list_risk_events(self, limit: int = 50) -> list[RiskEvent]:
        return self.risk_events.list_recent(limit=limit)

    def update_account_risk(
        self,
        *,
        account_equity: float,
        source: str = "manual",
        metrics: dict[str, float | int | str] | None = None,
    ) -> TradingStatus:
        snapshot, events = self.risk_monitor.update(account_equity=account_equity, source=source)
        self._risk_snapshot = snapshot
        self._handle_risk_events(events=events, source=source, metrics=metrics or {})
        if snapshot.status == "blocked":
            self.control.kill_switch_enabled = True
            self.risk_gate.kill_switch_enabled = True
        return self.status()

    def _latest_trade_enable_request(self, target: str) -> ApprovalRequest | None:
        latest = self.approvals.latest_for_target(target=target, action="request_trade_enable")
        if latest is not None:
            return latest
        # Backward compatibility with earlier action name.
        return self.approvals.latest_for_target(target=target, action="unlock")

    def _audit(self, event_type: str, payload: dict[str, object]) -> None:
        self.audit_store.append(
            AuditLogEntry(
                trace_id=uuid4(),
                event_type=event_type,
                payload=payload,
            )
        )

    def _update_risk_from_order(self, *, request: PaperOrderRequest, result: PaperOrderResult, source: str) -> None:
        if not result.accepted:
            return
        base_price = float(result.fill_price or 100.0)
        notional = abs(float(request.quantity)) * max(0.01, base_price)
        micro_cost = max(0.5, notional * 0.00005)
        side = str(request.side).lower()
        signed = -micro_cost if side == "buy" else (micro_cost * 0.5)
        next_equity = max(1.0, float(self._risk_snapshot.account_equity) + signed)
        self.update_account_risk(
            account_equity=next_equity,
            source=f"{source}_order",
            metrics={
                "notional": round(notional, 6),
                "micro_cost": round(micro_cost, 6),
                "order_side": side,
            },
        )

    def _handle_risk_events(
        self,
        *,
        events: list[RiskEvent],
        source: str,
        metrics: dict[str, float | int | str],
    ) -> None:
        if not events:
            return
        for event in events:
            self.risk_events.append(event)
            payload = {
                "event_id": str(event.event_id),
                "event_type": event.event_type,
                "severity": event.severity,
                "message": event.message,
                "source": event.source,
                "metrics": {**event.metrics, **metrics},
                "created_at": event.created_at.isoformat(),
            }
            self._audit("risk.monitor.event", payload)
            event_bus.publish(
                event_type="risk.event",
                session_id="trading",
                payload=payload,
            )
        block_required = any(str(event.severity).lower() == "high" for event in events)
        # Hard enforcement: block-grade risk events force kill switch.
        if block_required and (not self.control.kill_switch_enabled):
            self.control.kill_switch_enabled = True
            self.risk_gate.kill_switch_enabled = True
            self._audit(
                "trading.kill_switch.auto_triggered",
                {
                    "source": source,
                    "reason": "risk_monitor_breach",
                    "event_count": len(events),
                },
            )
            event_bus.publish(
                event_type="risk.event",
                session_id="trading",
                payload={
                    "event_type": "kill_switch_auto_enabled",
                    "severity": "high",
                    "message": f"Auto kill switch enabled due to {source}.",
                    "event_count": len(events),
                },
            )

    def _evaluate_runtime_failure_conditions(
        self,
        *,
        request: PaperOrderRequest,
        source: str,
    ) -> tuple[bool, list[FailureConditionCheckResult]]:
        conditions = normalize_failure_conditions(
            request.failure_conditions,
            default_applies_to="strategy",
        )
        if not conditions:
            return False, []

        context: dict[str, Any] = {
            "instrument_id": request.instrument_id,
            "quantity": float(request.quantity),
            "market": str(request.instrument_id).split("_", 1)[0].upper(),
            **dict(request.failure_context),
        }
        results = self.failure_check_registry.evaluate(conditions=conditions, context=context)
        events: list[RiskEvent] = []
        blocked = False
        for result in results:
            level = str(result.level).lower()
            if level not in {"warn", "block"}:
                continue
            severity = "high" if level == "block" else "medium"
            blocked = blocked or (level == "block")
            events.append(
                RiskEvent(
                    event_type="failure_condition_block" if level == "block" else "failure_condition_warn",
                    severity=severity,
                    message=result.message,
                    source="failure_conditions",
                    metrics={
                        "code": result.code,
                        "level": level,
                        **result.metrics,
                    },
                )
            )
        if events:
            self._handle_risk_events(events=events, source=source, metrics={})
        return blocked, results

    def _emit_approval_status_changed(self, request: ApprovalRequest, *, actor: str, source: str) -> None:
        event_bus.publish(
            event_type="approval.status_changed",
            session_id="trading",
            payload={
                "request_id": str(request.request_id),
                "target": request.target,
                "action": request.action,
                "status": request.status,
                "actor": actor,
                "source": source,
            },
        )
