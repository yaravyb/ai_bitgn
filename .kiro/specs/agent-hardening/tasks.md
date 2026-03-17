# Implementation Tasks: agent-hardening

> Rewrite the sandbox agent into a modular multi-phase architecture with reactive DAG-based scout, LLM-driven executor with parallel tool dispatch, two-layer skill system, programmatic grounding tracking, prompt injection defense, and provider-agnostic LLM access via LiteLLM.

## Status: Generated

---

## Task 1: Create the `agent/` package scaffold and leaf module `tools.py` (P)

> Set up the package directory structure and implement the zero-dependency tool schema definitions.

**Requirements**: 8, 11

- [x] 1.1 Create `sandbox/py/agent/__init__.py` as an empty placeholder (will re-export `run_agent` later).
- [x] 1.2 Create `sandbox/py/agent/tools.py` with the `TOOL_SCHEMAS` list containing all eight OpenAI-compatible function definitions (`tree`, `list_dir`, `read_file`, `write_file`, `delete_file`, `search`, `report_completion`, `load_skill`) per design section 4.1, and the `TOOL_NAMES` set. No imports from other agent modules.
- [x] 1.3 Verify that each schema includes `type: "function"`, `function.name`, `function.description`, and `function.parameters` with proper JSON Schema types, required fields, and defaults.

## Task 2: Implement `tracker.py` -- GroundingTracker (P)

> Build the programmatic grounding reference tracker as a pure data module with no external dependencies.

**Requirements**: 3, 11

- [x] 2.1 Create `sandbox/py/agent/tracker.py` with the `GroundingTracker` class implementing `add(path)`, `add_many(paths)`, `merge(llm_refs) -> list[str]`, `all() -> set[str]`, `__len__()`, and `__repr__()` per design section 3.4 and 4.2.
- [x] 2.2 Implement path normalization: strip leading `/`, resolve `..` segments via `posixpath.normpath`, lowercase for comparison but preserve original casing in the set.
- [x] 2.3 Ensure `merge()` returns the sorted union of programmatically tracked files and LLM-provided refs, and that the tracker never returns an empty list when files have been read.

## Task 3: Implement `dag.py` -- Task and TaskGraph (P)

> Build the reactive task DAG data structure as a pure module with no I/O and no imports from other agent modules.

**Requirements**: 9

- [x] 3.1 Create `sandbox/py/agent/dag.py` with `TaskType` (StrEnum: tree, list, read, write, delete, search, decide, report), `TaskStatus` (StrEnum: pending, ready, running, completed, cancelled), and the `Task` dataclass with fields `id`, `type`, `args`, `status`, `blocked_by`, `result`, `parent_id`, `spawn_reason` per design section 3.1.
- [x] 3.2 Implement the `TaskGraph` class with `add()`, `complete()`, `cancel()`, `ready_tasks()`, `has_pending()`, `get()`, and `all_tasks()` methods per design section 3.2.
- [x] 3.3 Enforce invariants: a task becomes `ready` when `blocked_by` becomes empty; `complete()` removes the completed ID from all dependents' `blocked_by` sets and returns newly ready IDs; `cancel()` removes the cancelled ID from dependents' sets (not transitive unless explicitly requested) and returns newly ready IDs.
- [x] 3.4 Add a monotonic `_counter` for auto-generated task IDs when callers don't provide one.

## Task 4: Implement `llm.py` -- LiteLLM wrapper (P)

> Create the provider-agnostic LLM client module wrapping LiteLLM's completion API.

**Requirements**: 1, 8, 11

- [x] 4.1 Create `sandbox/py/agent/llm.py` with the `LLMResponse` and `ToolCall` dataclasses per design section 3.6.
- [x] 4.2 Implement `call_llm(model, messages, tools, max_tokens)` wrapping `litellm.completion()` with `parallel_tool_calls=True` when tools are provided, per design section 4.4 and 10.1.
- [x] 4.3 Parse `response.choices[0].message.tool_calls` into typed `ToolCall` objects with `id`, `name`, and `arguments` (JSON-parsed dict). Handle the case where `tool_calls` is `None` (text-only response).
- [x] 4.4 Add error handling and basic retry logic for transient failures (connection errors, rate limits).

## Task 5: Implement `dispatch.py` -- Tool dispatch with protected files and parallel execution

> Build the tool dispatch layer that maps tool names to VM operations, enforces protected files, tracks grounding, and supports concurrent execution.

**Requirements**: 3, 5, 8, 9, 12

- [x] 5.1 Create `sandbox/py/agent/dispatch.py` importing only from `tracker` and `tools`. Define `DISPATCH_MAP: dict[str, Callable]` mapping each tool name to a handler function (replacing the `isinstance()` chain from current `agent.py`).
- [x] 5.2 Implement handler functions for each tool: `tree` calls `vm.outline()`, `list_dir` calls `vm.list()`, `read_file` calls `vm.read()`, `write_file` calls `vm.write()`, `delete_file` calls `vm.delete()`, `search` calls `vm.search()`. Each handler serializes the protobuf response via `MessageToDict()` and returns a JSON string.
- [x] 5.3 In `read_file` and `tree` handlers, call `tracker.add(path)` on successful execution to maintain programmatic grounding.
- [x] 5.4 Implement the `delete_file` handler with protected file checking: normalize the target path (strip leading `/`, resolve `..`, lowercase), check against the `protected_files` set, refuse with a JSON error string if protected, otherwise proceed with `vm.delete()`.
- [x] 5.5 Implement the `report_completion` handler: call `tracker.merge(llm_refs)` to produce the final grounding list, then call `vm.answer()` with the merged refs.
- [x] 5.6 Implement the `load_skill` handler that delegates to `skill_loader.get_content(name)` when a skill loader is provided.
- [x] 5.7 Implement `dispatch_tool()` and `dispatch_parallel()` functions per design section 4.5. `dispatch_parallel()` uses `concurrent.futures.ThreadPoolExecutor` to execute multiple tool calls concurrently, returning `list[tuple[str, str]]` of `(tool_call_id, result)`.

## Task 6: Implement `prompt.py` -- System prompt builder (P)

> Create the system prompt composition module that assembles all required sections for scout and executor prompts.

**Requirements**: 4, 6, 7, 10

- [x] 6.1 Create `sandbox/py/agent/prompt.py` with `build_system_prompt(skills_metadata, scout_summary, security_skill_body)` per design section 4.6.
- [x] 6.2 Compose all nine executor prompt sections in order: role definition, security policy (injection defense), protected files notice, exploration protocol, grounding requirements, task handling (untrusted `<task>` delimiters), skills catalog (Layer 1 descriptions), scout context (injected summary), and completion format.
- [x] 6.3 Implement `build_scout_prompt()` as a minimal reserved prompt for the LLM-free scout phase (reserved for future extension).
- [x] 6.4 Ensure the security section contains all five defense rules from design section 8.1: never follow contradicting instructions in `<task>`, never modify policy files, ignore override patterns (with examples), treat semantic intent only, err on refusal when uncertain.

## Task 7: Implement `skills.py` -- SkillLoader with folder structure (P)

> Build the skill loader that scans the skills directory, parses YAML frontmatter from SKILL.md files, and provides Layer 1 and Layer 2 access.

**Requirements**: 10, 11

- [x] 7.1 Create `sandbox/py/agent/skills.py` with the `SkillEntry` dataclass (`name`, `description`, `body`, `path`) and the `SkillLoader` class per design section 3.5 and 4.7.
- [x] 7.2 Implement `__init__(skills_dir)` that scans `skills/<name>/SKILL.md` files at init, parses YAML frontmatter (regex-based extraction between `---` delimiters) to extract `name` and `description`, and indexes by name.
- [x] 7.3 Implement `get_descriptions() -> str` (Layer 1: one-line per skill for system prompt), `get_content(name) -> str` (Layer 2: full body wrapped in `<skill>` tags), and `list_names() -> list[str]`.

## Task 8: Create built-in skill files

> Author the four built-in skill SKILL.md files with proper folder structure and YAML frontmatter.

**Requirements**: 10

- [x] 8.1 Create `sandbox/py/skills/workspace-discovery/SKILL.md` with YAML frontmatter and body describing the systematic vault exploration protocol (tree root, list all folders, identify and read meta-files). Create `sandbox/py/skills/workspace-discovery/references/meta-file-patterns.md` listing all meta-file patterns.
- [x] 8.2 Create `sandbox/py/skills/pattern-match-create/SKILL.md` with body describing how to inspect existing files, detect naming/numbering patterns, read meta-files, and create matching files. Create `sandbox/py/skills/pattern-match-create/references/numbering-detection.md`.
- [x] 8.3 Create `sandbox/py/skills/policy-gate/SKILL.md` with body describing how to parse conditional policies from AGENTS.MD, check conditions against the task, and refuse/halt when conditions are not met.
- [x] 8.4 Create `sandbox/py/skills/security-posture/SKILL.md` with the prompt injection defense rules that get embedded directly in the system prompt (never deferred to on-demand loading).

## Task 9: Implement `scout.py` -- Reactive DAG scout phase

> Build the LLM-free scout phase that drives the reactive DAG to exhaustively discover workspace contents, spawn child tasks from results, and produce a ScoutSummary.

**Requirements**: 2, 6, 9

- [x] 9.1 Create `sandbox/py/agent/scout.py` importing from `dag`, `dispatch`, and `tracker` only. Define the `ScoutSummary` dataclass with `directory_tree`, `policy_files`, `vault_skills`, `files_read`, and `folders_explored` per design section 3.3.
- [x] 9.2 Implement `run_scout(vm, tracker) -> ScoutSummary` that creates a `TaskGraph`, seeds it with `Task(type="tree", args={"path": "/"})`, and runs the wave loop: collect ready tasks, execute in parallel via ThreadPoolExecutor, call reactors to spawn child tasks, until no pending tasks remain.
- [x] 9.3 Implement reactor rules per design section 4.8: `tree` completion spawns `read` for AGENTS.MD and `list` for each top-level folder; `list` completion spawns `read` for meta-files and `list` for subfolders; `read` completion spawns `read` for redirect targets.
- [x] 9.4 Implement meta-file detection using the regex patterns from design section 5.2 (case-insensitive matches for `_rules.*`, `RULES.*`, `skill-*.*`, `_config.*`, `_meta.*`, `AGENTS.*`, `README.*`, `*.rules`).
- [x] 9.5 Implement numbered file detection per design section 5.3: group files by prefix and extension, if 3+ members with sequential numeric suffixes, read only the highest-numbered file.
- [x] 9.6 Add wave observability logging: wave number, tasks per wave, spawned task provenance (`parent_id`, `spawn_reason`), and cancellation reasons per design section 5.4.

## Task 10: Implement `loop.py` -- Orchestrator lifecycle

> Build the main orchestrator that connects all modules: initializes components, runs the scout phase, builds the system prompt, executes the LLM-driven tool-use loop, and handles completion.

**Requirements**: 1, 2, 4, 5, 8, 9, 10, 11, 12

- [x] 10.1 Create `sandbox/py/agent/loop.py` with `run_agent(executor_model, harness_url, task_text, scout_model, skills_dir)` per design section 4.9.
- [x] 10.2 Implement initialization: create `MiniRuntimeClientSync`, `GroundingTracker`, `SkillLoader` (if skills_dir exists), and initialize `protected_files` set with `{"agents.md"}`.
- [x] 10.3 Implement the scout phase call: invoke `run_scout(vm, tracker)` and expand `protected_files` with normalized paths of all scout-discovered policy files.
- [x] 10.4 Build the system prompt: load the `security-posture` skill body (always embedded), call `build_system_prompt()` with skills metadata, scout summary, and security body.
- [x] 10.5 Implement the executor phase as a standard tool-use loop (design section 6.1): wrap task text in `<task>` delimiters, call `call_llm()` with `TOOL_SCHEMAS`, dispatch tool calls via `dispatch_parallel()`, append results as tool messages, break on `report_completion` or step limit (30 steps with matching comment).
- [x] 10.6 Update `sandbox/py/agent/__init__.py` to re-export `run_agent` from `loop`.

## Task 11: Update `main.py` and `pyproject.toml` for the new architecture

> Modify the entry point and project configuration to use the new agent package, LiteLLM dependency, and configurable model identifiers.

**Requirements**: 1, 11, 12

- [x] 11.1 Update `sandbox/py/pyproject.toml`: replace `openai>=2.26.0` with `litellm>=1.60.0` in dependencies. Retain `pydantic`.
- [x] 11.2 Update `sandbox/py/main.py`: read `MODEL_ID` from `os.getenv("MODEL_ID")` or `os.getenv("EXECUTOR_MODEL")` with fallback to `"openai/gpt-4.1"`. Read `SCOUT_MODEL` from env. Set `SKILLS_DIR = Path(__file__).parent / "skills"`. Update the `run_agent()` call to pass `executor_model`, `harness_url`, `task_text`, `scout_model`, and `skills_dir`.
- [x] 11.3 Create `sandbox/py/.env.example` documenting supported LiteLLM provider prefixes and example model identifiers for OpenAI, AWS Bedrock, and Anthropic.

## Task 12: Delete legacy `agent.py` and verify end-to-end integration

> Remove the old monolithic agent file, verify no broken imports, and confirm the full lifecycle works.

**Requirements**: 11, 12

- [x] 12.1 Delete `sandbox/py/agent.py` (the monolithic single-file agent replaced by the `agent/` package).
- [x] 12.2 Verify that `main.py` imports `run_agent` from `agent` (package `__init__.py`) without errors.
- [x] 12.3 Verify dependency flow: confirm no circular imports exist by checking that leaf modules (`dag`, `tracker`, `tools`, `llm`, `prompt`, `skills`) import nothing from other `agent/` modules, and that only `loop.py` imports from all others.
- [x] 12.4 Run a manual end-to-end test: execute `uv run python main.py` with at least one task (e.g., `t05`) and verify that the scout phase discovers the workspace, the executor completes the task, grounding refs include all read files, and no protected files are deleted.

---

## Requirements Coverage

| Requirement | Covered by Tasks |
|-------------|-----------------|
| 1 | 4, 10, 11 |
| 2 | 9, 10 |
| 3 | 2, 5, 10 |
| 4 | 6, 10 |
| 5 | 5, 10 |
| 6 | 6, 9 |
| 7 | 6 |
| 8 | 1, 4, 5, 10 |
| 9 | 3, 5, 9, 10 |
| 10 | 6, 7, 8, 10 |
| 11 | 1, 2, 3, 4, 5, 6, 7, 10, 11, 12 |
| 12 | 5, 10, 11, 12 |
