from openfinance.core.config import settings
from openfinance.llm.provider import LLMResponse, ZhipuGLM47Provider


def test_llm_provider_uses_stub_when_forced() -> None:
    provider = ZhipuGLM47Provider()
    original_force_stub = settings.llm_force_stub
    original_api_key = settings.zhipu_api_key
    try:
        settings.llm_force_stub = True
        settings.zhipu_api_key = ""
        resp = provider.complete("hello")
        assert resp.mode == "stub"
        assert "[glm-4.7 stub]" in resp.content
    finally:
        settings.llm_force_stub = original_force_stub
        settings.zhipu_api_key = original_api_key


def test_llm_provider_remote_path_can_be_mocked(monkeypatch) -> None:
    provider = ZhipuGLM47Provider()
    original_force_stub = settings.llm_force_stub
    original_api_key = settings.zhipu_api_key
    try:
        settings.llm_force_stub = False
        settings.zhipu_api_key = "dummy-key"

        def fake_remote(prompt: str, **kwargs):
            return LLMResponse(
                model="glm-4.7",
                content=f"remote:{prompt}",
                usage={"prompt_tokens": 1, "completion_tokens": 1},
                mode="remote",
            )

        monkeypatch.setattr(provider, "_remote_complete", fake_remote)
        resp = provider.complete("hello remote")
        assert resp.mode == "remote"
        assert resp.content == "remote:hello remote"
    finally:
        settings.llm_force_stub = original_force_stub
        settings.zhipu_api_key = original_api_key
