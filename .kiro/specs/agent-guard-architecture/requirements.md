# Requirements: agent-guard-architecture

> Initialized: 2026-03-24T12:00:00Z
> Status: generated

## Project Description

Refactor programmatic dispatch guards from regex/globals to LLM-driven, thread-safe, testable architecture. Address all gaps identified in the branch review:

1. **Module-level mutable globals** (`_source_basename`, `_scope_constrained`) in dispatch.py -- replace with a `DispatchContext` dataclass passed through function signatures
2. **Task-text parsing** -- regex-based filename extraction and hardcoded scope phrases -- LLM-driven constraint extraction during scout or early executor phase
3. **Scope-constrained write blocking** -- overly aggressive (blocks all writes to read files) -- smarter policy that checks task intent
4. **Template deletion guard** -- unconditional `_`-prefix protection -- configurable, directory-scoped
5. **Missing tests** for `_is_basename_mismatch()`, `_extract_slug()`, scope guards, template protection
6. **verify.py structural frame** still hardcoded -- externalize to skill or template
7. **Scout doesn't use SDK v2 features** -- bootstrap tree should use `level` parameter
8. **agent-analysis.md stale** -- doesn't document any recent changes
9. **Thread safety** -- dispatch guards use module globals that race under `dispatch_parallel()`

---

## Requirement 1: Thread-Safe Dispatch Context

Replace module-level mutable globals (`_source_basename`, `_scope_constrained`) in `dispatch.py` with an explicit, immutable context object passed through function signatures, eliminating thread-safety hazards under concurrent dispatch.

### Acceptance Criteria

1. **The dispatch module shall** define a `DispatchContext` dataclass containing `source_basename: str | None` and `scope_constrained: bool` fields, replacing the module-level `_source_basename` and `_scope_constrained` globals.
2. **When** `dispatch_tool()` is called, **it shall** accept a `DispatchContext` parameter instead of separate `source_basename` and `scope_constrained` keyword arguments.
3. **When** `dispatch_parallel()` is called, **it shall** pass the `DispatchContext` instance to each concurrent `dispatch_tool()` invocation without mutation, so that each thread reads from its own immutable snapshot.
4. **The `DispatchContext` dataclass shall** be frozen (immutable) to guarantee that concurrent threads cannot modify shared state.
5. **The handler functions** (`_handle_write_file`, `_handle_delete_file`) **shall** receive guard parameters from the `DispatchContext` passed through `dispatch_tool()`, not from module-level globals.
6. **After refactoring, the dispatch module shall not** contain any module-level mutable state used by handler functions.
7. **The `loop.py` orchestrator shall** construct a `DispatchContext` once per task and pass it to all dispatch calls, replacing the current pattern of setting module globals before each call.

---

## Requirement 2: LLM-Driven Task Constraint Extraction

Replace regex-based task-text parsing (`_extract_source_basename()`, `_SCOPE_PHRASES`) with structured constraint extraction performed by the LLM during the scout or early executor phase, making constraint detection model-driven rather than pattern-coupled.

### Acceptance Criteria

1. **The system shall** define a `TaskConstraints` data structure containing at minimum: `source_file: str | None` (source file basename), `scope_level: str` (e.g., "focused", "normal"), and `target_directories: list[str]` (allowed write targets).
2. **When** the scout phase or early executor phase processes a task, **the system shall** prompt the LLM to extract structured task constraints and return them as a `TaskConstraints` instance.
3. **The `_extract_source_basename()` function and `_FILE_PATH_RE` regex in `loop.py` shall** be removed and replaced with the LLM-extracted `source_file` field from `TaskConstraints`.
4. **The `_SCOPE_PHRASES` tuple in `loop.py` shall** be removed and replaced with the LLM-extracted `scope_level` field from `TaskConstraints`.
5. **The extracted `TaskConstraints` shall** be passed into `DispatchContext` (Requirement 1), making constraint data available to all guard functions without global state.
6. **When** the LLM fails to extract constraints or returns an empty result, **the system shall** default to `TaskConstraints(source_file=None, scope_level="normal", target_directories=[])`, which disables all constraint-based guards (fail-open for constraint extraction).

---

## Requirement 3: Intent-Aware Scope Guard

Replace the over-aggressive scope-constrained write guard (which blocks ALL writes to previously-read files) with a smarter guard that understands task intent, allowing legitimate read-modify-write workflows while still preventing unrequested changes.

### Acceptance Criteria

1. **When** scope is constrained and a write is attempted to a previously-read file, **the scope guard shall** check whether the file is listed in `TaskConstraints.target_directories` or matches the task's `source_file` before blocking.
2. **When** the write target matches a file or directory explicitly mentioned as a task target in `TaskConstraints`, **the scope guard shall** allow the write even if the file was previously read.
3. **When** the write target does NOT match any task target and scope is constrained and the file was previously read, **the scope guard shall** block the write and return a descriptive error message.
4. **The scope guard shall** log the decision (allow or block) with the file path, the matched target (if allowed), and the constraint source for observability.
5. **The scope guard shall not** require any module-level mutable state; all inputs (scope constraint status, target directories, tracker) come from the `DispatchContext` or function parameters.

---

## Requirement 4: Configurable Template Deletion Guard

Replace the unconditional `_`-prefix deletion protection with a configurable, directory-scoped guard that can be overridden when legitimate deletion of `_`-prefixed files is required.

### Acceptance Criteria

1. **The template deletion guard shall** support a configuration parameter that specifies which directory paths are protected (e.g., only files under `/templates/` or `/structural/`).
2. **When** a delete targets a `_`-prefixed file inside a protected directory, **the guard shall** block the deletion and return an error message.
3. **When** a delete targets a `_`-prefixed file outside any protected directory, **the guard shall** allow the deletion.
4. **When** no protected directories are configured, **the guard shall** default to the current behavior (block all `_`-prefixed file deletions) for backward compatibility.
5. **The guard configuration shall** be part of the `DispatchContext` or a separate configuration object passed through `dispatch_tool()`, not hardcoded in the handler function.
6. **The guard shall** log each decision (block or allow) with the file path and the applicable configuration for observability.

---

## Requirement 5: Dispatch Guard Test Coverage

Add comprehensive unit tests for all dispatch guard functions that currently have zero test coverage, ensuring each guard behavior is verified in isolation.

### Acceptance Criteria

1. **The test suite shall** include tests for `_is_basename_mismatch()` covering: exact match (returns False), unrelated filenames (returns False), same slug with inserted segments (returns True), and edge cases (empty strings, no extension, no slug prefix).
2. **The test suite shall** include tests for `_extract_slug()` covering: date-prefixed stems (`2026-03-23__0000__hn-foo` returns `hn-foo`), date-only prefix (`2026-03-23__hn-foo` returns `hn-foo`), no prefix (`report` returns `report`), and empty string.
3. **The test suite shall** include tests for the scope-constrained write guard covering: write blocked when file was previously read and scope is constrained, write allowed when scope is not constrained, write allowed when file was not previously read, and write allowed when target is in the task's allowed targets (Requirement 3).
4. **The test suite shall** include tests for the template deletion guard covering: `_`-prefixed file blocked, non-prefixed file allowed, `_`-prefixed file in non-protected directory allowed (Requirement 4), and configuration override behavior.
5. **The test suite shall** include tests for the basename mismatch write guard covering: write blocked when basename mismatch detected, write allowed when basenames match, and write allowed when no source basename is set.
6. **All guard test functions shall** be unit tests that mock only the VM adapter, not internal guard functions, to ensure end-to-end guard behavior is verified through `dispatch_tool()`.

---

## Requirement 6: Externalized Verification Prompt Frame

Move the structural prompt content in `verify.py` (`<verification>` tags, `## Proposed Answer`, `## Instructions` sections) to an external skill file or template, so that the verification prompt structure is configurable without code changes.

### Acceptance Criteria

1. **The verification prompt frame shall** be defined in an external file (skill markdown or template) rather than hardcoded as string literals in `build_verification_prompt()`.
2. **The `build_verification_prompt()` function shall** accept the frame template as a parameter or load it from a configurable path, with a hardcoded fallback for backward compatibility if the external file is missing.
3. **The external frame shall** support placeholder substitution for dynamic content: the proposed answer, outcome code, policy file contents, checklist body, and source basename check.
4. **When** the external verification frame file is missing or unreadable, **the system shall** fall back to the current inline frame without error, logging a warning.
5. **The verification prompt's structural elements** (`<verification>` / `</verification>` tags, section headings, instruction text) **shall not** be hardcoded in Python source after this refactoring.

---

## Requirement 7: Scout SDK v2 Integration

Update the scout phase to leverage SDK v2 features, specifically depth-limited directory trees and line-range file reads, to reduce token consumption and improve exploration precision.

### Acceptance Criteria

1. **When** the bootstrap phase calls `tree("/")`, **it shall** pass a `level` parameter to limit tree depth (e.g., `level=2` for top two levels), reducing the initial token cost for large workspaces.
2. **The `level` parameter value shall** be configurable via `ScoutConfig` or environment variable, with a sensible default (e.g., `level=3`).
3. **When** the scout LLM explorer reads large files, **it shall** use `start_line` and `end_line` parameters to read only relevant sections rather than entire files, when the file is known to be large from prior tree or list output.
4. **The `MiniRuntime` adapter shall** pass the `level` parameter to the underlying SDK if the SDK supports it, or ignore it gracefully if not.
5. **The `PcmRuntime` adapter shall** pass the `level` parameter to the `TreeRequest` (already supported in the current codebase -- verify it is used in the scout bootstrap path).

---

## Requirement 8: Architecture Documentation Update

Update `agent-analysis.md` to reflect all changes from the current branch and this specification, providing an accurate reference for the current system architecture.

### Acceptance Criteria

1. **The documentation shall** describe the current module structure including all modules (`loop.py`, `dispatch.py`, `scout.py`, `verify.py`, `tracker.py`, `tools.py`, `prompt.py`, `runtime.py`, `context.py`, `skills.py`, `llm.py`).
2. **The documentation shall** describe the PCM outcome codes (`OUTCOME_OK`, `OUTCOME_ERR_INTERNAL`, `OUTCOME_NONE_UNSUPPORTED`, `OUTCOME_DENIED_SECURITY`, `OUTCOME_NONE_CLARIFICATION`) and how they are used.
3. **The documentation shall** describe the embedded skills system (always-on skills like `security-posture`, `execution-discipline` vs. on-demand skills loaded via `load_skill` tool).
4. **The documentation shall** describe the programmatic guard system: basename mismatch guard, scope-constrained write guard, template deletion guard, protected file guard, and how they are configured and triggered.
5. **The documentation shall** describe the `DispatchContext` pattern (after Requirement 1 is implemented), explaining how guard parameters flow through the dispatch chain.
6. **The documentation shall** describe SDK v2 features used (line-range reads, depth-limited trees, PCM-specific tools: `find`, `mkdir`, `move`).
7. **The documentation shall** describe the self-verification loop, context management (micro-compact, auto-compact, truncation), and the two-phase scout architecture (bootstrap + LLM explorer).

---

## Requirement 9: Thread-Safe Grounding Tracker

Make `GroundingTracker` thread-safe so that concurrent dispatch threads can safely add file paths and query the tracker without data races.

### Acceptance Criteria

1. **The `GroundingTracker` class shall** use a threading lock to synchronize all mutating operations (`add()`, `add_many()`) and read operations that depend on consistent state (`contains()`, `merge()`, `all()`, `__len__()`).
2. **When** multiple threads call `add()` concurrently, **the tracker shall** guarantee that no path is lost and no duplicate is introduced due to a race condition.
3. **When** one thread calls `contains()` while another calls `add()`, **the tracker shall** return a consistent result (either the path is fully present or fully absent, no partial state).
4. **The thread-safety implementation shall not** introduce deadlocks or significant performance degradation for the typical workload (fewer than 100 concurrent operations per task).
5. **The `GroundingTracker` shall** remain a leaf module with zero imports from other `agent/` modules after the thread-safety addition.
6. **The test suite shall** include a concurrent test that spawns multiple threads calling `add()` and `contains()` simultaneously and verifies no data corruption occurs.
