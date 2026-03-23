"""Context management: pure functions for token estimation, micro-compact, and tool result truncation.

Leaf module: zero imports from other agent/ modules.
Provides pure functions and data classes only.
All orchestration (LLM calls, transcript I/O) belongs in loop.py.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COMPACT_SENTINEL: str = "__COMPACT_SENTINEL__"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class ContextConfig:
    """Configuration for the three-layer context compression pipeline.

    All parameters have sensible defaults and are overridable via environment
    variables through the ``from_env()`` factory method.
    """

    truncation_limit: int = 10_000
    micro_compact_keep_batches: int = 3
    micro_compact_min_length: int = 100
    auto_compact_threshold: int = 80_000
    transcript_dir: str = ".transcripts/"

    @classmethod
    def from_env(cls) -> ContextConfig:
        """Create a ContextConfig reading from environment variables with fallback to defaults."""
        return cls(
            truncation_limit=int(os.environ.get("CTX_TRUNCATION_LIMIT", "10000")),
            micro_compact_keep_batches=int(os.environ.get("CTX_MICRO_COMPACT_KEEP_BATCHES", "3")),
            micro_compact_min_length=int(os.environ.get("CTX_MICRO_COMPACT_MIN_LENGTH", "100")),
            auto_compact_threshold=int(os.environ.get("CTX_AUTO_COMPACT_THRESHOLD", "80000")),
            transcript_dir=os.environ.get("CTX_TRANSCRIPT_DIR", ".transcripts/"),
        )


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate the token count for a messages list using a character-based heuristic.

    Pure function with no external dependencies.
    Computes ``len(str(messages)) // 4``.
    """
    return len(str(messages)) // 4


# ---------------------------------------------------------------------------
# Tool result truncation
# ---------------------------------------------------------------------------

def truncate_tool_result(result_text: str, config: ContextConfig) -> str:
    """Truncate an oversized tool result string, preserving JSON structure when possible.

    Returns the input unchanged if ``len(result_text) <= config.truncation_limit``.

    When truncation is needed:
    1. JSON-aware path: parse JSON, find the largest string value in the dict,
       truncate that value within the character budget, re-serialize.
    2. Fallback path: truncate the raw string.

    The truncation indicator ``\\n...[truncated, {original_length} chars total]``
    is appended in both paths.
    """
    if len(result_text) <= config.truncation_limit:
        return result_text

    original_length = len(result_text)
    indicator = f"\n...[truncated, {original_length} chars total]"

    # JSON-aware path
    try:
        data = json.loads(result_text)
        if isinstance(data, dict):
            # Find the key with the longest string value
            longest_key: str | None = None
            longest_len = 0
            for key, value in data.items():
                if isinstance(value, str) and len(value) > longest_len:
                    longest_key = key
                    longest_len = len(value)

            if longest_key is not None:
                # Calculate how much we need to cut from the largest value.
                # We need the total serialized JSON to fit within truncation_limit.
                # Estimate overhead: serialize everything except the target value.
                data_copy = dict(data)
                data_copy[longest_key] = ""
                overhead = len(json.dumps(data_copy, ensure_ascii=False))
                # Budget for the value: limit - overhead - indicator length
                # (indicator goes inside the value before re-serialization)
                value_budget = config.truncation_limit - overhead - len(indicator)
                if value_budget < 0:
                    value_budget = 0

                truncated_value = data[longest_key][:value_budget] + indicator
                data[longest_key] = truncated_value
                return json.dumps(data, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    # Fallback: raw string truncation
    truncated = result_text[:config.truncation_limit] + indicator
    return truncated


# ---------------------------------------------------------------------------
# Micro-compact
# ---------------------------------------------------------------------------

def micro_compact(messages: list[dict[str, Any]], config: ContextConfig) -> None:
    """Replace old tool result content with placeholders, mutating messages in-place.

    A "batch" of tool results corresponds to one assistant turn that included
    ``tool_calls``. The boundary is detected by scanning messages in order:
    an assistant message with a ``tool_calls`` key starts a new batch; all
    subsequent ``role == "tool"`` messages before the next assistant message
    belong to that batch.

    Only tool result messages in batches older than the most recent
    ``config.micro_compact_keep_batches`` batches are eligible for clearing.
    Content is replaced only if it is a string longer than
    ``config.micro_compact_min_length``.

    This function never removes messages, never removes ``tool_call_id``,
    and never modifies system, user, or assistant messages.
    """
    if not messages:
        return

    # Step 1: Identify batch boundaries.
    # Each batch is a list of indices of role=="tool" messages.
    batches: list[list[int]] = []
    current_batch: list[int] | None = None

    for idx, msg in enumerate(messages):
        role = msg.get("role")
        if role == "assistant" and "tool_calls" in msg:
            # Start a new batch
            current_batch = []
            batches.append(current_batch)
        elif role == "tool" and current_batch is not None:
            current_batch.append(idx)

    # Step 2: If total batches <= keep, nothing to clear.
    if len(batches) <= config.micro_compact_keep_batches:
        return

    # Step 3: Clear old batches (all except the most recent keep_batches).
    old_batches = batches[:-config.micro_compact_keep_batches]
    for batch in old_batches:
        for idx in batch:
            msg = messages[idx]
            content = msg.get("content")
            if isinstance(content, str) and len(content) > config.micro_compact_min_length:
                msg["content"] = "[Previous tool result cleared]"
