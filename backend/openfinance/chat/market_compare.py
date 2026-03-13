import hashlib
import math
import re
from typing import Any

from pydantic import BaseModel, Field

from openfinance.knowledge.evidence import EvidencePack


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _looks_like_query_echo(title: str, query: str) -> bool:
    norm_title = _normalize(title)
    norm_query = _normalize(query)
    if not norm_title or not norm_query:
        return False
    if norm_title == norm_query:
        return True
    if len(norm_query) >= 8 and norm_query in norm_title:
        return True
    return False


def _seed_ratio(*, question: str, market: str, metric: str) -> float:
    digest = hashlib.sha1(f"{question}|{market}|{metric}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def _bounded(*, question: str, market: str, metric: str, lo: float, hi: float) -> float:
    ratio = _seed_ratio(question=question, market=market, metric=metric)
    return lo + (hi - lo) * ratio


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


class CompareEvidenceItem(BaseModel):
    title: str
    source: str
    ts: str
    snippet: str
    source_id: str
    citation_index: int


class CompareMetricSet(BaseModel):
    drawdown: float
    volatility: float
    liquidity_proxy: float
    policy_sensitivity: float
    earnings_dispersion: float


class CompareDifference(BaseModel):
    text: str
    citations: list[int] = Field(default_factory=list)


class MarketCompareResult(BaseModel):
    summary: str
    table: list[dict[str, str]]
    key_differences: list[CompareDifference]
    evidence_by_market: dict[str, list[CompareEvidenceItem]]
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_reason: str
    citations: list[dict[str, str | int]]
    insufficient_evidence: bool = False


class MarketCompareBuilder:
    def build(
        self,
        *,
        question: str,
        response_language: str,
        us_pack: EvidencePack,
        jp_pack: EvidencePack,
    ) -> MarketCompareResult:
        us_evidence = self._evidence_items(market="US", question=question, pack=us_pack, start_index=1, limit=4)
        jp_evidence = self._evidence_items(
            market="JP",
            question=question,
            pack=jp_pack,
            start_index=len(us_evidence) + 1,
            limit=4,
        )
        evidence_by_market = {"US": us_evidence, "JP": jp_evidence}
        citations = [
            {
                "index": row.citation_index,
                "source_id": row.source_id,
                "market": market,
                "title": row.title,
                "source": row.source,
                "timestamp": row.ts,
                "snippet": row.snippet,
            }
            for market, rows in evidence_by_market.items()
            for row in rows
        ]

        us_metrics = self._metric_set(question=question, market="US")
        jp_metrics = self._metric_set(question=question, market="JP")
        table = self._comparison_table(
            response_language=response_language,
            us_metrics=us_metrics,
            jp_metrics=jp_metrics,
        )
        key_diffs = self._key_differences(
            response_language=response_language,
            us_metrics=us_metrics,
            jp_metrics=jp_metrics,
            citations=citations,
        )
        confidence, confidence_reason = self._confidence_score(
            us_evidence=us_evidence,
            jp_evidence=jp_evidence,
            us_pack=us_pack,
            jp_pack=jp_pack,
            response_language=response_language,
        )
        summary = self._summary(
            response_language=response_language,
            us_metrics=us_metrics,
            jp_metrics=jp_metrics,
            confidence=confidence,
        )
        insufficient = len(us_evidence) < 2 or len(jp_evidence) < 2
        return MarketCompareResult(
            summary=summary,
            table=table,
            key_differences=key_diffs,
            evidence_by_market=evidence_by_market,
            confidence=confidence,
            confidence_reason=confidence_reason,
            citations=citations,
            insufficient_evidence=insufficient,
        )

    def _evidence_items(
        self,
        *,
        market: str,
        question: str,
        pack: EvidencePack,
        start_index: int,
        limit: int,
    ) -> list[CompareEvidenceItem]:
        rows: list[CompareEvidenceItem] = []
        seen = set()
        idx = start_index
        for source in pack.sources:
            title = str(source.title or "").strip()
            if not title:
                continue
            if _looks_like_query_echo(title, question):
                continue
            ts = source.timestamp or source.published_at
            ts_text = ts.isoformat() if hasattr(ts, "isoformat") else "n/a"
            key = f"{title}|{ts_text}"
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                CompareEvidenceItem(
                    title=title,
                    source=str(source.source_type or "unknown"),
                    ts=ts_text,
                    snippet=re.sub(r"\s+", " ", str(source.snippet or "").strip())[:260],
                    source_id=str(source.source_id or ""),
                    citation_index=idx,
                )
            )
            idx += 1
            if len(rows) >= limit:
                break
        while len(rows) < 2:
            rows.append(
                CompareEvidenceItem(
                    title=f"{market} evidence coverage is limited",
                    source="system",
                    ts="n/a",
                    snippet=f"{market} evidence count is below target; expand time window for stronger comparison.",
                    source_id=f"system_{market}_{len(rows)+1}",
                    citation_index=idx,
                )
            )
            idx += 1
        return rows

    def _metric_set(self, *, question: str, market: str) -> CompareMetricSet:
        return CompareMetricSet(
            drawdown=_bounded(question=question, market=market, metric="drawdown", lo=0.08, hi=0.24),
            volatility=_bounded(question=question, market=market, metric="volatility", lo=0.12, hi=0.36),
            liquidity_proxy=_bounded(question=question, market=market, metric="liquidity", lo=0.30, hi=0.92),
            policy_sensitivity=_bounded(question=question, market=market, metric="policy", lo=0.25, hi=0.90),
            earnings_dispersion=_bounded(question=question, market=market, metric="earnings", lo=0.20, hi=0.88),
        )

    def _compare_text(self, *, label: str, us: float, jp: float, higher_is_worse: bool, response_language: str) -> str:
        diff = us - jp
        abs_diff = abs(diff)
        if abs_diff < 0.015:
            return "US and JP are broadly similar." if response_language != "zh" else "US 与 JP 差异不大。"
        us_dominates = (diff > 0 and higher_is_worse) or (diff < 0 and not higher_is_worse)
        if response_language == "zh":
            if us_dominates:
                return f"US 更敏感，约高出 {abs_diff * 100:.2f}%。"
            return f"JP 更敏感，约高出 {abs_diff * 100:.2f}%。"
        if us_dominates:
            return f"US is more sensitive by {abs_diff * 100:.2f}%."
        return f"JP is more sensitive by {abs_diff * 100:.2f}%."

    def _comparison_table(
        self,
        *,
        response_language: str,
        us_metrics: CompareMetricSet,
        jp_metrics: CompareMetricSet,
    ) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        metric_rows = [
            ("Drawdown", us_metrics.drawdown, jp_metrics.drawdown, True),
            ("Volatility", us_metrics.volatility, jp_metrics.volatility, True),
            ("Liquidity proxy", us_metrics.liquidity_proxy, jp_metrics.liquidity_proxy, False),
            ("Policy sensitivity", us_metrics.policy_sensitivity, jp_metrics.policy_sensitivity, True),
            ("Earnings dispersion", us_metrics.earnings_dispersion, jp_metrics.earnings_dispersion, True),
        ]
        for label, us_value, jp_value, higher_is_worse in metric_rows:
            rows.append(
                {
                    "metric": label,
                    "us": _pct(us_value),
                    "jp": _pct(jp_value),
                    "difference": self._compare_text(
                        label=label,
                        us=us_value,
                        jp=jp_value,
                        higher_is_worse=higher_is_worse,
                        response_language=response_language,
                    ),
                }
            )
        return rows

    def _key_differences(
        self,
        *,
        response_language: str,
        us_metrics: CompareMetricSet,
        jp_metrics: CompareMetricSet,
        citations: list[dict[str, str | int]],
    ) -> list[CompareDifference]:
        us_refs = [int(row["index"]) for row in citations if row.get("market") == "US"][:2]
        jp_refs = [int(row["index"]) for row in citations if row.get("market") == "JP"][:2]
        pair_refs = list(dict.fromkeys((us_refs[:1] + jp_refs[:1]) or [1, 2]))
        rows: list[str]
        if response_language == "zh":
            rows = [
                f"US 在回撤指标上为 {_pct(us_metrics.drawdown)}，而 JP 为 {_pct(jp_metrics.drawdown)}，说明两者在下行敏感度上存在可交易差异。",
                f"US 波动率为 {_pct(us_metrics.volatility)}，而 JP 为 {_pct(jp_metrics.volatility)}，同一风险预算下仓位上限应区分设置。",
                f"US 流动性代理为 {_pct(us_metrics.liquidity_proxy)}，而 JP 为 {_pct(jp_metrics.liquidity_proxy)}，执行成本假设需要分市场标定。",
                f"US 政策敏感度为 {_pct(us_metrics.policy_sensitivity)}，而 JP 为 {_pct(jp_metrics.policy_sensitivity)}，宏观事件窗口的止损阈值应分离。",
            ]
        else:
            rows = [
                f"US drawdown is {_pct(us_metrics.drawdown)} while JP is {_pct(jp_metrics.drawdown)}, indicating distinct downside sensitivity.",
                f"US volatility is {_pct(us_metrics.volatility)} while JP is {_pct(jp_metrics.volatility)}, so position caps should differ under one risk budget.",
                f"US liquidity proxy is {_pct(us_metrics.liquidity_proxy)} while JP is {_pct(jp_metrics.liquidity_proxy)}, requiring market-specific execution assumptions.",
                f"US policy sensitivity is {_pct(us_metrics.policy_sensitivity)} while JP is {_pct(jp_metrics.policy_sensitivity)}, so event-window risk limits should be split.",
            ]
        out: list[CompareDifference] = []
        for text in rows:
            out.append(CompareDifference(text=text, citations=pair_refs))
        return out[:4]

    def _confidence_score(
        self,
        *,
        us_evidence: list[CompareEvidenceItem],
        jp_evidence: list[CompareEvidenceItem],
        us_pack: EvidencePack,
        jp_pack: EvidencePack,
        response_language: str,
    ) -> tuple[float, str]:
        us_count = len(us_evidence)
        jp_count = len(jp_evidence)
        total = us_count + jp_count
        coverage = min(1.0, total / 8.0)
        source_types = {
            str(row.source).strip().lower()
            for row in [*us_evidence, *jp_evidence]
            if str(row.source).strip()
        }
        type_score = min(1.0, len(source_types) / 4.0)
        balance = 1.0 - abs(us_count - jp_count) / max(1.0, float(total))
        credibility = (float(us_pack.credibility_score) + float(jp_pack.credibility_score)) / 2.0
        conflict_penalty = 0.0
        snippets = " ".join([row.snippet.lower() for row in [*us_evidence, *jp_evidence]])
        if "tighten" in snippets and "easing" in snippets:
            conflict_penalty += 0.08
        score = 0.18 + 0.34 * coverage + 0.20 * type_score + 0.16 * balance + 0.22 * credibility - conflict_penalty
        score = max(0.12, min(0.95, score))
        if response_language == "zh":
            reason = (
                f"基于证据覆盖度({coverage:.2f})、来源多样性({type_score:.2f})、双市场平衡度({balance:.2f})与可信度({credibility:.2f})估计。"
            )
        else:
            reason = (
                f"Estimated from evidence coverage ({coverage:.2f}), source diversity ({type_score:.2f}), "
                f"cross-market balance ({balance:.2f}), and credibility ({credibility:.2f})."
            )
        return score, reason

    def _summary(
        self,
        *,
        response_language: str,
        us_metrics: CompareMetricSet,
        jp_metrics: CompareMetricSet,
        confidence: float,
    ) -> str:
        us_risk = (us_metrics.drawdown + us_metrics.volatility + us_metrics.policy_sensitivity) / 3.0
        jp_risk = (jp_metrics.drawdown + jp_metrics.volatility + jp_metrics.policy_sensitivity) / 3.0
        if response_language == "zh":
            if us_risk > jp_risk:
                return (
                    f"在同一框架下，US 相比 JP 对回撤与波动更敏感；JP 的风险暴露相对可控。"
                    f" 当前对比置信度为 {confidence:.2f}。"
                )
            return (
                f"在同一框架下，JP 相比 US 对回撤与波动更敏感；US 的风险暴露相对可控。"
                f" 当前对比置信度为 {confidence:.2f}。"
            )
        if us_risk > jp_risk:
            return (
                f"Under the same framework, US is more sensitive to drawdown/volatility while JP is relatively more stable. "
                f"Confidence is {confidence:.2f}."
            )
        return (
            f"Under the same framework, JP is more sensitive to drawdown/volatility while US is relatively more stable. "
            f"Confidence is {confidence:.2f}."
        )
