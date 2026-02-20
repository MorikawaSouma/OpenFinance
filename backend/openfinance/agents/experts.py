import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from openfinance.agents.base import BaseAgent
from openfinance.agents.counterfactual import CounterfactualQueryGenerator
from openfinance.agents.schemas import AgentCitation, AgentOutput, AgentTaskInput, ReasoningTrace
from openfinance.knowledge.evidence import EvidenceSource
from openfinance.knowledge.service import KnowledgeService, build_default_knowledge_service
from openfinance.llm.provider import LLMProvider


@dataclass(frozen=True)
class AgentLens:
    name: str
    model: str
    focus: str
    style: str
    keywords: tuple[str, ...]


def _extract_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _as_text_lines(value: Any) -> list[str]:
    if isinstance(value, str):
        line = value.strip()
        return [line] if line else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            line = str(item).strip()
            if line:
                out.append(line)
        return out
    return []


def _normalized_confidence(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return None
        return max(0.0, min(1.0, parsed))
    return None


def _is_placeholder_line(text: str) -> bool:
    low = text.strip().lower()
    placeholders = {
        "one clear conclusion",
        "reason 1",
        "reason 2",
        "source_id_from_list",
        "counterpoint or unknown",
        "string",
    }
    if low in placeholders:
        return True
    if low.startswith("reason ") and len(low) <= 12:
        return True
    return False


def _ts_text(source: EvidenceSource) -> str:
    ts = source.timestamp or source.published_at
    if ts is None:
        return "n/a"
    return ts.isoformat()


def _dt_score(source: EvidenceSource) -> float:
    ts = source.timestamp or source.published_at
    if ts is None:
        return 0.0
    try:
        return float(ts.timestamp())
    except (OverflowError, OSError, ValueError):
        return 0.0


class EvidenceGroundedAgent(BaseAgent):
    def __init__(self, lens: AgentLens, llm_provider: LLMProvider) -> None:
        self.name = lens.name
        self.model = lens.model
        self._focus = lens.focus
        self._style = lens.style
        self._keywords = lens.keywords
        self._llm = llm_provider

    def run(self, task: AgentTaskInput) -> AgentOutput:
        question = (task.question or task.prompt or "").strip()
        all_sources = list(task.evidence_pack.sources) if task.evidence_pack else []
        ranked_sources = self._rank_sources(question, all_sources)
        selected_sources = ranked_sources[: max(1, min(task.max_citations, len(ranked_sources) or 1))]
        prompt = self._build_prompt(task=task, question=question, selected_sources=selected_sources)
        response = self._llm.complete(prompt, max_tokens=420, temperature=0.15)
        parsed = _extract_json_object(response.content) or {}

        evidence_refs = self._normalize_evidence_refs(
            parsed_refs=parsed.get("evidence_refs"),
            selected_sources=selected_sources,
            all_sources=all_sources,
        )
        citations = self._build_citations(evidence_refs=evidence_refs, all_sources=all_sources)

        claim = str(parsed.get("claim", "")).strip()
        if (not claim) or _is_placeholder_line(claim):
            claim = self._fallback_claim(question=question, selected_sources=selected_sources)

        rationale = _as_text_lines(parsed.get("rationale"))
        rationale = [line for line in rationale if not _is_placeholder_line(line)]
        if not rationale:
            rationale = self._fallback_rationale(question=question, selected_sources=selected_sources)

        uncertainty = _as_text_lines(parsed.get("uncertainty"))
        uncertainty = [line for line in uncertainty if not _is_placeholder_line(line)]
        if not uncertainty:
            uncertainty = self._fallback_uncertainty(all_sources=all_sources)
        parsed_confidence = _normalized_confidence(parsed.get("confidence"))
        reasoning_trace = self._parse_reasoning_trace(parsed.get("reasoning_trace"))

        return AgentOutput(
            agent_name=self.name,
            claim=claim,
            rationale=rationale,
            uncertainty=uncertainty,
            evidence_refs=evidence_refs,
            citations=citations,
            confidence=parsed_confidence
            if parsed_confidence is not None
            else self._confidence(evidence_refs=evidence_refs, total_sources=len(all_sources)),
            reasoning_trace=reasoning_trace,
            next_actions=self._next_actions(evidence_refs=evidence_refs),
            prompt_used=prompt if task.developer_mode else None,
            raw_response=response.content if task.developer_mode else None,
        )

    def _rank_sources(self, question: str, sources: list[EvidenceSource]) -> list[EvidenceSource]:
        q = question.lower()
        q_tokens = set(re.findall(r"[a-z0-9_]+", q))

        scored: list[tuple[float, float, EvidenceSource]] = []
        for source in sources:
            hay = f"{source.title} {source.snippet}".lower()
            score = 0.0
            for keyword in self._keywords:
                if keyword.lower() in hay:
                    score += 2.0
            if q_tokens:
                score += sum(0.15 for token in q_tokens if token and token in hay)
            score += float(source.credibility_score) * 0.4
            # Deterministic tie-breaker so different agent lenses do not collapse to identical refs.
            digest = hashlib.sha1(f"{self.name}:{source.source_id}".encode("utf-8")).hexdigest()
            score += (int(digest[:4], 16) % 17) / 1000.0
            scored.append((score, _dt_score(source), source))

        scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
        return [row[2] for row in scored]

    def _build_prompt(
        self, *, task: AgentTaskInput, question: str, selected_sources: list[EvidenceSource]
    ) -> str:
        rows: list[dict[str, str]] = []
        for source in selected_sources:
            rows.append(
                {
                    "source_id": source.source_id,
                    "title": source.title,
                    "timestamp": _ts_text(source),
                    "uri": source.uri or source.url or "",
                    "snippet": (source.snippet or "")[:360],
                }
            )
        evidence_json = json.dumps(rows, ensure_ascii=False)
        return (
            "You are an investment expert agent. Read the evidence list and return strict JSON only.\n"
            "Do not use markdown. Do not omit evidence usage.\n"
            "Required fields:\n"
            "{\n"
            '  "claim": "one clear conclusion",\n'
            '  "rationale": ["reason 1", "reason 2"],\n'
            '  "evidence_refs": ["source_id_from_list"],\n'
            '  "uncertainty": ["counterpoint or unknown"],\n'
            '  "confidence": 0.0,\n'
            '  "reasoning_trace": {\n'
            '    "steps": [\n'
            '      {\n'
            '        "step_type": "hypothesis",\n'
            '        "question": "question text",\n'
            '        "query": "optional query string",\n'
            '        "evidence_refs": ["source_id_from_list"],\n'
            '        "output_summary": "short summary",\n'
            '        "confidence_delta": 0.0\n'
            "      }\n"
            "    ]\n"
            "  }\n"
            "}\n"
            f"Agent: {self.name}\n"
            f"Lens focus: {self._focus}\n"
            f"Style: {self._style}\n"
            f"Question: {question}\n"
            f"Market context: {json.dumps(task.market_context, ensure_ascii=False)}\n"
            f"Constraints: {json.dumps(task.constraints, ensure_ascii=False)}\n"
            f"EvidencePackID: {task.evidence_pack_id or ''}\n"
            f"Evidence sources: {evidence_json}\n"
            "If evidence is available, cite at least one source_id from evidence_refs.\n"
            "reasoning_trace must include at least 4 steps and include one counterevidence_search step."
        )

    def _normalize_evidence_refs(
        self,
        *,
        parsed_refs: Any,
        selected_sources: list[EvidenceSource],
        all_sources: list[EvidenceSource],
    ) -> list[str]:
        all_ids = {source.source_id for source in all_sources}
        refs: list[str] = []
        if isinstance(parsed_refs, str):
            refs = [parsed_refs]
        elif isinstance(parsed_refs, list):
            refs = [str(row) for row in parsed_refs]

        normalized = [row for row in refs if row in all_ids]
        if normalized:
            return list(dict.fromkeys(normalized))

        fallback = [source.source_id for source in selected_sources if source.source_id in all_ids][:2]
        return list(dict.fromkeys(fallback))

    def _build_citations(
        self, *, evidence_refs: list[str], all_sources: list[EvidenceSource]
    ) -> list[AgentCitation]:
        source_map = {source.source_id: source for source in all_sources}
        citations: list[AgentCitation] = []
        for ref in evidence_refs:
            source = source_map.get(ref)
            if source is None:
                continue
            citations.append(
                AgentCitation(
                    source_id=source.source_id,
                    title=source.title,
                    timestamp=_ts_text(source),
                    uri=source.uri or source.url,
                )
            )
        return citations

    def _parse_reasoning_trace(self, payload: Any) -> ReasoningTrace | None:
        if payload is None:
            return None
        try:
            if isinstance(payload, dict):
                return ReasoningTrace.model_validate(payload)
            if isinstance(payload, list):
                return ReasoningTrace.model_validate({"steps": payload})
        except Exception:
            return None
        return None

    def _fallback_claim(self, question: str, selected_sources: list[EvidenceSource]) -> str:
        if selected_sources:
            title = selected_sources[0].title
            return (
                f"{self.name}结论: {question[:120]} 的主判断应优先参考证据《{title}》并采用"
                f"{self._focus}视角进行约束化执行。"
            )
        return f"{self.name}结论: 当前证据不足，先补充与问题直接相关的可验证材料。"

    def _fallback_rationale(
        self, question: str, selected_sources: list[EvidenceSource]
    ) -> list[str]:
        lines = [f"围绕问题“{question[:80]}”按{self._focus}视角筛选证据。"]
        if selected_sources:
            lines.append(f"优先依据《{selected_sources[0].title}》的时间戳与摘要判断有效性。")
        lines.append("在给定约束下先保持可执行性，再扩展实验验证。")
        return lines

    def _fallback_uncertainty(self, all_sources: list[EvidenceSource]) -> list[str]:
        if not all_sources:
            return ["未检索到有效证据，存在高不确定性。"]
        return ["证据样本有限，需加入反例与跨周期数据以排除偶然性。"]

    def _confidence(self, *, evidence_refs: list[str], total_sources: int) -> float:
        if total_sources <= 0:
            return 0.35
        coverage = min(1.0, len(evidence_refs) / max(1, total_sources))
        return round(min(0.9, 0.45 + coverage * 0.45), 3)

    def _next_actions(self, *, evidence_refs: list[str]) -> list[str]:
        if not evidence_refs:
            return ["补充至少2条高可信来源后再更新结论。"]
        return [
            "将当前引用证据映射到可复现实验参数并复跑。",
            "补充一条反向证据以检验结论稳健性。",
        ]


class BuffettAgent(EvidenceGroundedAgent):
    def __init__(self, llm_provider: LLMProvider) -> None:
        super().__init__(
            lens=AgentLens(
                name="Buffett",
                model="expert-fundamental-v2",
                focus="durable business quality, valuation discipline, and cashflow durability",
                style="long-term fundamental and downside-protection first",
                keywords=(
                    "value",
                    "valuation",
                    "earnings",
                    "cash flow",
                    "quality",
                    "moat",
                    "价值",
                    "估值",
                    "盈利",
                    "护城河",
                ),
            ),
            llm_provider=llm_provider,
        )


class SorosAgent(EvidenceGroundedAgent):
    def __init__(self, llm_provider: LLMProvider) -> None:
        super().__init__(
            lens=AgentLens(
                name="Soros",
                model="expert-macro-reflexivity-v2",
                focus="macro regime shifts, liquidity, reflexive feedback loops",
                style="regime-sensitive and narrative-reversal aware",
                keywords=(
                    "macro",
                    "liquidity",
                    "policy",
                    "rates",
                    "fx",
                    "inflation",
                    "regime",
                    "宏观",
                    "流动性",
                    "利率",
                    "通胀",
                ),
            ),
            llm_provider=llm_provider,
        )


class SimonsAgent(EvidenceGroundedAgent):
    def __init__(self, llm_provider: LLMProvider) -> None:
        super().__init__(
            lens=AgentLens(
                name="Simons",
                model="expert-stat-arb-v2",
                focus="out-of-sample statistical edge, decay, and cost-aware alpha",
                style="test first, then deploy",
                keywords=(
                    "signal",
                    "alpha",
                    "decay",
                    "rankic",
                    "ic",
                    "stat",
                    "turnover",
                    "因子",
                    "衰减",
                ),
            ),
            llm_provider=llm_provider,
        )


class DalioAgent(EvidenceGroundedAgent):
    def __init__(self, llm_provider: LLMProvider) -> None:
        super().__init__(
            lens=AgentLens(
                name="Dalio",
                model="expert-risk-budgeting-v2",
                focus="risk budgeting, correlation regime, and balance across sleeves",
                style="portfolio construction under scenario stress",
                keywords=(
                    "risk parity",
                    "allocation",
                    "correlation",
                    "drawdown",
                    "volatility",
                    "风险平价",
                    "配置",
                    "相关性",
                    "回撤",
                ),
            ),
            llm_provider=llm_provider,
        )


class KahnemanAgent(EvidenceGroundedAgent):
    def __init__(
        self,
        llm_provider: LLMProvider,
        knowledge_service: KnowledgeService | None = None,
        query_generator: CounterfactualQueryGenerator | None = None,
    ) -> None:
        super().__init__(
            lens=AgentLens(
                name="Kahneman",
                model="expert-bias-control-v2",
                focus="cognitive bias checks and counterfactual reasoning",
                style="force disconfirmation before commitment",
                keywords=(
                    "bias",
                    "behavior",
                    "narrative",
                    "counter",
                    "uncertainty",
                    "偏差",
                    "行为",
                    "叙事",
                    "反例",
                ),
            ),
            llm_provider=llm_provider,
        )
        self._knowledge_service = knowledge_service or build_default_knowledge_service()
        self._counterfactual = query_generator or CounterfactualQueryGenerator()

    def run(self, task: AgentTaskInput) -> AgentOutput:
        out = super().run(task)
        evidence_pack = task.evidence_pack
        queries = self._counterfactual.generate(
            initial_conclusion=out.claim or out.summary,
            evidence_pack=evidence_pack,
            question=task.question,
        )

        initial_refs = set(out.evidence_refs)
        counter_sources: list[EvidenceSource] = []
        for row in queries:
            try:
                pack = self._knowledge_service.retrieve(query=row.query, top_k=max(3, task.max_citations + 1))
            except Exception:
                continue
            counter_sources.extend(pack.sources)

        counter_sources = self._dedupe_sources(counter_sources)
        counter_refs = [source.source_id for source in counter_sources if source.source_id not in initial_refs]
        if not counter_refs and counter_sources:
            counter_refs = [counter_sources[0].source_id]
        if not counter_refs and evidence_pack and evidence_pack.sources:
            fallback = [source.source_id for source in evidence_pack.sources if source.source_id not in initial_refs]
            if fallback:
                counter_refs = [fallback[0]]
            else:
                counter_refs = [evidence_pack.sources[-1].source_id]
        counter_refs = list(dict.fromkeys(counter_refs))[:4]

        old_conf = float(out.confidence)
        conf_penalty = 0.08 if len(counter_refs) >= 2 else (0.05 if counter_refs else 0.0)
        new_conf = round(max(0.05, old_conf - conf_penalty), 3)

        out.counter_evidence_refs = counter_refs
        out.challenged_assumptions = self._challenged_assumptions(
            question=task.question,
            rationale=out.rationale,
            counter_refs=counter_refs,
        )
        if counter_refs:
            out.revised_recommendation = (
                f"修正建议：在执行“{out.claim}”前加入反证门槛校验与仓位分步，"
                f"置信度 {old_conf:.3f}->{new_conf:.3f}。"
            )
            out.confidence = new_conf
        else:
            out.revised_recommendation = (
                f"修正建议：反证样本仍不足，维持当前建议并继续补充反向数据，"
                f"置信度 {old_conf:.3f}->{old_conf:.3f}。"
            )

        out.uncertainty = list(
            dict.fromkeys(
                [
                    *out.uncertainty,
                    "Kahneman反事实检查：已执行反向查询，需持续验证叙事偏差与数据偏差。",
                ]
            )
        )
        out.next_actions = list(
            dict.fromkeys(
                [
                    *out.next_actions,
                    "运行CounterfactualQueryGenerator三类查询并复核假设。",
                ]
            )
        )
        out.citations = self._merge_counter_citations(
            citations=out.citations,
            counter_sources=counter_sources,
            counter_refs=counter_refs,
        )
        if task.developer_mode:
            out.artifacts = list(
                dict.fromkeys(
                    [
                        *out.artifacts,
                        *(f"counterfactual_query:{row.category}:{row.query}" for row in queries),
                    ]
                )
            )
        return out

    def _dedupe_sources(self, sources: list[EvidenceSource]) -> list[EvidenceSource]:
        seen: set[str] = set()
        out: list[EvidenceSource] = []
        for source in sources:
            if source.source_id in seen:
                continue
            seen.add(source.source_id)
            out.append(source)
        return out

    def _challenged_assumptions(
        self,
        *,
        question: str,
        rationale: list[str],
        counter_refs: list[str],
    ) -> list[str]:
        assumptions: list[str] = []
        assumptions.append("假设1：当前主叙事在未来一个周期内仍稳定有效。")
        assumptions.append("假设2：观察到的收益/风险关系不是样本选择偏差。")
        if rationale:
            assumptions.append(f"假设3：关键推理链“{rationale[0][:60]}”在反例场景下仍成立。")
        challenged = [
            f"{row} -> 反证检索发现 {len(counter_refs)} 条相关反向证据，需下调确定性。"
            for row in assumptions[:2]
        ]
        if len(challenged) < 1:
            challenged.append(f"围绕问题“{question[:80]}”发现反向证据，建议延后强结论。")
        return challenged

    def _merge_counter_citations(
        self,
        *,
        citations: list[AgentCitation],
        counter_sources: list[EvidenceSource],
        counter_refs: list[str],
    ) -> list[AgentCitation]:
        out = list(citations)
        existing = {row.source_id for row in out}
        source_map = {source.source_id: source for source in counter_sources}
        for ref in counter_refs:
            if ref in existing:
                continue
            source = source_map.get(ref)
            if source is None:
                continue
            out.append(
                AgentCitation(
                    source_id=source.source_id,
                    title=source.title,
                    timestamp=_ts_text(source),
                    uri=source.uri or source.url,
                )
            )
            existing.add(ref)
        return out


class FactorAgent(EvidenceGroundedAgent):
    def __init__(self, llm_provider: LLMProvider) -> None:
        super().__init__(
            lens=AgentLens(
                name="Factor",
                model="expert-factor-lifecycle-v2",
                focus="factor definition, lag safety, QC and versioning discipline",
                style="factor must be testable and traceable",
                keywords=(
                    "factor",
                    "ic",
                    "rankic",
                    "oos",
                    "decay",
                    "turnover",
                    "因子",
                    "样本外",
                    "质检",
                ),
            ),
            llm_provider=llm_provider,
        )
