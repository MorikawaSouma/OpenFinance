from datetime import UTC, datetime

from pydantic import BaseModel, Field


class DataQualityReport(BaseModel):
    total_rows: int = 0
    missing_rate: float = Field(ge=0.0, le=1.0, default=0.0)
    delayed_rate: float = Field(ge=0.0, le=1.0, default=0.0)
    backfill_rate: float = Field(ge=0.0, le=1.0, default=0.0)
    outlier_rate: float = Field(ge=0.0, le=1.0, default=0.0)
    survivorship_bias_enabled: bool = False
    survivorship_bias_risk: str = "low"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
