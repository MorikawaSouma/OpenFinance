import hashlib
import json
import re
from datetime import date
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from openfinance.agents.catalog import build_default_agents
from openfinance.agents.orchestrator import AgentOrchestrator, OrchestratorRequest
from openfinance.core.audit import AuditLogEntry, FileAuditStore
from openfinance.core.config import settings
from openfinance.core.events import event_bus
from openfinance.data.mock_factory import MockDataFactory, MockDatasetConfig
from openfinance.data.registry import DatasetRegistry
from openfinance.knowledge.evidence import EvidencePack
from openfinance.knowledge.service import KnowledgeService, build_default_knowledge_service
from openfinance.llm.provider import LLMProviderRegistry, ZhipuGLM47Provider
from openfinance.quant.backtest.report import BacktestRequest, CostModel
from openfinance.quant.backtest.run_registry import RunRegistry
from openfinance.quant.backtest.runner import BacktestRunner
from openfinance.quant.backtest.migration import MigrationChecker
from openfinance.quant.factors.engine import FactorEngine
from openfinance.quant.factors.factor_spec import (
    CostSensitivity,
    CostSensitivityLevel,
    ExpectedHorizon,
    FactorInput,
    FactorSpec,
    FactorTransform,
    ValidationPlan,
)
from openfinance.quant.factors.registry import FactorRegistry
from openfinance.research.plan_registry import PlanRegistry
from openfinance.research.strategy_agent import StrategyAgent, StrategyDecision
from openfinance.tools.registry import build_default_tool_registry
from openfinance.trading.paper import PaperOrderRequest
from openfinance.trading.service import TradingService


class FactorCandidate(BaseModel):
    factor_id: str
    description: str
    source: str
    availability_lag: str
    rationale: str


class ExperimentVariant(BaseModel):
    variant_id: str
    strategy_family: str
    rebalance: str
    lookback_days: int = Field(ge=2, le=252)
    signal_threshold: float = 0.0
    position_sizing: str = "risk_budget"
    risk_budget: str = "vol_target_10pct"
    max_position: float = Field(default=0.15, gt=0, lt=1)
    cost_model: CostModel = Field(default_factory=CostModel)
    start: str = "2023-01-01"
    end: str = "2024-12-31"
    notes: str = ""


class ResearchSection(BaseModel):
    hypotheses: list[str] = Field(default_factory=list)
    evidence_queries: list[str] = Field(default_factory=list)
    evaluation_actions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class ResearchPlan(BaseModel):
    plan_id: str
    question: str
    markets: list[str]
    objectives: list[str]
    constraints: dict[str, Any] = Field(default_factory=dict)
    evidence_queries: list[str] = Field(default_factory=list)
    candidate_factors: list[FactorCandidate] = Field(default_factory=list)
    candidate_strategy_families: list[str] = Field(default_factory=list)
    experiment_matrix: list[ExperimentVariant] = Field(default_factory=list)
    risk_checks: list[str] = Field(default_factory=list)
    output_format: list[str] = Field(default_factory=list)
    seed: int = 42
    planner_rationale: str = ""
    agent_consensus: str = ""
    tool_context: dict[str, Any] = Field(default_factory=dict)
    value: ResearchSection
    macro: ResearchSection
    stats: ResearchSection
    behavior: ResearchSection


class CircuitBreakerRule(BaseModel):
    type: Literal["consecutive_losses", "drawdown", "vol_spike"] = "drawdown"
    threshold: float = Field(default=0.1, ge=0.0)
    cool_down_days: int = Field(default=5, ge=0)


class CircuitBreakerSpec(BaseModel):
    enabled: bool = True
    rule: CircuitBreakerRule = Field(default_factory=CircuitBreakerRule)


class StrategySpec(BaseModel):
    strategy_id: str
    strategy_version: str
    plan_id: str
    experiment_id: str
    market: str
    strategy_family: str
    rebalance: str
    lookback_days: int
    signal_threshold: float
    position_sizing: str
    risk_budget: str
    max_position: float
    stop_loss: float
    leverage_limit: float
    factor_weights: dict[str, float]
    constraints: dict[str, Any]
    circuit_breaker: CircuitBreakerSpec
    failure_regimes: list[str] = Field(default_factory=list)
    strategy_decision: dict[str, Any] = Field(default_factory=dict)
    rationale: str


class PlanCreateRequest(BaseModel):
    question: str = Field(min_length=1)
    market: str = "US"
    objectives: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    seed: int | None = None


class PlanCreateResponse(BaseModel):
    trace_id: str
    plan_id: str
    plan: ResearchPlan
    evidence_pack_id: str
    preflight_warnings: list["PreflightWarning"] = Field(default_factory=list)
    llm_mode: str


class PipelineRequest(BaseModel):
    question: str | None = Field(default=None, min_length=1)
    market: str = "US"
    objectives: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    max_drawdown_target: float = Field(default=0.10, gt=0, lt=1)
    run_paper_trade: bool = True
    plan_id: str | None = None
    seed: int | None = None
    experiments: int = Field(default=3, ge=3, le=8)
    migration_preflight_confirmed: bool = False
    auto_adjust_for_market_rules: bool = False
    response_language: Literal["en", "zh"] = "en"


class PreflightWarning(BaseModel):
    market: str
    severity: Literal["warn", "block"] = "warn"
    code: str
    title: str
    explanation: str
    suggestion: str = ""
    variant_id: str | None = None


class PipelineStep(BaseModel):
    name: str
    status: str
    summary: str
    artifacts: list[str] = Field(default_factory=list)


class ExperimentResult(BaseModel):
    variant_id: str
    strategy_family: str
    factor_version: str
    strategy_version: str
    run_id: str
    dataset_version: str
    objective_score: float
    metrics: dict[str, Any]
    factor_report: dict[str, Any]
    factor_artifact_path: str
    factor_cached: bool = False
    strategy_spec: dict[str, Any]
    strategy_decision: dict[str, Any] = Field(default_factory=dict)
    backtest_request: dict[str, Any]
    why_selected: str


class PipelineResponse(BaseModel):
    trace_id: str
    question: str
    plan_id: str
    evidence_pack_id: str
    evidence_sources: list[dict[str, Any]] = Field(default_factory=list)
    factor_version: str
    factor_report: dict[str, Any] = Field(default_factory=dict)
    factor_artifact_path: str = ""
    strategy_version: str
    dataset_version: str
    run_id: str
    backtest_metrics: dict[str, Any]
    strategy_config: dict[str, Any]
    strategy_decision: dict[str, Any] = Field(default_factory=dict)
    risk_explanation: str
    research_plan: dict[str, Any] = Field(default_factory=dict)
    experiments: list[ExperimentResult] = Field(default_factory=list)
    comparison_table: list[dict[str, Any]] = Field(default_factory=list)
    interpretation: str = ""
    paper_trade_result: dict[str, Any] | None = None
    agent_outputs: list[dict[str, Any]] = Field(default_factory=list)
    preflight_warnings: list[PreflightWarning] = Field(default_factory=list)
    preflight_actions: list[str] = Field(default_factory=list)
    llm_mode: str = "stub"
    steps: list[PipelineStep]


class MigrationPreflightBlockedError(ValueError):
    def __init__(self, warnings: list[PreflightWarning]) -> None:
        super().__init__("Migration preflight blocked. Confirm migration risk or enable auto-adjust before running.")
        self.warnings = warnings


PlanCreateResponse.model_rebuild()


class ResearchPipelineEngine:
    def __init__(
        self,
        audit_store: FileAuditStore,
        dataset_registry: DatasetRegistry,
        run_registry: RunRegistry,
        plan_registry: PlanRegistry,
    ) -> None:
        self.audit_store = audit_store
        self.dataset_registry = dataset_registry
        self.run_registry = run_registry
        self.plan_registry = plan_registry
        self.trading_service = TradingService(audit_store=audit_store)
        self.runner = BacktestRunner(
            dataset_registry=dataset_registry,
            run_registry=run_registry,
            audit_store=audit_store,
            report_root=dataset_registry.data_root.as_posix(),
        )
        self.factor_registry = FactorRegistry(settings.factor_registry_db_file)
        self.factor_engine = FactorEngine(
            dataset_registry=dataset_registry,
            factor_registry=self.factor_registry,
            artifact_root=settings.factor_artifact_root,
        )
        self.knowledge: KnowledgeService = build_default_knowledge_service()
        self.llm_registry = LLMProviderRegistry()
        self.llm_registry.register(ZhipuGLM47Provider(), is_default=True)
        self.strategy_agent = StrategyAgent(self.llm_registry)
        tools = build_default_tool_registry(
            audit_store=audit_store,
            dataset_registry=dataset_registry,
            run_registry=run_registry,
        )
        self.orchestrator = AgentOrchestrator(
            build_default_agents(knowledge_service=self.knowledge),
            tool_registry=tools,
            audit_store=audit_store,
            knowledge_service=self.knowledge,
        )

    def create_plan(self, request: PlanCreateRequest) -> PlanCreateResponse:
        trace_id = str(uuid4())
        self._emit("task.created", trace_id, {"stage": "plan.start", "question": request.question})
        plan, evidence, llm_mode = self._build_research_plan(request, trace_id)
        preflight_warnings = self._run_migration_preflight(plan)
        self.plan_registry.append(plan)
        self._audit(
            trace_id,
            "plan.created",
            {
                "plan_id": plan.plan_id,
                "question": plan.question,
                "markets": plan.markets,
                "objectives": plan.objectives,
                "constraints": plan.constraints,
                "candidate_factors": [f.model_dump(mode="json") for f in plan.candidate_factors],
                "experiment_matrix": [v.model_dump(mode="json") for v in plan.experiment_matrix],
                "framework_sections": {
                    "value": plan.value.model_dump(mode="json"),
                    "macro": plan.macro.model_dump(mode="json"),
                    "stats": plan.stats.model_dump(mode="json"),
                    "behavior": plan.behavior.model_dump(mode="json"),
                },
                "preflight_warnings": [row.model_dump(mode="json") for row in preflight_warnings],
            },
        )
        self._emit("task.done", trace_id, {"stage": "plan.done", "plan_id": plan.plan_id})
        return PlanCreateResponse(
            trace_id=trace_id,
            plan_id=plan.plan_id,
            plan=plan,
            evidence_pack_id=str(evidence.evidence_pack_id),
            preflight_warnings=preflight_warnings,
            llm_mode=llm_mode,
        )

    def run(self, request: PipelineRequest) -> PipelineResponse:
        trace_id = str(uuid4())
        if request.plan_id:
            raw = self.plan_registry.get_plan_payload(request.plan_id)
            if raw is None:
                raise ValueError(f"plan_id not found: {request.plan_id}")
            normalized_raw, schema_validation_errors = self._normalize_framework_sections(
                dict(raw),
                question=str(raw.get("question") or request.question or ""),
                market=str((raw.get("markets") or [request.market])[0] if isinstance(raw.get("markets"), list) else request.market),
                profile=self._detect_profile(str(raw.get("question") or request.question or "")),
            )
            if schema_validation_errors:
                self._audit(
                    trace_id,
                    "plan.schema.validation",
                    {
                        "plan_id": str(raw.get("plan_id") or request.plan_id),
                        "schema_validation_errors": schema_validation_errors,
                        "source": "plan_registry_load",
                    },
                )
            plan = ResearchPlan.model_validate(normalized_raw)
            llm_mode = "cached_plan"
            evidence = self._build_evidence_pack(plan, trace_id)
        else:
            if not request.question:
                raise ValueError("question is required when plan_id is not provided")
            plan_req = PlanCreateRequest(
                question=request.question,
                market=request.market,
                objectives=request.objectives,
                constraints=request.constraints,
                seed=request.seed,
            )
            plan, evidence, llm_mode = self._build_research_plan(plan_req, trace_id)
            self.plan_registry.append(plan)

        if request.max_drawdown_target:
            plan.constraints["max_drawdown_target"] = request.max_drawdown_target
        plan.experiment_matrix = plan.experiment_matrix[: max(3, request.experiments)]
        preflight_warnings = self._run_migration_preflight(plan)
        preflight_actions: list[str] = []
        if preflight_warnings:
            self._audit(
                trace_id,
                "pipeline.preflight.warning",
                {
                    "plan_id": plan.plan_id,
                    "warnings": [row.model_dump(mode="json") for row in preflight_warnings],
                },
            )
        has_block = any(row.severity == "block" for row in preflight_warnings)
        if has_block and request.auto_adjust_for_market_rules:
            preflight_actions = self._apply_preflight_adjustments(plan, preflight_warnings)
            preflight_warnings = self._run_migration_preflight(plan)
            has_block = any(row.severity == "block" for row in preflight_warnings)
            self._audit(
                trace_id,
                "pipeline.preflight.auto_adjust",
                {
                    "plan_id": plan.plan_id,
                    "actions": preflight_actions,
                    "remaining_warnings": [row.model_dump(mode="json") for row in preflight_warnings],
                },
            )
        if has_block and (not request.migration_preflight_confirmed):
            raise MigrationPreflightBlockedError(preflight_warnings)
        self._emit("task.created", trace_id, {"stage": "pipeline.start", "plan_id": plan.plan_id})
        return self._execute_plan(
            plan=plan,
            evidence=evidence,
            trace_id=trace_id,
            run_paper_trade=request.run_paper_trade,
            preflight_warnings=preflight_warnings,
            preflight_actions=preflight_actions,
            llm_mode=llm_mode,
            response_language=request.response_language,
        )

    def _build_research_plan(
        self, request: PlanCreateRequest, trace_id: str
    ) -> tuple[ResearchPlan, EvidencePack, str]:
        profile = self._detect_profile(request.question)
        seed = request.seed if request.seed is not None else self._seed_from_question(request.question)
        market = request.market or self._infer_market(request.question)
        base = self._profile_template(profile=profile, question=request.question, market=market)
        if request.objectives:
            base["objectives"] = request.objectives
        base["constraints"].update(request.constraints)
        base["constraints"].setdefault("max_drawdown_target", 0.1)
        base["seed"] = seed
        plan_id = self._plan_id(request.question, market, seed, base["objectives"], base["constraints"])

        llm_overlay, llm_mode = self._llm_plan_overlay(request.question, base)
        if llm_overlay:
            base = self._merge_plan_overlay(base, llm_overlay)
        base, schema_validation_errors = self._normalize_framework_sections(
            base,
            question=request.question,
            market=market,
            profile=profile,
        )
        if schema_validation_errors:
            self._audit(
                trace_id,
                "plan.schema.validation",
                {
                    "plan_id": plan_id,
                    "schema_validation_errors": schema_validation_errors,
                    "source": "llm_overlay_or_template",
                },
            )

        plan = ResearchPlan(
            plan_id=plan_id,
            question=request.question,
            markets=[market],
            objectives=base["objectives"],
            constraints=base["constraints"],
            evidence_queries=base["evidence_queries"],
            candidate_factors=[FactorCandidate.model_validate(row) for row in base["candidate_factors"]],
            candidate_strategy_families=base["candidate_strategy_families"],
            experiment_matrix=[ExperimentVariant.model_validate(row) for row in base["experiment_matrix"]],
            risk_checks=base["risk_checks"],
            output_format=base["output_format"],
            seed=seed,
            planner_rationale=base["planner_rationale"],
            agent_consensus="",
            tool_context={},
            value=ResearchSection.model_validate(base["value"]),
            macro=ResearchSection.model_validate(base["macro"]),
            stats=ResearchSection.model_validate(base["stats"]),
            behavior=ResearchSection.model_validate(base["behavior"]),
        )
        evidence = self._build_evidence_pack(plan, trace_id)
        orch = self.orchestrator.handle(
            OrchestratorRequest(
                prompt=request.question,
                question=request.question,
                active_agents=["Buffett", "Soros", "Simons", "Dalio", "Kahneman", "Factor"],
                tool_calls=[
                    "read_dataset_versions",
                    "read_run_versions",
                    "read_market_rules",
                    "read_risk_controls",
                ],
                evidence_pack_id=str(evidence.evidence_pack_id),
                evidence_pack=evidence,
                market_context={
                    "market": market,
                    "objectives": plan.objectives,
                    "plan_id": plan.plan_id,
                },
                constraints=plan.constraints,
                developer_mode=True,
            )
        )
        plan.agent_consensus = orch.summary
        plan.tool_context = {
            "tool_results": orch.tool_results,
            "agent_outputs": [row.model_dump(mode="json") for row in orch.outputs],
        }
        return plan, evidence, llm_mode

    def _execute_plan(
        self,
        *,
        plan: ResearchPlan,
        evidence: EvidencePack,
        trace_id: str,
        run_paper_trade: bool,
        preflight_warnings: list[PreflightWarning],
        preflight_actions: list[str],
        llm_mode: str,
        response_language: Literal["en", "zh"],
    ) -> PipelineResponse:
        steps: list[PipelineStep] = []
        steps.append(
            PipelineStep(
                name="plan.compose",
                status="done",
                summary=f"Plan generated with {len(plan.experiment_matrix)} experiment variants.",
                artifacts=[plan.plan_id],
            )
        )
        if preflight_warnings:
            block_count = len([row for row in preflight_warnings if row.severity == "block"])
            warn_count = len(preflight_warnings) - block_count
            status = "warn" if block_count == 0 else "done"
            summary = f"Preflight warnings={warn_count}, blocks={block_count}."
            if preflight_actions:
                summary = f"{summary} Applied auto-adjustments: {len(preflight_actions)}."
            steps.append(
                PipelineStep(
                    name="migration.preflight",
                    status=status,
                    summary=summary,
                    artifacts=[row.code for row in preflight_warnings],
                )
            )
        self._stage_evidence(plan, trace_id, steps, evidence)
        dataset_version = self._stage_dataset(plan, trace_id, steps)

        experiments: list[ExperimentResult] = []
        for variant in plan.experiment_matrix:
            factor_spec, factor_version = self._build_factor_spec(plan, variant)
            factor_result = self.factor_engine.run(
                factor_spec=factor_spec,
                dataset_version=dataset_version,
                factor_version=factor_version,
                seed=plan.seed,
            )
            factor_report_payload = factor_result.report.model_dump(mode="json")
            strategy_decision = self.strategy_agent.decide(
                question=plan.question,
                market=plan.markets[0],
                research_plan=plan.model_dump(mode="json"),
                factor_health_report=factor_report_payload,
                constraints=plan.constraints,
                market_rules=self._market_rules_payload(plan.markets[0]),
                risk_budget=variant.risk_budget,
                variant=variant.model_dump(mode="json"),
            )
            strategy_spec = self._build_strategy_spec(
                plan,
                variant,
                factor_result.factor_version,
                strategy_decision=strategy_decision,
            )
            backtest_request = self._build_backtest_request(
                plan=plan,
                variant=variant,
                strategy_spec=strategy_spec,
                dataset_version=dataset_version,
                evidence=evidence,
                factor_id=factor_result.factor_id,
                factor_version=factor_result.factor_version,
                factor_artifact_path=factor_result.artifact_path,
                factor_failure_conditions=factor_spec.failure_conditions,
                strategy_decision=strategy_decision,
            )
            report = self.runner.run(backtest_request)
            score = self._score_objective(report.metrics, plan.objectives)
            result = ExperimentResult(
                variant_id=variant.variant_id,
                strategy_family=variant.strategy_family,
                factor_version=factor_result.factor_version,
                strategy_version=strategy_spec.strategy_version,
                run_id=str(report.run_id),
                dataset_version=dataset_version,
                objective_score=score,
                metrics=report.metrics,
                factor_report=factor_result.report.model_dump(mode="json"),
                factor_artifact_path=factor_result.artifact_path,
                factor_cached=factor_result.cached,
                strategy_spec=strategy_spec.model_dump(mode="json"),
                strategy_decision=strategy_decision.model_dump(mode="json"),
                backtest_request=backtest_request.model_dump(mode="json"),
                why_selected=strategy_decision.selected.rationale or variant.notes or strategy_spec.rationale,
            )
            experiments.append(result)
            self._audit(
                trace_id,
                "pipeline.experiment.done",
                {
                    "plan_id": plan.plan_id,
                    "variant_id": variant.variant_id,
                    "factor_spec": factor_spec.model_dump(mode="json"),
                    "factor_report": factor_result.report.model_dump(mode="json"),
                    "factor_artifact_path": factor_result.artifact_path,
                    "factor_health_report_artifact_path": factor_result.report.health_report_artifact_path,
                    "factor_cached": factor_result.cached,
                    "strategy_spec": strategy_spec.model_dump(mode="json"),
                    "strategy_decision": strategy_decision.model_dump(mode="json"),
                    "backtest_request": backtest_request.model_dump(mode="json"),
                    "evidence_pack_id": str(evidence.evidence_pack_id),
                    "metrics": report.metrics,
                },
                report.run_id,
            )
            self._audit(
                trace_id,
                "strategy.decision.selected",
                {
                    "plan_id": plan.plan_id,
                    "variant_id": variant.variant_id,
                    "selected": strategy_decision.selected.model_dump(mode="json"),
                    "candidates": [row.model_dump(mode="json") for row in strategy_decision.candidates],
                    "llm_mode": strategy_decision.llm_mode,
                },
                report.run_id,
            )

        experiments = sorted(experiments, key=lambda item: item.objective_score, reverse=True)
        if not experiments:
            raise RuntimeError("experiment_matrix produced no experiments")
        best = experiments[0]
        steps.append(
            PipelineStep(
                name="factor.define",
                status="done",
                summary=(
                    f"Selected factor version {best.factor_version}; "
                    f"IC={best.factor_report.get('ic_mean')}, RankIC={best.factor_report.get('rank_ic_mean')}."
                ),
                artifacts=[best.factor_version, best.factor_artifact_path],
            )
        )
        steps.append(
            PipelineStep(
                name="strategy.compose",
                status="done",
                summary=(
                    f"Selected strategy {best.strategy_version} ({best.strategy_family}). "
                    f"{str((best.strategy_decision.get('selected') or {}).get('tradeoff_summary', ''))[:120]}"
                ).strip(),
                artifacts=[best.strategy_version],
            )
        )
        steps.append(
            PipelineStep(
                name="backtest.run",
                status="done",
                summary=(
                    f"Best run {best.run_id} with Sharpe={best.metrics.get('sharpe')}, "
                    f"MDD={best.metrics.get('max_drawdown')}"
                ),
                artifacts=[best.run_id],
            )
        )
        steps.append(
            PipelineStep(
                name="backtest.compare",
                status="done",
                summary=f"Compared {len(experiments)} variants under same dataset_version.",
                artifacts=[exp.run_id for exp in experiments],
            )
        )
        paper = self._stage_paper_trade(
            plan,
            trace_id,
            steps,
            enabled=run_paper_trade,
            evidence_pack_id=str(evidence.evidence_pack_id),
        )
        risk_explanation = (
            "Risk gate active. Live trading remains disabled by default. "
            f"Kill switch is {'on' if self.trading_service.status().kill_switch_enabled else 'off'}."
        )
        steps.append(PipelineStep(name="risk.explain", status="done", summary=risk_explanation))
        interpretation, interpret_mode = self._interpret_results(
            plan,
            evidence,
            experiments,
            response_language=response_language,
        )
        comparison = self._comparison_table(experiments)
        self._emit("task.done", trace_id, {"stage": "pipeline.done", "run_id": best.run_id, "plan_id": plan.plan_id})

        return PipelineResponse(
            trace_id=trace_id,
            question=plan.question,
            plan_id=plan.plan_id,
            evidence_pack_id=str(evidence.evidence_pack_id),
            evidence_sources=[self._evidence_source_payload(source) for source in evidence.sources],
            factor_version=best.factor_version,
            factor_report=best.factor_report,
            factor_artifact_path=best.factor_artifact_path,
            strategy_version=best.strategy_version,
            dataset_version=best.dataset_version,
            run_id=best.run_id,
            backtest_metrics=best.metrics,
            strategy_config=best.strategy_spec,
            strategy_decision=best.strategy_decision,
            risk_explanation=risk_explanation,
            research_plan=plan.model_dump(mode="json"),
            experiments=experiments,
            comparison_table=comparison,
            interpretation=interpretation,
            paper_trade_result=paper,
            agent_outputs=list(plan.tool_context.get("agent_outputs", [])),
            preflight_warnings=preflight_warnings,
            preflight_actions=preflight_actions,
            llm_mode=interpret_mode if interpret_mode != "stub" else llm_mode,
            steps=steps,
        )

    def _stage_evidence(
        self, plan: ResearchPlan, trace_id: str, steps: list[PipelineStep], evidence: EvidencePack
    ) -> None:
        steps.append(
            PipelineStep(
                name="evidence.pack",
                status="done",
                summary=f"Evidence pack built with {len(evidence.sources)} sources.",
                artifacts=[str(evidence.evidence_pack_id)],
            )
        )
        self._audit(
            trace_id,
            "pipeline.evidence.done",
            {
                "plan_id": plan.plan_id,
                "evidence_pack_id": str(evidence.evidence_pack_id),
                "queries": plan.evidence_queries,
                "sources": [
                    {
                        "title": source.title,
                        "source_type": source.source_type,
                        "uri": source.uri or source.url,
                        "ts": source.published_at.isoformat() if source.published_at else None,
                        "full_text_ref": source.full_text_ref,
                        "credibility_score": source.credibility_score,
                        "credibility_breakdown": source.credibility_breakdown,
                    }
                    for source in evidence.sources
                ],
                "credibility_breakdown": evidence.credibility_breakdown,
            },
        )
        self._emit("task.progress", trace_id, {"stage": "evidence.pack", "status": "done"})

    def _stage_dataset(self, plan: ResearchPlan, trace_id: str, steps: list[PipelineStep]) -> str:
        market = plan.markets[0] if plan.markets else "US"
        symbol_map = {"US": "AAPL", "CN": "600519.SS", "JP": "7203.T", "CRYPTO": "BTCUSDT"}
        config = MockDatasetConfig(
            dataset_id=f"plan_{market.lower()}",
            market=market,
            symbol=symbol_map.get(market, "AAPL"),
            start_date=date(2023, 1, 1),
            end_date=date(2024, 12, 31),
            seed=plan.seed,
            include_survivorship_bias=bool(plan.constraints.get("survivorship_bias", True)),
        )
        dataset = MockDataFactory().generate(config)
        entry = self.dataset_registry.register(dataset)
        steps.append(
            PipelineStep(
                name="dataset.prepare",
                status="done",
                summary="Dataset generated and registered from plan seed/config.",
                artifacts=[entry.dataset_version],
            )
        )
        self._audit(
            trace_id,
            "pipeline.dataset.done",
            {
                "plan_id": plan.plan_id,
                "dataset_version": entry.dataset_version,
                "seed": plan.seed,
                "generation_config": entry.generation_config,
            },
        )
        self._emit("task.progress", trace_id, {"stage": "dataset.prepare", "status": "done"})
        return entry.dataset_version

    def _build_factor_spec(self, plan: ResearchPlan, variant: ExperimentVariant) -> tuple[FactorSpec, str]:
        factor_inputs = [
            FactorInput(
                name=row.factor_id,
                source=row.source,
                availability_lag=row.availability_lag,
            )
            for row in plan.candidate_factors[:3]
        ]
        factor_id = self._factor_id_for_strategy_family(variant.strategy_family)
        params: dict[str, Any] = {
            "lookback_days": variant.lookback_days,
            "signal_threshold": variant.signal_threshold,
            "strategy_family": variant.strategy_family,
            "market": plan.markets[0],
            "decay_lags": 6,
        }
        raw_universe = plan.constraints.get("universe")
        if isinstance(raw_universe, list):
            params["universe"] = [str(item) for item in raw_universe if str(item).strip()]
        level_map = {
            "low": CostSensitivityLevel.low,
            "medium": CostSensitivityLevel.medium,
            "high": CostSensitivityLevel.high,
        }
        horizon_map = {
            "intraday": ExpectedHorizon.intraday,
            "swing": ExpectedHorizon.swing,
            "long_only": ExpectedHorizon.long_only,
        }
        raw_cost_level = str(
            plan.constraints.get("factor_cost_sensitivity_level", plan.constraints.get("cost_sensitivity_level", "medium"))
        ).lower()
        cost_level = level_map.get(raw_cost_level, CostSensitivityLevel.medium)
        raw_horizon = str(plan.constraints.get("factor_expected_horizon", plan.constraints.get("expected_horizon", "swing"))).lower()
        expected_horizon = horizon_map.get(raw_horizon, ExpectedHorizon.swing)
        cost_rationale = str(
            plan.constraints.get(
                "factor_cost_sensitivity_rationale",
                "Planner default for draft factor pack before live tuning.",
            )
        ).strip()
        spec = FactorSpec(
            factor_id=factor_id,
            factor_version="draft",
            description=f"{variant.strategy_family} factor pack for plan {plan.plan_id}",
            inputs=factor_inputs,
            params=params,
            transforms=[
                FactorTransform(name="momentum_1d", params={"lookback": max(1, min(variant.lookback_days, 40))}),
                FactorTransform(name="mean_reversion", params={"window": max(5, min(variant.lookback_days, 60))}),
                FactorTransform(name="volatility", params={"window": max(5, min(variant.lookback_days, 30))}),
                FactorTransform(name="volume_surprise", params={"window": max(5, min(variant.lookback_days, 30))}),
                FactorTransform(name="intraday_return", params={}),
                FactorTransform(name="carry_proxy", params={"market": plan.markets[0]}),
            ],
            failure_conditions=[
                "high_volatility_regime",
                "range_bound_market",
                "liquidity_dry_up",
                "policy_shock",
            ],
            cost_sensitivity=CostSensitivity(
                level=cost_level,
                rationale=cost_rationale or "Planner default for draft factor pack before live tuning.",
            ),
            expected_horizon=expected_horizon,
            validation_plan=ValidationPlan(
                in_sample_start=variant.start,
                in_sample_end="2023-12-31",
                out_sample_start="2024-01-01",
                out_sample_end=variant.end,
                checks=["lookahead", "stability", "survivorship", "turnover_sensitivity"],
            ),
        )
        version = hashlib.sha1(
            json.dumps(
                {
                    "plan_id": plan.plan_id,
                    "variant_id": variant.variant_id,
                    "factor": spec.model_dump(mode="json"),
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:12]
        spec = spec.model_copy(update={"factor_version": version})
        return spec, version

    def _build_strategy_spec(
        self,
        plan: ResearchPlan,
        variant: ExperimentVariant,
        factor_version: str,
        strategy_decision: StrategyDecision | None = None,
    ) -> StrategySpec:
        selected_spec = strategy_decision.selected.spec if strategy_decision else {}
        selected_rebalance = str(selected_spec.get("rebalance", variant.rebalance)).strip().lower()
        selected_lookback = int(selected_spec.get("lookback_days", variant.lookback_days) or variant.lookback_days)
        selected_signal_threshold = float(
            selected_spec.get("signal_threshold", variant.signal_threshold) or variant.signal_threshold
        )
        selected_position_sizing = str(selected_spec.get("position_sizing", variant.position_sizing)).strip().lower()
        selected_risk_budget = str(selected_spec.get("risk_budget", variant.risk_budget)).strip()
        selected_max_position = float(selected_spec.get("max_position", variant.max_position) or variant.max_position)
        selected_strategy_family = str(selected_spec.get("strategy_family", variant.strategy_family)).strip()
        selected_max_position = max(0.01, min(0.95, selected_max_position))
        selected_lookback = max(2, min(252, selected_lookback))
        weights = self._factor_weights(plan.candidate_factors)
        payload = {
            "plan_id": plan.plan_id,
            "variant_id": variant.variant_id,
            "factor_version": factor_version,
            "strategy_decision_selected": selected_spec,
            "constraints": plan.constraints,
        }
        strategy_version = hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:12]
        stop_loss = float(plan.constraints.get("stop_loss", 0.06))
        leverage_limit = float(plan.constraints.get("leverage_limit", 1.0))
        default_drawdown_limit = float(plan.constraints.get("max_drawdown_target", 0.1))
        raw_circuit_breaker = plan.constraints.get("circuit_breaker")
        cb_enabled = True
        cb_type: Literal["consecutive_losses", "drawdown", "vol_spike"] = "drawdown"
        cb_threshold = max(0.0, default_drawdown_limit)
        cb_cool_down_days = 5
        if isinstance(raw_circuit_breaker, dict):
            if isinstance(raw_circuit_breaker.get("enabled"), bool):
                cb_enabled = bool(raw_circuit_breaker.get("enabled"))
            raw_rule = raw_circuit_breaker.get("rule")
            if isinstance(raw_rule, dict):
                raw_type = str(raw_rule.get("type", "drawdown")).strip().lower()
                if raw_type in {"consecutive_losses", "drawdown", "vol_spike"}:
                    cb_type = raw_type  # type: ignore[assignment]
                raw_threshold = raw_rule.get("threshold")
                if isinstance(raw_threshold, (int, float)):
                    cb_threshold = max(0.0, float(raw_threshold))
                raw_cool_down = raw_rule.get("cool_down_days")
                if isinstance(raw_cool_down, (int, float)):
                    cb_cool_down_days = max(0, int(raw_cool_down))
        raw_failure_regimes = plan.constraints.get("failure_regimes")
        if isinstance(raw_failure_regimes, list):
            failure_regimes = [str(item).strip() for item in raw_failure_regimes if str(item).strip()]
        else:
            failure_regimes = [
                "range_bound_market",
                "high_correlation_breakdown",
                "frequent_gap_moves",
            ]
        if strategy_decision:
            decision_regimes: list[str] = []
            for row in strategy_decision.candidates:
                if row.name == strategy_decision.selected.name:
                    decision_regimes.extend(row.expected_failure_regimes)
            if decision_regimes:
                failure_regimes = decision_regimes + failure_regimes
        failure_regimes = list(dict.fromkeys(failure_regimes))[:8]
        rationale = variant.notes or f"Experiment tuned for objectives: {', '.join(plan.objectives)}"
        if strategy_decision:
            rationale = (
                f"{strategy_decision.selected.rationale}\n"
                f"Trade-off: {strategy_decision.selected.tradeoff_summary}"
            ).strip()
        return StrategySpec(
            strategy_id="plan_strategy",
            strategy_version=strategy_version,
            plan_id=plan.plan_id,
            experiment_id=variant.variant_id,
            market=plan.markets[0],
            strategy_family=selected_strategy_family,
            rebalance=selected_rebalance,
            lookback_days=selected_lookback,
            signal_threshold=selected_signal_threshold,
            position_sizing=selected_position_sizing,
            risk_budget=selected_risk_budget,
            max_position=selected_max_position,
            stop_loss=stop_loss,
            leverage_limit=leverage_limit,
            factor_weights=weights,
            constraints=plan.constraints,
            circuit_breaker=CircuitBreakerSpec(
                enabled=cb_enabled,
                rule=CircuitBreakerRule(
                    type=cb_type,
                    threshold=cb_threshold,
                    cool_down_days=cb_cool_down_days,
                ),
            ),
            failure_regimes=failure_regimes,
            strategy_decision=strategy_decision.model_dump(mode="json") if strategy_decision else {},
            rationale=rationale,
        )

    def _build_backtest_request(
        self,
        plan: ResearchPlan,
        variant: ExperimentVariant,
        strategy_spec: StrategySpec,
        dataset_version: str,
        evidence: EvidencePack,
        factor_id: str,
        factor_version: str,
        factor_artifact_path: str,
        factor_failure_conditions: list[Any] | None = None,
        strategy_decision: StrategyDecision | None = None,
    ) -> BacktestRequest:
        failure_conditions_payload: list[dict[str, Any]] = []
        for row in factor_failure_conditions or []:
            if hasattr(row, "model_dump"):
                failure_conditions_payload.append(row.model_dump(mode="json"))
            elif isinstance(row, dict):
                failure_conditions_payload.append(dict(row))
        constraints = {
            "plan_id": plan.plan_id,
            "experiment_id": strategy_spec.experiment_id,
            "strategy_family": strategy_spec.strategy_family,
            "rebalance": strategy_spec.rebalance,
            "lookback_days": strategy_spec.lookback_days,
            "signal_threshold": strategy_spec.signal_threshold,
            "position_sizing": strategy_spec.position_sizing,
            "risk_budget": strategy_spec.risk_budget,
            "max_position": strategy_spec.max_position,
            "execution_model": str(plan.constraints.get("execution_model", "next_open")),
            "factor_version": factor_version,
            "factor_id": factor_id,
            "factor_versions": [{"factor_id": factor_id, "version": factor_version}],
            "factor_artifact_path": factor_artifact_path,
            "failure_conditions": failure_conditions_payload,
            "strategy_decision": strategy_decision.model_dump(mode="json") if strategy_decision else strategy_spec.strategy_decision,
        }
        constraints.update(plan.constraints)
        constraints["circuit_breaker"] = strategy_spec.circuit_breaker.model_dump(mode="json")
        constraints["failure_regimes"] = list(strategy_spec.failure_regimes)
        if strategy_spec.circuit_breaker.rule.type == "drawdown":
            constraints["max_drawdown_target"] = float(strategy_spec.circuit_breaker.rule.threshold)
        return BacktestRequest(
            dataset_version=dataset_version,
            strategy_id=strategy_spec.strategy_id,
            strategy_version=strategy_spec.strategy_version,
            market=plan.markets[0],
            start=variant.start,
            end=variant.end,
            execution_model=str(constraints.get("execution_model", "next_open")),
            cost_model=variant.cost_model,
            factor_versions=[{"factor_id": factor_id, "version": factor_version}],
            constraints=constraints,
            evaluation_plan={
                "window": {"start": variant.start, "end": variant.end},
                "stress": ["high_cost", "regime_shift", "liquidity_shock"],
                "seed": plan.seed,
                "evidence_pack_id": str(evidence.evidence_pack_id),
                "evidence_refs": self._build_evidence_refs(evidence),
                "factor_id": factor_id,
                "factor_version": factor_version,
                "factor_versions": [{"factor_id": factor_id, "version": factor_version}],
                "factor_artifact_path": factor_artifact_path,
                "failure_conditions": failure_conditions_payload,
                "strategy_decision": strategy_decision.model_dump(mode="json") if strategy_decision else strategy_spec.strategy_decision,
            },
        )

    def _stage_paper_trade(
        self,
        plan: ResearchPlan,
        trace_id: str,
        steps: list[PipelineStep],
        enabled: bool,
        evidence_pack_id: str,
    ) -> dict[str, Any] | None:
        if not enabled:
            return None
        result = self.trading_service.place_paper_order(
            PaperOrderRequest(
                instrument_id=f"{plan.markets[0]}_DEMO",
                side="buy",
                quantity=100,
                order_type="market",
                plan_id=plan.plan_id,
                evidence_pack_id=evidence_pack_id,
            )
        )
        payload = {"accepted": result.accepted, "reason": result.reason, "mode": result.mode}
        steps.append(PipelineStep(name="paper.trade", status="done", summary=f"Paper order {result.reason}."))
        self._audit(trace_id, "pipeline.paper.done", payload)
        self._emit("task.progress", trace_id, {"stage": "paper.trade", "status": "done"})
        return payload

    def _build_evidence_pack(self, plan: ResearchPlan, trace_id: str) -> EvidencePack:
        combined_query = plan.question
        if plan.evidence_queries:
            combined_query = f"{combined_query}\n" + "\n".join(plan.evidence_queries[:3])
        evidence = self.knowledge.retrieve(query=combined_query, top_k=6)
        self._emit("audit.trace", trace_id, {"evidence_pack_id": str(evidence.evidence_pack_id), "plan_id": plan.plan_id})
        return evidence

    def _llm_plan_overlay(self, question: str, base: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        llm = self.llm_registry.get()
        section_draft = {
            "value": base.get("value", {}),
            "macro": base.get("macro", {}),
            "stats": base.get("stats", {}),
            "behavior": base.get("behavior", {}),
        }
        prompt = (
            "Return strict JSON only.\n"
            "Required fields:\n"
            "objectives(list[str]), constraints(dict), candidate_strategy_families(list[str]),\n"
            "value(dict), macro(dict), stats(dict), behavior(dict).\n"
            "Each of value/macro/stats/behavior must contain:\n"
            "hypotheses(list[str]), evidence_queries(list[str]), evaluation_actions(list[str]), risks(list[str]).\n"
            "question: "
            f"{question}\n"
            f"draft: {json.dumps({'objectives': base['objectives'], 'constraints': base['constraints'], 'sections': section_draft}, ensure_ascii=False)}"
        )
        response = llm.complete(prompt, max_tokens=520, temperature=0.1)
        payload = self._extract_json(response.content)
        if isinstance(payload, dict):
            return payload, response.mode
        return None, response.mode

    def _merge_plan_overlay(self, base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
        merged = dict(base)
        if isinstance(overlay.get("objectives"), list):
            merged["objectives"] = [str(item) for item in overlay["objectives"]][:6] or merged["objectives"]
        if isinstance(overlay.get("constraints"), dict):
            for key, value in overlay["constraints"].items():
                if isinstance(key, str):
                    merged["constraints"][key] = value
        if isinstance(overlay.get("candidate_strategy_families"), list):
            rows = [str(item) for item in overlay["candidate_strategy_families"] if str(item).strip()]
            if rows:
                merged["candidate_strategy_families"] = rows[:5]
        for section_name in ("value", "macro", "stats", "behavior"):
            section_value = overlay.get(section_name)
            if isinstance(section_value, dict):
                merged[section_name] = {
                    **dict(base.get(section_name) or {}),
                    **section_value,
                }
        return merged

    def _normalize_framework_sections(
        self,
        payload: dict[str, Any],
        *,
        question: str,
        market: str,
        profile: str,
    ) -> tuple[dict[str, Any], list[str]]:
        normalized = dict(payload)
        errors: list[str] = []
        defaults = self._framework_sections_template(profile=profile, question=question, market=market)
        for section_name in ("value", "macro", "stats", "behavior"):
            fallback = dict(defaults[section_name])
            raw = normalized.get(section_name)
            if not isinstance(raw, dict):
                errors.append(f"{section_name}: missing section object")
                normalized[section_name] = fallback
                continue
            section_rows: dict[str, list[str]] = {}
            for key in ("hypotheses", "evidence_queries", "evaluation_actions", "risks"):
                value = raw.get(key)
                if not isinstance(value, list):
                    errors.append(f"{section_name}.{key}: missing list")
                    section_rows[key] = list(fallback[key])
                    continue
                rows = [str(item).strip() for item in value if str(item).strip()]
                if not rows:
                    errors.append(f"{section_name}.{key}: empty list")
                    rows = list(fallback[key])
                section_rows[key] = rows
            normalized[section_name] = section_rows
        return normalized, errors

    def _interpret_results(
        self,
        plan: ResearchPlan,
        evidence: EvidencePack,
        experiments: list[ExperimentResult],
        *,
        response_language: Literal["en", "zh"] = "en",
    ) -> tuple[str, str]:
        llm = self.llm_registry.get()
        top = experiments[:3]
        payload = [
            {
                "variant_id": row.variant_id,
                "family": row.strategy_family,
                "sharpe": row.metrics.get("sharpe"),
                "mdd": row.metrics.get("max_drawdown"),
                "return": row.metrics.get("total_return"),
            }
            for row in top
        ]
        if response_language == "zh":
            prompt = (
                "Use concise Chinese in 3-5 lines: why first experiment wins, key risks, next iteration.\n"
                f"question: {plan.question}\n"
                f"objectives: {plan.objectives}\n"
                f"experiment_results: {json.dumps(payload, ensure_ascii=False)}\n"
                f"evidence_points: {evidence.key_points}\n"
            )
        else:
            prompt = (
                "Use concise English in 3-5 lines: why first experiment wins, key risks, next iteration.\n"
                f"question: {plan.question}\n"
                f"objectives: {plan.objectives}\n"
                f"experiment_results: {json.dumps(payload, ensure_ascii=False)}\n"
                f"evidence_points: {evidence.key_points}\n"
            )
        response = llm.complete(prompt, max_tokens=260, temperature=0.2)
        if response.content.strip():
            return response.content.strip(), response.mode
        top_one = top[0]
        if response_language == "zh":
            fallback = (
                f"最佳实验为 {top_one.variant_id}（{top_one.strategy_family}），目标评分最高。\n"
                "主要风险是交易成本上升与市场制度切换。\n"
                "下一步建议扩展样本外窗口，并在更高成本假设下重跑。"
            )
        else:
            fallback = (
                f"Top experiment {top_one.variant_id} ({top_one.strategy_family}) has the highest objective score.\n"
                "Main risks are cost escalation and market rule regime shifts.\n"
                "Next step: extend out-of-sample window and rerun under higher cost assumptions."
            )
        return fallback, response.mode

    def _comparison_table(self, experiments: list[ExperimentResult]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in experiments:
            rows.append(
                {
                    "variant_id": row.variant_id,
                    "strategy_family": row.strategy_family,
                    "run_id": row.run_id,
                    "factor_version": row.factor_version,
                    "factor_ic": row.factor_report.get("ic_mean"),
                    "factor_rank_ic": row.factor_report.get("rank_ic_mean"),
                    "sharpe": row.metrics.get("sharpe"),
                    "max_drawdown": row.metrics.get("max_drawdown"),
                    "total_return": row.metrics.get("total_return"),
                    "volatility": row.metrics.get("volatility"),
                    "objective_score": row.objective_score,
                }
            )
        return rows

    def _run_migration_preflight(self, plan: ResearchPlan) -> list[PreflightWarning]:
        market = str((plan.markets or ["US"])[0]).upper()
        if market not in {"US", "CN", "JP", "CRYPTO"}:
            return []
        rules = self.runner.market_rules.get(market)
        checker = MigrationChecker()
        warnings: list[PreflightWarning] = []
        seen: set[tuple[str, str]] = set()
        if market == "CN":
            notice = PreflightWarning(
                market=market,
                severity="warn",
                code="cn_microstructure_notice",
                title="CN market structure differs from US",
                explanation=(
                    "CN uses T+1 settlement for equities, enforces lot-size multiples (typically 100 shares), "
                    "and has fixed trading sessions. High-turnover setups need special handling."
                ),
                suggestion="Prefer daily/weekly rebalance, keep auto_round_lot enabled, and align run_time_utc with CN sessions.",
            )
            warnings.append(notice)
            seen.add(("", notice.code))

        turnover_threshold = float(plan.constraints.get("expected_turnover_threshold", 0.35) or 0.35)
        for variant in plan.experiment_matrix:
            factor_spec, _ = self._build_factor_spec(plan, variant)
            strategy_spec = self._build_strategy_spec(plan, variant, factor_version="preflight")
            strategy_payload = strategy_spec.model_dump(mode="json")
            strategy_payload["auto_round_lot"] = bool(plan.constraints.get("auto_round_lot", True))
            strategy_payload["run_time_utc"] = str(plan.constraints.get("run_time_utc", "16:00"))
            migration_warnings = checker.check(strategy_payload, market, rules)
            for item in migration_warnings:
                key = (variant.variant_id, item.code)
                if key in seen:
                    continue
                seen.add(key)
                severity = "block" if str(item.severity).lower() == "high" else "warn"
                warnings.append(
                    PreflightWarning(
                        market=market,
                        severity=severity,
                        code=item.code,
                        title=item.title,
                        explanation=item.explanation,
                        suggestion=self._preflight_suggestion(item.code, market),
                        variant_id=variant.variant_id,
                    )
                )

            if (
                market == "CN"
                and factor_spec.cost_sensitivity.level == CostSensitivityLevel.high
                and factor_spec.expected_horizon == ExpectedHorizon.intraday
            ):
                key = (variant.variant_id, "cn_t1_intraday_high_cost_factor")
                if key not in seen:
                    seen.add(key)
                    warnings.append(
                        PreflightWarning(
                            market=market,
                            severity="block",
                            code="cn_t1_intraday_high_cost_factor",
                            title="Intraday high-cost factor is risky in CN",
                            explanation=(
                                "Factor metadata indicates intraday horizon with high transaction-cost sensitivity. "
                                "Under CN T+1, same-day turnover is constrained; lot-size rounding and fixed sessions "
                                "can further increase slippage."
                            ),
                            suggestion=(
                                "Switch expected_horizon to swing or long_only, reduce turnover target, and rebalance at least daily."
                            ),
                            variant_id=variant.variant_id,
                        )
                    )

            expected_turnover = float(plan.constraints.get("expected_turnover", self._estimate_expected_turnover(variant)) or 0.0)
            if market == "CN" and expected_turnover > turnover_threshold:
                key = (variant.variant_id, "cn_expected_turnover_high")
                if key not in seen:
                    seen.add(key)
                    warnings.append(
                        PreflightWarning(
                            market=market,
                            severity="warn",
                            code="cn_expected_turnover_high",
                            title="Expected turnover may be too high for CN execution",
                            explanation=(
                                f"Estimated turnover {expected_turnover:.2f} exceeds threshold {turnover_threshold:.2f}. "
                                "With T+1 and lot-size constraints, realized cost may increase materially."
                            ),
                            suggestion="Increase rebalance interval, raise signal_threshold, or cap max_position to lower turnover.",
                            variant_id=variant.variant_id,
                        )
                    )
        return warnings

    def _preflight_suggestion(self, code: str, market: str) -> str:
        mapping = {
            "cn_t_plus_one_high_frequency": "Change rebalance from intraday/hourly to daily or weekly for CN T+1.",
            "lot_size_precision_mismatch": "Enable auto_round_lot or align target quantity to lot_size multiples.",
            "lot_size_rounding_impact": "Reduce max_position or use round-lot-aware sizing to minimize exposure drift.",
            "trading_session_coverage_gap": f"Adjust run_time_utc to {market} trading hours before order dispatch.",
        }
        return mapping.get(code, "Review market rules and adjust strategy constraints before running.")

    def _estimate_expected_turnover(self, variant: ExperimentVariant) -> float:
        rebalance_base = {
            "intraday": 1.0,
            "hourly": 0.75,
            "daily": 0.45,
            "weekly": 0.25,
            "biweekly": 0.15,
            "monthly": 0.08,
        }
        base = rebalance_base.get(str(variant.rebalance).lower(), 0.2)
        lookback_term = min(0.25, max(0.0, (20.0 - float(variant.lookback_days)) / 100.0))
        threshold_term = min(0.2, max(0.0, 0.01 - float(variant.signal_threshold)))
        return round(base + lookback_term + threshold_term, 4)

    def _apply_preflight_adjustments(self, plan: ResearchPlan, warnings: list[PreflightWarning]) -> list[str]:
        if not warnings:
            return []
        actions: list[str] = []
        by_variant = {row.variant_id: row for row in plan.experiment_matrix}
        for warn in warnings:
            if warn.severity != "block":
                continue
            if warn.code in {"cn_t_plus_one_high_frequency", "cn_t1_intraday_high_cost_factor"}:
                variant = by_variant.get(warn.variant_id or "")
                if variant is not None:
                    if str(variant.rebalance).lower() in {"intraday", "hourly"}:
                        old = variant.rebalance
                        variant.rebalance = "daily"
                        actions.append(f"{variant.variant_id}: rebalance {old} -> daily")
                    elif str(variant.rebalance).lower() == "daily":
                        variant.rebalance = "weekly"
                        actions.append(f"{variant.variant_id}: rebalance daily -> weekly")
                    if int(variant.lookback_days) <= 5:
                        old_lookback = variant.lookback_days
                        variant.lookback_days = 10
                        actions.append(f"{variant.variant_id}: lookback_days {old_lookback} -> 10")
                if str(plan.constraints.get("factor_expected_horizon", "")).lower() == "intraday":
                    plan.constraints["factor_expected_horizon"] = "swing"
                    actions.append("constraints.factor_expected_horizon intraday -> swing")
                if str(plan.constraints.get("factor_cost_sensitivity_level", "")).lower() == "high":
                    plan.constraints["factor_cost_sensitivity_level"] = "medium"
                    actions.append("constraints.factor_cost_sensitivity_level high -> medium")
                turnover = float(plan.constraints.get("expected_turnover", 0.0) or 0.0)
                if turnover > 0.0:
                    capped = round(min(turnover, 0.3), 4)
                    if capped < turnover:
                        plan.constraints["expected_turnover"] = capped
                        actions.append(f"constraints.expected_turnover {turnover:.2f} -> {capped:.2f}")
            if warn.code == "lot_size_precision_mismatch":
                if not bool(plan.constraints.get("auto_round_lot", True)):
                    plan.constraints["auto_round_lot"] = True
                    actions.append("constraints.auto_round_lot false -> true")
        return actions

    def _score_objective(self, metrics: dict[str, Any], objectives: list[str]) -> float:
        sharpe = float(metrics.get("sharpe", 0.0) or 0.0)
        mdd = float(metrics.get("max_drawdown", 0.0) or 0.0)
        ret = float(metrics.get("total_return", 0.0) or 0.0)
        turnover = float(metrics.get("turnover", 0.0) or 0.0)
        obj_text = " ".join(objectives).lower()
        score = sharpe * 1.4 + ret * 0.8 - mdd * 1.8 - turnover * 0.1
        if ("\u4f4e\u56de\u64a4" in obj_text) or ("drawdown" in obj_text):
            score -= mdd * 1.2
        if ("\u9ad8\u590f\u666e" in obj_text) or ("sharpe" in obj_text):
            score += sharpe * 0.5
        if "\u4e8b\u4ef6" in obj_text:
            score += ret * 0.3
        return round(score, 6)

    def _factor_weights(self, factors: list[FactorCandidate]) -> dict[str, float]:
        if not factors:
            return {"fallback": 1.0}
        w = round(1.0 / len(factors), 4)
        return {row.factor_id: w for row in factors}

    def _factor_id_for_strategy_family(self, family: str) -> str:
        key = family.lower()
        mapping = {
            "trend": "momentum_1d",
            "trend_with_vol_filter": "volatility",
            "mean_reversion": "mean_reversion",
            "value": "mean_reversion",
            "quality_value": "mean_reversion",
            "value_with_momentum_filter": "momentum_1d",
            "risk_parity": "volatility",
            "regime_allocation": "volatility",
            "defensive_carry": "carry_proxy",
        }
        return mapping.get(key, "intraday_return")

    def _detect_profile(self, question: str) -> str:
        text = question.lower()
        if any(key in text for key in ["\u8d8b\u52bf", "trend", "momentum", "breakout"]):
            return "trend"
        if any(key in text for key in ["\u4ef7\u503c", "value", "\u4f30\u503c", "pe", "pb"]):
            return "value"
        if any(
            key in text
            for key in ["\u98ce\u9669\u5e73\u4ef7", "\u914d\u7f6e", "\u80a1\u503a", "risk parity", "allocation"]
        ):
            return "allocation"
        return "general"

    def _infer_market(self, text: str) -> str:
        low = text.lower()
        if ("\u65e5\u7ecf" in text) or ("\u65e5\u672c" in text) or ("nikkei" in low):
            return "JP"
        if ("a\u80a1" in text) or ("\u6caa\u6df1" in text) or ("\u4e2d\u8bc1" in text):
            return "CN"
        if ("crypto" in low) or ("\u52a0\u5bc6" in text) or ("\u6bd4\u7279\u5e01" in text):
            return "CRYPTO"
        return "US"

    def _seed_from_question(self, question: str) -> int:
        return int(hashlib.sha1(question.encode("utf-8")).hexdigest()[:8], 16) % 100000

    def _plan_id(
        self, question: str, market: str, seed: int, objectives: list[str], constraints: dict[str, Any]
    ) -> str:
        payload = {"q": question, "m": market, "seed": seed, "obj": objectives, "cons": constraints}
        digest = hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        return f"plan_{digest}"

    def _extract_json(self, text: str) -> dict[str, Any] | None:
        if not text:
            return None
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return None
        try:
            loaded = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        return loaded if isinstance(loaded, dict) else None

    def _evidence_source_payload(self, source: Any) -> dict[str, Any]:
        return {
            "source_id": source.source_id,
            "title": source.title,
            "source_type": source.source_type,
            "uri": source.uri or source.url,
            "published_at": source.published_at.isoformat() if source.published_at else None,
            "timestamp": source.timestamp.isoformat() if source.timestamp else None,
            "snippet": source.snippet,
            "full_text_ref": source.full_text_ref,
            "credibility_score": source.credibility_score,
            "credibility_breakdown": source.credibility_breakdown,
        }

    def _build_evidence_refs(self, evidence: EvidencePack) -> list[str]:
        refs = [f"evidence_pack:{evidence.evidence_pack_id}"]
        for source in evidence.sources[:4]:
            refs.append(f"evidence_source:{source.source_id}")
        return refs

    def _market_rules_payload(self, market: str) -> dict[str, Any]:
        key = str(market or "US").upper()
        rules = self.runner.market_rules.get(key)
        return {
            "market": key,
            "t_plus_one": bool(rules.t_plus_one()),
            "lot_size": float(rules.lot_size()),
            "supports_fractional_qty": bool(rules.supports_fractional_qty()),
            "min_notional": float(rules.min_notional()),
            "is_24x7": bool(rules.is_24x7()),
        }

    def _framework_sections_template(self, *, profile: str, question: str, market: str) -> dict[str, dict[str, list[str]]]:
        base = {
            "value": {
                "hypotheses": [f"{market} valuation spread is mispriced for the current cycle."],
                "evidence_queries": [f"{market} valuation spread mean reversion evidence"],
                "evaluation_actions": ["Build value-vs-growth cohort test and compare forward returns."],
                "risks": ["Value trap risk under deteriorating fundamentals."],
            },
            "macro": {
                "hypotheses": [f"{market} macro liquidity and policy drive current return regime."],
                "evidence_queries": [f"{market} policy liquidity inflation growth surprise"],
                "evaluation_actions": ["Regime-split backtest by macro state and compare drawdown profile."],
                "risks": ["Policy shock or macro data revision risk."],
            },
            "stats": {
                "hypotheses": ["Observed alpha remains positive out-of-sample after cost assumptions."],
                "evidence_queries": ["factor IC rankIC decay OOS parameter sensitivity"],
                "evaluation_actions": ["Run IC/RankIC/decay/OOS plus perturbation grid."],
                "risks": ["Overfitting and unstable parameter sensitivity."],
            },
            "behavior": {
                "hypotheses": ["Crowding and narrative bias can reverse signal efficacy."],
                "evidence_queries": ["behavioral bias crowding narrative reversal counter-evidence"],
                "evaluation_actions": ["Add counter-evidence retrieval and challenge core assumptions."],
                "risks": ["Behavioral regime shifts causing fast signal decay."],
            },
        }
        if profile == "trend":
            base["value"]["hypotheses"] = [f"{market} trend winners are not yet overvalued enough to fade."]
            base["macro"]["hypotheses"] = [f"{market} macro liquidity supports medium-term trend persistence."]
            base["stats"]["hypotheses"] = ["Momentum signal keeps positive RankIC after cost stress."]
            base["behavior"]["hypotheses"] = ["Late-cycle crowding may trigger sharp trend reversals."]
        elif profile == "value":
            base["value"]["hypotheses"] = [f"{market} valuation discount can revert without severe earnings deterioration."]
            base["macro"]["hypotheses"] = [f"{market} macro slowdown risk is already partially priced in value names."]
            base["stats"]["hypotheses"] = ["Value+quality blend has lower turnover and stable OOS IC."]
            base["behavior"]["hypotheses"] = ["Narrative pessimism may create contrarian entry windows."]
        elif profile == "allocation":
            base["value"]["hypotheses"] = [f"{market} risk assets offer uneven valuation requiring balanced allocation."]
            base["macro"]["hypotheses"] = [f"{market} macro regime shifts dominate cross-asset allocation outcome."]
            base["stats"]["hypotheses"] = ["Risk-budget allocation keeps drawdown lower across regimes."]
            base["behavior"]["hypotheses"] = ["Panic/regret cycles can amplify correlation spikes."]
        return base

    def _profile_template(self, profile: str, question: str, market: str) -> dict[str, Any]:
        common_risk_checks = [
            "lookahead_bias_guard",
            "survivorship_bias_switch",
            "liquidity_feasibility",
            "limit_up_down_and_suspend",
        ]
        common_output = [
            "summary",
            "evidence",
            "factor_rationale",
            "strategy_spec",
            "backtest_comparison",
            "risk_explanation",
            "next_iteration",
        ]
        framework_sections = self._framework_sections_template(profile=profile, question=question, market=market)
        if profile == "trend":
            return {
                "objectives": ["high_sharpe", "trend_capture", "controlled_drawdown"],
                "constraints": {"max_drawdown_target": 0.1, "turnover_target": 0.35, "leverage_limit": 1.0},
                "evidence_queries": [
                    f"{market} market trend regime and volatility drivers",
                    f"{market} momentum factor stability paper",
                    "macro liquidity trend following risk",
                ],
                "candidate_factors": [
                    {
                        "factor_id": "price_momentum_60d",
                        "description": "60-day cross-sectional momentum",
                        "source": "market",
                        "availability_lag": "0s",
                        "rationale": "Capture medium-term trend persistence.",
                    },
                    {
                        "factor_id": "breakout_20d",
                        "description": "20-day breakout strength",
                        "source": "market",
                        "availability_lag": "0s",
                        "rationale": "Respond to regime acceleration windows.",
                    },
                    {
                        "factor_id": "news_sentiment_decay",
                        "description": "News sentiment with decay",
                        "source": "news",
                        "availability_lag": "2h",
                        "rationale": "Filter false breakouts with sentiment drift.",
                    },
                ],
                "candidate_strategy_families": ["trend", "trend_with_vol_filter", "mean_reversion"],
                "experiment_matrix": [
                    {
                        "variant_id": "trend_fast_weekly",
                        "strategy_family": "trend",
                        "rebalance": "weekly",
                        "lookback_days": 20,
                        "signal_threshold": 0.002,
                        "position_sizing": "vol_target",
                        "risk_budget": "vol_target_10pct",
                        "max_position": 0.16,
                        "cost_model": {"commission_bps": 5, "slippage_bps": 10},
                        "notes": "Fast trend capture with tighter threshold.",
                    },
                    {
                        "variant_id": "trend_mid_biweekly",
                        "strategy_family": "trend_with_vol_filter",
                        "rebalance": "biweekly",
                        "lookback_days": 60,
                        "signal_threshold": 0.001,
                        "position_sizing": "risk_budget",
                        "risk_budget": "vol_target_8pct",
                        "max_position": 0.14,
                        "cost_model": {"commission_bps": 5, "slippage_bps": 8},
                        "notes": "Balance signal persistence and transaction cost.",
                    },
                    {
                        "variant_id": "counter_meanrev_monthly",
                        "strategy_family": "mean_reversion",
                        "rebalance": "monthly",
                        "lookback_days": 15,
                        "signal_threshold": 0.003,
                        "position_sizing": "equal_risk",
                        "risk_budget": "vol_target_6pct",
                        "max_position": 0.1,
                        "cost_model": {"commission_bps": 4, "slippage_bps": 6},
                        "notes": "Counter-trend baseline for robustness comparison.",
                    },
                ],
                "risk_checks": common_risk_checks,
                "output_format": common_output,
                "planner_rationale": "Trend intent detected; run fast/mid/counter experiments.",
                **framework_sections,
            }
        if profile == "value":
            return {
                "objectives": ["valuation_reversion", "low_turnover", "defensive_drawdown"],
                "constraints": {"max_drawdown_target": 0.12, "turnover_target": 0.2, "leverage_limit": 0.9},
                "evidence_queries": [
                    f"{market} valuation spread and mean reversion evidence",
                    "earnings quality and value trap diagnostics",
                    "value factor crowding and cycle risk",
                ],
                "candidate_factors": [
                    {
                        "factor_id": "earnings_yield",
                        "description": "Inverse PE with profitability adjustment",
                        "source": "fundamental",
                        "availability_lag": "1d",
                        "rationale": "Core valuation anchor after publish lag.",
                    },
                    {
                        "factor_id": "quality_roe_margin",
                        "description": "ROE and margin stability blend",
                        "source": "fundamental",
                        "availability_lag": "1d",
                        "rationale": "Reduce value traps from weak balance sheets.",
                    },
                    {
                        "factor_id": "analyst_revision",
                        "description": "Earnings revision trend",
                        "source": "news",
                        "availability_lag": "4h",
                        "rationale": "Improve timing for value re-rating windows.",
                    },
                ],
                "candidate_strategy_families": ["value", "quality_value", "value_with_momentum_filter"],
                "experiment_matrix": [
                    {
                        "variant_id": "value_monthly_core",
                        "strategy_family": "value",
                        "rebalance": "monthly",
                        "lookback_days": 120,
                        "signal_threshold": 0.0,
                        "position_sizing": "score_weighted",
                        "risk_budget": "vol_target_8pct",
                        "max_position": 0.12,
                        "cost_model": {"commission_bps": 4, "slippage_bps": 5},
                        "notes": "Core value deployment with lower turnover.",
                    },
                    {
                        "variant_id": "quality_value_biweekly",
                        "strategy_family": "quality_value",
                        "rebalance": "biweekly",
                        "lookback_days": 90,
                        "signal_threshold": 0.001,
                        "position_sizing": "risk_budget",
                        "risk_budget": "vol_target_7pct",
                        "max_position": 0.1,
                        "cost_model": {"commission_bps": 4, "slippage_bps": 6},
                        "notes": "Defensive variant emphasizing earnings quality.",
                    },
                    {
                        "variant_id": "value_momo_overlay",
                        "strategy_family": "value_with_momentum_filter",
                        "rebalance": "weekly",
                        "lookback_days": 60,
                        "signal_threshold": 0.002,
                        "position_sizing": "equal_risk",
                        "risk_budget": "vol_target_9pct",
                        "max_position": 0.13,
                        "cost_model": {"commission_bps": 5, "slippage_bps": 8},
                        "notes": "Timing overlay to reduce early value entry.",
                    },
                ],
                "risk_checks": common_risk_checks,
                "output_format": common_output,
                "planner_rationale": "Value intent detected; prioritize lag-safe fundamentals and turnover control.",
                **framework_sections,
            }
        if profile == "allocation":
            return {
                "objectives": ["low_drawdown", "risk_parity_balance", "stable_sharpe"],
                "constraints": {"max_drawdown_target": 0.08, "turnover_target": 0.18, "leverage_limit": 1.2},
                "evidence_queries": [
                    "risk parity macro regime allocation evidence",
                    "equity bond correlation regime shift",
                    "drawdown control through volatility targeting",
                ],
                "candidate_factors": [
                    {
                        "factor_id": "macro_growth_surprise",
                        "description": "Growth surprise and inflation trend",
                        "source": "macro",
                        "availability_lag": "1d",
                        "rationale": "Define allocation regime transitions.",
                    },
                    {
                        "factor_id": "cross_asset_vol_ratio",
                        "description": "Equity-bond realized volatility ratio",
                        "source": "market",
                        "availability_lag": "0s",
                        "rationale": "Drive risk budget balancing across sleeves.",
                    },
                    {
                        "factor_id": "fx_liquidity_stress",
                        "description": "FX and liquidity stress proxy",
                        "source": "macro",
                        "availability_lag": "4h",
                        "rationale": "Reduce drawdown during shock regimes.",
                    },
                ],
                "candidate_strategy_families": ["risk_parity", "regime_allocation", "defensive_carry"],
                "experiment_matrix": [
                    {
                        "variant_id": "risk_parity_monthly",
                        "strategy_family": "risk_parity",
                        "rebalance": "monthly",
                        "lookback_days": 90,
                        "signal_threshold": 0.0,
                        "position_sizing": "inverse_vol",
                        "risk_budget": "vol_target_7pct",
                        "max_position": 0.22,
                        "cost_model": {"commission_bps": 3, "slippage_bps": 4},
                        "notes": "Baseline low-drawdown allocation sleeve.",
                    },
                    {
                        "variant_id": "regime_weekly_guarded",
                        "strategy_family": "regime_allocation",
                        "rebalance": "weekly",
                        "lookback_days": 45,
                        "signal_threshold": 0.001,
                        "position_sizing": "risk_budget",
                        "risk_budget": "vol_target_8pct",
                        "max_position": 0.2,
                        "cost_model": {"commission_bps": 4, "slippage_bps": 6},
                        "notes": "Faster regime adaptation with defensive cap.",
                    },
                    {
                        "variant_id": "carry_defensive_biweekly",
                        "strategy_family": "defensive_carry",
                        "rebalance": "biweekly",
                        "lookback_days": 60,
                        "signal_threshold": 0.0015,
                        "position_sizing": "equal_risk",
                        "risk_budget": "vol_target_6pct",
                        "max_position": 0.18,
                        "cost_model": {"commission_bps": 4, "slippage_bps": 7},
                        "notes": "Carry-style defensive allocation benchmark.",
                    },
                ],
                "risk_checks": common_risk_checks,
                "output_format": common_output,
                "planner_rationale": "Allocation intent detected; emphasize drawdown and regime checks.",
                **framework_sections,
            }
        return {
            "objectives": ["balanced_alpha", "controlled_drawdown", "cost_awareness"],
            "constraints": {"max_drawdown_target": 0.1, "turnover_target": 0.3, "leverage_limit": 1.0},
            "evidence_queries": [
                f"{market} volatility drivers and policy expectations",
                "multi-factor robustness and cost sensitivity",
                "behavioral risk and narrative reversal",
            ],
            "candidate_factors": [
                {
                    "factor_id": "momentum_40d",
                    "description": "Intermediate trend signal",
                    "source": "market",
                    "availability_lag": "0s",
                    "rationale": "Capture trend persistence.",
                },
                {
                    "factor_id": "valuation_quality_blend",
                    "description": "Value and quality mix",
                    "source": "fundamental",
                    "availability_lag": "1d",
                    "rationale": "Improve medium-term robustness.",
                },
                {
                    "factor_id": "macro_liquidity_shift",
                    "description": "Macro and liquidity regime proxy",
                    "source": "macro",
                    "availability_lag": "1d",
                    "rationale": "Control tail-risk episodes.",
                },
            ],
            "candidate_strategy_families": ["trend", "value", "risk_parity"],
            "experiment_matrix": [
                {
                    "variant_id": "balanced_trend",
                    "strategy_family": "trend",
                    "rebalance": "weekly",
                    "lookback_days": 40,
                    "signal_threshold": 0.001,
                    "position_sizing": "risk_budget",
                    "risk_budget": "vol_target_9pct",
                    "max_position": 0.14,
                    "cost_model": {"commission_bps": 5, "slippage_bps": 8},
                    "notes": "Trend anchor in blended objective setting.",
                },
                {
                    "variant_id": "balanced_value",
                    "strategy_family": "value",
                    "rebalance": "monthly",
                    "lookback_days": 120,
                    "signal_threshold": 0.0,
                    "position_sizing": "score_weighted",
                    "risk_budget": "vol_target_8pct",
                    "max_position": 0.12,
                    "cost_model": {"commission_bps": 4, "slippage_bps": 6},
                    "notes": "Value anchor with lower turnover baseline.",
                },
                {
                    "variant_id": "balanced_risk_parity",
                    "strategy_family": "risk_parity",
                    "rebalance": "biweekly",
                    "lookback_days": 60,
                    "signal_threshold": 0.001,
                    "position_sizing": "inverse_vol",
                    "risk_budget": "vol_target_7pct",
                    "max_position": 0.18,
                    "cost_model": {"commission_bps": 4, "slippage_bps": 6},
                    "notes": "Risk balancing benchmark for drawdown control.",
                },
            ],
            "risk_checks": common_risk_checks,
            "output_format": common_output,
            "planner_rationale": "General intent detected; diversify hypotheses across families.",
            **framework_sections,
        }

    def _audit(self, trace_id: str, event_type: str, payload: dict[str, Any], run_id: UUID | None = None) -> None:
        self.audit_store.append(AuditLogEntry(trace_id=UUID(trace_id), run_id=run_id, event_type=event_type, payload=payload))

    def _emit(self, event_type: str, trace_id: str, payload: dict[str, Any]) -> None:
        event_bus.publish(event_type=event_type, trace_id=trace_id, payload=payload, session_id="pipeline")
