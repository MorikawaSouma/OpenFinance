from abc import ABC, abstractmethod
from datetime import datetime

from pydantic import BaseModel

from openfinance.data.contracts.instruments import Instrument


class OrderCheckResult(BaseModel):
    accepted: bool
    reason: str | None = None


class MarketRules(ABC):
    market: str

    @abstractmethod
    def validate_order(self, instrument: Instrument, quantity: float) -> OrderCheckResult:
        raise NotImplementedError

    def lot_size(self) -> float:
        return 1.0

    def supports_fractional_qty(self) -> bool:
        return False

    def min_notional(self) -> float:
        return 0.0

    def is_24x7(self) -> bool:
        return False

    def t_plus_one(self) -> bool:
        return False

    def price_limit_pct(self) -> float | None:
        return None

    def in_trading_session(self, ts: datetime) -> bool:
        return True


class MarketRulesProvider:
    def __init__(self) -> None:
        self._registry: dict[str, MarketRules] = {}

    def register(self, rules: MarketRules) -> None:
        self._registry[rules.market] = rules

    def get(self, market: str) -> MarketRules:
        if market not in self._registry:
            raise KeyError(f"Market rules not found: {market}")
        return self._registry[market]
