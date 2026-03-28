"""LLM client wrapping LiteLLM's completion API.

Leaf module: no imports from other agent/ modules.
Provides provider-agnostic LLM access with error handling and retry.

Custom endpoint support: set LLM_API_BASE and LLM_API_KEY env vars
to route all LLM calls to a custom OpenAI-compatible endpoint.
Example: LLM_API_BASE=https://gpt.azati.com/llm-api LLM_API_KEY=test1
         MODEL_ID=openai/qwen3.5:27b-q4_K_M
"""

from __future__ import annotations

import json
import os
import time
import logging
from dataclasses import dataclass
from typing import Any

import litellm
from litellm import completion

# Suppress noisy LiteLLM warnings (e.g. "consecutive user/tool blocks" on Bedrock)
litellm.suppress_debug_info = True
logging.getLogger("LiteLLM").setLevel(logging.ERROR)

log = logging.getLogger(__name__)

# Exceptions considered transient and worth retrying
_RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    litellm.RateLimitError,
    litellm.ServiceUnavailableError,
    litellm.APIConnectionError,
    litellm.Timeout,
    litellm.InternalServerError,
)

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0  # seconds, doubles each retry


@dataclass
class ToolCall:
    """A parsed tool call from an LLM response."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Thin wrapper around a LiteLLM completion response."""

    content: str | None
    tool_calls: list[ToolCall]
    raw: Any


def _parse_response(response: Any) -> LLMResponse:
    """Parse a LiteLLM completion response into an LLMResponse."""
    message = response.choices[0].message

    content = message.content
    # Reasoning models (Qwen, DeepSeek) may put output in reasoning_content
    # with empty content field. Fall back to reasoning_content when available.
    if not content:
        reasoning = getattr(message, "reasoning_content", None)
        if reasoning:
            content = reasoning

    tool_calls: list[ToolCall] = []
    if message.tool_calls:
        for tc in message.tool_calls:
            arguments = tc.function.arguments
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            tool_calls.append(
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=arguments,
                )
            )

    return LLMResponse(content=content, tool_calls=tool_calls, raw=response)


def call_llm(
    model: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    max_tokens: int = 16384,
    metadata: dict | None = None,
) -> LLMResponse:
    """Call an LLM via LiteLLM with retry logic for transient failures.

    Args:
        model: LiteLLM model identifier (e.g., "openai/gpt-4.1").
        messages: Conversation messages in OpenAI format.
        tools: OpenAI-compatible function schemas, or None.
        max_tokens: Maximum completion tokens.
        metadata: Optional metadata dict for observability (e.g., Langfuse trace grouping).

    Returns:
        Parsed LLMResponse with content, tool_calls, and raw response.

    Raises:
        The underlying exception after max retries are exhausted,
        or immediately for non-retryable errors.
    """
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["parallel_tool_calls"] = True
    if metadata is not None:
        kwargs["metadata"] = metadata
    # Custom endpoint support: route to a self-hosted OpenAI-compatible API
    api_base = os.environ.get("LLM_API_BASE")
    if api_base:
        kwargs["api_base"] = api_base
    api_key = os.environ.get("LLM_API_KEY")
    if api_key:
        kwargs["api_key"] = api_key

    last_exception: BaseException | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            response = completion(**kwargs)
            return _parse_response(response)
        except _RETRYABLE_EXCEPTIONS as exc:
            last_exception = exc
            delay = _RETRY_BASE_DELAY * (2 ** attempt)
            log.warning(
                "LLM call attempt %d/%d failed (%s: %s), retrying in %.1fs",
                attempt + 1,
                _MAX_RETRIES,
                type(exc).__name__,
                exc,
                delay,
            )
            time.sleep(delay)
        except Exception:
            # Non-retryable errors propagate immediately
            raise

    # All retries exhausted
    raise last_exception  # type: ignore[misc]
