import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from openfinance.core.config import settings
from openfinance.knowledge.evidence import EvidenceSource
from openfinance.llm.provider import LLMProviderRegistry, ZhipuGLM47Provider


_PROMO_WORDS = {
    "guaranteed",
    "exclusive",
    "limited time",
    "buy now",
    "amazing",
    "best ever",
    "稳赚",
    "立刻买入",
    "保本",
    "暴涨",
    "神奇",
}
_METHOD_WORDS = {
    "method",
    "methodology",
    "sample",
    "dataset",
    "regression",
    "confidence interval",
    "p-value",
    "robustness",
    "oos",
    "ablation",
    "实验",
    "样本",
    "方法",
    "回归",
    "显著性",
}
_AUTHORITATIVE_HINTS = {
    "reuters",
    "bloomberg",
    "wsj",
    "ft.com",
    "sec.gov",
    ".gov",
    ".edu",
    "imf",
    "world bank",
    "federal reserve",
    "央行",
    "统计局",
}


@dataclass
class SemanticAssistResult:
    score: float
    tags: list[str]
    mode: str


class EvidenceCredibilityScorer:
    def __init__(self, *, seed: int | None = None) -> None:
        self.seed = int(seed if seed is not None else settings.credibility_seed)
        self._anchor_time = datetime.now(UTC).replace(microsecond=0)
        self.semantic_enabled = bool(settings.credibility_semantic_enabled)
        self.semantic_use_llm = bool(settings.credibility_semantic_use_llm)
        self.hard_weights = self._normalize(
            {
                "source_type": float(settings.credibility_weight_source_type),
                "recency": float(settings.credibility_weight_recency),
                "citation_density": float(settings.credibility_weight_citation_density),
                "conflict_score": float(settings.credibility_weight_conflict),
            }
        )
        self.final_weights = self._normalize(
            {
                "hard": float(settings.credibility_weight_hard),
                "semantic": float(settings.credibility_weight_semantic),
            }
        )
        self._llm_registry: LLMProviderRegistry | None = None
        if self.semantic_use_llm:
            registry = LLMProviderRegistry()
            registry.register(ZhipuGLM47Provider(), is_default=True)
            self._llm_registry = registry

    def score_sources(self, sources: list[EvidenceSource]) -> tuple[list[EvidenceSource], dict[str, Any]]:
        scored_sources: list[EvidenceSource] = []
        source_rows: list[dict[str, Any]] = []
        for source in sources:
            score_row = self._score_one(source)
            updated = source.model_copy(
                update={
                    "source_type": score_row["source_type"],
                    "credibility_score": float(score_row["final_score"]),
                    "time_relevance": float(score_row["hard_signals"]["recency"]),
                    "credibility_breakdown": score_row,
                }
            )
            scored_sources.append(updated)
            source_rows.append(score_row)
        hard_mean = self._mean([float(row["hard_score"]) for row in source_rows], default=0.5)
        semantic_mean = self._mean(
            [float((row.get("semantic") or {}).get("score", 0.5)) for row in source_rows],
            default=0.5,
        )
        final_mean = self._mean([float(row["final_score"]) for row in source_rows], default=0.5)
        breakdown = {
            "scoring_version": "credibility_v2",
            "seed": self.seed,
            "anchor_time": self._anchor_time.isoformat(),
            "weights": {
                "hard_signals": self.hard_weights,
                "final": self.final_weights,
            },
            "source_level": source_rows,
            "aggregate": {
                "source_count": len(source_rows),
                "hard_score_mean": round(hard_mean, 6),
                "semantic_score_mean": round(semantic_mean, 6),
                "final_score_mean": round(final_mean, 6),
            },
        }
        return scored_sources, breakdown

    def _score_one(self, source: EvidenceSource) -> dict[str, Any]:
        source_type = self._infer_source_type(source)
        combined_text = f"{source.title}\n{source.snippet}".strip()
        hard_signals = {
            "source_type": self._source_type_score(source_type),
            "recency": self._recency_score(source.timestamp or source.published_at),
            "citation_density": self._citation_density_score(combined_text),
            "conflict_score": self._conflict_score(combined_text),
        }
        hard_score = sum(float(hard_signals[k]) * float(self.hard_weights[k]) for k in self.hard_weights)
        semantic = self._semantic_assist(source=source, source_type=source_type, text=combined_text)
        semantic_score = float(semantic.score)
        if self.semantic_enabled:
            final_score = (
                hard_score * float(self.final_weights["hard"])
                + semantic_score * float(self.final_weights["semantic"])
            )
        else:
            final_score = hard_score
        return {
            "source_id": source.source_id,
            "source_type": source_type,
            "hard_signals": {k: round(float(v), 6) for k, v in hard_signals.items()},
            "hard_score": round(hard_score, 6),
            "semantic": {
                "enabled": self.semantic_enabled,
                "score": round(semantic_score, 6),
                "tags": semantic.tags,
                "mode": semantic.mode,
            },
            "weights": {
                "hard_signals": self.hard_weights,
                "final": self.final_weights,
            },
            "final_score": round(max(0.0, min(1.0, final_score)), 6),
            "seed": self.seed,
        }

    def _semantic_assist(self, *, source: EvidenceSource, source_type: str, text: str) -> SemanticAssistResult:
        rule_based = self._rule_semantic(text=text, source=source, source_type=source_type)
        if (not self.semantic_enabled) or (not self.semantic_use_llm) or self._llm_registry is None:
            return rule_based
        llm = self._llm_registry.get()
        prompt = (
            "Return strict JSON only.\n"
            'Schema: {"score": float(0..1), "rationale_tags": [string]}.\n'
            "Use tags from this set when applicable: "
            "authoritative_source, promotional_language, missing_methods, methods_disclosed, data_cited, conflicting_claims.\n"
            f"source_type={source_type}\n"
            f"title={source.title}\n"
            f"text={text[:1200]}"
        )
        response = llm.complete(prompt, max_tokens=180, temperature=0.0)
        parsed = self._extract_json(response.content)
        if not isinstance(parsed, dict):
            return rule_based
        raw_score = parsed.get("score")
        raw_tags = parsed.get("rationale_tags")
        if not isinstance(raw_score, (int, float)) or not isinstance(raw_tags, list):
            return rule_based
        tags = [str(row).strip() for row in raw_tags if str(row).strip()]
        if not tags:
            return rule_based
        score = max(0.0, min(1.0, float(raw_score)))
        return SemanticAssistResult(score=round(score, 6), tags=tags[:8], mode=response.mode)

    def _rule_semantic(self, *, text: str, source: EvidenceSource, source_type: str) -> SemanticAssistResult:
        low = text.lower()
        tags: list[str] = []
        score = 0.5
        promo_hits = self._keyword_hits(low, _PROMO_WORDS)
        method_hits = self._keyword_hits(low, _METHOD_WORDS)
        auth_hits = self._keyword_hits((source.title + " " + (source.url or source.uri or "")).lower(), _AUTHORITATIVE_HINTS)

        if auth_hits > 0 or source_type in {"authoritative_news", "research_paper", "regulatory_filing"}:
            tags.append("authoritative_source")
            score += 0.2
        if promo_hits > 0:
            tags.append("promotional_language")
            score -= min(0.35, promo_hits * 0.08)
        if method_hits > 0:
            tags.append("methods_disclosed")
            score += min(0.25, method_hits * 0.05)
        else:
            tags.append("missing_methods")
            score -= 0.12

        citation_pattern = re.compile(r"\[(\d+)\]|doi:|source:|table\s*\d+|figure\s*\d+|dataset", flags=re.IGNORECASE)
        if citation_pattern.search(text):
            tags.append("data_cited")
            score += 0.1
        if ("no risk" in low and "guaranteed" in low) or ("稳赚" in low and "无风险" in low):
            tags.append("conflicting_claims")
            score -= 0.18
        dedup_tags = list(dict.fromkeys(tags))
        return SemanticAssistResult(
            score=round(max(0.0, min(1.0, score)), 6),
            tags=dedup_tags[:8],
            mode="rule_fallback",
        )

    def _infer_source_type(self, source: EvidenceSource) -> str:
        sid = source.source_id.lower()
        title = source.title.lower()
        ref = f"{source.url or ''} {source.uri or ''} {source.full_text_ref or ''}".lower()
        merged = f"{sid} {title} {ref}"
        if "mock_macro" in sid:
            return "macro_release"
        if "mock_news" in sid:
            return "newswire"
        if any(token in merged for token in [".gov", ".edu", "sec.gov", "federalreserve", "imf", "worldbank"]):
            return "regulatory_filing"
        if any(token in merged for token in ["paper", "journal", "ssrn", "arxiv", "methodology", "研究"]):
            return "research_paper"
        if self._keyword_hits(merged, _PROMO_WORDS) > 0:
            return "promotional_content"
        if any(token in merged for token in ["reuters", "bloomberg", "wsj", "ft.com"]):
            return "authoritative_news"
        return "local_corpus"

    def _source_type_score(self, source_type: str) -> float:
        table = {
            "regulatory_filing": 0.9,
            "research_paper": 0.86,
            "authoritative_news": 0.8,
            "macro_release": 0.76,
            "newswire": 0.7,
            "local_corpus": 0.64,
            "promotional_content": 0.28,
        }
        return float(table.get(source_type, 0.55))

    def _recency_score(self, ts: datetime | None) -> float:
        if ts is None:
            return 0.45
        age_days = max(0.0, (self._anchor_time - ts).total_seconds() / 86400.0)
        return round(max(0.25, math.exp(-age_days / 45.0)), 6)

    def _citation_density_score(self, text: str) -> float:
        if not text.strip():
            return 0.2
        pattern = re.compile(
            r"\[(\d+)\]|doi:|source:|table\s*\d+|figure\s*\d+|dataset|method|sample|regression|appendix",
            flags=re.IGNORECASE,
        )
        hits = len(pattern.findall(text))
        token_count = max(1, len(re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]", text)))
        density = hits / max(1.0, token_count / 80.0)
        return round(max(0.0, min(1.0, density / 4.0)), 6)

    def _conflict_score(self, text: str) -> float:
        low = text.lower()
        promo_hits = self._keyword_hits(low, _PROMO_WORDS)
        method_hits = self._keyword_hits(low, _METHOD_WORDS)
        penalty = min(0.55, promo_hits * 0.08)
        boost = min(0.3, method_hits * 0.04)
        if ("no risk" in low and "guaranteed" in low) or ("无风险" in low and "稳赚" in low):
            penalty += 0.2
        return round(max(0.0, min(1.0, 0.7 + boost - penalty)), 6)

    def _extract_json(self, text: str) -> dict[str, Any] | None:
        if not text:
            return None
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _keyword_hits(self, text: str, vocab: set[str]) -> int:
        count = 0
        for token in vocab:
            if token in text:
                count += 1
        return count

    def _normalize(self, values: dict[str, float]) -> dict[str, float]:
        total = sum(max(0.0, float(v)) for v in values.values())
        if total <= 0:
            fallback = 1.0 / max(1, len(values))
            return {k: round(fallback, 6) for k in values}
        return {k: round(max(0.0, float(v)) / total, 6) for k, v in values.items()}

    def _mean(self, rows: list[float], *, default: float) -> float:
        if not rows:
            return default
        return sum(rows) / len(rows)

