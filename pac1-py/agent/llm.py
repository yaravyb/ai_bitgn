import json
import logging
import time

import litellm
from litellm import completion

from agent.config import AgentConfig

log = logging.getLogger(__name__)

_RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    litellm.RateLimitError,
    litellm.ServiceUnavailableError,
    litellm.APIConnectionError,
    litellm.Timeout,
    litellm.InternalServerError,
)


def call_llm(
    config: AgentConfig,
    model: str,
    messages: list,
    tools: list,
    metadata: dict | None = None,
):
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "max_tokens": 16384,
        "temperature": 0,
    }
    if metadata is not None:
        kwargs["metadata"] = metadata
    if config.llm_api_base:
        kwargs["api_base"] = config.llm_api_base
    if config.llm_api_key:
        kwargs["api_key"] = config.llm_api_key

    last_exc: BaseException | None = None
    for attempt in range(config.max_retries):
        try:
            return completion(**kwargs)
        except _RETRYABLE_EXCEPTIONS as exc:
            last_exc = exc
            delay = config.retry_base_delay * (2**attempt)
            log.warning(
                "LLM call attempt %d/%d failed (%s: %s), retrying in %.1fs",
                attempt + 1, config.max_retries, type(exc).__name__, exc, delay,
            )
            time.sleep(delay)
        except Exception:
            raise
    raise last_exc  # type: ignore[misc]


def call_llm_no_tools(
    config: AgentConfig,
    model: str,
    messages: list,
    metadata: dict | None = None,
    max_tokens: int = 2048,
):
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if config.llm_api_base:
        kwargs["api_base"] = config.llm_api_base
    if config.llm_api_key:
        kwargs["api_key"] = config.llm_api_key
    if metadata is not None:
        kwargs["metadata"] = metadata

    last_exc: BaseException | None = None
    for attempt in range(config.max_retries):
        try:
            return completion(**kwargs)
        except _RETRYABLE_EXCEPTIONS as exc:
            last_exc = exc
            delay = config.retry_base_delay * (2**attempt)
            log.warning(
                "LLM no-tools call attempt %d/%d failed (%s: %s), retrying in %.1fs",
                attempt + 1, config.max_retries, type(exc).__name__, exc, delay,
            )
            time.sleep(delay)
        except Exception:
            raise
    raise last_exc  # type: ignore[misc]


def estimate_tokens(messages: list) -> int:
    return len(json.dumps(messages, default=str)) // 4
