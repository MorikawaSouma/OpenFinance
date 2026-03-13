import hashlib
import math
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


def _normalize_topic(query: str) -> dict[str, str | list[str]]:
    low = query.lower()
    if any(token in query for token in ["\u7f8e\u80a1", "\u7eb3\u6307", "\u6807\u666e", "\u9053\u743c\u65af"]) or any(
        token in low for token in ["us", "sp500", "nasdaq", "dow", "s&p"]
    ):
        market = "US equities"
    elif any(token in query for token in ["\u65e5\u80a1", "\u65e5\u7ecf", "\u65e5\u672c"]) or any(
        token in low for token in ["nikkei", "japan", "jp"]
    ):
        market = "Japan equities"
    elif any(token in query for token in ["a\u80a1", "\u6caa\u6df1", "\u4e2d\u56fd\u80a1\u5e02"]) or any(
        token in low for token in ["china", "cn", "csi300"]
    ):
        market = "China equities"
    elif any(token in query for token in ["\u52a0\u5bc6", "\u6bd4\u7279\u5e01", "\u4ee5\u592a\u574a"]) or any(
        token in low for token in ["crypto", "bitcoin", "ethereum"]
    ):
        market = "Crypto assets"
    else:
        market = "Global equities"

    theme_map = [
        ("volatility", ["\u6ce2\u52a8", "\u9707\u8361", "volatility", "vix"]),
        ("liquidity", ["\u6d41\u52a8\u6027", "liquidity", "funding"]),
        ("earnings", ["\u76c8\u5229", "\u8d22\u62a5", "earnings", "guidance"]),
        ("valuation", ["\u4f30\u503c", "valuation", "multiple"]),
        ("policy", ["\u653f\u7b56", "\u5229\u7387", "fed", "\u592e\u884c", "rate"]),
        ("credit", ["\u4fe1\u7528", "credit", "spread"]),
    ]
    themes: list[str] = []
    for label, tokens in theme_map:
        if any(token in query for token in tokens) or any(token in low for token in tokens):
            themes.append(label)
    if not themes:
        themes = ["liquidity", "volatility", "earnings"]
    return {"market": market, "themes": themes[:3]}


def _ensure_diversity(titles: list[str], min_ratio: float = 0.6) -> list[str]:
    if not titles:
        return titles
    required = max(1, math.ceil(len(titles) * min_ratio))
    if len(set(titles)) >= required:
        return titles
    out = list(titles)
    for i in range(len(out)):
        if len(set(out)) >= required:
            break
        out[i] = f"{out[i]} | update {i + 1}"
    return out


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
        "policy expectations shifted faster than positioning",
        "liquidity premia repriced across index futures",
        "earnings revisions became more uneven across sectors",
        "defensive quality outperformed high-beta cyclicals",
        "real-rate pressure triggered valuation recalibration",
        "cross-asset correlations rose during intraday stress",
    ]

    _title_templates = [
        "{market}: volatility rises as policy expectations shift",
        "Liquidity repricing drives cross-asset volatility regime change",
        "Earnings dispersion widens amid tightening financial conditions",
        "{market}: defensive sectors gain as risk appetite cools",
        "Position crowding leaves {market} exposed to macro surprises",
        "{market}: valuation reset extends under higher real yields",
        "Funding sensitivity increases as liquidity conditions tighten",
        "{market}: investors rotate toward quality balance sheets",
        "Volatility term structure steepens on policy uncertainty",
        "Macro-sensitive sectors lag as execution costs rise",
        "{market}: breadth narrows while index concentration climbs",
        "Risk-premium repricing accelerates in late-session trading",
    ]

    _theme_phrases = {
        "volatility": "volatility remains elevated",
        "liquidity": "liquidity conditions stay tight",
        "earnings": "earnings revisions stay divergent",
        "valuation": "valuation pressure persists",
        "policy": "policy guidance remains data-dependent",
        "credit": "credit conditions are becoming selective",
    }

    def search(self, query: str, limit: int = 5) -> list[ExternalNewsItem]:
        n = max(1, min(limit, 10))
        base = _seed(query, "news")
        topic = _normalize_topic(query)
        market = str(topic["market"])
        themes = list(topic["themes"])
        rows: list[ExternalNewsItem] = []
        now = datetime.now(UTC)
        titles: list[str] = []

        for i in range(n):
            source = self._sources[(base + i) % len(self._sources)]
            angle = self._angles[(base + i * 3) % len(self._angles)]
            template = self._title_templates[(base + i * 5) % len(self._title_templates)]
            title = template.format(market=market)
            theme = themes[(base + i) % len(themes)]
            theme_phrase = self._theme_phrases.get(theme, "market positioning stays fragile")
            if "{" not in template:
                title = f"{title}; {theme_phrase}"
            titles.append(title)

            ts = now - timedelta(hours=4 * (i + 1))
            slug = _slug(f"{title}_{source}_{i}")
            rows.append(
                ExternalNewsItem(
                    item_id=f"news_{base % 10000}_{i + 1}",
                    headline=title,
                    source=source,
                    timestamp=ts,
                    url=f"https://mock.news/{slug}",
                    summary=(
                        f"{source} notes that {angle}. "
                        f"Desk color suggests {theme_phrase} with focus on drawdown control and execution quality."
                    ),
                )
            )

        diversified = _ensure_diversity(titles, min_ratio=0.6)
        for idx, title in enumerate(diversified):
            if idx < len(rows):
                rows[idx] = ExternalNewsItem(
                    item_id=rows[idx].item_id,
                    headline=title,
                    source=rows[idx].source,
                    timestamp=rows[idx].timestamp,
                    url=rows[idx].url,
                    summary=rows[idx].summary,
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
        "policy stance became more data dependent under sticky services inflation",
        "USD liquidity tightened and cross-market risk appetite weakened",
        "real rates rose and pressured long-duration valuations",
        "funding spreads widened while equity risk premium adjusted",
    ]

    _macro_templates = [
        "Macro brief: policy path remains data dependent under uneven growth",
        "Rates and liquidity monitor: real-yield pressure reshapes risk pricing",
        "Cross-asset macro watch: funding conditions tighten across regions",
        "Macro outlook: inflation persistence complicates easing expectations",
        "Policy and growth pulse: transmission remains uneven across sectors",
        "Macro strategy note: higher-for-longer narrative lifts discount rates",
    ]

    def search(self, query: str, limit: int = 5) -> list[ExternalMacroItem]:
        n = max(1, min(limit, 10))
        base = _seed(query, "macro")
        topic = _normalize_topic(query)
        market = str(topic["market"])
        themes = list(topic["themes"])
        rows: list[ExternalMacroItem] = []
        now = datetime.now(UTC)
        titles: list[str] = []

        for i in range(n):
            institution = self._institutions[(base + i) % len(self._institutions)]
            signal = self._signals[(base + i * 5) % len(self._signals)]
            template = self._macro_templates[(base + i * 2) % len(self._macro_templates)]
            theme = themes[(base + i) % len(themes)]
            title = f"{template} | {market} | {theme}"
            titles.append(title)

            ts = now - timedelta(days=(i + 1))
            slug = _slug(f"{title}_{institution}_{i}")
            rows.append(
                ExternalMacroItem(
                    item_id=f"macro_{base % 10000}_{i + 1}",
                    headline=title,
                    source=institution,
                    timestamp=ts,
                    url=f"https://mock.macro/{slug}",
                    summary=(
                        f"{institution} indicates {signal}. "
                        "Allocation desks continue to balance valuation pressure with drawdown and liquidity constraints."
                    ),
                )
            )

        diversified = _ensure_diversity(titles, min_ratio=0.6)
        for idx, title in enumerate(diversified):
            if idx < len(rows):
                rows[idx] = ExternalMacroItem(
                    item_id=rows[idx].item_id,
                    headline=title,
                    source=rows[idx].source,
                    timestamp=rows[idx].timestamp,
                    url=rows[idx].url,
                    summary=rows[idx].summary,
                )
        return rows
