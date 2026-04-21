"""R4 structural security guard (Phase E D5).

A deterministic backstop behind the existing LLM ``_security_review``.
Scans pending outbox writes for attachments referencing the four
internal-lane paths and returns a traceable citation string when a
match is found. No LLM calls, no I/O, no prompt surface.

The check is NOT described to the LLM (R4 AC10): neither the executor
prompt nor any skill file names ``30_knowledge/``, ``90_memory/``,
``99_system/``. The guard is enforced by greps in the R9 pre-push hook.
"""

from __future__ import annotations

import re
from typing import Optional

# R4 AC4: directory prefixes are case-sensitive.
_INTERNAL_LANE_PREFIXES = ("30_knowledge/", "90_memory/", "99_system/")

# R4 AC4: ``AGENTS.md`` filename match is case-insensitive.
_INTERNAL_FILENAME_CI = frozenset({"agents.md"})

# Reuse the pattern from executor.py:1278 to find the YAML `attachments:`
# list inside a write payload's frontmatter.
_ATTACHMENTS_RE = re.compile(
    r"^attachments:\s*\n((?:\s+-\s+.+\n?)+)",
    re.MULTILINE,
)


def _normalize_attachment_path(raw: str) -> str:
    """Strip defensive prefixes so case-sensitive checks match reality.

    - Removes quoting (``"``/``'``).
    - Strips leading ``./`` one or more times.
    - Strips a leading ``/workspace/`` segment.
    - Leaves directory casing intact (R4 AC4).
    """
    path = raw.strip().strip('"').strip("'")
    while path.startswith("./"):
        path = path[2:]
    if path.startswith("/workspace/"):
        path = path[len("/workspace/"):]
    # Also drop a plain leading slash so '/30_knowledge/foo' normalizes.
    if path.startswith("/") and not path.startswith("/workspace/"):
        path = path.lstrip("/")
    return path


def _iter_attachments(content: str):
    """Yield normalized attachment paths from a write payload's YAML frontmatter."""
    if not isinstance(content, str) or not content.startswith("---"):
        return
    fm_end = content.find("\n---", 3)
    if fm_end == -1:
        return
    fm_block = content[4:fm_end]
    match = _ATTACHMENTS_RE.search(fm_block)
    if not match:
        return
    for line in match.group(1).splitlines():
        m = re.match(r"\s*-\s*(.+)", line)
        if not m:
            continue
        yield _normalize_attachment_path(m.group(1))


def structural_security_check(pending_writes: list[dict]) -> Optional[str]:
    """R4: return a citation string if any pending outbox write attaches
    an internal-lane file; return ``None`` otherwise.

    Parameters
    ----------
    pending_writes:
        List of ``TaskManager`` pending-write dicts shaped as
        ``{"op": "write", "args": {"path": ..., "content": ...}}``.
        Non-``write`` operations are ignored.
    """
    if not pending_writes:
        return None

    for write in pending_writes:
        if write.get("op") != "write":
            continue
        content = write.get("args", {}).get("content", "")
        for path in _iter_attachments(content):
            # Prefix match (case-sensitive per R4 AC4).
            for prefix in _INTERNAL_LANE_PREFIXES:
                if path.startswith(prefix):
                    return (
                        "Structural security check: outbox write references "
                        f"internal-lane file {path}"
                    )
            # Filename match (case-insensitive per R4 AC4).
            basename = path.rsplit("/", 1)[-1]
            if basename.lower() in _INTERNAL_FILENAME_CI:
                return (
                    "Structural security check: outbox write references "
                    f"internal-lane file {path}"
                )
    return None
