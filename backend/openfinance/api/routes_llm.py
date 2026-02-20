from functools import lru_cache

from fastapi import APIRouter
from pydantic import BaseModel, Field

from openfinance.core.config import settings
from openfinance.llm.provider import LLMProviderRegistry, ZhipuGLM47Provider

router = APIRouter(prefix="/llm", tags=["llm"])


class CompleteRequest(BaseModel):
    prompt: str = Field(min_length=1)
    provider: str | None = None
    max_tokens: int = Field(default=256, ge=1, le=2048)


@lru_cache(maxsize=1)
def _registry() -> LLMProviderRegistry:
    reg = LLMProviderRegistry()
    reg.register(ZhipuGLM47Provider(), is_default=True)
    return reg


@router.get("/providers")
def list_providers() -> list[dict[str, str]]:
    return [
        {
            "name": "zhipu",
            "model": settings.zhipu_model,
            "default": "true",
            "mode": "stub" if (settings.llm_force_stub or not settings.zhipu_api_key) else "remote",
        }
    ]


@router.post("/complete")
def complete(request: CompleteRequest) -> dict:
    provider = _registry().get(request.provider)
    resp = provider.complete(request.prompt, max_tokens=request.max_tokens)
    return {
        "provider": provider.name,
        "model": resp.model,
        "mode": resp.mode,
        "content": resp.content,
        "usage": resp.usage,
    }
