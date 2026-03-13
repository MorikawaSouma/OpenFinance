from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.core.config import settings
from openfinance.quant.backtest.run_registry import RunRegistry


def _wait_task_done(client: TestClient, task_id: str, timeout_s: float = 30.0) -> dict:
    import time

    start = time.time()
    while time.time() - start <= timeout_s:
        row = client.get(f"/workbench/tasks/{task_id}").json()
        if row.get("status") in {"done", "error", "failed", "canceled"}:
            return row
        time.sleep(0.1)
    raise TimeoutError(task_id)


def test_chat_iterative_modify_last_run_cost_and_drawdown() -> None:
    previous_force_stub = settings.llm_force_stub
    settings.llm_force_stub = True
    client = TestClient(app)
    try:
        first = client.post(
            "/chat/message",
            json={"message": "Give me a trend strategy and run backtest.", "include_debug": True},
        )
        assert first.status_code == 200
        first_payload = first.json()
        session_id = first_payload["session_id"]
        first_dev = first_payload["debug"]
        first_parent_task_id = str(first_dev["parent_task_id"])
        first_done = _wait_task_done(client, first_parent_task_id)
        first_run_id = str((first_done.get("result_ref") or {}).get("run_id") or "")
        first_plan_id = str((first_done.get("result") or {}).get("plan_id") or "")
        assert first_run_id
        assert first_plan_id
        assert first_payload["mode"] == "pipeline_research"
        assert first_dev["intent"] == "pipeline_research"

        second = client.post(
            "/chat/message",
            json={"session_id": session_id, "message": "Double cost and run again.", "include_debug": True},
        )
        assert second.status_code == 200
        second_payload = second.json()
        second_dev = second_payload["debug"]
        assert second_payload["mode"] == "modify_last_run"
        assert second_dev["intent"] == "modify_last_run"
        assert second_dev["old_run_id"] == first_run_id
        assert second_dev["run_id"] != first_run_id
        assert second_dev["plan_id"] == first_plan_id
        assert second_dev["ops"]["cost_multiplier"] == 2.0

        registry = RunRegistry(settings.run_registry_file)
        old_entry = registry.get_entry(first_run_id)
        assert old_entry is not None
        old_cost = old_entry.request["cost_model"]
        new_cost = second_dev["mutated_backtest_request"]["cost_model"]
        assert float(new_cost["commission_bps"]) == float(old_cost["commission_bps"]) * 2.0
        assert float(new_cost["slippage_bps"]) == float(old_cost["slippage_bps"]) * 2.0
        assert "cost_diff" in second_dev
        assert "risk_action_diff" in second_dev
        assert "total_delta" in second_dev["cost_diff"]
        assert "delta_total" in second_dev["risk_action_diff"]

        third = client.post(
            "/chat/message",
            json={"session_id": session_id, "message": "Set drawdown target to 5% and run again.", "include_debug": True},
        )
        assert third.status_code == 200
        third_payload = third.json()
        third_dev = third_payload["debug"]
        assert third_payload["mode"] == "modify_last_run"
        assert third_dev["intent"] == "modify_last_run"
        assert third_dev["old_run_id"] == second_dev["run_id"]
        assert abs(float(third_dev["mutated_backtest_request"]["constraints"]["max_drawdown_target"]) - 0.05) < 1e-9
        assert "metrics_diff" in third_dev
        assert "cost_diff" in third_dev
        assert "risk_action_diff" in third_dev
    finally:
        settings.llm_force_stub = previous_force_stub
