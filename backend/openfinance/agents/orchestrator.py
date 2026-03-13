from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from openfinance.agents.base import BaseAgent
from openfinance.agents.schemas import (
    AgentOutput,
    AgentTaskInput,
    ReasoningStep,
    ReasoningTrace,
    ReasoningTraceStep,
)
from openfinance.core.audit import AuditLogEntry, FileAuditStore
from openfinance.core.config import settings
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
    session_id: str = "pipeline"
    task_id: str | None = None
    variant_index: int | None = None
    total_variants: int | None = None
    force_reasoning_parse_error: bool = False
    event_callback: Any | None = Field(default=None, exclude=True, repr=False)

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
    reasoning_steps: dict[str, list[ReasoningTraceStep]] = Field(default_factory=dict)
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

    def _summarize_payload(self, payload: Any) -> dict[str, Any]:
        if isinstance(payload, dict):
            keys = sorted([str(key) for key in payload.keys()])[:12]
            return {"type": "object", "keys": keys, "size": len(payload)}
        if isinstance(payload, list):
            return {"type": "list", "size": len(payload)}
        if isinstance(payload, (str, int, float, bool)):
            text = str(payload)
            return {"type": type(payload).__name__, "preview": text[:120]}
        return {"type": type(payload).__name__}

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

    def _legacy_step_type(self, step_type: str) -> str:
        key = str(step_type or "").strip().lower()
        mapping = {
            "hypothesis": "hypothesis",
            "evidence_use": "evidence_search",
            "counterevidence_use": "counterevidence_search",
            "revision": "revision",
            "decision": "decision",
            "validation": "decision",
            "warning": "revision",
        }
        return mapping.get(key, "revision")

    def _steps_to_reasoning_trace(
        self,
        *,
        question: str,
        evidence_query: str,
        counter_query: str,
        steps: list[ReasoningTraceStep],
    ) -> ReasoningTrace:
        out_steps: list[ReasoningStep] = []
        for row in sorted(steps, key=lambda step: (int(step.step_idx), str(step.created_at))):
            step_type = self._legacy_step_type(row.step_type)
            query = ""
            if step_type == "evidence_search":
                query = evidence_query
            elif step_type == "counterevidence_search":
                query = counter_query
            out_steps.append(
                ReasoningStep(
                    step_type=step_type,  # type: ignore[arg-type]
                    question=question,
                    query=query,
                    evidence_refs=[ref.source_id for ref in row.evidence_refs],
                    output_summary=row.summary,
                    confidence_delta=float(row.confidence_delta or 0.0),
                )
            )
        if not out_steps:
            return ReasoningTrace(steps=[])
        return ReasoningTrace(steps=out_steps)

    def _trace_to_streamed_steps(
        self,
        *,
        trace_id: UUID,
        session_id: str,
        task_id: str,
        agent_name: str,
        trace: ReasoningTrace,
    ) -> list[ReasoningTraceStep]:
        rows: list[ReasoningTraceStep] = []
        for idx, step in enumerate(trace.steps, start=1):
            rows.append(
                ReasoningTraceStep(
                    trace_id=str(trace_id),
                    task_id=task_id,
                    session_id=session_id,
                    agent_name=agent_name,
                    step_idx=idx,
                    step_type=(
                        "counterevidence_use"
                        if step.step_type == "counterevidence_search"
                        else "evidence_use"
                        if step.step_type == "evidence_search"
                        else step.step_type  # type: ignore[assignment]
                    ),
                    title=str(step.step_type).replace("_", " ").title(),
                    summary=step.output_summary,
                    evidence_refs=[
                        {
                            "source_id": source_id,
                            "title": "",
                            "ts": None,
                        }
                        for source_id in step.evidence_refs
                    ],
                    confidence_delta=step.confidence_delta,
                    created_at=datetime.now(UTC).isoformat(),
                )
            )
        return rows

    def handle(self, req: OrchestratorRequest) -> OrchestratorResponse:
        trace_id = uuid4()
        question = req.question or req.prompt or ""
        evidence = self._resolve_evidence_pack(req)
        if evidence is None:
            evidence = self._retrieve_pack(question, top_k=req.research_top_k)
        evidence = evidence or EvidencePack(query=question, sources=[], key_points=["No evidence available."])
        evidence_pack_id = req.evidence_pack_id or str(evidence.evidence_pack_id)
        reasoning_steps_by_agent: dict[str, list[ReasoningTraceStep]] = {}

        def _emit_observable(event_type: str, payload: dict[str, Any]) -> None:
            enriched = {
                **payload,
                "trace_id": str(trace_id),
                "session_id": req.session_id,
                "task_id": str(req.task_id or ""),
                "variant_index": req.variant_index,
                "total_variants": req.total_variants,
            }
            if event_type in {"reasoning.step.created", "reasoning.step.updated"}:
                step_raw = enriched.get("step")
                if isinstance(step_raw, dict):
                    step_payload = {
                        **step_raw,
                        "trace_id": str(step_raw.get("trace_id") or str(trace_id)),
                        "task_id": str(step_raw.get("task_id") or str(req.task_id or "")),
                        "session_id": str(step_raw.get("session_id") or req.session_id),
                        "agent_name": str(step_raw.get("agent_name") or payload.get("agent_name") or ""),
                    }
                    try:
                        step_obj = ReasoningTraceStep.model_validate(step_payload)
                        agent_key = str(step_obj.agent_name or "unknown")
                        rows = reasoning_steps_by_agent.setdefault(agent_key, [])
                        replaced = False
                        for idx, row in enumerate(rows):
                            if int(row.step_idx) == int(step_obj.step_idx):
                                rows[idx] = step_obj
                                replaced = True
                                break
                        if not replaced:
                            rows.append(step_obj)
                    except Exception:
                        pass
            callback = req.event_callback
            if not callable(callback):
                if event_type in {"reasoning.step.created", "reasoning.step.updated", "reasoning.trace.final"}:
                    self.audit_store.append(
                        AuditLogEntry(
                            trace_id=trace_id,
                            run_id=req.run_id,
                            event_type=event_type,
                            payload=enriched,
                        )
                    )
                return
            callback(event_type, enriched)

        outputs: list[AgentOutput] = []
        for agent_idx, agent_name in enumerate(req.active_agents, start=1):
            agent = self.agents.get(agent_name)
            if agent is None:
                continue
            _emit_observable(
                "agent.dispatched",
                {
                    "agent_name": agent_name,
                    "agent_index": agent_idx,
                    "question_preview": question[:180],
                    "evidence_pack_id": evidence_pack_id,
                },
            )
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
                    trace_id=str(trace_id),
                    task_id=str(req.task_id or ""),
                    session_id=req.session_id,
                    force_reasoning_parse_error=bool(
                        req.force_reasoning_parse_error or settings.agent_force_step_parse_error
                    ),
                    observable_emitter=_emit_observable,
                )
            )
            streamed_steps = sorted(
                list(reasoning_steps_by_agent.get(agent_name, [])),
                key=lambda row: (int(row.step_idx), str(row.created_at)),
            )
            has_parse_error = any(bool(row.parse_error) for row in streamed_steps)
            if streamed_steps and not has_parse_error:
                out.reasoning_steps = streamed_steps
                out.reasoning_trace = self._steps_to_reasoning_trace(
                    question=question,
                    evidence_query=evidence_query,
                    counter_query=counter_query,
                    steps=streamed_steps,
                )
            else:
                out.reasoning_trace = self._build_research_trace(
                    question=question,
                    agent_name=agent_name,
                    evidence_query=evidence_query,
                    counter_query=counter_query,
                    initial_sources=initial_sources,
                    counter_sources=counter_sources,
                    out=out,
                )
                if streamed_steps:
                    out.reasoning_steps = streamed_steps
                else:
                    out.reasoning_steps = self._trace_to_streamed_steps(
                        trace_id=trace_id,
                        session_id=req.session_id,
                        task_id=str(req.task_id or ""),
                        agent_name=agent_name,
                        trace=out.reasoning_trace,
                    )
            if evidence_pack_id:
                out.evidence_refs = list(dict.fromkeys([*out.evidence_refs, evidence_pack_id]))
            outputs.append(out)
            _emit_observable(
                "reasoning.trace.final",
                {
                    "agent_name": agent_name,
                    "steps_count": len(out.reasoning_steps),
                    "steps": [row.model_dump(mode="json") for row in out.reasoning_steps],
                    "has_parse_error": any(bool(row.parse_error) for row in out.reasoning_steps),
                    "prompt_hash": str(out.prompt_hash or ""),
                },
            )
            _emit_observable(
                "agent.completed",
                {
                    "agent_name": agent_name,
                    "agent_index": agent_idx,
                    "confidence": float(out.confidence or 0.0),
                    "claim_preview": str(out.claim or out.summary or "")[:180],
                    "evidence_refs": list(out.evidence_refs[:6]),
                },
            )
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
                        "reasoning_steps": [row.model_dump(mode="json") for row in out.reasoning_steps],
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
            _emit_observable(
                "tool.call.started",
                {
                    "tool_name": tool_name,
                    "args_summary": self._summarize_payload({}),
                },
            )
            t0 = perf_counter()
            tool_results[tool_name] = self.tool_registry.call(
                tool_name=tool_name,
                tool_input={},
                caller_agent="Orchestrator",
                model="router-v0",
                trace_id=trace_id,
                run_id=req.run_id,
            )
            _emit_observable(
                "tool.call.finished",
                {
                    "tool_name": tool_name,
                    "args_summary": self._summarize_payload({}),
                    "result_summary": self._summarize_payload(tool_results[tool_name]),
                    "latency_ms": int((perf_counter() - t0) * 1000),
                },
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
            reasoning_steps={row.agent_name: row.reasoning_steps for row in outputs},
            tool_results=tool_results,
            summary=summary,
        )
