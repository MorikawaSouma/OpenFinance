from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


class EvidenceSource(BaseModel):
    source_id: str
    title: str
    source_type: str = "unknown"
    url: str | None = None
    uri: str | None = None
    published_at: datetime | None = None
    timestamp: datetime | None = None
    snippet: str = ""
    full_text_ref: str | None = None
    credibility_score: float = Field(default=0.5, ge=0.0, le=1.0)
    time_relevance: float = Field(default=0.5, ge=0.0, le=1.0)
    credibility_breakdown: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _normalize_alias_fields(self) -> "EvidenceSource":
        if self.url and not self.uri:
            self.uri = self.url
        if self.uri and not self.url:
            self.url = self.uri
        if self.published_at and not self.timestamp:
            self.timestamp = self.published_at
        if self.timestamp and not self.published_at:
            self.published_at = self.timestamp
        return self


class ExtractedTable(BaseModel):
    table_name: str
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class EvidencePack(BaseModel):
    evidence_pack_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    query: str
    sources: list[EvidenceSource] = Field(default_factory=list)
    key_points: list[str] = Field(default_factory=list)
    extracted_tables: list[ExtractedTable] = Field(default_factory=list)
    credibility_score: float = Field(default=0.5, ge=0.0, le=1.0)
    time_relevance: float = Field(default=0.5, ge=0.0, le=1.0)
    credibility_breakdown: dict[str, object] = Field(default_factory=dict)
