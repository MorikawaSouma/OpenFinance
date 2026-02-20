import logging
from dataclasses import dataclass
from typing import Any

import httpx

from openfinance.core.config import settings

logger = logging.getLogger(__name__)

from abc import ABC, abstractmethod


@dataclass
class LLMResponse:
    model: str
    content: str
    usage: dict[str, int]
    mode: str = "stub"


class LLMProvider(ABC):
    name: str
    model: str

    @abstractmethod
    def complete(self, prompt: str, **kwargs: Any) -> LLMResponse:
        raise NotImplementedError


class ZhipuGLM47Provider(LLMProvider):
    name = settings.llm_default_provider
    model = settings.zhipu_model

    def complete(self, prompt: str, **kwargs: Any) -> LLMResponse:
        if settings.llm_force_stub or not settings.zhipu_api_key:
            return self._stub_complete(prompt, **kwargs)
        try:
            return self._remote_complete(prompt, **kwargs)
        except Exception as ex:  # pragma: no cover
            logger.warning("Zhipu remote call failed; fallback to stub: %s", ex)
            return self._stub_complete(prompt, **kwargs)

    def _stub_complete(self, prompt: str, **kwargs: Any) -> LLMResponse:
        max_tokens = int(kwargs.get("max_tokens", 256))
        text = f"[{self.model} stub] {prompt[:max_tokens]}"
        return LLMResponse(
            model=self.model,
            content=text,
            usage={"prompt_tokens": len(prompt) // 4 + 1, "completion_tokens": min(max_tokens, 64)},
            mode="stub",
        )

    def _remote_complete(self, prompt: str, **kwargs: Any) -> LLMResponse:
        max_tokens = int(kwargs.get("max_tokens", 256))
        timeout_s = float(kwargs.get("timeout_s", 30))
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": float(kwargs.get("temperature", 0.2)),
            "thinking": {"type": "disabled"},
        }
        headers = {"Authorization": f"Bearer {settings.zhipu_api_key}", "Content-Type": "application/json"}
        with httpx.Client(timeout=timeout_s) as client:
            resp = client.post(settings.zhipu_base_url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        content = self._extract_content(data)
        usage = data.get("usage", {})
        return LLMResponse(
            model=data.get("model", self.model),
            content=content,
            usage={
                "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                "completion_tokens": int(usage.get("completion_tokens", 0)),
            },
            mode="remote",
        )

    def _extract_content(self, data: dict[str, Any]) -> str:
        choices = data.get("choices", [])
        if not isinstance(choices, list) or not choices:
            return ""

        c0 = choices[0] if isinstance(choices[0], dict) else {}
        message = c0.get("message") if isinstance(c0, dict) else None
        message = message if isinstance(message, dict) else {}

        # Primary final answer path.
        content = message.get("content")
        parsed = self._coerce_text(content)
        if parsed:
            return parsed

        # Some response shapes put answer at choice level.
        parsed = self._coerce_text(c0.get("content"))
        if parsed:
            return parsed

        # For models that return reasoning-only channel, fallback to it.
        reasoning = self._coerce_text(message.get("reasoning_content"))
        if reasoning:
            return reasoning

        # Compatibility with alternative response wrappers.
        parsed = self._coerce_text(data.get("output_text"))
        if parsed:
            return parsed
        return ""

    def _coerce_text(self, value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            parts: list[str] = []
            for item in value:
                if isinstance(item, str):
                    text = item.strip()
                    if text:
                        parts.append(text)
                elif isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
            return "\n".join(parts).strip()
        return ""


class LLMProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {}
        self._default: str | None = None

    def register(self, provider: LLMProvider, is_default: bool = False) -> None:
        self._providers[provider.name] = provider
        if is_default or self._default is None:
            self._default = provider.name

    def get(self, name: str | None = None) -> LLMProvider:
        key = name or self._default
        if key is None or key not in self._providers:
            raise KeyError("LLM provider not found")
        return self._providers[key]
