from openfinance.agents.base import BaseAgent
from openfinance.agents.experts import (
    BuffettAgent,
    DalioAgent,
    FactorAgent,
    KahnemanAgent,
    SimonsAgent,
    SorosAgent,
)
from openfinance.agents.schemas import AgentCitation, AgentOutput, AgentTaskInput
from openfinance.knowledge.service import KnowledgeService
from openfinance.llm.provider import LLMProvider, LLMProviderRegistry, ZhipuGLM47Provider


def _build_default_provider() -> LLMProvider:
    registry = LLMProviderRegistry()
    registry.register(ZhipuGLM47Provider(), is_default=True)
    return registry.get()


class _HeuristicOpsAgent(BaseAgent):
    def __init__(self, name: str, focus: str, style: str, keywords: tuple[str, ...]) -> None:
        self.name = name
        self.model = f"ops-{name.lower()}-heuristic-v1"
        self._focus = focus
        self._style = style
        self._keywords = keywords

    def run(self, task: AgentTaskInput) -> AgentOutput:
        sources = list(task.evidence_pack.sources) if task.evidence_pack else []
        chosen = sources[:2]
        refs = [row.source_id for row in chosen]
        citations = [
            AgentCitation(
                source_id=row.source_id,
                title=row.title,
                timestamp=(row.timestamp or row.published_at).isoformat() if (row.timestamp or row.published_at) else "n/a",
                uri=row.uri or row.url,
            )
            for row in chosen
        ]
        claim = (
            f"{self.name}结论: 在{self._focus}视角下，先满足约束再执行。"
            if refs
            else f"{self.name}结论: 证据不足，先补齐可追溯来源后再执行。"
        )
        rationale = [
            f"问题: {task.question[:80]}",
            f"执行风格: {self._style}",
        ]
        if refs:
            rationale.append(f"已引用证据: {', '.join(refs)}")
        uncertainty = ["需要更多跨市场样本验证当前判断。"]
        return AgentOutput(
            agent_name=self.name,
            claim=claim,
            rationale=rationale,
            uncertainty=uncertainty,
            evidence_refs=refs,
            citations=citations,
            confidence=0.56 if refs else 0.42,
        )


def _ops_agent(name: str, focus: str, style: str, keywords: tuple[str, ...]) -> BaseAgent:
    return _HeuristicOpsAgent(name=name, focus=focus, style=style, keywords=keywords)


def build_default_agents(knowledge_service: KnowledgeService | None = None) -> dict[str, BaseAgent]:
    llm = _build_default_provider()
    return {
        "Buffett": BuffettAgent(llm),
        "Soros": SorosAgent(llm),
        "Simons": SimonsAgent(llm),
        "Dalio": DalioAgent(llm),
        "Kahneman": KahnemanAgent(llm, knowledge_service=knowledge_service),
        "Factor": FactorAgent(llm),
        "Librarian": _ops_agent(
            name="Librarian",
            focus="source coverage, citation quality, and chronology checks",
            style="evidence-first indexing",
            keywords=("source", "citation", "timestamp", "coverage", "证据", "引用"),
        ),
        "DataEngineer": _ops_agent(
            name="DataEngineer",
            focus="data quality, schema assumptions, and lineage constraints",
            style="data contracts before modeling",
            keywords=("data", "schema", "missing", "lineage", "质量", "缺失"),
        ),
        "RiskManager": _ops_agent(
            name="RiskManager",
            focus="drawdown guardrails, leverage limits, and rejection reasons",
            style="fail-safe controls",
            keywords=("risk", "drawdown", "limit", "leverage", "风险", "回撤", "约束"),
        ),
        "ExecutionTrader": _ops_agent(
            name="ExecutionTrader",
            focus="execution feasibility, slippage, and cost-aware order intent",
            style="execution realism over theoretical edge",
            keywords=("execution", "slippage", "commission", "liquidity", "成交", "滑点"),
        ),
        "ComplianceAudit": _ops_agent(
            name="ComplianceAudit",
            focus="traceability, approval gates, and audit completeness",
            style="policy and audit constraints",
            keywords=("approval", "audit", "trace", "policy", "审批", "审计"),
        ),
        "Strategy": _ops_agent(
            name="Strategy",
            focus="strategy synthesis under objective and constraint tradeoffs",
            style="objective-aligned portfolio decisions",
            keywords=("strategy", "objective", "tradeoff", "variant", "策略", "目标"),
        ),
        "Code": _ops_agent(
            name="Code",
            focus="implementation feasibility, testing scope, and reproducibility",
            style="deterministic execution plan",
            keywords=("implementation", "test", "reproduce", "version", "实现", "测试"),
        ),
    }
