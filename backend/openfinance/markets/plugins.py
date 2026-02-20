from dataclasses import dataclass
from datetime import datetime, time

from openfinance.data.contracts.instruments import Instrument
from openfinance.markets.rules_base import MarketRules, MarketRulesProvider, OrderCheckResult


@dataclass
class USMarketRules(MarketRules):
    market: str = "US"
    min_lot: float = 1.0

    def validate_order(self, instrument: Instrument, quantity: float) -> OrderCheckResult:
        if quantity < self.min_lot:
            return OrderCheckResult(accepted=False, reason="below_min_lot")
        if quantity % instrument.lot_size != 0:
            return OrderCheckResult(accepted=False, reason="invalid_lot_multiple")
        return OrderCheckResult(accepted=True)

    def lot_size(self) -> float:
        return self.min_lot


@dataclass
class CNMarketRules(MarketRules):
    market: str = "CN"
    enable_t_plus_one: bool = True
    min_lot: float = 100.0
    daily_price_limit_pct: float = 0.1

    def validate_order(self, instrument: Instrument, quantity: float) -> OrderCheckResult:
        if quantity < self.min_lot:
            return OrderCheckResult(accepted=False, reason="below_cn_min_lot_100")
        if quantity % self.min_lot != 0:
            return OrderCheckResult(accepted=False, reason="cn_lot_must_be_100_multiple")
        return OrderCheckResult(accepted=True)

    def lot_size(self) -> float:
        return self.min_lot

    def t_plus_one(self) -> bool:
        return self.enable_t_plus_one

    def price_limit_pct(self) -> float | None:
        return self.daily_price_limit_pct


@dataclass
class CryptoMarketRules(MarketRules):
    market: str = "CRYPTO"
    always_open: bool = True
    min_order_notional: float = 5.0

    def validate_order(self, instrument: Instrument, quantity: float) -> OrderCheckResult:
        if quantity <= 0:
            return OrderCheckResult(accepted=False, reason="invalid_quantity")
        ref_price = float(instrument.meta.get("ref_price", "0") or 0)
        if ref_price > 0 and (quantity * ref_price) < self.min_order_notional:
            return OrderCheckResult(accepted=False, reason="below_crypto_min_notional")
        return OrderCheckResult(accepted=True)

    def lot_size(self) -> float:
        return 0.0001

    def supports_fractional_qty(self) -> bool:
        return True

    def min_notional(self) -> float:
        return self.min_order_notional

    def is_24x7(self) -> bool:
        return self.always_open


@dataclass
class JPMarketRules(MarketRules):
    market: str = "JP"
    min_lot: float = 100.0
    morning_start: str = "09:00"
    morning_end: str = "11:30"
    afternoon_start: str = "12:30"
    afternoon_end: str = "15:00"

    def validate_order(self, instrument: Instrument, quantity: float) -> OrderCheckResult:
        if quantity < self.min_lot or quantity % self.min_lot != 0:
            return OrderCheckResult(accepted=False, reason="jp_lot_must_be_100_multiple")
        return OrderCheckResult(accepted=True)

    def lot_size(self) -> float:
        return self.min_lot

    def in_trading_session(self, ts: datetime) -> bool:
        t = ts.time()
        am_open = time.fromisoformat(self.morning_start)
        am_close = time.fromisoformat(self.morning_end)
        pm_open = time.fromisoformat(self.afternoon_start)
        pm_close = time.fromisoformat(self.afternoon_end)
        in_am = am_open <= t <= am_close
        in_pm = pm_open <= t <= pm_close
        return in_am or in_pm


def build_market_rules_provider() -> MarketRulesProvider:
    provider = MarketRulesProvider()
    provider.register(USMarketRules())
    provider.register(CNMarketRules())
    provider.register(CryptoMarketRules())
    provider.register(JPMarketRules())
    return provider
