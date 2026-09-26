"""OpenAI uyumlu /chat/completions uç noktası (Claude dışındaki sağlayıcılar veya yerel modeller için:
Ollama, LM Studio, vLLM vb.). Claude için `LLM_PROVIDER=anthropic` kullanın.

Uç nokta operatörün .env dosyasından gelir (güvenilir); arayüzden değiştirilemez.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from .base import LLMError, LLMResult


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(self, cfg):
        self.base = cfg.openai_compat_base_url.rstrip("/")
        self.model = cfg.llm_model
        self.api_key = cfg.openai_compat_api_key
        self.strict_schema = True

    def generate_json(self, *, system: str, user: str, schema: dict[str, Any], max_tokens: int = 4000) -> LLMResult:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body: dict[str, Any] = {
            "model": self.model, "max_tokens": max_tokens, "temperature": 0.2,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if self.strict_schema:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "bulten_ozet", "schema": schema, "strict": True}}
        else:
            body["response_format"] = {"type": "json_object"}
        try:
            with httpx.Client(timeout=180.0) as client:
                r = client.post(f"{self.base}/chat/completions", headers=headers, json=body)
                if r.status_code == 400 and self.strict_schema:
                    self.strict_schema = False
                    return self.generate_json(system=system, user=user, schema=schema, max_tokens=max_tokens)
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM uç noktasına bağlanılamadı: {exc}", retryable=True) from exc
        if r.status_code >= 400:
            raise LLMError(f"LLM uç noktası hata döndü: HTTP {r.status_code}", retryable=r.status_code >= 500)
        try:
            payload = r.json()
            choice = payload["choices"][0]
            if choice.get("finish_reason") == "length":
                raise LLMError("Yanıt token sınırında kesildi.")
            content = choice["message"]["content"]
            data = json.loads(content)
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise LLMError("LLM yanıtı beklenen biçimde değil.") from exc
        usage = payload.get("usage") or {}
        return LLMResult(data=data, input_tokens=int(usage.get("prompt_tokens") or 0),
                         output_tokens=int(usage.get("completion_tokens") or 0), model=self.model)
