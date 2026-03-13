import time
from uuid import uuid4

from fastapi.testclient import TestClient

from openfinance.api.main import app


def _wait_task(client: TestClient, task_id: str, timeout_s: float = 5.0) -> dict:
    t0 = time.time()
    while time.time() - t0 <= timeout_s:
        payload = client.get(f"/workbench/tasks/{task_id}").json()
        if payload["status"] in {"done", "failed", "error", "canceled"}:
            return payload
        time.sleep(0.1)
    raise TimeoutError(f"task timeout: {task_id}")


def test_workbench_dataset_and_backtest_flow() -> None:
    client = TestClient(app)

    ds_task = client.post(
        "/workbench/datasets/generate",
        json={
            "dataset_id": "wb_demo",
            "market": "US",
            "symbol": "AAPL",
            "start": "2024-01-01",
            "end": "2024-02-01",
            "seed": 1,
            "base_price": 100.0,
        },
    )
    assert ds_task.status_code == 200
    ds_final = _wait_task(client, ds_task.json()["task_id"])
    assert ds_final["status"] == "done"
    assert "dataset_version" in ds_final["result"]

    bt_task = client.post(
        "/workbench/backtests/run",
        json={
            "dataset_version": ds_final["result"]["dataset_version"],
            "strategy_id": "demo",
            "strategy_version": "0.1.0",
            "market": "US",
            "start": "2024-01-01",
            "end": "2024-02-01",
        },
    )
    assert bt_task.status_code == 200
    bt_final = _wait_task(client, bt_task.json()["task_id"])
    assert bt_final["status"] == "done"
    run_id = bt_final["result"]["run_id"]

    reports = client.get("/workbench/reports")
    assert reports.status_code == 200
    assert any(item["run_id"] == run_id for item in reports.json())

    report = client.get(f"/workbench/reports/{run_id}")
    assert report.status_code == 200
    report_payload = report.json()
    assert report_payload["run_id"] == run_id
    assert "factor_versions" in report_payload

    runs = client.get("/workbench/runs")
    assert runs.status_code == 200
    assert any(item["run_id"] == run_id for item in runs.json())

    run_detail = client.get(f"/workbench/runs/{run_id}")
    assert run_detail.status_code == 200
    assert run_detail.json()["run_id"] == run_id

    run_alias = client.get(f"/workbench/run/{run_id}")
    assert run_alias.status_code == 200
    assert run_alias.json()["run_id"] == run_id

    dataset_version = ds_final["result"]["dataset_version"]
    dataset_detail = client.get(f"/workbench/datasets/{dataset_version}")
    assert dataset_detail.status_code == 200
    assert dataset_detail.json()["dataset_version"] == dataset_version

    strategy_version = "0.1.0"
    strategy_detail = client.get(f"/workbench/strategies/{strategy_version}")
    assert strategy_detail.status_code == 200
    strategy_payload = strategy_detail.json()
    assert strategy_payload["strategy_version"] == strategy_version
    assert "circuit_breaker" in strategy_payload
    assert "failure_regimes" in strategy_payload


def test_workbench_factor_registry_endpoints() -> None:
    client = TestClient(app)
    run_resp = client.post(
        "/pipeline/run",
        json={
            "question": "给我一套趋势策略并做三组实验对比",
            "market": "US",
            "run_paper_trade": False,
            "experiments": 3,
        },
    )
    assert run_resp.status_code == 200
    factor_version = run_resp.json()["factor_version"]

    rows = client.get("/workbench/factors")
    assert rows.status_code == 200
    assert any(item["version"] == factor_version for item in rows.json())

    detail = client.get(f"/workbench/factors/{factor_version}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["version"] == factor_version
    assert "spec" in payload


def test_workbench_formula_factor_run_endpoint() -> None:
    client = TestClient(app)
    version = f"intraday_formula_api_{uuid4().hex[:8]}"
    ds_task = client.post(
        "/workbench/datasets/generate",
        json={
            "dataset_id": "factor_formula_api",
            "market": "US",
            "symbol": "AAPL",
            "start": "2024-01-01",
            "end": "2024-02-10",
            "seed": 12,
            "base_price": 100.0,
        },
    )
    assert ds_task.status_code == 200
    ds_done = _wait_task(client, ds_task.json()["task_id"])
    assert ds_done["status"] == "done"
    dataset_version = ds_done["result"]["dataset_version"]

    run_1 = client.post(
        "/workbench/factors/run",
        json={
            "dataset_version": dataset_version,
            "factor_id": "intraday_formula_api",
            "factor_version": version,
            "formula": "(close-open)/open",
            "inputs": ["close", "open"],
            "availability_lag": "0s",
            "failure_conditions": ["high_volatility", "liquidity_dry_up"],
            "cost_sensitivity_level": "medium",
            "cost_sensitivity_rationale": "Intraday turnover introduces moderate trading cost drag.",
            "expected_horizon": "intraday",
            "decay_lags": 3,
        },
    )
    assert run_1.status_code == 200
    payload_1 = run_1.json()
    assert payload_1["factor_version"] == version
    assert payload_1["cached"] is False
    assert "ic_mean" in payload_1["report"]
    assert "decay_curve" in payload_1["report"]

    run_2 = client.post(
        "/workbench/factors/run",
        json={
            "dataset_version": dataset_version,
            "factor_id": "intraday_formula_api",
            "factor_version": version,
            "formula": "(close-open)/open",
            "inputs": ["close", "open"],
            "availability_lag": "0s",
            "failure_conditions": ["high_volatility", "liquidity_dry_up"],
            "cost_sensitivity_level": "medium",
            "cost_sensitivity_rationale": "Intraday turnover introduces moderate trading cost drag.",
            "expected_horizon": "intraday",
            "decay_lags": 3,
        },
    )
    assert run_2.status_code == 200
    assert run_2.json()["cached"] is True

    detail = client.get(f"/workbench/factors/{version}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["inputs_signature"]
    assert payload["availability_lag"] == "0s"
    assert payload["spec"]["failure_conditions"]
    assert payload["spec"]["cost_sensitivity"]["level"] == "medium"
    assert payload["spec"]["expected_horizon"] == "intraday"
    assert payload["report"] is not None


def test_workbench_formula_factor_requires_metadata_fields() -> None:
    client = TestClient(app)
    ds_task = client.post(
        "/workbench/datasets/generate",
        json={
            "dataset_id": "factor_formula_missing_metadata",
            "market": "US",
            "symbol": "AAPL",
            "start": "2024-01-01",
            "end": "2024-02-10",
            "seed": 12,
            "base_price": 100.0,
        },
    )
    assert ds_task.status_code == 200
    ds_done = _wait_task(client, ds_task.json()["task_id"])
    assert ds_done["status"] == "done"
    dataset_version = ds_done["result"]["dataset_version"]

    run = client.post(
        "/workbench/factors/run",
        json={
            "dataset_version": dataset_version,
            "factor_id": "intraday_formula_api",
            "factor_version": f"intraday_formula_api_{uuid4().hex[:8]}",
            "formula": "(close-open)/open",
            "inputs": ["close", "open"],
            "availability_lag": "0s",
            "decay_lags": 3,
        },
    )
    assert run.status_code == 400
    assert "failure_conditions" in run.json().get("detail", "")


def test_multi_market_compare_creates_parent_child_tasks() -> None:
    client = TestClient(app)
    resp = client.post(
        "/workbench/reports/multi-market/compare",
        json={
            "markets": ["US", "JP"],
            "strategy_id": "obs_test_strategy",
            "strategy_version": "obs-test-v1",
            "start": "2024-01-01",
            "end": "2024-03-31",
            "seed": 7,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    parent_task_id = str(payload.get("parent_task_id") or "")
    child_task_ids = payload.get("child_task_ids") or []
    assert parent_task_id
    assert len(child_task_ids) >= 2

    parent = _wait_task(client, parent_task_id, timeout_s=8.0)
    assert parent["status"] == "done"
    assert parent.get("result_ref", {}).get("open_path")

    tasks = client.get("/workbench/tasks").json()
    children = [row for row in tasks if str(row.get("parent_task_id") or "") == parent_task_id]
    assert len(children) >= 2
    assert all(row.get("status") == "done" for row in children)
    assert all(str(row.get("result_ref", {}).get("run_id") or "").strip() for row in children)
