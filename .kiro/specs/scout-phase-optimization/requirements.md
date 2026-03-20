# Requirements: scout-phase-optimization

> Two-Phase LLM Scout: Replace the deterministic DAG-based scout with a two-phase architecture — a fast deterministic bootstrap (tree + root meta-files) followed by an LLM-driven tool-use explorer that reuses existing agent infrastructure (call_llm, dispatch_parallel, TOOL_SCHEMAS) with a scout-specific prompt and read-only tools for task-aware, quality-first workspace discovery.

## Status: Generated

## Context

Current state: The scout phase (`sandbox/py/agent/scout.py`) uses a reactive DAG (`dag.py`) to discover workspace contents in a deterministic, LLM-free manner. It seeds with `tree("/")`, then reactively spawns `list` and `read` tasks via reactor rules. The `scout_model` parameter exists in `run_agent()` but is unused. The `build_scout_prompt()` function exists as a placeholder in `prompt.py`.

Documented limitations (from `docs/agent-analysis.md`, weakness #4):

1. **No depth control** -- explores everything reactor rules match, unbounded.
2. **No prioritization** -- all ready tasks treated equally, no task awareness.
3. **Numbered file heuristic limitations** -- reads only the highest-numbered file.
4. **No timeout or task budget** -- unbounded waves.

### New Architecture: Two-Phase LLM Scout

The scout phase becomes a two-phase system:

- **Phase 1 (Deterministic Bootstrap)**: `tree("/")` + read root-level text files. Fast (~1 second), free (no LLM), provides the LLM with a full recursive directory map and policy file contents.
- **Phase 2 (LLM Explorer)**: A tool-use loop reusing `call_llm()`, `dispatch_parallel()`, and a read-only subset of `TOOL_SCHEMAS`. The LLM sees the full tree and can jump to any depth directly — no level-by-level traversal needed. The LLM decides what to explore based on the task instruction, focuses on relevant areas, skips irrelevant ones, and stops when it has enough context.

The reactive DAG and reactor system are replaced entirely. The LLM IS the intelligence layer — no heuristics, no fixed rules, no priority scores.

Reusable components from the existing codebase:

| Component | Location | Reuse |
|-----------|----------|-------|
| `call_llm()` | `agent/llm.py` | Same function, pass `scout_model` |
| `dispatch_parallel()` | `agent/dispatch.py` | Same function, same tool handlers |
| `TOOL_SCHEMAS` | `agent/tools.py` | Filter to read-only subset |
| `GroundingTracker` | `agent/tracker.py` | Already used by scout |
| `build_scout_prompt()` | `agent/prompt.py` | Placeholder exists, needs implementation |

Design constraints:
- The scout model defaults to the executor model (`SCOUT_MODEL = os.getenv("SCOUT_MODEL") or MODEL_ID`).
- The `ScoutSummary` interface consumed by `loop.py` must remain backward-compatible (extended, not broken).
- The scout uses `parallel_tool_calls=True` for efficient batched exploration.
- Observability: scout LLM calls get traced automatically via existing Langfuse callbacks.

---

## Requirement 1: Two-Phase Scout Execution

The scout phase must execute in two sequential phases: a fast deterministic bootstrap followed by an LLM-driven exploration loop.

### Acceptance Criteria

1. **The scout phase shall** execute Phase 1 (deterministic bootstrap) first: run `tree("/")` to obtain the full recursive directory structure, then read all root-level text files (`.md`, `.txt`) to capture policy and configuration files.
2. **Phase 1 shall** use the existing `dispatch_tool()` and `GroundingTracker` infrastructure for tree and read operations.
3. **Phase 1 shall** produce a `BootstrapContext` containing: the full directory tree output, root policy file contents (keyed by path), root vault skills (keyed by path), the set of files read, and the list of folders discovered.
4. **The scout phase shall** execute Phase 2 (LLM explorer) after Phase 1 completes: run a tool-use loop using `call_llm()` with the scout model, passing the bootstrap context as initial context and `SCOUT_TOOL_SCHEMAS` as available tools.
5. **Phase 2 shall** follow the same tool-use loop pattern as the executor in `loop.py`: call LLM, dispatch tool calls via `dispatch_parallel()`, append results to messages, repeat.
6. **Phase 2 shall** terminate when the LLM returns a text response without tool calls (natural completion) or when the step limit is reached.
7. **Phase 2 shall** reuse `call_llm()` from `agent/llm.py` and `dispatch_parallel()` from `agent/dispatch.py` directly -- no new LLM client or dispatch mechanism.

---

## Requirement 2: Scout System Prompt

The scout phase must use a dedicated system prompt that instructs the LLM to explore the workspace intelligently based on the task instruction, using the bootstrap context as its starting map.

### Acceptance Criteria

1. **The `build_scout_prompt()` function in `prompt.py` shall** be implemented (replacing its current placeholder) to generate a scout-specific system prompt.
2. **The `build_scout_prompt()` function shall** accept the task instruction text and the formatted bootstrap context (tree + root policy file contents) as parameters.
3. **The scout system prompt shall** define the LLM's role as a workspace reconnaissance agent that discovers and catalogs content -- not solves the task.
4. **The scout system prompt shall** embed the bootstrap context (directory tree + root policy contents) so the LLM has full structural awareness from turn 1.
5. **The scout system prompt shall** include the task instruction so the LLM can prioritize exploration paths relevant to the task.
6. **The scout system prompt shall** instruct the LLM to: read policy/rules files first, follow redirects, explore directories relevant to the task, use `search()` when looking for specific content, use parallel tool calls to batch reads, and skip clearly irrelevant directories.
7. **The scout system prompt shall** instruct the LLM to end exploration with a structured text summary listing: policy files found and key rules, files read and why, areas explored vs skipped with reasons, patterns detected, and recommended focus areas for the executor.
8. **The scout system prompt shall** explicitly state that the LLM must not attempt to solve the task or perform write operations.

---

## Requirement 3: Read-Only Tool Schema Subset

The scout phase must use a read-only subset of the existing tool schemas to prevent the scout LLM from performing destructive or task-solving operations.

### Acceptance Criteria

1. **The `tools.py` module shall** export a `SCOUT_TOOL_SCHEMAS` constant containing only the read-only tools: `tree`, `list_dir`, `read_file`, and `search`.
2. **The `SCOUT_TOOL_SCHEMAS` shall** be derived from the existing `TOOL_SCHEMAS` by filtering -- not by duplicating definitions -- ensuring schema consistency when tool definitions are updated.
3. **The scout tool-use loop shall** pass `SCOUT_TOOL_SCHEMAS` (not `TOOL_SCHEMAS`) to `call_llm()`, so the LLM only sees and can call read-only tools.

---

## Requirement 4: Scout Configuration

The scout phase must expose a configuration object that controls the scout model and step limit.

### Acceptance Criteria

1. **The scout phase shall** define a configuration dataclass (`ScoutConfig`) that encapsulates: scout model identifier, task instruction text, maximum step count, and thread pool size.
2. **The `ScoutConfig.model` field shall** be a required string (the LiteLLM model identifier for the scout LLM).
3. **The `ScoutConfig.task_instruction` field shall** be a required string containing the user's task text.
4. **The `ScoutConfig.max_steps` field shall** default to 20 (the maximum number of LLM call rounds in Phase 2).
5. **The `ScoutConfig.max_workers` field shall** default to 4 (the thread pool size for parallel tool dispatch).
6. **The `run_scout()` function signature shall** accept a `ScoutConfig` parameter.

---

## Requirement 5: ScoutSummary Construction from Two-Phase Results

The scout phase must construct a `ScoutSummary` from both the bootstrap results and the LLM explorer's tool call results, producing a data structure compatible with the executor.

### Acceptance Criteria

1. **The scout phase shall** build a `ScoutSummary` by combining Phase 1 bootstrap results with Phase 2 LLM tool call results.
2. **The `directory_tree` field shall** be populated from the Phase 1 `tree("/")` output.
3. **The `policy_files` field shall** include root policy files from Phase 1 and any additional policy files (matching `META_PATTERNS` or classified via `is_meta_file()`) discovered by the LLM in Phase 2.
4. **The `vault_skills` field shall** include vault skills from Phase 1 and any additional `skill-*.*` files discovered by the LLM in Phase 2.
5. **The `files_read` field shall** be the union of all files read during both phases (from `GroundingTracker.all()`).
6. **The `folders_explored` field shall** include folders from Phase 1 and all directories listed by the LLM in Phase 2.
7. **The constructed `ScoutSummary` shall** be compatible with `_format_scout_context()` in `loop.py` -- the executor must work identically with the new scout output.

---

## Requirement 6: Enhanced ScoutSummary with LLM Metadata

The `ScoutSummary` must include metadata about the LLM exploration so the executor can benefit from the scout's analysis.

### Acceptance Criteria

1. **The `ScoutSummary` shall** include an `llm_summary` field (string or None) containing the LLM's final text response -- its structured analysis of what it found, patterns detected, and recommended focus areas.
2. **The `ScoutSummary` shall** include a `mode` field (string) indicating `"llm"`.
3. **The `ScoutSummary` shall** include a `total_llm_steps` field (int) recording how many LLM call rounds Phase 2 executed.
4. **The `ScoutSummary` shall** include a `completed_fully` field (bool) indicating whether the LLM finished naturally (returned text without tool calls) or was stopped by the step limit.
5. **The existing `ScoutSummary` fields** (`directory_tree`, `policy_files`, `vault_skills`, `files_read`, `folders_explored`) **shall** remain present and backward-compatible -- new fields are additive only.
6. **The `_format_scout_context()` function in `loop.py` shall** be extended to include the `llm_summary` in the scout context injected into the executor prompt, under a "## Scout Analysis" section.
7. **When** the scout was stopped by the step limit (`completed_fully` is False), **the `_format_scout_context()` function shall** include a truncation warning so the executor knows which areas may not have been fully explored.

---

## Requirement 7: Orchestrator Integration

The orchestrator (`loop.py`) must wire the scout model and task instruction into the new scout phase with minimal changes.

### Acceptance Criteria

1. **The `run_agent()` function in `loop.py` shall** construct a `ScoutConfig` using the `scout_model` parameter (defaulting to `executor_model` if not provided) and the `task_text` parameter, and pass it to `run_scout()`.
2. **The `SCOUT_MODEL` in `main.py` shall** default to the executor model: `SCOUT_MODEL = os.getenv("SCOUT_MODEL") or MODEL_ID`.
3. **The `run_agent()` function shall** pass the `scout_model` value from `main.py` to `run_scout()` via `ScoutConfig`.
4. **The existing `_format_scout_context()` function shall** continue to work with the enhanced `ScoutSummary` by handling new fields additively.
5. **The scout LLM calls shall** use separate trace metadata (distinct `trace_id`) from the executor, so scout and executor traces appear as separate groups in Langfuse.

---

## Requirement 8: Module Dependency and Code Cleanup

The scout phase changes must cleanly update the module dependency graph and remove unused code.

### Acceptance Criteria

1. **The `scout.py` module shall** import from `llm.py` and `tools.py` in addition to `dispatch.py` and `tracker.py` -- the dependency on `dag.py` is no longer required.
2. **The reactive DAG infrastructure** (`_react_tree`, `_react_list`, `_react_read`, `_REACTORS`, `_tool_name`, `_ScoutCollector`) **shall** be removed from `scout.py` since it is replaced by the LLM explorer.
3. **The `detect_numbered_files()` function shall** be removed since the LLM makes file selection decisions directly.
4. **The `is_meta_file()` function and `META_PATTERNS` shall** be retained for use in `ScoutSummary` construction (classifying LLM-read files as policy files or vault skills).
5. **Existing tests that assert `scout.py` import restrictions or test removed functions shall** be updated to reflect the new architecture.
