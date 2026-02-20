import hashlib
import re
from datetime import UTC, datetime, timedelta

from openfinance.external_adapters.base import (
    ExternalMacroItem,
    ExternalNewsItem,
    MacroProviderBase,
    NewsProviderBase,
)


def _seed(query: str, salt: str) -> int:
    digest = hashlib.sha1(f"{salt}:{query}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _slug(text: str, max_len: int = 40) -> str:
    raw = "_".join(re.findall(r"[a-z0-9]+", text.lower()))
    if not raw:
        raw = "market_update"
    return raw[:max_len]


class MockNewsProvider(NewsProviderBase):
    provider_name = "mock-news"

    _sources = [
        "GlobalWire Finance",
        "Macro Daily Desk",
        "Street Signals",
        "Market Pulse Terminal",
        "OpenFinance Mock News",
    ]

    _angles = [
        "liquidity repricing after policy guidance",
        "valuation compression amid higher real yields",
        "sector rotation toward defensive quality",
        "cross-asset volatility regime transition",
        "earnings revision dispersion widens",
    ]

    def search(self, query: str, limit: int = 5) -> list[ExternalNewsItem]:
        n = max(1, min(limit, 10))
        base = _seed(query, "news")
        topic = query.strip() or "market outlook"
        rows: list[ExternalNewsItem] = []
        now = datetime.now(UTC)
        for i in range(n):
            source = self._sources[(base + i) % len(self._sources)]
            angle = self._angles[(base + i * 3) % len(self._angles)]
            headline = f"{topic[:64]}: {angle}"
            ts = now - timedelta(hours=6 * (i + 1))
            slug = _slug(f"{topic}_{angle}_{i}")
            rows.append(
                ExternalNewsItem(
                    item_id=f"news_{base % 10000}_{i + 1}",
                    headline=headline,
                    source=source,
                    timestamp=ts,
                    url=f"https://mock.news/{slug}",
                    summary=(
                        f"{source} reports {angle}. "
                        "Desk notes emphasize position crowding and execution cost sensitivity."
                    ),
                )
            )
        return rows


class MockMacroProvider(MacroProviderBase):
    provider_name = "mock-macro"

    _institutions = [
        "Macro Research Forum",
        "Global Rates Monitor",
        "Policy Signals Lab",
        "OpenFinance Mock Macro",
    ]

    _signals = [
        "inflation expectations stayed elevated while growth momentum cooled",
        "credit impulse improved but transmission remained uneven",
        "policy stance turned more data dependent under sticky services inflation",
        "USD liquidity tightened and cross-market risk appetite weakened",
        "real rates rose and pressured long-duration valuations",
    ]

    def search(self, query: str, limit: int = 5) -> list[ExternalMacroItem]:
        n = max(1, min(limit, 10))
        base = _seed(query, "macro")
        topic = query.strip() or "macro regime"
        rows: list[ExternalMacroItem] = []
        now = datetime.now(UTC)
        for i in range(n):
            institution = self._institutions[(base + i) % len(self._institutions)]
            signal = self._signals[(base + i * 5) % len(self._signals)]
            headline = f"Macro brief on {topic[:48]}: {signal}"
            ts = now - timedelta(days=(i + 1))
            slug = _slug(f"{topic}_{institution}_{i}")
            rows.append(
                ExternalMacroItem(
                    item_id=f"macro_{base % 10000}_{i + 1}",
                    headline=headline,
                    source=institution,
                    timestamp=ts,
                    url=f"https://mock.macro/{slug}",
                    summary=(
                        f"{institution} indicates {signal}. "
                        "Allocation desks suggest balancing drawdown control with policy-path uncertainty."
                    ),
                )
            )
        return rows

