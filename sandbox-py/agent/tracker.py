"""Grounding reference tracker.

Pure data module: maintains a set of file paths read during agent execution.
Zero imports from other agent/ modules.
"""

from __future__ import annotations

import posixpath
from collections.abc import Iterable


def _normalize(path: str) -> str:
    """Normalize a file path for consistent comparison.

    - Strip leading '/'
    - Resolve '..' segments via posixpath.normpath
    - Result is used for dedup comparison (lowercased externally).
    """
    stripped = path.lstrip("/")
    return posixpath.normpath(stripped)


class GroundingTracker:
    """Tracks file paths read during agent execution for grounding references.

    Path normalization: leading '/' is stripped, '..' is resolved,
    lowercase is used for deduplication comparison but original casing
    is preserved.
    """

    def __init__(self) -> None:
        # Maps normalized-lowercase key -> original-casing path
        self._files: dict[str, str] = {}

    def add(self, path: str) -> None:
        """Add a single file path, normalizing it."""
        normalized = _normalize(path)
        key = normalized.lower()
        if key not in self._files:
            self._files[key] = normalized

    def add_many(self, paths: Iterable[str]) -> None:
        """Add multiple file paths."""
        for p in paths:
            self.add(p)

    def merge(self, llm_refs: list[str]) -> list[str]:
        """Return sorted union of tracked files and LLM-provided refs.

        LLM refs are also normalized. Deduplication is case-insensitive.
        Never returns an empty list if files have been tracked.
        """
        # Start with all tracked files
        merged: dict[str, str] = dict(self._files)
        # Add LLM refs, normalizing them
        for ref in llm_refs:
            normalized = _normalize(ref)
            key = normalized.lower()
            if key not in merged:
                merged[key] = normalized
        return sorted(merged.values())

    def all(self) -> set[str]:
        """Return a copy of tracked file paths (original casing)."""
        return set(self._files.values())

    def contains(self, path: str) -> bool:
        """Check if a file path has been tracked (case-insensitive)."""
        normalized = _normalize(path)
        return normalized.lower() in self._files

    def __len__(self) -> int:
        return len(self._files)

    def __repr__(self) -> str:
        return f"GroundingTracker({len(self._files)} files)"
