from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from openfinance.data.quality import DataQualityReport


class OHLCVBar(BaseModel):
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    spread_bps: float = 0.0
    is_missing: bool = False
    is_outlier: bool = False


class FundamentalPoint(BaseModel):
    symbol: str
    report_date: date
    publish_time: datetime
    availability_lag_days: int = 0
    pe_ratio: float | None = None
    roe: float | None = None
    is_backfilled: bool = False


class NewsEvent(BaseModel):
    ts: datetime
    symbol: str
    headline: str
    sentiment: float = Field(ge=-1.0, le=1.0)
    source: str = "mock_news"


class CorporateAction(BaseModel):
    symbol: str
    action_type: str  # dividend | split | reverse_split
    ex_date: date
    value: float


class TradingCalendarDay(BaseModel):
    market: str
    session_date: date
    is_open: bool = True
    open_time: str = "09:30"
    close_time: str = "16:00"
    timezone: str = "UTC"


class MacroPoint(BaseModel):
    series: str
    value: float
    publish_time: datetime
    revision: int = 0


class DatasetLineage(BaseModel):
    tables: list[str] = Field(default_factory=list)
    fields: list[str] = Field(default_factory=list)
    time_range: dict[str, str] = Field(default_factory=dict)
    filters: dict[str, Any] = Field(default_factory=dict)


class GeneratedDataset(BaseModel):
    dataset_id: str
    dataset_version: str
    schema_version: str = "1.0.0"
    seed: int
    generation_config: dict[str, Any]
    lineage: DatasetLineage
    quality_report: DataQualityReport
    market: list[OHLCVBar] = Field(default_factory=list)
    corporate_actions: list[CorporateAction] = Field(default_factory=list)
    trading_calendar: list[TradingCalendarDay] = Field(default_factory=list)
    fundamentals: list[FundamentalPoint] = Field(default_factory=list)
    macro: list[MacroPoint] = Field(default_factory=list)
    news: list[NewsEvent] = Field(default_factory=list)
