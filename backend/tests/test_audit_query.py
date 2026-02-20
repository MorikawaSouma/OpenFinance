import time

from fastapi.testclient import TestClient

from openfinance.api.main import app


def test_audit_query_by_trace_id() -> None:
    client = TestClient(app)
    task = client.post(
        "/workbench/datasets/generate",
        json={
            "dataset_id": "audit_demo",
            "market": "US",
            "symbol": "AAPL",
            "start": "2024-01-01",
            "end": "2024-01-10",
            "seed": 9,
            "base_price": 100.0,
        },
    ).json()
    task_id = task["task_id"]

    t0 = time.time()
    while time.time() - t0 <= 4:
        payload = client.get(f"/workbench/tasks/{task_id}").json()
        if payload["status"] in {"done", "failed"}:
            break
        time.sleep(0.1)

    logs = client.get("/workbench/audit").json()
    assert len(logs) > 0
    trace_id = logs[-1]["trace_id"]
    filtered = client.get("/workbench/audit", params={"trace_id": trace_id}).json()
    assert all(item["trace_id"] == trace_id for item in filtered)
