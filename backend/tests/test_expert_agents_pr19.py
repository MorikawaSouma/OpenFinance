from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.core.config import settings


def _orchestrator_payload(question: str, evidence_pack_id: str) -> dict:
    return {
        "question": question,
        "active_agents": ["Buffett", "Soros"],
        "evidence_pack_id": evidence_pack_id,
        "market_context": {"market": "US"},
        "constraints": {"max_drawdown_target": 0.1},
        "developer_mode": True,
    }


def _with_stub_llm() -> tuple[bool, str]:
    original_force_stub = settings.llm_force_stub
    original_api_key = settings.zhipu_api_key
    settings.llm_force_stub = True
    settings.zhipu_api_key = ""
    return original_force_stub, original_api_key


def _restore_llm(original: tuple[bool, str]) -> None:
    settings.llm_force_stub, settings.zhipu_api_key = original


def test_pr19_orchestrator_outputs_structured_citations() -> None:
    client = TestClient(app)
    llm_state = _with_stub_llm()
    try:
        evidence = client.get("/knowledge/evidence/mock", params={"query": "macro liquidity inflation risk parity", "top_k": 6})
        assert evidence.status_code == 200
        pack = evidence.json()
        assert len(pack["sources"]) >= 2

        resp = client.post("/orchestrator/run", json=_orchestrator_payload("高利率环境下如何做资产配置", pack["evidence_pack_id"]))
        assert resp.status_code == 200
        payload = resp.json()
        assert len(payload["outputs"]) == 2

        for output in payload["outputs"]:
            assert output["claim"]
            assert len(output["rationale"]) >= 1
            assert len(output["uncertainty"]) >= 1
            assert len(output["citations"]) >= 1
            assert output["prompt_used"]
            assert output["raw_response"] is not None
            for cite in output["citations"]:
                assert cite["title"]
                assert "timestamp" in cite
    finally:
        _restore_llm(llm_state)


def test_pr19_three_questions_not_static_and_cross_agent_refs_diverge() -> None:
    client = TestClient(app)
    llm_state = _with_stub_llm()
    try:
        questions = [
            "美股价值风格在高利率下如何控制回撤？",
            "日元波动放大时，宏观资金应如何管理风险预算？",
            "因子衰减和成本上升时，模型应如何迭代？",
        ]
        buffett_claims: set[str] = set()
        soros_claims: set[str] = set()

        for question in questions:
            evidence = client.get("/knowledge/evidence/mock", params={"query": question, "top_k": 6})
            assert evidence.status_code == 200
            pack_id = evidence.json()["evidence_pack_id"]

            resp = client.post("/orchestrator/run", json=_orchestrator_payload(question, pack_id))
            assert resp.status_code == 200
            outputs = {row["agent_name"]: row for row in resp.json()["outputs"]}
            assert {"Buffett", "Soros"}.issubset(outputs.keys())

            buffett = outputs["Buffett"]
            soros = outputs["Soros"]
            buffett_claims.add(buffett["claim"])
            soros_claims.add(soros["claim"])

            buffett_sources = {row["source_id"] for row in buffett.get("citations", [])}
            soros_sources = {row["source_id"] for row in soros.get("citations", [])}
            assert buffett_sources
            assert soros_sources
            assert buffett_sources != soros_sources

        assert len(buffett_claims) >= 2
        assert len(soros_claims) >= 2
    finally:
        _restore_llm(llm_state)

