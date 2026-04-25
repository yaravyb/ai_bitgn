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
_CALL_TIMEOUT_SEC = 300

# Cap exponential backoff so per-retry sleep never grows unbounded when
# max_retries is bumped. With base_delay=1.0 and max_retries=3 the effective
# delay sequence is 1s, 2s, 4s (unchanged from before); with max_retries=6 it
# would cap at 1s, 2s, 4s, 8s, 8s, 8s instead of 1/2/4/8/16/32.
_RETRY_MAX_DELAY = 8.0

# Hard ceiling on total wall-clock time spent across all retry attempts for a
# single call_llm invocation. Prevents the "27-minute hang on a single
# validator call" failure mode observed on t10 during upstream 504 storms.
_RETRY_TOTAL_BUDGET_SEC = 1000.0


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

    # Diagnostic: estimate input size so 504s/timeouts can be correlated
    # with context length. Includes tool schemas (they add real prompt
    # tokens). Cheap rough estimator — 4 chars / token.
    in_est = estimate_tokens(kwargs.get("messages") or [])
    if kwargs.get("tools"):
        in_est += estimate_tokens(kwargs["tools"])
    max_out = kwargs.get("max_tokens", "?")
    n_tools = len(kwargs.get("tools") or [])
    print(f"  [llm→] {label}  in≈{in_est}  max_out={max_out}  tools={n_tools}", flush=True)

    start = time.monotonic()
    last_exc: BaseException | None = None
    correction_added = False
    for attempt in range(max_retries):
        attempt_start = time.monotonic()
        try:
            resp = completion(**kwargs)
            usage = getattr(resp, "usage", None)
            attempt_elapsed = time.monotonic() - attempt_start
            if usage is not None:
                print(
                    f"  [llm←] {label}  prompt={getattr(usage,'prompt_tokens','?')}  "
                    f"out={getattr(usage,'completion_tokens','?')}  "
                    f"elapsed={attempt_elapsed:.1f}s",
                    flush=True,
                )
            else:
                print(f"  [llm←] {label}  elapsed={attempt_elapsed:.1f}s  (no usage)", flush=True)
            return resp
        except _RETRYABLE_EXCEPTIONS as exc:
            last_exc = exc
            attempt_elapsed = time.monotonic() - attempt_start
            elapsed = time.monotonic() - start
            print(
                f"  [llm✗] {label}  attempt={attempt+1}/{max_retries}  "
                f"elapsed={attempt_elapsed:.1f}s  err={type(exc).__name__}",
                flush=True,
            )
            # Feedback-on-retry: when the backend rejects the model's
            # output as malformed tool-call syntax (e.g. "<parameter>
            # closed by </function>"), adding a corrective system
            # message tells the model to emit valid JSON tool calls on
            # the next attempt. Without this, temperature=0 + identical
            # prompt = identical broken output → all retries fail
            # identically. Only inject the message once per call.
            exc_text = str(exc).lower()
            looks_like_tool_syntax_error = (
                "syntax error" in exc_text
                or "xml" in exc_text and "element" in exc_text
                or "<parameter>" in exc_text
                or "</function>" in exc_text
            )
            if looks_like_tool_syntax_error and not correction_added and kwargs.get("tools"):
                correction_added = True
                kwargs["messages"] = list(kwargs.get("messages", [])) + [{
                    "role": "system",
                    "content": (
                        "Your previous response had malformed tool-call "
                        "syntax. Emit tool calls strictly as valid JSON "
                        "conforming to the tools schema — no XML tags "
                        "like <parameter> or </function>. If you cannot "
                        "produce a valid tool call, return plain text "
                        "with your conclusion instead."
                    ),
                }]
                print(
                    f"  [retry-feedback] {label} appended tool-syntax correction",
                    flush=True,
                )
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
    enable_thinking: bool | None = None,
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
    # Qwen3-on-Ollama thinking suppression (Azati deployment, probed
    # 2026-04-24). The backend ignores chat_template_kwargs.enable_thinking
    # and the /no_think chat marker, but honors OpenAI-style
    # reasoning_effort="none" via the OpenAI-compatible endpoint — this
    # maps to Ollama's native think=False. "low"/"medium"/"high" have no
    # effect (Ollama's Qwen3 exposes a binary on/off, not a gradient).
    # Use for mechanical completions (code generation, one-word judges)
    # where hidden reasoning would burn the max_tokens budget before any
    # content is emitted.
    if enable_thinking is False:
        kwargs["extra_body"] = {"reasoning_effort": "none"}

    return _completion_with_retry(
        kwargs,
        max_retries=config.max_retries,
        base_delay=config.retry_base_delay,
        label="LLM no-tools call",
    )


def estimate_tokens(messages: list) -> int:
    return len(json.dumps(messages, default=str)) // 4
