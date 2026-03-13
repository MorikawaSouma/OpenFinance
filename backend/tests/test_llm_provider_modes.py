from openfinance.core.config import settings
from openfinance.llm.provider import LLMResponse, ZhipuGLM47Provider


def test_llm_provider_uses_stub_when_forced() -> None:
    provider = ZhipuGLM47Provider()
    original_force_stub = settings.llm_force_stub
    original_api_key = settings.zhipu_api_key
    original_require_remote = settings.llm_require_remote
    try:
        settings.llm_force_stub = True
        settings.llm_require_remote = False
        settings.zhipu_api_key = ""
        resp = provider.complete("hello")
        assert resp.mode == "stub"
        assert "[glm-4.7 stub]" in resp.content
    finally:
        settings.llm_force_stub = original_force_stub
        settings.zhipu_api_key = original_api_key
        settings.llm_require_remote = original_require_remote


def test_llm_provider_remote_path_can_be_mocked(monkeypatch) -> None:
    provider = ZhipuGLM47Provider()
    original_force_stub = settings.llm_force_stub
    original_api_key = settings.zhipu_api_key
    original_require_remote = settings.llm_require_remote
    original_retries = settings.llm_remote_retries
    try:
        settings.llm_force_stub = False
        settings.llm_require_remote = False
        settings.llm_remote_retries = 0
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
        settings.llm_require_remote = original_require_remote
        settings.llm_remote_retries = original_retries


def test_llm_provider_raises_when_remote_required_and_no_api_key() -> None:
    provider = ZhipuGLM47Provider()
    original_force_stub = settings.llm_force_stub
    original_api_key = settings.zhipu_api_key
    original_require_remote = settings.llm_require_remote
    try:
        settings.llm_force_stub = False
        settings.llm_require_remote = True
        settings.zhipu_api_key = ""

        raised = False
        try:
            provider.complete("hello")
        except RuntimeError as ex:
            raised = True
            assert "API key" in str(ex)
        assert raised is True
    finally:
        settings.llm_force_stub = original_force_stub
        settings.zhipu_api_key = original_api_key
        settings.llm_require_remote = original_require_remote


def test_llm_provider_retries_remote_before_stub(monkeypatch) -> None:
    provider = ZhipuGLM47Provider()
    original_force_stub = settings.llm_force_stub
    original_api_key = settings.zhipu_api_key
    original_require_remote = settings.llm_require_remote
    original_retries = settings.llm_remote_retries
    calls = {"n": 0}

    def flaky_remote(prompt: str, **kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("temporary network error")
        return LLMResponse(
            model="glm-4.7",
            content=f"remote:{prompt}",
            usage={"prompt_tokens": 1, "completion_tokens": 1},
            mode="remote",
        )

    try:
        settings.llm_force_stub = False
        settings.llm_require_remote = False
        settings.llm_remote_retries = 2
        settings.zhipu_api_key = "dummy-key"
        monkeypatch.setattr(provider, "_remote_complete", flaky_remote)
        resp = provider.complete("retry test")
        assert resp.mode == "remote"
        assert calls["n"] == 2
    finally:
        settings.llm_force_stub = original_force_stub
        settings.zhipu_api_key = original_api_key
        settings.llm_require_remote = original_require_remote
        settings.llm_remote_retries = original_retries
