# Requirements: modular-refactor

> Modular refactor of the PAC1-PY agent: split the monolithic agent.py (1347 lines) into composable phase-based modules, add a unit test suite for critical deterministic components, enhance observability with span-level Langfuse tracing, centralize configuration, deduplicate prompt rules, remove dead code, and add micro-compact and output-cap improvements -- all while preserving the existing 100% (30/30) PAC1 benchmark score.

## Status: Generated

## Context

The PAC1-PY agent currently consists of 6 Python files totaling ~2445 lines of code, with the majority (1347 lines) concentrated in a single `agent.py` monolith. This file contains bootstrap logic, planner, executor, validator, decision-lock, dispatch, context management, prompts, helpers, and dead code (arbiter). The agent scores 100% (30/30) on the PAC1 benchmark. All changes in this specification are strictly behavioral-preserving refactors.

### Architecture to preserve (invariant):
Bootstrap (no LLM) -> Planner (1 LLM call) -> Executor (N tool calls, deferred writes) -> Decision-Lock (deterministic) -> Validator (1 LLM call) -> Apply writes -> Submit

### Current file structure:
- `agent.py` (1347 lines) -- monolith
- `tools.py` (629 lines) -- tool schemas (21 tools, 4 categories)
- `tasks.py` (202 lines) -- TaskManager with dependency graph
- `skills.py` (71 lines) -- two-layer skill injection loader
- `observability.py` (80 lines) -- Langfuse integration (basic)
- `main.py` (116 lines) -- benchmark orchestration entry point
- `skills/` -- 6 SKILL.md files

---

## 1. Module Decomposition

The monolithic `agent.py` shall be split into focused, single-responsibility modules while preserving identical runtime behavior.

### Acceptance Criteria

- **AC 1.1**: When the refactoring is complete, the system shall organize the agent as a Python package `pac1-py/` with the following modules, each in its own file: `bootstrap.py` (phase 1 deterministic discovery), `planner.py` (single LLM call for task analysis), `executor.py` (tool-call loop with deferred writes), `validator.py` (decision-lock and LLM validation), `dispatch.py` (tool name to PCM call mapping with shadow reads), `context.py` (context assembly and auto-compact), and `prompts.py` (system prompt constants and builders).
- **AC 1.2**: The existing `tools.py`, `tasks.py`, `skills.py`, `observability.py`, and `main.py` shall remain as separate files, with `tools.py`, `tasks.py`, and `skills.py` treated as leaf modules with zero imports from other project modules.
- **AC 1.3**: When `main.py` calls `run_agent()`, the function shall be importable from a single entry module (e.g., `from executor import run_agent` or equivalent top-level orchestrator) that internally coordinates all phase modules.
- **AC 1.4**: The `skills/` directory containing 6 SKILL.md files shall remain unchanged in location and content.

---

## 2. Dependency Direction

Modules shall follow a strict unidirectional dependency flow to prevent circular imports and enable isolated testing.

### Acceptance Criteria

- **AC 2.1**: Dependencies shall flow in one direction: `main -> run_agent orchestrator -> {bootstrap, planner, executor, validator, context} -> {dispatch, prompts} -> {tools, tasks, skills, observability}`.
- **AC 2.2**: No circular imports shall exist between any modules.
- **AC 2.3**: `tools.py`, `tasks.py`, and `skills.py` shall have zero imports from other project modules (leaf modules).
- **AC 2.4**: `dispatch.py` shall import only from `tools.py` and `tasks.py` (and standard library / protobuf), not from `planner.py`, `executor.py`, `validator.py`, or `prompts.py`.
- **AC 2.5**: `prompts.py` shall import only from `skills.py` (for skill descriptions) and not from any phase module.

---

## 3. Unit Test Suite

The system shall include a unit test suite covering all critical deterministic components that currently have zero test coverage.

### Acceptance Criteria

- **AC 3.1**: The system shall include unit tests for the `_extract_decision_outcome` function (decision-lock) covering: admin trust level overriding DENY, blacklist/valid trust escalating CLARIFICATION to DENY, NEEDS_VALIDATOR returned for valid-channel + PROCEED, structured compliance cross-account triggering CLARIFICATION, and explicit DECISION= note parsing.
- **AC 3.2**: The system shall include unit tests for the `TaskManager` class covering: `create` (plan creation), `update` (status transitions), `add` with `blocked_by` (dependency unblocking), `defer_write` and `get_pending_writes` (deferred write tracking), `track_read`/`track_write`/`track_delete` (file operation tracking), `set_compliance` and `get_compliance`, and `render` (output format consistency).
- **AC 3.3**: The system shall include unit tests for the `SkillLoader` class covering: loading from a directory with SKILL.md files, `_parse_frontmatter` (YAML parsing), `get_descriptions` (Layer 1 output), `get_content` for existing and non-existing skills, and `get_names`.
- **AC 3.4**: The system shall include unit tests for dispatch logic covering: shadow read behavior (read of a deferred-deleted file returns "not found"), shadow list behavior (deferred deletes filtered from listings), deferred write storage (operations stored in TaskManager instead of executed), and handler dispatch map coverage for all tool names.
- **AC 3.5**: The system shall include unit tests for the `_compact_tree` helper covering: normal JSON tree to text conversion, root node handling, and malformed input graceful failure.
- **AC 3.6**: All unit tests shall be runnable with `pytest` and shall not require a running PCM runtime, LLM API, or Langfuse instance (all external dependencies mocked).
- **AC 3.7**: The test suite shall be located in a `tests/` directory at the `pac1-py/` level.

---

## 4. Observability Enhancement

The observability module shall support span-level Langfuse tracing for each agent phase, replacing the current global-callback-only integration.

### Acceptance Criteria

- **AC 4.1**: When Langfuse is configured and reachable, the system shall create a distinct Langfuse span (or generation) for each of the following phases: bootstrap, planner, executor, and validator.
- **AC 4.2**: Each span shall include metadata identifying the phase name, the model used (for LLM phases), and the elapsed wall-clock time.
- **AC 4.3**: The executor span shall include the number of tool calls executed and the number of LLM turns.
- **AC 4.4**: When Langfuse is not configured or not reachable, the system shall behave identically to the current implementation with no performance overhead beyond a single boolean check.
- **AC 4.5**: The existing `configure_observability()` function in `observability.py` shall remain the single entry point for enabling observability, extended (not replaced) to support span-level tracing.

---

## 5. Configuration Centralization

Scattered environment variable reads and hardcoded constants shall be consolidated into a single configuration module or section.

### Acceptance Criteria

- **AC 5.1**: The system shall provide a centralized configuration source (module, class, or frozen dataclass) that holds all runtime-configurable values currently spread across `agent.py`: `CTX_TRUNCATION_LIMIT` (output cap), `CTX_AUTO_COMPACT_THRESHOLD`, `LLM_API_BASE`, `LLM_API_KEY`, `_MAX_RETRIES`, `_RETRY_BASE_DELAY`, and the executor step limit (currently hardcoded as 50).
- **AC 5.2**: All modules shall read configuration values from this centralized source rather than calling `os.environ.get()` or using module-level constants directly.
- **AC 5.3**: The centralized configuration shall be populated once at startup (in `main.py` or the orchestrator) and passed to or accessible by all modules that need it.
- **AC 5.4**: The default values for all configuration settings shall be identical to the current hardcoded defaults.

---

## 6. Prompt Rule Deduplication

Prompt rules that currently appear in multiple locations shall be consolidated into a single source of truth.

### Acceptance Criteria

- **AC 6.1**: The "keep diffs focused" rule (currently present in `_EXECUTOR_SYSTEM`, `_plan_task` system prompt, and the `execution-discipline` SKILL.md) shall have a single canonical definition in `prompts.py` and be referenced from all locations that need it.
- **AC 6.2**: The "list before read" rule (currently present in `_EXECUTOR_SYSTEM` and the `inbox-processing` SKILL.md) shall have a single canonical definition in `prompts.py` and be referenced from all locations that need it.
- **AC 6.3**: The `AGENT_CAN` and `AGENT_CANNOT` capability descriptions (currently used in both `_EXECUTOR_SYSTEM` and `_plan_task`) shall be defined once in `prompts.py` and imported wherever needed.
- **AC 6.4**: The `OUTCOME_BY_NAME` mapping and outcome code documentation shall be defined once and shared across dispatch and validation logic.
- **AC 6.5**: When a deduplicated rule is modified, the change shall automatically propagate to all prompt locations that reference it, without requiring manual updates in multiple files.

---

## 7. Dead Code Removal

Unreachable and unused code shall be removed from the codebase.

### Acceptance Criteria

- **AC 7.1**: The `_arbiter` function (~70 lines) and the `_ARBITER_TOOL` schema (~30 lines) shall be removed, as they are fully implemented but never called from any code path.
- **AC 7.2**: After removal, no references to "arbiter", "_arbiter", or "_ARBITER_TOOL" shall remain in any source file.
- **AC 7.3**: If any other functions, imports, or constants in `agent.py` are identified as unreachable during the refactoring, they shall also be removed.

---

## 8. Output Truncation Improvement

The output cap truncation shall respect JSON structure boundaries instead of cutting mid-string.

### Acceptance Criteria

- **AC 8.1**: When a tool result exceeds the configured output cap (`_OUTPUT_CAP`), the system shall attempt to truncate at a JSON-safe boundary (end of a complete JSON value, array element, or object field) rather than at an arbitrary character position.
- **AC 8.2**: When the tool result is valid JSON that exceeds the cap, the truncated output shall remain parseable as valid JSON (e.g., by closing open brackets/braces) or shall include a clear truncation marker outside the JSON structure.
- **AC 8.3**: When the tool result is plain text (not JSON), the system shall truncate at the last complete line boundary before the cap, appending a truncation marker.
- **AC 8.4**: The truncation marker shall clearly indicate that output was truncated (e.g., `\n... [truncated]`), consistent with the current marker text.

---

## 9. Micro-Compact

The system shall support clearing stale tool results between executor turns to reduce context size without requiring an LLM call.

### Acceptance Criteria

- **AC 9.1**: When a configurable micro-compact feature is enabled, the system shall replace tool result content from turns older than N turns (configurable, default: 5) with a short summary placeholder (e.g., tool name and status only), freeing token budget without an LLM summarization call.
- **AC 9.2**: The micro-compact operation shall preserve tool call IDs and the tool/assistant message structure required by the LLM API (messages remain valid for the next LLM call).
- **AC 9.3**: The micro-compact operation shall never remove or modify the system message, the initial context messages, or the most recent N turns of conversation.
- **AC 9.4**: When micro-compact is disabled, the system shall behave identically to the current implementation.
- **AC 9.5**: The micro-compact operation shall run before the existing auto-compact check, reducing the frequency of expensive LLM-based summarization.

---

## 10. Benchmark Regression Safety

All changes shall be validated against the PAC1 benchmark to ensure zero regression.

### Acceptance Criteria

- **AC 10.1**: After the refactoring is complete, the agent shall score 100% (30/30) on the PAC1 benchmark with the same model configuration used before the refactor.
- **AC 10.2**: The system prompt content (`_EXECUTOR_SYSTEM`), tool schemas (all schemas in `tools.py`), decision-lock logic (`_extract_decision_outcome`), skill injection pattern (two-layer: names in prompt, bodies on-demand), and deferred writes with shadow reads pattern shall be functionally identical after refactoring -- moved to new locations but not rewritten.
- **AC 10.3**: The `run_agent` function signature (`model, harness_url, task_text, metadata`) and return behavior shall remain unchanged so that `main.py` requires no modifications beyond import path changes.
- **AC 10.4**: The agent execution pipeline order (Bootstrap -> Planner -> Executor -> Decision-Lock -> Validator -> Apply writes -> Submit) shall be preserved exactly.
