import time

from fastapi.testclient import TestClient

from openfinance.api.main import app


def _wait_done(client: TestClient, task_id: str, timeout: float = 5.0) -> dict:
    start = time.time()
    while time.time() - start <= timeout:
        row = client.get(f"/workbench/tasks/{task_id}").json()
        if row["status"] in {"done", "failed"}:
            return row
        time.sleep(0.1)
    raise TimeoutError(task_id)


def test_reports_required_fields_and_strategies_endpoint() -> None:
    client = TestClient(app)
    ds = client.post(
        "/workbench/datasets/generate",
        json={
            "dataset_id": "acc_contract",
            "market": "US",
            "symbol": "AAPL",
            "start": "2024-01-01",
            "end": "2024-02-01",
            "seed": 5,
            "base_price": 100.0,
        },
    ).json()
    ds_done = _wait_done(client, ds["task_id"])
    assert ds_done["status"] == "done"

    bt = client.post(
        "/workbench/backtests/run",
        json={
            "dataset_version": ds_done["result"]["dataset_version"],
            "strategy_id": "acceptance_strategy",
            "strategy_version": "0.1.0",
            "market": "US",
            "start": "2024-01-01",
            "end": "2024-02-01",
        },
    ).json()
    bt_done = _wait_done(client, bt["task_id"])
    assert bt_done["status"] == "done"
    run_id = bt_done["result"]["run_id"]

    report = client.get(f"/workbench/reports/{run_id}")
    assert report.status_code == 200
    payload = report.json()
    for key in ["metrics", "charts", "dataset_version", "strategy_version", "factor_versions", "run_id", "audit_trace_id"]:
        assert key in payload

    strategies = client.get("/workbench/strategies")
    assert strategies.status_code == 200
    assert len(strategies.json()) >= 1
