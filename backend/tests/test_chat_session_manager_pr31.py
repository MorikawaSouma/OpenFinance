from pathlib import Path

from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.api.routes_chat import _audit_store, _chat_store, _pipeline_engine
from openfinance.core.config import settings


def test_chat_session_compare_uses_last_two_runs_without_manual_run_id(tmp_path: Path) -> None:
    settings.chat_session_store_file = str(tmp_path / "registry" / "chat_sessions.json")
    settings.audit_log_file = str(tmp_path / "registry" / "audit.jsonl")
    settings.dataset_registry_file = str(tmp_path / "registry" / "datasets.jsonl")
    settings.run_registry_file = str(tmp_path / "registry" / "runs.jsonl")
    settings.plan_registry_file = str(tmp_path / "registry" / "plans.jsonl")
    settings.data_root = str(tmp_path / "data")
    _chat_store.cache_clear()
    _pipeline_engine.cache_clear()
    _audit_store.cache_clear()

    client = TestClient(app)

    first = client.post("/chat/message", json={"message": "build a trend strategy and run backtest"})
    assert first.status_code == 200
    session_id = first.json()["session_id"]
    first_run_id = str(first.json()["developer_payload"]["run_id"])

    second = client.post(
        "/chat/message",
        json={"session_id": session_id, "message": "double commission and slippage then run again"},
    )
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["developer_payload"]["intent"] == "modify_last_run"
    second_run_id = str(second_payload["developer_payload"]["run_id"])
    assert second_run_id != first_run_id

    third = client.post(
        "/chat/message",
        json={"session_id": session_id, "message": "why worse than last run?"},
    )
    assert third.status_code == 200
    payload = third.json()
    assert payload["developer_payload"]["intent"] == "session_compare"
    assert "run_compare" in payload["developer_payload"]
    assert "run_compare" in payload["cards"]
    compare = payload["developer_payload"]["run_compare"]
    assert str(compare["current_run_id"]) == second_run_id
    assert str(compare["baseline_run_id"]) == first_run_id
    assert len(compare["metrics_diff"]) > 0
    assert "cost_diff" in compare

