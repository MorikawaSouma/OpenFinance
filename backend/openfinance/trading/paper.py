from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from openfinance.trading.risk import RiskGate


class PaperOrderRequest(BaseModel):
    instrument_id: str
    side: str
    quantity: float
    order_type: str = "market"
    plan_id: str | None = None
    evidence_pack_id: str | None = None
    failure_conditions: list[str | dict[str, Any]] = Field(default_factory=list)
    failure_context: dict[str, float | int | str] = Field(default_factory=dict)


class PaperOrderResult(BaseModel):
    order_id: UUID = Field(default_factory=uuid4)
    accepted: bool
    reason: str
    mode: str
    status: str = "completed"
    request_id: str | None = None
    fill_price: float | None = None
    fill_qty: float | None = None
    user_message: str = ""
    log_refs: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PaperTradingEngine:
    def __init__(self, risk_gate: RiskGate) -> None:
        self.risk_gate = risk_gate
        self._orders: list[PaperOrderResult] = []

    def place_order(self, request: PaperOrderRequest) -> PaperOrderResult:
        decision = self.risk_gate.check_order(quantity=request.quantity, is_live=False)
        result = PaperOrderResult(
            accepted=decision.allowed,
            reason=decision.reason,
            mode="paper",
        )
        self._orders.append(result)
        return result

    def list_orders(self) -> list[PaperOrderResult]:
        return list(self._orders)
