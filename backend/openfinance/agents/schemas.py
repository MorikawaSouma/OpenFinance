from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from openfinance.knowledge.evidence import EvidencePack


class AgentCitation(BaseModel):
    source_id: str
    title: str
    timestamp: str | None = None
    uri: str | None = None


ReasoningStepType = Literal[
    "hypothesis",
    "evidence_search",
    "counterevidence_search",
    "revision",
    "decision",
    "evidence_use",
    "counterevidence_use",
    "validation",
    "warning",
    "intent_classification",
    "evidence_retrieval",
    "llm_synthesis",
]


class ReasoningStep(BaseModel):
    step_type: ReasoningStepType
    question: str = ""
    query: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    output_summary: str = ""
    confidence_delta: float = 0.0


class ReasoningTrace(BaseModel):
    steps: list[ReasoningStep] = Field(default_factory=list)


ReasoningTraceStepType = Literal[
    "hypothesis",
    "evidence_use",
    "counterevidence_use",
    "revision",
    "decision",
    "validation",
    "warning",
]


class ReasoningEvidenceRef(BaseModel):
    source_id: str
    title: str = ""
    ts: str | None = None


class ReasoningTraceStep(BaseModel):
    trace_id: str = ""
    task_id: str = ""
    session_id: str = ""
    agent_name: str = ""
    step_idx: int = Field(default=1, ge=1)
    step_type: ReasoningTraceStepType = "warning"
    title: str = ""
    summary: str = ""
    evidence_refs: list[ReasoningEvidenceRef] = Field(default_factory=list)
    confidence_delta: float | None = None
    parse_error: str | None = None
    prompt_hash: str | None = None
    created_at: str = ""


class AgentTaskInput(BaseModel):
    question: str = ""
    prompt: str = ""
    evidence_pack: EvidencePack | None = None
    evidence_pack_id: str | None = None
    market_context: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    max_citations: int = Field(default=3, ge=1, le=8)
    developer_mode: bool = False
    trace_id: str = ""
    task_id: str = ""
    session_id: str = ""
    force_reasoning_parse_error: bool = False
    observable_emitter: Any | None = Field(default=None, exclude=True, repr=False)

    @model_validator(mode="after")
    def _normalize_question(self) -> "AgentTaskInput":
        if not self.question and self.prompt:
            self.question = self.prompt
        if not self.prompt and self.question:
            self.prompt = self.question
        return self


class AgentOutput(BaseModel):
    agent_name: str = "unknown"

    # PR19 structured reasoning output.
    claim: str = ""
    rationale: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    citations: list[AgentCitation] = Field(default_factory=list)
    reasoning_trace: ReasoningTrace | None = None
    reasoning_steps: list[ReasoningTraceStep] = Field(default_factory=list)
    challenged_assumptions: list[str] = Field(default_factory=list)
    counter_evidence_refs: list[str] = Field(default_factory=list)
    revised_recommendation: str = ""

    # Legacy-compatible fields.
    summary: str = ""
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    artifacts: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)

    # Developer diagnostics for prompt/response transparency.
    prompt_used: str | None = None
    prompt_hash: str | None = None
    raw_response: str | None = None

    @model_validator(mode="after")
    def _backfill_legacy_fields(self) -> "AgentOutput":
        if not self.claim and self.summary:
            self.claim = self.summary
        if not self.summary and self.claim:
            self.summary = self.claim
        if not self.rationale and self.assumptions:
            self.rationale = list(self.assumptions)
        if not self.assumptions and self.rationale:
            self.assumptions = list(self.rationale)
        if not self.uncertainty and self.risks:
            self.uncertainty = list(self.risks)
        if not self.risks and self.uncertainty:
            self.risks = list(self.uncertainty)
        return self
