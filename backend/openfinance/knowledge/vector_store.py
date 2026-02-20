from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class VectorRecord:
    record_id: str
    text: str
    embedding: list[float]
    metadata: dict[str, str]


class VectorStore(ABC):
    @abstractmethod
    def upsert(self, records: list[VectorRecord]) -> None:
        raise NotImplementedError

    @abstractmethod
    def search(self, query_embedding: list[float], top_k: int = 5) -> list[VectorRecord]:
        raise NotImplementedError


class InMemoryVectorStore(VectorStore):
    def __init__(self) -> None:
        self._records: dict[str, VectorRecord] = {}

    def upsert(self, records: list[VectorRecord]) -> None:
        for record in records:
            self._records[record.record_id] = record

    def search(self, query_embedding: list[float], top_k: int = 5) -> list[VectorRecord]:
        # PR5 stub: return latest inserted records to keep interface ready.
        return list(self._records.values())[-top_k:]
