import hashlib
import json
import random
from datetime import UTC, date, datetime, time, timedelta

from pydantic import BaseModel, Field

from openfinance.data.contracts.dataset import (
    CorporateAction,
    DatasetLineage,
    FundamentalPoint,
    GeneratedDataset,
    MacroPoint,
    NewsEvent,
    OHLCVBar,
    TradingCalendarDay,
)
from openfinance.data.quality import DataQualityReport


class MockDatasetConfig(BaseModel):
    dataset_id: str = "mock_us_equity"
    market: str = "US"
    symbol: str = "AAPL"
    start_date: date
    end_date: date
    seed: int = 42
    base_price: float = Field(default=100.0, gt=0)
    missing_rate_target: float = Field(default=0.01, ge=0.0, le=0.5)
    delayed_rate_target: float = Field(default=0.02, ge=0.0, le=0.5)
    backfill_rate_target: float = Field(default=0.01, ge=0.0, le=0.5)
    outlier_rate_target: float = Field(default=0.005, ge=0.0, le=0.5)
    include_survivorship_bias: bool = False
    inject_high_vol_segment: bool = False
    high_vol_start_day: int = 20
    high_vol_end_day: int = 40
    high_vol_scale: float = Field(default=3.0, ge=1.0, le=20.0)

    def canonical_payload(self) -> dict[str, object]:
        payload = self.model_dump(mode="json")
        payload["start_date"] = self.start_date.isoformat()
        payload["end_date"] = self.end_date.isoformat()
        return payload


def build_dataset_version(config: MockDatasetConfig, schema_version: str = "1.0.0") -> str:
    raw = {
        "schema_version": schema_version,
        "seed": config.seed,
        "config": config.canonical_payload(),
    }
    fingerprint = hashlib.sha256(
        json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:12]
    return f"{config.dataset_id}-{fingerprint}"


class MockDataFactory:
    def generate(self, config: MockDatasetConfig) -> GeneratedDataset:
        rng = random.Random(config.seed)
        dataset_version = build_dataset_version(config)

        bars = self._gen_market_bars(config, rng)
        corp_actions = self._gen_corporate_actions(config, rng, bars)
        calendar = self._gen_trading_calendar(config)
        fundamentals = self._gen_fundamentals(config, rng, bars)
        macro = self._gen_macro(config, rng)
        news = self._gen_news(config, rng, bars)
        quality = self._quality_report(config, bars, fundamentals)
        lineage = DatasetLineage(
            tables=["market", "corporate_actions", "trading_calendar", "fundamentals", "macro", "news"],
            fields=[
                "open",
                "high",
                "low",
                "close",
                "volume",
                "spread_bps",
                "action_type",
                "session_date",
                "pe_ratio",
                "roe",
                "macro_value",
                "sentiment",
            ],
            time_range={
                "start_date": config.start_date.isoformat(),
                "end_date": config.end_date.isoformat(),
            },
            filters={"symbol": config.symbol, "market": config.market},
        )

        return GeneratedDataset(
            dataset_id=config.dataset_id,
            dataset_version=dataset_version,
            seed=config.seed,
            generation_config=config.canonical_payload(),
            lineage=lineage,
            quality_report=quality,
            market=bars,
            corporate_actions=corp_actions,
            trading_calendar=calendar,
            fundamentals=fundamentals,
            macro=macro,
            news=news,
        )

    def _gen_market_bars(self, config: MockDatasetConfig, rng: random.Random) -> list[OHLCVBar]:
        bars: list[OHLCVBar] = []
        price = config.base_price
        anchor_price = config.base_price
        prev_ret = 0.0
        current = config.start_date
        idx = 0
        is_crypto = config.market.upper() == "CRYPTO"
        profile = self._market_profile(config.market.upper())

        while current <= config.end_date:
            if (not is_crypto) and current.weekday() >= 5:
                current += timedelta(days=1)
                continue

            ts = datetime.combine(current, time(16, 0), tzinfo=UTC)
            regime = profile["vol_low"] if (idx // 50) % 2 == 0 else profile["vol_high"]
            in_high_vol_window = (
                config.inject_high_vol_segment
                and config.high_vol_start_day <= idx <= config.high_vol_end_day
            )
            if in_high_vol_window:
                regime *= config.high_vol_scale
            jump = (
                rng.uniform(-profile["jump_scale"], profile["jump_scale"])
                if rng.random() < profile["jump_prob"]
                else 0.0
            )
            if in_high_vol_window and rng.random() < 0.2:
                jump += rng.uniform(-0.12, 0.12)
            mean_reversion = profile["mean_reversion"] * ((anchor_price / max(price, 1e-6)) - 1.0)
            trend = profile["autocorr"] * prev_ret
            ret = profile["drift"] + trend + mean_reversion + rng.gauss(0.0, regime) + jump
            ret = max(-0.35, min(0.35, ret))

            o = price
            c = max(0.5, o * (1.0 + ret))
            high = max(o, c) * (1 + abs(rng.gauss(0, regime * 0.35)))
            low = min(o, c) * (1 - abs(rng.gauss(0, regime * 0.35)))
            volume = max(
                10_000.0,
                profile["volume_base"] * (1 + abs(ret) * profile["volume_ret_scale"] + rng.random() * 0.5),
            )
            spread_bps = max(0.5, (regime * 10000) * profile["spread_mult"] * (0.15 + rng.random() * 0.5))

            is_missing = rng.random() < config.missing_rate_target
            is_outlier = rng.random() < config.outlier_rate_target
            if is_outlier:
                c = max(0.5, c * (1.0 + rng.choice([-1, 1]) * rng.uniform(0.05, 0.2)))

            bar = OHLCVBar(
                ts=ts,
                open=o,
                high=high,
                low=low,
                close=c,
                volume=volume,
                spread_bps=spread_bps,
                is_missing=is_missing,
                is_outlier=is_outlier,
            )
            if is_missing:
                bar.volume = 0.0

            bars.append(bar)
            prev_ret = ret
            anchor_price = (anchor_price * profile["anchor_alpha"]) + (c * (1.0 - profile["anchor_alpha"]))
            price = c
            current += timedelta(days=1)
            idx += 1

        return bars

    def _market_profile(self, market: str) -> dict[str, float]:
        key = market.upper()
        if key == "US":
            return {
                "drift": 0.0005,
                "vol_low": 0.004,
                "vol_high": 0.01,
                "jump_prob": 0.008,
                "jump_scale": 0.06,
                "autocorr": 0.45,
                "mean_reversion": 0.01,
                "spread_mult": 0.65,
                "volume_base": 1_600_000.0,
                "volume_ret_scale": 10.0,
                "anchor_alpha": 0.975,
            }
        if key == "CN":
            return {
                "drift": 0.00035,
                "vol_low": 0.01,
                "vol_high": 0.026,
                "jump_prob": 0.05,
                "jump_scale": 0.1,
                "autocorr": 0.08,
                "mean_reversion": 0.11,
                "spread_mult": 1.2,
                "volume_base": 1_050_000.0,
                "volume_ret_scale": 13.0,
                "anchor_alpha": 0.965,
            }
        if key == "JP":
            return {
                "drift": 0.00015,
                "vol_low": 0.009,
                "vol_high": 0.022,
                "jump_prob": 0.04,
                "jump_scale": 0.07,
                "autocorr": -0.35,
                "mean_reversion": 0.5,
                "spread_mult": 0.85,
                "volume_base": 900_000.0,
                "volume_ret_scale": 9.0,
                "anchor_alpha": 0.88,
            }
        if key == "CRYPTO":
            return {
                "drift": 0.0008,
                "vol_low": 0.018,
                "vol_high": 0.045,
                "jump_prob": 0.08,
                "jump_scale": 0.15,
                "autocorr": 0.22,
                "mean_reversion": 0.04,
                "spread_mult": 1.75,
                "volume_base": 2_000_000.0,
                "volume_ret_scale": 18.0,
                "anchor_alpha": 0.985,
            }
        return {
            "drift": 0.0003,
            "vol_low": 0.008,
            "vol_high": 0.02,
            "jump_prob": 0.03,
            "jump_scale": 0.08,
            "autocorr": 0.05,
            "mean_reversion": 0.1,
            "spread_mult": 1.0,
            "volume_base": 1_000_000.0,
            "volume_ret_scale": 12.0,
            "anchor_alpha": 0.97,
        }

    def _gen_corporate_actions(
        self, config: MockDatasetConfig, rng: random.Random, bars: list[OHLCVBar]
    ) -> list[CorporateAction]:
        if not bars:
            return []
        rows: list[CorporateAction] = []
        if len(bars) >= 20:
            rows.append(
                CorporateAction(
                    symbol=config.symbol,
                    action_type="dividend",
                    ex_date=bars[min(10, len(bars) - 1)].ts.date(),
                    value=round(rng.uniform(0.1, 1.5), 4),
                )
            )
        if len(bars) >= 40:
            rows.append(
                CorporateAction(
                    symbol=config.symbol,
                    action_type="split",
                    ex_date=bars[min(30, len(bars) - 1)].ts.date(),
                    value=2.0,
                )
            )
        return rows

    def _gen_trading_calendar(self, config: MockDatasetConfig) -> list[TradingCalendarDay]:
        rows: list[TradingCalendarDay] = []
        current = config.start_date
        market = config.market.upper()
        while current <= config.end_date:
            is_open = True if market == "CRYPTO" else current.weekday() < 5
            if market == "US":
                open_time, close_time, timezone = "09:30", "16:00", "America/New_York"
            elif market == "CN":
                open_time, close_time, timezone = "09:30", "15:00", "Asia/Shanghai"
            elif market == "JP":
                open_time, close_time, timezone = "09:00", "15:00", "Asia/Tokyo"
            elif market == "CRYPTO":
                open_time, close_time, timezone = "00:00", "23:59", "UTC"
            else:
                open_time, close_time, timezone = "09:30", "16:00", "UTC"
            rows.append(
                TradingCalendarDay(
                    market=config.market,
                    session_date=current,
                    is_open=is_open,
                    open_time=open_time if is_open else "00:00",
                    close_time=close_time if is_open else "00:00",
                    timezone=timezone,
                )
            )
            current += timedelta(days=1)
        return rows

    def _gen_fundamentals(
        self, config: MockDatasetConfig, rng: random.Random, bars: list[OHLCVBar]
    ) -> list[FundamentalPoint]:
        if not bars:
            return []

        fundamentals: list[FundamentalPoint] = []
        bar_index = {bar.ts.date(): bar for bar in bars}
        current = date(config.start_date.year, config.start_date.month, 1)

        while current <= config.end_date:
            proxy_day = bar_index.get(current)
            price_proxy = proxy_day.close if proxy_day else config.base_price
            pe = max(5.0, 30.0 - (price_proxy / config.base_price) * 10 + rng.gauss(0, 1.2))
            roe = max(0.01, min(0.5, 0.1 + rng.gauss(0, 0.02)))
            lag_days = 1 if rng.random() < config.delayed_rate_target else 0
            is_backfilled = rng.random() < config.backfill_rate_target
            publish_time = datetime.combine(current, time(20, 0), tzinfo=UTC)

            fundamentals.append(
                FundamentalPoint(
                    symbol=config.symbol,
                    report_date=current,
                    publish_time=publish_time,
                    availability_lag_days=lag_days,
                    pe_ratio=pe,
                    roe=roe,
                    is_backfilled=is_backfilled,
                )
            )
            year = current.year + (1 if current.month == 12 else 0)
            month = 1 if current.month == 12 else current.month + 1
            current = date(year, month, 1)
        return fundamentals

    def _gen_news(
        self, config: MockDatasetConfig, rng: random.Random, bars: list[OHLCVBar]
    ) -> list[NewsEvent]:
        news: list[NewsEvent] = []
        for bar in bars:
            if rng.random() < 0.12:
                sentiment = max(-1.0, min(1.0, rng.gauss(0.0, 0.45)))
                news.append(
                    NewsEvent(
                        ts=bar.ts - timedelta(hours=2),
                        symbol=config.symbol,
                        headline=f"{config.symbol} mock event on {bar.ts.date().isoformat()}",
                        sentiment=sentiment,
                    )
                )
        return news

    def _gen_macro(self, config: MockDatasetConfig, rng: random.Random) -> list[MacroPoint]:
        rows: list[MacroPoint] = []
        current = date(config.start_date.year, config.start_date.month, 1)
        while current <= config.end_date:
            publish = datetime.combine(current, time(13, 30), tzinfo=UTC)
            rows.append(
                MacroPoint(
                    series="CPI_YOY",
                    value=round(1.5 + rng.random() * 4.0, 3),
                    publish_time=publish,
                    revision=0,
                )
            )
            year = current.year + (1 if current.month == 12 else 0)
            month = 1 if current.month == 12 else current.month + 1
            current = date(year, month, 1)
        return rows

    def _quality_report(
        self, config: MockDatasetConfig, bars: list[OHLCVBar], fundamentals: list[FundamentalPoint]
    ) -> DataQualityReport:
        total = max(1, len(bars))
        missing = sum(1 for bar in bars if bar.is_missing)
        outliers = sum(1 for bar in bars if bar.is_outlier)
        delayed = sum(1 for point in fundamentals if point.availability_lag_days > 0)
        backfilled = sum(1 for point in fundamentals if point.is_backfilled)
        fundamentals_total = max(1, len(fundamentals))

        return DataQualityReport(
            total_rows=len(bars),
            missing_rate=missing / total,
            delayed_rate=delayed / fundamentals_total,
            backfill_rate=backfilled / fundamentals_total,
            outlier_rate=outliers / total,
            survivorship_bias_enabled=config.include_survivorship_bias,
            survivorship_bias_risk="high" if config.include_survivorship_bias else "low",
        )
