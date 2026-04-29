# Design: modular-refactor

> Architectural design for decomposing the monolithic `agent.py` (1347 lines) into a composable `agent/` subpackage, adding a unit test suite, centralizing configuration, deduplicating prompt rules, improving output truncation, adding micro-compact, and removing dead code -- all while preserving the 100% (30/30) PAC1 benchmark score.

## Status: Generated

---

## 1. Architecture Overview

The refactoring restructures the PAC1-PY agent from a single-file monolith into a layered, phase-based package architecture. The existing runtime behavior (Bootstrap -> Planner -> Executor -> Decision-Lock -> Validator -> Apply Writes -> Submit) is preserved identically; only the code organization changes.

```
┌─────────────────────────────────────────────────────────────────────┐
│                           main.py                                   │
│         (benchmark orchestration, unchanged except import)          │
│                              │                                      │
│                    from agent import run_agent                       │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                        agent/ package                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐           │
│  │bootstrap │  │ planner  │  │ executor │  │ validator  │           │
│  │ (Phase 1)│  │ (Phase 2)│  │ (Phase 3)│  │ (Phase 4)  │           │
│  │ no LLM   │→ │ 1 LLM   │→ │ N tools  │→ │ lock+LLM   │           │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └─────┬─────┘           │
│       │              │             │               │                │
│  ┌────▼──────────────▼─────────────▼───────────────▼─────┐          │
│  │              shared layer                              │          │
│  │  ┌──────────┐ ┌──────────┐ ┌────────┐ ┌────────────┐ │          │
│  │  │ dispatch │ │ context  │ │ llm    │ │  prompts   │ │          │
│  │  │          │ │          │ │        │ │            │ │          │
│  │  └────┬─────┘ └────┬─────┘ └───┬────┘ └─────┬──────┘ │          │
│  │       │             │           │             │        │          │
│  │  ┌────▼─────────────▼───────────▼─────────────▼─────┐ │          │
│  │  │                  config                          │ │          │
│  │  └──────────────────────────────────────────────────┘ │          │
│  └───────────────────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────────────┘
         │                    │                  │
┌────────▼────────┐ ┌────────▼────────┐ ┌───────▼─────────┐
│    tools.py     │ │    tasks.py     │ │    skills.py    │
│  (leaf, pure    │ │  (leaf, +public │ │  (leaf,         │
│   data, as-is)  │ │   accessors)    │ │   unchanged)    │
└─────────────────┘ └─────────────────┘ └─────────────────┘

              observability.py  (leaf, KEEP AS-IS)
```

### Dependency Direction (Requirement 2)

Dependencies flow strictly downward. No module in a lower layer imports from an upper layer.

```
Layer 0 (entry):     main.py
Layer 1 (package):   agent/__init__.py
Layer 2 (phases):    agent/executor.py, agent/bootstrap.py, agent/planner.py, agent/validator.py
Layer 3 (shared):    agent/dispatch.py, agent/context.py, agent/llm.py, agent/prompts.py
Layer 4 (config):    agent/config.py
Layer 5 (leaf):      tools.py, tasks.py, skills.py, observability.py
```

No circular imports exist by construction: each layer imports only from layers with a higher number.

---

## 2. Component Design

### 2.1. `agent/config.py` -- Centralized Configuration

**Traces to**: AC 5.1, AC 5.2, AC 5.3, AC 5.4

A frozen dataclass that consolidates all runtime-configurable values currently scattered across `agent.py` module-level constants and `os.environ.get()` calls.

```
@dataclass(frozen=True)
class AgentConfig:
    # Output and context
    output_cap: int                      # CTX_TRUNCATION_LIMIT, default 10_000
    auto_compact_threshold: int          # CTX_AUTO_COMPACT_THRESHOLD, default 80_000
    micro_compact_enabled: bool          # default False
    micro_compact_keep_turns: int        # default 5
    smart_truncation_enabled: bool       # default False (feature flag for JSON-aware truncation)

    # LLM
    llm_api_base: str | None             # LLM_API_BASE, default None
    llm_api_key: str | None              # LLM_API_KEY, default None
    max_retries: int                     # default 3
    retry_base_delay: float              # default 1.0
    max_executor_steps: int              # default 50

    @classmethod
    def from_env() -> AgentConfig:
        """Populate from environment variables with current defaults."""
        ...
```

**Imports**: `dataclasses`, `os` (stdlib only).

**Key decisions**:
- Frozen dataclass prevents accidental mutation after startup.
- `from_env()` class method reads environment variables once; all defaults are identical to current hardcoded values (AC 5.4).
- Created once in `run_agent()` and passed down to all modules that need it.
- The `_RETRYABLE_EXCEPTIONS` tuple stays in `agent/llm.py` since it is a code-level constant, not a runtime configuration value.

---

### 2.2. `agent/prompts.py` -- System Prompts and Shared Rules

**Traces to**: AC 1.1, AC 6.1, AC 6.2, AC 6.3, AC 6.4, AC 6.5, AC 10.2

Single source of truth for all prompt text, capability descriptions, shared rules, outcome code documentation, and CLI color constants.

```
# --- Shared rule constants (single source of truth) ---

AGENT_CAN: str                    # capability description (moved from agent.py)
AGENT_CANNOT: str                 # capability description (moved from agent.py)

RULE_KEEP_DIFFS_FOCUSED: str      # the "keep diffs focused" rule text
RULE_LIST_BEFORE_READ: str        # the "list before read" rule text

OUTCOME_CODES_DOC: str            # outcome code documentation block

# --- CLI color constants ---

CLI_RED: str
CLI_GREEN: str
CLI_CLR: str
CLI_BLUE: str
CLI_YELLOW: str
CLI_DIM: str
CLI_BOLD: str
CLI_CYAN: str

# --- Prompt builders ---

def build_executor_system() -> str:
    """Build the executor system prompt.

    Replaces the module-level f-string `_EXECUTOR_SYSTEM`.
    Interpolates AGENT_CAN, AGENT_CANNOT, RULE_KEEP_DIFFS_FOCUSED,
    RULE_LIST_BEFORE_READ at call time (not import time).
    Returns the same prompt text as the current _EXECUTOR_SYSTEM.
    """
    ...

def build_planner_system() -> str:
    """Build the planner system prompt.

    References AGENT_CAN, AGENT_CANNOT, RULE_KEEP_DIFFS_FOCUSED.
    """
    ...

def build_validator_system() -> str:
    """Build the validator system prompt.

    Identical content to current _validate_completion system message.
    """
    ...
```

**Imports**: `skills.py` (for `SkillLoader` used in `get_descriptions`, if needed -- but per dependency rules, prompts.py may import from skills.py). In the current design, AGENT_CAN/AGENT_CANNOT are string constants, not computed from skills, so no import is needed.

**Key decisions**:
- `build_executor_system()` replaces the module-level f-string `_EXECUTOR_SYSTEM`. The f-string currently interpolates `AGENT_CAN` and `AGENT_CANNOT` at import time. Converting to a builder function means interpolation happens at call time, which is functionally identical since the values are constants, but avoids the fragile module-level evaluation.
- `RULE_KEEP_DIFFS_FOCUSED` is the single canonical definition referenced by both `build_executor_system()` and `build_planner_system()`. The execution-discipline SKILL.md will have its copy removed and replaced with a reference to "the system prompt already contains this rule" (AC 6.1, AC 6.5).
- `RULE_LIST_BEFORE_READ` is the single canonical definition referenced by `build_executor_system()`. The inbox-processing SKILL.md already has its own procedural version which is complementary (not a copy), so no change needed there (AC 6.2).
- `OUTCOME_CODES_DOC` provides a single source for outcome code semantics shared by dispatch (`OUTCOME_BY_NAME` mapping) and validation (AC 6.4). The `OUTCOME_BY_NAME` dict itself moves to `dispatch.py` since it requires the protobuf `Outcome` import.

---

### 2.3. `agent/llm.py` -- LLM Call with Retry and Token Estimation

**Traces to**: AC 1.1 (module decomposition)

Extracts `_call_llm`, `_estimate_tokens`, and the retry logic.

```
from agent.config import AgentConfig

# _RETRYABLE_EXCEPTIONS tuple (litellm exception classes)

def call_llm(
    config: AgentConfig,
    model: str,
    messages: list[dict],
    tools: list[dict],
    metadata: dict | None = None,
    max_tokens: int = 16384,
) -> litellm.ModelResponse:
    """Call LLM with tools and retry on transient errors.

    Uses config.llm_api_base, config.llm_api_key, config.max_retries,
    config.retry_base_delay.
    """
    ...

def call_llm_no_tools(
    config: AgentConfig,
    model: str,
    messages: list[dict],
    metadata: dict | None = None,
    max_tokens: int = 2048,
) -> litellm.ModelResponse:
    """Call LLM without tools (for auto-compact summarization).

    Uses config.llm_api_base, config.llm_api_key.
    """
    ...

def estimate_tokens(messages: list[dict]) -> int:
    """Estimate token count from message list (len(json) // 4)."""
    ...
```

**Imports**: `agent/config.py`, `litellm`, `json`, `time`, `logging` (stdlib).

**Key decisions**:
- `config: AgentConfig` is the first parameter, replacing direct `os.environ.get()` calls.
- `call_llm_no_tools` is a separate function (not overloaded) because the auto-compact summarization call has fundamentally different kwargs (no tools, different max_tokens). This avoids optional parameter confusion.
- The `_RETRYABLE_EXCEPTIONS` tuple is defined in this module since it directly governs retry behavior and references `litellm` exception classes.

---

### 2.4. `agent/dispatch.py` -- Tool Dispatch, Shadow Reads, Deferred Writes

**Traces to**: AC 1.1, AC 2.4, AC 8.1, AC 8.2, AC 8.3, AC 8.4

Extracts `_dispatch`, `_load_skill`, `_compact_tree`, and shadow read/write logic.

```
from bitgn.vm.pcm_connect import PcmRuntimeClientSync
from tasks import TaskManager
from skills import SkillLoader
from tools import ...  # no imports needed; tool names are string keys
from agent.config import AgentConfig

def compact_tree(tree_json: str) -> str:
    """Convert JSON tree to compact text like `tree` command output."""
    ...

def load_skill(
    vm: PcmRuntimeClientSync,
    skill_loader: SkillLoader,
    name_or_path: str,
) -> str:
    """Load a skill by name (local) or path (PCM runtime).

    Takes an explicit SkillLoader parameter instead of using the module-level
    _SKILLS global.
    """
    ...

def dispatch(
    vm: PcmRuntimeClientSync,
    name: str,
    args: dict,
    config: AgentConfig,
    tm: TaskManager | None = None,
    defer_writes: bool = False,
    skill_loader: SkillLoader | None = None,
) -> str:
    """Execute a tool call against the PCM runtime. Returns result string.

    Handles:
    - PCM runtime tool calls (tree, find, search, list, read, write, etc.)
    - Task management tools (plan_create, plan_update, etc.) via TaskManager
    - Deferred write operations (stored in TaskManager, not executed)
    - Shadow reads (reflect pending deletes/writes)
    - Output truncation (smart JSON-aware truncation via truncate_output)
    - Inbox security reminders on untrusted file reads
    """
    ...

def truncate_output(text: str, cap: int) -> str:
    """Truncate tool output respecting structure boundaries.

    For valid JSON: truncate at a JSON-safe boundary (end of complete value,
    array element, or object field), then close open brackets/braces. If
    that is not feasible, fall back to character truncation with marker.

    For plain text: truncate at the last complete line boundary before cap.

    Always appends '\\n... [truncated]' marker when truncation occurs.
    """
    ...

# OUTCOME_BY_NAME mapping (requires protobuf Outcome import)
OUTCOME_BY_NAME: dict[str, int]
```

**Imports**: `agent/config.py`, `tasks.py`, `skills.py`, protobuf types, `json`, `re`, `logging`.

**Key decisions**:
- `_load_skill` now takes an explicit `SkillLoader` parameter instead of referencing the module-level `_SKILLS` global. This resolves the dual-dependency issue (gap analysis finding #4).
- `dispatch` takes `config: AgentConfig` to read `output_cap` instead of the module-level `_OUTPUT_CAP`.
- Shadow reads use `tm.files_deleted` and `tm.pending_writes` (new public properties on TaskManager) instead of direct `tm._files_deleted` and `tm._pending_writes` access (gap analysis finding #2).
- `truncate_output` is a new helper that replaces the current naive `txt[:_OUTPUT_CAP] + "\n... [truncated]"` with JSON-aware truncation (AC 8.1--8.4).
- `OUTCOME_BY_NAME` lives here because it requires the protobuf `Outcome` import and is consumed by dispatch and by `executor.py` for the final answer submission.

---

### 2.5. `agent/bootstrap.py` -- Phase 1: Deterministic Discovery

**Traces to**: AC 1.1, AC 10.4

Extracts `_phase1_bootstrap` verbatim.

```
from bitgn.vm.pcm_connect import PcmRuntimeClientSync

def phase1_bootstrap(vm: PcmRuntimeClientSync) -> dict:
    """General-purpose workspace discovery. No LLM calls.

    Returns a context dict with:
      - directory_tree: full tree output (JSON string)
      - agents_md: concatenated content of all AGENTS.md files
      - readmes: concatenated README.md contents
      - skill_paths: list of doc paths from docs/ and 99_process/
    """
    ...
```

**Imports**: protobuf types, `json`, `logging`. Does NOT import from other agent modules.

**Key decisions**:
- The function body is moved verbatim from `agent.py` lines 481--608.
- CLI output (print statements with color codes) is preserved for benchmark compatibility.
- The `_extract_paths` and `_extract_doc_paths` inner functions move with it.

---

### 2.6. `agent/planner.py` -- Phase 2: Task Planning

**Traces to**: AC 1.1, AC 10.4

Extracts `_plan_task`.

```
from agent.config import AgentConfig
from agent.llm import call_llm
from agent.prompts import build_planner_system, CLI_GREEN, CLI_RED, CLI_DIM, CLI_BOLD, CLI_CLR
from agent.dispatch import compact_tree
from skills import SkillLoader
from tools import PLANNER_TOOL

def plan_task(
    config: AgentConfig,
    model: str,
    task_text: str,
    phase1_ctx: dict,
    skill_loader: SkillLoader,
    metadata: dict | None = None,
) -> dict:
    """Analyze task and produce an execution plan.

    Returns dict with:
      - strategy: free-form plan text for the executor
      - instructions: list of applicable rules from AGENTS.md
      - rejection: None if feasible, or dict with outcome/message
    """
    ...
```

**Imports**: `agent/config.py`, `agent/llm.py`, `agent/prompts.py`, `agent/dispatch.py` (for `compact_tree`), `skills.py`, `tools.py`, `json`, `time`.

**Key decisions**:
- `skill_loader` is passed explicitly instead of using the module-level `_SKILLS` global.
- The planner system prompt is constructed via `build_planner_system()` which references `AGENT_CAN`, `AGENT_CANNOT`, and `RULE_KEEP_DIFFS_FOCUSED` from prompts.py.

---

### 2.7. `agent/validator.py` -- Phase 4: Decision-Lock and LLM Validation

**Traces to**: AC 1.1, AC 10.2, AC 10.4

Extracts `_extract_decision_outcome` and `_validate_completion`.

```
from agent.config import AgentConfig
from agent.llm import call_llm
from agent.prompts import build_validator_system, CLI_GREEN, CLI_YELLOW, CLI_DIM, CLI_CLR
from tasks import TaskManager
from tools import VALIDATION_TOOL

def extract_decision_outcome(
    execution_context: str,
    tm: TaskManager | None = None,
) -> str | None:
    """Extract outcome from structured data and VERIFY notes.

    Sources of truth (no keyword heuristics):
    1. Structured: plan_compliance tool -> tm.get_compliance()
    2. Trust level: trust=admin/valid/blacklist from VERIFY notes
    3. Explicit DECISION= notes from the model
    4. CONFLICT notes

    Returns:
    - A definitive outcome when the decision-lock has high confidence
    - "NEEDS_VALIDATOR" when trust=valid + PROCEED (uncertain, needs LLM review)
    - None when no signal at all
    """
    ...

def validate_completion(
    config: AgentConfig,
    model: str,
    task_text: str,
    proposed_message: str,
    proposed_outcome: str,
    agents_md: str,
    execution_context: str,
    metadata: dict | None = None,
    tm: TaskManager | None = None,
) -> dict | None:
    """Validate proposed answer before submitting.

    Decision-lock runs first (deterministic). If inconclusive,
    falls through to LLM validator.

    Returns None if approved, or a dict with corrected outcome/message.
    """
    ...
```

**Imports**: `agent/config.py`, `agent/llm.py`, `agent/prompts.py`, `tasks.py`, `tools.py`, `json`, `time`.

**Key decisions**:
- Functions are renamed from `_extract_decision_outcome` to `extract_decision_outcome` (public, for testability).
- The function bodies are moved verbatim; logic is not rewritten.
- `config` parameter replaces implicit `os.environ.get()` calls for LLM configuration.

---

### 2.8. `agent/context.py` -- Context Assembly and Compaction

**Traces to**: AC 1.1, AC 9.1, AC 9.2, AC 9.3, AC 9.4, AC 9.5

Extracts context assembly logic (from `run_agent`) and `_auto_compact`. Adds new micro-compact.

```
from agent.config import AgentConfig
from agent.llm import call_llm_no_tools, estimate_tokens
from skills import SkillLoader

def build_executor_context(
    phase1_ctx: dict,
    skill_loader: SkillLoader,
) -> str:
    """Assemble the executor context string from phase1 bootstrap results.

    Combines agents_md, workspace tree, folder READMEs, and available skills
    into the structured XML-tagged context block.
    """
    ...

def build_task_message(
    task_text: str,
    plan: dict,
    skill_loader: SkillLoader,
) -> str:
    """Build the task user message with instructions, strategy, and discipline skill."""
    ...

def micro_compact(
    config: AgentConfig,
    messages: list[dict],
) -> None:
    """Replace stale tool results with short placeholders (no LLM call).

    When config.micro_compact_enabled is True:
    - Identifies tool result messages older than config.micro_compact_keep_turns turns
    - Replaces their content with a short summary: tool name + "ok"/"error" status
    - Preserves tool_call_id and message structure (valid for LLM API)
    - Never modifies system message, initial context, or recent N turns

    When config.micro_compact_enabled is False: no-op.

    Mutates messages in-place.
    """
    ...

def auto_compact(
    config: AgentConfig,
    model: str,
    messages: list[dict],
    metadata: dict | None = None,
) -> None:
    """Summarize conversation when token estimate exceeds threshold.

    Runs micro_compact first (AC 9.5), then checks if LLM summarization
    is still needed.

    Mutates messages in-place.
    """
    ...
```

**Imports**: `agent/config.py`, `agent/llm.py`, `skills.py`, `json`.

**Key decisions**:
- `build_executor_context` extracts the context assembly block from `run_agent` (lines 1127--1161 of agent.py). This is pure string construction.
- `build_task_message` extracts the task message construction (lines 1163--1188 of agent.py).
- `micro_compact` runs before `auto_compact` (AC 9.5). It scans messages from the start, skipping the system message (index 0), the initial context messages (indices 1--3), and the most recent `config.micro_compact_keep_turns * 2` messages (each turn = assistant + tool). It replaces qualifying tool result messages with `"{tool_name}: ok"` or `"{tool_name}: error"`, preserving `tool_call_id` and `role: "tool"` (AC 9.2).
- `auto_compact` calls `micro_compact` first, then re-estimates tokens, then proceeds to LLM summarization only if still above threshold (AC 9.5).

---

### 2.9. `agent/executor.py` -- Phase 3: Tool-Call Loop and Orchestrator

**Traces to**: AC 1.1, AC 1.3, AC 10.2, AC 10.3, AC 10.4

Contains the executor loop and the top-level `run_agent` orchestrator.

```
from bitgn.vm.pcm_connect import PcmRuntimeClientSync
from bitgn.vm.pcm_pb2 import AnswerRequest, Outcome
from skills import SkillLoader
from tasks import TaskManager
from tools import EXECUTOR_TOOLS
from agent.config import AgentConfig
from agent.bootstrap import phase1_bootstrap
from agent.planner import plan_task
from agent.validator import validate_completion
from agent.dispatch import dispatch, OUTCOME_BY_NAME
from agent.context import build_executor_context, build_task_message, auto_compact
from agent.llm import call_llm
from agent.prompts import build_executor_system, CLI_RED, CLI_GREEN, CLI_YELLOW, CLI_DIM, CLI_BOLD, CLI_CLR, CLI_CYAN

def _run_executor(
    config: AgentConfig,
    model: str,
    vm: PcmRuntimeClientSync,
    skill_loader: SkillLoader,
    executor_system: str,
    context_msg: str,
    task_msg: str,
    metadata: dict | None = None,
    run_id: str = "",
    defer: bool = True,
) -> tuple[dict | None, TaskManager]:
    """Run one executor session with the tool-call loop.

    Replaces the closure `_run_executor` in agent.py, converting captured
    variables into explicit parameters (gap analysis finding #1).

    Returns (result dict or None, TaskManager instance).
    """
    ...

def run_agent(
    model: str,
    harness_url: str,
    task_text: str,
    metadata: dict | None = None,
) -> None:
    """Top-level agent orchestrator. Signature preserved for main.py (AC 10.3).

    Pipeline: Bootstrap -> Planner -> Executor -> Decision-Lock -> Validator
    -> Apply Writes -> Submit.
    """
    config = AgentConfig.from_env()
    vm = PcmRuntimeClientSync(harness_url)
    skill_loader = SkillLoader(Path(__file__).parent.parent / "skills")

    # Phase 1: Bootstrap
    phase1_ctx = phase1_bootstrap(vm)

    # Phase 2: Planner
    plan = plan_task(config, model, task_text, phase1_ctx, skill_loader, metadata)
    if plan["rejection"]:
        ...  # submit rejection, return

    # Build context and task message
    executor_system = build_executor_system()
    context_msg = build_executor_context(phase1_ctx, skill_loader)
    task_msg = build_task_message(task_text, plan, skill_loader)

    # Phase 3: Executor
    result, tm_exec = _run_executor(
        config, model, vm, skill_loader,
        executor_system, context_msg, task_msg, metadata,
    )

    if not result:
        ...  # submit error, return

    # Phase 4: Decision-Lock + Validator
    correction = validate_completion(
        config, model, task_text,
        result["message"], result["outcome"],
        phase1_ctx.get("agents_md", ""),
        result.get("execution_context", ""),
        metadata, tm_exec,
    )
    ...

    # Apply deferred writes (only for OUTCOME_OK)
    ...

    # Submit final answer
    ...
```

**Imports**: All agent submodules, protobuf types, `json`, `time`, `logging`, `pathlib`.

**Key decisions**:
- `_run_executor` is converted from a closure (capturing 8+ variables -- gap analysis finding #1) into a module-level function with explicit parameters. Every previously captured variable becomes a named parameter.
- `run_agent` signature remains `(model, harness_url, task_text, metadata)` exactly as before (AC 10.3).
- `AgentConfig.from_env()` is called once at the top of `run_agent` and threaded down.
- `SkillLoader` is instantiated once in `run_agent` and passed explicitly to all functions that need it, replacing the module-level `_SKILLS` global.
- The `plan["instructions"]` are passed to `TaskManager.set_instructions()` inside `_run_executor`, same as currently.

---

### 2.10. `agent/__init__.py` -- Package Entry Point

**Traces to**: AC 1.3

```
from agent.executor import run_agent

__all__ = ["run_agent"]
```

This enables `from agent import run_agent` in `main.py`.

---

### 2.11. `tasks.py` -- Public Accessors (Minimal Change)

**Traces to**: AC 1.2, AC 2.3

Two read-only properties are added to expose previously private attributes accessed by dispatch (gap analysis finding #2).

```
class TaskManager:
    ...
    @property
    def files_deleted(self) -> list[str]:
        """Public read-only accessor for _files_deleted."""
        return self._files_deleted

    @property
    def pending_writes(self) -> list[dict]:
        """Public read-only accessor for _pending_writes."""
        return self._pending_writes
```

No other changes. Zero new imports. Remains a leaf module.

---

### 2.12. `main.py` -- Import Path Change Only

**Traces to**: AC 10.3

Single change:

```
# Before:
from agent import run_agent

# After:
from agent import run_agent   # resolves to agent/__init__.py
```

The import statement text is identical because `agent.py` becomes `agent/__init__.py` re-exporting `run_agent`. No other changes to `main.py`.

---

### 2.13. SKILL.md Files -- No Changes Needed

**Traces to**: AC 6.1, AC 6.2, AC 6.5

**Validation finding**: The SKILL.md files do NOT contain verbatim copies of the "keep diffs focused" or "list before read" rules. The `execution-discipline/SKILL.md` has complementary procedural instructions (e.g., "you MUST `list` the folder and read EVERY file"), not duplicated rule text. The `inbox-processing/SKILL.md` similarly has its own workflow steps.

**Decision**: No SKILL.md edits are required. The deduplication target (AC 6.1, AC 6.2) is satisfied by extracting rules from the executor and planner system prompts into `RULE_KEEP_DIFFS_FOCUSED` and `RULE_LIST_BEFORE_READ` constants in `prompts.py`, which the design already does (Section 2.2). The skill files remain unchanged to preserve benchmark behavior.

---

### 2.14. Dead Code Removal

**Traces to**: AC 7.1, AC 7.2, AC 7.3

The following are removed entirely and NOT moved to any new module:
- `_arbiter` function (lines 888--983 of `agent.py`, ~96 lines)
- `_ARBITER_TOOL` schema (lines 853--885 of `agent.py`, ~33 lines)

After removal, zero references to "arbiter", "_arbiter", or "_ARBITER_TOOL" shall exist in any source file (AC 7.2).

---

### 2.15. Unit Test Suite

**Traces to**: AC 3.1, AC 3.2, AC 3.3, AC 3.4, AC 3.5, AC 3.6, AC 3.7

```
pac1-py/tests/
├── conftest.py              # shared fixtures (mock VM, mock TaskManager, tmp skills dir)
├── test_decision_lock.py    # AC 3.1: _extract_decision_outcome
├── test_task_manager.py     # AC 3.2: TaskManager class
├── test_skill_loader.py     # AC 3.3: SkillLoader class
├── test_dispatch.py         # AC 3.4: dispatch, shadow reads, deferred writes
└── test_compact_tree.py     # AC 3.5: compact_tree helper
```

**`tests/conftest.py`**:

```
@pytest.fixture
def mock_vm() -> Mock:
    """Mock PcmRuntimeClientSync with common responses."""
    ...

@pytest.fixture
def tm() -> TaskManager:
    """Fresh TaskManager instance."""
    ...

@pytest.fixture
def skill_loader(tmp_path: Path) -> SkillLoader:
    """SkillLoader with a temporary skills directory."""
    ...

@pytest.fixture
def default_config() -> AgentConfig:
    """AgentConfig with default values."""
    ...
```

**`tests/test_decision_lock.py`** (AC 3.1):

```
class TestExtractDecisionOutcome:
    def test_admin_trust_overrides_deny(self): ...
    def test_blacklist_trust_escalates_clarification_to_deny(self): ...
    def test_valid_trust_escalates_clarification_to_deny(self): ...
    def test_valid_trust_proceed_returns_needs_validator(self): ...
    def test_cross_account_compliance_triggers_clarification(self): ...
    def test_explicit_decision_deny_security(self): ...
    def test_explicit_decision_deny_clarify(self): ...
    def test_explicit_decision_proceed(self): ...
    def test_no_signal_returns_none(self): ...
    def test_conflict_returns_clarification(self): ...
```

**`tests/test_task_manager.py`** (AC 3.2):

```
class TestTaskManager:
    def test_create_plan(self): ...
    def test_update_status_transitions(self): ...
    def test_add_with_blocked_by(self): ...
    def test_completing_unblocks_dependents(self): ...
    def test_defer_write_and_get_pending_writes(self): ...
    def test_track_read_write_delete(self): ...
    def test_set_and_get_compliance(self): ...
    def test_render_output_format(self): ...
    def test_files_deleted_property(self): ...
    def test_pending_writes_property(self): ...
```

**`tests/test_skill_loader.py`** (AC 3.3):

```
class TestSkillLoader:
    def test_load_from_directory(self, tmp_path): ...
    def test_parse_frontmatter(self): ...
    def test_get_descriptions(self, skill_loader): ...
    def test_get_content_existing_skill(self, skill_loader): ...
    def test_get_content_nonexistent_skill(self, skill_loader): ...
    def test_get_names(self, skill_loader): ...
```

**`tests/test_dispatch.py`** (AC 3.4):

```
class TestDispatch:
    def test_shadow_read_deleted_file_returns_not_found(self): ...
    def test_shadow_read_rewritten_after_delete(self): ...
    def test_shadow_list_filters_deferred_deletes(self): ...
    def test_deferred_write_stored_not_executed(self): ...
    def test_deferred_write_tracks_file_operations(self): ...
    def test_handler_dispatch_coverage_all_tools(self): ...
    def test_unknown_tool_returns_error(self): ...
    def test_output_truncation_json(self): ...
    def test_output_truncation_plain_text(self): ...
    def test_inbox_security_reminder(self): ...
```

**`tests/test_compact_tree.py`** (AC 3.5):

```
class TestCompactTree:
    def test_normal_json_tree(self): ...
    def test_root_node_handling(self): ...
    def test_malformed_input_returns_empty(self): ...
    def test_nested_directories(self): ...
```

All tests use `pytest` (AC 3.6) with mocked external dependencies. No PCM runtime, LLM API, or Langfuse instance required.

**`pyproject.toml` addition**:

```toml
[dependency-groups]
dev = [
    "pytest>=8.0",
]
```

---

## 3. Integration Challenges and Solutions

### 3.1. `_run_executor` Closure (Gap Finding #1)

**Problem**: The current `_run_executor` is a closure inside `run_agent` that captures 8+ variables: `vm`, `model`, `metadata`, `context`, `task_msg`, `plan`, `_EXECUTOR_SYSTEM`, `EXECUTOR_TOOLS`.

**Solution**: Convert to a module-level function `_run_executor` in `agent/executor.py` with explicit parameters:

| Captured variable | Becomes parameter |
|---|---|
| `vm` | `vm: PcmRuntimeClientSync` |
| `model` | `model: str` |
| `metadata` | `metadata: dict \| None` |
| `context` (string) | `context_msg: str` |
| `task_msg` | `task_msg: str` |
| `plan["instructions"]` | Passed to `tm.set_instructions()` inside `_run_executor` |
| `_EXECUTOR_SYSTEM` | `executor_system: str` |
| `EXECUTOR_TOOLS` | Imported directly from `tools` |

Additionally: `config: AgentConfig` and `skill_loader: SkillLoader` are added as parameters.

### 3.2. `_dispatch` Private Attribute Access (Gap Finding #2)

**Problem**: `_dispatch` reads `tm._files_deleted` and `tm._pending_writes` directly.

**Solution**: Add public read-only properties `files_deleted` and `pending_writes` on `TaskManager` (see Section 2.11). Update `dispatch.py` to use `tm.files_deleted` and `tm.pending_writes`.

### 3.3. `_EXECUTOR_SYSTEM` Module-Level F-String (Gap Finding #3)

**Problem**: `_EXECUTOR_SYSTEM` is an f-string interpolated at import time using `AGENT_CAN` and `AGENT_CANNOT`.

**Solution**: Replace with `build_executor_system()` function in `prompts.py`. Called once in `run_agent` and passed to `_run_executor` as `executor_system` parameter. Since `AGENT_CAN` and `AGENT_CANNOT` are string constants (not computed at runtime), the result is identical.

### 3.4. `_load_skill` Dual Dependency (Gap Finding #4)

**Problem**: `_load_skill` needs both a `SkillLoader` instance and the PCM `vm` runtime.

**Solution**: Pass both as explicit parameters: `load_skill(vm, skill_loader, name_or_path)`. The `dispatch` function receives `skill_loader` as a parameter and passes it through.

---

## 4. Output Truncation Design (AC 8.1--8.4)

The `truncate_output` function in `dispatch.py` implements structured truncation, **gated behind the `config.smart_truncation_enabled` feature flag** (default: `False`).

**Rationale for feature flag**: JSON-aware truncation produces different token sequences than the current naive cut, which can cascade into different LLM tool calls and final answers. To isolate refactoring risk from feature risk, the flag defaults to OFF. The benchmark should first pass with the flag OFF (verbatim behavior), then be re-run with the flag ON to validate the improvement separately.

**When `smart_truncation_enabled is False`** (default):
The current behavior is preserved verbatim:
```python
if len(txt) > cap:
    txt = txt[:cap] + "\n... [truncated]"
```

**When `smart_truncation_enabled is True`**:

1. If `len(text) <= cap`: return text unchanged.
2. Attempt JSON parse of the full text:
   - **If valid JSON**: Use a streaming/incremental approach:
     - For JSON arrays: include complete elements until adding the next would exceed cap. Close the array with `]`.
     - For JSON objects: include complete key-value pairs until adding the next would exceed cap. Close with `}`.
     - Append `"\n... [truncated]"` after the closing bracket.
   - **If JSON parse fails at boundary**: Fall back to finding the last complete JSON value boundary (`,` or `\n`) before the cap, then append truncation marker.
3. **If not JSON** (plain text): Find the last `\n` before cap position. Truncate there. Append `"\n... [truncated]"`.
4. **Final fallback**: Character cut at cap position + `"\n... [truncated]"` (matches current behavior).

The truncation marker text `"\n... [truncated]"` is identical to the current marker (AC 8.4).

---

## 5. Micro-Compact Design (AC 9.1--9.5)

**Message structure context**: The executor message list follows this pattern:

```
Index 0: system message
Index 1: user (context)
Index 2: assistant ("Ready to execute.")
Index 3: user (task message)
Index 4+: alternating assistant (with tool_calls) and tool result messages
```

**Micro-compact algorithm**:

1. If `config.micro_compact_enabled is False`: return immediately (AC 9.4).
2. **Identify turn boundaries** by scanning backward from the end of `messages`:
   - A "turn" is one assistant message (with `tool_calls`) plus ALL subsequent tool result messages until the next assistant message.
   - Since the LLM often batches multiple tool calls per turn (3-8 is common), each turn may contain 1 assistant + N tool messages where N varies.
   - Count backward through `config.micro_compact_keep_turns` complete turns to find the protected-tail boundary index.
3. Calculate the protected zones:
   - Protected head: indices 0--3 (system, context, ack, task) -- never modified (AC 9.3).
   - Protected tail: all messages from the boundary index found in step 2 to the end of the list.
4. For each message in the modifiable zone (between head and tail):
   - If `role == "tool"`: replace `content` with `"{tool_name}: ok"` (or `"{tool_name}: error"` if content starts with `"Error"`). Preserve `tool_call_id` and `role` (AC 9.2).
   - If `role == "assistant"`: preserve `content` and `tool_calls` structure unchanged.
5. Mutate `messages` in-place (no return value needed).

**Turn counting**: A "turn" is defined as one assistant message (with its `tool_calls`) plus all subsequent tool result messages until the next assistant message. Turns are counted backward from the end of the message list to correctly handle variable tool-call counts per turn. The most recent `config.micro_compact_keep_turns` complete turns are protected.

---

## 6. File-Level Change Summary

| File | Change | Lines (est.) |
|---|---|---|
| `agent.py` | **Deleted** (replaced by `agent/` package) | -1347 |
| `agent/__init__.py` | **New**: re-exports `run_agent` | ~5 |
| `agent/config.py` | **New**: `AgentConfig` frozen dataclass | ~50 |
| `agent/prompts.py` | **New**: constants + builder functions | ~120 |
| `agent/llm.py` | **New**: `call_llm`, `call_llm_no_tools`, `estimate_tokens` | ~80 |
| `agent/dispatch.py` | **New**: `dispatch`, `load_skill`, `compact_tree`, `truncate_output`, `OUTCOME_BY_NAME` | ~300 |
| `agent/bootstrap.py` | **New**: `phase1_bootstrap` | ~130 |
| `agent/planner.py` | **New**: `plan_task` | ~100 |
| `agent/executor.py` | **New**: `_run_executor`, `run_agent` | ~200 |
| `agent/validator.py` | **New**: `extract_decision_outcome`, `validate_completion` | ~120 |
| `agent/context.py` | **New**: `build_executor_context`, `build_task_message`, `micro_compact`, `auto_compact` | ~130 |
| `tasks.py` | **Modified**: +2 properties (`files_deleted`, `pending_writes`) | +10 |
| `main.py` | **Unchanged** (import resolves to `agent/__init__.py`) | 0 |
| `tools.py` | **Unchanged** | 0 |
| `skills.py` | **Unchanged** | 0 |
| `observability.py` | **Unchanged** (KEEP AS-IS) | 0 |
| `skills/execution-discipline/SKILL.md` | **Unchanged** (no duplicates found) | 0 |
| `tests/conftest.py` | **New** | ~40 |
| `tests/test_decision_lock.py` | **New** | ~120 |
| `tests/test_task_manager.py` | **New** | ~130 |
| `tests/test_skill_loader.py` | **New** | ~80 |
| `tests/test_dispatch.py` | **New** | ~150 |
| `tests/test_compact_tree.py` | **New** | ~60 |
| `pyproject.toml` | **Modified**: add pytest dev dependency | +3 |

---

## 7. Observability -- No Changes

**Traces to**: Requirement 4 (descoped per user decision)

The existing `observability.py` is kept exactly as-is. The current LiteLLM callback approach works well. No span-level tracing is added. Requirements AC 4.1 through AC 4.5 are descoped from this refactoring.

---

## 8. Benchmark Regression Safety Strategy

**Traces to**: AC 10.1, AC 10.2, AC 10.3, AC 10.4

1. **Function body preservation**: All logic is moved verbatim, not rewritten. The only structural changes are: converting a closure to explicit parameters, adding public properties to TaskManager, and converting module-level f-string to builder function.
2. **Import path continuity**: `from agent import run_agent` works both before (`agent.py`) and after (`agent/__init__.py`). `main.py` needs zero code changes.
3. **Pipeline order preserved**: Bootstrap -> Planner -> Executor -> Decision-Lock -> Validator -> Apply Writes -> Submit (AC 10.4).
4. **Prompt text identity**: `build_executor_system()` produces byte-identical output to the current `_EXECUTOR_SYSTEM` f-string. Verifiable with a simple string comparison test.
5. **Tool schemas untouched**: `tools.py` has zero changes.
6. **Validation gate**: Run the full PAC1 benchmark (30/30) after refactoring and before merge.

---

## 9. Requirements Traceability Matrix

| Requirement | Design Section | Component(s) |
|---|---|---|
| AC 1.1 | 2.4--2.9 | All `agent/` modules |
| AC 1.2 | 2.11, architecture overview | tools.py, tasks.py, skills.py, observability.py, main.py |
| AC 1.3 | 2.9, 2.10 | agent/__init__.py, agent/executor.py |
| AC 1.4 | 2.13 | skills/ directory |
| AC 2.1 | 1 (dependency graph) | Entire architecture |
| AC 2.2 | 1 (layer model) | Entire architecture |
| AC 2.3 | 2.11 | tools.py, tasks.py, skills.py |
| AC 2.4 | 2.4 | agent/dispatch.py |
| AC 2.5 | 2.2 | agent/prompts.py |
| AC 3.1 | 2.15 | tests/test_decision_lock.py |
| AC 3.2 | 2.15 | tests/test_task_manager.py |
| AC 3.3 | 2.15 | tests/test_skill_loader.py |
| AC 3.4 | 2.15 | tests/test_dispatch.py |
| AC 3.5 | 2.15 | tests/test_compact_tree.py |
| AC 3.6 | 2.15 | All test files |
| AC 3.7 | 2.15 | tests/ directory |
| AC 4.1--4.5 | 7 | Descoped -- observability.py unchanged |
| AC 5.1 | 2.1 | agent/config.py |
| AC 5.2 | 2.1 | All modules consuming config |
| AC 5.3 | 2.9 | agent/executor.py (run_agent) |
| AC 5.4 | 2.1 | agent/config.py (from_env defaults) |
| AC 6.1 | 2.2 | agent/prompts.py (RULE_KEEP_DIFFS_FOCUSED constant) |
| AC 6.2 | 2.2 | agent/prompts.py (RULE_LIST_BEFORE_READ constant) |
| AC 6.3 | 2.2 | agent/prompts.py |
| AC 6.4 | 2.2, 2.4 | agent/prompts.py, agent/dispatch.py |
| AC 6.5 | 2.2 | agent/prompts.py (constants imported by builders) |
| AC 7.1 | 2.14 | Dead code removal from agent.py |
| AC 7.2 | 2.14 | All source files |
| AC 7.3 | 2.14 | agent.py |
| AC 8.1 | 4 | agent/dispatch.py (truncate_output) |
| AC 8.2 | 4 | agent/dispatch.py (truncate_output) |
| AC 8.3 | 4 | agent/dispatch.py (truncate_output) |
| AC 8.4 | 4 | agent/dispatch.py (truncate_output) |
| AC 9.1 | 5 | agent/context.py (micro_compact) |
| AC 9.2 | 5 | agent/context.py (micro_compact) |
| AC 9.3 | 5 | agent/context.py (micro_compact) |
| AC 9.4 | 5 | agent/context.py (micro_compact) |
| AC 9.5 | 5 | agent/context.py (auto_compact) |
| AC 10.1 | 8 | Benchmark regression validation |
| AC 10.2 | 8 | Verbatim code moves |
| AC 10.3 | 2.9, 2.12 | agent/executor.py, main.py |
| AC 10.4 | 2.9, 8 | agent/executor.py pipeline order |
