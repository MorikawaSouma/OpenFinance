import hashlib
from datetime import UTC, datetime
from threading import Lock
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from openfinance.trading.paper import PaperOrderRequest, PaperOrderResult


class SimBrokerLog(BaseModel):
    log_id: UUID = Field(default_factory=uuid4)
    order_id: UUID
    stage: str
    instrument_id: str
    side: str
    quantity: float
    price: float | None = None
    detail: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SimBrokerAdapter:
    def __init__(self) -> None:
        self._logs: list[SimBrokerLog] = []
        self._lock = Lock()

    def submit_and_reconcile(self, request: PaperOrderRequest) -> PaperOrderResult:
        order_id = uuid4()
        fill_price = self._synthetic_fill_price(request.instrument_id, request.side, request.quantity)

        submitted = SimBrokerLog(
            order_id=order_id,
            stage="order_submitted",
            instrument_id=request.instrument_id,
            side=request.side,
            quantity=request.quantity,
            detail="Order accepted by simulated broker.",
        )
        filled = SimBrokerLog(
            order_id=order_id,
            stage="order_filled",
            instrument_id=request.instrument_id,
            side=request.side,
            quantity=request.quantity,
            price=fill_price,
            detail="Order filled at synthetic price.",
        )
        reconciled = SimBrokerLog(
            order_id=order_id,
            stage="order_reconciled",
            instrument_id=request.instrument_id,
            side=request.side,
            quantity=request.quantity,
            price=fill_price,
            detail="Post-trade reconciliation completed.",
        )
        with self._lock:
            self._logs.extend([submitted, filled, reconciled])
        return PaperOrderResult(
            order_id=order_id,
            accepted=True,
            reason="sim_live_filled",
            mode="live",
            status="filled",
            fill_price=fill_price,
            fill_qty=request.quantity,
            user_message="模拟实盘订单已成交并完成对账。",
            log_refs=[str(submitted.log_id), str(filled.log_id), str(reconciled.log_id)],
        )

    def list_logs(self, limit: int = 200) -> list[SimBrokerLog]:
        with self._lock:
            rows = list(self._logs)
        return list(reversed(rows[-max(1, limit) :]))

    def _synthetic_fill_price(self, instrument_id: str, side: str, quantity: float) -> float:
        seed = f"{instrument_id}:{side}:{round(quantity, 6)}".encode("utf-8")
        digest = hashlib.sha1(seed).hexdigest()
        base = 80.0 + (int(digest[:6], 16) % 5000) / 100.0
        slip = min(1.5, abs(quantity) * 0.0002)
        if side.lower() == "buy":
            return round(base + slip, 6)
        return round(max(0.01, base - slip), 6)
