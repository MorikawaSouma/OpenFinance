from dataclasses import dataclass

from openfinance.knowledge.evidence import EvidencePack


@dataclass(frozen=True)
class CounterfactualQuery:
    category: str
    query: str
    rationale: str


class CounterfactualQueryGenerator:
    """Generate structured disconfirmation queries from current thesis and evidence."""

    def generate(
        self,
        *,
        initial_conclusion: str,
        evidence_pack: EvidencePack | None,
        question: str,
    ) -> list[CounterfactualQuery]:
        topic = self._topic(question=question, initial_conclusion=initial_conclusion, evidence_pack=evidence_pack)
        return [
            CounterfactualQuery(
                category="counterexample_event",
                query=(
                    f"{topic} 反例事件 同类资产 相反走势 原因 "
                    "opposite move case study drawdown trigger"
                ),
                rationale="Search for same-asset-class episodes with opposite price action.",
            ),
            CounterfactualQuery(
                category="alternative_explanation",
                query=(
                    f"{topic} 替代解释 宏观 流动性 制度 "
                    "alternative explanation macro liquidity policy regime shift"
                ),
                rationale="Probe non-primary explanations such as policy or liquidity changes.",
            ),
            CounterfactualQuery(
                category="bias_data_check",
                query=(
                    f"{topic} 数据偏差 幸存者偏差 选择偏差 回看偏差 "
                    "survivorship bias selection bias data revision lookahead"
                ),
                rationale="Stress-test the thesis against data and sampling bias risks.",
            ),
        ]

    def _topic(self, *, question: str, initial_conclusion: str, evidence_pack: EvidencePack | None) -> str:
        q = (question or "").strip()
        if q:
            return q[:120]
        c = (initial_conclusion or "").strip()
        if c:
            return c[:120]
        if evidence_pack and evidence_pack.sources:
            return evidence_pack.sources[0].title[:120]
        return "market thesis"
