import json
from pathlib import Path
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class AuditLogEntry(BaseModel):
    trace_id: UUID = Field(default_factory=uuid4)
    run_id: UUID | None = None
    event_type: str
    payload: dict[str, Any]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InMemoryAuditStore:
    def __init__(self) -> None:
        self._entries: list[AuditLogEntry] = []

    def append(self, entry: AuditLogEntry) -> None:
        self._entries.append(entry)

    def list_all(self) -> list[AuditLogEntry]:
        return list(self._entries)


class FileAuditStore:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, entry: AuditLogEntry) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry.model_dump(mode="json"), ensure_ascii=False) + "\n")

    def list_all(self) -> list[AuditLogEntry]:
        if not self.path.exists():
            return []
        rows: list[AuditLogEntry] = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(AuditLogEntry.model_validate_json(line))
                except ValueError:
                    # tolerate legacy or malformed lines instead of breaking audit queries
                    continue
        return rows
