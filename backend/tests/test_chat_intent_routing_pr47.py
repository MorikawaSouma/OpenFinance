from pathlib import Path

from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.api.routes_chat import (
    _audit_store,
    _chat_store,
    _general_info_answerer,
    _knowledge,
    _market_compare_builder,
    _pipeline_engine,
    _task_manager,
)
from openfinance.api.routes_workbench import _task_manager as _workbench_task_manager
from openfinance.core.config import settings
from openfinance.core.events import event_bus
from openfinance.core.tasks import get_task_manager
from openfinance.llm.provider import LLMResponse


def _wait_task_done(client: TestClient, task_id: str, timeout_s: float = 90.0) -> dict:
    import time

    start = time.time()
    while time.time() - start <= timeout_s:
        row = client.get(f"/workbench/tasks/{task_id}").json()
        if row.get("status") in {"done", "error", "failed", "canceled"}:
            return row
        time.sleep(0.1)
    raise TimeoutError(task_id)


def _configure_paths(tmp_path: Path) -> None:
    settings.chat_session_store_file = str(tmp_path / "registry" / "chat_sessions.json")
    settings.audit_log_file = str(tmp_path / "registry" / "audit.jsonl")
    settings.task_registry_file = str(tmp_path / "registry" / "tasks.json")
    settings.dataset_registry_file = str(tmp_path / "registry" / "datasets.jsonl")
    settings.run_registry_file = str(tmp_path / "registry" / "runs.jsonl")
    settings.plan_registry_file = str(tmp_path / "registry" / "plans.jsonl")
    settings.evidence_db_file = str(tmp_path / "registry" / "evidence.sqlite3")
    settings.data_root = str(tmp_path / "data")
    settings.llm_force_stub = True
    settings.zhipu_api_key = ""
    _chat_store.cache_clear()
    _pipeline_engine.cache_clear()
    _audit_store.cache_clear()
    _knowledge.cache_clear()
    _general_info_answerer.cache_clear()
    _market_compare_builder.cache_clear()
    _task_manager.cache_clear()
    _workbench_task_manager.cache_clear()
    get_task_manager.cache_clear()


def test_chat_intent_general_info_query_returns_summary_and_citations(tmp_path: Path, monkeypatch) -> None:
    _configure_paths(tmp_path)
    client = TestClient(app)
    original_force_stub = settings.llm_force_stub
    original_api_key = settings.zhipu_api_key
    settings.llm_force_stub = False
    settings.zhipu_api_key = "dummy-key"
    answerer = _general_info_answerer()

    def fake_remote(prompt: str, **kwargs):
        return LLMResponse(
            model="glm-4.7",
            mode="remote",
            usage={"prompt_tokens": 11, "completion_tokens": 24},
            content="""
{
  "summary": [
    {"point":"US equities stayed volatile as liquidity repricing accelerated.", "citations":[1,2]},
    {"point":"Sector leadership rotated toward defensive quality stocks.", "citations":[1,3]},
    {"point":"Positioning remains fragile around macro data releases.", "citations":[2,3]}
  ],
  "drivers": [
    {"point":"Rate-path uncertainty lifted discount-rate sensitivity.", "citations":[1,2]},
    {"point":"Earnings-revision dispersion widened across cyclicals.", "citations":[3]}
  ],
  "risks": [
    {"point":"Volatility may re-accelerate on policy surprises.", "citations":[1,2]},
    {"point":"Execution-cost drag can erode net alpha in crowded names.", "citations":[2,3]}
  ],
  "what_to_watch": [
    {"point":"Monitor inflation/labor prints for policy repricing confirmation.", "citations":[1]},
    {"point":"Track revision breadth and volatility term structure.", "citations":[2,3]}
  ],
  "citations": [1,2,3],
  "confidence": 0.71
}
""".strip(),
        )

    monkeypatch.setattr(answerer.provider, "_remote_complete", fake_remote)

    try:
        query = "How is the US stock market recently?"
        resp = client.post("/chat/message", json={"message": query, "include_debug": True})
        assert resp.status_code == 200
        payload = resp.json()

        assert payload["mode"] == "general_info_query"
        assert isinstance(payload["cards"], list)
        card_types = {row["type"] for row in payload["cards"]}
        assert {"summary", "drivers", "evidence", "risks", "watch", "next_steps"}.issubset(card_types)
        evidence_card = next(row for row in payload["cards"] if row["type"] == "evidence")
        assert len(evidence_card.get("items") or []) >= 2

        debug = payload["debug"]
        assert debug["intent"] == "general_info_query"
        assert len(debug.get("citations") or []) >= 2
        assert len(debug.get("evidence_refs") or []) >= 1
        answer = debug["general_info_answer"]
        assert len(answer.get("summary") or []) >= 3
        assert len(answer.get("drivers") or []) >= 2
        assert len(answer.get("risks") or []) >= 2
        assert len(answer.get("what_to_watch") or []) >= 2
        llm = debug["general_info_llm"]
        assert llm["model"] == "glm-4.7"
        assert llm["mode"] == "remote"
        assert llm["latency_ms"] >= 0
        assert llm["prompt_hash"]
        assert "General Info Answer generated by LLM:" in debug["general_info_llm_notice"]
        assert debug.get("llm_mode") == "remote"

        text = payload["assistant_message"]
        assert "Sharpe" not in text
        assert "MDD" not in text
        assert "market overview" in text.lower()

        for row in debug.get("citations") or []:
            assert query.lower() not in str(row.get("title", "")).lower()
        llm_events = [row for row in _audit_store().list_all() if row.event_type == "chat.general_info.llm"]
        assert llm_events
        event_payload = llm_events[-1].payload
        assert event_payload.get("model") == "glm-4.7"
        assert event_payload.get("mode") == "remote"
        assert event_payload.get("prompt_hash")
        assert "latency_ms" in event_payload
    finally:
        settings.llm_force_stub = original_force_stub
        settings.zhipu_api_key = original_api_key
        _general_info_answerer.cache_clear()


def test_chat_intent_general_info_query_honors_stub_flag(tmp_path: Path) -> None:
    _configure_paths(tmp_path)
    client = TestClient(app)
    original_force_stub = settings.llm_force_stub
    original_api_key = settings.zhipu_api_key
    settings.llm_force_stub = True
    settings.zhipu_api_key = ""
    try:
        resp = client.post("/chat/message", json={"message": "美股最近怎么样？", "include_debug": True})
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["mode"] == "general_info_query"
        debug = payload["debug"]
        assert debug["general_info_llm"]["mode"] == "stub"
        assert debug["llm_mode"] == "stub"
        assert "mode=stub" in debug["general_info_llm_notice"]
        answer = debug["general_info_answer"]
        assert len(answer.get("summary") or []) >= 3
        assert len(answer.get("citations") or []) >= 2
    finally:
        settings.llm_force_stub = original_force_stub
        settings.zhipu_api_key = original_api_key
        _general_info_answerer.cache_clear()


def test_chat_intent_pipeline_research_requires_explicit_strategy_request(tmp_path: Path) -> None:
    _configure_paths(tmp_path)
    client = TestClient(app)

    resp = client.post(
        "/chat/message",
        json={"message": "Give me a US low-drawdown strategy and run backtest.", "include_debug": True},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["mode"] == "pipeline_research"
    debug = payload["debug"]
    assert debug["intent"] == "pipeline_research"
    parent_task_id = str(debug.get("parent_task_id") or "")
    assert parent_task_id
    task_done = _wait_task_done(client, parent_task_id)
    assert task_done["status"] == "done"
    assert str((task_done.get("result_ref") or {}).get("run_id") or "").strip()
    card_types = {row["type"] for row in payload["cards"]}
    assert {"summary", "next_steps"}.issubset(card_types)


def test_chat_general_info_emits_chat_request_event_not_task_created(tmp_path: Path) -> None:
    _configure_paths(tmp_path)
    client = TestClient(app)
    seen_ids = {str(ev.get("event_id") or "") for ev in event_bus.snapshot()}
    resp = client.post("/chat/message", json={"message": "美股最近如何？", "include_debug": True})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["mode"] == "general_info_query"

    events = [ev for ev in event_bus.snapshot() if str(ev.get("event_id") or "") not in seen_ids]
    assert any(ev.get("type") == "chat.request.received" for ev in events)
    assert not any(
        ev.get("type") == "task.created" and str((ev.get("payload") or {}).get("stage") or "") == "chat.request.received"
        for ev in events
    )
    session_id = str(payload.get("session_id") or "")
    tasks = client.get(f"/workbench/tasks?session_id={session_id}").json()
    assert not any(
        str(row.get("task_type") or "") == "pipeline_run" and str(row.get("status") or "") in {"queued", "running"}
        for row in tasks
    )


def test_chat_intent_modify_last_run_reuses_session_context(tmp_path: Path) -> None:
    _configure_paths(tmp_path)
    client = TestClient(app)

    first = client.post(
        "/chat/message",
        json={"message": "Give me a US low-drawdown strategy and run backtest.", "include_debug": True},
    )
    assert first.status_code == 200
    first_payload = first.json()
    session_id = first_payload["session_id"]
    parent_task_id = str(first_payload.get("debug", {}).get("parent_task_id") or "")
    assert parent_task_id
    first_task_done = _wait_task_done(client, parent_task_id)
    first_run_id = str((first_task_done.get("result_ref") or {}).get("run_id") or "")
    assert first_run_id

    second = client.post(
        "/chat/message",
        json={"session_id": session_id, "message": "Double cost and run again.", "include_debug": True},
    )
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["mode"] == "modify_last_run"
    debug = second_payload["debug"]
    assert debug["intent"] == "modify_last_run"
    assert str(debug["old_run_id"]) == first_run_id
    assert str(debug["run_id"]) != first_run_id
    assert debug["ops"]["cost_multiplier"] == 2.0
    assert "metrics_diff" in debug
    assert "cost_diff" in debug
    card_types = {row["type"] for row in second_payload["cards"]}
    assert "diff" in card_types
