from pathlib import Path

from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.api.routes_trading import _service
from openfinance.core.config import settings


def test_live_order_pending_then_enabled_with_sim_logs(tmp_path: Path) -> None:
    settings.approval_db_file = str(tmp_path / "registry" / "approvals.sqlite3")
    settings.audit_log_file = str(tmp_path / "registry" / "audit.jsonl")
    _service.cache_clear()
    client = TestClient(app)

    pending = client.post(
        "/trading/live/orders",
        json={
            "instrument_id": "sim_us_aapl",
            "side": "buy",
            "quantity": 10,
            "order_type": "market",
            "plan_id": "plan_test_pr18",
        },
    )
    assert pending.status_code == 200
    payload = pending.json()
    assert payload["accepted"] is False
    assert payload["reason"] == "pending_approval"
    assert payload["status"] == "pending_approval"
    request_id = payload["request_id"]
    assert isinstance(request_id, str) and request_id

    approved = client.post(f"/trading/approvals/{request_id}/approve", json={"actor": "admin"})
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    enabled = client.post(f"/trading/approvals/{request_id}/enable", json={"actor": "admin"})
    assert enabled.status_code == 200
    assert enabled.json()["status"] == "enabled"

    executed = client.post(
        "/trading/live/orders",
        json={
            "instrument_id": "sim_us_aapl",
            "side": "buy",
            "quantity": 10,
            "order_type": "market",
            "evidence_pack_id": "evidence_test_pr18",
        },
    )
    assert executed.status_code == 200
    filled = executed.json()
    assert filled["accepted"] is True
    assert filled["reason"] == "sim_live_filled"
    assert filled["status"] == "filled"
    assert len(filled["log_refs"]) == 3

    logs = client.get("/trading/live/logs?limit=20")
    assert logs.status_code == 200
    rows = logs.json()
    assert len(rows) >= 3
    stages = {row["stage"] for row in rows}
    assert "order_submitted" in stages
    assert "order_filled" in stages
    assert "order_reconciled" in stages
