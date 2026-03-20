# Tasks: scout-phase-optimization

> Implementation tasks for the Two-Phase LLM Scout feature. Replaces the deterministic DAG-based scout with a fast bootstrap (tree + root meta-files) followed by an LLM-driven tool-use explorer reusing existing agent infrastructure.

## Status: Generated

---

## Task 1: Add SCOUT_TOOL_SCHEMAS to tools.py (P)

**Requirements**: 3

Add the read-only tool schema subset for the scout phase to `sandbox/py/agent/tools.py`. Define a module-private `_SCOUT_TOOL_NAMES` frozenset containing `tree`, `list_dir`, `read_file`, and `search`. Derive `SCOUT_TOOL_SCHEMAS` by filtering `TOOL_SCHEMAS` against this set so schema updates propagate automatically. Do not duplicate any tool definitions.

**Acceptance Criteria**:
- [x] `_SCOUT_TOOL_NAMES` is a `frozenset` containing exactly four tool names
- [x] `SCOUT_TOOL_SCHEMAS` contains exactly the schemas for `tree`, `list_dir`, `read_file`, `search`
- [x] `SCOUT_TOOL_SCHEMAS` is derived by filtering `TOOL_SCHEMAS`, not by copying definitions
- [x] Existing `TOOL_SCHEMAS` and `TOOL_NAMES` exports are unchanged

---

## Task 2: Implement build_scout_prompt() in prompt.py (P)

**Requirements**: 2

Replace the placeholder `build_scout_prompt()` function in `sandbox/py/agent/prompt.py` with a full implementation. Change the signature to accept `task_instruction: str` and `bootstrap_context: str`. Build the scout system prompt with all six sections described in the design: role definition (workspace reconnaissance agent), bootstrap context in `<bootstrap>` tags, task context in `<task>` tags, exploration instructions (read policies first, follow redirects, use parallel tool calls, skip irrelevant directories), completion instructions (structured summary with five sections), and constraints (read-only, must not solve the task). Keep `prompt.py` as a leaf module with zero imports from other `agent/` modules.

**Acceptance Criteria**:
- [x] Signature is `build_scout_prompt(task_instruction: str, bootstrap_context: str) -> str`
- [x] Returned prompt contains all six sections: role, bootstrap context, task context, exploration instructions, completion instructions, constraints
- [x] Bootstrap context is embedded in `<bootstrap>` tags
- [x] Task instruction is embedded in `<task>` tags with a note not to solve the task
- [x] Prompt instructs reading policy files first, following redirects, using parallel tool calls, and skipping irrelevant directories
- [x] Prompt instructs the LLM to end with a structured summary (policy files, files read, areas explored vs skipped, patterns, recommendations)
- [x] Prompt states the LLM must not solve the task or call write/delete tools
- [x] `prompt.py` remains a leaf module with zero imports from other `agent/` modules

---

## Task 3: Define ScoutConfig and BootstrapContext dataclasses in scout.py

**Requirements**: 1, 4

Add the `ScoutConfig` and `BootstrapContext` dataclasses to `sandbox/py/agent/scout.py`. `ScoutConfig` has four fields: `model` (required str), `task_instruction` (required str), `max_steps` (int, default 20), `max_workers` (int, default 4). `BootstrapContext` has five fields: `directory_tree` (str), `root_policy_files` (dict[str, str]), `root_vault_skills` (dict[str, str]), `files_read` (set[str]), `folders_discovered` (list[str]). Only `ScoutConfig` and `ScoutSummary` are public exports; `BootstrapContext` is internal.

**Acceptance Criteria**:
- [x] `ScoutConfig` dataclass exists with `model`, `task_instruction`, `max_steps` (default 20), `max_workers` (default 4)
- [x] `BootstrapContext` dataclass exists with `directory_tree`, `root_policy_files`, `root_vault_skills`, `files_read`, `folders_discovered`
- [x] `ScoutConfig.model` and `ScoutConfig.task_instruction` are required (no default)
- [x] `BootstrapContext` is not in the module's public API (not re-exported)

---

## Task 4: Extend ScoutSummary with LLM metadata fields

**Requirements**: 5, 6

Add four new fields to the `ScoutSummary` dataclass in `sandbox/py/agent/scout.py`: `llm_summary` (str | None, default None), `mode` (str, default "llm"), `total_llm_steps` (int, default 0), `completed_fully` (bool, default False). All existing fields must remain unchanged with identical types and defaults to preserve backward compatibility.

**Acceptance Criteria**:
- [x] `ScoutSummary` has `llm_summary: str | None = None`
- [x] `ScoutSummary` has `mode: str = "llm"`
- [x] `ScoutSummary` has `total_llm_steps: int = 0`
- [x] `ScoutSummary` has `completed_fully: bool = False`
- [x] Existing five fields (`directory_tree`, `policy_files`, `vault_skills`, `files_read`, `folders_explored`) remain with identical types and defaults
- [x] Constructing `ScoutSummary()` with only existing fields still works (no required new fields)

---

## Task 5: Implement Phase 1 deterministic bootstrap

**Requirements**: 1

Implement `_run_bootstrap()` in `sandbox/py/agent/scout.py`. This function accepts `vm`, `tracker`, and `protected_files`, runs `dispatch_tool("tree", {"path": "/"})` to get the full directory tree, parses the JSON response to extract root-level folders and files, reads each root-level `.md` and `.txt` file via `dispatch_tool("read_file", ...)`, classifies each file (meta-files go to `root_policy_files`, `skill-*` files go to `root_vault_skills`), and returns a `BootstrapContext`. Root file reads are sequential. Also implement `_format_bootstrap_for_prompt()` which formats the bootstrap context as a human-readable string with the directory tree and each root policy file's content under its path heading.

**Acceptance Criteria**:
- [x] `_run_bootstrap()` calls `dispatch_tool("tree", {"path": "/"}, ...)` first
- [x] Parses tree JSON to extract root-level folders and root-level `.md`/`.txt` files
- [x] Reads each root-level text file via `dispatch_tool("read_file", ...)`
- [x] Classifies files using `is_meta_file()` for policy files and `skill-` prefix for vault skills
- [x] Returns a populated `BootstrapContext`
- [x] Handles tree or read failures gracefully (empty/error responses)
- [x] `_format_bootstrap_for_prompt()` produces a readable string with tree and file contents

---

## Task 6: Implement Phase 2 LLM explorer loop

**Requirements**: 1, 3, 4

Implement `_run_llm_explorer()` in `sandbox/py/agent/scout.py`. This function builds the scout system prompt via `build_scout_prompt()`, initializes the message list with the system prompt, constructs scout-specific trace metadata (separate `trace_id`, `trace_name` of `"scout_llm_explorer"`), then loops up to `config.max_steps`: call `call_llm()` with `config.model`, messages, and `SCOUT_TOOL_SCHEMAS`; if no tool calls, capture `llm_summary` and set `completed_fully = True`; otherwise dispatch tool calls via `dispatch_parallel()` with `max_workers=config.max_workers`, accumulate `read_file` results for later classification, track `list_dir` arguments for `folders_explored`, and append tool result messages. Return `(llm_summary, total_steps, completed_fully, accumulated_reads, phase2_folders)`.

**Acceptance Criteria**:
- [x] Calls `build_scout_prompt(config.task_instruction, formatted_bootstrap)` for system prompt
- [x] Calls `call_llm()` with `config.model`, messages, and `SCOUT_TOOL_SCHEMAS` (not full `TOOL_SCHEMAS`)
- [x] Uses `dispatch_parallel()` for tool calls with `max_workers=config.max_workers`
- [x] Terminates when LLM returns text without tool calls (`completed_fully = True`)
- [x] Terminates when step limit is reached (`completed_fully = False`)
- [x] Accumulates `read_file` results for later classification in `_build_summary()`
- [x] Tracks `list_dir` call paths for `folders_explored`
- [x] Uses separate scout trace metadata with distinct `trace_id` and `trace_name = "scout_llm_explorer"`
- [x] Appends assistant and tool messages to the conversation correctly

---

## Task 7: Implement summary builder and rewire run_scout()

**Requirements**: 1, 5, 6, 8

Implement `_build_summary()` in `sandbox/py/agent/scout.py` which merges Phase 1 and Phase 2 results into a `ScoutSummary`: `directory_tree` from bootstrap, `policy_files` from both phases (Phase 2 files classified via `is_meta_file()`), `vault_skills` from both phases (`skill-*` prefix), `files_read` as the union from `tracker.all()`, `folders_explored` combining bootstrap folders and Phase 2 `list_dir` paths, plus the LLM metadata fields. Then rewrite `run_scout()` to accept a `ScoutConfig` parameter, call `_run_bootstrap()` then `_run_llm_explorer()` then `_build_summary()`, and return the result. Remove all reactive DAG infrastructure: `_react_tree`, `_react_list`, `_react_read`, `_REACTORS`, `_tool_name`, `_ScoutCollector`, `detect_numbered_files`, `_NUMBERED_FILE_RE`, and the `dag.py` import. Add imports for `call_llm` from `llm.py`, `SCOUT_TOOL_SCHEMAS` from `tools.py`, `build_scout_prompt` from `prompt.py`, and `dispatch_parallel` from `dispatch.py`. Retain `META_PATTERNS`, `is_meta_file()`, `_REDIRECT_RE`, and `ScoutSummary`.

**Acceptance Criteria**:
- [x] `_build_summary()` merges Phase 1 bootstrap + Phase 2 LLM results into `ScoutSummary`
- [x] Policy files from Phase 2 classified via `is_meta_file()` basename check
- [x] Vault skills from Phase 2 classified via `skill-` prefix check
- [x] `files_read` uses union from `tracker.all()`
- [x] `run_scout()` signature is `run_scout(vm, tracker, config: ScoutConfig) -> ScoutSummary`
- [x] `run_scout()` orchestrates Phase 1 -> Phase 2 -> summary build
- [x] DAG infrastructure removed: `_react_tree`, `_react_list`, `_react_read`, `_REACTORS`, `_tool_name`, `_ScoutCollector`, `detect_numbered_files`, `_NUMBERED_FILE_RE`
- [x] `from agent.dag import ...` removed
- [x] New imports added: `call_llm`, `SCOUT_TOOL_SCHEMAS`, `build_scout_prompt`, `dispatch_parallel`
- [x] `META_PATTERNS`, `is_meta_file()`, `_REDIRECT_RE` retained

---

## Task 8: Update orchestrator integration in loop.py and main.py

**Requirements**: 7

Update `sandbox/py/agent/loop.py`: import `ScoutConfig` from `scout.py`, construct a `ScoutConfig` using `scout_model or executor_model` and `task_text` before calling `run_scout(vm, tracker, scout_config)`. Extend `_format_scout_context()` to include a `## Scout Analysis` section when `llm_summary` is present (using `getattr` with defaults for backward safety), and append a truncation warning when `completed_fully` is `False`. Update `sandbox/py/main.py`: change `SCOUT_MODEL` to default to `MODEL_ID` instead of `None`.

**Acceptance Criteria**:
- [x] `loop.py` imports `ScoutConfig` from `agent.scout`
- [x] `run_agent()` constructs `ScoutConfig(model=scout_model or executor_model, task_instruction=task_text)` and passes to `run_scout()`
- [x] `_format_scout_context()` includes `## Scout Analysis` section when `llm_summary` is not None/empty
- [x] `_format_scout_context()` includes truncation warning when `completed_fully` is False
- [x] `_format_scout_context()` uses `getattr()` with defaults for new fields
- [x] `main.py` sets `SCOUT_MODEL = os.getenv("SCOUT_MODEL") or MODEL_ID`

---

## Task 9: Rewrite test_scout.py for two-phase architecture

**Requirements**: 8

Rewrite `sandbox/py/tests/test_scout.py` to test the new two-phase scout. Remove test classes for removed code: `TestScoutModuleDependencies` (import restrictions change), `TestReactorTreeCompletion`, `TestReactorListCompletion`, `TestReactorReadCompletion`, `TestNumberedFileDetection`, `TestWaveObservability`. Add tests for: `ScoutConfig` dataclass fields and defaults, `BootstrapContext` dataclass construction, `ScoutSummary` new fields alongside existing ones, `_run_bootstrap()` calling tree and reading root files, `_run_llm_explorer()` calling `call_llm` with `SCOUT_TOOL_SCHEMAS` and terminating correctly, `run_scout()` returning merged `ScoutSummary`, `SCOUT_TOOL_SCHEMAS` containing exactly four read-only tools, `build_scout_prompt()` accepting parameters and producing correct prompt sections, and scout module import assertions (imports `llm`, `tools`, `prompt`, `dispatch`, `tracker`; does NOT import `dag`, `skills`, `loop`). Update `TestRunScoutBasic` and `TestScoutFullScenario` to pass `ScoutConfig` and mock `call_llm`/`dispatch_parallel`. Retain `TestMetaFileDetection` unchanged.

**Acceptance Criteria**:
- [x] Removed test classes: `TestScoutModuleDependencies`, `TestReactorTreeCompletion`, `TestReactorListCompletion`, `TestReactorReadCompletion`, `TestNumberedFileDetection`, `TestWaveObservability`
- [x] Added tests for `ScoutConfig` fields, defaults, and required params
- [x] Added tests for `BootstrapContext` construction
- [x] Added tests for `ScoutSummary` new fields (`llm_summary`, `mode`, `total_llm_steps`, `completed_fully`) alongside existing fields
- [x] Added tests for `_run_bootstrap()` with mocked `dispatch_tool`
- [x] Added tests for `_run_llm_explorer()` with mocked `call_llm` and `dispatch_parallel`
- [x] Added test that `SCOUT_TOOL_SCHEMAS` contains exactly `tree`, `list_dir`, `read_file`, `search`
- [x] Added test for `build_scout_prompt()` signature and prompt content
- [x] Added import assertion test: scout imports from `llm`, `tools`, `prompt`, `dispatch`, `tracker`; NOT from `dag`, `skills`, `loop`
- [x] `TestRunScoutBasic` updated to pass `ScoutConfig` and mock LLM
- [x] `TestScoutFullScenario` updated for two-phase flow
- [x] `TestMetaFileDetection` retained unchanged

---

## Task 10: Update test_loop.py for new run_scout signature

**Requirements**: 7

Update `sandbox/py/tests/test_loop.py` to reflect the new `run_scout(vm, tracker, config)` signature. Update all `run_scout` mocks so the return value's `ScoutSummary` includes new fields (`llm_summary`, `mode`, `total_llm_steps`, `completed_fully`). Add a test for `_format_scout_context()` verifying the `## Scout Analysis` section appears when `llm_summary` is set, and that the truncation warning appears when `completed_fully` is False. Verify `run_scout` is called with a `ScoutConfig` argument containing the correct model and task instruction.

**Acceptance Criteria**:
- [x] All `run_scout` mocks updated to match `run_scout(vm, tracker, config)` call pattern
- [x] Mock `ScoutSummary` return values include new fields
- [x] Test verifies `run_scout` called with `ScoutConfig` containing correct model and task instruction
- [x] Test for `_format_scout_context()` with `llm_summary` producing `## Scout Analysis` section
- [x] Test for `_format_scout_context()` with `completed_fully=False` producing truncation warning
- [x] Existing test assertions still pass

- [x]* Additional acceptance-criteria-focused edge-case tests for `_format_scout_context()` when `llm_summary` is None or empty

---

## Requirements Coverage

| Requirement | Tasks |
|---|---|
| 1 (Two-Phase Scout Execution) | 3, 5, 6, 7 |
| 2 (Scout System Prompt) | 2 |
| 3 (Read-Only Tool Schema Subset) | 1, 6 |
| 4 (Scout Configuration) | 3, 6 |
| 5 (ScoutSummary Construction) | 4, 7 |
| 6 (Enhanced ScoutSummary with LLM Metadata) | 4, 7, 8 |
| 7 (Orchestrator Integration) | 8, 10 |
| 8 (Module Dependency and Code Cleanup) | 7, 9 |
