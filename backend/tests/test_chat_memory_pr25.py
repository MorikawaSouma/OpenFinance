from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.api.routes_chat import _chat_store
from openfinance.core.chat import ChatStore
from openfinance.core.config import settings


def test_chat_store_persists_last_memory_fields(tmp_path: Path) -> None:
    store_path = tmp_path / "registry" / "chat_sessions.json"
    session_id = uuid4()

    first = ChatStore(str(store_path))
    first.get_or_create(session_id)
    first.append_turn(session_id, role="user", content="hello")
    first.set_last_context(
        session_id,
        last_plan_id="plan_a",
        last_run_id="run_a",
        last_report_id="run_a",
        last_dataset_version="dataset_a",
    )

    second = ChatStore(str(store_path))
    memory = second.get_last_memory(session_id)
    assert memory["last_plan_id"] == "plan_a"
    assert memory["last_run_id"] == "run_a"
    assert memory["last_report_id"] == "run_a"
    assert memory["last_dataset_version"] == "dataset_a"


def test_chat_sessions_include_memory_fields(tmp_path: Path) -> None:
    settings.chat_session_store_file = str(tmp_path / "registry" / "chat_sessions.json")
    _chat_store.cache_clear()
    client = TestClient(app)

    response = client.post("/chat/message", json={"message": "给我一套趋势策略并跑回测"})
    assert response.status_code == 200
    session_id = response.json()["session_id"]

    rows = client.get("/chat/sessions")
    assert rows.status_code == 200
    matched = [row for row in rows.json() if row.get("session_id") == session_id]
    assert len(matched) == 1
    row = matched[0]
    assert row.get("last_plan_id")
    assert row.get("last_run_id")
    assert row.get("last_report_id")
    assert row.get("last_dataset_version")
    UUID(str(row["session_id"]))
