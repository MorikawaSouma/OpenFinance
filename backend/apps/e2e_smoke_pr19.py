from pathlib import Path

from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.core.config import settings


def main() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    corpus_dir = backend_root / "resources" / "corpus"
    corpus_files = sorted(list(corpus_dir.glob("*.md")) + list(corpus_dir.glob("*.txt")))
    assert len(corpus_files) >= 10, f"expected >=10 corpus docs, got {len(corpus_files)}"

    client = TestClient(app)
    original_force_stub = settings.llm_force_stub
    original_api_key = settings.zhipu_api_key
    settings.llm_force_stub = True
    settings.zhipu_api_key = ""

    try:
        questions = [
            "美股价值风格在高利率下如何控制回撤？",
            "日元波动上行时，宏观交易应如何管理风险预算？",
            "因子衰减和交易成本上升时，策略应如何调整？",
        ]
        buffett_claims: set[str] = set()
        soros_claims: set[str] = set()

        for question in questions:
            evidence = client.get("/knowledge/evidence/mock", params={"query": question, "top_k": 6})
            evidence.raise_for_status()
            pack = evidence.json()

            response = client.post(
                "/orchestrator/run",
                json={
                    "question": question,
                    "active_agents": ["Buffett", "Soros"],
                    "evidence_pack_id": pack["evidence_pack_id"],
                    "market_context": {"market": "US"},
                    "constraints": {"max_drawdown_target": 0.1},
                    "developer_mode": True,
                },
            )
            response.raise_for_status()
            outputs = {row["agent_name"]: row for row in response.json()["outputs"]}
            assert {"Buffett", "Soros"}.issubset(outputs.keys())

            buffett = outputs["Buffett"]
            soros = outputs["Soros"]
            buffett_claims.add(buffett["claim"])
            soros_claims.add(soros["claim"])

            buffett_refs = {row["source_id"] for row in buffett.get("citations", [])}
            soros_refs = {row["source_id"] for row in soros.get("citations", [])}
            assert buffett_refs, "Buffett citations cannot be empty"
            assert soros_refs, "Soros citations cannot be empty"
            assert buffett_refs != soros_refs, "Buffett and Soros must cite different sources"

        assert len(buffett_claims) >= 2, "Buffett output looks static/repeated"
        assert len(soros_claims) >= 2, "Soros output looks static/repeated"
        print("PR19 smoke passed.")
        print(f"corpus_docs={len(corpus_files)}")
        print(f"buffett_unique_claims={len(buffett_claims)} soros_unique_claims={len(soros_claims)}")
    finally:
        settings.llm_force_stub = original_force_stub
        settings.zhipu_api_key = original_api_key


if __name__ == "__main__":
    main()

