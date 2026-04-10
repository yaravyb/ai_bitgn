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

# Tight per-call timeout (seconds). Upstream 504 storms must fail fast so the
# outer retry loop owns the retry decision instead of waiting on litellm's
# default ~600s per-request timeout. A single 5-run t29 battery observed a
# ~27-minute hang before this cap was in place.
_CALL_TIMEOUT_SEC = 90

# Cap exponential backoff so per-retry sleep never grows unbounded when
# max_retries is bumped. With base_delay=1.0 and max_retries=3 the effective
# delay sequence is 1s, 2s, 4s (unchanged from before); with max_retries=6 it
# would cap at 1s, 2s, 4s, 8s, 8s, 8s instead of 1/2/4/8/16/32.
_RETRY_MAX_DELAY = 8.0

# Hard ceiling on total wall-clock time spent across all retry attempts for a
# single call_llm invocation. Prevents the "27-minute hang on a single
# validator call" failure mode observed on t10 during upstream 504 storms.
_RETRY_TOTAL_BUDGET_SEC = 300.0


def _completion_with_retry(
    kwargs: dict,
    max_retries: int,
    base_delay: float,
    label: str,
):
    """Shared retry wrapper for ``litellm.completion``.

    Retry ownership is collapsed to this single layer:

    - litellm's internal retries are disabled (``num_retries=0``) so the
      retry loop here is the only retry surface. Prevents the three-layer
      retry stacking (OpenAI SDK -> litellm -> ours) that caused a
      ~27-minute hang on t10 during a 504 storm.
    - Per-call timeout is capped at ``_CALL_TIMEOUT_SEC`` so a single
      attempt fails fast instead of waiting on litellm's default ~600s.
    - Exponential backoff is capped at ``_RETRY_MAX_DELAY`` per sleep.
    - Total wall-clock retry budget is capped at ``_RETRY_TOTAL_BUDGET_SEC``
      across all attempts, so the whole retry sequence can never exceed the
      budget (worst case ~= max_retries * _CALL_TIMEOUT_SEC + sum of backoff
      delays, whichever is smaller than the budget).
    """
    kwargs = dict(kwargs)
    kwargs.setdefault("timeout", _CALL_TIMEOUT_SEC)
    kwargs.setdefault("num_retries", 0)

    start = time.monotonic()
    last_exc: BaseException | None = None
    for attempt in range(max_retries):
        try:
            return completion(**kwargs)
        except _RETRYABLE_EXCEPTIONS as exc:
            last_exc = exc
            elapsed = time.monotonic() - start
            if elapsed >= _RETRY_TOTAL_BUDGET_SEC:
                log.warning(
                    "%s retry budget exhausted after %.1fs (%d/%d attempts) — giving up",
                    label, elapsed, attempt + 1, max_retries,
                )
                break
            if attempt + 1 >= max_retries:
                break
            delay = min(base_delay * (2**attempt), _RETRY_MAX_DELAY)
            log.warning(
                "%s attempt %d/%d failed (%s: %s), retrying in %.1fs",
                label, attempt + 1, max_retries, type(exc).__name__, exc, delay,
            )
            time.sleep(delay)
        except Exception:
            raise
    raise last_exc  # type: ignore[misc]


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

    return _completion_with_retry(
        kwargs,
        max_retries=config.max_retries,
        base_delay=config.retry_base_delay,
        label="LLM call",
    )


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

    return _completion_with_retry(
        kwargs,
        max_retries=config.max_retries,
        base_delay=config.retry_base_delay,
        label="LLM no-tools call",
    )


def estimate_tokens(messages: list) -> int:
    return len(json.dumps(messages, default=str)) // 4
