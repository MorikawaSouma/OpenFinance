import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from openfinance.core.config import settings


class TaskRecord(BaseModel):
    task_id: UUID = Field(default_factory=uuid4)
    parent_task_id: UUID | None = None
    task_type: str
    status: str = "queued"  # queued | running | done | error | canceled
    progress: int = 0
    message: str = ""
    result: dict[str, Any] = Field(default_factory=dict)
    result_ref: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TaskManager:
    def __init__(self, storage_file: str | None = None, max_tasks: int = 5000) -> None:
        self._lock = Lock()
        self._tasks: dict[UUID, TaskRecord] = {}
        self._max_tasks = max(100, int(max_tasks))
        self._storage_path = Path(storage_file).expanduser() if storage_file else None
        if self._storage_path is not None:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            self._load()

    def _recover_interrupted_tasks_locked(self) -> None:
        recovered = False
        now = datetime.now(UTC)
        for task in self._tasks.values():
            if task.status not in {"queued", "running"}:
                continue
            task.status = "error"
            task.progress = 100
            task.error = "Task interrupted by service restart"
            task.message = task.message or "task interrupted"
            task.updated_at = now
            recovered = True
        if recovered:
            self._save_locked()

    def _load(self) -> None:
        if self._storage_path is None or (not self._storage_path.exists()):
            return
        try:
            raw = json.loads(self._storage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, list):
            return
        loaded: dict[UUID, TaskRecord] = {}
        for row in raw:
            if not isinstance(row, dict):
                continue
            try:
                item = TaskRecord.model_validate(row)
            except ValueError:
                continue
            loaded[item.task_id] = item
        with self._lock:
            self._tasks = loaded
            self._recover_interrupted_tasks_locked()

    def _trim_locked(self) -> None:
        if len(self._tasks) <= self._max_tasks:
            return
        rows = sorted(self._tasks.values(), key=lambda item: item.updated_at, reverse=True)[: self._max_tasks]
        self._tasks = {row.task_id: row for row in rows}

    def _save_locked(self) -> None:
        if self._storage_path is None:
            return
        self._trim_locked()
        payload = [row.model_dump(mode="json") for row in sorted(self._tasks.values(), key=lambda item: item.updated_at)]
        self._storage_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def create(
        self,
        task_type: str,
        message: str = "",
        *,
        parent_task_id: UUID | None = None,
        status: str = "queued",
        meta: dict[str, Any] | None = None,
    ) -> TaskRecord:
        task = TaskRecord(
            task_type=task_type,
            message=message,
            parent_task_id=parent_task_id,
            status=status,
            meta=dict(meta or {}),
        )
        with self._lock:
            self._tasks[task.task_id] = task
            self._save_locked()
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
        result_ref: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> TaskRecord:
        with self._lock:
            task = self._tasks[task_id]
            if status is not None:
                task.status = status
            if progress is not None:
                task.progress = max(0, min(100, int(progress)))
            if message is not None:
                task.message = message
            if result is not None:
                task.result = result
            if result_ref is not None:
                task.result_ref = result_ref
            if meta is not None:
                task.meta = meta
            task.error = error
            task.updated_at = datetime.now(UTC)
            self._tasks[task_id] = task
            self._save_locked()
            return task


@lru_cache(maxsize=1)
def get_task_manager() -> TaskManager:
    return TaskManager(storage_file=settings.task_registry_file)
