# AI Agent Implementation Analysis

> Living document — updated as the agent evolves. Last reviewed: 2026-03-26 (persistent-task-planner + smart micro-compact update).

---

## Architecture Overview

The agent is a **modular multi-phase system** built for the BitGN benchmark platform. It decomposes into two execution phases — a two-phase **Scout** (deterministic bootstrap + LLM-driven explorer) and an LLM-driven **Executor** (tool-use loop with optional self-verification) — connected by an orchestrator (`loop.py`), with 11 modules under strict one-way dependency flow.

### Module Structure

The codebase follows a strict **leaf/orchestrator pattern**: leaf modules have zero imports from other `agent/` modules, while orchestrator modules import from leaves but never from each other. No circular imports exist.

| Module | Type | Role | Imports from agent/ |
|---|---|---|---|
| `loop.py` | Orchestrator | Top-level lifecycle: scout -> constraint extraction -> executor loop. Only module permitted to import from all other agent/ modules. Constructs `DispatchContext`, manages verification state and resilience state (`ResilienceState`), applies context compression. Five-point weak-model resilience system with `_looks_like_tool_call()`, `_detect_tool_name()`, `_build_tool_name_list()` helpers. Plan-aware checkpoint (`_read_plan_for_checkpoint`) and verification (`_read_plan_for_verification`) helpers read plan state from local storage. Initialises plan storage via `init_plan_storage(trace_id)`. Verification interception resets replan timer to prevent post-completion damage. | scout, llm, dispatch, verify, prompt, skills, tracker, tools, context |
| `scout.py` | Orchestrator | Two-phase workspace discovery: deterministic bootstrap (tree + meta-file reads) followed by LLM-driven explorer (tool-use loop with read-only tool subset). | llm, dispatch, tracker, tools, prompt, context |
| `dispatch.py` | Leaf | Tool dispatch: maps tool names to VM operations. Defines `DispatchContext`, `TaskConstraints`, `TemplateGuardConfig` dataclasses. Contains standalone guard functions (`_check_basename_guard`, `_check_scope_guard`, `_check_template_guard`). Supports concurrent execution via `dispatch_parallel()`. Hosts persistent plan storage (`init_plan_storage`, `get_plan_file_path`, `_read_plan`) on the host filesystem (`/tmp/ai-bitgn-plans/{uuid}/`) — separate from the sandbox VM to avoid polluting benchmark-scored filesystems. Plan handlers: `_handle_plan_create`, `_handle_plan_status`, `_handle_plan_step_done` (batch indices), `_handle_plan_step_skip`, `_handle_plan_note`. | tracker, llm (ToolCall type only), context |
| `verify.py` | Leaf | Self-verification: pure functions and dataclasses (`VerificationState`, `VerificationOutcome`, `should_verify`, `build_verification_prompt`, `detect_verification_outcome`). Supports externalized frame template via `frame_template` parameter. | None (zero agent/ imports) |
| `prompt.py` | Leaf | System prompt builder: pure structural assembler. Accepts `embedded_skill_bodies` and `scout_summary` parameters. All behavioral rules come from skill files, not hardcoded here. | None (zero agent/ imports) |
| `context.py` | Leaf | Context management: `ContextConfig` and `ResilienceConfig` dataclasses, `estimate_tokens()`, `micro_compact()`, `truncate_tool_result()`. Pure functions implementing the three-layer compression pipeline. Smart micro-compact (`_summarize_tool_result`, `_extract_file_summary`) replaces old tool results with format-aware summaries instead of deleting them. `ResilienceConfig` provides env-configurable thresholds for the weak-model resilience system. | None (zero agent/ imports) |
| `tracker.py` | Leaf | Grounding reference tracker: `GroundingTracker` class with thread-safe `add`/`contains`/`merge`/`all` operations. Uses `threading.Lock` for concurrent access safety. | None (zero agent/ imports) |
| `tools.py` | Leaf | Tool schema definitions: OpenAI-compatible function calling schemas (`TOOL_SCHEMAS`, `SCOUT_TOOL_SCHEMAS`). 14 base tools (including 5 plan tools: `plan_create`, `plan_step_done`, `plan_step_skip`, `plan_status`, `plan_note`). `get_tool_schemas(runtime_type)` returns PCM-extended schemas when needed. | None (zero agent/ imports) |
| `skills.py` | Leaf | Skill loader: reads `SKILL.md` files with YAML frontmatter. Provides Layer 1 metadata (descriptions) and Layer 2 body content. | None (zero agent/ imports) |
| `runtime.py` | Leaf | Runtime adapters: `RuntimeAdapter` Protocol, `MiniRuntime`, `PcmRuntime`. Unified interface over Mini and PCM VMs with SDK v2 parameter support. | None (imports only from bitgn SDK) |
| `llm.py` | Leaf | LLM client: wraps LiteLLM's completion API. Provider-agnostic access with retry logic (3 retries, exponential backoff). `ToolCall` and `LLMResponse` dataclasses. | None (zero agent/ imports) |

Additional modules (not part of the core 11): `dag.py` (leaf, orphaned -- no longer imported), `observability.py` (leaf, optional Langfuse integration).

```
main.py -> agent/loop.py (orchestrator)
             |-- verify.py             (leaf -- pure functions, zero agent/ imports)
             |-- context.py            (leaf -- pure functions, zero agent/ imports)
             |-- scout.py  -> llm.py, dispatch.py, tracker.py, tools.py, prompt.py, context.py
             |-- llm.py                (leaf)
             |-- dispatch.py -> tracker.py, llm.py (ToolCall type), context.py
             |-- prompt.py             (leaf)
             |-- skills.py             (leaf)
             |-- tracker.py            (leaf -- thread-safe via threading.Lock)
             |-- tools.py              (leaf)
             |-- runtime.py            (leaf -- imports only bitgn SDK)
             +-- observability.py      (leaf, optional)
```

---

## Strengths

### 1. Excellent Modular Architecture

Clear separation into 8 leaf modules (`tracker.py`, `tools.py`, `llm.py`, `prompt.py`, `skills.py`, `context.py`, `verify.py`, `runtime.py`) vs. 3 orchestrator modules (`loop.py`, `scout.py`, `dispatch.py`) with strict one-way dependency flow. No circular imports; each module has a single responsibility. See the Module Structure table above for the full breakdown of roles and import constraints.

Key constraints enforced:
- **Leaf modules**: zero `agent/` imports (only stdlib, external SDKs, or built-in types).
- **Orchestrator modules**: may import from leaves but never from each other (`scout.py` does not import `loop.py` and vice versa).
- **`dispatch.py`**: imports only `tracker.py`, `llm.py` (ToolCall type), and `context.py`. Hosts the `DispatchContext` / `TaskConstraints` / `TemplateGuardConfig` dataclasses and standalone guard functions.

**Status**: Maintained.

### 2. Two-Phase LLM Scout

The scout phase uses a two-phase architecture for task-aware workspace discovery:

- **Phase 1 (Deterministic Bootstrap)**: Runs `tree("/")` and reads root-level `.md`/`.txt` files. Fast (~1 second), free (no LLM tokens), provides the LLM with a full directory map and policy file contents.
- **Phase 2 (LLM Explorer)**: A tool-use loop reusing `call_llm()`, `dispatch_parallel()`, and a read-only subset of tool schemas (`SCOUT_TOOL_SCHEMAS`). The LLM sees the full tree from Phase 1 and can jump to any depth directly — no level-by-level traversal. It decides what to explore based on the task instruction, focuses on relevant areas, skips irrelevant ones, and stops when it has enough context.

The scout LLM produces a structured summary (policy files, patterns detected, recommended focus areas) that is injected into the executor's context as a `## Scout Analysis` section, giving the executor a head start.

Replaced the previous reactive DAG-based scout which had no task awareness, no depth control, and no prioritization.

**Status**: Redesigned (replaced DAG-based scout).

### 3. Strong Safety Mechanisms

- **Protected files** — policy files can't be deleted or moved by the LLM, with dynamic expansion from scout results.
- **Programmatic guard system** — four standalone guard functions executed as pre-dispatch checks (see Strength 14 for full details).
- **Prompt injection defense** — task text wrapped in `<task>` delimiters. Injection Response Protocol: refuse entire task with `OUTCOME_DENIED_SECURITY` when injection detected.
- **Step limit** (30 steps) — prevents infinite loops and runaway costs.
- **Immutable dispatch context** — guard parameters are frozen (`DispatchContext` dataclass), eliminating thread-safety hazards under concurrent dispatch (see Strength 15 for full details).

**Status**: Significantly enhanced (programmatic guards, injection protocol, DispatchContext pattern).

### 4. Provider-Agnostic LLM Access

LiteLLM enables swapping between OpenAI, Anthropic, AWS Bedrock, Azure, and Vertex AI via environment variable. No code changes needed.

**Status**: Maintained.

### 5. Graceful Degradation for Observability

Langfuse integration is a model of optional features: optional dependency group, `ImportError` handled, missing env vars → silent no-op, fire-and-forget async callbacks. Additionally includes a TCP reachability check — if credentials are set but the host is unreachable, observability is silently disabled rather than causing errors.

**Status**: Improved (added host reachability check).

### 6. Parallel Tool Dispatch

`dispatch_parallel()` with `ThreadPoolExecutor(max_workers=4)` executes multiple tool calls concurrently, reducing wall-clock time for multi-tool steps.

**Status**: Maintained.

### 7. Comprehensive TDD Test Suite

Every module has dedicated tests. `conftest.py` handles pre-mocking of `bitgn` and `connectrpc` protobuf dependencies. Tests organized by task/requirement for traceability.

**Status**: Maintained.

### 8. Grounding Reference Tracking

`GroundingTracker` merges programmatically-tracked file reads with LLM-declared references, ensuring `report_completion` always includes all files the agent actually read.

**Status**: Maintained.

### 9. Three-Layer Context Compression Pipeline

A defense-in-depth strategy against unbounded context growth, implemented as three independent layers in `context.py` (pure functions) with orchestration in `loop.py`:

- **Layer 1 — Tool result truncation**: Applied at the `dispatch_tool()` boundary. JSON-aware truncation preserves the JSON envelope while cutting the largest string value within the character budget. Configurable limit (default 10K chars). `report_completion` is exempt.
- **Layer 2 — Smart micro-compact**: A zero-cost pass before every `call_llm()` that replaces old tool results with **format-aware summaries** instead of deleting them. `_summarize_tool_result()` dispatches to `_extract_file_summary()` which handles five content types: JSON records (extracts scalar fields like IDs, names, emails, dates; drops arrays and body text), emails (extracts From/Subject/To headers), markdown (skips frontmatter and HTML comments, takes title + first meaningful line), line-numbered content (strips `"     1\t..."` prefixes first), and generic text (first 150 chars). Batch-based detection preserves the N most recent tool-use turns (default 10). Never removes messages or `tool_call_id` linkage. The model sees `[compacted] read_file "outbox/seq.json": {"id": 84845}` instead of `[Previous tool result cleared]`, eliminating the need to re-read files.
- **Layer 3 — Auto-compact**: When estimated tokens exceed a configurable threshold (default 80K), an LLM summarization call compresses the entire conversation into [system, summary, ack]. Pre-compaction transcripts are saved as JSONL for audit/debugging.

Additionally exposes a `compact` tool that lets the LLM trigger summarization on-demand (sentinel pattern, same as `report_completion`). Scout phase uses Layer 1 + Layer 2 only (no auto-compact), with independently tunable settings.

All parameters configurable via environment variables (`CTX_TRUNCATION_LIMIT`, `CTX_AUTO_COMPACT_THRESHOLD`, etc.). Backward-compatible: `context_config=None` skips all layers.

**Status**: New.

### 10. Self-Verification Loop

A pre-submission verification loop intercepts `report_completion` (both tool-call and text-only auto-submit paths) to let the LLM double-check its answer before final submission. Configurable via `VERIFY_ENABLED` and `VERIFY_MAX_ATTEMPTS` (default: 2) environment variables.

Key design decisions:
- **Pure leaf module** (`verify.py`): `VerificationState` dataclass, `should_verify()`, `build_verification_prompt()`, `detect_verification_outcome()` — all pure functions with zero `agent/` imports.
- **Pre-filter pattern**: `report_completion` is separated from other tool calls before `dispatch_parallel()`, so the harness never receives a premature answer. Other tool calls in the same response are dispatched normally.
- **Policy-aware prompt**: Verification prompt embeds all policy file contents from the scout summary inline (saves LLM steps vs. re-reading).
- **Defense in depth**: `verification_max_attempts` caps re-verification cycles; the 30-step executor limit caps total execution.
- **Structured text extraction**: `_try_extract_completion()` handles weaker models that output tool calls as text (JSON, `report_completion({...})`, or Python kwargs syntax) instead of using the tool mechanism.
- **Empty response fallback**: If the LLM returns empty content during a verification cycle, the captured answer is submitted rather than dropping it silently.
- **Graceful unknown tool handling**: `dispatch_tool()` returns an error JSON for unrecognized tool names instead of crashing with `ValueError`.
- **Backward compatible**: Disabled by default (`verification_enabled=False`). When disabled, identical behavior to pre-verification code with no overhead beyond a single boolean check.

**Status**: New.

### 11. Embedded Skills System

Behavioral rules live in skill markdown files (`SKILL.md` with YAML frontmatter), not hardcoded in Python. The `SkillLoader` class scans a skills directory, parses frontmatter for Layer 1 metadata (descriptions), and provides Layer 2 body content on demand.

**Three skill categories**:

| Category | Skills | Injection Point | Loading Mechanism |
|---|---|---|---|
| Always-on | `security-posture`, `execution-discipline` | System prompt (`embedded_skill_bodies` parameter in `build_system_prompt()`) | Loaded at startup, embedded in every LLM call |
| On-demand | `pattern-match-create`, `policy-gate`, `workspace-discovery` | Tool result (returned to LLM when it calls `load_skill()`) | LLM triggers via `load_skill` tool call; Layer 1 descriptions in system prompt let the LLM know what's available |
| Verification | `self-verification`, `verification-frame` | Verification prompt (`checklist_body` and `frame_template` parameters in `build_verification_prompt()`) | Loaded at startup, injected only during self-verification cycles |

**Key design decisions**:
- `prompt.py` is a pure structural assembler -- zero behavioral content. All rules come from skill files.
- `verification-frame` externalizes the verification prompt structure (`<verification>` tags, section headings, instruction text) into a skill template with `{{ANSWER}}`, `{{CODE}}`, `{{POLICY_SECTION}}`, `{{CHECKLIST_SECTION}}`, `{{SOURCE_BASENAME_SECTION}}`, `{{PLAN_STATUS_SECTION}}` placeholders. When the skill file is missing, `build_verification_prompt()` falls back to the inline frame (backward compatible). The `plan_status` parameter injects plan completion status into the verification prompt so the verifier can check whether all planned steps were completed.
- Always-on skills are loaded unconditionally; on-demand skills are catalog-only until the LLM explicitly requests them.

**Status**: Enhanced (added `verification-frame` skill with placeholder substitution).

### 12. Full PCM Outcome Vocabulary

All 5 PCM outcome codes are exposed in the `report_completion` tool schema with self-documenting enum names matching the reference agent pattern.

| Code | Usage Context |
|---|---|
| `OUTCOME_OK` | Task completed successfully. The agent produced a valid answer with grounding references. |
| `OUTCOME_ERR_INTERNAL` | Agent encountered an internal error (LLM failure, runtime exception, unexpected state) that prevented task completion. |
| `OUTCOME_NONE_UNSUPPORTED` | Task type is not supported by the agent's capabilities (e.g., requires a tool that doesn't exist, asks for something outside the agent's scope). |
| `OUTCOME_DENIED_SECURITY` | Task was refused for security reasons: prompt injection detected, policy violation, or unsafe operation requested. Used by the Injection Response Protocol. |
| `OUTCOME_NONE_CLARIFICATION` | Task is ambiguous or incomplete; the agent cannot proceed without additional information or clarification from the user. |

The codes are defined as a string enum in the `report_completion` tool schema (`tools.py`). The `_handle_report_completion` handler in `dispatch.py` passes the code directly to `vm.answer()`. During self-verification, `build_verification_prompt()` injects the captured code so the verifier can confirm or correct it.

**Status**: Enhanced (usage context documented).

### 13. SDK v2 Tool Capabilities

Updated to bitgn SDK v2 (20260324) with enhanced tool parameters and PCM-specific tools.

**Enhanced parameters** (available on both Mini and PCM runtimes):
- **Line-range reads**: `read_file(path, number, start_line, end_line)` -- partial file reads for context efficiency. The scout prompt instructs the LLM to use `start_line`/`end_line` for files exceeding ~200 lines.
- **Line-range writes**: `write_file(path, content, start_line, end_line)` -- surgical edits without full file rewrites.
- **Depth-limited tree**: `tree(path, level)` -- controlled directory outline. Configurable via `ScoutConfig.tree_level` (default 3, overridable with `SCOUT_TREE_LEVEL` env var). `MiniRuntime` accepts but gracefully ignores the `level` parameter; `PcmRuntime` passes it to `TreeRequest`.

**PCM-specific tools** (available only when `runtime_type == "pcm"`, via `get_tool_schemas("pcm")`):
- **`find`**: Find files or directories by name pattern. Parameters: `name` (pattern), `root` (search root, default `/`), `kind` (`all`/`files`/`dirs`), `limit` (max results, default 10).
- **`mkdir`**: Create a directory. Protected file guard applies (cannot create over protected paths).
- **`move`**: Move or rename a file or directory. Protected file guard prevents moving protected policy files.

Tool schema flow: `tools.py` (schema definitions) -> `dispatch.py` (handler routing + guard checks) -> `runtime.py` (VM adapter calls). `_PCM_EXTRA_SCHEMAS` are appended to `TOOL_SCHEMAS` by `get_tool_schemas("pcm")`.

**Status**: Enhanced (PCM-specific tools documented, scout tree_level configurable).

### 14. Programmatic Guard System

Four standalone guard functions in `dispatch.py` implement pre-dispatch safety checks. Each guard is a pure function that reads from `DispatchContext` (Strength 15), returns an error message string to block or `None` to allow, and logs every decision for observability.

#### Basename Mismatch Guard (`_check_basename_guard`)

- **Trigger**: `write_file` operations when `dispatch_ctx.source_basename` is set.
- **Purpose**: Prevents the LLM from creating renamed derivatives of the source file (e.g., writing `2026-03-23__0000__hn-foo.md` when the source is `hn-foo.md`).
- **Decision logic**:
  1. No `source_basename` configured -> ALLOW (guard inactive).
  2. Written basename matches source exactly -> ALLOW.
  3. Extract slug from both filenames (stripping date/numeric prefixes via `_extract_slug()`). Same slug but different full stem -> BLOCK (segment was inserted).
  4. Different slug -> ALLOW (unrelated file, not a derivative).
- **Configuration source**: `DispatchContext.source_basename`, derived from `TaskConstraints.source_file` (extracted by LLM or regex fast-path).

#### Scope-Constrained Write Guard (`_check_scope_guard`)

- **Trigger**: `write_file` operations when `dispatch_ctx.scope_constrained` is `True`.
- **Purpose**: Prevents the LLM from modifying files that were read for context only, when the task explicitly requests a focused diff.
- **Decision logic** (intent-aware five-step):
  1. Not scope-constrained -> ALLOW (no constraint active).
  2. File not previously read (not in `GroundingTracker`) -> ALLOW (new file creation).
  3. File path starts with any entry in `target_directories` -> ALLOW (task-approved target).
  4. File basename matches `source_basename` -> ALLOW (source file itself).
  5. Otherwise -> BLOCK with descriptive error message.
- **Configuration source**: `DispatchContext.scope_constrained` (from `TaskConstraints.scope_level == "focused"`), `DispatchContext.target_directories` (from `TaskConstraints.target_directories`), `GroundingTracker` instance (tracks all files read during execution).

#### Template Deletion Guard (`_check_template_guard`)

- **Trigger**: `delete_file` operations targeting files whose basename starts with `_`.
- **Purpose**: Protects structural scaffolding files (templates, config files prefixed with `_`) from accidental deletion.
- **Decision logic** (configurable directory-scoped):
  1. Basename does not start with `_` -> ALLOW (not a template file).
  2. `protected_directories` is empty -> BLOCK all `_`-prefixed deletions (backward compatibility default).
  3. File path is inside any `protected_directory` -> BLOCK.
  4. File path is outside all protected directories -> ALLOW (not in protected scope).
- **Configuration source**: `DispatchContext.template_guard_config.protected_directories`, read from the `TEMPLATE_PROTECTED_DIRS` environment variable (comma-separated directory paths). Empty value triggers backward-compatible block-all behavior.

#### Protected File Guard (inline in handlers)

- **Trigger**: `delete_file` and `move` operations targeting policy files.
- **Purpose**: Prevents deletion or relocation of policy files discovered during the scout phase.
- **Decision logic**: Path is normalized and checked against the `protected_files` set. This set starts with `{"agents.md"}` and is expanded dynamically with all policy file paths discovered by the scout phase.
- **Configuration source**: `protected_files: set[str]` parameter passed to `dispatch_tool()` and handlers. Built by `loop.py` from the scout summary.

**Guard invocation order in `dispatch_tool()`**:
1. If `dispatch_ctx` is not `None` and tool is `write_file`: run basename guard, then scope guard.
2. If `dispatch_ctx` is not `None` and tool is `delete_file`: run template guard.
3. Protected file guard runs inside the `_handle_delete_file` and `_handle_move` handlers (always active, independent of `dispatch_ctx`).

If any guard returns a non-None error, `dispatch_tool()` short-circuits and returns `{"error": "..."}` JSON without calling the VM handler.

**Status**: New.

### 15. DispatchContext Pattern

The `DispatchContext` pattern eliminates module-level mutable globals and provides thread-safe guard parameter flow through the dispatch chain.

**Data flow**:

```
Task text
    |
    v
_extract_task_constraints_regex(task_text)     -- regex fast-path
    |  returns None if ambiguous
    v
_extract_task_constraints_llm(model, text)     -- LLM fallback (fail-open)
    |
    v
TaskConstraints (frozen dataclass)
    |   source_file: str | None
    |   scope_level: "focused" | "normal"
    |   target_directories: tuple[str, ...]
    |
    v
DispatchContext (frozen dataclass)             -- constructed once per task in loop.py
    |   source_basename = constraints.source_file
    |   scope_constrained = (scope_level == "focused")
    |   target_directories = constraints.target_directories
    |   template_guard_config = TemplateGuardConfig(protected_directories=...)
    |
    +---> dispatch_tool(vm, name, args, tracker, protected, ..., dispatch_ctx)
    |         |
    |         +---> _check_basename_guard(dispatch_ctx, path)
    |         +---> _check_scope_guard(dispatch_ctx, path, tracker)
    |         +---> _check_template_guard(dispatch_ctx, path)
    |
    +---> dispatch_parallel(vm, tool_calls, tracker, protected, ..., dispatch_ctx)
              |
              +---> Each concurrent thread receives the same frozen dispatch_ctx
                    (immutable, no locking needed)
```

**Key design decisions**:
- **Frozen dataclasses**: `DispatchContext`, `TaskConstraints`, and `TemplateGuardConfig` are all `@dataclass(frozen=True)`. Immutability guarantees that concurrent threads in `dispatch_parallel()` cannot modify shared state.
- **Constructed once per task**: `loop.py` builds the `DispatchContext` after constraint extraction. The same instance is passed to every `dispatch_tool()` and `dispatch_parallel()` call throughout the executor loop.
- **Backward compatible**: When `dispatch_ctx` is `None`, all context-dependent guards are disabled. This allows legacy callers and the scout phase (which uses read-only tools) to work without providing a context.
- **No module-level mutable state**: The former `_source_basename` and `_scope_constrained` globals in `dispatch.py` were removed entirely. Guard functions read all inputs from their parameters.
- **Hybrid constraint extraction**: The regex fast-path (`_extract_task_constraints_regex`) handles trivial cases (file path and scope phrases detected with high confidence) without an LLM call. The LLM fallback (`_extract_task_constraints_llm`) handles ambiguous tasks. On any extraction failure, the system defaults to `TaskConstraints()` which disables all constraint-based guards (fail-open).

**Status**: New.

### 16. Weak-Model Resilience System

A five-point resilience mechanism in `loop.py` that handles three weak-model failure modes (empty LLM responses, tool calls as plain text, no error recovery) without adding overhead for strong models. All resilience state is tracked in a mutable `ResilienceState` dataclass; all thresholds are configurable via a frozen `ResilienceConfig` dataclass with `from_env()` pattern (same as `ContextConfig`).

**Intervention points**:

| Point | Trigger | Action | Config |
|---|---|---|---|
| A - Empty Response | LLM returns empty/whitespace with no tool calls | Retry with nudge (includes available tool names); fallback submit with `OUTCOME_ERR_INTERNAL` after max retries | `RESILIENCE_EMPTY_RETRY_MAX` (default 3) |
| B - Text-as-Tool | LLM outputs tool-call JSON as plain text (not via function calling) | Inject correction message naming the detected tool; fall through to auto-submit after max re-prompts | `RESILIENCE_TEXT_TOOL_MAX` (default 2) |
| C - Error Recovery | Tool dispatch returns NOT_FOUND or consecutive errors | Append recovery hint to tool result; escalation message with tool names after threshold | `RESILIENCE_ERROR_THRESHOLD` (default 3) |
| D - Post-Loop Guard | Loop exits without `report_completion` called | Submit fallback (verification answer if available, else `OUTCOME_ERR_INTERNAL`) | Always active |
| E - Re-Planning | 3 identical tool calls (repetition) or N steps without completion (stall) | Auto-compact context + inject checkpoint prompt (no tool names in checkpoint) | `RESILIENCE_REPLAN_INTERVAL` (default 8) |

**Detection helpers**: `_looks_like_tool_call()` checks for distinguishing parameter combinations (e.g., `{path, content}` -> write_file, `{pattern}` -> search) but returns False for ambiguous cases (`{path}` alone) and for dicts containing `answer` (handled by `_try_extract_completion`). Pre-check: returns False immediately if text does not start/end with `{}` (zero overhead for non-JSON text).

**Known model behavior pattern (Root Cause 2)**: Weaker models (e.g., openai.gpt-oss-120b) sometimes output tool-call JSON as raw text instead of using the function calling mechanism. This affects 3/9 failures at the 47% score level. The text-as-tool detector (Point B) handles this by detecting the JSON pattern and re-prompting the model to use function calling.

**Zero-overhead design**: When the model behaves correctly (valid tool calls, valid text responses), no resilience logic executes beyond lightweight counter increments and a boolean check at loop exit. No extra LLM calls, no string parsing, no message injections.

**Verification-replan collision fix**: Verification interception now resets `steps_since_completion_attempt` at both interception points (text-only auto-submit and `report_completion`). This prevents the replan checkpoint from firing during verification cycles, which previously caused post-completion damage (spurious `mkdir`, double-writes to `seq.json`).

**Status**: Enhanced (spec: weak-model-resilience + persistent-task-planner).

### 17. Persistent Task Planner

A plan-on-disk system that lets the model decompose tasks into steps and save key facts, with all state stored on the **host filesystem** (`/tmp/ai-bitgn-plans/{uuid}/steps.json`) rather than the sandbox VM. Plans survive context compression because they exist outside the conversation.

**Five plan tools**:

| Tool | Purpose | Key Design |
|---|---|---|
| `plan_create` | Decompose task into discrete steps | Writes `steps.json` on host; overwrites existing plan |
| `plan_step_done` | Mark steps completed | Accepts single int or **batch array** (`[0, 1, 2]`) to reduce step overhead |
| `plan_step_skip` | Mark steps unnecessary | Skipped steps excluded from incomplete count in summary |
| `plan_status` | Read plan from disk | Used after context compression to reorient |
| `plan_note` | Save key facts (IDs, emails, dates) | Appended to `notes` array in plan JSON; surfaced in replan checkpoints |

**Integration points**:

- **Replan checkpoint (Point E)**: `_read_plan_for_checkpoint()` reads the plan from disk and injects a `<plan-status>` block showing step completion markers (`[DONE]`, `[PENDING]`, `[SKIPPED]`), saved notes, and revision guidance. When all steps are done, suggests `report_completion`.
- **Pre-completion verification**: `_read_plan_for_verification()` injects plan status into the verification prompt via `{{PLAN_STATUS_SECTION}}` placeholder, showing incomplete steps with review instructions.
- **Execution-discipline skill**: Updated to teach `plan_create` (persist step list), `plan_step_done` (batch marking), `plan_note` (save key facts immediately after reads), and `plan_status` (review before completion).

**Host-side storage design**: Plans are stored under `/tmp/ai-bitgn-plans/{uuid}/` using the `trace_id` generated at `run_agent()` start. This prevents plan artifacts from appearing in the sandbox VM filesystem, which is diff-scored by benchmarks. `init_plan_storage()` creates the directory; all plan handlers use `get_plan_file_path()` and Python's built-in file I/O (no VM read/write, no protobuf).

**Summary format**: Adapts to skipped steps — `"3/5 steps completed"` vs. `"3/4 actionable steps completed, 1 skipped"` (denominator = total - skipped).

**Status**: New (spec: persistent-task-planner).

---

## Weaknesses

### 1. ~~No Error Recovery or Re-Planning~~

~~The executor loop is a simple linear sequence. If the LLM goes down a wrong path, there is no mechanism to detect this and re-plan. Only safeguards: 30-step hard limit and auto-submit on text-only responses.~~

**Status**: **Addressed** (see Strength #16). Five-point resilience system: empty response retry with nudge, text-as-tool detection and correction, error recovery hints with escalation, guaranteed answer submission post-loop guard, and re-planning checkpoints with repetition detection. All configurable via environment variables, zero overhead for strong models.

### 2. ~~No Memory / Context Management~~

~~The message list grows unboundedly across the 30 steps. Large tool results get appended in full and stay in context forever. No summarization, truncation, or sliding window.~~

**Status**: **Addressed** (see Strength #9). Three-layer compression pipeline: tool result truncation at dispatch, micro-compact per-turn pruning, auto-compact LLM summarization at token threshold. All configurable via environment variables.

### 3. Hardcoded Configuration

Several values have no configuration surface:
- `max_workers=4` in `dispatch_parallel()`
- `max_tokens=16384` in `call_llm()`
- 30-step limit in executor loop
- `{"agents.md"}` as static protected files baseline
- Retry parameters (3 retries, 1s base delay)

**Impact**: Tuning requires code changes.
**Status**: Open.

### 4. Scout Phase Cost

The scout now consumes LLM tokens (Phase 2). Estimated ~3K-15K tokens per scout run depending on workspace complexity. The LLM decides exploration depth, so large workspaces may require more steps.

**Impact**: Token cost per task increased; mitigated by configurable `SCOUT_MODEL` env var (can use a cheaper model) and `max_steps` default of 20.
**Status**: Addressed (replaced DAG limitations with LLM intelligence; cost is the tradeoff).

### 5. No Streaming or Progressive Output

`call_llm()` waits for the full response. No streaming, progress indicators, or partial result handling.

**Impact**: Agent appears frozen during long LLM calls; can't abort early.
**Status**: Open.

### 6. ~~Thread Safety Concerns~~

~~`GroundingTracker` uses a plain `set[str]` without synchronization. `dispatch_parallel()` passes the tracker to all concurrent handlers that call `tracker.add()` from different threads.~~

**Status**: **Addressed** (spec: agent-guard-architecture, Tasks 1 & 2). `GroundingTracker` now uses `threading.Lock` for all operations (see Strength #1, tracker.py). Module-level mutable globals replaced with frozen `DispatchContext` dataclass (see Strength #15). Concurrent test suite validates thread safety.

### 7. ~~No Tool Result Validation~~

~~`dispatch_tool()` returns raw serialized results without schema validation or size limits. A large file in the sandbox could blow up context or increase costs.~~

**Status**: **Partially addressed** (see Strength #9). Tool results are now truncated at the dispatch boundary with configurable limits (Layer 1). JSON-aware truncation preserves structure. Schema validation of tool results is still not implemented — the truncation handles the size problem but not structural correctness.

### 8. Limited Observability for Non-LLM Operations

Langfuse traces LLM calls (both executor and scout Phase 2, with separate `trace_id`s). No structured telemetry for:
- Scout Phase 1 bootstrap execution timing
- Tool dispatch latency
- End-to-end task timing
- Per-tool error rates

**Impact**: Blind spots when diagnosing performance issues outside LLM calls.
**Status**: Partially improved (scout LLM calls now traced via Langfuse); remaining gaps open.

### 9. ~~Single-Attempt Completion~~

~~No mechanism for self-verification before submitting. No multi-attempt strategies, confidence scoring, or refinement loops. Auto-submit (text-only response → `report_completion`) could fire prematurely.~~

**Status**: **Addressed** (see Strength #10). Self-verification loop intercepts `report_completion` and text-only auto-submit, injects a policy-aware verification prompt, and gives the LLM up to N attempts to confirm or correct its answer. Includes structured text extraction for weaker models and empty-response fallback. Configurable via `VERIFY_ENABLED` and `VERIFY_MAX_ATTEMPTS`.

### 10. No Caching Layer

Every `run_agent()` starts fresh. Scout re-explores the workspace even if unchanged. No caching of scout results, file contents, or LLM responses.

**Impact**: Redundant work across multiple tasks against the same sandbox.
**Status**: Open.

### 11. ~~Module-Level Mutable Globals in Dispatch~~

~~`dispatch.py` uses `_source_basename` and `_scope_constrained` module-level globals set by `dispatch_tool()` before handler invocation. These race under `dispatch_parallel()` with `ThreadPoolExecutor`.~~

**Status**: **Addressed** (spec: agent-guard-architecture, Task 2). Globals removed, replaced with frozen `DispatchContext` dataclass. See Strength #15.

### 12. ~~Regex-Based Task Parsing~~

~~`loop.py` uses `_FILE_PATH_RE` regex and `_SCOPE_PHRASES` tuple to extract task constraints. Fragile, English-only, benchmark-coupled.~~

**Status**: **Addressed** (spec: agent-guard-architecture, Task 5). Hybrid approach implemented: regex fast-path for trivial cases, LLM fallback for ambiguous tasks. Fail-open on extraction errors.

### 13. ~~No Tests for Dispatch Guards~~

~~`_is_basename_mismatch()`, `_extract_slug()`, scope guard, template guard — all production code with zero unit tests.~~

**Status**: **Addressed** (spec: agent-guard-architecture, Task 7). 67 guard tests added covering all functions, end-to-end dispatch paths, and guard interactions.

---

## Summary Scorecard

| Aspect              | Rating   | Notes                                                                   |
|---------------------|----------|-------------------------------------------------------------------------|
| Modularity          | Strong   | Clean boundaries, no circular deps, 11 modules                         |
| Safety              | Strong   | Protected files, template guards, injection protocol, basename/scope guards |
| Provider flexibility| Strong   | LiteLLM-based, config-driven                                           |
| Scout intelligence  | Strong   | Task-aware LLM explorer with structured analysis                       |
| Context management  | Strong   | Three-layer compression: truncation, **smart micro-compact** (format-aware summaries), auto-compact; persistent plan-on-disk |
| Self-verification   | Strong   | Pre-submission verification loop with policy-aware prompt, text extraction, fallbacks |
| Observability       | Partial  | LLM calls traced; Langfuse host reachability check; tool dispatch ops not traced |
| Error handling      | Strong   | 5-point resilience + persistent plan tools; verification-replan collision fix; smart micro-compact preserves key facts |
| Scalability         | Moderate | Context managed, but no caching layer                                  |
| Testability         | Strong   | Comprehensive TDD suite (812 tests); full guard coverage; resilience + plan tool tests |
| Robustness          | Strong   | Thread-safe tracker, frozen DispatchContext, 67 guard tests             |
| SDK integration     | Strong   | SDK v2 line-range reads/writes, depth-limited tree, all PCM tools      |
| Outcome vocabulary  | Strong   | All 5 PCM outcome codes, self-documenting enum names                   |

---

## Changelog

| Date       | Change                                                                          |
|------------|---------------------------------------------------------------------------------|
| 2026-03-20 | Initial analysis created                                                        |
| 2026-03-20 | Updated for two-phase LLM scout (replaced DAG-based scout)                      |
| 2026-03-23 | Updated for three-layer context compression pipeline; weaknesses #2 and #7 addressed; added Langfuse host reachability check; test count 388→436 |
| 2026-03-23 | Added self-verification loop (verify.py); weakness #9 addressed; structured text extraction for weaker models; graceful unknown tool handling; LiteLLM/Langfuse log suppression; per-task timing in benchmark runner; test count 436→501 |
| 2026-03-24 | Full PCM outcome codes (5 codes, self-documenting names); embedded skills system (security-posture, execution-discipline, self-verification); programmatic dispatch guards (basename mismatch, scope constraint, template protection); SDK v2 upgrade (line-range read/write, depth-limited tree); prompt.py made pure structural assembler; injection response protocol; spec `agent-guard-architecture` generated for remaining gaps (globals→context, regex→LLM, tests); test count 501→534 |
| 2026-03-25 | Spec `agent-guard-architecture` fully implemented (Tasks 1-8): thread-safe tracker (Lock), frozen DispatchContext (eliminates globals), scout SDK v2 depth-limited tree, externalized verification frame, hybrid LLM constraint extraction (regex fast-path + LLM fallback), configurable template guard, 67 guard tests, weaknesses #6/#11/#12/#13 addressed; test count 534→715+ |
| 2026-03-25 | Spec `weak-model-resilience` fully implemented (Tasks 1-11): 5-point resilience system (empty response retry, text-as-tool detection, error recovery hints, post-loop guard, re-planning checkpoints); ResilienceConfig/ResilienceState dataclasses; _looks_like_tool_call/_detect_tool_name helpers; 37 new tests; weakness #1 addressed; error handling rating Moderate→Strong; test count 715→738+ |
| 2026-03-26 | Spec `persistent-task-planner` fully implemented with iterative benchmark-driven fixes: 5 plan tools (plan_create, plan_step_done with batch indices, plan_step_skip, plan_status, plan_note) on host-side local storage (`/tmp/ai-bitgn-plans/{uuid}/`); smart micro-compact replaces destructive deletion with format-aware summaries (`_summarize_tool_result`, `_extract_file_summary` — handles JSON records, emails, markdown, line-numbered content); micro_compact_keep_batches 5→10; verification-replan collision fix (reset replan timer on verification interception to prevent post-completion damage); `{{PLAN_STATUS_SECTION}}` placeholder in verification-frame; execution-discipline skill updated with plan tool guidance and softened OUTCOME_NONE_CLARIFICATION; test count 738→812 |
