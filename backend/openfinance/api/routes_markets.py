from functools import lru_cache

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from openfinance.data.contracts.instruments import Instrument, TradingHours
from openfinance.markets.plugins import build_market_rules_provider

router = APIRouter(prefix="/markets", tags=["markets"])


class ValidateOrderRequest(BaseModel):
    market: str
    quantity: float
    symbol: str = "AAPL"
    lot_size: float = 1.0


@lru_cache(maxsize=1)
def _provider():
    return build_market_rules_provider()


@router.get("/rules")
def list_rules() -> list[dict[str, str]]:
    markets = ["US", "CN", "CRYPTO", "JP"]
    return [{"market": m, "status": "enabled"} for m in markets if _provider().get(m)]


@router.post("/validate-order")
def validate_order(payload: ValidateOrderRequest) -> dict[str, str | bool]:
    try:
        rules = _provider().get(payload.market)
    except KeyError as ex:
        raise HTTPException(status_code=404, detail=str(ex)) from ex

    instrument = Instrument(
        instrument_id=f"{payload.market}_{payload.symbol}",
        symbol=payload.symbol,
        asset_class="equity",
        venue=payload.market,
        currency="USD",
        tick_size=0.01,
        lot_size=payload.lot_size,
        contract_multiplier=1.0,
        trading_hours=TradingHours(timezone="UTC", sessions=[]),
    )
    result = rules.validate_order(instrument=instrument, quantity=payload.quantity)
    return {"accepted": result.accepted, "reason": result.reason or "ok"}
