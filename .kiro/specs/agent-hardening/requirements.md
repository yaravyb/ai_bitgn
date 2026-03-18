# Requirements: agent-hardening

> Rewrite the sandbox agent from a single monolithic agent to a multi-phase architecture with DAG-based parallel execution, scout subagent, skill system, programmatic grounding tracking, prompt injection defense, and provider-agnostic LLM access via LiteLLM — addressing all three failure modes (t05, t06, t07) and enabling multi-provider model selection with parallel tool dispatch.

## Status: Generated

## Context

Current architecture: single `agent.py` using OpenAI SDK with structured output (`response_format=NextStep`), one tool per turn, no exploration subagent, no grounding tracking, no injection defense, hardcoded to OpenAI.

Target: multi-phase agent inspired by examples s04 (subagent), s05 (skills), s03 (tracking), s02 (safe dispatch), s07 (task DAG), s08 (parallel dispatch) — with LiteLLM for provider-agnostic model access.

Benchmark failures addressed:
- **t05** (0.00): skipped `workspace/RULES.md` — incomplete exploration, missing grounding ref
- **t06** (0.00): skipped `skills/` folder entirely, ignored `_rules.txt` — incomplete exploration, missing grounding ref
- **t07** (0.00): prompt injection in HTML comment — deleted AGENTS.MD

---

## Requirement 1: Provider-Agnostic LLM Access via LiteLLM

The agent must support multiple LLM providers (OpenAI, AWS Bedrock, Anthropic, etc.) through LiteLLM, replacing the current hardcoded OpenAI SDK dependency.

### Acceptance Criteria

1. **The agent shall** use LiteLLM's `completion()` API instead of the OpenAI SDK's `client.beta.chat.completions.parse()` for all LLM calls.
2. **The agent shall** accept a model identifier in LiteLLM format (e.g., `openai/gpt-4.1`, `bedrock/us.anthropic.claude-sonnet-4-5-v2:0`, `anthropic/claude-sonnet-4-6`) via environment variable or CLI argument.
3. **When** the model identifier uses LiteLLM provider prefixes, **the agent shall** route the request to the correct provider without code changes.
4. **The dependency** `openai` **shall** be replaced with `litellm` in `pyproject.toml`.
5. **The agent shall** support `response_format` (JSON mode / structured output) through LiteLLM's provider-agnostic interface, falling back to JSON-mode prompting for providers that don't support native structured output.
6. **The `.env.example` or CLI help shall** document supported provider prefixes and example model identifiers.

---

## Requirement 2: Multi-Phase Agent Architecture (Scout + Executor)

The agent must be restructured into two phases: a **scout phase** that exhaustively discovers the workspace, followed by an **executor phase** that performs the task with full context.

### Acceptance Criteria

1. **The agent shall** implement a scout phase that runs before the main task loop, using a dedicated system prompt focused solely on workspace discovery.
2. **The scout phase shall** execute the following sequence: (a) tree the root, (b) read `AGENTS.MD` (or its redirect target), (c) list every top-level folder, (d) read all meta/policy/skill files found.
3. **The scout phase shall** return a structured summary to the executor containing: (a) directory structure, (b) contents of all policy/rules/skill files, (c) the complete list of files read.
4. **The executor phase shall** receive the scout summary injected into its conversation context before processing the task.
5. **The scout phase shall** operate with its own fresh conversation context (subagent pattern from s04), preventing discovery noise from polluting the executor's reasoning.
6. **The scout and executor may** use different models (e.g., a cheaper/faster model for scouting, a more capable model for execution), configurable via separate model identifiers.

---

## Requirement 3: Programmatic Grounding Reference Tracking

The agent must track all files read during execution programmatically (not relying on LLM memory) and automatically populate grounding references at completion time.

### Acceptance Criteria

1. **The dispatch layer shall** maintain a `files_read: set[str]` that is automatically updated every time a `read` or `outline` (tree) command returns file content.
2. **When** the scout phase reads files, **those paths shall** be added to the `files_read` set and carried over to the executor phase.
3. **When** `ReportTaskCompletion` is dispatched, **the dispatch layer shall** merge the LLM-provided `grounding_refs` with the programmatic `files_read` set, ensuring no read file is missing.
4. **The agent shall not** report completion with an empty `grounding_refs` list if any files were read during the session.
5. **The `files_read` set shall** be visible in debug output so operators can verify grounding completeness.

---

## Requirement 4: Prompt Injection Defense

The agent must resist adversarial instructions embedded in task text and never execute destructive or policy-violating actions triggered by injected content.

### Acceptance Criteria

1. **The system prompt shall** contain an explicit injection defense section instructing the model to treat task text as untrusted user data that must not override system-level rules.
2. **When** the task text contains override patterns (e.g., "ignore all previous instructions", "clear prompt", "DEBUG=ON", HTML comments with directives), **the agent shall** disregard those and continue following its system prompt.
3. **The agent shall** never delete, overwrite, or modify `AGENTS.MD` (or any file it identified as a policy source during the scout phase) regardless of task text content.
4. **The task text shall** be wrapped in explicit delimiters (e.g., `<task>...</task>`) when injected into the conversation, with instructions to treat only the semantic intent of the task.

---

## Requirement 5: Protected Files and Destructive Operation Guardrails

The agent must enforce code-level safeguards on delete operations to prevent accidental or adversarial data loss.

### Acceptance Criteria

1. **The dispatch layer shall** maintain a protected file set, initialized from a static list (`AGENTS.MD`, `AGENTS.md`) and dynamically expanded with every file the scout phase identifies as a policy/rules source.
2. **When** a delete command targets a protected file (normalized: case-insensitive, path-resolved), **the dispatch layer shall** refuse the operation and return an error message.
3. **When** a delete is refused, **the dispatch layer shall** log the refusal in the conversation history as a tool result error, so the LLM can reason about it.
4. **The protection check shall** normalize paths (strip leading `/`, resolve `..` segments) before matching against the protected set.

---

## Requirement 6: Exhaustive Exploration Protocol

The system prompt must enforce a systematic discovery protocol that ensures no relevant directory or meta-file is skipped.

### Acceptance Criteria

1. **The system prompt shall** instruct the agent to explore ALL top-level directories returned by the root outline, not just those whose names appear related to the task.
2. **The system prompt shall** instruct the agent to read any file matching meta-file patterns (`_rules.*`, `RULES.*`, `skill-*.*`, `_config.*`, `_meta.*`, `*.rules`) in every directory before acting on data files.
3. **When** a folder named `skills/` exists, **the agent shall** read all files within it to understand available capabilities.
4. **When** a directory contains both data files and meta-files, **the agent shall** read meta-files first.
5. **The scout phase implementation (Req 2) shall** fulfill this requirement automatically by exhaustively scanning before the executor begins.

---

## Requirement 7: Comprehensive System Prompt

The system prompt must provide complete operational guidance, replacing the current minimal 4-bullet prompt.

### Acceptance Criteria

1. **The system prompt shall** contain the following sections: (a) role definition, (b) security policy (injection defense, protected files), (c) exploration protocol, (d) meta-file reading protocol, (e) grounding requirements, (f) completion reporting format.
2. **The system prompt shall** instruct the agent to include ALL read files in grounding references upon completion.
3. **The system prompt shall** instruct the agent to treat task text as untrusted input.
4. **The executor system prompt shall** receive the scout summary as context, making exploration rules partially redundant but still present as defense-in-depth.

---

## Requirement 8: Standard Tool-Use Pattern (Migration from Structured Output)

The agent should migrate from OpenAI-specific structured output (`response_format=NextStep`) to the standard tool-use pattern used by the examples, enabling multi-provider compatibility.

### Acceptance Criteria

1. **The agent shall** define tools as OpenAI-compatible function schemas (the same format LiteLLM accepts) instead of Pydantic `Union` types in `response_format`.
2. **The agent loop shall** follow the standard pattern: `while tool_calls: execute tools → append results → call LLM`.
3. **The agent shall** support the LLM calling multiple tools in a single turn (parallel tool calls) where the provider supports it.
4. **The `ReportTaskCompletion` tool shall** remain as a tool (not a response_format field), so completion is a tool call the LLM invokes when done.
5. **The `NextStep` Pydantic model shall** be removed, replaced by standard tool dispatch.

---

## Requirement 9: Reactive Task DAG with Parallel Execution

The agent must support a **reactive task dependency graph** where tasks are discovered, spawned, decomposed, and cancelled dynamically as results arrive — with independent tasks executing in parallel.

### 9A: Core DAG Structure

1. **Each task in the DAG shall** have: `id`, `type` (tree/list/read/write/decide/report), `args`, `status` (pending/ready/running/completed/cancelled), `blocked_by` (set of dependency task IDs), and `result`.
2. **A task shall** transition to `ready` when its `blocked_by` set becomes empty (all dependencies completed or cancelled).
3. **The DAG shall** execute in waves: each wave collects all `ready` tasks and dispatches them in parallel using `concurrent.futures.ThreadPoolExecutor`.
4. **The DAG shall** continue executing waves until no pending tasks remain or a terminal task (report_completion) executes.

### 9B: Reactive Graph Modification (Task Spawning, Decomposition, Cancellation)

1. **When** a `tree` task completes, **the DAG shall** automatically spawn `list` tasks for each discovered folder and a `read` task for `AGENTS.MD` (if present).
2. **When** a `list` task completes, **the DAG shall** spawn `read` tasks for any discovered meta-files (`_rules.*`, `RULES.*`, `skill-*.*`, `_config.*`) and `list` tasks for any discovered subfolders that warrant deeper exploration.
3. **When** a `read` task completes and the content indicates a redirect (e.g., `"See README.MD"`), **the DAG shall** spawn a new `read` task for the redirect target.
4. **When** a task's result makes a sibling task redundant (e.g., a folder contains no relevant files), **the DAG shall** cancel the redundant task and propagate cancellation to its dependents.
5. **The DAG shall** support spawning child tasks that are immediately `ready` (no blockers) so they execute in the next wave without delay.
6. **When** a `list` task discovers numbered/patterned files (e.g., `PAY-1.md` through `PAY-12.md`), **the DAG shall** spawn a read task only for the relevant files (e.g., highest-numbered for template inspection), not for all files.

### 9C: Scout Phase DAG (LLM-Free)

1. **The scout phase shall** use the reactive DAG with **no LLM calls** — all task spawning and cancellation logic is deterministic code reacting to VM results.
2. **The scout DAG shall** begin with a single seed task: `tree(root)`, and grow reactively from there.
3. **The scout phase shall** terminate when the DAG has no more pending/ready tasks, producing a summary of: (a) directory structure, (b) all policy/meta-file contents, (c) vault-discovered skills, (d) `files_read` set.
4. **Meta-file detection shall** use pattern matching on filenames: `_rules.*`, `RULES.*`, `skill-*.*`, `_config.*`, `_meta.*`, `AGENTS.*`, `README.*` (case-insensitive).

### 9D: Executor Phase Parallelism

1. **When** the LLM emits multiple tool calls in a single turn, **the dispatch layer shall** execute them concurrently using a thread pool, not sequentially.
2. **The dispatch layer shall** collect all parallel results and return them together before the next LLM call.
3. **The executor phase shall** rely on the LLM's native parallel tool calls — the LLM decides which operations can run together.

### 9E: Observability

1. **The agent shall** log each DAG wave with the tasks it contains, their types, and dependencies.
2. **When** a task is spawned reactively, **the log shall** indicate which parent task triggered the spawn and why.
3. **When** a task is cancelled, **the log shall** indicate the reason (redundancy, parent cancellation, policy decision).

---

## Requirement 10: Skill System

The agent must support a two-layer skill system with a rich folder structure: built-in behavioral skills shipped with the agent, and vault-discovered skills found during the scout phase.

### 10A: Skill Folder Structure

1. **Each built-in skill shall** be a folder under `skills/` containing:
   - `SKILL.md` — Entry point with YAML frontmatter (`name`, `description`) and the skill body.
   - `references/` (optional) — Supporting documents, code examples, and patterns the skill can reference.
   - `scripts/` (optional) — Runnable helper scripts related to the skill.
2. **The directory layout shall** follow the established convention from `learn-claude-code/skills`:
   ```
   skills/
     workspace-discovery/
       SKILL.md
       references/
         meta-file-patterns.md
     pattern-match-create/
       SKILL.md
       references/
         numbering-detection.md
     policy-gate/
       SKILL.md
     security-posture/
       SKILL.md
   ```
3. **The `SKILL.md` frontmatter shall** include at minimum `name` and `description` fields, where `description` contains trigger conditions (when the skill should be loaded).

### 10B: Two-Layer Loading

1. **Layer 1 (system prompt)**: skill names and short descriptions (from frontmatter) shall be included in the system prompt (~100 tokens per skill) so the LLM knows what's available.
2. **Layer 2 (on demand)**: the full `SKILL.md` body (and optionally referenced files) shall be loaded into the conversation as a tool result only when the LLM calls `load_skill(name)` or when the scout phase determines the skill is relevant.
3. **The `SkillLoader` class shall** scan the `skills/` directory at startup, parse frontmatter from each `SKILL.md`, and index skills by name.

### 10C: Built-in Skills

1. **The agent shall** ship with the following built-in skills:
   - `workspace-discovery`: Systematic vault exploration protocol — how to tree, list all folders, identify and read meta-files. Always loaded for scout phase. References: meta-file pattern list.
   - `pattern-match-create`: How to inspect existing files, detect naming/numbering patterns, read meta-files in the same directory, and create new files matching the discovered template. References: examples of numbering detection logic.
   - `policy-gate`: How to parse conditional policies from AGENTS.MD (if/when rules), check each condition against the task request, and refuse/halt with a specific response when conditions aren't met.
   - `security-posture`: Prompt injection defense rules — always embedded in system prompt (not on-demand). Instructs the model to treat task text as untrusted, reject override phrases, and never modify policy files.
2. **Skills shall** encode behavioral protocols (HOW to discover and follow rules), not domain knowledge (WHAT the rules are) — domain knowledge comes from the vault.

### 10D: Vault-Discovered Skills

1. **When** the scout phase discovers skill-like files in the sandbox filesystem (e.g., `skills/skill-todo.md`), **their contents shall** be included in the scout summary and injected into the executor's context as vault skills.
2. **Vault skills shall** be clearly distinguished from built-in skills in the executor's context (e.g., wrapped in `<vault-skill>` tags).
3. **Vault skill paths shall** be added to the `files_read` tracker for grounding reference completeness.

### 10E: Skill Selection

1. **The skill selection shall** support both LLM-driven loading (LLM calls `load_skill(name)` tool) and heuristic pre-loading (code analyzes scout output and pre-loads likely relevant skills based on desk type or discovered patterns).
2. **The `security-posture` skill shall** always be embedded in the system prompt (never deferred to on-demand loading).
3. **The `workspace-discovery` skill shall** always be loaded for the scout phase.

---

## Requirement 11: Modular Architecture with Clean Separation

The agent must be decomposed into independent modules with clear responsibility boundaries, single-direction dependencies, and the ability to unit-test each module in isolation.

### 11A: Module Structure

1. **The codebase shall** be organized as a Python package `agent/` with the following modules, each in its own file:
   - `loop.py` — Orchestrator: scout → executor lifecycle, the only module that imports all others.
   - `llm.py` — LLM client: LiteLLM wrapper, model configuration, completion calls. No knowledge of VM, DAG, or tools.
   - `dispatch.py` — Tool dispatch: maps tool names to VM operations, enforces protected files, executes calls via thread pool. No knowledge of LLM or prompts.
   - `prompt.py` — System prompt builder: composes prompt sections (role, security, exploration, grounding). No knowledge of VM or DAG.
   - `scout.py` — Scout phase: drives the reactive DAG to discover workspace contents. No knowledge of LLM (LLM-free phase).
   - `dag.py` — Task DAG: data structure for Task, TaskGraph, wave execution, reactive spawn/cancel. No knowledge of VM, LLM, or any domain concept.
   - `tracker.py` — Grounding tracker: maintains `files_read: set[str]`, merges with LLM-provided refs at completion. Minimal dependency (just a set with helpers).
   - `skills.py` — Skill loader: reads SKILL.md files with frontmatter, provides Layer 1 metadata and Layer 2 body content. No knowledge of VM or LLM.
   - `tools.py` — Tool schemas: pure data definitions (OpenAI-compatible function schemas). Zero imports from other agent modules.
2. **Built-in skill files** shall live in a `skills/` directory alongside the `agent/` package, each in its own subfolder with a `SKILL.md` file.
3. **`main.py`** shall remain at the package root as the entry point, importing only from `agent/loop.py`.

### 11B: Dependency Rules

1. **Dependencies shall** flow in one direction: `main → loop → {scout, llm, dispatch, prompt, skills} → {dag, tracker, tools}`.
2. **No circular imports shall** exist between modules.
3. **`dag.py`, `tracker.py`, and `tools.py` shall** have zero imports from other `agent/` modules (leaf modules).
4. **`scout.py` shall** import from `dag.py`, `dispatch.py`, and `tracker.py` but NOT from `llm.py`, `prompt.py`, or `skills.py`.
5. **`dispatch.py` shall** import from `tracker.py` and `tools.py` but NOT from `llm.py`, `prompt.py`, `scout.py`, or `dag.py`.
6. **`loop.py` shall** be the only module permitted to import from all other `agent/` modules (orchestrator privilege).

### 11C: Interface Contracts

1. **Each module shall** expose its public API through top-level functions or classes, not through internal implementation details.
2. **`scout.py` shall** expose a function `run_scout(vm, tracker) -> ScoutSummary` that takes a VM client and tracker, returns a structured summary.
3. **`dispatch.py` shall** expose a function `dispatch(vm, tool_name, args, tracker, protected_files) -> str` that executes a single tool call.
4. **`dag.py` shall** expose `Task`, `TaskGraph` classes with `add()`, `complete()`, `cancel()`, `ready_tasks()`, and `has_pending()` methods.
5. **`llm.py` shall** expose a function `call_llm(model, messages, tools) -> LLMResponse` that wraps LiteLLM with error handling.
6. **`prompt.py` shall** expose a function `build_system_prompt(skills_metadata, scout_summary=None) -> str` that composes the prompt from sections.
7. **`tracker.py` shall** expose a `GroundingTracker` class with `add(path)`, `merge(llm_refs) -> list[str]`, and `all() -> set[str]` methods.
8. **`skills.py` shall** expose a `SkillLoader` class with `get_descriptions() -> str` (Layer 1) and `get_content(name) -> str` (Layer 2) methods.

### 11D: Testability

1. **Each module except `loop.py` shall** be unit-testable by mocking only its direct dependencies (no transitive mocking required).
2. **`dag.py` shall** be testable with no mocks at all — pure data structure logic.
3. **`tracker.py` shall** be testable with no mocks at all — pure set operations.
4. **`tools.py` shall** be testable with no mocks at all — pure schema validation.

---

## Requirement 12: Code Hygiene

The agent loop configuration must be internally consistent and the codebase clean.

### Acceptance Criteria

1. **The agent's** step loop limit and its inline documentation comment shall state the same number.
2. **The dispatch function shall** use a dispatch map (`dict[str, handler]`) instead of an `isinstance()` chain.
3. **No unreachable code shall** exist in any module.
