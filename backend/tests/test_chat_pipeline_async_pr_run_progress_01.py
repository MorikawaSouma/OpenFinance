import time

from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.core.config import settings


def _wait_task(client: TestClient, task_id: str, timeout_s: float = 90.0) -> dict:
    start = time.time()
    while time.time() - start <= timeout_s:
        row = client.get(f"/workbench/tasks/{task_id}").json()
        if row.get("status") in {"done", "error", "failed", "canceled"}:
            return row
        time.sleep(0.1)
    raise TimeoutError(task_id)


def test_pr_run_progress_01_case1_jp_general_then_pipeline_async_task_visible() -> None:
    previous_force_stub = settings.llm_force_stub
    settings.llm_force_stub = True
    client = TestClient(app)
    try:
        general = client.post(
            "/chat/message",
            json={"message": "日经最近如何？", "include_debug": True},
        )
        assert general.status_code == 200
        general_payload = general.json()
        assert general_payload["mode"] == "general_info_query"
        session_id = general_payload["session_id"]

        run_resp = client.post(
            "/chat/message",
            json={
                "session_id": session_id,
                "message": "基于当前JP市场，给我一个低回撤策略并回测。",
                "include_debug": True,
            },
        )
        assert run_resp.status_code == 200
        payload = run_resp.json()
        assert payload["mode"] == "pipeline_research"
        parent_task_id = str(payload.get("debug", {}).get("parent_task_id") or "")
        assert parent_task_id

        tasks_now = client.get(f"/workbench/tasks?session_id={session_id}").json()
        assert any(str(row.get("task_id")) == parent_task_id for row in tasks_now)

        parent_done = _wait_task(client, parent_task_id)
        assert parent_done["status"] == "done"
        assert str((parent_done.get("result_ref") or {}).get("run_id") or "").strip()

        tasks_final = client.get(f"/workbench/tasks?session_id={session_id}").json()
        children = [row for row in tasks_final if str(row.get("parent_task_id") or "") == parent_task_id]
        assert len(children) >= 1
        assert any(str(row.get("status")) == "done" for row in children)

        turns = client.get(f"/chat/sessions/{session_id}").json()
        assert len(turns) >= 2
        assert any("Task #" in str(row.get("content", "")) or "任务 #" in str(row.get("content", "")) for row in turns)
    finally:
        settings.llm_force_stub = previous_force_stub


def test_pr_run_progress_01_case2_variant_failure_surfaces_parent_and_child_error() -> None:
    client = TestClient(app)
    previous_force_stub = settings.llm_force_stub
    settings.llm_force_stub = True
    previous = settings.pipeline_force_variant_error
    settings.pipeline_force_variant_error = True
    try:
        run_resp = client.post(
            "/chat/message",
            json={"message": "Give me a US low-drawdown strategy and run backtest.", "include_debug": True},
        )
        assert run_resp.status_code == 200
        payload = run_resp.json()
        assert payload["mode"] == "pipeline_research"
        session_id = payload["session_id"]
        parent_task_id = str(payload.get("debug", {}).get("parent_task_id") or "")
        assert parent_task_id

        parent_done = _wait_task(client, parent_task_id)
        assert parent_done["status"] == "error"
        assert str(parent_done.get("error") or "").strip()

        tasks_final = client.get(f"/workbench/tasks?session_id={session_id}").json()
        children = [row for row in tasks_final if str(row.get("parent_task_id") or "") == parent_task_id]
        assert len(children) >= 1
        assert any(str(row.get("status")) == "error" for row in children)
        assert any(str(row.get("error") or "").strip() for row in children)
    finally:
        settings.llm_force_stub = previous_force_stub
        settings.pipeline_force_variant_error = previous
