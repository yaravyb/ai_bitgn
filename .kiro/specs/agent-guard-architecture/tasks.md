# Tasks: agent-guard-architecture

> Generated: 2026-03-24T20:00:00Z
> Status: generated

---

## Task 1: Make GroundingTracker Thread-Safe (P)

Add a `threading.Lock` to `GroundingTracker` so that concurrent dispatch threads can safely read and write tracked file paths without data races. The public API does not change; thread safety is an internal implementation detail.

**Requirements**: 9

### Sub-tasks

- [x] 1.1. Add a `threading.Lock` instance attribute (`_lock`) to `GroundingTracker.__init__` in `sandbox-py/agent/tracker.py`.
- [x] 1.2. Wrap all mutating methods (`add`, `add_many`) and state-dependent read methods (`contains`, `merge`, `all`, `__len__`) with `with self._lock:` blocks, following the lock strategy from the design (pre-compute normalized entries outside the lock in `add_many`; copy `_files` under the lock in `merge`, then merge outside).
- [x] 1.3. Verify that `tracker.py` imports only `threading` and remains a leaf module with zero `agent/` imports.
- [x] 1.4. Add a concurrent thread-safety test class `TestGroundingTrackerThreadSafety` in `sandbox-py/tests/test_tracker.py` that spawns multiple threads calling `add` and `contains` simultaneously and verifies no data loss or corruption.

---

## Task 2: Introduce DispatchContext and Guard Dataclasses

Define the frozen dataclasses (`DispatchContext`, `TaskConstraints`, `TemplateGuardConfig`) in `dispatch.py`, refactor `dispatch_tool` and `dispatch_parallel` to accept a `DispatchContext` parameter instead of separate `source_basename` and `scope_constrained` keyword arguments, remove module-level mutable globals, and extract guard logic into standalone pure functions that read from `DispatchContext`.

**Requirements**: 1, 3, 4

### Sub-tasks

- [x] 2.1. Add the `TemplateGuardConfig`, `TaskConstraints`, and `DispatchContext` frozen dataclasses to the top of `sandbox-py/agent/dispatch.py` as specified in the design (Section 2.1).
- [x] 2.2. Remove the module-level mutable globals `_source_basename` and `_scope_constrained` from `dispatch.py`.
- [x] 2.3. Change the `dispatch_tool` signature to replace `source_basename` and `scope_constrained` parameters with `dispatch_ctx: DispatchContext | None = None`.
- [x] 2.4. Change the `dispatch_parallel` signature to replace `source_basename` and `scope_constrained` parameters with `dispatch_ctx: DispatchContext | None = None`, passing the same frozen context instance to every concurrent `dispatch_tool` invocation.
- [x] 2.5. Extract the basename mismatch guard from `_handle_write_file` into a standalone function `_check_basename_guard(dispatch_ctx, path) -> str | None` that reads from `DispatchContext`.
- [x] 2.6. Extract and rewrite the scope-constrained write guard into `_check_scope_guard(dispatch_ctx, path, tracker) -> str | None` implementing the intent-aware five-step decision logic from the design (allow if not constrained, allow if not tracked, allow if target in `target_directories`, allow if basename matches `source_basename`, else block).
- [x] 2.7. Extract and rewrite the template deletion guard into `_check_template_guard(dispatch_ctx, path) -> str | None` with configurable directory-scoped behavior: when `protected_directories` is non-empty, block only `_`-prefixed files inside those directories; when empty, block all `_`-prefixed files for backward compatibility.
- [x] 2.8. Wire the three guard functions as pre-dispatch checks in `dispatch_tool` (write_file triggers basename and scope guards; delete_file triggers template guard), returning error JSON if any guard blocks.
- [x] 2.9. Add observability logging to each guard function (log allow/block decisions with file path, matched target, and constraint source).
- [x] 2.10. Update all `dispatch_tool` and `dispatch_parallel` call sites in `sandbox-py/agent/loop.py` and `sandbox-py/agent/scout.py` to use `dispatch_ctx` instead of the removed keyword arguments (scout passes `None` since it uses read-only tools).
- [x] 2.11. Update existing tests in `sandbox-py/tests/test_dispatch.py` that used the old `source_basename` / `scope_constrained` keyword arguments to use `dispatch_ctx=DispatchContext(...)`.

---

## Task 3: Add Scout SDK v2 Features (P)

Extend `ScoutConfig` with a configurable `tree_level` field, pass the `level` parameter in the bootstrap tree call, and update the scout prompt to instruct the LLM to use line-range reads for large files.

**Requirements**: 7

### Sub-tasks

- [x] 3.1. Add a `tree_level: int` field to `ScoutConfig` in `sandbox-py/agent/scout.py` with a default value of `3`, configurable via the `SCOUT_TREE_LEVEL` environment variable.
- [x] 3.2. Update the bootstrap `tree("/")` call in `_run_bootstrap()` to pass `{"path": "/", "level": config.tree_level}` as the tool arguments.
- [x] 3.3. Add a prompt instruction in the scout LLM explorer system message directing the model to use `start_line` / `end_line` parameters for files exceeding approximately 200 lines.
- [x] 3.4. Verify that `PcmRuntime.tree()` already passes `level` to `TreeRequest` and that `MiniRuntime.tree()` accepts and gracefully ignores the parameter; document findings as code comments if needed.

---

## Task 4: Externalize Verification Prompt Frame (P)

Move the hardcoded structural prompt content from `verify.py` into an external skill file, add placeholder substitution support to `build_verification_prompt`, and load the template via `SkillLoader` in the executor loop.

**Requirements**: 6

### Sub-tasks

- [x] 4.1. Create the skill file `sandbox-py/skills/verification-frame/SKILL.md` containing the verification frame template with `{{ANSWER}}`, `{{CODE}}`, `{{POLICY_SECTION}}`, `{{CHECKLIST_SECTION}}`, and `{{SOURCE_BASENAME_SECTION}}` placeholders.
- [x] 4.2. Add a `frame_template: str | None = None` parameter to `build_verification_prompt` in `sandbox-py/agent/verify.py`.
- [x] 4.3. Implement placeholder substitution logic: when `frame_template` is provided, replace each `{{...}}` token with the corresponding dynamic content; when `None`, fall back to the current inline frame construction.
- [x] 4.4. Remove hardcoded structural elements (`<verification>` tags, section headings, instruction text) from the inline code path, keeping them only in the skill template and the backward-compatible fallback.
- [x] 4.5. In `sandbox-py/agent/loop.py`, load the `verification-frame` skill via `SkillLoader.get_content("verification-frame")` and pass it to `build_verification_prompt` as the `frame_template` argument.
- [x] 4.6. Add a fallback warning log when the skill file is missing or unreadable, confirming the inline frame is used instead.
- [x] 4.7. Update existing verification prompt tests in `sandbox-py/tests/test_verify.py` to cover both the template-driven path and the fallback path.

---

## Task 5: Implement LLM-Driven Task Constraint Extraction

Replace regex-based task-text parsing (`_extract_source_basename`, `_SCOPE_PHRASES`, `_FILE_PATH_RE`) in `loop.py` with a hybrid extraction approach: a regex fast-path for trivial cases and an LLM fallback for ambiguous tasks, producing a `TaskConstraints` instance that feeds into `DispatchContext`.

**Requirements**: 2

### Sub-tasks

- [x] 5.1. Implement `_extract_task_constraints_regex(task_text) -> TaskConstraints | None` in `sandbox-py/agent/loop.py` that reuses existing regex patterns to extract `source_file` and `scope_level` with high confidence, returning `None` when ambiguous.
- [x] 5.2. Implement `_extract_task_constraints_llm(model, task_text, trace_metadata) -> TaskConstraints` in `sandbox-py/agent/loop.py` that prompts the LLM with the extraction prompt from the design, parses the JSON response, and returns a `TaskConstraints` instance.
- [x] 5.3. Add fail-open error handling in `_extract_task_constraints_llm`: on JSON parse failure or LLM error, return the default `TaskConstraints(source_file=None, scope_level="normal", target_directories=())`.
- [x] 5.4. Wire the hybrid flow into `run_agent()`: call the regex fast-path first, fall back to LLM when it returns `None`, then construct `DispatchContext` from the resulting `TaskConstraints`.
- [x] 5.5. Remove the now-unused `_extract_source_basename()` function, `_FILE_PATH_RE` regex, and `_SCOPE_PHRASES` tuple from `loop.py`.
- [x] 5.6. Add unit tests for both `_extract_task_constraints_regex` (pattern-matched and ambiguous inputs) and `_extract_task_constraints_llm` (valid JSON, malformed JSON, LLM error) in `sandbox-py/tests/test_loop.py` or a new test file.

---

## Task 6: Implement Configurable Template Deletion Guard Logic

Wire the configurable `TemplateGuardConfig` into the `DispatchContext` construction in `loop.py`, reading protected directories from the `TEMPLATE_PROTECTED_DIRS` environment variable, so the template guard enforces directory-scoped protection at runtime.

**Requirements**: 4

### Sub-tasks

- [x] 6.1. In `sandbox-py/agent/loop.py` where `DispatchContext` is constructed, read the `TEMPLATE_PROTECTED_DIRS` environment variable (comma-separated), parse it into a tuple, and pass it as `TemplateGuardConfig(protected_directories=...)`.
- [x] 6.2. Verify end-to-end that deleting a `_`-prefixed file inside a protected directory is blocked, deleting outside is allowed, and an empty config blocks all `_`-prefixed deletions.

---

## Task 7: Add Comprehensive Dispatch Guard Tests

Write unit and integration tests for all guard functions (basename mismatch, scope-constrained write, template deletion) exercising both the standalone guard functions directly and the end-to-end guard behavior through `dispatch_tool`, mocking only the VM adapter.

**Requirements**: 5

### Sub-tasks

- [x] 7.1. Add `TestExtractSlug` test class in `sandbox-py/tests/test_dispatch.py` covering date-prefixed stems, date-only prefix, no prefix, and empty string.
- [x] 7.2. Add `TestIsBasenameMismatch` test class covering exact match, unrelated filenames, inserted segments, empty strings, no extension, and no slug prefix.
- [x] 7.3. Add `TestScopeGuard` test class covering: write blocked when file was read and scope constrained; write allowed when scope not constrained; write allowed when file not read; write allowed when target in `target_directories`.
- [x] 7.4. Add `TestTemplateGuard` test class covering: `_`-prefixed file blocked; non-prefixed allowed; `_`-prefixed in non-protected directory allowed; configuration override; empty config blocks all `_`-prefixed.
- [x] 7.5. Add `TestBasenameMismatchGuard` test class covering: write blocked on mismatch; write allowed on match; write allowed when no source basename set.
- [x] 7.6. Ensure all guard tests also exercise the end-to-end path through `dispatch_tool` with a mocked VM adapter, verifying that the correct error JSON is returned when guards block and that the VM is called when guards allow.
- [x]* 7.7. Add edge-case and regression tests for guard interactions (e.g., scope guard and basename guard both active, template guard with deeply nested protected paths).

---

## Task 8: Update Architecture Documentation

Rewrite `sandbox-py/agent-analysis.md` to reflect all changes from this specification: module structure, PCM outcome codes, embedded skills system, programmatic guard system with `DispatchContext` pattern, SDK v2 features, self-verification loop, context management, and two-phase scout architecture.

**Requirements**: 8

### Sub-tasks

- [x] 8.1. Document the module structure covering all 11 modules with their roles and import constraints (leaf vs. orchestrator).
- [x] 8.2. Document the PCM outcome codes (`OUTCOME_OK`, `OUTCOME_ERR_INTERNAL`, `OUTCOME_NONE_UNSUPPORTED`, `OUTCOME_DENIED_SECURITY`, `OUTCOME_NONE_CLARIFICATION`) and their usage context.
- [x] 8.3. Document the embedded skills system: always-on skills (`security-posture`, `execution-discipline`) vs. on-demand skills (`load_skill`) vs. verification skills (`self-verification`, `verification-frame`).
- [x] 8.4. Document the programmatic guard system: basename mismatch guard, scope-constrained write guard, template deletion guard, protected file guard, with trigger conditions, configuration sources, and decision logic.
- [x] 8.5. Document the `DispatchContext` pattern explaining how guard parameters flow from `TaskConstraints` through `DispatchContext` to guard functions.
- [x] 8.6. Document SDK v2 features (line-range reads, depth-limited trees, PCM-specific tools: `find`, `mkdir`, `move`).
- [x] 8.7. Document the self-verification loop, context management (micro-compact, auto-compact, truncation), and two-phase scout architecture (bootstrap + LLM explorer).
