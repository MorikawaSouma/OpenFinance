from pydantic import BaseModel, Field


class TradingSession(BaseModel):
    start: str = Field(description="Session start in HH:MM format")
    end: str = Field(description="Session end in HH:MM format")


class TradingHours(BaseModel):
    timezone: str
    sessions: list[TradingSession] = Field(default_factory=list)


class Instrument(BaseModel):
    instrument_id: str
    symbol: str
    asset_class: str
    venue: str
    currency: str
    tick_size: float = Field(gt=0)
    lot_size: float = Field(gt=0)
    contract_multiplier: float = Field(default=1.0, gt=0)
    trading_hours: TradingHours
    meta: dict[str, str] = Field(default_factory=dict)
