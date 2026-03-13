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


def _assert_pipeline_market(
    *,
    client: TestClient,
    session_id: str,
    parent_task_id: str,
    expected_market: str,
) -> None:
    parent = _wait_task(client, parent_task_id, timeout_s=120.0)
    assert parent["status"] == "done"
    assert str((parent.get("meta") or {}).get("market") or "").strip().upper() == expected_market
    assert str((parent.get("result") or {}).get("market") or "").strip().upper() == expected_market

    tasks = client.get(f"/workbench/tasks?session_id={session_id}").json()
    children = [row for row in tasks if str(row.get("parent_task_id") or "") == parent_task_id]
    assert len(children) >= 3
    done_children = [row for row in children if str(row.get("status")).lower() == "done"]
    assert len(done_children) >= 3

    for row in done_children:
        assert str((row.get("meta") or {}).get("market") or "").strip().upper() == expected_market
        run_id = str((row.get("result_ref") or {}).get("run_id") or "").strip()
        assert run_id
        report = client.get(f"/workbench/runs/{run_id}").json()
        assert str(report.get("market") or "").strip().upper() == expected_market


def test_market_context_case1_explicit_jp_pipeline_and_variants_are_jp() -> None:
    previous_force_stub = settings.llm_force_stub
    settings.llm_force_stub = True
    client = TestClient(app)
    try:
        message = "\u57fa\u4e8e\u5f53\u524dJP\u5e02\u573a\uff0c\u7ed9\u6211\u4e00\u4e2a\u4f4e\u56de\u64a4\u7b56\u7565\u5e76\u56de\u6d4b"
        resp = client.post("/chat/message", json={"message": message, "include_debug": True})
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["mode"] == "pipeline_research"
        session_id = payload["session_id"]
        parent_task_id = str(payload.get("debug", {}).get("parent_task_id") or "")
        assert parent_task_id
        _assert_pipeline_market(
            client=client,
            session_id=session_id,
            parent_task_id=parent_task_id,
            expected_market="JP",
        )
    finally:
        settings.llm_force_stub = previous_force_stub


def test_market_context_case2_context_jp_then_pipeline_uses_jp() -> None:
    previous_force_stub = settings.llm_force_stub
    settings.llm_force_stub = True
    client = TestClient(app)
    try:
        first = client.post(
            "/chat/message",
            json={"message": "How is Nikkei recently?", "include_debug": True},
        )
        assert first.status_code == 200
        first_payload = first.json()
        assert first_payload["mode"] == "general_info_query"
        session_id = first_payload["session_id"]

        second = client.post(
            "/chat/message",
            json={
                "session_id": session_id,
                "message": "Give me a low-drawdown strategy and run backtest.",
                "include_debug": True,
            },
        )
        assert second.status_code == 200
        second_payload = second.json()
        assert second_payload["mode"] == "pipeline_research"
        parent_task_id = str(second_payload.get("debug", {}).get("parent_task_id") or "")
        assert parent_task_id
        _assert_pipeline_market(
            client=client,
            session_id=session_id,
            parent_task_id=parent_task_id,
            expected_market="JP",
        )
    finally:
        settings.llm_force_stub = previous_force_stub


def test_market_context_case3_explicit_us_overrides_session_jp() -> None:
    previous_force_stub = settings.llm_force_stub
    settings.llm_force_stub = True
    client = TestClient(app)
    try:
        first = client.post(
            "/chat/message",
            json={"message": "How is Nikkei recently?", "include_debug": True},
        )
        assert first.status_code == 200
        session_id = first.json()["session_id"]

        second = client.post(
            "/chat/message",
            json={
                "session_id": session_id,
                "message": "Based on US market, run a low-drawdown strategy and backtest.",
                "include_debug": True,
            },
        )
        assert second.status_code == 200
        second_payload = second.json()
        assert second_payload["mode"] == "pipeline_research"
        parent_task_id = str(second_payload.get("debug", {}).get("parent_task_id") or "")
        assert parent_task_id
        _assert_pipeline_market(
            client=client,
            session_id=session_id,
            parent_task_id=parent_task_id,
            expected_market="US",
        )
    finally:
        settings.llm_force_stub = previous_force_stub
