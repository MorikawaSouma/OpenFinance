from fastapi.testclient import TestClient

from openfinance.agents.counterfactual import CounterfactualQueryGenerator
from openfinance.api.main import app
from openfinance.core.config import settings
from openfinance.knowledge.evidence import EvidencePack, EvidenceSource


def _with_stub_llm() -> tuple[bool, str]:
    original_force_stub = settings.llm_force_stub
    original_api_key = settings.zhipu_api_key
    settings.llm_force_stub = True
    settings.zhipu_api_key = ""
    return original_force_stub, original_api_key


def _restore_llm(original: tuple[bool, str]) -> None:
    settings.llm_force_stub, settings.zhipu_api_key = original


def test_pr27_counterfactual_query_generator_returns_three_categories() -> None:
    generator = CounterfactualQueryGenerator()
    pack = EvidencePack(
        query="US growth and liquidity regime",
        sources=[
            EvidenceSource(
                source_id="s1",
                title="Liquidity and Risk Asset Reversal",
                uri="https://example.com/s1",
                snippet="Liquidity-driven reversals can invalidate trend narratives.",
            )
        ],
    )
    rows = generator.generate(
        initial_conclusion="Should keep full risk-on because trend is strong.",
        evidence_pack=pack,
        question="US equity trend allocation",
    )
    assert len(rows) == 3
    categories = {row.category for row in rows}
    assert categories == {"counterexample_event", "alternative_explanation", "bias_data_check"}
    assert all(row.query.strip() for row in rows)


def test_pr27_kahneman_outputs_counterfactual_fields_non_empty() -> None:
    client = TestClient(app)
    llm_state = _with_stub_llm()
    try:
        evidence = client.get(
            "/knowledge/evidence/mock",
            params={"query": "macro liquidity inflation risk sentiment", "top_k": 8},
        )
        assert evidence.status_code == 200
        pack = evidence.json()

        resp = client.post(
            "/orchestrator/run",
            json={
                "question": "当前上涨是否只是叙事驱动，请主动找反证并修正建议。",
                "active_agents": ["Kahneman"],
                "evidence_pack_id": pack["evidence_pack_id"],
                "developer_mode": True,
                "research_top_k": 8,
            },
        )
        assert resp.status_code == 200
        out = resp.json()["outputs"][0]
        assert len(out.get("counter_evidence_refs") or []) >= 1
        assert len(out.get("challenged_assumptions") or []) >= 1
        revised = str(out.get("revised_recommendation") or "")
        assert revised
        assert "置信度" in revised
        assert "->" in revised
    finally:
        _restore_llm(llm_state)
