import json
from pathlib import Path

from pydantic import BaseModel

from openfinance.data.contracts.dataset import GeneratedDataset


class DatasetRegistryEntry(BaseModel):
    dataset_id: str
    dataset_version: str
    schema_version: str
    seed: int
    generation_config: dict[str, object]
    lineage: dict[str, object]
    quality_report: dict[str, object]
    artifact_path: str


class DatasetRegistry:
    def __init__(self, registry_file: str, data_root: str) -> None:
        self.registry_file = Path(registry_file)
        self.data_root = Path(data_root)
        self.registry_file.parent.mkdir(parents=True, exist_ok=True)
        self.data_root.mkdir(parents=True, exist_ok=True)

    def register(self, dataset: GeneratedDataset) -> DatasetRegistryEntry:
        artifact_path = self.data_root / f"{dataset.dataset_version}.json"
        artifact_path.write_text(
            json.dumps(dataset.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        entry = DatasetRegistryEntry(
            dataset_id=dataset.dataset_id,
            dataset_version=dataset.dataset_version,
            schema_version=dataset.schema_version,
            seed=dataset.seed,
            generation_config=dataset.generation_config,
            lineage=dataset.lineage.model_dump(mode="json"),
            quality_report=dataset.quality_report.model_dump(mode="json"),
            artifact_path=str(artifact_path),
        )
        with self.registry_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry.model_dump(mode="json"), ensure_ascii=False) + "\n")
        return entry

    def list_entries(self) -> list[DatasetRegistryEntry]:
        if not self.registry_file.exists():
            return []
        entries: list[DatasetRegistryEntry] = []
        with self.registry_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entries.append(DatasetRegistryEntry.model_validate_json(line))
        return entries

    def get_entry(self, dataset_version: str) -> DatasetRegistryEntry | None:
        for entry in reversed(self.list_entries()):
            if entry.dataset_version == dataset_version:
                return entry
        return None
