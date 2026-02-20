from pathlib import Path

from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.api.routes_trading import _service
from openfinance.core.config import settings


def test_trading_status_and_guards(tmp_path: Path) -> None:
    settings.approval_db_file = str(tmp_path / "registry" / "approvals.sqlite3")
    settings.audit_log_file = str(tmp_path / "registry" / "audit.jsonl")
    _service.cache_clear()
    client = TestClient(app)

    status = client.get("/trading/status")
    assert status.status_code == 200
    status_payload = status.json()
    assert status_payload["live_trading_enabled"] is False

    paper_order = client.post(
        "/trading/paper/orders",
        json={
            "instrument_id": "us_eq_aapl",
            "side": "buy",
            "quantity": 100,
            "order_type": "market",
            "plan_id": "plan_test_pr6",
        },
    )
    assert paper_order.status_code == 200
    assert paper_order.json()["accepted"] is True

    live_order = client.post(
        "/trading/live/orders",
        json={
            "instrument_id": "us_eq_aapl",
            "side": "buy",
            "quantity": 10,
            "order_type": "market",
            "evidence_pack_id": "evidence_test_pr6",
        },
    )
    assert live_order.status_code == 200
    assert live_order.json()["accepted"] is False
    assert live_order.json()["reason"] == "pending_approval"
    assert live_order.json()["status"] == "pending_approval"
    assert live_order.json()["request_id"]

    client.post("/trading/kill-switch", json={"enabled": True})
    blocked_paper_order = client.post(
        "/trading/paper/orders",
        json={
            "instrument_id": "us_eq_aapl",
            "side": "buy",
            "quantity": 10,
            "order_type": "market",
            "plan_id": "plan_test_pr6",
        },
    )
    assert blocked_paper_order.status_code == 200
    assert blocked_paper_order.json()["accepted"] is False
    assert blocked_paper_order.json()["reason"] == "kill_switch_enabled"
