"""
LLM Router — retry, fallback model, and per-model circuit breaking.

Retry policy: up to 3 attempts (1 initial + 2 retries) with exponential
backoff + jitter. On NotFoundError the next candidate model is tried
immediately (no backoff). RateLimitError and provider errors trigger
backoff before the next attempt.

Circuit breaker: opens after FAILURE_THRESHOLD consecutive failures on a
model and stays open for OPEN_DURATION seconds. After that a single probe
attempt is allowed (half-open). Success resets the failure count.
"""
import asyncio
import logging
import random
import time
from typing import Optional

from openai import AsyncOpenAI, APIConnectionError, APIStatusError, NotFoundError, RateLimitError

from app.config import settings

logger = logging.getLogger(__name__)

_CIRCUIT_OPEN_DURATION = 60.0       # seconds a circuit stays open
_CIRCUIT_FAILURE_THRESHOLD = 3      # consecutive failures before opening
_MAX_ATTEMPTS = 3                   # total attempts (1 + 2 retries)


class _CircuitBreaker:
    """Simple in-process per-model circuit breaker."""

    def __init__(self) -> None:
        self._failures: dict[str, int] = {}
        self._opened_at: dict[str, float] = {}

    def is_open(self, model: str) -> bool:
        opened = self._opened_at.get(model)
        if opened is None:
            return False
        if time.monotonic() - opened > _CIRCUIT_OPEN_DURATION:
            # Transition to half-open: allow one probe
            del self._opened_at[model]
            self._failures[model] = 0
            return False
        return True

    def record_failure(self, model: str) -> None:
        self._failures[model] = self._failures.get(model, 0) + 1
        if self._failures[model] >= _CIRCUIT_FAILURE_THRESHOLD:
            if model not in self._opened_at:
                self._opened_at[model] = time.monotonic()
                logger.warning("llm_router: circuit opened for model '%s'", model)

    def record_success(self, model: str) -> None:
        self._failures.pop(model, None)
        self._opened_at.pop(model, None)


_circuit_breaker = _CircuitBreaker()


class LLMRouter:
    """Routes LLM calls with retry, model fallback, and circuit breaking."""

    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            base_url=settings.OLLAMA_BASE_URL,
            api_key="ollama",
        )

    async def complete(
        self,
        model: str,
        messages: list,
        tools: Optional[list] = None,
    ):
        """
        Issue a chat completion with retry and fallback.

        Returns an openai ChatCompletion on success.
        Raises the last exception if every attempt on every candidate fails.
        """
        candidates = [model]
        fallback = settings.FALLBACK_MODEL
        if fallback and fallback != model:
            candidates.append(fallback)

        last_exc: Optional[Exception] = None

        for attempt in range(_MAX_ATTEMPTS):
            for candidate in candidates:
                if _circuit_breaker.is_open(candidate):
                    logger.debug("llm_router: circuit open for '%s', skipping", candidate)
                    continue

                try:
                    kwargs: dict = {"model": candidate, "messages": messages}
                    if tools:
                        kwargs["tools"] = tools
                        kwargs["tool_choice"] = "auto"

                    result = await self._client.chat.completions.create(**kwargs)
                    _circuit_breaker.record_success(candidate)
                    if candidate != model:
                        logger.info(
                            "llm_router: request served by fallback model '%s'", candidate
                        )
                    return result

                except NotFoundError:
                    # Model unavailable on this provider — try next candidate immediately.
                    logger.warning(
                        "llm_router: model '%s' not found, trying next candidate", candidate
                    )
                    continue

                except RateLimitError as exc:
                    last_exc = exc
                    _circuit_breaker.record_failure(candidate)
                    delay = (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        "llm_router: rate limited on '%s' (attempt %d/%d), backing off %.1fs",
                        candidate, attempt + 1, _MAX_ATTEMPTS, delay,
                    )
                    await asyncio.sleep(delay)
                    break  # outer loop retries with backoff applied

                except (APIConnectionError, APIStatusError) as exc:
                    last_exc = exc
                    _circuit_breaker.record_failure(candidate)
                    logger.warning(
                        "llm_router: provider error on '%s' (attempt %d/%d): %s",
                        candidate, attempt + 1, _MAX_ATTEMPTS, exc,
                    )
                    if attempt < _MAX_ATTEMPTS - 1:
                        delay = (2 ** attempt) + random.uniform(0, 1)
                        await asyncio.sleep(delay)
                    break  # outer loop retries

        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"No available LLM model after exhausting candidates: {candidates}")


_router: Optional[LLMRouter] = None


def get_llm_router() -> LLMRouter:
    """Return the module-level LLMRouter singleton."""
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router
