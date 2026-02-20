import time

from fastapi.testclient import TestClient

from openfinance.api.main import app


def _wait_task(client: TestClient, task_id: str, timeout_s: float = 5.0) -> dict:
    t0 = time.time()
    while time.time() - t0 <= timeout_s:
        payload = client.get(f"/workbench/tasks/{task_id}").json()
        if payload["status"] in {"done", "failed"}:
            return payload
        time.sleep(0.1)
    raise TimeoutError(f"task timeout: {task_id}")


def _request_payload() -> dict:
    return {
        "factor_spec": {
            "factor_id": "pr37_momentum_formula",
            "factor_version": "pr37-v1",
            "description": "multi-market momentum comparison",
            "inputs": [
                {"name": "close", "source": "market", "availability_lag": "0s"},
            ],
            "params": {
                "formula": "Rank(Ts_Mean(close, 20))",
                "lookback_days": 20,
                "decay_lags": 6,
                "universe": ["AAA", "BBB", "CCC", "DDD"],
            },
            "validation_plan": {
                "in_sample_start": "2023-01-01",
                "in_sample_end": "2023-12-31",
                "out_sample_start": "2024-01-01",
                "out_sample_end": "2024-12-31",
            },
            "failure_conditions": ["high_volatility", "range_bound_market"],
            "cost_sensitivity": {
                "level": "medium",
                "rationale": "Moderate turnover in cross-market deployment.",
            },
            "expected_horizon": "swing",
        },
        "markets": ["US", "JP"],
        "start": "2023-01-01",
        "end": "2024-12-31",
        "seed": 42,
        "eval_metrics": ["IC", "RankIC", "decay", "coverage"],
    }


def test_factor_multi_market_compare_returns_metrics_and_curves() -> None:
    client = TestClient(app)
    resp = client.post("/workbench/factor/multi_market_compare", json=_request_payload())
    assert resp.status_code == 200
    payload = resp.json()

    assert payload["compare_id"].startswith("fmmc_")
    assert payload["requested_metrics"] == ["ic", "rankic", "decay", "coverage"]
    assert len(payload["per_market_metrics"]) == 2
    assert len(payload["per_market_decay_curves"]) == 2
    assert len(payload["summary_insights"]) >= 1

    metrics_by_market = {
        row["market"]: row for row in payload["per_market_metrics"] if row["factor_version"] == "pr37-v1"
    }
    assert {"US", "JP"} <= set(metrics_by_market.keys())
    assert metrics_by_market["US"]["coverage"] > 0.0
    assert metrics_by_market["JP"]["coverage"] > 0.0
    assert metrics_by_market["US"]["decay_ratio"] >= metrics_by_market["JP"]["decay_ratio"]

    us_curve = next(row for row in payload["per_market_decay_curves"] if row["market"] == "US")
    assert len(us_curve["points"]) >= 3
    assert all("lag" in point and "ic" in point for point in us_curve["points"])


def test_factor_multi_market_compare_requires_two_markets() -> None:
    client = TestClient(app)
    payload = _request_payload()
    payload["markets"] = ["US"]
    resp = client.post("/workbench/factor/multi_market_compare", json=payload)
    assert resp.status_code == 400


def test_factor_multi_market_compare_supports_factor_id_and_versions() -> None:
    client = TestClient(app)
    dataset_task = client.post(
        "/workbench/datasets/generate",
        json={
            "dataset_id": "pr37_api_factor_ds",
            "market": "US",
            "symbol": "AAPL",
            "start": "2024-01-01",
            "end": "2024-06-30",
            "seed": 7,
        },
    )
    assert dataset_task.status_code == 200
    dataset_done = _wait_task(client, dataset_task.json()["task_id"])
    assert dataset_done["status"] == "done"

    run_resp = client.post(
        "/workbench/factors/run",
        json={
            "dataset_version": dataset_done["result"]["dataset_version"],
            "factor_id": "pr37_api_factor",
            "factor_version": "pr37-api-v1",
            "formula": "Rank(Ts_Mean(close, 20))",
            "inputs": ["close"],
            "availability_lag": "0s",
            "failure_conditions": ["high_volatility"],
            "cost_sensitivity_level": "medium",
            "cost_sensitivity_rationale": "Moderate rebalance turnover.",
            "expected_horizon": "swing",
        },
    )
    assert run_resp.status_code == 200

    compare_resp = client.post(
        "/workbench/factor/multi_market_compare",
        json={
            "factor_id": "pr37_api_factor",
            "factor_versions": ["pr37-api-v1"],
            "markets": ["US", "CN"],
            "start": "2023-01-01",
            "end": "2024-12-31",
            "seed": 7,
        },
    )
    assert compare_resp.status_code == 200
    payload = compare_resp.json()
    assert len(payload["per_market_metrics"]) == 2
    assert {row["market"] for row in payload["per_market_metrics"]} == {"US", "CN"}
