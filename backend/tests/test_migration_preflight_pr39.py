from fastapi.testclient import TestClient

from openfinance.api.main import app


def _cn_high_turnover_constraints() -> dict:
    return {
        "factor_cost_sensitivity_level": "high",
        "factor_expected_horizon": "intraday",
        "expected_turnover": 0.7,
        "expected_turnover_threshold": 0.35,
        "auto_round_lot": False,
    }


def test_pr39_plan_preflight_warns_before_run_for_cn() -> None:
    client = TestClient(app)
    resp = client.post(
        "/plan",
        json={
            "question": "US 高频因子切到 A 股会怎样？",
            "market": "CN",
            "constraints": _cn_high_turnover_constraints(),
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    warnings = payload.get("preflight_warnings", [])
    assert warnings
    assert any(str(row.get("severity")) == "block" for row in warnings)
    explanation_text = " ".join(str(row.get("explanation", "")) for row in warnings).lower()
    assert "t+1" in explanation_text
    assert "lot" in explanation_text
    assert ("session" in explanation_text) or ("时段" in explanation_text)


def test_pr39_run_blocks_when_preflight_block_not_confirmed() -> None:
    client = TestClient(app)
    resp = client.post(
        "/run",
        json={
            "question": "把美股高频动量策略直接迁移到A股",
            "market": "CN",
            "constraints": _cn_high_turnover_constraints(),
            "run_paper_trade": False,
            "experiments": 3,
        },
    )
    assert resp.status_code == 400
    detail = resp.json().get("detail", {})
    warnings = detail.get("preflight_warnings", [])
    assert warnings
    assert any(str(row.get("severity")) == "block" for row in warnings)
    assert "migration_preflight_confirmed" in str(detail.get("action_required", ""))


def test_pr39_run_auto_adjust_allows_cn_execution() -> None:
    client = TestClient(app)
    resp = client.post(
        "/run",
        json={
            "question": "把美股高频动量策略直接迁移到A股",
            "market": "CN",
            "constraints": _cn_high_turnover_constraints(),
            "auto_adjust_for_market_rules": True,
            "run_paper_trade": False,
            "experiments": 3,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("preflight_actions")
    warnings = payload.get("preflight_warnings", [])
    assert all(str(row.get("severity")) != "block" for row in warnings)
