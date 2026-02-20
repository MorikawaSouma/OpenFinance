from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Order(BaseModel):
    order_id: UUID = Field(default_factory=uuid4)
    instrument_id: str
    side: str
    quantity: float = Field(gt=0)
    order_type: str
    status: str = "new"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Fill(BaseModel):
    fill_id: UUID = Field(default_factory=uuid4)
    order_id: UUID
    price: float = Field(gt=0)
    quantity: float = Field(gt=0)
    filled_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Position(BaseModel):
    instrument_id: str
    quantity: float = 0.0
    avg_price: float = 0.0


class AccountSnapshot(BaseModel):
    equity: float
    cash: float
    margin_used: float = 0.0
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RiskEvent(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    severity: str
    message: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
