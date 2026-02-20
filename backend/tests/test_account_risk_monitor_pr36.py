from pathlib import Path

from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.api.routes_trading import _service
from openfinance.core.config import settings
from openfinance.core.events import event_bus


def _configure_paths(tmp_path: Path) -> None:
    settings.approval_db_file = str(tmp_path / "registry" / "approvals.sqlite3")
    settings.audit_log_file = str(tmp_path / "registry" / "audit.jsonl")
    settings.risk_events_db_file = str(tmp_path / "registry" / "risk_events.sqlite3")
    settings.risk_max_account_drawdown = 0.05
    settings.risk_abnormal_volatility_threshold = 0.03
    settings.risk_volatility_window = 20
    settings.risk_monitor_initial_equity = 1_000_000.0


def test_pr36_drawdown_breach_auto_kill_switch_and_sse(tmp_path: Path) -> None:
    _configure_paths(tmp_path)
    settings.risk_max_account_drawdown = 0.05
    settings.risk_abnormal_volatility_threshold = 0.03
    settings.risk_volatility_window = 6
    settings.risk_monitor_initial_equity = 1_000_000.0
    _service.cache_clear()

    client = TestClient(app)
    initial = client.get("/trading/status")
    assert initial.status_code == 200
    assert initial.json()["kill_switch_enabled"] is False

    tick_1 = client.post(
        "/trading/risk/heartbeat",
        json={"account_equity": 1_000_000.0, "source": "mock_bar", "metrics": {"bar": 1}},
    )
    assert tick_1.status_code == 200
    assert tick_1.json()["risk_status"] in {"normal", "warn", "blocked"}

    tick_2 = client.post(
        "/trading/risk/heartbeat",
        json={"account_equity": 940_000.0, "source": "mock_bar", "metrics": {"bar": 2}},
    )
    assert tick_2.status_code == 200
    payload = tick_2.json()
    assert payload["kill_switch_enabled"] is True
    assert payload["risk_status"] == "blocked"
    assert float(payload["current_drawdown"]) >= 0.05

    events = client.get("/trading/risk/events?limit=20")
    assert events.status_code == 200
    rows = events.json()
    assert any(row["event_type"] == "max_account_drawdown_breach" for row in rows)
    assert any("账户回撤超过 5.0% 已自动停机" in row["message"] for row in rows)

    blocked = client.post(
        "/trading/paper/orders",
        json={
            "instrument_id": "us_eq_aapl",
            "side": "buy",
            "quantity": 10,
            "order_type": "market",
            "plan_id": "plan_pr36_drawdown",
        },
    )
    assert blocked.status_code == 200
    assert blocked.json()["accepted"] is False
    assert blocked.json()["reason"] == "kill_switch_enabled"

    sse_rows = [row for row in event_bus.snapshot() if row.get("type") == "risk.event"]
    assert any((row.get("payload") or {}).get("event_type") == "max_account_drawdown_breach" for row in sse_rows)


def test_pr36_abnormal_volatility_breach_triggers_block(tmp_path: Path) -> None:
    _configure_paths(tmp_path)
    settings.risk_max_account_drawdown = 0.5
    settings.risk_abnormal_volatility_threshold = 0.02
    settings.risk_volatility_window = 4
    settings.risk_monitor_initial_equity = 1_000_000.0
    _service.cache_clear()
    client = TestClient(app)

    for idx, equity in enumerate([1_000_000.0, 1_120_000.0, 970_000.0, 1_150_000.0], start=1):
        row = client.post(
            "/trading/risk/heartbeat",
            json={"account_equity": equity, "source": "mock_vol", "metrics": {"bar": idx}},
        )
        assert row.status_code == 200

    status = client.get("/trading/status")
    assert status.status_code == 200
    payload = status.json()
    assert payload["kill_switch_enabled"] is True
    assert payload["risk_status"] == "blocked"
    assert float(payload["current_volatility"]) >= settings.risk_abnormal_volatility_threshold

    events = client.get("/trading/risk/events?limit=20")
    assert events.status_code == 200
    rows = events.json()
    assert any(row["event_type"] == "abnormal_volatility_breach" for row in rows)
