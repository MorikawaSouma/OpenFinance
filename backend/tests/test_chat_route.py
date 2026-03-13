from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.core.config import settings


def _wait_task_done(client: TestClient, task_id: str, timeout_s: float = 90.0) -> dict:
    import time

    start = time.time()
    while time.time() - start <= timeout_s:
        row = client.get(f"/workbench/tasks/{task_id}").json()
        if row.get("status") in {"done", "error", "failed", "canceled"}:
            return row
        time.sleep(0.1)
    raise TimeoutError(task_id)


def test_chat_message_and_history() -> None:
    previous_force_stub = settings.llm_force_stub
    settings.llm_force_stub = True
    client = TestClient(app)
    try:
        r = client.post(
            "/chat/message",
            json={"message": "为什么日经最近波动大，给我高夏普低回撤策略并给回测结果", "include_debug": True},
        )
        assert r.status_code == 200
        payload = r.json()
        assert "session_id" in payload
        assert "trace_id" in payload
        assert payload["mode"] == "pipeline_research"
        assert payload["language"] in {"zh", "en"}
        assert len(payload["assistant_message"]) > 0
        assert ("Task #" in payload["assistant_message"]) or ("任务 #" in payload["assistant_message"])
        assert isinstance(payload["cards"], list)
        card_types = {row["type"] for row in payload["cards"]}
        assert "summary" in card_types
        assert "next_steps" in card_types
        assert "debug" in payload
        assert payload["debug"]["trace_id"]
        assert payload["debug"]["parent_task_id"]
        parent_task_id = str(payload["debug"]["parent_task_id"])
        task_done = _wait_task_done(client, parent_task_id)
        assert task_done["status"] == "done"
        assert str((task_done.get("result_ref") or {}).get("run_id") or "").strip()
        assert len(payload["turns"]) >= 2

        session_id = payload["session_id"]
        h = client.get(f"/chat/sessions/{session_id}")
        assert h.status_code == 200
        turns = h.json()
        assert len(turns) >= 2
        assert turns[0]["role"] == "user"
    finally:
        settings.llm_force_stub = previous_force_stub


def test_chat_sessions_list() -> None:
    client = TestClient(app)
    client.post("/chat/message", json={"message": "session listing check"})
    r = client.get("/chat/sessions")
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_chat_multi_market_compare_routes_to_tasked_compare() -> None:
    client = TestClient(app)
    resp = client.post(
        "/chat/message",
        json={
            "message": "运行 US vs JP 多市场可比回测报告，重点看回撤和波动",
            "include_debug": True,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["mode"] == "multi_market_compare_report"
    card_types = [row.get("type") for row in payload.get("cards", [])]
    assert "summary" in card_types
    assert "next_steps" in card_types
    parent_task_id = str(payload.get("debug", {}).get("parent_task_id") or "")
    assert parent_task_id
    done = _wait_task_done(client, parent_task_id)
    assert done["status"] == "done"
    assert str((done.get("result_ref") or {}).get("open_path") or "").strip()

    next_steps = next((row for row in payload["cards"] if row.get("type") == "next_steps"), {})
    actions = next_steps.get("actions", [])
    open_task = next((row for row in actions if row.get("action") == "open_task"), None)
    assert open_task is not None
    assert str(open_task.get("payload", {}).get("parent_task_id") or "").strip()


def test_chat_multi_market_compare_failure_surfaces_error_card() -> None:
    client = TestClient(app)
    previous = settings.task_force_error
    settings.task_force_error = True
    try:
        resp = client.post(
            "/chat/message",
            json={
                "message": "运行 US vs JP 多市场可比回测报告，重点看回撤和波动",
                "include_debug": True,
            },
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["mode"] == "multi_market_compare_report"
        assert any(row.get("type") == "summary" for row in payload.get("cards", []))
        parent_task_id = str(payload.get("debug", {}).get("parent_task_id") or "")
        assert parent_task_id
        done = _wait_task_done(client, parent_task_id)
        assert done["status"] == "error"
        assert str(done.get("error") or "").strip()

        tasks = client.get("/workbench/tasks").json()
        mm_tasks = [row for row in tasks if row.get("task_type") == "multi_market.compare"]
        assert mm_tasks
        assert any(str(row.get("status")) == "error" for row in mm_tasks)
    finally:
        settings.task_force_error = previous
