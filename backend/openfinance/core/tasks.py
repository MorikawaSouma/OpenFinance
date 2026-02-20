from datetime import UTC, datetime
from threading import Lock
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class TaskRecord(BaseModel):
    task_id: UUID = Field(default_factory=uuid4)
    task_type: str
    status: str = "created"  # created | running | done | failed
    progress: int = 0
    message: str = ""
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TaskManager:
    def __init__(self) -> None:
        self._lock = Lock()
        self._tasks: dict[UUID, TaskRecord] = {}

    def create(self, task_type: str, message: str = "") -> TaskRecord:
        task = TaskRecord(task_type=task_type, message=message)
        with self._lock:
            self._tasks[task.task_id] = task
        return task

    def list_tasks(self) -> list[TaskRecord]:
        with self._lock:
            rows = list(self._tasks.values())
        return sorted(rows, key=lambda x: x.created_at, reverse=True)

    def get(self, task_id: UUID) -> TaskRecord | None:
        with self._lock:
            return self._tasks.get(task_id)

    def update(
        self,
        task_id: UUID,
        *,
        status: str | None = None,
        progress: int | None = None,
        message: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> TaskRecord:
        with self._lock:
            task = self._tasks[task_id]
            if status is not None:
                task.status = status
            if progress is not None:
                task.progress = progress
            if message is not None:
                task.message = message
            if result is not None:
                task.result = result
            task.error = error
            task.updated_at = datetime.now(UTC)
            self._tasks[task_id] = task
            return task
