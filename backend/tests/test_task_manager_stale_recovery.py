from pathlib import Path

from openfinance.core.tasks import TaskManager


def test_task_manager_recovers_inflight_tasks_on_reload(tmp_path: Path) -> None:
    storage = tmp_path / "registry" / "tasks.json"
    first = TaskManager(storage_file=str(storage))
    running = first.create(task_type="pipeline_run", status="running", message="pipeline running")
    queued = first.create(task_type="backtest_variant", status="queued", message="queued")
    done = first.create(task_type="pipeline_run", status="done", message="done")

    reloaded = TaskManager(storage_file=str(storage))
    running_row = reloaded.get(running.task_id)
    queued_row = reloaded.get(queued.task_id)
    done_row = reloaded.get(done.task_id)

    assert running_row is not None
    assert queued_row is not None
    assert done_row is not None

    assert running_row.status == "error"
    assert running_row.progress == 100
    assert str(running_row.error or "").strip() == "Task interrupted by service restart"

    assert queued_row.status == "error"
    assert queued_row.progress == 100
    assert str(queued_row.error or "").strip() == "Task interrupted by service restart"

    assert done_row.status == "done"
    assert done_row.error is None

