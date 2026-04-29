# Tasks: modular-refactor

> Implementation tasks for decomposing the monolithic agent.py into a composable agent/ package, adding unit tests, centralizing configuration, deduplicating prompts, improving output truncation, adding micro-compact, and removing dead code -- all while preserving the 100% (30/30) PAC1 benchmark score.

## Task 1: Scaffold the agent/ package and create the centralized configuration module

**Requirements**: 1, 2, 5

Create the `pac1-py/agent/` directory with an empty `__init__.py`. Create `agent/config.py` containing the `AgentConfig` frozen dataclass with all fields and defaults matching the current hardcoded values in `agent.py`. Implement the `from_env()` class method that reads environment variables once and returns a frozen instance. Verify that `AgentConfig.from_env()` produces values identical to the current module-level constants (`_OUTPUT_CAP`, `_AUTO_COMPACT_THRESHOLD`, `_MAX_RETRIES`, `_RETRY_BASE_DELAY`, and the hardcoded executor step limit of 50). Add `micro_compact_enabled` (default False), `micro_compact_keep_turns` (default 5), and `smart_truncation_enabled` (default False) as new feature-flagged fields.

### Sub-tasks

- [x] 1.1. Create `pac1-py/agent/` directory with an empty `__init__.py` file
- [x] 1.2. Create `agent/config.py` with the `AgentConfig` frozen dataclass, all fields, defaults, and `from_env()` class method

---

## Task 2: Extract prompt constants and builder functions into agent/prompts.py (P)

**Requirements**: 1, 6

Create `agent/prompts.py` as the single source of truth for all prompt text. Move `AGENT_CAN`, `AGENT_CANNOT`, CLI color constants, and outcome codes documentation from `agent.py`. Define `RULE_KEEP_DIFFS_FOCUSED` and `RULE_LIST_BEFORE_READ` as canonical constants extracted from the executor and planner system prompts. Implement `build_executor_system()`, `build_planner_system()`, and `build_validator_system()` builder functions that compose prompts using the shared constants. Verify that `build_executor_system()` produces byte-identical output to the current `_EXECUTOR_SYSTEM` f-string. The module must import only from `skills.py` (if needed) and standard library -- no imports from phase modules.

### Sub-tasks

- [x] 2.1. Create `agent/prompts.py` with CLI color constants, `AGENT_CAN`, `AGENT_CANNOT`, `RULE_KEEP_DIFFS_FOCUSED`, `RULE_LIST_BEFORE_READ`, and `OUTCOME_CODES_DOC`
- [x] 2.2. Implement `build_executor_system()`, `build_planner_system()`, and `build_validator_system()` builder functions that compose prompts using the shared constants
- [x] 2.3. Verify byte-identical output of `build_executor_system()` compared to current `_EXECUTOR_SYSTEM` by running a simple comparison

---

## Task 3: Extract LLM call logic into agent/llm.py (P)

**Requirements**: 1, 2

Create `agent/llm.py` containing `call_llm`, `call_llm_no_tools`, and `estimate_tokens`. Move the `_RETRYABLE_EXCEPTIONS` tuple here. Both call functions take `config: AgentConfig` as the first parameter, replacing direct `os.environ.get()` usage for API base, API key, retry count, and retry delay. `call_llm_no_tools` is a separate function (not overloaded) for auto-compact summarization with different kwargs. The module imports only from `agent/config.py`, `litellm`, and standard library.

### Sub-tasks

- [x] 3.1. Create `agent/llm.py` with `_RETRYABLE_EXCEPTIONS`, `call_llm`, `call_llm_no_tools`, and `estimate_tokens`, all accepting `AgentConfig` where needed

---

## Task 4: Extract tool dispatch, shadow reads, and output truncation into agent/dispatch.py (P)

**Requirements**: 1, 2, 6, 8

Create `agent/dispatch.py` containing `dispatch`, `load_skill`, `compact_tree`, `truncate_output`, and the `OUTCOME_BY_NAME` mapping. Move the dispatch function verbatim, converting it to accept `config: AgentConfig`, `tm: TaskManager`, `skill_loader: SkillLoader` as explicit parameters instead of module-level globals. Implement `truncate_output` with the feature-flagged behavior: when `smart_truncation_enabled` is False (default), preserve the current naive truncation exactly; when True, use JSON-aware boundary truncation. Move `OUTCOME_BY_NAME` here since it requires the protobuf `Outcome` import. The module imports only from `agent/config.py`, `tasks.py`, `skills.py`, protobuf types, and standard library.

### Sub-tasks

- [x] 4.1. Create `agent/dispatch.py` with `compact_tree`, `load_skill`, `OUTCOME_BY_NAME`, and the `dispatch` function moved verbatim with explicit parameters
- [x] 4.2. Implement `truncate_output` with the feature-flagged JSON-aware truncation (default off, preserving current behavior verbatim)

---

## Task 5: Extract bootstrap phase into agent/bootstrap.py (P)

**Requirements**: 1, 10

Create `agent/bootstrap.py` containing `phase1_bootstrap` moved verbatim from `agent.py` (lines 481-608). Include the `_extract_paths` and `_extract_doc_paths` inner functions. The function body, CLI print statements with color codes, and return dict structure must be preserved exactly for benchmark compatibility. The module must NOT import from other agent submodules -- only from protobuf types, standard library, and `json`.

### Sub-tasks

- [x] 5.1. Create `agent/bootstrap.py` with `phase1_bootstrap` and its helper functions moved verbatim from `agent.py`

---

## Task 6: Extract planner phase into agent/planner.py

**Requirements**: 1, 2, 10

Create `agent/planner.py` containing `plan_task` extracted from `_plan_task` in `agent.py`. The function takes `config: AgentConfig`, `model`, `task_text`, `phase1_ctx`, `skill_loader: SkillLoader`, and `metadata` as explicit parameters. Use `build_planner_system()` from `prompts.py` for the system prompt. Import `compact_tree` from `dispatch.py`, `PLANNER_TOOL` from `tools.py`, and `call_llm` from `llm.py`. The function body and logic are moved verbatim.

### Sub-tasks

- [x] 6.1. Create `agent/planner.py` with `plan_task` function using explicit parameters and imported prompt builders

---

## Task 7: Extract context assembly and compaction into agent/context.py (P)

**Requirements**: 1, 9

Create `agent/context.py` containing `build_executor_context`, `build_task_message`, `micro_compact`, and `auto_compact`. Extract the context assembly block and task message construction from `run_agent`. Move `_auto_compact` logic verbatim. Implement the new `micro_compact` function that replaces stale tool results with short placeholders when enabled. Wire `auto_compact` to call `micro_compact` first, then re-estimate tokens, then proceed to LLM summarization only if still above threshold. When `micro_compact_enabled` is False (default), the function is a no-op preserving current behavior.

### Sub-tasks

- [x] 7.1. Create `agent/context.py` with `build_executor_context` and `build_task_message` extracted from `run_agent`
- [x] 7.2. Move `_auto_compact` logic into `auto_compact` in `context.py`, accepting `AgentConfig` parameter
- [x] 7.3. Implement `micro_compact` with turn-counting, protected zones, and placeholder replacement; wire it to run before `auto_compact`

---

## Task 8: Extract decision-lock and validator into agent/validator.py (P)

**Requirements**: 1, 2, 10

Create `agent/validator.py` containing `extract_decision_outcome` and `validate_completion`. Rename from private `_extract_decision_outcome` to public `extract_decision_outcome` for testability. Move function bodies verbatim -- logic is not rewritten. Both functions accept `config: AgentConfig` where LLM configuration is needed. Import `build_validator_system` from `prompts.py`, `call_llm` from `llm.py`, `VALIDATION_TOOL` from `tools.py`.

### Sub-tasks

- [x] 8.1. Create `agent/validator.py` with `extract_decision_outcome` (public) and `validate_completion`, moved verbatim with explicit parameters

---

## Task 9: Add public accessors to TaskManager in tasks.py

**Requirements**: 2

Add two read-only `@property` accessors to the `TaskManager` class in `tasks.py`: `files_deleted` (returns `self._files_deleted`) and `pending_writes` (returns `self._pending_writes`). These replace direct private attribute access by `dispatch.py`. No other changes to `tasks.py`. It remains a leaf module with zero imports from other project modules.

### Sub-tasks

- [x] 9.1. Add `files_deleted` and `pending_writes` read-only properties to `TaskManager` in `tasks.py`

---

## Task 10: Wire the executor loop and run_agent orchestrator in agent/executor.py

**Requirements**: 1, 2, 10

Create `agent/executor.py` containing `_run_executor` (converted from closure to module-level function with explicit parameters) and `run_agent` (the top-level orchestrator). `_run_executor` receives all previously captured closure variables as named parameters: `config`, `model`, `vm`, `skill_loader`, `executor_system`, `context_msg`, `task_msg`, `metadata`, `run_id`, `defer`. `run_agent` preserves its exact signature `(model, harness_url, task_text, metadata)`, creates `AgentConfig.from_env()` once at the top, instantiates `SkillLoader`, and orchestrates all phases in order: Bootstrap -> Planner -> Executor -> Decision-Lock -> Validator -> Apply Writes -> Submit. Update `agent/__init__.py` to export `run_agent`.

### Sub-tasks

- [x] 10.1. Create `agent/executor.py` with `_run_executor` converted from closure to explicit-parameter function
- [x] 10.2. Implement `run_agent` orchestrator preserving the exact function signature and pipeline order
- [x] 10.3. Update `agent/__init__.py` to re-export `run_agent` from `agent.executor`

---

## Task 11: Remove dead code and delete the original agent.py

**Requirements**: 7, 10

Delete the `_arbiter` function and `_ARBITER_TOOL` schema (not moved to any new module). Verify zero references to "arbiter" remain in any source file. Delete the original `agent.py` file since all its contents have been distributed across the `agent/` package modules. Verify that `from agent import run_agent` in `main.py` resolves correctly to `agent/__init__.py`. Scan for any other unreachable functions, imports, or constants that were identified during the move and remove them.

### Sub-tasks

- [x] 11.1. Verify zero references to "arbiter", "_arbiter", or "_ARBITER_TOOL" across all source files, then delete the original `agent.py`
- [x] 11.2. Scan for any additional dead code (unused imports, unreachable functions) introduced during the refactoring and remove it

---

## Task 12: Add pytest dev dependency to pyproject.toml (P)

**Requirements**: 3

Add a `[dependency-groups]` section to `pac1-py/pyproject.toml` with `dev = ["pytest>=8.0"]` so that the test suite can be run with `pytest`.

### Sub-tasks

- [x] 12.1. Add pytest dev dependency group to `pyproject.toml`

---

## Task 13: Create shared test fixtures in tests/conftest.py (P)

**Requirements**: 3

Create `pac1-py/tests/conftest.py` with shared pytest fixtures: `mock_vm` (mocked `PcmRuntimeClientSync` with common responses), `tm` (fresh `TaskManager` instance), `skill_loader` (SkillLoader with a temporary skills directory containing sample SKILL.md files), and `default_config` (AgentConfig with default values). All fixtures must avoid external dependencies -- no real PCM runtime, LLM API, or Langfuse.

### Sub-tasks

- [x] 13.1. Create `pac1-py/tests/conftest.py` with `mock_vm`, `tm`, `skill_loader`, and `default_config` fixtures

---

## Task 14: Write unit tests for decision-lock (extract_decision_outcome)

**Requirements**: 3

Create `pac1-py/tests/test_decision_lock.py` covering all decision-lock scenarios: admin trust overriding DENY, blacklist/valid trust escalating CLARIFICATION to DENY, valid trust + PROCEED returning NEEDS_VALIDATOR, cross-account compliance triggering CLARIFICATION, explicit DECISION= note parsing (DENY_SECURITY, DENY_CLARIFY, PROCEED), no-signal returning None, and CONFLICT returning CLARIFICATION. Import `extract_decision_outcome` from `agent.validator`. Mock the `TaskManager` compliance data where needed. All tests must pass with `pytest` without external dependencies.

### Sub-tasks

- [x] 14.1. Create `tests/test_decision_lock.py` with all test cases from design section 2.15

---

## Task 15: Write unit tests for TaskManager (P)

**Requirements**: 3

Create `pac1-py/tests/test_task_manager.py` covering: `create` (plan creation), `update` (status transitions), `add` with `blocked_by` (dependency unblocking), `defer_write` and `get_pending_writes` (deferred write tracking), `track_read`/`track_write`/`track_delete` (file operation tracking), `set_compliance` and `get_compliance`, `render` (output format consistency), and the new `files_deleted` and `pending_writes` properties. All tests use a real `TaskManager` instance (no mocking needed for a pure data class).

### Sub-tasks

- [x] 15.1. Create `tests/test_task_manager.py` with all test cases from design section 2.15

---

## Task 16: Write unit tests for SkillLoader (P)

**Requirements**: 3

Create `pac1-py/tests/test_skill_loader.py` covering: loading from a directory with SKILL.md files, `_parse_frontmatter` (YAML parsing), `get_descriptions` (Layer 1 output), `get_content` for existing and non-existing skills, and `get_names`. Use `tmp_path` to create temporary skill directories with sample SKILL.md files containing YAML frontmatter.

### Sub-tasks

- [x] 16.1. Create `tests/test_skill_loader.py` with all test cases from design section 2.15

---

## Task 17: Write unit tests for dispatch logic

**Requirements**: 3

Create `pac1-py/tests/test_dispatch.py` covering: shadow read of a deferred-deleted file returning "not found", shadow read after rewrite-after-delete, shadow list filtering deferred deletes, deferred write stored in TaskManager not executed, handler dispatch map coverage for all tool names, unknown tool returning error, output truncation for JSON and plain text, and inbox security reminder. Mock `PcmRuntimeClientSync` for all PCM calls. Import `dispatch` and `truncate_output` from `agent.dispatch`.

### Sub-tasks

- [x] 17.1. Create `tests/test_dispatch.py` with shadow read/write, deferred write, handler coverage, and truncation test cases

---

## Task 18: Write unit tests for compact_tree helper (P)

**Requirements**: 3

Create `pac1-py/tests/test_compact_tree.py` covering: normal JSON tree to text conversion, root node handling, malformed input returning empty or graceful fallback, and nested directories. Import `compact_tree` from `agent.dispatch`.

### Sub-tasks

- [x] 18.1. Create `tests/test_compact_tree.py` with all test cases from design section 2.15

---

## Task 19: Run full benchmark and verify 100% score

**Requirements**: 10

Run the complete PAC1 benchmark (30 tests) against the refactored agent with the same model configuration used before the refactor. Verify the score is 100% (30/30). Confirm that `smart_truncation_enabled` defaults to False and `micro_compact_enabled` defaults to False so that the refactored agent behaves identically to the original. If any test fails, diagnose and fix the regression before proceeding. Run `pytest` on the full test suite and verify all unit tests pass.

### Sub-tasks

- [x] 19.1. Run the PAC1 benchmark (30/30) and verify zero regression with default configuration
- [x] 19.2. Run `pytest` on the full test suite and verify all unit tests pass
- [x]\* 19.3. Verify circular import absence by running `python -c "from agent import run_agent"` successfully
