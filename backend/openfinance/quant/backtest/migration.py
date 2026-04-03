from datetime import datetime
from typing import Any

from pydantic import BaseModel

from openfinance.markets.rules_base import MarketRules
from openfinance.research.strategy_decision import StrategyProposalSpec
from openfinance.research.strategy_spec import StrategySpec


class MigrationWarning(BaseModel):
    market: str
    code: str
    severity: str
    title: str
    explanation: str


class MigrationChecker:
    def check(
        self,
        strategy_spec: dict[str, Any] | StrategySpec | StrategyProposalSpec,
        market: str,
        rules: MarketRules,
    ) -> list[MigrationWarning]:
        market_key = str(market).upper()
        warnings: list[MigrationWarning] = []
        payload = self._payload(strategy_spec)

        family = str(payload.get("strategy_family", "")).lower()
        rebalance = str(payload.get("rebalance", "weekly")).lower()
        lookback_days = int(payload.get("lookback_days", 20) or 20)
        auto_round_lot = bool(payload.get("auto_round_lot", True))
        run_time_utc = str(payload.get("run_time_utc", "16:00"))

        high_frequency = rebalance == "daily" or lookback_days <= 5 or any(
            token in family for token in ["intraday", "high_freq", "hft"]
        )
        if rules.t_plus_one() and high_frequency:
            warnings.append(
                MigrationWarning(
                    market=market_key,
                    code="cn_t_plus_one_high_frequency",
                    severity="high",
                    title="High-frequency setup is not suitable for T+1",
                    explanation=(
                        "Strategy rebalances too frequently for a T+1 market. Same-day buy then sell turnover is blocked."
                    ),
                )
            )

        lot_size = float(rules.lot_size())
        supports_fractional = bool(rules.supports_fractional_qty())
        probe_qty = self._probe_qty(payload)
        if (not supports_fractional) and lot_size > 0:
            remainder = abs(probe_qty) % lot_size
            mismatch = remainder > 1e-9 and abs(remainder - lot_size) > 1e-9
            if mismatch and not auto_round_lot:
                warnings.append(
                    MigrationWarning(
                        market=market_key,
                        code="lot_size_precision_mismatch",
                        severity="high",
                        title="Order quantity precision may violate lot size",
                        explanation=(
                            f"Estimated target quantity {probe_qty:.4f} is not aligned to lot size {lot_size:.4f}, "
                            "and auto_round_lot is disabled."
                        ),
                    )
                )
            elif mismatch:
                warnings.append(
                    MigrationWarning(
                        market=market_key,
                        code="lot_size_rounding_impact",
                        severity="medium",
                        title="Lot-size rounding can change target exposure",
                        explanation=(
                            f"Estimated target quantity {probe_qty:.4f} is not a lot-size multiple ({lot_size:.4f}). "
                            "Execution may require aggressive rounding."
                        ),
                    )
                )

        if (not rules.is_24x7()) and (not self._in_session(run_time_utc, rules)):
            warnings.append(
                MigrationWarning(
                    market=market_key,
                    code="trading_session_coverage_gap",
                    severity="medium",
                    title="Configured execution time may miss local trading session",
                    explanation=(
                        f"Configured execution time {run_time_utc} UTC does not map to a tradable session in {market_key}. "
                        "Orders may queue or miss intended timing."
                    ),
                )
            )

        return warnings

    def highest_severity(self, warnings: list[MigrationWarning]) -> str:
        if not warnings:
            return "none"
        rank = {"high": 3, "medium": 2, "low": 1}
        out = "low"
        best = 1
        for item in warnings:
            key = str(item.severity).lower()
            score = rank.get(key, 1)
            if score > best:
                best = score
                out = key
        return out

    def _payload(self, strategy_spec: dict[str, Any] | StrategySpec | StrategyProposalSpec) -> dict[str, Any]:
        if isinstance(strategy_spec, (StrategySpec, StrategyProposalSpec)):
            return strategy_spec.model_dump(mode="json")
        return dict(strategy_spec)

    def _probe_qty(self, strategy_spec: dict[str, Any]) -> float:
        max_position = float(strategy_spec.get("max_position", 0.12) or 0.12)
        leverage = float(strategy_spec.get("leverage_limit", 1.0) or 1.0)
        notional = 1_000_000.0 * max(0.01, max_position) * max(0.25, leverage)
        price = float(strategy_spec.get("price_probe", 123.45) or 123.45)
        if price <= 0:
            price = 123.45
        return notional / price

    def _in_session(self, run_time_utc: str, rules: MarketRules) -> bool:
        parts = run_time_utc.strip().split(":")
        if len(parts) != 2:
            return True
        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except ValueError:
            return True
        dt = datetime(2024, 1, 2, hour=hour, minute=minute)
        try:
            return bool(rules.in_trading_session(dt))
        except Exception:
            return True
