from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from openfinance.agents.base import BaseAgent
from openfinance.agents.schemas import AgentOutput, AgentTaskInput, ReasoningStep, ReasoningTrace
from openfinance.core.audit import AuditLogEntry, FileAuditStore
from openfinance.knowledge.evidence import EvidencePack, EvidenceSource
from openfinance.knowledge.service import KnowledgeService
from openfinance.tools.registry import ToolRegistry


class OrchestratorRequest(BaseModel):
    prompt: str | None = None
    question: str | None = None
    active_agents: list[str] = Field(default_factory=lambda: ["Strategy", "RiskManager"])
    tool_calls: list[str] = Field(default_factory=list)
    evidence_pack_id: str | None = None
    evidence_pack: EvidencePack | None = None
    market_context: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    developer_mode: bool = False
    run_id: UUID | None = None
    research_top_k: int = Field(default=6, ge=3, le=12)

    @model_validator(mode="after")
    def _normalize_question(self) -> "OrchestratorRequest":
        if not self.question and self.prompt:
            self.question = self.prompt
        if not self.prompt and self.question:
            self.prompt = self.question
        return self


class OrchestratorResponse(BaseModel):
    trace_id: UUID
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    outputs: list[AgentOutput]
    tool_results: dict[str, dict] = Field(default_factory=dict)
    summary: str


class AgentOrchestrator:
    def __init__(
        self,
        agents: dict[str, BaseAgent],
        tool_registry: ToolRegistry,
        audit_store: FileAuditStore,
        knowledge_service: KnowledgeService | None = None,
    ) -> None:
        self.agents = agents
        self.tool_registry = tool_registry
        self.audit_store = audit_store
        self.knowledge_service = knowledge_service

    def _resolve_evidence_pack(self, req: OrchestratorRequest) -> EvidencePack | None:
        if req.evidence_pack is not None:
            return req.evidence_pack
        if req.evidence_pack_id and self.knowledge_service is not None:
            return self.knowledge_service.get_pack(req.evidence_pack_id)
        return None

    def _retrieve_pack(self, query: str, top_k: int) -> EvidencePack | None:
        if self.knowledge_service is None:
            return None
        try:
            return self.knowledge_service.retrieve(query=query, top_k=top_k)
        except Exception:
            return None

    def _build_counter_query(self, agent_name: str, question: str, evidence_query: str) -> str:
        base = evidence_query.strip() or question.strip()
        lens_suffix = {
            "Buffett": "disconfirming evidence value trap debt refinancing downside scenario",
            "Soros": "regime reversal liquidity shock policy surprise reflexivity unwind",
            "Simons": "signal decay overfit turnover spike transaction cost stress",
            "Dalio": "correlation breakdown inflation shock concentration risk downside",
            "Kahneman": "counterfactual base rate disconfirmation bias narrative fallacy opposite case",
            "Factor": "oos instability parameter fragility false discovery counterexample",
        }.get(agent_name, "counterexample downside risk opposite thesis")
        query = f"{base} {lens_suffix}".strip()
        if query == base:
            query = f"{base} opposite thesis and counterevidence"
        return query

    def _source_ids(self, sources: list[EvidenceSource]) -> set[str]:
        return {source.source_id for source in sources}

    def _merge_sources(self, left: list[EvidenceSource], right: list[EvidenceSource]) -> list[EvidenceSource]:
        seen: set[str] = set()
        merged: list[EvidenceSource] = []
        for source in [*left, *right]:
            if source.source_id in seen:
                continue
            seen.add(source.source_id)
            merged.append(source)
        return merged

    def _counter_sources(
        self,
        *,
        question: str,
        evidence_query: str,
        base_sources: list[EvidenceSource],
        top_k: int,
        agent_name: str,
    ) -> tuple[str, list[EvidenceSource]]:
        counter_query = self._build_counter_query(agent_name, question, evidence_query)
        initial_ids = self._source_ids(base_sources[:3])
        counter_pack = self._retrieve_pack(counter_query, top_k=top_k)
        candidates = list(counter_pack.sources) if counter_pack else []
        unique = [source for source in candidates if source.source_id not in initial_ids]

        if not unique and self.knowledge_service is not None:
            retry_query = f"{counter_query} opposite outcome risk case study"
            retry_pack = self._retrieve_pack(retry_query, top_k=min(12, top_k + 3))
            if retry_pack is not None:
                retry_unique = [source for source in retry_pack.sources if source.source_id not in initial_ids]
                if retry_unique:
                    counter_query = retry_query
                    unique = retry_unique
        if not unique:
            unique = [source for source in base_sources[3:] if source.source_id not in initial_ids]
        return counter_query, unique[: max(1, min(4, top_k))]

    def _build_research_trace(
        self,
        *,
        question: str,
        agent_name: str,
        evidence_query: str,
        counter_query: str,
        initial_sources: list[EvidenceSource],
        counter_sources: list[EvidenceSource],
        out: AgentOutput,
    ) -> ReasoningTrace:
        initial_refs = [source.source_id for source in initial_sources[:3]]
        counter_refs = [source.source_id for source in counter_sources[:3]]
        initial_hypothesis = f"初始假设：从{agent_name}视角看，问题“{question[:120]}”存在可执行主线。"
        initial_conf = min(0.85, 0.45 + len(initial_refs) * 0.08)
        after_evidence = min(0.9, initial_conf + (0.1 if initial_refs else 0.0))
        after_counter = max(0.1, after_evidence - (0.12 if counter_refs else 0.04))
        final_conf = max(0.0, min(1.0, float(out.confidence)))
        revision_delta = round(final_conf - after_counter, 4)

        steps = [
            ReasoningStep(
                step_type="hypothesis",
                question=question,
                query=evidence_query,
                evidence_refs=[],
                output_summary=initial_hypothesis,
                confidence_delta=round(initial_conf - 0.45, 4),
            ),
            ReasoningStep(
                step_type="evidence_search",
                question=question,
                query=evidence_query,
                evidence_refs=initial_refs,
                output_summary=(
                    f"主证据检索完成，聚焦 {len(initial_refs)} 条关键来源。"
                    if initial_refs
                    else "主证据检索完成，但未拿到足够高置信来源。"
                ),
                confidence_delta=round(after_evidence - initial_conf, 4),
            ),
            ReasoningStep(
                step_type="counterevidence_search",
                question=question,
                query=counter_query,
                evidence_refs=counter_refs,
                output_summary=(
                    f"已执行反证检索并找到 {len(counter_refs)} 条反向来源，用于挑战初始假设。"
                    if counter_refs
                    else "已执行反证检索，但反向证据不足，保留更高不确定性。"
                ),
                confidence_delta=round(after_counter - after_evidence, 4),
            ),
            ReasoningStep(
                step_type="revision",
                question=question,
                query=counter_query,
                evidence_refs=list(dict.fromkeys([*initial_refs, *counter_refs])),
                output_summary=(
                    f"修正：由“{initial_hypothesis}”调整为“{out.claim}”，"
                    f"并纳入反证后重新评估置信度。"
                ),
                confidence_delta=revision_delta,
            ),
            ReasoningStep(
                step_type="decision",
                question=question,
                query="",
                evidence_refs=out.evidence_refs[:3],
                output_summary=(
                    f"决策建议：{out.claim}。未解决问题：{'; '.join(out.uncertainty[:2]) or '继续补充反证样本。'}"
                ),
                confidence_delta=0.0,
            ),
        ]
        return ReasoningTrace(steps=steps)

    def handle(self, req: OrchestratorRequest) -> OrchestratorResponse:
        trace_id = uuid4()
        question = req.question or req.prompt or ""
        evidence = self._resolve_evidence_pack(req)
        if evidence is None:
            evidence = self._retrieve_pack(question, top_k=req.research_top_k)
        evidence = evidence or EvidencePack(query=question, sources=[], key_points=["No evidence available."])
        evidence_pack_id = req.evidence_pack_id or str(evidence.evidence_pack_id)

        outputs: list[AgentOutput] = []
        for agent_name in req.active_agents:
            agent = self.agents.get(agent_name)
            if agent is None:
                continue
            evidence_query = evidence.query or question
            initial_sources = list(evidence.sources)
            counter_query, counter_sources = self._counter_sources(
                question=question,
                evidence_query=evidence_query,
                base_sources=initial_sources,
                top_k=req.research_top_k,
                agent_name=agent_name,
            )
            merged_sources = self._merge_sources(initial_sources, counter_sources)
            merged_pack = evidence.model_copy(
                update={
                    "query": evidence_query,
                    "sources": merged_sources,
                    "key_points": [
                        *(evidence.key_points or []),
                        f"counter_query={counter_query}",
                        f"counter_sources={len(counter_sources)}",
                    ],
                }
            )
            loop_constraints = dict(req.constraints)
            loop_constraints["research_loop"] = {
                "agent": agent_name,
                "hypothesis": f"{agent_name} initial thesis on: {question}",
                "evidence_query": evidence_query,
                "counter_query": counter_query,
                "initial_source_ids": [source.source_id for source in initial_sources[:4]],
                "counter_source_ids": [source.source_id for source in counter_sources[:4]],
            }
            out = agent.run(
                AgentTaskInput(
                    question=question,
                    prompt=req.prompt or question,
                    evidence_pack=merged_pack,
                    evidence_pack_id=evidence_pack_id,
                    market_context=req.market_context,
                    constraints=loop_constraints,
                    developer_mode=req.developer_mode,
                )
            )
            out.reasoning_trace = self._build_research_trace(
                question=question,
                agent_name=agent_name,
                evidence_query=evidence_query,
                counter_query=counter_query,
                initial_sources=initial_sources,
                counter_sources=counter_sources,
                out=out,
            )
            if evidence_pack_id:
                out.evidence_refs = list(dict.fromkeys([*out.evidence_refs, evidence_pack_id]))
            outputs.append(out)
            self.audit_store.append(
                AuditLogEntry(
                    trace_id=trace_id,
                    run_id=req.run_id,
                    event_type="agent.output",
                    payload={
                        "agent": agent.name,
                        "model": agent.model,
                        "question": question,
                        "evidence_pack_id": evidence_pack_id,
                        "output": out.model_dump(mode="json"),
                    },
                )
            )
            self.audit_store.append(
                AuditLogEntry(
                    trace_id=trace_id,
                    run_id=req.run_id,
                    event_type="agent.reasoning_trace",
                    payload={
                        "agent": agent.name,
                        "question": question,
                        "evidence_pack_id": evidence_pack_id,
                        "reasoning_trace": out.reasoning_trace.model_dump(mode="json") if out.reasoning_trace else {},
                        "research_loop": {
                            "evidence_query": evidence_query,
                            "counter_query": counter_query,
                            "initial_source_ids": [source.source_id for source in initial_sources[:4]],
                            "counter_source_ids": [source.source_id for source in counter_sources[:4]],
                        },
                    },
                )
            )

        tool_results: dict[str, dict] = {}
        for tool_name in req.tool_calls:
            tool_results[tool_name] = self.tool_registry.call(
                tool_name=tool_name,
                tool_input={},
                caller_agent="Orchestrator",
                model="router-v0",
                trace_id=trace_id,
                run_id=req.run_id,
            )

        summary = " | ".join(
            f"{out.agent_name}: {out.claim or out.summary}" for out in outputs if (out.claim or out.summary)
        ) or "No agent output"
        self.audit_store.append(
            AuditLogEntry(
                trace_id=trace_id,
                run_id=req.run_id,
                event_type="orchestrator.done",
                payload={
                    "active_agents": req.active_agents,
                    "tool_calls": req.tool_calls,
                    "question": question,
                    "evidence_pack_id": evidence_pack_id,
                    "evidence_source_count": len(evidence.sources) if evidence else 0,
                    "outputs_count": len(outputs),
                },
            )
        )
        return OrchestratorResponse(
            trace_id=trace_id,
            outputs=outputs,
            tool_results=tool_results,
            summary=summary,
        )
