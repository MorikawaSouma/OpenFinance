from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable
from uuid import UUID

from openfinance.core.audit import AuditLogEntry, FileAuditStore
from openfinance.core.config import settings
from openfinance.data.registry import DatasetRegistry
from openfinance.markets.plugins import build_market_rules_provider
from openfinance.quant.backtest.run_registry import RunRegistry
from openfinance.trading.approval import ApprovalService


ToolFn = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass
class ToolSpec:
    name: str
    risk_level: str  # read | write | high_risk
    enabled: bool
    fn: ToolFn


class ToolRegistry:
    def __init__(self, audit_store: FileAuditStore) -> None:
        self.audit_store = audit_store
        self._tools: dict[str, ToolSpec] = {}
        self.approvals = ApprovalService(settings.approval_db_file)

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def list_tools(self) -> list[dict[str, str | bool]]:
        return [
            {"name": spec.name, "risk_level": spec.risk_level, "enabled": spec.enabled}
            for spec in self._tools.values()
        ]

    def call(
        self,
        *,
        tool_name: str,
        tool_input: dict[str, Any],
        caller_agent: str,
        model: str,
        trace_id: UUID,
        run_id: UUID | None = None,
    ) -> dict[str, Any]:
        if tool_name not in self._tools:
            raise ValueError(f"Tool not found: {tool_name}")
        spec = self._tools[tool_name]
        if not spec.enabled:
            raise PermissionError(f"Tool disabled: {tool_name}")

        approval_request_id: str | None = None
        if spec.risk_level == "high_risk":
            req = self.approvals.ensure_pending_request(
                target=f"tool:{tool_name}",
                action="high_risk_tool",
                context={"tool_input": tool_input},
                actor=caller_agent,
            )
            approval_request_id = str(req.request_id)
            if req.status in {"requested", "pending"}:
                self.audit_store.append(
                    AuditLogEntry(
                        trace_id=trace_id,
                        run_id=run_id,
                        event_type="risk.approval.requested",
                        payload={
                            "request_id": approval_request_id,
                            "target": req.target,
                            "action": req.action,
                            "status": req.status,
                            "actor": caller_agent,
                            "source": "tool_registry",
                        },
                    )
                )
                result = {
                    "status": "pending_approval",
                    "request_id": approval_request_id,
                    "reason": "high_risk_tool_requires_approval",
                }
                self.audit_store.append(
                    AuditLogEntry(
                        trace_id=trace_id,
                        run_id=run_id,
                        event_type="tool.call.pending_approval",
                        payload={
                            "caller_agent": caller_agent,
                            "model": model,
                            "tool_name": tool_name,
                            "input": tool_input,
                            "approval_request_id": approval_request_id,
                            "output": result,
                        },
                    )
                )
                return result
            if req.status == "approved":
                req = self.approvals.enable(
                    req.request_id,
                    actor="system",
                    reason=f"enabled_by_tool_call:{tool_name}",
                )
                approval_request_id = str(req.request_id)
                self.audit_store.append(
                    AuditLogEntry(
                        trace_id=trace_id,
                        run_id=run_id,
                        event_type="risk.approval.enabled",
                        payload={
                            "request_id": approval_request_id,
                            "target": req.target,
                            "action": req.action,
                            "status": req.status,
                            "actor": "system",
                            "source": "tool_registry",
                        },
                    )
                )
            if req.status != "enabled":
                return {
                    "status": "pending_approval",
                    "request_id": approval_request_id,
                    "reason": f"approval_not_enabled:{req.status}",
                }

        t0 = perf_counter()
        result = spec.fn(tool_input)
        if approval_request_id is not None and isinstance(result, dict):
            result = dict(result)
            result.setdefault("request_id", approval_request_id)
        latency_ms = int((perf_counter() - t0) * 1000)
        self.audit_store.append(
            AuditLogEntry(
                trace_id=trace_id,
                run_id=run_id,
                event_type="tool.call",
                payload={
                    "caller_agent": caller_agent,
                    "model": model,
                    "tool_name": tool_name,
                    "input": tool_input,
                    "output": result,
                    "latency_ms": latency_ms,
                    "approval_request_id": approval_request_id,
                },
            )
        )
        return result


def build_default_tool_registry(
    *, audit_store: FileAuditStore, dataset_registry: DatasetRegistry, run_registry: RunRegistry
) -> ToolRegistry:
    registry = ToolRegistry(audit_store=audit_store)
    market_rules = build_market_rules_provider()

    def read_dataset_versions(_: dict[str, Any]) -> dict[str, Any]:
        return {
            "items": [
                {
                    "dataset_id": entry.dataset_id,
                    "dataset_version": entry.dataset_version,
                    "seed": entry.seed,
                }
                for entry in dataset_registry.list_entries()
            ]
        }

    def read_run_versions(_: dict[str, Any]) -> dict[str, Any]:
        return {
            "items": [
                {
                    "run_id": str(entry.run_id),
                    "dataset_version": entry.dataset_version,
                    "strategy_version": entry.strategy_version,
                }
                for entry in run_registry.list_entries()
            ]
        }

    def read_market_rules(_: dict[str, Any]) -> dict[str, Any]:
        markets = ["US", "CN", "CRYPTO", "JP"]
        rows = []
        for market in markets:
            rules = market_rules.get(market)
            rows.append(
                {
                    "market": market,
                    "rule_class": type(rules).__name__,
                    "attrs": {
                        key: value
                        for key, value in vars(rules).items()
                        if isinstance(value, (str, int, float, bool))
                    },
                }
            )
        return {"items": rows}

    def read_risk_controls(_: dict[str, Any]) -> dict[str, Any]:
        return {
            "mode": settings.trading_mode,
            "live_enabled": bool(settings.enable_live_trading and not settings.live_trading_unlock_required),
            "kill_switch_enabled": settings.kill_switch_enabled,
            "risk_max_order_qty": settings.risk_max_order_qty,
            "live_unlock_required": settings.live_trading_unlock_required,
        }

    registry.register(
        ToolSpec(
            name="read_dataset_versions",
            risk_level="read",
            enabled=True,
            fn=read_dataset_versions,
        )
    )
    registry.register(
        ToolSpec(
            name="read_run_versions",
            risk_level="read",
            enabled=True,
            fn=read_run_versions,
        )
    )
    registry.register(
        ToolSpec(
            name="read_market_rules",
            risk_level="read",
            enabled=True,
            fn=read_market_rules,
        )
    )
    registry.register(
        ToolSpec(
            name="read_risk_controls",
            risk_level="read",
            enabled=True,
            fn=read_risk_controls,
        )
    )
    registry.register(
        ToolSpec(
            name="submit_live_order",
            risk_level="high_risk",
            enabled=True,
            fn=lambda payload: {"status": "simulated_live_order_submitted", "input": payload},
        )
    )
    return registry
