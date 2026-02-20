import math
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from openfinance.external_adapters import (
    FilingsProviderBase,
    MacroProviderBase,
    MockMacroProvider,
    MockNewsProvider,
    NewsProviderBase,
)
from openfinance.external_adapters.base import ExternalMacroItem, ExternalNewsItem
from openfinance.knowledge.credibility import EvidenceCredibilityScorer
from openfinance.knowledge.evidence import EvidencePack, EvidenceSource


class RAGRetriever(ABC):
    @abstractmethod
    def retrieve_evidence_pack(self, query: str, top_k: int = 5) -> EvidencePack:
        raise NotImplementedError


@dataclass
class CorpusDocument:
    doc_id: str
    title: str
    uri: str
    text: str
    published_at: datetime


@dataclass
class CorpusChunk:
    chunk_id: str
    doc_id: str
    title: str
    uri: str
    text: str
    published_at: datetime
    tokens: list[str]
    tf: dict[str, int]
    length: int


class LocalCorpusRetriever(RAGRetriever):
    def __init__(self, corpus_dir: Path) -> None:
        self.corpus_dir = corpus_dir
        self.docs = self._load_docs(corpus_dir)
        self.chunks = self._build_chunks(self.docs)
        self.credibility_scorer = EvidenceCredibilityScorer()
        self.doc_count = len(self.chunks)
        self.avg_dl = (sum(chunk.length for chunk in self.chunks) / self.doc_count) if self.doc_count > 0 else 1.0
        self.df: dict[str, int] = {}
        for chunk in self.chunks:
            for token in set(chunk.tokens):
                self.df[token] = self.df.get(token, 0) + 1

    def retrieve_evidence_pack(self, query: str, top_k: int = 5) -> EvidencePack:
        if not self.chunks:
            return EvidencePack(
                query=query,
                sources=[],
                key_points=["No corpus documents available."],
                credibility_score=0.0,
                time_relevance=0.0,
                credibility_breakdown={
                    "scoring_version": "credibility_v2",
                    "source_level": [],
                    "aggregate": {"source_count": 0, "final_score_mean": 0.0},
                },
            )
        q_tokens = self._tokenize(query)
        q_embed = self._embed(q_tokens)

        scored: list[tuple[float, CorpusChunk]] = []
        for chunk in self.chunks:
            bm25 = self._bm25_score(q_tokens, chunk)
            sim = self._cosine(q_embed, self._embed(chunk.tokens))
            title_tokens = set(self._tokenize(chunk.title))
            qset = set(q_tokens)
            docset = set(chunk.tokens)
            title_hit = sum(1 for token in qset if token in title_tokens)
            intent_boost = 0.0
            if ("value" in qset) or ("\u4ef7\u503c" in qset):
                intent_boost += 1.6 if (("value" in docset) or ("\u4ef7\u503c" in docset)) else -0.15
            if ("trend" in qset) or ("\u8d8b\u52bf" in qset):
                intent_boost += 1.6 if (("trend" in docset) or ("\u8d8b\u52bf" in docset)) else -0.15
            if ("risk" in qset and "parity" in qset) or ("\u98ce\u9669" in qset and "\u5e73\u4ef7" in qset):
                parity_hit = ("risk" in docset and "parity" in docset) or ("\u98ce\u9669" in docset and "\u5e73\u4ef7" in docset)
                intent_boost += 1.8 if parity_hit else -0.2
            score = 0.72 * bm25 + 0.23 * sim + 0.55 * title_hit + intent_boost
            scored.append((score, chunk))
        scored.sort(key=lambda row: row[0], reverse=True)
        selected = self._select_top_chunks(scored=scored, target=max(2, min(top_k, len(scored))))
        sources: list[EvidenceSource] = []
        for chunk in selected:
            snippet = self._build_snippet(chunk.text, q_tokens, width=280)
            source = EvidenceSource(
                source_id=chunk.chunk_id,
                title=chunk.title,
                source_type="local_corpus",
                url=chunk.uri,
                uri=chunk.uri,
                published_at=chunk.published_at,
                timestamp=chunk.published_at,
                snippet=snippet,
                full_text_ref=f"{chunk.uri}#chunk={chunk.chunk_id}",
                credibility_score=self._credibility_heuristic(chunk),
                time_relevance=0.58,
            )
            sources.append(source)
        sources, pack_breakdown = self.credibility_scorer.score_sources(sources)
        credibility_score = float((pack_breakdown.get("aggregate") or {}).get("final_score_mean", 0.5))
        time_relevance = float((pack_breakdown.get("aggregate") or {}).get("hard_score_mean", 0.5))
        return EvidencePack(
            query=query,
            sources=sources,
            key_points=[f"Retrieved {len(sources)} source(s) from local corpus."],
            credibility_score=round(credibility_score, 4),
            time_relevance=round(time_relevance, 4),
            credibility_breakdown=pack_breakdown,
        )

    def _load_docs(self, corpus_dir: Path) -> list[CorpusDocument]:
        docs: list[CorpusDocument] = []
        if not corpus_dir.exists():
            return docs
        files = sorted(list(corpus_dir.glob("**/*.md")) + list(corpus_dir.glob("**/*.txt")))
        for path in files:
            text = path.read_text(encoding="utf-8")
            title = self._title_from_text(path, text)
            published_at = self._published_at(path, text)
            docs.append(
                CorpusDocument(
                    doc_id=path.stem,
                    title=title,
                    uri=str(path.as_posix()),
                    text=text,
                    published_at=published_at,
                )
            )
        return docs

    def _build_chunks(self, docs: list[CorpusDocument]) -> list[CorpusChunk]:
        rows: list[CorpusChunk] = []
        for doc in docs:
            parts = self._split_text_chunks(doc.text, chunk_chars=360)
            for idx, text in enumerate(parts):
                tokens = self._tokenize(text)
                tf: dict[str, int] = {}
                for token in tokens:
                    tf[token] = tf.get(token, 0) + 1
                rows.append(
                    CorpusChunk(
                        chunk_id=f"{doc.doc_id}:{idx + 1}",
                        doc_id=doc.doc_id,
                        title=doc.title,
                        uri=doc.uri,
                        text=text,
                        published_at=doc.published_at,
                        tokens=tokens,
                        tf=tf,
                        length=max(1, len(tokens)),
                    )
                )
        return rows

    def _split_text_chunks(self, text: str, chunk_chars: int = 360) -> list[str]:
        clean = text.replace("\r\n", "\n").strip()
        if not clean:
            return [""]
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", clean) if p.strip()]
        chunks: list[str] = []
        for para in paragraphs:
            if len(para) <= chunk_chars:
                chunks.append(para)
                continue
            start = 0
            step = max(120, int(chunk_chars * 0.6))
            while start < len(para):
                chunks.append(para[start : start + chunk_chars].strip())
                start += step
        return chunks or [clean[:chunk_chars]]

    def _select_top_chunks(self, scored: list[tuple[float, CorpusChunk]], target: int) -> list[CorpusChunk]:
        out: list[CorpusChunk] = []
        seen_chunk: set[str] = set()
        seen_doc: set[str] = set()
        for _, chunk in scored:
            if chunk.chunk_id in seen_chunk:
                continue
            if chunk.doc_id in seen_doc and len(out) < target // 2:
                continue
            out.append(chunk)
            seen_chunk.add(chunk.chunk_id)
            seen_doc.add(chunk.doc_id)
            if len(out) >= target:
                break
        if len(out) < target:
            for _, chunk in scored:
                if chunk.chunk_id in seen_chunk:
                    continue
                out.append(chunk)
                seen_chunk.add(chunk.chunk_id)
                if len(out) >= target:
                    break
        return out

    def _title_from_text(self, path: Path, text: str) -> str:
        for line in text.splitlines():
            raw = line.strip()
            if not raw:
                continue
            return raw.lstrip("#").strip()
        return path.stem

    def _published_at(self, path: Path, text: str) -> datetime:
        match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
        if match:
            return datetime.fromisoformat(f"{match.group(1)}T00:00:00+00:00")
        return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)

    def _tokenize(self, text: str) -> list[str]:
        text = text.lower()
        latin = re.findall(r"[a-z0-9_]+", text)
        cjk_chars = [ch for ch in text if "\u4e00" <= ch <= "\u9fff"]
        cjk_bigrams: list[str] = []
        for idx in range(len(cjk_chars) - 1):
            cjk_bigrams.append(cjk_chars[idx] + cjk_chars[idx + 1])
        return latin + cjk_chars + cjk_bigrams

    def _bm25_score(self, q_tokens: list[str], chunk: CorpusChunk, k1: float = 1.5, b: float = 0.75) -> float:
        if not q_tokens:
            return 0.0
        score = 0.0
        for token in q_tokens:
            tf = chunk.tf.get(token, 0)
            if tf == 0:
                continue
            df = self.df.get(token, 0)
            idf = math.log(1 + (self.doc_count - df + 0.5) / (df + 0.5))
            denom = tf + k1 * (1 - b + b * (chunk.length / self.avg_dl))
            score += idf * ((tf * (k1 + 1)) / max(1e-9, denom))
        return score

    def _embed(self, tokens: list[str], dim: int = 16) -> list[float]:
        vec = [0.0] * dim
        if not tokens:
            return vec
        for token in tokens:
            idx = abs(hash(token)) % dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def _cosine(self, v1: list[float], v2: list[float]) -> float:
        if not v1 or not v2:
            return 0.0
        return sum(a * b for a, b in zip(v1, v2))

    def _build_snippet(self, text: str, q_tokens: list[str], width: int = 280) -> str:
        cleaned = " ".join(text.split())
        if not cleaned:
            return ""
        for token in q_tokens:
            if len(token) < 2:
                continue
            idx = cleaned.lower().find(token.lower())
            if idx >= 0:
                start = max(0, idx - width // 3)
                end = min(len(cleaned), idx + width)
                return cleaned[start:end]
        return cleaned[:width]

    def _credibility_heuristic(self, chunk: CorpusChunk) -> float:
        length_bonus = min(0.2, max(0.0, len(chunk.text) / 1000.0))
        title_bonus = 0.08 if any(token in chunk.title.lower() for token in ["report", "playbook", "summary"]) else 0.0
        return round(min(0.95, 0.55 + length_bonus + title_bonus), 4)


class HybridRetriever(RAGRetriever):
    def __init__(
        self,
        local_retriever: LocalCorpusRetriever,
        news_provider: NewsProviderBase | None = None,
        macro_provider: MacroProviderBase | None = None,
        filings_provider: FilingsProviderBase | None = None,
    ) -> None:
        self.local_retriever = local_retriever
        self.news_provider = news_provider or MockNewsProvider()
        self.macro_provider = macro_provider or MockMacroProvider()
        self.filings_provider = filings_provider
        self.credibility_scorer = EvidenceCredibilityScorer()

    def retrieve_evidence_pack(self, query: str, top_k: int = 5) -> EvidencePack:
        local_target = max(2, min(top_k, max(2, top_k // 2)))
        local_pack = self.local_retriever.retrieve_evidence_pack(query=query, top_k=local_target)
        external_target = max(1, top_k + 2 - len(local_pack.sources))

        external_sources: list[EvidenceSource] = []
        external_sources.extend(
            self._news_to_sources(self.news_provider.search(query=query, limit=external_target))
        )
        external_sources.extend(
            self._macro_to_sources(
                self.macro_provider.search(query=query, limit=max(1, external_target // 2 + 1))
            )
        )
        combined_sources, _ = self.credibility_scorer.score_sources([*local_pack.sources, *external_sources])
        merged = self._rank_hybrid_sources(query, combined_sources, top_k=max(2, top_k))
        merged, pack_breakdown = self.credibility_scorer.score_sources(merged)
        credibility = round(float((pack_breakdown.get("aggregate") or {}).get("final_score_mean", 0.5)), 4)
        time_relevance = round(float((pack_breakdown.get("aggregate") or {}).get("hard_score_mean", 0.5)), 4)
        local_count = len([row for row in merged if not row.source_id.startswith("mock_")])
        ext_count = len(merged) - local_count
        return EvidencePack(
            query=query,
            sources=merged,
            key_points=[
                f"Retrieved {local_count} local corpus source(s).",
                f"Retrieved {ext_count} external mock source(s).",
                "Hybrid retrieval combines local corpus and external adapters.",
            ],
            credibility_score=credibility,
            time_relevance=time_relevance,
            credibility_breakdown=pack_breakdown,
        )

    def _news_to_sources(self, items: list[ExternalNewsItem]) -> list[EvidenceSource]:
        out: list[EvidenceSource] = []
        for item in items:
            source_id = f"mock_news:{item.item_id}"
            out.append(
                EvidenceSource(
                    source_id=source_id,
                    title=f"{item.headline} [{item.source}]",
                    source_type="newswire",
                    url=item.url,
                    uri=item.url,
                    published_at=item.timestamp,
                    timestamp=item.timestamp,
                    snippet=item.summary,
                    full_text_ref=f"{item.url}#mock_news",
                    credibility_score=0.68,
                    time_relevance=self._recency_score(item.timestamp),
                )
            )
        return out

    def _macro_to_sources(self, items: list[ExternalMacroItem]) -> list[EvidenceSource]:
        out: list[EvidenceSource] = []
        for item in items:
            source_id = f"mock_macro:{item.item_id}"
            out.append(
                EvidenceSource(
                    source_id=source_id,
                    title=f"{item.headline} [{item.source}]",
                    source_type="macro_release",
                    url=item.url,
                    uri=item.url,
                    published_at=item.timestamp,
                    timestamp=item.timestamp,
                    snippet=item.summary,
                    full_text_ref=f"{item.url}#mock_macro",
                    credibility_score=0.72,
                    time_relevance=self._recency_score(item.timestamp),
                )
            )
        return out

    def _rank_hybrid_sources(self, query: str, sources: list[EvidenceSource], top_k: int) -> list[EvidenceSource]:
        q_tokens = set(_hybrid_tokenize(query))
        dedup: dict[str, EvidenceSource] = {}
        for source in sources:
            dedup[source.source_id] = source
        rows = list(dedup.values())
        scored: list[tuple[float, float, EvidenceSource]] = []
        for source in rows:
            hay = f"{source.title} {source.snippet}".lower()
            overlap = sum(1 for token in q_tokens if token and token in hay)
            source_type_boost = 0.35 if source.source_id.startswith("mock_") else 0.2
            score = overlap * 0.45 + source.credibility_score * 0.35 + source.time_relevance * 0.2 + source_type_boost
            scored.append((score, self._ts_score(source), source))
        scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
        selected = [row[2] for row in scored[: max(2, top_k)]]
        if not any(source.source_id.startswith("mock_") for source in selected):
            mock_rows = [row[2] for row in scored if row[2].source_id.startswith("mock_")]
            if mock_rows:
                selected[-1] = mock_rows[0]
        return selected

    def _ts_score(self, source: EvidenceSource) -> float:
        ts = source.timestamp or source.published_at
        if ts is None:
            return 0.0
        try:
            return float(ts.timestamp())
        except (OverflowError, OSError, ValueError):
            return 0.0

    def _recency_score(self, ts: datetime) -> float:
        now = datetime.now(UTC)
        age_days = max(0.0, (now - ts).total_seconds() / 86400.0)
        return round(max(0.35, 1.0 / (1.0 + age_days / 3.5)), 4)


class WebRetriever(RAGRetriever):
    def retrieve_evidence_pack(self, query: str, top_k: int = 5) -> EvidencePack:
        return EvidencePack(
            query=query,
            sources=[],
            key_points=["WebRetriever is optional and not enabled in this PR."],
            credibility_score=0.0,
            time_relevance=0.0,
            credibility_breakdown={
                "scoring_version": "credibility_v2",
                "source_level": [],
                "aggregate": {"source_count": 0, "final_score_mean": 0.0},
            },
        )


def _hybrid_tokenize(text: str) -> list[str]:
    low = text.lower()
    latin = re.findall(r"[a-z0-9_]+", low)
    cjk_chars = [ch for ch in low if "\u4e00" <= ch <= "\u9fff"]
    cjk_bigrams: list[str] = []
    for idx in range(len(cjk_chars) - 1):
        cjk_bigrams.append(cjk_chars[idx] + cjk_chars[idx + 1])
    return latin + cjk_chars + cjk_bigrams
