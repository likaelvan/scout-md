"""Thin, provider-agnostic LLM client (Groq by default, any OpenAI-compatible API).

Only returns parsed JSON. Callers must still validate the content - the LLM is
never trusted to write directly into the database.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

import openai

from .config import Config


class LLMError(Exception):
    """The LLM call failed or returned something unusable."""


class LLMUnavailable(LLMError):
    """No API key configured, auth failed, or the service can't be reached."""


@dataclass
class LLMUsage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    rate_limit_hits: int = 0


class LLMClient:
    def __init__(self, cfg: Config, *, max_retries: int = 3, base_delay: float = 2.0):
        self.cfg = cfg
        self.model = cfg.llm_model
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.usage = LLMUsage()
        self._client = (
            openai.OpenAI(api_key=cfg.llm_api_key, base_url=cfg.llm_base_url, timeout=60, max_retries=0)
            if cfg.llm_api_key
            else None
        )

    @property
    def available(self) -> bool:
        return self._client is not None

    def complete_json(self, system: str, user: str, *, temperature: float = 0.0) -> dict:
        """Chat completion in JSON mode, with backoff on rate limits / transient errors."""
        if not self._client:
            raise LLMUnavailable(f"No API key set for provider '{self.cfg.llm_provider}'")

        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                    response_format={"type": "json_object"},
                    temperature=temperature,
                )
                self.usage.calls += 1
                if resp.usage:
                    self.usage.prompt_tokens += resp.usage.prompt_tokens or 0
                    self.usage.completion_tokens += resp.usage.completion_tokens or 0
                content = resp.choices[0].message.content or ""
                try:
                    data = json.loads(content)
                except json.JSONDecodeError as e:
                    raise LLMError(f"LLM returned invalid JSON: {content[:200]!r}") from e
                if not isinstance(data, dict):
                    raise LLMError("LLM JSON was not an object")
                return data
            except openai.RateLimitError as e:
                self.usage.rate_limit_hits += 1
                last_err = e
            except (openai.APIConnectionError, openai.APITimeoutError, openai.InternalServerError) as e:
                last_err = e
            except (openai.AuthenticationError, openai.PermissionDeniedError) as e:
                raise LLMUnavailable(f"LLM auth failed: {e}") from e
            except openai.NotFoundError as e:
                raise LLMUnavailable(f"Model '{self.model}' not found - check LLM_MODEL: {e}") from e
            except openai.BadRequestError as e:
                raise LLMError(f"LLM rejected the request: {e}") from e

            if attempt < self.max_retries:
                time.sleep(self.base_delay * (2**attempt))

        raise LLMUnavailable(f"LLM failed after {self.max_retries + 1} attempts: {last_err}")

    def list_models(self) -> list[str]:
        if not self._client:
            raise LLMUnavailable("No API key configured")
        try:
            return sorted(m.id for m in self._client.models.list())
        except openai.OpenAIError as e:
            raise LLMUnavailable(str(e)) from e
