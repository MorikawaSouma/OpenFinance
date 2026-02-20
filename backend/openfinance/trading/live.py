from typing import Any

from pydantic import BaseModel, Field

from openfinance.trading.paper import PaperOrderRequest, PaperOrderResult
from openfinance.trading.risk import RiskGate


class LiveTradingEngine:
    def __init__(self, risk_gate: RiskGate) -> None:
        self.risk_gate = risk_gate

    def place_order(self, request: PaperOrderRequest) -> PaperOrderResult:
        decision = self.risk_gate.check_order(quantity=request.quantity, is_live=True)
        return PaperOrderResult(
            accepted=decision.allowed,
            reason=decision.reason,
            mode="live",
        )


class LiveOrderRequest(PaperOrderRequest):
    pass


class TradingStatus(BaseModel):
    mode: str
    kill_switch_enabled: bool
    live_trading_enabled: bool
    paper_trading_enabled: bool
    risk_max_order_qty: float
    live_approval_state: str | None = None
    paper_approval_state: str | None = None
    pending_approval_count: int = 0
    current_equity: float = 0.0
    peak_equity: float = 0.0
    current_drawdown: float = 0.0
    current_volatility: float = 0.0
    realized_volatility: float = 0.0
    risk_status: str = "normal"
    max_account_drawdown_limit: float = 0.0
    abnormal_volatility_limit: float = 0.0
    recent_risk_events: list[dict[str, Any]] = Field(default_factory=list)
