import time

from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.core.events import event_bus


def test_event_bus_publish_snapshot() -> None:
    event_bus.publish("task.progress", {"task_id": "x", "progress": 1}, session_id="test")
    rows = event_bus.snapshot()
    assert len(rows) >= 1
    assert rows[-1]["type"] == "task.progress"


def test_event_bus_subscribe_with_replay() -> None:
    event_bus.publish("task.created", {"task_id": "replay-1"}, session_id="test")
    sub_id, sub_q, replay = event_bus.subscribe(replay=1)
    try:
        assert len(replay) == 1
        event_bus.publish("task.progress", {"task_id": "replay-1", "progress": 25}, session_id="test")
        live = sub_q.get(timeout=1.0)
        assert live["type"] == "task.progress"
    finally:
        event_bus.unsubscribe(sub_id)


def test_workbench_publishes_task_events() -> None:
    client = TestClient(app)
    resp = client.post(
        "/workbench/datasets/generate",
        json={
            "dataset_id": "sse_demo",
            "market": "US",
            "symbol": "AAPL",
            "start": "2024-01-01",
            "end": "2024-01-15",
            "seed": 3,
            "base_price": 100.0,
        },
    )
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]
    t0 = time.time()
    done = False
    while time.time() - t0 <= 4:
        task = client.get(f"/workbench/tasks/{task_id}").json()
        if task["status"] in {"done", "failed"}:
            done = True
            break
        time.sleep(0.1)
    assert done
    history = event_bus.snapshot()
    assert any(ev["type"] == "task.created" for ev in history)
    assert any(ev["type"] == "task.done" for ev in history)
