import time

from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.core.config import settings
from openfinance.core.events import event_bus


def _wait_task(client: TestClient, task_id: str, timeout_s: float = 180.0) -> dict:
    start = time.time()
    while time.time() - start <= timeout_s:
        row = client.get(f"/workbench/tasks/{task_id}").json()
        if row.get("status") in {"done", "error", "failed", "canceled"}:
            return row
        time.sleep(0.15)
    raise TimeoutError(task_id)


def test_rv03_general_info_query_contains_minimal_reasoning_steps() -> None:
    previous_force_stub = settings.llm_force_stub
    settings.llm_force_stub = True
    client = TestClient(app)
    try:
        resp = client.post(
            "/chat/message",
            json={"message": "How is Nikkei recently?", "include_debug": True},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload.get("mode") == "general_info_query"
        trace_id = str(payload.get("trace_id") or "")
        debug = payload.get("debug") or {}
        steps = debug.get("reasoning_steps") or []
        assert isinstance(steps, list)
        assert len(steps) >= 3
        step_types = {str(row.get("step_type") or "") for row in steps if isinstance(row, dict)}
        assert {"hypothesis", "evidence_use", "decision"}.issubset(step_types)

        trace_events = [
            row
            for row in event_bus.snapshot()
            if str(row.get("trace_id") or "") == trace_id
        ]
        event_types = {str(row.get("type") or "") for row in trace_events}
        assert "reasoning.step.created" in event_types
        assert "reasoning.trace.final" in event_types
    finally:
        settings.llm_force_stub = previous_force_stub


def test_rv02_pipeline_contains_counterevidence_step_for_kahneman() -> None:
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
        parent_task_id = str(debug.get("parent_task_id") or "")
        trace_id = str(payload.get("trace_id") or "")
        assert parent_task_id
        done = _wait_task(client, parent_task_id)
        assert done.get("status") == "done"

        reasoning_steps = (done.get("result") or {}).get("reasoning_steps") or []
        assert isinstance(reasoning_steps, list)
        kahneman_steps = [
            row
            for row in reasoning_steps
            if isinstance(row, dict) and str(row.get("agent_name") or "") == "Kahneman"
        ]
        assert kahneman_steps
        assert any(str(row.get("step_type") or "") == "counterevidence_use" for row in kahneman_steps)
        assert any(len((row.get("evidence_refs") or [])) >= 1 for row in kahneman_steps)

        trace_events = [
            row
            for row in event_bus.snapshot()
            if str(row.get("trace_id") or "") == trace_id
            and str(row.get("type") or "") == "reasoning.step.created"
        ]
        assert trace_events
    finally:
        settings.llm_force_stub = previous_force_stub


def test_rv02_parse_error_falls_back_to_safe_reasoning_steps() -> None:
    previous_force_stub = settings.llm_force_stub
    previous_force_parse_error = settings.agent_force_step_parse_error
    settings.llm_force_stub = True
    settings.agent_force_step_parse_error = True
    client = TestClient(app)
    try:
        evidence = client.get(
            "/knowledge/evidence/mock",
            params={"query": "macro liquidity inflation risk parity", "top_k": 6},
        )
        assert evidence.status_code == 200
        evidence_pack_id = evidence.json()["evidence_pack_id"]

        resp = client.post(
            "/orchestrator/run",
            json={
                "question": "Build a robust JP allocation thesis.",
                "active_agents": ["Buffett"],
                "evidence_pack_id": evidence_pack_id,
                "developer_mode": True,
            },
        )
        assert resp.status_code == 200
        outputs = resp.json().get("outputs") or []
        assert len(outputs) == 1
        output = outputs[0]
        steps = output.get("reasoning_steps") or []
        assert any(str(row.get("step_type") or "") == "hypothesis" for row in steps)
        assert any(str(row.get("step_type") or "") == "decision" for row in steps)
        assert any(
            str(row.get("step_type") or "") == "warning" and str(row.get("parse_error") or "").strip()
            for row in steps
        )
        assert str(output.get("prompt_used") or "").startswith("sha1:")
    finally:
        settings.llm_force_stub = previous_force_stub
        settings.agent_force_step_parse_error = previous_force_parse_error
