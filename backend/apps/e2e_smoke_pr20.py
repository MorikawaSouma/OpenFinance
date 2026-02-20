from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.core.config import settings


def main() -> None:
    client = TestClient(app)
    original_force_stub = settings.llm_force_stub
    original_api_key = settings.zhipu_api_key
    settings.llm_force_stub = True
    settings.zhipu_api_key = ""

    try:
        evidence = client.get("/knowledge/evidence/mock", params={"query": "macro policy liquidity valuation", "top_k": 6})
        evidence.raise_for_status()
        pack = evidence.json()
        sources = pack["sources"]
        assert len(sources) >= 4, "expected mixed retrieval sources"
        assert any(str(row["source_id"]).startswith("mock_news:") for row in sources), "missing mock news sources"
        assert any(str(row["source_id"]).startswith("mock_macro:") for row in sources), "missing mock macro sources"
        assert all(row.get("url") for row in sources), "all evidence sources must contain url"
        assert all(row.get("timestamp") for row in sources), "all evidence sources must contain timestamp"

        orch = client.post(
            "/orchestrator/run",
            json={
                "question": "当前宏观环境下如何做稳健配置？",
                "active_agents": ["Buffett", "Soros"],
                "evidence_pack_id": pack["evidence_pack_id"],
                "developer_mode": True,
            },
        )
        orch.raise_for_status()
        outputs = orch.json()["outputs"]
        cited = {
            cite["source_id"]
            for out in outputs
            for cite in out.get("citations", [])
            if isinstance(cite, dict) and "source_id" in cite
        }
        assert any(str(row).startswith("mock_") for row in cited), "experts should cite external mock sources"

        print("PR20 smoke passed.")
        print(f"source_count={len(sources)} cited_external={len([x for x in cited if str(x).startswith('mock_')])}")
    finally:
        settings.llm_force_stub = original_force_stub
        settings.zhipu_api_key = original_api_key


if __name__ == "__main__":
    main()

