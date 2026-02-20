import json
from pathlib import Path

from pydantic import BaseModel


class PlanRegistryEntry(BaseModel):
    plan_id: str
    question: str
    market: str
    plan: dict


class PlanRegistry:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, plan: BaseModel) -> None:
        entry = PlanRegistryEntry(
            plan_id=getattr(plan, "plan_id"),
            question=getattr(plan, "question"),
            market=(getattr(plan, "markets") or ["US"])[0],
            plan=plan.model_dump(mode="json"),
        )
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry.model_dump(mode="json"), ensure_ascii=False) + "\n")

    def get_plan_payload(self, plan_id: str) -> dict | None:
        for row in reversed(self.list_entries()):
            if row.plan_id == plan_id:
                return row.plan
        return None

    def list_entries(self) -> list[PlanRegistryEntry]:
        if not self.path.exists():
            return []
        rows: list[PlanRegistryEntry] = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rows.append(PlanRegistryEntry.model_validate_json(line))
        return rows
