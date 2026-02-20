import json
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel


class RunRegistryEntry(BaseModel):
    run_id: UUID
    dataset_version: str
    strategy_id: str
    strategy_version: str
    audit_trace_id: UUID
    request: dict[str, object]
    report_path: str


class RunRegistry:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, entry: RunRegistryEntry) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry.model_dump(mode="json"), ensure_ascii=False) + "\n")

    def list_entries(self) -> list[RunRegistryEntry]:
        if not self.path.exists():
            return []
        rows: list[RunRegistryEntry] = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rows.append(RunRegistryEntry.model_validate_json(line))
        return rows

    def get_entry(self, run_id: str | UUID) -> RunRegistryEntry | None:
        target = str(run_id)
        for row in reversed(self.list_entries()):
            if str(row.run_id) == target:
                return row
        return None
