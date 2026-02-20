from fastapi.testclient import TestClient

from openfinance.api.main import app


def test_chat_message_and_history() -> None:
    client = TestClient(app)
    r = client.post(
        "/chat/message",
        json={"message": "为什么日经最近波动大，给我高夏普低回撤策略并给回测结果"},
    )
    assert r.status_code == 200
    payload = r.json()
    assert "session_id" in payload
    assert "trace_id" in payload
    assert len(payload["assistant_message"]) > 0
    assert "Sharpe" in payload["assistant_message"]
    assert "解释" in payload["assistant_message"]
    assert "证据引用" in payload["assistant_message"]
    assert payload["assistant_message"].count("- ") >= 2
    assert "developer_payload" in payload
    assert "trace_id" in payload["developer_payload"]
    assert "plan_id" in payload["developer_payload"]
    assert "experiments" in payload["developer_payload"]
    assert "evidence_sources" in payload["developer_payload"]
    assert "strategy_decision" in payload["developer_payload"]
    assert (payload["developer_payload"].get("strategy_decision") or {}).get("selected")
    assert "plan" in payload["cards"]
    assert "experiments" in payload["cards"]
    assert "strategy_decision" in payload["cards"]
    assert len(payload["turns"]) >= 2

    session_id = payload["session_id"]
    h = client.get(f"/chat/sessions/{session_id}")
    assert h.status_code == 200
    turns = h.json()
    assert len(turns) >= 2
    assert turns[0]["role"] == "user"


def test_chat_sessions_list() -> None:
    client = TestClient(app)
    client.post("/chat/message", json={"message": "session listing check"})
    r = client.get("/chat/sessions")
    assert r.status_code == 200
    assert len(r.json()) >= 1
