from pathlib import Path

from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.core.config import settings
from openfinance.external_adapters.base import ExternalNewsItem, NewsProviderBase
from openfinance.external_adapters.mock import MockMacroProvider, MockNewsProvider
from openfinance.knowledge.rag import HybridRetriever, LocalCorpusRetriever
from openfinance.knowledge.service import build_default_knowledge_service


class CustomNewsProvider(NewsProviderBase):
    provider_name = "custom-news"

    def search(self, query: str, limit: int = 5) -> list[ExternalNewsItem]:
        rows: list[ExternalNewsItem] = []
        base_ts = MockNewsProvider().search(query, limit=1)[0].timestamp
        for i in range(max(1, limit)):
            rows.append(
                ExternalNewsItem(
                    item_id=f"custom_{i + 1}",
                    headline=f"Custom feed on {query}",
                    source="CustomNewsLab",
                    timestamp=base_ts,
                    url=f"https://custom.news/{i + 1}",
                    summary="Custom adapter output for interface compatibility test.",
                )
            )
        return rows


def test_mock_providers_generate_structured_items() -> None:
    news = MockNewsProvider().search("macro liquidity policy", limit=3)
    macro = MockMacroProvider().search("macro liquidity policy", limit=2)
    assert len(news) == 3
    assert len(macro) == 2
    for row in [*news, *macro]:
        assert row.headline
        assert row.source
        assert row.url.startswith("https://")
        assert row.summary
        assert row.timestamp.tzinfo is not None


def test_hybrid_retriever_mixes_local_and_external_sources() -> None:
    corpus_dir = Path(__file__).resolve().parents[1] / "resources" / "corpus"
    hybrid = HybridRetriever(local_retriever=LocalCorpusRetriever(corpus_dir=corpus_dir))
    pack = hybrid.retrieve_evidence_pack("macro volatility policy drawdown", top_k=6)
    assert len(pack.sources) >= 4
    assert any(source.source_id.startswith("mock_news:") for source in pack.sources)
    assert any(source.source_id.startswith("mock_macro:") for source in pack.sources)
    assert all(source.url for source in pack.sources)
    assert all(source.timestamp for source in pack.sources)


def test_provider_is_swappable_without_changing_upper_layer() -> None:
    service = build_default_knowledge_service(
        news_provider=CustomNewsProvider(),
        macro_provider=MockMacroProvider(),
    )
    pack = service.retrieve("macro policy risk rates inflation", top_k=8)
    assert any(source.source_id.startswith("mock_news:custom_") for source in pack.sources)
    assert any(source.source_id.startswith("mock_") for source in pack.sources)


def test_orchestrator_can_cite_external_sources_offline() -> None:
    client = TestClient(app)
    original_force_stub = settings.llm_force_stub
    original_api_key = settings.zhipu_api_key
    settings.llm_force_stub = True
    settings.zhipu_api_key = ""
    try:
        evidence = client.get("/knowledge/evidence/mock", params={"query": "macro liquidity policy rates", "top_k": 6})
        assert evidence.status_code == 200
        pack = evidence.json()
        assert any(str(row["source_id"]).startswith("mock_") for row in pack["sources"])

        response = client.post(
            "/orchestrator/run",
            json={
                "question": "高利率和流动性收紧下如何做风险预算？",
                "active_agents": ["Buffett", "Soros"],
                "evidence_pack_id": pack["evidence_pack_id"],
                "developer_mode": True,
            },
        )
        assert response.status_code == 200
        outputs = response.json()["outputs"]
        cited_ids = {
            cite["source_id"]
            for out in outputs
            for cite in out.get("citations", [])
            if isinstance(cite, dict) and "source_id" in cite
        }
        assert any(str(row).startswith("mock_") for row in cited_ids)
    finally:
        settings.llm_force_stub = original_force_stub
        settings.zhipu_api_key = original_api_key
