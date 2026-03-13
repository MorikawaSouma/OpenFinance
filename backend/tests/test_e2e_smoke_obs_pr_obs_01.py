import time

from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.core.config import settings
from openfinance.core.events import event_bus


def _wait_task(client: TestClient, task_id: str, timeout_s: float = 120.0) -> dict:
    start = time.time()
    while time.time() - start <= timeout_s:
        row = client.get(f"/workbench/tasks/{task_id}").json()
        if row.get("status") in {"done", "error", "failed", "canceled"}:
            return row
        time.sleep(0.15)
    raise TimeoutError(task_id)


def test_obs_01_chat_response_contains_risk_and_approval_snapshots() -> None:
    client = TestClient(app)
    resp = client.post("/chat/message", json={"message": "Nikkei recent trend?", "include_debug": True})
    assert resp.status_code == 200
    payload = resp.json()
    risk = payload.get("risk_snapshot") or {}
    approvals = payload.get("approvals_snapshot") or {}
    assert isinstance(risk, dict)
    assert str(risk.get("updated_at") or "").strip()
    assert isinstance(approvals.get("items"), list)
    assert str(approvals.get("updated_at") or "").strip()


def test_obs_02_preflight_block_then_adjust_creates_pipeline_task() -> None:
    previous_force_stub = settings.llm_force_stub
    settings.llm_force_stub = True
    client = TestClient(app)
    try:
        first = client.post(
            "/chat/message",
            json={
                "message": "For CN market, migrate a US high-frequency intraday strategy and run backtest.",
                "include_debug": True,
            },
        )
        assert first.status_code == 200
        payload = first.json()
        debug = payload.get("debug") or {}
        assert debug.get("preflight_blocked") is True

        actions = []
        for card in payload.get("cards", []):
            rows = card.get("actions") if isinstance(card, dict) else None
            if isinstance(rows, list):
                actions.extend(rows)
        adjust_prompt = ""
        proceed_prompt = ""
        for row in actions:
            act_payload = row.get("payload") if isinstance(row, dict) else {}
            message = str((act_payload or {}).get("message") or "")
            if message.startswith("__preflight__:adjust:"):
                adjust_prompt = message
            if message.startswith("__preflight__:proceed:"):
                proceed_prompt = message
        assert adjust_prompt
        assert proceed_prompt

        proceed = client.post(
            "/chat/message",
            json={
                "session_id": payload["session_id"],
                "message": proceed_prompt,
                "include_debug": True,
            },
        )
        assert proceed.status_code == 200
        proceed_payload = proceed.json()
        assert proceed_payload.get("mode") == "pipeline_preflight_gate"

        adjusted = client.post(
            "/chat/message",
            json={
                "session_id": payload["session_id"],
                "message": adjust_prompt,
                "include_debug": True,
            },
        )
        assert adjusted.status_code == 200
        adjusted_payload = adjusted.json()
        adjusted_debug = adjusted_payload.get("debug") or {}
        parent_task_id = str(adjusted_debug.get("parent_task_id") or "")
        assert parent_task_id
    finally:
        settings.llm_force_stub = previous_force_stub


def test_obs_03_04_pipeline_heartbeat_and_dev_events_and_result_summary() -> None:
    previous_force_stub = settings.llm_force_stub
    settings.llm_force_stub = True
    client = TestClient(app)
    try:
        run_resp = client.post(
            "/chat/message",
            json={
                "message": "Based on current JP market, give me a low drawdown strategy and run backtest.",
                "include_debug": True,
            },
        )
        assert run_resp.status_code == 200
        payload = run_resp.json()
        debug = payload.get("debug") or {}
        trace_id = str(payload.get("trace_id") or "")
        parent_task_id = str(debug.get("parent_task_id") or "")
        assert parent_task_id

        done = _wait_task(client, parent_task_id, timeout_s=180.0)
        assert done.get("status") == "done"
        meta = done.get("meta") or {}
        assert str(meta.get("last_stage") or "").strip()
        assert str(meta.get("last_heartbeat_at") or "").strip()

        result = done.get("result") or {}
        summary = result.get("summary") or {}
        assert isinstance(summary, dict)
        assert str(summary.get("selected_strategy") or "").strip()
        assert str(summary.get("evidence_pack_id") or "").strip()
        assert str(summary.get("trace_id") or "").strip()
        assert isinstance(result.get("pipeline_response"), dict)

        all_events = list(event_bus.snapshot())
        trace_events = [row for row in all_events if str(row.get("trace_id") or "") == trace_id]
        event_types = {str(row.get("type") or "") for row in trace_events}
        assert "task.heartbeat" in event_types

        audit_rows = client.get(f"/workbench/audit?trace_id={trace_id}").json()
        audit_types = {str(row.get("event_type") or "") for row in audit_rows}
        assert "agent.dispatched" in audit_types
        assert "tool.call.finished" in audit_types
        assert "artifact.created" in audit_types
        assert "audit.tail" in audit_types
    finally:
        settings.llm_force_stub = previous_force_stub

