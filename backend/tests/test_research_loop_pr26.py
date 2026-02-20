from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.core.config import settings


def _with_stub_llm() -> tuple[bool, str]:
    original_force_stub = settings.llm_force_stub
    original_api_key = settings.zhipu_api_key
    settings.llm_force_stub = True
    settings.zhipu_api_key = ""
    return original_force_stub, original_api_key


def _restore_llm(original: tuple[bool, str]) -> None:
    settings.llm_force_stub, settings.zhipu_api_key = original


def _steps_by_type(steps: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for step in steps:
        step_type = str(step.get("step_type") or "")
        if step_type and step_type not in out:
            out[step_type] = step
    return out


def test_pr26_reasoning_trace_includes_forced_counter_loop() -> None:
    client = TestClient(app)
    llm_state = _with_stub_llm()
    try:
        evidence = client.get("/knowledge/evidence/mock", params={"query": "macro liquidity policy rates inflation", "top_k": 8})
        assert evidence.status_code == 200
        pack = evidence.json()

        resp = client.post(
            "/orchestrator/run",
            json={
                "question": "高利率环境下资产配置如何控制回撤并避免叙事偏差？",
                "active_agents": ["Buffett", "Soros", "Dalio", "Simons", "Kahneman"],
                "evidence_pack_id": pack["evidence_pack_id"],
                "developer_mode": True,
                "research_top_k": 8,
            },
        )
        assert resp.status_code == 200
        outputs = resp.json()["outputs"]
        assert len(outputs) == 5

        for out in outputs:
            trace = out.get("reasoning_trace") or {}
            steps = trace.get("steps") or []
            assert len(steps) >= 4
            steps_map = _steps_by_type(steps)

            assert "hypothesis" in steps_map
            assert "evidence_search" in steps_map
            assert "counterevidence_search" in steps_map
            assert "revision" in steps_map
            assert "decision" in steps_map

            evidence_query = str(steps_map["evidence_search"].get("query") or "")
            counter_query = str(steps_map["counterevidence_search"].get("query") or "")
            assert evidence_query
            assert counter_query
            assert evidence_query != counter_query

            evidence_refs = set(steps_map["evidence_search"].get("evidence_refs") or [])
            counter_refs = set(steps_map["counterevidence_search"].get("evidence_refs") or [])
            assert evidence_refs
            assert counter_refs
            assert evidence_refs != counter_refs

            revision = str(steps_map["revision"].get("output_summary") or "")
            assert "修正" in revision
            assert isinstance(steps_map["revision"].get("confidence_delta"), (int, float))
    finally:
        _restore_llm(llm_state)


def test_pr26_kahneman_trace_must_show_active_counterevidence_search() -> None:
    client = TestClient(app)
    llm_state = _with_stub_llm()
    try:
        evidence = client.get("/knowledge/evidence/mock", params={"query": "behavioral finance narrative reversal risk", "top_k": 8})
        assert evidence.status_code == 200
        pack = evidence.json()

        resp = client.post(
            "/orchestrator/run",
            json={
                "question": "这轮市场上涨是否只是叙事驱动？请主动找反证。",
                "active_agents": ["Kahneman"],
                "evidence_pack_id": pack["evidence_pack_id"],
                "developer_mode": True,
                "research_top_k": 8,
            },
        )
        assert resp.status_code == 200
        output = resp.json()["outputs"][0]
        steps = (output.get("reasoning_trace") or {}).get("steps") or []
        steps_map = _steps_by_type(steps)
        assert "counterevidence_search" in steps_map

        counter_step = steps_map["counterevidence_search"]
        counter_query = str(counter_step.get("query") or "").lower()
        assert counter_query
        assert any(token in counter_query for token in ["counter", "disconfirm", "opposite", "反证"])
        assert len(counter_step.get("evidence_refs") or []) >= 1
    finally:
        _restore_llm(llm_state)


def test_pr26_reasoning_trace_persisted_in_plan_tool_context() -> None:
    client = TestClient(app)
    llm_state = _with_stub_llm()
    try:
        resp = client.post(
            "/plan",
            json={
                "question": "在高通胀与高波动环境下，给我一套稳健的多资产研究方案。",
                "market": "US",
            },
        )
        assert resp.status_code == 200
        payload = resp.json()
        plan = payload["plan"]
        agent_outputs = (plan.get("tool_context") or {}).get("agent_outputs") or []
        assert len(agent_outputs) >= 5
        for out in agent_outputs:
            trace = out.get("reasoning_trace") or {}
            steps = trace.get("steps") or []
            assert len(steps) >= 4
    finally:
        _restore_llm(llm_state)
