from pathlib import Path

from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.knowledge.memory import (
    InMemoryEpisodicMemory,
    InMemoryProjectMemory,
    InMemorySemanticMemory,
)
from openfinance.knowledge.rag import LocalCorpusRetriever
from openfinance.knowledge.service import build_default_knowledge_service


def test_local_corpus_retriever_diff_query() -> None:
    corpus_dir = Path(__file__).resolve().parents[1] / "resources" / "corpus"
    retriever = LocalCorpusRetriever(corpus_dir=corpus_dir)
    assert len(retriever.docs) >= 5

    trend_pack = retriever.retrieve_evidence_pack("trend strategy high sharpe", top_k=3)
    value_pack = retriever.retrieve_evidence_pack("value strategy low turnover", top_k=3)
    assert len(trend_pack.sources) >= 2
    assert len(value_pack.sources) >= 2
    trend_ids = {row.source_id for row in trend_pack.sources}
    value_ids = {row.source_id for row in value_pack.sources}
    assert trend_ids != value_ids
    for source in trend_pack.sources + value_pack.sources:
        assert source.full_text_ref
        assert source.uri or source.url


def test_knowledge_service_persistence() -> None:
    service = build_default_knowledge_service()
    pack = service.retrieve("risk parity allocation drawdown control", top_k=4)
    found = service.get_pack(str(pack.evidence_pack_id))
    assert found is not None
    assert found.query == pack.query
    listed = service.list_packs(limit=20)
    assert any(item["id"] == str(pack.evidence_pack_id) for item in listed)


def test_memory_stubs() -> None:
    semantic = InMemorySemanticMemory()
    episodic = InMemoryEpisodicMemory()
    project = InMemoryProjectMemory()
    semantic.save_preference("risk", "medium")
    episodic.append_episode("ran backtest v1")
    project.save_project_note("ship PR5")
    assert semantic.get_preference("risk") == "medium"
    assert episodic.list_episodes() == ["ran backtest v1"]
    assert project.list_project_notes() == ["ship PR5"]


def test_knowledge_route() -> None:
    client = TestClient(app)
    response = client.get("/knowledge/evidence/mock", params={"query": "macro volatility"})
    assert response.status_code == 200
    payload = response.json()
    assert "evidence_pack_id" in payload
    assert payload["query"]
    assert len(payload["sources"]) >= 2
    assert all(row.get("full_text_ref") for row in payload["sources"])
    assert "credibility_breakdown" in payload
    assert payload["credibility_breakdown"].get("aggregate") is not None
    for row in payload["sources"]:
        assert "credibility_breakdown" in row
        assert "hard_signals" in row["credibility_breakdown"]

    list_resp = client.get("/knowledge/evidence/packs")
    assert list_resp.status_code == 200
    rows = list_resp.json()
    assert len(rows) >= 1
    pack_id = rows[0]["id"]
    assert "credibility_breakdown" in rows[0]

    detail_resp = client.get(f"/knowledge/evidence/packs/{pack_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["evidence_pack_id"] == pack_id
    assert "credibility_breakdown" in detail
