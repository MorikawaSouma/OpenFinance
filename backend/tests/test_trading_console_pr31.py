from pathlib import Path

from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.api.routes_trading import _service
from openfinance.core.config import settings


def test_approval_request_context_and_paper_control_gate(tmp_path: Path) -> None:
    settings.approval_db_file = str(tmp_path / "registry" / "approvals.sqlite3")
    settings.audit_log_file = str(tmp_path / "registry" / "audit.jsonl")
    _service.cache_clear()

    client = TestClient(app)

    requested = client.post(
        "/trading/approvals/request",
        json={
            "target": "live_trading",
            "use_case": "chat_console_unlock",
            "plan_id": "plan_pr31",
            "session_id": "session_pr31",
            "risk_statement_ack": True,
        },
    )
    assert requested.status_code == 200
    payload = requested.json()
    assert payload["status"] == "pending"
    context = payload["context"]
    assert context["use_case"] == "chat_console_unlock"
    assert context["plan_id"] == "plan_pr31"
    assert context["session_id"] == "session_pr31"
    assert context["risk_statement_ack"] is True

    stop_status = client.post("/trading/paper/control", json={"enabled": False})
    assert stop_status.status_code == 200
    assert stop_status.json()["paper_trading_enabled"] is False

    blocked = client.post(
        "/trading/paper/orders",
        json={
            "instrument_id": "us_eq_aapl",
            "side": "buy",
            "quantity": 10,
            "order_type": "market",
            "plan_id": "plan_pr31",
        },
    )
    assert blocked.status_code == 200
    assert blocked.json()["accepted"] is False
    assert blocked.json()["reason"] == "paper_trading_stopped"

    start_status = client.post("/trading/paper/control", json={"enabled": True})
    assert start_status.status_code == 200
    assert start_status.json()["paper_trading_enabled"] is True

    ok = client.post(
        "/trading/paper/orders",
        json={
            "instrument_id": "us_eq_aapl",
            "side": "buy",
            "quantity": 10,
            "order_type": "market",
            "plan_id": "plan_pr31",
        },
    )
    assert ok.status_code == 200
    assert ok.json()["accepted"] is True

