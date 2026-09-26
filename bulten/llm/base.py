"""Değiştirilebilir LLM sağlayıcı arayüzü."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class LLMError(Exception):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class LLMResult:
    data: dict[str, Any]
    input_tokens: int
    output_tokens: int
    model: str


class LLMProvider(Protocol):
    name: str
    model: str

    def generate_json(self, *, system: str, user: str, schema: dict[str, Any], max_tokens: int = 4000) -> LLMResult:
        ...


def get_provider(cfg) -> LLMProvider | None:
    """Yapılandırmaya göre sağlayıcı; yapılandırılmamışsa None (şablon özet kullanılır)."""
    if not cfg.llm_configured:
        return None
    if cfg.llm_provider == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(cfg)
    if cfg.llm_provider == "openai_compat":
        from .openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(cfg)
    return None
