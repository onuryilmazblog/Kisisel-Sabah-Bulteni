"""Anthropic Claude sağlayıcısı (resmî `anthropic` Python SDK).

- Yapılandırılmış çıktı: output_config.format (JSON şeması) — yanıt şemaya uygun JSON metnidir.
- Varsayılan model: claude-opus-5 (LLM_MODEL ile değiştirilebilir).
- Claude Opus 5 / Fable 5.1 için sunucu tarafı yedek model (fallbacks: "default") açıktır;
  LLM_FALLBACKS=off ile kapatılabilir. İstek reddedilirse (400) yedeksiz tekrar denenir.
- Reddetme (stop_reason == "refusal") ve kesilme (max_tokens) hata olarak döner; özetleme
  bu durumda şablona düşer.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from .base import LLMError, LLMResult

log = logging.getLogger(__name__)

FALLBACK_MODELS = {"claude-opus-5", "claude-fable-5-1"}
NO_EFFORT_PREFIXES = ("claude-haiku", "claude-sonnet-4-5", "claude-3")


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, cfg):
        self.model = cfg.llm_model or "claude-opus-5"
        self.effort = cfg.llm_effort if cfg.llm_effort in ("low", "medium", "high", "xhigh", "max") else "medium"
        self.use_fallbacks = cfg.llm_fallbacks == "default" and self.model in FALLBACK_MODELS
        self.client = anthropic.Anthropic(api_key=cfg.anthropic_api_key, max_retries=2, timeout=180.0)

    def _output_config(self, schema: dict[str, Any]) -> dict[str, Any]:
        oc: dict[str, Any] = {"format": {"type": "json_schema", "schema": schema}}
        if not self.model.startswith(NO_EFFORT_PREFIXES):
            oc["effort"] = self.effort
        return oc

    def _call(self, *, system: str, user: str, schema: dict[str, Any], max_tokens: int):
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user}],
            "output_config": self._output_config(schema),
        }
        if self.use_fallbacks:
            try:
                return self.client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
            except anthropic.BadRequestError as exc:
                log.warning("Yedek model parametresi reddedildi, yedeksiz deneniyor: %s", exc.message)
                self.use_fallbacks = False
        return self.client.messages.create(**kwargs)

    def generate_json(self, *, system: str, user: str, schema: dict[str, Any], max_tokens: int = 4000) -> LLMResult:
        try:
            resp = self._call(system=system, user=user, schema=schema, max_tokens=max_tokens)
        except anthropic.AuthenticationError as exc:
            raise LLMError("Anthropic API anahtarı geçersiz.") from exc
        except anthropic.PermissionDeniedError as exc:
            raise LLMError("Anthropic API anahtarının bu model için izni yok.") from exc
        except anthropic.NotFoundError as exc:
            raise LLMError(f"Model bulunamadı: {self.model}") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("Anthropic hız sınırı.", retryable=True) from exc
        except anthropic.BadRequestError as exc:
            raise LLMError(f"Geçersiz istek: {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Anthropic API hatası ({exc.status_code}).", retryable=exc.status_code >= 500) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Anthropic API'ye bağlanılamadı.", retryable=True) from exc

        if resp.stop_reason == "refusal":
            raise LLMError("Model isteği reddetti (refusal).")
        if resp.stop_reason == "max_tokens":
            raise LLMError("Yanıt token sınırında kesildi.")
        text = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), None)
        if not text:
            raise LLMError("Yanıtta metin bloğu yok.")
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise LLMError("Yanıt JSON olarak ayrıştırılamadı.") from exc
        usage = resp.usage
        return LLMResult(data=data, input_tokens=int(usage.input_tokens or 0) + int(
            getattr(usage, "cache_read_input_tokens", 0) or 0), output_tokens=int(usage.output_tokens or 0),
            model=getattr(resp, "model", self.model))
