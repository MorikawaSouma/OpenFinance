import hashlib
import json
import re
import time
from typing import Any

from pydantic import BaseModel, Field

from openfinance.knowledge.evidence import EvidencePack
from openfinance.llm.provider import LLMProvider, LLMProviderRegistry, LLMResponse, ZhipuGLM47Provider


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _looks_like_query_echo(title: str, query: str) -> bool:
    norm_title = _normalize_text(title)
    norm_query = _normalize_text(query)
    if not norm_title or not norm_query:
        return False
    if norm_title == norm_query:
        return True
    if len(norm_query) >= 8 and norm_query in norm_title:
        return True
    if len(norm_title) >= 8 and norm_title in norm_query:
        return True
    return False


def _source_timestamp_text(raw: Any) -> str:
    if hasattr(raw, "isoformat"):
        return str(raw.isoformat())
    text = str(raw or "").strip()
    return text or "n/a"


def _first_json_object(text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except (TypeError, ValueError):
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        try:
            parsed = json.loads(fenced.group(1))
            if isinstance(parsed, dict):
                return parsed
        except ValueError:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        return None


def _dedupe_lines(lines: list[str], max_count: int) -> list[str]:
    out: list[str] = []
    seen = set()
    for row in lines:
        text = re.sub(r"\s+", " ", str(row)).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= max_count:
            break
    return out


def _extract_indices(value: object) -> list[int]:
    out: list[int] = []
    if isinstance(value, int):
        return [value]
    if isinstance(value, list):
        for row in value:
            if isinstance(row, int):
                out.append(row)
            elif isinstance(row, str) and row.strip().isdigit():
                out.append(int(row.strip()))
            elif isinstance(row, dict):
                nested = row.get("index") or row.get("id") or row.get("citation")
                out.extend(_extract_indices(nested))
    elif isinstance(value, str):
        out.extend(int(m.group(1)) for m in re.finditer(r"\[(\d+)\]", value))
    uniq: list[int] = []
    seen = set()
    for n in out:
        if n in seen:
            continue
        seen.add(n)
        uniq.append(n)
    return uniq


def _append_citation_marks(text: str, indices: list[int]) -> str:
    if not text.strip() or not indices:
        return text.strip()
    if re.search(r"\[\d+\]", text):
        return text.strip()
    marks = "".join(f"[{idx}]" for idx in indices)
    return f"{text.strip()} {marks}"


class GeneralInfoCitation(BaseModel):
    source_id: str
    title: str
    source: str
    timestamp: str
    snippet: str


class GeneralInfoAnswerPayload(BaseModel):
    summary: list[str] = Field(default_factory=list)
    drivers: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    what_to_watch: list[str] = Field(default_factory=list)
    citations: list[GeneralInfoCitation] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class GeneralInfoLLMCall(BaseModel):
    provider: str
    model: str
    mode: str
    prompt_hash: str
    latency_ms: int
    token_usage: dict[str, int] = Field(default_factory=dict)


class GeneralInfoAnswerResult(BaseModel):
    answer: GeneralInfoAnswerPayload
    llm_call: GeneralInfoLLMCall
    raw_output: str = ""
    insufficient_evidence: bool = False


class GeneralInfoAnswerer:
    def __init__(self, llm_provider: LLMProvider | None = None) -> None:
        if llm_provider is not None:
            self._provider = llm_provider
        else:
            registry = LLMProviderRegistry()
            registry.register(ZhipuGLM47Provider(), is_default=True)
            self._provider = registry.get()

    @property
    def provider(self) -> LLMProvider:
        return self._provider

    def answer(
        self,
        *,
        question: str,
        market: str,
        response_language: str,
        evidence_pack: EvidencePack,
    ) -> GeneralInfoAnswerResult:
        citations = self._citation_candidates(question=question, evidence_pack=evidence_pack, max_count=8)
        insufficient = len(citations) < 2
        prompt = self._build_prompt(
            question=question,
            market=market,
            response_language=response_language,
            citations=citations,
            insufficient_evidence=insufficient,
        )
        prompt_hash = hashlib.sha1(prompt.encode("utf-8")).hexdigest()
        started = time.perf_counter()
        llm_resp = self._provider.complete(prompt, max_tokens=920, temperature=0.1)
        latency_ms = int((time.perf_counter() - started) * 1000)
        answer_payload = self._coerce_answer_payload(
            llm_resp=llm_resp,
            response_language=response_language,
            citations=citations,
            insufficient_evidence=insufficient,
        )
        call = GeneralInfoLLMCall(
            provider=str(getattr(self._provider, "name", "unknown")),
            model=llm_resp.model,
            mode=llm_resp.mode,
            prompt_hash=prompt_hash,
            latency_ms=max(latency_ms, 0),
            token_usage={
                "prompt_tokens": int((llm_resp.usage or {}).get("prompt_tokens", 0)),
                "completion_tokens": int((llm_resp.usage or {}).get("completion_tokens", 0)),
            },
        )
        return GeneralInfoAnswerResult(
            answer=answer_payload,
            llm_call=call,
            raw_output=llm_resp.content,
            insufficient_evidence=insufficient,
        )

    def _citation_candidates(self, *, question: str, evidence_pack: EvidencePack, max_count: int) -> list[GeneralInfoCitation]:
        rows: list[GeneralInfoCitation] = []
        seen = set()
        for source in evidence_pack.sources:
            title = str(source.title or "").strip()
            if not title:
                continue
            if _looks_like_query_echo(title, question):
                continue
            key = f"{title}|{_source_timestamp_text(source.timestamp or source.published_at)}"
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                GeneralInfoCitation(
                    source_id=str(source.source_id or ""),
                    title=title,
                    source=str(source.source_type or "unknown"),
                    timestamp=_source_timestamp_text(source.timestamp or source.published_at),
                    snippet=re.sub(r"\s+", " ", str(source.snippet or "").strip())[:260],
                )
            )
            if len(rows) >= max_count:
                break
        if rows:
            while len(rows) < 2:
                rows.append(
                    GeneralInfoCitation(
                        source_id=f"system_fallback_{len(rows) + 1}",
                        title="Limited evidence coverage",
                        source="system",
                        timestamp="n/a",
                        snippet="Evidence retrieval returned fewer than two display-ready sources.",
                    )
                )
            return rows
        for source in evidence_pack.sources[:2]:
            rows.append(
                GeneralInfoCitation(
                    source_id=str(source.source_id or ""),
                    title=str(source.title or "Untitled source"),
                    source=str(source.source_type or "unknown"),
                    timestamp=_source_timestamp_text(source.timestamp or source.published_at),
                    snippet=re.sub(r"\s+", " ", str(source.snippet or "").strip())[:260],
                )
            )
        while len(rows) < 2:
            rows.append(
                GeneralInfoCitation(
                    source_id=f"system_fallback_{len(rows) + 1}",
                    title="Limited evidence coverage",
                    source="system",
                    timestamp="n/a",
                    snippet="Evidence retrieval returned fewer than two display-ready sources.",
                )
            )
        return rows

    def _build_prompt(
        self,
        *,
        question: str,
        market: str,
        response_language: str,
        citations: list[GeneralInfoCitation],
        insufficient_evidence: bool,
    ) -> str:
        language_hint = "Chinese" if response_language == "zh" else "English"
        citation_rows = []
        for idx, cite in enumerate(citations, start=1):
            citation_rows.append(
                f"[{idx}] title={cite.title}\n"
                f"    source={cite.source}\n"
                f"    timestamp={cite.timestamp}\n"
                f"    source_id={cite.source_id}\n"
                f"    snippet={cite.snippet}"
            )
        evidence_block = "\n".join(citation_rows) if citation_rows else "[none]"
        insufficient_hint = (
            "Evidence is insufficient (<2 items). You must explicitly say confidence is low and recommend refresh evidence / expand time window."
            if insufficient_evidence
            else "Evidence is sufficient for a concise market overview."
        )
        return (
            "You are OpenFinance General Info Answerer.\n"
            f"User question: {question}\n"
            f"Market context: {market}\n"
            f"Output language: {language_hint}\n"
            f"{insufficient_hint}\n"
            "Task requirements:\n"
            "- Synthesize across multiple evidence rows.\n"
            "- Deduplicate repeated facts and avoid echoing the user query wording.\n"
            "- Do not invent facts not grounded in evidence; mark uncertainty when needed.\n"
            "- Each bullet should include citation indices like [1][2] whenever possible.\n"
            "- Return strict JSON only.\n"
            "JSON schema:\n"
            "{\n"
            '  "summary": [{"point":"...", "citations":[1,2]}],\n'
            '  "drivers": [{"point":"...", "citations":[1]}],\n'
            '  "risks": [{"point":"...", "citations":[2]}],\n'
            '  "what_to_watch": [{"point":"...", "citations":[1,3]}],\n'
            '  "citations": [1,2,3],\n'
            '  "confidence": 0.0\n'
            "}\n"
            "Constraints:\n"
            "- summary has 3-6 bullets\n"
            "- drivers/risks/what_to_watch each has 2-4 bullets\n"
            "- citations length >= 2 when evidence allows\n"
            f"Evidence rows:\n{evidence_block}"
        )

    def _coerce_answer_payload(
        self,
        *,
        llm_resp: LLMResponse,
        response_language: str,
        citations: list[GeneralInfoCitation],
        insufficient_evidence: bool,
    ) -> GeneralInfoAnswerPayload:
        parsed = _first_json_object(llm_resp.content or "")
        if not isinstance(parsed, dict):
            return self._fallback_payload(
                response_language=response_language,
                citations=citations,
                insufficient_evidence=insufficient_evidence,
            )
        summary = self._coerce_section(parsed.get("summary"), min_count=3, max_count=6)
        drivers = self._coerce_section(parsed.get("drivers"), min_count=2, max_count=4)
        risks = self._coerce_section(parsed.get("risks"), min_count=2, max_count=4)
        watch = self._coerce_section(parsed.get("what_to_watch"), min_count=2, max_count=4)
        requested_indices = _extract_indices(parsed.get("citations"))
        selected_citations = self._select_citations(citations, requested_indices)
        if len(selected_citations) < 2:
            selected_citations = self._select_citations(citations, [1, 2])

        summary = self._ensure_count(
            summary,
            min_count=3,
            max_count=6,
            fallback=self._fallback_summary(response_language, selected_citations, insufficient_evidence),
        )
        drivers = self._ensure_count(
            drivers,
            min_count=2,
            max_count=4,
            fallback=self._fallback_drivers(response_language, selected_citations),
        )
        risks = self._ensure_count(
            risks,
            min_count=2,
            max_count=4,
            fallback=self._fallback_risks(response_language, selected_citations),
        )
        watch = self._ensure_count(
            watch,
            min_count=2,
            max_count=4,
            fallback=self._fallback_watch(response_language, selected_citations, insufficient_evidence),
        )
        confidence = parsed.get("confidence")
        if not isinstance(confidence, (int, float)):
            confidence = 0.42 if insufficient_evidence else 0.68
        confidence = max(0.0, min(1.0, float(confidence)))
        return GeneralInfoAnswerPayload(
            summary=summary,
            drivers=drivers,
            risks=risks,
            what_to_watch=watch,
            citations=selected_citations[:6],
            confidence=confidence,
        )

    def _coerce_section(self, value: object, *, min_count: int, max_count: int) -> list[str]:
        rows: list[str] = []
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    rows.append(item.strip())
                elif isinstance(item, dict):
                    point = str(item.get("point") or item.get("text") or "").strip()
                    point = _append_citation_marks(point, _extract_indices(item.get("citations")))
                    rows.append(point)
        rows = _dedupe_lines(rows, max_count=max_count)
        if len(rows) < min_count:
            return rows
        return rows[:max_count]

    def _select_citations(self, candidates: list[GeneralInfoCitation], indices: list[int]) -> list[GeneralInfoCitation]:
        out: list[GeneralInfoCitation] = []
        seen = set()
        for idx in indices:
            if idx <= 0 or idx > len(candidates):
                continue
            cite = candidates[idx - 1]
            key = f"{cite.source_id}|{cite.title}|{cite.timestamp}"
            if key in seen:
                continue
            seen.add(key)
            out.append(cite)
        for cite in candidates:
            if len(out) >= 6:
                break
            key = f"{cite.source_id}|{cite.title}|{cite.timestamp}"
            if key in seen:
                continue
            seen.add(key)
            out.append(cite)
        return out

    def _ensure_count(self, rows: list[str], *, min_count: int, max_count: int, fallback: list[str]) -> list[str]:
        out = list(rows[:max_count])
        if len(out) >= min_count:
            return out
        for line in fallback:
            if len(out) >= max_count:
                break
            norm = _normalize_text(line)
            if any(_normalize_text(existing) == norm for existing in out):
                continue
            out.append(line)
        return out[:max_count]

    def _fallback_payload(
        self,
        *,
        response_language: str,
        citations: list[GeneralInfoCitation],
        insufficient_evidence: bool,
    ) -> GeneralInfoAnswerPayload:
        selected = self._select_citations(citations, [1, 2])
        return GeneralInfoAnswerPayload(
            summary=self._fallback_summary(response_language, selected, insufficient_evidence),
            drivers=self._fallback_drivers(response_language, selected),
            risks=self._fallback_risks(response_language, selected),
            what_to_watch=self._fallback_watch(response_language, selected, insufficient_evidence),
            citations=selected[:6],
            confidence=0.36 if insufficient_evidence else 0.62,
        )

    def _fallback_summary(
        self,
        language: str,
        citations: list[GeneralInfoCitation],
        insufficient_evidence: bool,
    ) -> list[str]:
        if language == "zh":
            rows = [
                "市场近期处于流动性与风险偏好再定价阶段，短期波动仍偏高 [1][2]。",
                "证据显示估值、盈利与利率预期的错配正在驱动板块轮动 [1][2]。",
                "当前更适合以防守型仓位管理为主，并持续跟踪波动收敛信号 [1][2]。",
            ]
            if insufficient_evidence:
                rows.insert(0, "当前可用证据不足（<2 条），结论置信度偏低，建议刷新证据或扩大时间窗口。")
            return rows
        rows_en = [
            "Markets remain in a liquidity and risk-appetite repricing phase, with elevated short-term volatility [1][2].",
            "Evidence points to valuation/earnings/rate-expectation mismatch as a key rotation driver [1][2].",
            "A defensive posture is preferred until volatility and revisions stabilize [1][2].",
        ]
        if insufficient_evidence:
            rows_en.insert(0, "Available evidence is limited (<2 items); confidence is low. Refresh evidence or expand time window.")
        return rows_en

    def _fallback_drivers(self, language: str, citations: list[GeneralInfoCitation]) -> list[str]:
        if language == "zh":
            return [
                "政策路径预期与实际流动性条件之间的偏差，推动资产再定价 [1][2]。",
                "盈利预期分化叠加行业拥挤交易，放大了横截面波动 [1][2]。",
            ]
        return [
            "Policy-path expectations versus realized liquidity conditions are driving repricing [1][2].",
            "Earnings dispersion and crowded positioning are amplifying cross-sectional volatility [1][2].",
        ]

    def _fallback_risks(self, language: str, citations: list[GeneralInfoCitation]) -> list[str]:
        if language == "zh":
            return [
                "若宏观数据与政策沟通再次错位，波动率可能二次抬升 [1][2]。",
                "执行成本与成交拥挤可能侵蚀策略收益并放大回撤 [1][2]。",
            ]
        return [
            "A renewed macro-policy mismatch can re-accelerate volatility [1][2].",
            "Execution-cost drag and crowding can erode returns and deepen drawdowns [1][2].",
        ]

    def _fallback_watch(self, language: str, citations: list[GeneralInfoCitation], insufficient_evidence: bool) -> list[str]:
        if language == "zh":
            rows = [
                "关注通胀、就业与增长数据是否与政策路径重新对齐 [1][2]。",
                "跟踪波动率期限结构与盈利预期修正的同步方向 [1][2]。",
            ]
            if insufficient_evidence:
                rows.append("建议执行“刷新证据”并将时间范围扩展到近 30-90 天。")
            return rows
        rows_en = [
            "Track whether inflation/labor/growth prints realign with policy path [1][2].",
            "Monitor volatility term-structure and earnings-revision breadth for confirmation [1][2].",
        ]
        if insufficient_evidence:
            rows_en.append("Refresh evidence and widen lookback to the recent 30-90 days.")
        return rows_en
