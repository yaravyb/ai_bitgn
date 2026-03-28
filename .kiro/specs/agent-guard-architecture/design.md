# Design: agent-guard-architecture

> Refactor programmatic dispatch guards from regex/globals to LLM-driven, thread-safe, testable architecture. Replace mutable globals with a frozen DispatchContext dataclass, introduce LLM-driven constraint extraction via TaskConstraints, make GroundingTracker thread-safe, externalize the verification prompt frame, and add comprehensive guard test coverage.

## Status: Generated

---

## 1. Architecture Overview

This design addresses nine requirements spanning four architectural concerns: (A) thread-safe state management for dispatch guards, (B) LLM-driven task constraint extraction replacing regex heuristics, (C) configurable guard policies, and (D) externalization of hardcoded prompt structures. All changes preserve the existing **leaf/orchestrator module pattern**: `dispatch.py`, `tracker.py`, `verify.py`, `prompt.py`, `context.py`, `tools.py`, `skills.py`, `runtime.py`, and `llm.py` remain leaf modules with zero `agent/` cross-imports; `loop.py` and `scout.py` remain the only orchestrator modules.

The core transformation replaces module-level mutable globals (`_source_basename`, `_scope_constrained`) in `dispatch.py` with an explicit, immutable `DispatchContext` frozen dataclass. Guard parameters flow through function signatures rather than module state, eliminating thread-safety hazards under `dispatch_parallel()`. Task constraints (source file, scope level, target directories) are extracted by the LLM during the scout or early executor phase and materialized as a `TaskConstraints` frozen dataclass, which feeds into `DispatchContext`.

```
+--------------------------------------------------------------------+
|                         loop.py (orchestrator)                      |
|                                                                     |
|  1. Scout phase -> run_scout() returns ScoutSummary                 |
|  2. Constraint extraction (new):                                    |
|     - Prompt LLM to extract TaskConstraints from task_text          |
|     - Fallback: regex fast-path for trivial cases                   |
|  3. Build DispatchContext (frozen, immutable):                       |
|     - source_basename from TaskConstraints.source_file              |
|     - scope_constrained from TaskConstraints.scope_level            |
|     - target_directories from TaskConstraints.target_directories    |
|     - template_guard_config from environment / ScoutConfig          |
|  4. Pass DispatchContext to all dispatch_tool / dispatch_parallel    |
|                                                                     |
|  +-------------------------------+  +----------------------------+  |
|  | dispatch_tool(vm, name, args, |  | dispatch_parallel(vm, tcs, |  |
|  |   tracker, protected,         |  |   tracker, protected,      |  |
|  |   ctx: DispatchContext)        |  |   ctx: DispatchContext)     |  |
|  +-------------------------------+  +----------------------------+  |
|                  |                              |                    |
|                  v                              v                    |
|  +--------------------------------------------------------------+   |
|  |                    dispatch.py (leaf module)                  |   |
|  |                                                              |   |
|  |  DispatchContext (frozen dataclass):                          |   |
|  |    source_basename: str | None                               |   |
|  |    scope_constrained: bool                                   |   |
|  |    target_directories: tuple[str, ...]                       |   |
|  |    template_guard_config: TemplateGuardConfig                |   |
|  |                                                              |   |
|  |  Guards read from DispatchContext, not module globals:        |   |
|  |    _handle_write_file: basename mismatch + scope guard       |   |
|  |    _handle_delete_file: protected + template guard           |   |
|  |                                                              |   |
|  |  No module-level mutable state.                              |   |
|  +--------------------------------------------------------------+   |
|                                                                     |
|  +-------------------------------+  +----------------------------+  |
|  | tracker.py (leaf module)      |  | verify.py (leaf module)    |  |
|  |                               |  |                            |  |
|  | GroundingTracker:             |  | build_verification_prompt  |  |
|  |   _lock: threading.Lock      |  |   accepts frame_template   |  |
|  |   add/contains/merge/all     |  |   parameter; loads from    |  |
|  |   all synchronized via lock  |  |   skill or uses fallback   |  |
|  +-------------------------------+  +----------------------------+  |
+--------------------------------------------------------------------+

+--------------------------------------------------------------------+
|                    New data structures (dispatch.py)                 |
|                                                                     |
|  @dataclass(frozen=True)                                            |
|  class TaskConstraints:                                             |
|      source_file: str | None                                        |
|      scope_level: str           # "focused" | "normal"              |
|      target_directories: tuple[str, ...]                            |
|                                                                     |
|  @dataclass(frozen=True)                                            |
|  class TemplateGuardConfig:                                         |
|      protected_directories: tuple[str, ...]                         |
|                                                                     |
|  @dataclass(frozen=True)                                            |
|  class DispatchContext:                                              |
|      source_basename: str | None                                    |
|      scope_constrained: bool                                        |
|      target_directories: tuple[str, ...]                            |
|      template_guard_config: TemplateGuardConfig                     |
+--------------------------------------------------------------------+
```

### Module Dependency Map (Post-Refactoring)

```
loop.py ─────────────> dispatch.py ──> tracker.py
   │                       │           (GroundingTracker + Lock)
   │                       │──> llm.py (ToolCall type only)
   │                       │──> context.py (ContextConfig, truncation)
   │                       │
   ├───> scout.py ────────>│ (dispatch_tool, dispatch_parallel)
   │        │──> llm.py    │
   │        │──> prompt.py │
   │        │──> tools.py  │
   │        │──> tracker.py│
   │        │──> context.py│
   │                       │
   ├───> verify.py         │  (pure functions, zero agent/ imports)
   ├───> prompt.py         │  (pure functions, zero agent/ imports)
   ├───> skills.py         │  (SkillLoader, zero agent/ imports)
   ├───> tracker.py        │  (GroundingTracker, zero agent/ imports)
   ├───> tools.py          │  (schemas, zero agent/ imports)
   ├───> context.py        │  (ContextConfig, zero agent/ imports)
   └───> llm.py            │  (call_llm, zero agent/ imports)
```

No new module-level import cycles are introduced. `dispatch.py` gains no new `agent/` imports. The `DispatchContext`, `TaskConstraints`, and `TemplateGuardConfig` dataclasses live in `dispatch.py` as they are consumed exclusively by dispatch guard logic.

---

## 2. Component Design

### 2.1 DispatchContext and Guard Dataclasses (Req 1)

**Location**: `sandbox-py/agent/dispatch.py`

**Rationale**: The dataclasses are consumed only by dispatch guard functions and the dispatch entry points (`dispatch_tool`, `dispatch_parallel`). Placing them in `dispatch.py` keeps the module self-contained and avoids introducing a new module solely for two small dataclasses.

```
@dataclass(frozen=True)
class TemplateGuardConfig:
    """Configuration for the template deletion guard.

    When protected_directories is empty, the guard defaults to blocking
    all _-prefixed file deletions (backward compatibility).
    """
    protected_directories: tuple[str, ...] = ()

@dataclass(frozen=True)
class TaskConstraints:
    """Structured task constraints extracted by LLM or regex fast-path.

    Immutable value object. Default values disable all constraint-based
    guards (fail-open).
    """
    source_file: str | None = None
    scope_level: str = "normal"            # "focused" | "normal"
    target_directories: tuple[str, ...] = ()

@dataclass(frozen=True)
class DispatchContext:
    """Immutable per-task guard configuration passed through dispatch calls.

    Constructed once per task by loop.py. Passed by reference to
    dispatch_tool() and dispatch_parallel(). Each concurrent thread
    reads from this frozen snapshot without mutation.
    """
    source_basename: str | None = None
    scope_constrained: bool = False
    target_directories: tuple[str, ...] = ()
    template_guard_config: TemplateGuardConfig = TemplateGuardConfig()
```

**Construction in loop.py**:
```
# After constraint extraction:
ctx = DispatchContext(
    source_basename=constraints.source_file,
    scope_constrained=(constraints.scope_level == "focused"),
    target_directories=constraints.target_directories,
    template_guard_config=TemplateGuardConfig(
        protected_directories=tuple(protected_dirs)
    ),
)
```

**Traceability**: Req 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7

### 2.2 dispatch_tool() Signature Change (Req 1)

**Current signature**:
```
def dispatch_tool(
    vm, tool_name, args, tracker, protected_files,
    skill_loader=None, context_config=None,
    source_basename=None, scope_constrained=False,
) -> str
```

**New signature**:
```
def dispatch_tool(
    vm,
    tool_name: str,
    args: dict[str, Any],
    tracker: GroundingTracker,
    protected_files: set[str],
    skill_loader: Any | None = None,
    context_config: ContextConfig | None = None,
    dispatch_ctx: DispatchContext | None = None,
) -> str
```

The `source_basename` and `scope_constrained` keyword arguments are replaced by a single `dispatch_ctx: DispatchContext | None` parameter. When `dispatch_ctx` is `None`, all guards that depend on context data are disabled (backward-compatible default). The module-level globals `_source_basename` and `_scope_constrained` are removed entirely.

**dispatch_parallel() follows the same pattern**: the `source_basename` and `scope_constrained` parameters are replaced by `dispatch_ctx`.

**Handler signature remains unchanged**: Handlers still receive `(vm, args, tracker, protected_files, skill_loader)`. The `dispatch_tool()` function reads guard parameters from `dispatch_ctx` before calling the handler, and passes relevant data to the handler via a closure or by checking context after the handler returns. For the write and delete guards, the guard logic moves into `dispatch_tool()` as pre-dispatch checks rather than being embedded inside handlers, enabling handlers to remain context-unaware.

**Traceability**: Req 1.2, 1.3, 1.5, 1.6

### 2.3 Guard Logic Refactoring (Req 1, 3, 4)

Guards currently embedded in `_handle_write_file` and `_handle_delete_file` are restructured as standalone pure functions called by `dispatch_tool()` before dispatching to the handler. This separates guard logic from tool execution, making guards independently testable.

**Guard functions in dispatch.py**:

```
def _check_basename_guard(
    dispatch_ctx: DispatchContext,
    path: str,
) -> str | None:
    """Return error message if basename mismatch detected, else None."""

def _check_scope_guard(
    dispatch_ctx: DispatchContext,
    path: str,
    tracker: GroundingTracker,
) -> str | None:
    """Return error message if scope-constrained write is blocked, else None.

    Intent-aware: allows writes when the target matches a directory
    or file listed in dispatch_ctx.target_directories.
    """

def _check_template_guard(
    dispatch_ctx: DispatchContext,
    path: str,
) -> str | None:
    """Return error message if template deletion is blocked, else None.

    Configurable: when protected_directories is non-empty, only blocks
    _-prefixed files inside those directories. When empty, blocks all
    _-prefixed files (backward compat).
    """
```

**Guard invocation in dispatch_tool()**:
```
if dispatch_ctx is not None:
    if tool_name == "write_file":
        path = args.get("path", "")
        error = _check_basename_guard(dispatch_ctx, path)
        if error:
            log.warning("BLOCKED: write_file %s (basename mismatch)", path)
            return json.dumps({"error": error}, ensure_ascii=False)
        error = _check_scope_guard(dispatch_ctx, path, tracker)
        if error:
            log.warning("BLOCKED: write_file %s (scope constrained)", path)
            return json.dumps({"error": error}, ensure_ascii=False)
    elif tool_name == "delete_file":
        path = args.get("path", "")
        error = _check_template_guard(dispatch_ctx, path)
        if error:
            log.warning("BLOCKED: delete_file %s (template guard)", path)
            return json.dumps({"error": error}, ensure_ascii=False)
```

**Scope Guard Intent-Awareness (Req 3)**:

The `_check_scope_guard` function implements the following decision logic:

```
1. If not scope_constrained: ALLOW (no constraint active)
2. If file not in tracker: ALLOW (not previously read)
3. If file path starts with any target_directory: ALLOW (task target)
4. If file basename matches source_basename: ALLOW (source file)
5. Otherwise: BLOCK and return descriptive error
```

Each decision is logged with the file path, matched target (if allowed), and constraint source for observability.

**Template Guard Configurability (Req 4)**:

```
1. If basename does not start with "_": ALLOW
2. If protected_directories is empty: BLOCK (backward compat default)
3. If file path is inside any protected_directory: BLOCK
4. Otherwise: ALLOW (not in protected scope)
```

**Traceability**: Req 1.5, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6

### 2.4 LLM-Driven Task Constraint Extraction (Req 2)

**Location**: `sandbox-py/agent/loop.py` (constraint extraction orchestration)

**Approach**: Hybrid (regex fast-path + LLM fallback). The regex fast-path preserves backward compatibility and avoids adding latency for simple tasks. The LLM path activates only when the fast-path returns empty or the task text is ambiguous.

**New function in loop.py**:

```
def _extract_task_constraints_regex(task_text: str) -> TaskConstraints | None:
    """Fast-path: attempt regex-based constraint extraction.

    Returns TaskConstraints if high-confidence extraction succeeds,
    None if the task text is ambiguous or no patterns match.
    """

async def _extract_task_constraints_llm(
    model: str,
    task_text: str,
    trace_metadata: dict[str, Any],
) -> TaskConstraints:
    """LLM-path: prompt the model to extract structured constraints.

    Returns TaskConstraints parsed from LLM response. Falls back to
    default TaskConstraints on parse failure.
    """
```

**Note**: `_extract_task_constraints_llm` uses `call_llm` synchronously (the `async` qualifier in the interface description is for clarity; the actual implementation uses the existing synchronous `call_llm` wrapper).

**LLM Extraction Prompt Structure**:

```
Extract task constraints from the following task instruction.
Return a JSON object with these fields:
- "source_file": basename of the primary source file (string or null)
- "scope_level": "focused" if the task restricts modifications, "normal" otherwise
- "target_directories": list of directory paths or file paths that the task
  explicitly allows modifications to

Task:
<task>
{task_text}
</task>

Respond with ONLY the JSON object, no additional text.
```

**Extraction flow in loop.py run_agent()**:

```
# Replace _extract_source_basename() and _SCOPE_PHRASES with:
constraints = _extract_task_constraints_regex(task_text)
if constraints is None:
    constraints = _extract_task_constraints_llm(
        executor_model, task_text, trace_metadata
    )

# Build DispatchContext from constraints
ctx = DispatchContext(
    source_basename=constraints.source_file,
    scope_constrained=(constraints.scope_level == "focused"),
    target_directories=constraints.target_directories,
    template_guard_config=TemplateGuardConfig(
        protected_directories=tuple(
            os.environ.get("TEMPLATE_PROTECTED_DIRS", "").split(",")
        ) if os.environ.get("TEMPLATE_PROTECTED_DIRS") else ()
    ),
)
```

**Regex fast-path heuristics** (retained from current codebase, enhanced):
1. `_FILE_PATH_RE` pattern extracts `source_file` (basename of first file path match).
2. `_SCOPE_PHRASES` tuple detects `scope_level = "focused"`.
3. If both are resolved with high confidence, returns `TaskConstraints` directly.
4. Returns `None` if either extraction is ambiguous.

**Fail-open default** (Req 2.6): When the LLM fails to extract constraints or returns an unparseable result, the system defaults to `TaskConstraints(source_file=None, scope_level="normal", target_directories=())`, which disables all constraint-based guards.

**Traceability**: Req 2.1, 2.2, 2.3, 2.4, 2.5, 2.6

### 2.5 Thread-Safe GroundingTracker (Req 9)

**Location**: `sandbox-py/agent/tracker.py`

**Approach**: Add a `threading.Lock` instance to `GroundingTracker`. All mutating operations (`add`, `add_many`) and read operations that depend on consistent state (`contains`, `merge`, `all`, `__len__`) acquire the lock before accessing `self._files`.

**Interface changes**: None. The public API remains identical. Thread safety is an internal implementation detail.

```
import threading

class GroundingTracker:
    def __init__(self) -> None:
        self._files: dict[str, str] = {}
        self._lock: threading.Lock = threading.Lock()

    def add(self, path: str) -> None:
        normalized = _normalize(path)
        key = normalized.lower()
        with self._lock:
            if key not in self._files:
                self._files[key] = normalized

    def add_many(self, paths: Iterable[str]) -> None:
        # Batch lock acquisition for efficiency
        entries: list[tuple[str, str]] = []
        for p in paths:
            normalized = _normalize(p)
            entries.append((normalized.lower(), normalized))
        with self._lock:
            for key, value in entries:
                if key not in self._files:
                    self._files[key] = value

    def contains(self, path: str) -> bool:
        normalized = _normalize(path)
        with self._lock:
            return normalized.lower() in self._files

    def merge(self, llm_refs: list[str]) -> list[str]:
        with self._lock:
            merged: dict[str, str] = dict(self._files)
        # LLM ref merging happens outside the lock (no mutation to _files)
        for ref in llm_refs:
            normalized = _normalize(ref)
            key = normalized.lower()
            if key not in merged:
                merged[key] = normalized
        return sorted(merged.values())

    def all(self) -> set[str]:
        with self._lock:
            return set(self._files.values())

    def __len__(self) -> int:
        with self._lock:
            return len(self._files)
```

**Design decisions**:
- Lock granularity: One lock per `GroundingTracker` instance (no global lock).
- `add_many()` pre-computes normalized entries outside the lock, then acquires the lock once for the batch insert, reducing lock hold time.
- `merge()` copies `_files` under the lock, then merges LLM refs outside the lock. This prevents holding the lock while processing external data.
- The lock is a `threading.Lock` (not `RLock`) because no method calls another locked method internally.

**Traceability**: Req 9.1, 9.2, 9.3, 9.4, 9.5

### 2.6 Externalized Verification Prompt Frame (Req 6)

**Location**: `sandbox-py/agent/verify.py` (modified), `sandbox-py/skills/verification-frame/SKILL.md` (new)

**Approach**: Skill-based. A new `verification-frame` skill contains the structural frame template. `build_verification_prompt()` accepts an optional `frame_template` parameter. When provided, it performs placeholder substitution. When absent, the function falls back to the current inline frame (backward compatibility).

**New skill file** `sandbox-py/skills/verification-frame/SKILL.md`:

```yaml
---
name: verification-frame
description: Structural frame template for the self-verification prompt. Contains placeholders for dynamic content injection.
---
```

The skill body contains the verification frame with placeholders:

```
<verification>
You are about to submit the following answer. Before submitting, verify it is correct.

## Proposed Answer
Code: {{CODE}}
Answer: {{ANSWER}}

{{POLICY_SECTION}}

{{CHECKLIST_SECTION}}

{{SOURCE_BASENAME_SECTION}}

## Instructions
- If the answer is correct, use the report_completion tool with the SAME answer and code.
- If the answer needs correction, use the report_completion tool with the CORRECTED answer.
- You may use other tools (read_file, list_dir, etc.) to verify file operations before submitting.
- IMPORTANT: Submit ONLY by calling the report_completion tool. Do NOT write the answer as plain text or JSON.
</verification>
```

**Modified build_verification_prompt() signature**:

```
def build_verification_prompt(
    answer: str,
    code: str,
    policy_contents: dict[str, str],
    checklist_body: str = "",
    source_basename: str | None = None,
    frame_template: str | None = None,
) -> str:
```

**Substitution logic**:
- `{{ANSWER}}` -> answer text
- `{{CODE}}` -> outcome code
- `{{POLICY_SECTION}}` -> formatted policy file contents (or empty string)
- `{{CHECKLIST_SECTION}}` -> checklist body (or empty string)
- `{{SOURCE_BASENAME_SECTION}}` -> source filename check section (or empty string)

**Fallback behavior**: When `frame_template is None` or empty, the function uses the current inline frame construction (existing code path). A warning is logged when the template is missing.

**Loading in loop.py**: The `verification-frame` skill is loaded via `SkillLoader.get_content("verification-frame")` alongside the existing `self-verification` checklist loading. The frame body is passed to `build_verification_prompt()` as the `frame_template` parameter.

**Traceability**: Req 6.1, 6.2, 6.3, 6.4, 6.5

### 2.7 Scout SDK v2 Integration (Req 7)

**Location**: `sandbox-py/agent/scout.py` (modified)

**Changes**:

1. **Bootstrap tree depth**: The `_run_bootstrap()` function currently calls `dispatch_tool(vm, "tree", {"path": "/"}, ...)`. The `level` parameter is added:
   ```
   tree_level = config.tree_level  # New field on ScoutConfig, default 3
   tree_result = dispatch_tool(
       vm, "tree", {"path": "/", "level": tree_level}, ...
   )
   ```

2. **ScoutConfig extension**:
   ```
   @dataclass
   class ScoutConfig:
       model: str
       task_instruction: str
       max_steps: int = 20
       max_workers: int = 4
       tree_level: int = int(os.environ.get("SCOUT_TREE_LEVEL", "3"))
   ```

3. **Line-range reads**: The LLM explorer already has access to `read_file` with `start_line` and `end_line` parameters in the tool schema. The scout prompt is updated to instruct the LLM to use line-range reads for large files:
   ```
   "8. For files exceeding ~200 lines (visible from tree/list output), "
   "use start_line/end_line parameters to read only relevant sections."
   ```

4. **Runtime adapter verification**:
   - `PcmRuntime.tree()` already passes `level` to `TreeRequest(root=path, level=level)` -- verified in current codebase.
   - `MiniRuntime.tree()` currently calls `self._vm.outline(OutlineRequest(path=path))` and ignores `level`. The `level` parameter is accepted but ignored gracefully (no change needed, the parameter already exists in the signature).

**Traceability**: Req 7.1, 7.2, 7.3, 7.4, 7.5

### 2.8 Dispatch Guard Test Coverage (Req 5)

**Location**: `sandbox-py/tests/test_dispatch.py` (extended)

**Test classes to add**:

```
class TestExtractSlug:
    """Req 5.2: Tests for _extract_slug()."""
    def test_date_prefixed_stem() -> None: ...
    def test_date_only_prefix() -> None: ...
    def test_no_prefix() -> None: ...
    def test_empty_string() -> None: ...

class TestIsBasenameMismatch:
    """Req 5.1: Tests for _is_basename_mismatch()."""
    def test_exact_match_returns_false() -> None: ...
    def test_unrelated_filenames_returns_false() -> None: ...
    def test_inserted_segments_returns_true() -> None: ...
    def test_empty_source_basename() -> None: ...
    def test_no_extension() -> None: ...
    def test_no_slug_prefix() -> None: ...

class TestScopeGuard:
    """Req 5.3: Tests for scope-constrained write guard."""
    def test_blocked_when_read_and_scope_constrained() -> None: ...
    def test_allowed_when_scope_not_constrained() -> None: ...
    def test_allowed_when_file_not_read() -> None: ...
    def test_allowed_when_target_in_task_targets() -> None: ...

class TestTemplateGuard:
    """Req 5.4: Tests for template deletion guard."""
    def test_underscore_prefixed_blocked() -> None: ...
    def test_non_prefixed_allowed() -> None: ...
    def test_underscore_in_non_protected_dir_allowed() -> None: ...
    def test_config_override_behavior() -> None: ...
    def test_empty_config_blocks_all_underscore() -> None: ...

class TestBasenameMismatchGuard:
    """Req 5.5: Tests for basename mismatch write guard through dispatch_tool."""
    def test_blocked_when_mismatch_detected() -> None: ...
    def test_allowed_when_basenames_match() -> None: ...
    def test_allowed_when_no_source_basename() -> None: ...
```

**Test strategy** (Req 5.6): All guard tests exercise the guard behavior through `dispatch_tool()`, mocking only the `vm` RuntimeAdapter. Internal guard functions are also tested directly for edge cases. This provides both unit-level coverage and end-to-end guard verification.

**New concurrent test for GroundingTracker** (in `sandbox-py/tests/test_tracker.py`):

```
class TestGroundingTrackerThreadSafety:
    """Req 9.6: Concurrent add/contains test."""
    def test_concurrent_add_no_data_loss() -> None:
        """Spawn N threads each adding unique paths. Verify all paths present."""
    def test_concurrent_add_contains_no_corruption() -> None:
        """Spawn threads mixing add() and contains() calls. No exceptions."""
```

**Traceability**: Req 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 9.6

### 2.9 Architecture Documentation Update (Req 8)

**Location**: `sandbox-py/agent-analysis.md` (rewritten)

**Sections to document**:

1. Module structure: all 11 modules with their role and import constraints.
2. PCM outcome codes: `OUTCOME_OK`, `OUTCOME_ERR_INTERNAL`, `OUTCOME_NONE_UNSUPPORTED`, `OUTCOME_DENIED_SECURITY`, `OUTCOME_NONE_CLARIFICATION` with usage context.
3. Embedded skills system: always-on (`security-posture`, `execution-discipline`) vs. on-demand (`load_skill` tool) vs. verification skills (`self-verification`, `verification-frame`).
4. Programmatic guard system: basename mismatch guard, scope-constrained write guard, template deletion guard, protected file guard. Each guard's trigger condition, configuration source, and decision logic.
5. DispatchContext pattern: how guard parameters flow from `TaskConstraints` through `DispatchContext` to guard functions in the dispatch chain.
6. SDK v2 features: line-range reads, depth-limited trees, PCM-specific tools (`find`, `mkdir`, `move`).
7. Self-verification loop, context management (micro-compact, auto-compact, truncation), and two-phase scout architecture (bootstrap + LLM explorer).

**Traceability**: Req 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7

---

## 3. Interface Contracts

### 3.1 DispatchContext (dispatch.py)

```python
@dataclass(frozen=True)
class TemplateGuardConfig:
    """Configuration for directory-scoped template deletion guard."""
    protected_directories: tuple[str, ...] = ()

@dataclass(frozen=True)
class TaskConstraints:
    """LLM-extracted or regex-extracted task constraints."""
    source_file: str | None = None
    scope_level: str = "normal"
    target_directories: tuple[str, ...] = ()

@dataclass(frozen=True)
class DispatchContext:
    """Frozen per-task guard configuration. Thread-safe by immutability."""
    source_basename: str | None = None
    scope_constrained: bool = False
    target_directories: tuple[str, ...] = ()
    template_guard_config: TemplateGuardConfig = TemplateGuardConfig()
```

### 3.2 dispatch_tool() (dispatch.py)

```python
def dispatch_tool(
    vm: RuntimeAdapter,
    tool_name: str,
    args: dict[str, Any],
    tracker: GroundingTracker,
    protected_files: set[str],
    skill_loader: Any | None = None,
    context_config: ContextConfig | None = None,
    dispatch_ctx: DispatchContext | None = None,
) -> str:
    """Dispatch a single tool call with guard enforcement.

    Pre-dispatch guard checks are performed when dispatch_ctx is provided.
    Returns error JSON string if a guard blocks the operation.
    """
```

### 3.3 dispatch_parallel() (dispatch.py)

```python
def dispatch_parallel(
    vm: RuntimeAdapter,
    tool_calls: list[ToolCall],
    tracker: GroundingTracker,
    protected_files: set[str],
    skill_loader: Any | None = None,
    max_workers: int = 4,
    context_config: ContextConfig | None = None,
    dispatch_ctx: DispatchContext | None = None,
) -> list[tuple[str, str]]:
    """Execute multiple tool calls concurrently with shared DispatchContext.

    Each thread receives the same frozen DispatchContext snapshot.
    """
```

### 3.4 Guard Functions (dispatch.py)

```python
def _check_basename_guard(
    dispatch_ctx: DispatchContext,
    path: str,
) -> str | None:
    """Check basename mismatch guard. Returns error string or None."""

def _check_scope_guard(
    dispatch_ctx: DispatchContext,
    path: str,
    tracker: GroundingTracker,
) -> str | None:
    """Check intent-aware scope guard. Returns error string or None."""

def _check_template_guard(
    dispatch_ctx: DispatchContext,
    path: str,
) -> str | None:
    """Check configurable template deletion guard. Returns error string or None."""
```

### 3.5 Constraint Extraction (loop.py)

```python
def _extract_task_constraints_regex(task_text: str) -> TaskConstraints | None:
    """Regex fast-path for task constraint extraction.

    Returns TaskConstraints if high-confidence extraction succeeds.
    Returns None if task text is ambiguous (triggers LLM fallback).
    """

def _extract_task_constraints_llm(
    model: str,
    task_text: str,
    trace_metadata: dict[str, Any],
) -> TaskConstraints:
    """LLM-driven structured constraint extraction.

    Prompts the model to return a JSON object with source_file,
    scope_level, and target_directories. Falls back to default
    TaskConstraints on parse failure.
    """
```

### 3.6 build_verification_prompt() (verify.py)

```python
def build_verification_prompt(
    answer: str,
    code: str,
    policy_contents: dict[str, str],
    checklist_body: str = "",
    source_basename: str | None = None,
    frame_template: str | None = None,
) -> str:
    """Construct verification prompt with optional externalized frame.

    When frame_template is provided, performs placeholder substitution:
      {{ANSWER}}, {{CODE}}, {{POLICY_SECTION}},
      {{CHECKLIST_SECTION}}, {{SOURCE_BASENAME_SECTION}}
    When frame_template is None, uses inline fallback frame.
    """
```

### 3.7 GroundingTracker (tracker.py)

```python
class GroundingTracker:
    """Thread-safe grounding reference tracker.

    All operations are synchronized via threading.Lock.
    Public interface is unchanged from pre-refactoring version.
    """
    def __init__(self) -> None: ...
    def add(self, path: str) -> None: ...
    def add_many(self, paths: Iterable[str]) -> None: ...
    def contains(self, path: str) -> bool: ...
    def merge(self, llm_refs: list[str]) -> list[str]: ...
    def all(self) -> set[str]: ...
    def __len__(self) -> int: ...
```

### 3.8 ScoutConfig (scout.py)

```python
@dataclass
class ScoutConfig:
    """Configuration for the two-phase scout. Extended with tree_level."""
    model: str
    task_instruction: str
    max_steps: int = 20
    max_workers: int = 4
    tree_level: int = 3  # Configurable via SCOUT_TREE_LEVEL env var
```

---

## 4. Key Design Decisions

### 4.1 Guard Logic as Pre-Dispatch Checks vs. In-Handler Logic

**Decision**: Move guard logic out of handler functions into standalone guard functions called by `dispatch_tool()` before handler invocation.

**Rationale**: (a) Handlers remain uniform in signature and responsibility (execute VM operation, return result). (b) Guard functions are independently testable as pure functions. (c) Guard logic is centralized in one code path rather than scattered across handlers. (d) Adding new guards does not require modifying handler signatures.

**Trade-off**: Slightly more code in `dispatch_tool()`, but significantly improved testability and separation of concerns.

### 4.2 Hybrid Constraint Extraction (Regex + LLM)

**Decision**: Use regex as a fast-path, LLM only when regex returns `None`.

**Rationale**: (a) Most tasks have simple, regex-parseable file paths and scope phrases. Adding an LLM call for every task would add 1-3 seconds of latency and cost. (b) Regex provides deterministic, predictable results for well-formed inputs. (c) LLM extraction handles edge cases (ambiguous task descriptions, implicit scope constraints, multiple file references) that regex cannot. (d) Fail-open default ensures constraint extraction failure never blocks task execution.

**Trade-off**: Two code paths to maintain. Mitigated by clear separation (regex function returns `None` on low confidence, LLM function always returns a valid `TaskConstraints`).

### 4.3 DispatchContext in dispatch.py vs. Separate Module

**Decision**: Place `DispatchContext`, `TaskConstraints`, and `TemplateGuardConfig` in `dispatch.py`.

**Rationale**: (a) These dataclasses are consumed exclusively by dispatch guard logic. (b) Creating a new `guard_types.py` module would add import complexity with no clear benefit. (c) `dispatch.py` already contains the guard functions that consume these types. (d) The dataclasses are small (3-5 fields each) and do not warrant a separate module.

**Trade-off**: `dispatch.py` grows slightly. Acceptable given the module already contains ~400 lines and the additions are ~30 lines of dataclass definitions.

### 4.4 GroundingTracker Lock Strategy

**Decision**: Instance-level `threading.Lock` (not `RLock`, not global lock).

**Rationale**: (a) Instance-level lock scopes synchronization to the specific tracker, not all trackers. (b) `threading.Lock` (non-reentrant) is sufficient because no `GroundingTracker` method calls another locked method internally. (c) `Lock` is simpler and slightly faster than `RLock`. (d) The lock is held for very short durations (dict lookup/insert), minimizing contention impact.

**Trade-off**: If future methods need to call other locked methods, refactoring to `RLock` would be needed. This is unlikely given the simple data structure.

### 4.5 Verification Frame as Skill vs. Template File

**Decision**: Use the existing `SkillLoader` mechanism to deliver the verification frame as a skill file.

**Rationale**: (a) `SkillLoader` is already wired into `loop.py` and handles file loading, error handling, and content wrapping. (b) Skills are the established mechanism for externalizing prompt content in this codebase (`self-verification` checklist is already a skill). (c) No new file-loading infrastructure needed. (d) `verify.py` remains a leaf module (no file I/O, no `SkillLoader` import -- the template is passed as a parameter).

**Trade-off**: The verification frame is now part of the skills directory, which conceptually is for "agent capabilities" rather than "prompt templates." This is a minor semantic stretch, acceptable given the infrastructure reuse benefit.

---

## 5. Requirements Traceability

| Requirement | Components | Section |
|---|---|---|
| 1.1 DispatchContext dataclass | `dispatch.py`: `DispatchContext` | 2.1 |
| 1.2 dispatch_tool accepts DispatchContext | `dispatch.py`: `dispatch_tool()` | 2.2 |
| 1.3 dispatch_parallel passes DispatchContext | `dispatch.py`: `dispatch_parallel()` | 2.2 |
| 1.4 Frozen (immutable) DispatchContext | `dispatch.py`: `@dataclass(frozen=True)` | 2.1 |
| 1.5 Handlers receive guard params from ctx | `dispatch.py`: pre-dispatch guard checks | 2.3 |
| 1.6 No module-level mutable state | `dispatch.py`: remove `_source_basename`, `_scope_constrained` | 2.2 |
| 1.7 loop.py constructs DispatchContext | `loop.py`: `run_agent()` | 2.1 |
| 2.1 TaskConstraints data structure | `dispatch.py`: `TaskConstraints` | 2.1 |
| 2.2 LLM extracts structured constraints | `loop.py`: `_extract_task_constraints_llm()` | 2.4 |
| 2.3 Remove _extract_source_basename | `loop.py`: replaced by constraint extraction | 2.4 |
| 2.4 Remove _SCOPE_PHRASES | `loop.py`: replaced by constraint extraction | 2.4 |
| 2.5 TaskConstraints feeds DispatchContext | `loop.py`: construction in `run_agent()` | 2.4 |
| 2.6 Fail-open default on extraction failure | `loop.py`: `_extract_task_constraints_llm()` | 2.4 |
| 3.1 Scope guard checks target_directories | `dispatch.py`: `_check_scope_guard()` | 2.3 |
| 3.2 Allow write when target matches task | `dispatch.py`: `_check_scope_guard()` | 2.3 |
| 3.3 Block write when no match and scope on | `dispatch.py`: `_check_scope_guard()` | 2.3 |
| 3.4 Log guard decisions | `dispatch.py`: all guard functions | 2.3 |
| 3.5 No module-level mutable state in guard | `dispatch.py`: all inputs from params | 2.3 |
| 4.1 Configurable protected directories | `dispatch.py`: `TemplateGuardConfig` | 2.1 |
| 4.2 Block _-prefixed in protected dir | `dispatch.py`: `_check_template_guard()` | 2.3 |
| 4.3 Allow _-prefixed outside protected dir | `dispatch.py`: `_check_template_guard()` | 2.3 |
| 4.4 Default to block-all (backward compat) | `dispatch.py`: `_check_template_guard()` | 2.3 |
| 4.5 Config in DispatchContext | `dispatch.py`: `DispatchContext.template_guard_config` | 2.1 |
| 4.6 Log guard decisions | `dispatch.py`: `_check_template_guard()` | 2.3 |
| 5.1 Tests for _is_basename_mismatch | `tests/test_dispatch.py`: `TestIsBasenameMismatch` | 2.8 |
| 5.2 Tests for _extract_slug | `tests/test_dispatch.py`: `TestExtractSlug` | 2.8 |
| 5.3 Tests for scope guard | `tests/test_dispatch.py`: `TestScopeGuard` | 2.8 |
| 5.4 Tests for template guard | `tests/test_dispatch.py`: `TestTemplateGuard` | 2.8 |
| 5.5 Tests for basename mismatch guard | `tests/test_dispatch.py`: `TestBasenameMismatchGuard` | 2.8 |
| 5.6 Unit tests mock VM only | `tests/test_dispatch.py`: test strategy | 2.8 |
| 6.1 External verification frame | `skills/verification-frame/SKILL.md` | 2.6 |
| 6.2 build_verification_prompt accepts frame | `verify.py`: `frame_template` param | 2.6 |
| 6.3 Placeholder substitution | `verify.py`: `build_verification_prompt()` | 2.6 |
| 6.4 Fallback to inline frame | `verify.py`: `frame_template is None` path | 2.6 |
| 6.5 No hardcoded structural elements | `verify.py`: template-driven | 2.6 |
| 7.1 Bootstrap tree uses level param | `scout.py`: `_run_bootstrap()` | 2.7 |
| 7.2 Level configurable via ScoutConfig | `scout.py`: `ScoutConfig.tree_level` | 2.7 |
| 7.3 Line-range reads in scout | `scout.py`: prompt instruction | 2.7 |
| 7.4 MiniRuntime ignores level gracefully | `runtime.py`: already handled | 2.7 |
| 7.5 PcmRuntime passes level to TreeRequest | `runtime.py`: already implemented | 2.7 |
| 8.1-8.7 Documentation update | `agent-analysis.md` | 2.9 |
| 9.1 Threading lock on GroundingTracker | `tracker.py`: `self._lock` | 2.5 |
| 9.2 Concurrent add safety | `tracker.py`: `add()` with lock | 2.5 |
| 9.3 Consistent contains during add | `tracker.py`: both locked | 2.5 |
| 9.4 No deadlocks/significant perf impact | `tracker.py`: Lock (not RLock), short hold | 2.5 |
| 9.5 Remains leaf module | `tracker.py`: no new imports | 2.5 |
| 9.6 Concurrent test | `tests/test_tracker.py`: thread-safety tests | 2.8 |

---

## 6. Migration and Backward Compatibility

### 6.1 dispatch_tool() / dispatch_parallel() Callers

The `source_basename` and `scope_constrained` keyword arguments are removed from `dispatch_tool()` and `dispatch_parallel()`. All call sites in `loop.py` and `scout.py` must be updated to pass `dispatch_ctx` instead.

**Scout phase** (`scout.py`): The scout phase does not use write or delete guards (read-only tools). It can pass `dispatch_ctx=None` (default), which disables all guard checks. No functional change.

**Executor phase** (`loop.py`): The `dispatch_parallel()` and `dispatch_tool()` calls in the executor loop replace `source_basename=source_basename, scope_constrained=scope_constrained` with `dispatch_ctx=ctx`.

### 6.2 GroundingTracker

The threading lock addition is fully backward-compatible. No callers need to change. Performance impact is negligible for the typical workload (fewer than 100 concurrent operations per task).

### 6.3 build_verification_prompt()

The new `frame_template` parameter has a default of `None`, which preserves the current inline frame behavior. Existing call sites in `loop.py` need only add the template parameter when the `verification-frame` skill is loaded. If the skill file is missing, the fallback is automatic.

### 6.4 ScoutConfig

The new `tree_level` field has a default value (`3`), so existing `ScoutConfig()` constructions do not break.

### 6.5 Test Compatibility

Existing tests in `test_dispatch.py` that use the old `source_basename` and `scope_constrained` keyword arguments need updating to use `dispatch_ctx=DispatchContext(...)`. The test helper `_make_mock_vm()` remains unchanged.
