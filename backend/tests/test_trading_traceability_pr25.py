import json
from pathlib import Path

from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.api.routes_trading import _service
from openfinance.core.config import settings
from openfinance.core.events import event_bus


def test_approval_get_by_id_and_sse_status_changed(tmp_path: Path) -> None:
    settings.approval_db_file = str(tmp_path / "registry" / "approvals.sqlite3")
    settings.audit_log_file = str(tmp_path / "registry" / "audit.jsonl")
    _service.cache_clear()

    client = TestClient(app)
    requested = client.post("/trading/approvals/request", json={"target": "live_trading"})
    assert requested.status_code == 200
    request_id = requested.json()["request_id"]

    fetched = client.get(f"/trading/approvals/{request_id}")
    assert fetched.status_code == 200
    assert fetched.json()["request_id"] == request_id
    assert fetched.json()["status"] == "pending"

    approved = client.post(f"/trading/approvals/{request_id}/approve", json={"actor": "admin"})
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    events = event_bus.snapshot()
    rows = [
        ev
        for ev in events
        if ev.get("type") == "approval.status_changed"
        and str((ev.get("payload") or {}).get("request_id")) == request_id
    ]
    assert len(rows) >= 2
    statuses = {str((row.get("payload") or {}).get("status")) for row in rows}
    assert "pending" in statuses
    assert "approved" in statuses


def test_order_traceability_guard_and_audit_references(tmp_path: Path) -> None:
    settings.approval_db_file = str(tmp_path / "registry" / "approvals.sqlite3")
    settings.audit_log_file = str(tmp_path / "registry" / "audit.jsonl")
    _service.cache_clear()
    client = TestClient(app)

    missing = client.post(
        "/trading/paper/orders",
        json={"instrument_id": "us_eq_aapl", "side": "buy", "quantity": 10, "order_type": "market"},
    )
    assert missing.status_code == 400
    assert "plan_id or evidence_pack_id" in missing.json()["detail"]

    ok_paper = client.post(
        "/trading/paper/orders",
        json={
            "instrument_id": "us_eq_aapl",
            "side": "buy",
            "quantity": 10,
            "order_type": "market",
            "plan_id": "plan_pr25_trace",
        },
    )
    assert ok_paper.status_code == 200

    ok_live = client.post(
        "/trading/live/orders",
        json={
            "instrument_id": "us_eq_aapl",
            "side": "buy",
            "quantity": 10,
            "order_type": "market",
            "evidence_pack_id": "ep_pr25_trace",
        },
    )
    assert ok_live.status_code == 200
    assert ok_live.json()["reason"] == "pending_approval"

    audit_path = Path(settings.audit_log_file)
    lines = [line for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [json.loads(line) for line in lines]
    paper_audit = [row for row in rows if row.get("event_type") == "trading.paper.order"]
    live_audit = [row for row in rows if row.get("event_type") == "trading.live.order"]
    assert any((row.get("payload") or {}).get("plan_id") == "plan_pr25_trace" for row in paper_audit)
    assert any((row.get("payload") or {}).get("evidence_pack_id") == "ep_pr25_trace" for row in live_audit)
