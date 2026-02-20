from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.quant.backtest.run_registry import RunRegistry
from openfinance.core.config import settings


def test_chat_iterative_modify_last_run_cost_and_drawdown() -> None:
    client = TestClient(app)

    first = client.post("/chat/message", json={"message": "给我一套趋势策略并跑回测"})
    assert first.status_code == 200
    first_payload = first.json()
    session_id = first_payload["session_id"]
    first_dev = first_payload["developer_payload"]
    first_run_id = first_dev["run_id"]
    first_plan_id = first_dev["plan_id"]
    assert first_dev["intent"] == "new_research"

    second = client.post(
        "/chat/message",
        json={"session_id": session_id, "message": "成本翻倍再跑一次"},
    )
    assert second.status_code == 200
    second_payload = second.json()
    second_dev = second_payload["developer_payload"]
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
        json={"session_id": session_id, "message": "把回撤目标从10%改到5%再跑一次"},
    )
    assert third.status_code == 200
    third_dev = third.json()["developer_payload"]
    assert third_dev["intent"] == "modify_last_run"
    assert third_dev["old_run_id"] == second_dev["run_id"]
    assert abs(float(third_dev["mutated_backtest_request"]["constraints"]["max_drawdown_target"]) - 0.05) < 1e-9
    assert "metrics_diff" in third_dev
    assert "cost_diff" in third_dev
    assert "risk_action_diff" in third_dev
