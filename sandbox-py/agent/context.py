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

@dataclass(frozen=True)
class ResilienceConfig:
    """Configuration for weak-model resilience mechanisms.

    All parameters have sensible defaults and are overridable via environment
    variables through the ``from_env()`` factory method.  Frozen and immutable
    -- constructed once per ``run_agent`` call.
    """

    empty_retry_max: int = 3
    text_tool_max: int = 2
    error_threshold: int = 3
    replan_interval: int = 8

    @classmethod
    def from_env(cls) -> ResilienceConfig:
        """Create a ResilienceConfig reading from environment variables with fallback to defaults."""
        return cls(
            empty_retry_max=int(os.environ.get("RESILIENCE_EMPTY_RETRY_MAX", "3")),
            text_tool_max=int(os.environ.get("RESILIENCE_TEXT_TOOL_MAX", "2")),
            error_threshold=int(os.environ.get("RESILIENCE_ERROR_THRESHOLD", "3")),
            replan_interval=int(os.environ.get("RESILIENCE_REPLAN_INTERVAL", "8")),
        )


@dataclass
class ContextConfig:
    """Configuration for the three-layer context compression pipeline.

    All parameters have sensible defaults and are overridable via environment
    variables through the ``from_env()`` factory method.
    """

    truncation_limit: int = 10_000
    micro_compact_keep_batches: int = 10
    micro_compact_min_length: int = 100
    auto_compact_threshold: int = 80_000
    transcript_dir: str = ".transcripts/"

    # Verification configuration (self-verification feature)
    verification_enabled: bool = False
    verification_max_attempts: int = 2

    @classmethod
    def from_env(cls) -> ContextConfig:
        """Create a ContextConfig reading from environment variables with fallback to defaults."""
        return cls(
            truncation_limit=int(os.environ.get("CTX_TRUNCATION_LIMIT", "10000")),
            micro_compact_keep_batches=int(os.environ.get("CTX_MICRO_COMPACT_KEEP_BATCHES", "10")),
            micro_compact_min_length=int(os.environ.get("CTX_MICRO_COMPACT_MIN_LENGTH", "100")),
            auto_compact_threshold=int(os.environ.get("CTX_AUTO_COMPACT_THRESHOLD", "80000")),
            transcript_dir=os.environ.get("CTX_TRANSCRIPT_DIR", ".transcripts/"),
            verification_enabled=os.environ.get("VERIFY_ENABLED", "").lower() in ("1", "true", "yes"),
            verification_max_attempts=int(os.environ.get("VERIFY_MAX_ATTEMPTS", "2")),
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

def _extract_file_summary(file_content: str) -> str:
    """Extract the most useful information from file content.

    Handles JSON records, markdown, emails, and line-numbered content.
    Returns a compact summary ≤150 chars.
    """
    # Strip line-number prefixes (e.g. "     1\t..." from read_file with number=true)
    lines_raw = file_content.split("\n")
    stripped_lines: list[str] = []
    for line in lines_raw:
        # Detect "   123\t..." prefix pattern
        if "\t" in line:
            parts = line.split("\t", 1)
            if parts[0].strip().isdigit():
                stripped_lines.append(parts[1])
                continue
        stripped_lines.append(line)

    clean_text = "\n".join(stripped_lines).strip()
    if not clean_text:
        return "(empty file)"

    # Try JSON: extract all fields except large nested objects and body text
    try:
        obj = json.loads(clean_text)
        if isinstance(obj, dict):
            summary: dict[str, Any] = {}
            for k, v in obj.items():
                if k == "body":
                    continue  # Skip email body text
                if isinstance(v, (str, int, float, bool)):
                    summary[k] = v
                elif isinstance(v, list):
                    if len(v) <= 5 and all(isinstance(x, (str, int, float)) for x in v):
                        # Preserve short scalar arrays (compliance_flags, tags, risk_flags)
                        summary[k] = v
                    else:
                        summary[f"_{k}_count"] = len(v)
            compact = json.dumps(summary, ensure_ascii=False)
            if len(compact) <= 400:
                return compact
            # Too long — keep only the most identifying fields + arrays
            priority_keys = ["id", "number", "name", "full_name", "email", "to",
                             "subject", "account_id", "status", "due_on",
                             "issued_on", "next_follow_up_on", "total",
                             "compliance_flags", "risk_flags", "tags"]
            important = {k: v for k, v in summary.items() if k in priority_keys}
            return json.dumps(important, ensure_ascii=False)[:400]
        # Simple scalar JSON (e.g. {"id": 84845})
        return json.dumps(obj, ensure_ascii=False)[:150]
    except (json.JSONDecodeError, ValueError):
        pass

    # Email-style: extract From/Subject/To headers + first body lines
    header_lines = []
    body_lines = []
    in_body = False
    for line in stripped_lines[:20]:
        lower = line.lower()
        if lower.startswith(("from:", "subject:", "to:", "date:")):
            header_lines.append(line.strip())
        elif not line.strip() and header_lines and not in_body:
            in_body = True  # blank line after headers = body starts
        elif in_body and line.strip() and len(body_lines) < 3:
            body_lines.append(line.strip())
    if header_lines:
        parts = header_lines
        if body_lines:
            parts = parts + ["Body: " + " ".join(body_lines)]
        return " | ".join(parts)[:400]

    # Markdown: extract title + rule lines (bullets, numbered items).
    # Process/policy files have critical rules in bullet points — preserve those.
    title = ""
    rules: list[str] = []
    in_frontmatter = False
    for line in stripped_lines:
        s = line.strip()
        if s == "---":
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter:
            continue
        if s.startswith("<!--") or not s:
            continue
        # Capture the title (first heading or first non-empty line)
        if not title:
            title = s
            continue
        # Capture rule lines (bullets and numbered items) — these are the actionable content
        if s.startswith(("- ", "* ", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.")):
            rules.append(s)

    if title:
        parts = [title]
        if rules:
            # Fit as many rules as possible within budget
            budget = 350 - len(title)
            for rule in rules:
                if budget - len(rule) - 3 < 0:
                    break
                parts.append(rule)
                budget -= len(rule) + 3
        return " | ".join(parts)[:400]

    # Fallback
    return clean_text[:150]


def _summarize_tool_result(content: str) -> str:
    """Extract a short summary from a tool result instead of deleting it.

    Preserves key facts (paths, IDs, counts, values) so the model can
    reorient without re-reading files.
    """
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        # Not JSON tool result — extract meaningful lines
        return f"[compacted] {_extract_file_summary(content)}"

    # read_file result: {"path": "...", "content": "..."}
    if "path" in data and "content" in data:
        path = data["path"]
        summary = _extract_file_summary(data["content"])
        return f'[compacted] read_file "{path}": {summary}'

    # list_dir result: {"entries": [...]}
    if "entries" in data:
        entries = data["entries"]
        names = [e.get("name", "") for e in entries[:5]]
        suffix = f" +{len(entries) - 5} more" if len(entries) > 5 else ""
        return f"[compacted] list_dir: {', '.join(names)}{suffix} ({len(entries)} items)"

    # search result: {"matches": [...]}
    if "matches" in data:
        matches = data["matches"]
        if not matches:
            return "[compacted] search: no matches"
        paths = list(dict.fromkeys(m.get("path", "") for m in matches))[:3]
        return f"[compacted] search: {len(matches)} matches in {', '.join(paths)}"

    # error result: {"error": "..."}
    if "error" in data:
        return f'[compacted] error: {data["error"][:150]}'

    # Generic JSON — keep first 150 chars of serialized form
    compact = json.dumps(data, ensure_ascii=False)[:150]
    return f"[compacted] {compact}"


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

    # Step 3: Summarize old batches (all except the most recent keep_batches).
    # Instead of deleting, extract a short summary to preserve key facts.
    old_batches = batches[:-config.micro_compact_keep_batches]
    for batch in old_batches:
        for idx in batch:
            msg = messages[idx]
            content = msg.get("content")
            if isinstance(content, str) and len(content) > config.micro_compact_min_length:
                # Skip already-compacted content to prevent double-summarization
                if content.startswith("[compacted]"):
                    continue
                msg["content"] = _summarize_tool_result(content)
