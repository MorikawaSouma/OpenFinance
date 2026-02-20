import json
from pathlib import Path

from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.api.routes_orchestrator import _build_orchestrator
from openfinance.api.routes_trading import _service
from openfinance.core.config import settings


def test_trading_approval_state_machine_and_audit(tmp_path: Path) -> None:
    settings.approval_db_file = str(tmp_path / "registry" / "approvals.sqlite3")
    settings.audit_log_file = str(tmp_path / "registry" / "audit.jsonl")
    _service.cache_clear()

    client = TestClient(app)
    requested = client.post("/trading/approvals/request", json={"target": "live_trading"})
    assert requested.status_code == 200
    req = requested.json()
    assert req["status"] == "pending"
    request_id = req["request_id"]

    approved = client.post(f"/trading/approvals/{request_id}/approve", json={"actor": "admin"})
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    enabled = client.post(f"/trading/approvals/{request_id}/enable", json={"actor": "admin"})
    assert enabled.status_code == 200
    assert enabled.json()["status"] == "enabled"

    status = client.get("/trading/status")
    assert status.status_code == 200
    assert status.json()["live_approval_state"] == "enabled"

    revoked = client.post(f"/trading/approvals/{request_id}/revoke", json={"actor": "admin"})
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"

    rows = client.get("/trading/approvals")
    assert rows.status_code == 200
    assert any(row["request_id"] == request_id for row in rows.json())

    audit_path = Path(settings.audit_log_file)
    assert audit_path.exists()
    lines = [line for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any('"event_type": "risk.approval.requested"' in line for line in lines)
    assert any('"event_type": "risk.approval.approved"' in line for line in lines)
    assert any('"event_type": "risk.approval.enabled"' in line for line in lines)
    assert any('"event_type": "risk.approval.revoked"' in line for line in lines)


def test_high_risk_tool_call_requires_approval_and_references_request_id(tmp_path: Path) -> None:
    settings.approval_db_file = str(tmp_path / "registry" / "approvals.sqlite3")
    settings.audit_log_file = str(tmp_path / "registry" / "audit.jsonl")
    _service.cache_clear()
    _build_orchestrator.cache_clear()

    client = TestClient(app)
    first = client.post(
        "/orchestrator/run",
        json={
            "prompt": "attempt live order",
            "active_agents": ["RiskManager"],
            "tool_calls": ["submit_live_order"],
        },
    )
    assert first.status_code == 200
    tool_first = first.json()["tool_results"]["submit_live_order"]
    assert tool_first["status"] == "pending_approval"
    request_id = tool_first["request_id"]

    approve = client.post(f"/trading/approvals/{request_id}/approve", json={"actor": "admin"})
    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"

    second = client.post(
        "/orchestrator/run",
        json={
            "prompt": "attempt live order again",
            "active_agents": ["RiskManager"],
            "tool_calls": ["submit_live_order"],
        },
    )
    assert second.status_code == 200
    tool_second = second.json()["tool_results"]["submit_live_order"]
    assert tool_second["status"] == "simulated_live_order_submitted"
    assert tool_second["request_id"] == request_id

    audit_path = Path(settings.audit_log_file)
    lines = [line for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    parsed = [json.loads(line) for line in lines]
    tool_calls = [row for row in parsed if row.get("event_type") == "tool.call"]
    assert len(tool_calls) >= 1
    assert any((row.get("payload") or {}).get("approval_request_id") == request_id for row in tool_calls)
