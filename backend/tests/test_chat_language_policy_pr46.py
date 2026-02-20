from fastapi.testclient import TestClient

from openfinance.api.main import app


def test_chat_response_language_follows_user_input_per_turn() -> None:
    client = TestClient(app)

    zh_resp = client.post(
        "/chat/message",
        json={"message": "请用中文分析一下日经最近波动率变化，并给出回测结论。"},
    )
    assert zh_resp.status_code == 200
    zh_payload = zh_resp.json()
    assert "研究计划已生成" in zh_payload["assistant_message"]
    assert "证据引用" in zh_payload["assistant_message"]
    session_id = zh_payload["session_id"]

    en_resp = client.post(
        "/chat/message",
        json={"session_id": session_id, "message": "Please answer in English and rerun with higher costs."},
    )
    assert en_resp.status_code == 200
    en_payload = en_resp.json()
    assert "Research plan generated" in en_payload["assistant_message"] or "Iterative rerun completed" in en_payload["assistant_message"]
    assert ("Evidence references" in en_payload["assistant_message"]) or ("changes:" in en_payload["assistant_message"])

