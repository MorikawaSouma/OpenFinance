from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class CostModel(BaseModel):
    commission_bps: float = 0.0
    slippage_bps: float = 0.0


class FactorVersionRef(BaseModel):
    factor_id: str
    version: str


class BacktestRequest(BaseModel):
    dataset_version: str
    strategy_id: str
    strategy_version: str
    market: str
    start: str
    end: str
    execution_model: str = "next_open"
    cost_model: CostModel = Field(default_factory=CostModel)
    factor_versions: list[FactorVersionRef] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    evaluation_plan: dict[str, Any] = Field(default_factory=dict)


class BacktestOrder(BaseModel):
    order_id: UUID = Field(default_factory=uuid4)
    time: datetime
    instrument: str
    side: str
    qty: float
    order_type: str = "market"
    limit_price: float | None = None
    status: str = "submitted"
    reason_code: str = ""
    reason_msg: str = ""
    user_friendly_msg: str = ""
    reason: str = ""


class BacktestTrade(BaseModel):
    trade_id: UUID = Field(default_factory=uuid4)
    order_id: UUID
    time: datetime
    instrument: str
    side: str
    price: float
    qty: float
    commission: float
    slippage: float


class PositionSnapshot(BaseModel):
    time: datetime
    instrument: str
    qty: float
    avg_price: float
    market_price: float
    market_value: float
    cash: float
    equity: float
    unrealized_pnl: float


class BacktestReport(BaseModel):
    run_id: UUID = Field(default_factory=uuid4)
    dataset_version: str
    market: str = "US"
    strategy_version: str
    strategy_decision: dict[str, Any] = Field(default_factory=dict)
    factor_versions: list[FactorVersionRef] = Field(default_factory=list)
    factor_versions_reason: str | None = None
    audit_trace_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metrics: dict[str, float | int | str] = Field(default_factory=dict)
    charts: list[str] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    equity_curve: list[dict[str, float | int | str]] = Field(default_factory=list)
    orders: list[BacktestOrder] = Field(default_factory=list)
    trades: list[BacktestTrade] = Field(default_factory=list)
    positions: list[PositionSnapshot] = Field(default_factory=list)
    positions_ts: list[PositionSnapshot] = Field(default_factory=list)
    cost_breakdown: dict[str, float] = Field(default_factory=dict)
    attribution: dict[str, dict[str, float]] = Field(default_factory=dict)
