"""Provider-agnostic LLM client.

Supports OpenAI-compatible chat-completions APIs (OpenAI, Groq, Together,
Mistral, local servers such as Ollama/LM Studio) and the Anthropic Messages API.
Handles timeouts, rate limits (HTTP 429 with Retry-After), server errors and
malformed responses. The key is read from the backend environment only.
"""
from __future__ import annotations

import logging
import time

import httpx

from app.config import get_settings

logger = logging.getLogger("datapulse.llm")


class LLMUnavailableError(RuntimeError):
    """The LLM is not configured or could not produce a response."""


class LLMClient:
    def __init__(self, transport: httpx.BaseTransport | None = None, sleep=time.sleep):
        self.s = get_settings()
        self._transport = transport
        self._sleep = sleep

    @property
    def configured(self) -> bool:
        return self.s.llm_configured

    @property
    def model(self) -> str:
        return self.s.llm_model

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        if not self.configured:
            raise LLMUnavailableError("No LLM is configured (set LLM_API_KEY and LLM_MODEL).")
        last_error = "unknown error"
        for attempt in range(self.s.llm_max_retries + 1):
            try:
                with httpx.Client(timeout=self.s.llm_timeout_seconds, transport=self._transport) as client:
                    if self.s.llm_provider == "anthropic":
                        response = self._anthropic(client, system, user)
                    else:
                        response = self._openai(client, system, user, json_mode)
                if response.status_code == 429 or response.status_code >= 500:
                    wait = _retry_after(response) or min(2 ** attempt, 8)
                    last_error = f"HTTP {response.status_code}"
                    logger.warning("LLM %s; retrying in %.1fs", last_error, wait)
                    if attempt < self.s.llm_max_retries:
                        self._sleep(wait)
                        continue
                    break
                if response.status_code >= 400:
                    raise LLMUnavailableError(f"LLM request rejected (HTTP {response.status_code}). "
                                              "Check LLM_MODEL, LLM_BASE_URL and the API key.")
                return self._extract_text(response.json())
            except httpx.TimeoutException:
                last_error = "timeout"
                if attempt < self.s.llm_max_retries:
                    self._sleep(min(2 ** attempt, 8))
                    continue
            except httpx.HTTPError as exc:
                last_error = type(exc).__name__
                if attempt < self.s.llm_max_retries:
                    self._sleep(min(2 ** attempt, 8))
                    continue
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise LLMUnavailableError(f"LLM returned an unexpected response format ({type(exc).__name__}).")
        raise LLMUnavailableError(f"LLM request failed after retries ({last_error}).")

    def _openai(self, client: httpx.Client, system: str, user: str, json_mode: bool) -> httpx.Response:
        body = {"model": self.s.llm_model, "temperature": 0.1, "max_tokens": self.s.llm_max_output_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        return client.post(self.s.llm_base_url.rstrip("/") + "/chat/completions", json=body,
                           headers={"Authorization": f"Bearer {self.s.llm_api_key}"})

    def _anthropic(self, client: httpx.Client, system: str, user: str) -> httpx.Response:
        base = self.s.llm_base_url.rstrip("/") if "anthropic" in self.s.llm_base_url else "https://api.anthropic.com/v1"
        body = {"model": self.s.llm_model, "max_tokens": self.s.llm_max_output_tokens, "temperature": 0.1,
                "system": system, "messages": [{"role": "user", "content": user}]}
        return client.post(base + "/messages", json=body,
                           headers={"x-api-key": self.s.llm_api_key, "anthropic-version": "2023-06-01"})

    def _extract_text(self, data: dict) -> str:
        if self.s.llm_provider == "anthropic":
            text = "".join(block.get("text", "") for block in data["content"] if block.get("type") == "text")
        else:
            text = data["choices"][0]["message"]["content"]
        if not text or not text.strip():
            raise ValueError("empty completion")
        return text


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    try:
        return min(float(value), 30.0) if value else None
    except ValueError:
        return None
