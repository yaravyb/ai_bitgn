"""Grounding reference tracker.

Pure data module: maintains a set of file paths read during agent execution.
Zero imports from other agent/ modules.

Thread-safe: all operations are synchronized via threading.Lock.
Public interface is unchanged from pre-refactoring version.
"""

from __future__ import annotations

import posixpath
import threading
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

    All operations are synchronized via threading.Lock for safe concurrent
    access from multiple dispatch threads.
    """

    def __init__(self) -> None:
        # Maps normalized-lowercase key -> original-casing path
        self._files: dict[str, str] = {}
        self._lock: threading.Lock = threading.Lock()

    def add(self, path: str) -> None:
        """Add a single file path, normalizing it."""
        normalized = _normalize(path)
        key = normalized.lower()
        with self._lock:
            if key not in self._files:
                self._files[key] = normalized

    def add_many(self, paths: Iterable[str]) -> None:
        """Add multiple file paths.

        Pre-computes normalized entries outside the lock, then acquires
        the lock once for the batch insert to reduce lock hold time.
        """
        # Pre-compute normalized entries outside the lock
        entries: list[tuple[str, str]] = []
        for p in paths:
            normalized = _normalize(p)
            entries.append((normalized.lower(), normalized))
        # Acquire lock once for the batch insert
        with self._lock:
            for key, value in entries:
                if key not in self._files:
                    self._files[key] = value

    def merge(self, llm_refs: list[str]) -> list[str]:
        """Return sorted union of tracked files and LLM-provided refs.

        LLM refs are also normalized. Deduplication is case-insensitive.
        Never returns an empty list if files have been tracked.

        Copies _files under the lock, then merges LLM refs outside
        to avoid holding the lock while processing external data.
        """
        # Copy _files under the lock
        with self._lock:
            merged: dict[str, str] = dict(self._files)
        # Merge LLM refs outside the lock (no mutation to _files)
        for ref in llm_refs:
            normalized = _normalize(ref)
            key = normalized.lower()
            if key not in merged:
                merged[key] = normalized
        return sorted(merged.values())

    def all(self) -> set[str]:
        """Return a copy of tracked file paths (original casing)."""
        with self._lock:
            return set(self._files.values())

    def contains(self, path: str) -> bool:
        """Check if a file path has been tracked (case-insensitive)."""
        normalized = _normalize(path)
        with self._lock:
            return normalized.lower() in self._files

    def __len__(self) -> int:
        with self._lock:
            return len(self._files)

    def __repr__(self) -> str:
        with self._lock:
            return f"GroundingTracker({len(self._files)} files)"
