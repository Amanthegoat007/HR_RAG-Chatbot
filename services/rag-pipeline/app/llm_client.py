"""
============================================================================
FILE: services/query/app/llm_client.py
PURPOSE: Unified LLM client — local llama.cpp server + Azure OpenAI fallback.
         Implements circuit breaker to auto-switch providers on failure.
ARCHITECTURE REF: §3.7 — LLM Generation with Streaming
DEPENDENCIES: httpx, asyncio, tenacity
============================================================================

LLM Provider Strategy:
━━━━━━━━━━━━━━━━━━━━━━
1. Primary (LLM_PROVIDER=local):
   - Calls llama.cpp HTTP server at http://llm-server:8080
   - OpenAI-compatible API: POST /v1/chat/completions
   - Model: Mistral-7B-Instruct-v0.3 Q5_K_M (on-premises, private)
   - Streaming: stream=True → Server-Sent Events from llama.cpp

2. Fallback (LLM_PROVIDER=azure_openai, or auto-switch via circuit breaker):
   - Azure OpenAI endpoint with API key from env vars
   - Same OpenAI-compatible API format
   - Only used when: explicitly configured OR circuit breaker trips

Circuit Breaker Logic:
━━━━━━━━━━━━━━━━━━━━━━
- Tracks consecutive failures for the local LLM
- After 3 failures within 60 seconds → OPEN (fallback to Azure)
- After 60 seconds in OPEN state → HALF-OPEN (try local again)
- If local succeeds in HALF-OPEN → CLOSED (back to normal)
- If Azure is not configured and circuit is open → raise LLMUnavailableError

SSE Streaming:
━━━━━━━━━━━━━━
Both llama.cpp and Azure OpenAI send tokens as:
  data: {"choices": [{"delta": {"content": "token_here"}, "finish_reason": null}]}
  data: [DONE]

We yield each token string so the pipeline can forward them to the client.
"""

import asyncio
import json
import logging
import time
from enum import Enum
from typing import AsyncGenerator, Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Custom exceptions
# ──────────────────────────────────────────────────────────────────────────────


class LLMUnavailableError(Exception):
    """Raised when all LLM providers are unavailable (circuit open + no fallback)."""


# ──────────────────────────────────────────────────────────────────────────────
# Circuit Breaker
# ──────────────────────────────────────────────────────────────────────────────


class CircuitState(Enum):
    """States of the circuit breaker."""
    CLOSED = "closed"        # Normal operation — using local LLM
    OPEN = "open"            # Too many failures — using fallback
    HALF_OPEN = "half_open"  # Testing if local LLM recovered


class CircuitBreaker:
    """
    Simple in-process circuit breaker for the local LLM connection.

    Not distributed (each query-svc replica maintains its own state).
    For a single-replica deployment this is sufficient.

    Thresholds (from config):
        failure_threshold: 3 consecutive failures → OPEN
        recovery_timeout:  60 seconds in OPEN → HALF_OPEN
    """

    def __init__(self, failure_threshold: int = 3, recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None

    @property
    def state(self) -> CircuitState:
        """Return current state, auto-transitioning OPEN→HALF_OPEN after timeout."""
        if (
            self._state == CircuitState.OPEN
            and self._last_failure_time is not None
            and time.monotonic() - self._last_failure_time >= self.recovery_timeout
        ):
            logger.info("Circuit breaker → HALF_OPEN (recovery timeout elapsed)")
            self._state = CircuitState.HALF_OPEN
        return self._state

    def record_success(self) -> None:
        """Record a successful call — close the circuit."""
        if self._state != CircuitState.CLOSED:
            logger.info("Circuit breaker → CLOSED (local LLM recovered)")
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = None

    def record_failure(self) -> None:
        """Record a failed call — increment counter, trip if threshold reached."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self.failure_threshold:
            if self._state != CircuitState.OPEN:
                logger.warning(
                    "Circuit breaker → OPEN",
                    extra={"failure_count": self._failure_count},
                )
            self._state = CircuitState.OPEN

    @property
    def is_available(self) -> bool:
        """Return True if we should try the local LLM."""
        return self.state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)


# Module-level singleton — shared across all requests in this process
_circuit_breaker = CircuitBreaker(
    failure_threshold=settings.llm_circuit_breaker_threshold,
    recovery_timeout=settings.llm_circuit_breaker_recovery_seconds,
)


# ──────────────────────────────────────────────────────────────────────────────
# Token streaming helpers
# ──────────────────────────────────────────────────────────────────────────────


async def _stream_tokens_from_response(
    response: httpx.Response,
) -> AsyncGenerator[str, None]:
    """
    Parse Server-Sent Events from an OpenAI-compatible streaming response.

    Both llama.cpp and Azure OpenAI follow the same SSE format:
        data: {"id":"...","choices":[{"delta":{"content":"token"},...}]}
        data: [DONE]

    Yields:
        Each token string as it arrives from the server.
    """
    async for line in response.aiter_lines():
        line = line.strip()
        if not line or not line.startswith("data:"):
            continue

        payload = line[len("data:"):].strip()

        # [DONE] sentinel marks end of stream
        if payload == "[DONE]":
            break

        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            logger.debug("SSE parse error — non-JSON payload", extra={"payload": payload[:100]})
            continue

        choices = data.get("choices", [])
        if not choices:
            continue

        delta = choices[0].get("delta", {})
        token = delta.get("content")
        if token:
            yield token


# ──────────────────────────────────────────────────────────────────────────────
# Local LLM (llama.cpp HTTP server)
# ──────────────────────────────────────────────────────────────────────────────


async def _call_local_llm(
    client: httpx.AsyncClient,
    messages: list[dict[str, str]],
    max_tokens: Optional[int] = None,
    stop: Optional[list[str]] = None,
) -> AsyncGenerator[str, None]:
    """
    Call the local llama.cpp HTTP server with streaming enabled.

    The llama.cpp server exposes an OpenAI-compatible API at /v1/chat/completions.
    We use httpx's async streaming to avoid buffering the full response.

    Args:
        client: Shared httpx.AsyncClient.
        messages: List of {role, content} dicts (system + user messages).

    Yields:
        Token strings from the model's output stream.

    Raises:
        httpx.HTTPStatusError: On 4xx/5xx responses.
        httpx.TimeoutException: If the server doesn't respond in time.
    """
    payload = {
        "model": "mistral",         # llama.cpp ignores model name but needs it
        "messages": messages,
        "stream": True,
        "temperature": settings.llm_temperature,
        "max_tokens": max_tokens if max_tokens is not None else settings.llm_max_tokens,
        "top_p": settings.llm_top_p,
    }
    if stop:
        payload["stop"] = stop

    async with client.stream(
        "POST",
        f"{settings.llm_server_url}/v1/chat/completions",
        json=payload,
        timeout=settings.llm_stream_timeout_seconds,  # Long timeout for token streaming
    ) as response:
        response.raise_for_status()
        async for token in _stream_tokens_from_response(response):
            yield token


# ──────────────────────────────────────────────────────────────────────────────
# Azure OpenAI fallback
# ──────────────────────────────────────────────────────────────────────────────


async def _call_azure_openai(
    client: httpx.AsyncClient,
    messages: list[dict[str, str]],
    max_tokens: Optional[int] = None,
    stop: Optional[list[str]] = None,
) -> AsyncGenerator[str, None]:
    """
    Call Azure OpenAI as fallback when the local LLM is unavailable.

    Uses the Azure OpenAI REST API with the same message format.
    Requires AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT_ID
    environment variables (set via .env / Docker Compose).

    Args:
        client: Shared httpx.AsyncClient.
        messages: List of {role, content} dicts.

    Yields:
        Token strings from the Azure OpenAI response stream.

    Raises:
        LLMUnavailableError: If Azure OpenAI is not configured.
        httpx.HTTPStatusError: On API errors.
    """
    if not settings.azure_openai_endpoint or not settings.azure_openai_api_key:
        raise LLMUnavailableError(
            "Local LLM is unavailable and Azure OpenAI is not configured. "
            "Set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY in .env to enable fallback."
        )

    # Azure OpenAI API URL format:
    # https://<resource>.openai.azure.com/openai/deployments/<deployment>/chat/completions?api-version=<version>
    url = (
        f"{settings.azure_openai_endpoint}/openai/deployments/"
        f"{settings.azure_openai_deployment_id}/chat/completions"
        f"?api-version={settings.azure_openai_api_version}"
    )

    payload = {
        "messages": messages,
        "stream": True,
        "temperature": settings.llm_temperature,
        "max_tokens": max_tokens if max_tokens is not None else settings.llm_max_tokens,
    }
    if stop:
        payload["stop"] = stop

    headers = {"api-key": settings.azure_openai_api_key}

    logger.warning("Using Azure OpenAI fallback (local LLM circuit breaker is OPEN)")

    async with client.stream(
        "POST",
        url,
        json=payload,
        headers=headers,
        timeout=settings.llm_stream_timeout_seconds,
    ) as response:
        response.raise_for_status()
        async for token in _stream_tokens_from_response(response):
            yield token


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────


async def generate_stream(
    client: httpx.AsyncClient,
    messages: list[dict[str, str]],
    max_tokens: Optional[int] = None,
    stop: Optional[list[str]] = None,
) -> AsyncGenerator[str, None]:
    """
    Generate a streaming LLM response, automatically selecting the provider.

    Provider selection logic:
      1. If LLM_PROVIDER=azure_openai (explicitly set) → use Azure directly
      2. If LLM_PROVIDER=local (default) AND circuit is CLOSED/HALF_OPEN → try local
      3. If local call fails → record failure, trip circuit if threshold reached
      4. If circuit is OPEN (or local failed) → try Azure OpenAI fallback
      5. If Azure is also not configured → raise LLMUnavailableError

    Architecture Reference: §3.7 — LLM Generation with Streaming

    Args:
        client: Shared httpx.AsyncClient (injected from FastAPI app state).
        messages: Formatted prompt as list of {role, content} dicts.
                  Typically: [{"role": "system", "content": SYSTEM_PROMPT},
                               {"role": "user",   "content": question_with_context}]

    Yields:
        Token strings as they stream from the LLM.

    Raises:
        LLMUnavailableError: If all providers are unavailable.
    """
    # --- Explicit Azure-only mode ---
    if settings.llm_provider == "azure_openai":
        async for token in _call_azure_openai(
            client,
            messages,
            max_tokens=max_tokens,
            stop=stop,
        ):
            yield token
        return

    # --- Local LLM with circuit breaker ---
    if _circuit_breaker.is_available:
        try:
            token_count = 0
            async for token in _call_local_llm(
                client,
                messages,
                max_tokens=max_tokens,
                stop=stop,
            ):
                yield token
                token_count += 1
            # Success: close the circuit (records success only after full stream)
            _circuit_breaker.record_success()
            logger.debug("Local LLM stream complete", extra={"token_count": token_count})
            return  # Done — no need for fallback

        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as exc:
            logger.error(
                "Local LLM call failed",
                extra={"error": str(exc), "circuit_state": _circuit_breaker.state.value},
            )
            _circuit_breaker.record_failure()
            # Fall through to Azure fallback below

    # --- Azure OpenAI fallback ---
    logger.info("Falling back to Azure OpenAI", extra={"circuit_state": _circuit_breaker.state.value})
    async for token in _call_azure_openai(
        client,
        messages,
        max_tokens=max_tokens,
        stop=stop,
    ):
        yield token
