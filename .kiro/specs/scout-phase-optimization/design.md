# Design: scout-phase-optimization

> Two-Phase LLM Scout: Replace the deterministic DAG-based scout with a fast deterministic bootstrap (tree + root meta-files) followed by an LLM-driven tool-use explorer that reuses existing agent infrastructure for task-aware, quality-first workspace discovery.

## Status: Generated

---

## 1. Architecture Overview

The scout phase transforms from a single-pass reactive DAG system into a two-phase architecture:

```
main.py
  └─ loop.py (orchestrator)
       └─ run_scout(vm, tracker, config: ScoutConfig)
            ├─ Phase 1: Deterministic Bootstrap
            │    ├─ tree("/") via dispatch_tool()
            │    ├─ read root-level .md/.txt files via dispatch_tool()
            │    └─ produces BootstrapContext
            │
            └─ Phase 2: LLM Explorer
                 ├─ build_scout_prompt(task_instruction, bootstrap_context)
                 ├─ call_llm(scout_model, messages, SCOUT_TOOL_SCHEMAS)
                 ├─ dispatch_parallel(vm, tool_calls, tracker, ...)
                 ├─ loop until text response or max_steps
                 └─ produces LLM summary + accumulated tool results
```

### Module Dependency Graph (Post-Change)

```
main.py → agent/loop.py (orchestrator)
             ├── scout.py  → llm.py, dispatch.py, tracker.py, tools.py
             ├── llm.py                (leaf)
             ├── dispatch.py → tracker.py, tools.py, llm.py
             ├── prompt.py             (leaf)
             ├── skills.py             (leaf)
             ├── tracker.py            (leaf)
             ├── tools.py              (leaf)
             └── observability.py      (leaf)
```

Key change: `scout.py` drops `dag.py` dependency, adds `llm.py` and `tools.py`. The `dag.py` module is no longer imported by any module (orphaned; may be deleted later).

### Requirements Traceability

| Requirement | Components | Section |
|---|---|---|
| 1 (Two-Phase Scout Execution) | `scout.py`, `dispatch.py`, `tracker.py` | 2.1, 2.2 |
| 2 (Scout System Prompt) | `prompt.py` | 2.4 |
| 3 (Read-Only Tool Schema Subset) | `tools.py` | 2.3 |
| 4 (Scout Configuration) | `scout.py` | 2.1 |
| 5 (ScoutSummary Construction) | `scout.py` | 2.5 |
| 6 (Enhanced ScoutSummary with LLM Metadata) | `scout.py`, `loop.py` | 2.5, 2.6 |
| 7 (Orchestrator Integration) | `loop.py`, `main.py` | 2.6, 2.7 |
| 8 (Module Dependency and Code Cleanup) | `scout.py`, test files | 2.8 |

---

## 2. Component Design

### 2.1 ScoutConfig Dataclass (scout.py)

**Requirement**: 4.1 -- 4.6

```
@dataclass
class ScoutConfig:
    model: str                  # Required: LiteLLM model identifier for scout LLM
    task_instruction: str       # Required: user's task text for task-aware exploration
    max_steps: int = 20        # Maximum LLM call rounds in Phase 2
    max_workers: int = 4       # Thread pool size for parallel tool dispatch
```

**Design rationale**: A flat dataclass, not a dict, so callers get IDE autocomplete and type-checking. All fields mirror the brainstorming decision verbatim. No budget/timeout complexity -- just a step limit.

### 2.2 BootstrapContext Dataclass (scout.py)

**Requirement**: 1.3

```
@dataclass
class BootstrapContext:
    directory_tree: str                 # Raw JSON output from tree("/")
    root_policy_files: dict[str, str]   # path -> content for root .md/.txt files
    root_vault_skills: dict[str, str]   # path -> content for root skill-*.* files
    files_read: set[str]                # All files read during bootstrap
    folders_discovered: list[str]       # Top-level folders from tree output
```

**Produced by**: `_run_bootstrap()` (Phase 1 internal function).

**Consumed by**: `build_scout_prompt()` for embedding into the LLM system message, and `_build_summary()` for populating `ScoutSummary` base fields.

### 2.3 SCOUT_TOOL_SCHEMAS (tools.py)

**Requirement**: 3.1 -- 3.3

```
_SCOUT_TOOL_NAMES: frozenset[str] = frozenset({"tree", "list_dir", "read_file", "search"})

SCOUT_TOOL_SCHEMAS: list[dict] = [
    s for s in TOOL_SCHEMAS
    if s["function"]["name"] in _SCOUT_TOOL_NAMES
]
```

**Design rationale**: Derived by filtering `TOOL_SCHEMAS`, not by duplicating definitions. When a tool schema is updated in `TOOL_SCHEMAS`, `SCOUT_TOOL_SCHEMAS` automatically inherits the change. The filter set uses `frozenset` for immutability and O(1) lookup.

`TOOL_NAMES` (existing export) is unchanged. A new `SCOUT_TOOL_NAMES` is not exported -- the `frozenset` is module-private since only `SCOUT_TOOL_SCHEMAS` is the public contract.

### 2.4 build_scout_prompt() (prompt.py)

**Requirement**: 2.1 -- 2.8

**Signature change**:

```
# Before (placeholder):
def build_scout_prompt() -> str

# After (implemented):
def build_scout_prompt(
    task_instruction: str,
    bootstrap_context: str,
) -> str
```

**Parameters**:
- `task_instruction`: The user's raw task text, embedded so the LLM can prioritize exploration.
- `bootstrap_context`: Pre-formatted string containing the directory tree and root policy file contents. Formatted by the caller in `scout.py` before passing.

**Prompt structure** (returned as a single string with section headers):

1. **Role**: "You are a workspace reconnaissance agent. Your mission is to discover and catalog workspace contents to help a downstream executor agent. You do NOT solve the task -- you only explore and report."
2. **Bootstrap Context**: The full directory tree and root policy file contents, embedded in `<bootstrap>` tags.
3. **Task Context**: The task instruction, embedded in `<task>` tags, with instruction: "Use this to prioritize which areas of the workspace to explore. Do NOT attempt to solve this task."
4. **Exploration Instructions**:
   - Read policy/rules files first (AGENTS.MD, README.MD, _rules.*, etc.).
   - If a policy file redirects to another file (e.g., "See CLAUDE.MD"), follow the redirect.
   - Explore directories that are relevant to the task instruction.
   - Use `search()` when looking for specific content patterns.
   - Use parallel tool calls to batch multiple reads or listings.
   - Skip clearly irrelevant directories (e.g., `node_modules`, `.git`).
   - You have the full directory tree already -- jump directly to any path at any depth.
5. **Completion Instructions**: "When you have gathered sufficient context, end your exploration by responding with a structured text summary containing: (1) Policy files found and key rules from each, (2) Files read and why each was relevant, (3) Areas explored vs. skipped with reasons, (4) Patterns detected in the workspace, (5) Recommended focus areas for the executor agent."
6. **Constraints**: "You MUST NOT attempt to solve the task. You MUST NOT call write_file or delete_file. You are read-only."

**Design rationale**: The prompt receives `bootstrap_context` as a pre-formatted string, not the `BootstrapContext` dataclass. This keeps `prompt.py` as a leaf module with zero imports from other `agent/` modules (maintaining the existing architectural invariant). The formatting responsibility stays in `scout.py`.

### 2.5 ScoutSummary (scout.py)

**Requirement**: 5.1 -- 5.7, 6.1 -- 6.5

```
@dataclass
class ScoutSummary:
    # Existing fields (backward-compatible)
    directory_tree: str = ""
    policy_files: dict[str, str] = field(default_factory=dict)
    vault_skills: dict[str, str] = field(default_factory=dict)
    files_read: set[str] = field(default_factory=set)
    folders_explored: list[str] = field(default_factory=list)

    # New additive fields
    llm_summary: str | None = None       # LLM's final structured text analysis
    mode: str = "llm"                    # Always "llm" in new architecture
    total_llm_steps: int = 0             # Number of LLM call rounds in Phase 2
    completed_fully: bool = False        # True if LLM returned text naturally; False if step limit hit
```

**Construction logic** (`_build_summary()` internal function in `scout.py`):

1. `directory_tree` = `bootstrap.directory_tree` (from Phase 1).
2. `policy_files` = `bootstrap.root_policy_files` merged with Phase 2 files classified via `is_meta_file()`.
3. `vault_skills` = `bootstrap.root_vault_skills` merged with Phase 2 files matching `skill-*.*`.
4. `files_read` = `bootstrap.files_read | tracker.all()` (union of both phases).
5. `folders_explored` = `bootstrap.folders_discovered` plus directories listed by LLM in Phase 2 (extracted from `list_dir` tool call arguments).
6. `llm_summary` = the LLM's final text response (the last `response.content` when `response.tool_calls` is empty), or `None` if the step limit was hit and the LLM never returned a text-only response.
7. `mode` = `"llm"` (constant).
8. `total_llm_steps` = count of LLM call rounds executed in Phase 2.
9. `completed_fully` = `True` if the LLM ended naturally (text response, no tool calls), `False` if terminated by step limit.

**Classifying Phase 2 files**: When processing Phase 2 tool results, `read_file` results are classified:
- If the file path's basename matches `is_meta_file()` or the file is a redirect target from a policy file, it is added to `policy_files`.
- If the basename starts with `skill-`, it is added to `vault_skills`.
- All read files are added to `files_read` (already handled by `GroundingTracker`).

**Phase 2 file classification approach**: The LLM explorer loop in `_run_llm_explorer()` accumulates tool call results. After the loop completes, `_build_summary()` iterates over the accumulated `read_file` results and classifies each file using `is_meta_file()` and the `skill-` prefix check. This defers classification to summary construction, keeping the loop itself clean.

### 2.6 _format_scout_context() Extension (loop.py)

**Requirement**: 6.6, 6.7, 7.4

The existing `_format_scout_context()` function is extended to handle the new `ScoutSummary` fields additively. The function uses `getattr()` with defaults so it continues to work even if passed an older-style `ScoutSummary` (defensive coding).

**Extended output structure**:

```
<scout-summary>
## Directory Structure
{summary.directory_tree}

## Policy Files
### {path}
{content}
...

## Vault Skills
<vault-skill path="{path}">
{content}
</vault-skill>
...

## Files Read During Scout
- {file1}
- {file2}
...

## Scout Analysis                        <-- NEW SECTION
{summary.llm_summary}

**Warning: Scout exploration was truncated by the step limit.
Some areas may not have been fully explored. The scout completed
{summary.total_llm_steps} LLM rounds.**     <-- CONDITIONAL: only if not completed_fully

</scout-summary>
```

**Logic**:
1. If `llm_summary` is not `None` and not empty, append a `## Scout Analysis` section containing the raw LLM summary text.
2. If `completed_fully` is `False`, append a truncation warning paragraph within the Scout Analysis section, including the step count.
3. All existing sections remain unchanged.

### 2.7 Orchestrator Integration (loop.py, main.py)

**Requirement**: 7.1 -- 7.5

#### main.py Changes

```
# Before:
SCOUT_MODEL = os.getenv("SCOUT_MODEL")  # optional: None = LLM-free scout

# After:
SCOUT_MODEL = os.getenv("SCOUT_MODEL") or MODEL_ID  # defaults to executor model
```

The `run_agent()` call in `main.py` already passes `scout_model=SCOUT_MODEL`. No other changes needed in `main.py`.

#### loop.py Changes

**run_scout() call site**:

```
# Before:
summary = run_scout(vm, tracker)

# After:
from agent.scout import ScoutConfig
scout_config = ScoutConfig(
    model=scout_model or executor_model,
    task_instruction=task_text,
)
summary = run_scout(vm, tracker, scout_config)
```

**run_agent() signature**: No change. The existing `scout_model: str | None = None` parameter is used to construct `ScoutConfig`. When `scout_model` is `None`, it falls back to `executor_model`.

**Scout trace metadata**: Scout LLM calls receive a separate `trace_id` from the executor. This is achieved by passing distinct `metadata` to `call_llm()` inside `_run_llm_explorer()`:

```
scout_trace_metadata = {
    "trace_id": str(uuid.uuid4()),          # Separate from executor trace_id
    "trace_name": "scout_llm_explorer",
    "session_id": os.environ.get("SESSION_ID", ""),
    "trace_metadata": {
        "model": config.model,
        "phase": "scout",
    },
}
```

This metadata is constructed inside `run_scout()` (in `scout.py`), not in `loop.py`. The `scout.py` module imports `uuid` and `os` for this purpose (both stdlib, no new dependencies).

**Import changes in loop.py**:

```
# Add:
from agent.scout import ScoutConfig
```

### 2.8 run_scout() Redesign (scout.py)

**Requirement**: 1.1 -- 1.7, 8.1 -- 8.5

#### Public Interface

```
def run_scout(
    vm: MiniRuntimeClientSync,
    tracker: GroundingTracker,
    config: ScoutConfig,
) -> ScoutSummary:
```

**Breaking change**: The `config` parameter is new and required. The orchestrator (`loop.py`) is the only caller; it is updated simultaneously (section 2.7).

#### Internal Functions

```
def _run_bootstrap(
    vm: MiniRuntimeClientSync,
    tracker: GroundingTracker,
    protected_files: set[str],
) -> BootstrapContext:
```

Phase 1 implementation:
1. Call `dispatch_tool(vm, "tree", {"path": "/"}, tracker, protected_files)` to get the full recursive directory tree.
2. Parse the JSON tree response to extract root-level folders and files.
3. For each root-level file with extension `.md` or `.txt`, call `dispatch_tool(vm, "read_file", {"path": f"/{filename}"}, tracker, protected_files)`.
4. Classify each read file: if `is_meta_file()` matches, add to `root_policy_files`; if `skill-*.*`, add to `root_vault_skills`.
5. Construct and return `BootstrapContext`.

Root-level file reads are executed sequentially (typically 1-3 files), not in parallel. The overhead is negligible, and sequential execution keeps bootstrap simple and deterministic.

```
def _format_bootstrap_for_prompt(ctx: BootstrapContext) -> str:
```

Formats the bootstrap context as a human-readable string for embedding in the scout prompt. Includes the directory tree and each root policy file's content under its path heading.

```
def _run_llm_explorer(
    vm: MiniRuntimeClientSync,
    tracker: GroundingTracker,
    config: ScoutConfig,
    bootstrap: BootstrapContext,
    protected_files: set[str],
) -> tuple[str | None, int, bool, list[tuple[str, str, dict]]]:
```

Returns: `(llm_summary, total_steps, completed_fully, accumulated_read_results)` where `accumulated_read_results` is a list of `(tool_name, file_path, parsed_result)` tuples from `read_file` calls.

Phase 2 implementation:
1. Format bootstrap context via `_format_bootstrap_for_prompt()`.
2. Build scout system prompt via `build_scout_prompt(config.task_instruction, formatted_context)`.
3. Initialize messages: `[{"role": "system", "content": scout_prompt}]`.
4. Construct scout trace metadata (separate `trace_id`).
5. Loop for up to `config.max_steps` iterations:
   a. Call `call_llm(config.model, messages, tools=SCOUT_TOOL_SCHEMAS, metadata=trace_metadata)`.
   b. Append assistant message to `messages`.
   c. If no tool calls: set `llm_summary = response.content`, set `completed_fully = True`, break.
   d. Call `dispatch_parallel(vm, response.tool_calls, tracker, protected_files, max_workers=config.max_workers)`.
   e. Accumulate `read_file` results for later classification.
   f. Track `list_dir` arguments for `folders_explored`.
   g. Append tool result messages to `messages`.
6. Return results.

```
def _build_summary(
    bootstrap: BootstrapContext,
    tracker: GroundingTracker,
    llm_summary: str | None,
    total_steps: int,
    completed_fully: bool,
    accumulated_reads: list[tuple[str, str, dict]],
    phase2_folders: list[str],
) -> ScoutSummary:
```

Merges Phase 1 and Phase 2 results into a single `ScoutSummary` as described in section 2.5.

#### run_scout() Orchestration

```
def run_scout(vm, tracker, config):
    protected_files: set[str] = set()

    # Phase 1
    bootstrap = _run_bootstrap(vm, tracker, protected_files)

    # Phase 2
    llm_summary, total_steps, completed_fully, reads, folders = _run_llm_explorer(
        vm, tracker, config, bootstrap, protected_files,
    )

    # Build summary
    return _build_summary(
        bootstrap, tracker, llm_summary, total_steps, completed_fully, reads, folders,
    )
```

#### Code Removal

The following are removed from `scout.py`:

| Removed | Reason |
|---------|--------|
| `_react_tree()` | Replaced by LLM-driven exploration |
| `_react_list()` | Replaced by LLM-driven exploration |
| `_react_read()` | Replaced by LLM-driven exploration |
| `_REACTORS` dispatch table | No longer needed |
| `_tool_name()` | DAG-specific mapping, no longer used |
| `_ScoutCollector` class | Replaced by `BootstrapContext` + direct accumulation |
| `detect_numbered_files()` | LLM decides file selection |
| `_NUMBERED_FILE_RE` | Only used by `detect_numbered_files()` |
| Import of `dag.py` | No longer a dependency |

**Retained**:

| Retained | Reason |
|----------|--------|
| `META_PATTERNS` | Used in `_build_summary()` for classifying Phase 2 reads |
| `is_meta_file()` | Used in `_build_summary()` and `_run_bootstrap()` |
| `_REDIRECT_RE` | Not strictly needed (LLM follows redirects naturally), but retained for `_run_bootstrap()` redirect detection in root files |
| `ScoutSummary` | Extended with new fields |

#### New Imports in scout.py

```
# Remove:
from agent.dag import Task, TaskGraph, TaskStatus, TaskType

# Add:
from agent.llm import call_llm
from agent.tools import SCOUT_TOOL_SCHEMAS
from agent.prompt import build_scout_prompt
```

Note: `dispatch_tool` from `dispatch.py` is already imported. `dispatch_parallel` needs to be added:

```
from agent.dispatch import dispatch_tool, dispatch_parallel
```

---

## 3. Data Flow

### 3.1 End-to-End Sequence

```
main.py                loop.py               scout.py              prompt.py    llm.py    dispatch.py
  │                       │                     │                     │            │           │
  │─run_agent(model,──────>│                     │                     │            │           │
  │  harness, task,        │                     │                     │            │           │
  │  scout_model)          │                     │                     │            │           │
  │                       │─ScoutConfig(model,──>│                     │            │           │
  │                       │  task_instruction)   │                     │            │           │
  │                       │                     │──_run_bootstrap()───>│            │           │
  │                       │                     │  dispatch_tool("tree")────────────────────────>│
  │                       │                     │  dispatch_tool("read_file") x N───────────────>│
  │                       │                     │<──BootstrapContext───│            │           │
  │                       │                     │                     │            │           │
  │                       │                     │──_format_bootstrap──>│            │           │
  │                       │                     │──build_scout_prompt──────────────>│            │
  │                       │                     │<──system_prompt──────────────────│            │
  │                       │                     │                     │            │           │
  │                       │                     │──_run_llm_explorer()─│            │           │
  │                       │                     │  ┌─loop (max_steps)──────────────>│           │
  │                       │                     │  │ call_llm(scout_model, msgs, SCOUT_TOOLS)──>│
  │                       │                     │  │<──response─────────────────────│           │
  │                       │                     │  │ dispatch_parallel(tool_calls)──────────────>│
  │                       │                     │  │<──results──────────────────────────────────│
  │                       │                     │  └─repeat until text or max_steps │           │
  │                       │                     │                     │            │           │
  │                       │                     │──_build_summary()───>│            │           │
  │                       │<──ScoutSummary───────│                     │            │           │
  │                       │                     │                     │            │           │
  │                       │─_format_scout_ctx()─>│                     │            │           │
  │                       │  (includes llm_summary)                    │            │           │
  │                       │─build_system_prompt()─────────────────────>│            │           │
  │                       │─executor loop────────│─────────────────────│───call_llm()──────────>│
```

### 3.2 Type Flow Summary

| Step | Input | Output | Producer | Consumer |
|------|-------|--------|----------|----------|
| 1 | VM, tracker, protected_files | `BootstrapContext` | `_run_bootstrap()` | `_run_llm_explorer()`, `_build_summary()` |
| 2 | task_instruction, formatted bootstrap | scout system prompt (str) | `build_scout_prompt()` | `_run_llm_explorer()` |
| 3 | scout_model, messages, SCOUT_TOOL_SCHEMAS | `LLMResponse` | `call_llm()` | `_run_llm_explorer()` loop |
| 4 | tool_calls, vm, tracker | results list | `dispatch_parallel()` | `_run_llm_explorer()` loop |
| 5 | bootstrap, tracker, llm results | `ScoutSummary` | `_build_summary()` | `loop.py` |
| 6 | `ScoutSummary` | formatted context (str) | `_format_scout_context()` | `build_system_prompt()` |

---

## 4. Interface Contracts

### 4.1 run_scout() -- Public API

```python
def run_scout(
    vm: MiniRuntimeClientSync,
    tracker: GroundingTracker,
    config: ScoutConfig,
) -> ScoutSummary:
    """Run the two-phase scout: deterministic bootstrap + LLM-driven explorer.

    Args:
        vm: MiniRuntimeClientSync instance for VM operations.
        tracker: GroundingTracker to record all files read during both phases.
        config: ScoutConfig with model, task_instruction, max_steps, max_workers.

    Returns:
        ScoutSummary with directory tree, policy files, vault skills,
        files read, folders explored, LLM summary, and completion metadata.
    """
```

### 4.2 build_scout_prompt() -- Public API

```python
def build_scout_prompt(
    task_instruction: str,
    bootstrap_context: str,
) -> str:
    """Build the scout LLM system prompt.

    Args:
        task_instruction: The user's task text (for task-aware exploration).
        bootstrap_context: Pre-formatted string with directory tree and root policy contents.

    Returns:
        Complete system prompt string for the scout LLM.
    """
```

### 4.3 SCOUT_TOOL_SCHEMAS -- Public Constant

```python
# In tools.py
SCOUT_TOOL_SCHEMAS: list[dict]  # Read-only subset of TOOL_SCHEMAS
```

Contains exactly 4 tool schemas: `tree`, `list_dir`, `read_file`, `search`. Derived by filtering, not duplicating.

### 4.4 ScoutConfig -- Public Dataclass

```python
@dataclass
class ScoutConfig:
    model: str
    task_instruction: str
    max_steps: int = 20
    max_workers: int = 4
```

### 4.5 BootstrapContext -- Internal Dataclass

```python
@dataclass
class BootstrapContext:
    directory_tree: str
    root_policy_files: dict[str, str]
    root_vault_skills: dict[str, str]
    files_read: set[str]
    folders_discovered: list[str]
```

Not exported from `scout.py` (internal implementation detail). Only `ScoutConfig`, `ScoutSummary`, `run_scout`, `is_meta_file`, and `META_PATTERNS` are public.

---

## 5. Affected Files

| File | Change Type | Summary |
|------|-------------|---------|
| `sandbox/py/agent/scout.py` | **Major rewrite** | Remove DAG infrastructure, add two-phase architecture, new dataclasses (`ScoutConfig`, `BootstrapContext`), extend `ScoutSummary`, new internal functions |
| `sandbox/py/agent/tools.py` | **Minor addition** | Add `_SCOUT_TOOL_NAMES` and `SCOUT_TOOL_SCHEMAS` (4 lines) |
| `sandbox/py/agent/prompt.py` | **Moderate rewrite** | Implement `build_scout_prompt()` with full prompt content (replace placeholder) |
| `sandbox/py/agent/loop.py` | **Moderate edit** | Import `ScoutConfig`, construct config, pass to `run_scout()`, extend `_format_scout_context()` |
| `sandbox/py/main.py` | **Trivial edit** | Change `SCOUT_MODEL` default from `None` to `MODEL_ID` |
| `sandbox/py/tests/test_scout.py` | **Major rewrite** | Remove DAG-based tests, add Phase 1 + Phase 2 tests, update import assertions |
| `sandbox/py/tests/test_loop.py` | **Moderate edit** | Update `run_scout` mock to accept `ScoutConfig`, test new `_format_scout_context()` behavior |

---

## 6. Design Decisions

### 6.1 No Deterministic Fallback

**Decision**: The scout is always LLM-driven. There is no `if scout_model: use_llm() else: use_dag()` branching.

**Rationale**: The brainstorming explicitly decided against a fallback path. The deterministic bootstrap (Phase 1) provides the minimal guaranteed context. The LLM explorer (Phase 2) always runs. This eliminates a branching code path that would need separate testing and maintenance.

**Tradeoff**: Every scout run costs LLM tokens. Mitigated by: (1) the scout model can be a cheaper/faster model, (2) max_steps defaults to 20, (3) the LLM sees the full tree from Phase 1 and can complete quickly.

### 6.2 Reuse Existing Infrastructure

**Decision**: No new LLM client, no new dispatch mechanism, no new tool schema definitions.

**Rationale**: `call_llm()`, `dispatch_parallel()`, and `TOOL_SCHEMAS` already exist and are tested. Reusing them means: (1) fewer bugs, (2) automatic Langfuse observability, (3) automatic retry logic, (4) consistent tool result format.

**Implementation constraint**: `SCOUT_TOOL_SCHEMAS` must be derived by filtering, never by copying. This ensures schema updates propagate automatically.

### 6.3 prompt.py Remains a Leaf Module

**Decision**: `build_scout_prompt()` accepts `bootstrap_context` as a pre-formatted string, not as a `BootstrapContext` dataclass.

**Rationale**: The existing architecture enforces that `prompt.py` has zero imports from other `agent/` modules (leaf module invariant). Passing the dataclass would require importing it, creating a circular or at least undesirable dependency. The formatting responsibility is placed in `scout.py` via `_format_bootstrap_for_prompt()`.

### 6.4 BootstrapContext is Internal

**Decision**: `BootstrapContext` is not exported from `scout.py`.

**Rationale**: Only `_run_bootstrap()` produces it and `_run_llm_explorer()` + `_build_summary()` consume it -- all internal to `scout.py`. Exposing it would increase the public API surface without benefit. External consumers (loop.py) interact only with `ScoutConfig` (input) and `ScoutSummary` (output).

### 6.5 Sequential Bootstrap, Parallel Explorer

**Decision**: Phase 1 reads root files sequentially. Phase 2 uses `dispatch_parallel()` with `parallel_tool_calls=True`.

**Rationale**: Phase 1 typically reads 1-3 root text files -- parallelism overhead is not justified. Phase 2, where the LLM can request many reads/listings per turn, benefits from concurrent dispatch (already handled by `dispatch_parallel()`).

### 6.6 Protected Files in Scout

**Decision**: Scout passes an empty `protected_files` set to dispatch. Protected file enforcement is only meaningful for write/delete operations, which the scout cannot perform (read-only tools).

**Rationale**: `dispatch_tool()` checks protected files only in `_handle_delete_file()`. Since `SCOUT_TOOL_SCHEMAS` excludes `write_file` and `delete_file`, the protected files check is never reached. Passing an empty set avoids confusion and makes the intent explicit.

### 6.7 Separate Scout Trace ID

**Decision**: Scout LLM calls use a distinct `trace_id` from the executor's `trace_id` in Langfuse metadata.

**Rationale**: This allows Langfuse to display scout and executor as separate trace groups, making it easy to analyze scout behavior independently. The `trace_name` is `"scout_llm_explorer"` to distinguish it from the executor's `"run_agent"`.

---

## 7. Error Handling

### 7.1 Phase 1 Failures

| Scenario | Behavior |
|----------|----------|
| `tree("/")` fails (ConnectError) | `dispatch_tool()` returns `{"error": "..."}`. Bootstrap proceeds with empty tree. Phase 2 LLM has no directory structure but can still use `tree()` and `list_dir()` tools. |
| Root file read fails | `dispatch_tool()` returns `{"error": "..."}`. File is skipped; bootstrap continues with remaining files. |
| All root reads fail | `BootstrapContext` has empty `root_policy_files`. LLM must discover policy files itself. |

### 7.2 Phase 2 Failures

| Scenario | Behavior |
|----------|----------|
| `call_llm()` transient error | Handled by `call_llm()`'s built-in retry (3 attempts with exponential backoff). |
| `call_llm()` permanent error | Exception propagates to `run_scout()`, then to `run_agent()`. Agent fails. |
| Tool dispatch error | `dispatch_tool()` returns `{"error": "..."}`. Error message appended to LLM context; LLM can retry or skip. |
| Step limit reached | Loop terminates. `completed_fully = False`. `llm_summary = None` (LLM did not produce a final text response). Truncation warning included in `_format_scout_context()`. |
| LLM returns empty text (no tools, no content) | Treated as natural completion. `completed_fully = True`, `llm_summary = ""`. |

### 7.3 Backward Compatibility

| Contract | Guarantee |
|----------|-----------|
| `ScoutSummary` fields | All existing fields (`directory_tree`, `policy_files`, `vault_skills`, `files_read`, `folders_explored`) remain with identical types and semantics. New fields are additive. |
| `_format_scout_context()` | Uses `getattr(summary, "llm_summary", None)` pattern to handle both old and new `ScoutSummary` instances, though in practice only new instances will be produced. |
| `run_agent()` signature | Unchanged. |
| `TOOL_SCHEMAS` | Unchanged. `SCOUT_TOOL_SCHEMAS` is a new addition. |
| `TOOL_NAMES` | Unchanged. |

---

## 8. Test Strategy

### 8.1 Tests to Remove

| Test Class/Function | File | Reason |
|---------------------|------|--------|
| `TestScoutModuleDependencies` | `test_scout.py` | Import restrictions change: scout now imports `llm`, `tools`, `prompt` |
| `TestReactorTreeCompletion` | `test_scout.py` | Reactor functions removed |
| `TestReactorListCompletion` | `test_scout.py` | Reactor functions removed |
| `TestReactorReadCompletion` | `test_scout.py` | Reactor functions removed |
| `TestNumberedFileDetection` | `test_scout.py` | `detect_numbered_files()` removed |
| `TestWaveObservability` | `test_scout.py` | Wave logging replaced by LLM loop logging |

### 8.2 Tests to Add

| Test Area | What to Assert |
|-----------|----------------|
| `ScoutConfig` dataclass | Fields, defaults, required params |
| `BootstrapContext` dataclass | Fields, construction |
| `ScoutSummary` new fields | `llm_summary`, `mode`, `total_llm_steps`, `completed_fully` present and typed |
| `ScoutSummary` backward compatibility | Existing field names and defaults unchanged |
| `_run_bootstrap()` | Calls `dispatch_tool("tree", ...)`, reads root `.md`/`.txt` files, classifies policy files and vault skills, returns `BootstrapContext` |
| `_run_llm_explorer()` | Calls `call_llm()` with `SCOUT_TOOL_SCHEMAS`, dispatches tool calls via `dispatch_parallel()`, terminates on text response, terminates on step limit |
| `run_scout()` | Returns `ScoutSummary` with Phase 1 + Phase 2 data merged |
| `SCOUT_TOOL_SCHEMAS` | Contains exactly `tree`, `list_dir`, `read_file`, `search`; is subset of `TOOL_SCHEMAS` |
| `build_scout_prompt()` | Accepts `task_instruction` and `bootstrap_context`; output contains role, bootstrap, task, exploration instructions, constraints |
| `_format_scout_context()` extended | Includes `## Scout Analysis` section when `llm_summary` is present; includes truncation warning when `completed_fully` is `False` |
| Scout module imports | `scout.py` imports from `llm`, `dispatch`, `tracker`, `tools`, `prompt`; does NOT import `dag`, `skills`, `loop` |
| `loop.py` constructs `ScoutConfig` | `run_scout()` called with `ScoutConfig` containing `scout_model` and `task_text` |
| `main.py` SCOUT_MODEL default | `SCOUT_MODEL` defaults to `MODEL_ID` |

### 8.3 Tests to Update

| Test | File | Change |
|------|------|--------|
| `TestRunScoutBasic` | `test_scout.py` | Update `run_scout()` call to pass `ScoutConfig`; mock `call_llm()` and `dispatch_parallel()` |
| `TestScoutSummaryDataclass` | `test_scout.py` | Assert new fields exist alongside existing ones |
| `TestScoutFullScenario` | `test_scout.py` | Rewrite to test two-phase flow with mocked LLM |
| `TestLoopScoutPhase` | `test_loop.py` | Update `run_scout` mock to accept `(vm, tracker, config)` |
| `TestLoopModuleDependencies` | `test_loop.py` | No change (loop still imports from scout, llm, dispatch, prompt, skills, tracker, tools) |

### 8.4 Mock Strategy

- **`call_llm()`**: Mock in `scout.py` tests to return controlled `LLMResponse` objects. First call returns tool calls, subsequent calls return text response.
- **`dispatch_parallel()`**: Mock in `scout.py` tests to return canned `(tool_call_id, result_json)` tuples.
- **`dispatch_tool()`**: Mock for Phase 1 bootstrap (tree and read operations).
- **`build_scout_prompt()`**: Mock in `scout.py` tests (or test it separately in `test_prompt.py`).

---

## 9. Migration Notes

### 9.1 dag.py Status

After this change, `dag.py` is no longer imported by any module. It becomes an orphaned module. It should NOT be deleted in this feature's scope -- deletion is a separate cleanup concern. The module remains available for future use or reference.

### 9.2 Environment Variable Changes

| Variable | Before | After |
|----------|--------|-------|
| `SCOUT_MODEL` | Optional; `None` means LLM-free scout | Optional; defaults to `MODEL_ID` (executor model) |

Users who previously had `SCOUT_MODEL` unset will now use the executor model for scout. This is the intended behavior -- the LLM explorer requires a model.

### 9.3 Cost Implications

The scout now consumes LLM tokens. Estimated per-task cost:
- Phase 2 system prompt: ~500-1000 tokens (tree + root file contents + instructions)
- Per step: ~200-500 tokens input (tool results), ~100-300 tokens output (tool calls)
- Typical exploration: 5-10 steps for small workspaces, 15-20 for complex ones
- Total: ~3K-15K tokens per scout run

Mitigation: Use a cheaper model (e.g., `gpt-4.1-mini`) via `SCOUT_MODEL` env var.
