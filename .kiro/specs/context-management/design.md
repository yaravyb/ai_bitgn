# Design: context-management

> Three-layer context compression pipeline (tool result truncation, micro-compact, auto-compact) adapted from s06_context_compact.py to prevent unbounded message growth and tool result blowup in the executor loop and scout phase.

## Status: Generated

---

## 1. Architecture Overview

The context management pipeline introduces three compression layers into the agent's existing orchestration flow. Each layer operates at a different scope and frequency, forming a defense-in-depth strategy against unbounded context growth.

```
                         ┌─────────────────────────────────────────────┐
                         │               Executor Loop                 │
                         │               (loop.py)                     │
                         │                                             │
                         │  ┌─────────────────────────────────────┐    │
                         │  │   Before each call_llm()            │    │
                         │  │                                     │    │
                         │  │  1. micro_compact(messages, cfg)    │    │
                         │  │  2. estimate_tokens(messages)       │    │
                         │  │  3. if tokens > threshold:          │    │
                         │  │       auto_compact(messages, ...)   │    │
                         │  └─────────────────────────────────────┘    │
                         │                    │                         │
                         │                    v                         │
                         │           call_llm(model, messages, ...)    │
                         │                    │                         │
                         │                    v                         │
                         │         dispatch_parallel(tool_calls)       │
                         │           │                                 │
                         │           v                                 │
                         │    ┌──────────────┐                         │
                         │    │ dispatch_tool │──> truncate_tool_result │
                         │    └──────────────┘                         │
                         │                                             │
                         │         (compact tool sentinel detected?)   │
                         │           │ yes                             │
                         │           v                                 │
                         │         auto_compact(messages, ...)         │
                         └─────────────────────────────────────────────┘

                         ┌─────────────────────────────────────────────┐
                         │           Scout LLM Explorer                │
                         │               (scout.py)                    │
                         │                                             │
                         │  Before each call_llm():                    │
                         │    micro_compact(messages, scout_cfg)       │
                         │                                             │
                         │  (No auto-compact in scout phase)           │
                         └─────────────────────────────────────────────┘

                         ┌─────────────────────────────────────────────┐
                         │          context.py (new leaf module)       │
                         │                                             │
                         │  Pure functions, no agent/ imports:         │
                         │  - estimate_tokens(messages) -> int         │
                         │  - micro_compact(messages, cfg) -> None     │
                         │  - truncate_tool_result(text, cfg) -> str   │
                         │  - ContextConfig (dataclass)                │
                         │  - COMPACT_SENTINEL (constant)              │
                         └─────────────────────────────────────────────┘
```

### Layer Summary

| Layer | Location | Trigger | Mechanism | Req |
|-------|----------|---------|-----------|-----|
| 1. Tool result truncation | `dispatch.py` (calls `context.py`) | Every `dispatch_tool()` call | Truncate oversized results at dispatch boundary | 1 |
| 2. Micro-compact | `loop.py` / `scout.py` (calls `context.py`) | Before every `call_llm()` | Replace old tool result content with placeholders | 2, 5 |
| 3. Auto-compact | `loop.py` (orchestrates using `context.py` + `llm.py`) | Token threshold exceeded | LLM-generated summary replaces full conversation | 3, 6 |

### Module Dependency Update

```
main.py → agent/loop.py (orchestrator)
             ├── context.py           (NEW leaf — no agent/ imports)
             ├── scout.py  → llm.py, dispatch.py, tracker.py, tools.py, prompt.py, context.py
             ├── llm.py               (leaf, unchanged)
             ├── dispatch.py → tracker.py, tools.py, llm.py, context.py
             ├── prompt.py            (leaf, unchanged)
             ├── skills.py            (leaf, unchanged)
             ├── tracker.py           (leaf, unchanged)
             ├── tools.py             (leaf, updated: compact schema added)
             └── observability.py     (leaf, unchanged)
```

`context.py` is a **pure leaf module** with zero imports from other `agent/` modules. It provides pure functions and data classes only. All orchestration (calling the LLM for summarization, saving transcripts, coordinating the compact tool sentinel) remains in `loop.py`.

---

## 2. Component Design

### 2.1 Component: `agent/context.py` (New Module)

**Purpose**: Pure functions for token estimation, micro-compact, and tool result truncation. Configuration dataclass for all context management parameters.

**Traceability**: Req 1, 2, 4, 5, 8, 9

#### 2.1.1 `ContextConfig` Dataclass

```
@dataclass
class ContextConfig:
    truncation_limit: int          # Max characters for tool results (Req 1.2, 8.1)
    micro_compact_keep_batches: int  # Recent batches to preserve (Req 2.2, 8.1)
    micro_compact_min_length: int  # Min content length to clear (Req 2.3, 8.1)
    auto_compact_threshold: int    # Token threshold for auto-compact (Req 3.2, 8.1)
    transcript_dir: str            # Path for transcript files (Req 3.6, 8.1)
```

**Defaults**: `truncation_limit=10000`, `micro_compact_keep_batches=3`, `micro_compact_min_length=100`, `auto_compact_threshold=80000`, `transcript_dir=".transcripts/"`.

**Factory method**: `ContextConfig.from_env()` reads environment variables with fallback to defaults (Req 8.2):
- `CTX_TRUNCATION_LIMIT` -> `truncation_limit`
- `CTX_MICRO_COMPACT_KEEP_BATCHES` -> `micro_compact_keep_batches`
- `CTX_MICRO_COMPACT_MIN_LENGTH` -> `micro_compact_min_length`
- `CTX_AUTO_COMPACT_THRESHOLD` -> `auto_compact_threshold`
- `CTX_TRANSCRIPT_DIR` -> `transcript_dir`

#### 2.1.2 `estimate_tokens(messages: list[dict[str, Any]]) -> int`

**Traceability**: Req 4.1, 4.2, 4.3

Pure function. Computes `len(str(messages)) // 4`. No external dependencies. Used by both the executor loop (auto-compact threshold check) and logging/observability code.

#### 2.1.3 `truncate_tool_result(result_text: str, config: ContextConfig) -> str`

**Traceability**: Req 1.1, 1.2, 1.5

Pure function. Returns the input unchanged if `len(result_text) <= config.truncation_limit`.

When truncation is needed:
1. **JSON-aware path**: Attempt `json.loads(result_text)`. If successful and the result is a dict, find the key whose string value is longest (typically `"content"`). Truncate that value to fit within the character budget, re-serialize to JSON string. Append `"\n...[truncated, {original_length} chars total]"` to the truncated value before re-serialization.
2. **Fallback path**: If JSON parsing fails or the structure is not a dict, truncate `result_text` as a raw string to `config.truncation_limit` characters and append `"\n...[truncated, {original_length} chars total]"`.

The function preserves the JSON envelope (keys, structure) when possible, truncating only the largest string value within it.

**Parameters**:
- `result_text: str` -- The raw tool result string.
- `config: ContextConfig` -- Configuration with `truncation_limit`.

**Returns**: `str` -- Truncated (or original) result string.

#### 2.1.4 `micro_compact(messages: list[dict[str, Any]], config: ContextConfig) -> None`

**Traceability**: Req 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 5.1, 9.1, 9.3

Pure function. Mutates the `messages` list in-place (no return value needed; returns `None`).

**Batch detection algorithm**:
A "batch" of tool results corresponds to one assistant turn that included `tool_calls`. The boundary is detected by scanning messages in order: an assistant message with a `"tool_calls"` key starts a new batch; all subsequent `role == "tool"` messages before the next assistant message belong to that batch.

**Steps**:
1. Scan `messages` from index 0, identifying batch boundaries. Each batch is a list of indices of `role == "tool"` messages that belong to the same assistant turn.
2. If total number of batches <= `config.micro_compact_keep_batches`, return immediately (nothing to clear).
3. For batches older than the most recent `config.micro_compact_keep_batches` batches: for each tool message index in those batches, if `msg["content"]` is a string and `len(msg["content"]) > config.micro_compact_min_length`, replace `msg["content"]` with `"[Previous tool result cleared]"`.
4. Preserve `tool_call_id` on every message (never remove the key, never remove the message from the list).
5. Never modify system messages, user messages, or assistant messages.

**Returns**: `None` (mutates in-place). This satisfies Req 2.7 (pure function: takes messages list and configuration, mutates the list in-place, no I/O or LLM calls).

#### 2.1.5 `COMPACT_SENTINEL: str`

**Traceability**: Req 6.2

A module-level constant string: `"__COMPACT_SENTINEL__"`. When `dispatch_tool()` encounters the `"compact"` tool name, it returns this sentinel. `loop.py` detects the sentinel in the results and triggers the auto-compact operation. This follows the same pattern as `report_completion` detection in the existing codebase.

---

### 2.2 Component: `agent/dispatch.py` (Modified)

**Purpose**: Integrate tool result truncation into the dispatch layer. Add compact tool sentinel handling.

**Traceability**: Req 1.1, 1.3, 1.4, 1.5, 1.6, 6.2

#### 2.2.1 Changes to `dispatch_tool()`

After the existing handler returns a result string, apply truncation:

```
result = handler(vm, args, tracker, protected_files, skill_loader)
```

Becomes:

```
result = handler(vm, args, tracker, protected_files, skill_loader)
if tool_name != "report_completion":
    result = truncate_tool_result(result, context_config)
    # Log truncation at DEBUG level if truncated (Req 1.4)
```

The `report_completion` tool is exempt from truncation (Req 1.3).

**New parameter**: `dispatch_tool()` receives a `context_config: ContextConfig | None = None` parameter. When `None`, truncation is skipped (Req 9.2 -- backward compatibility when context management is disabled).

**Signature change**:

```
def dispatch_tool(
    vm: MiniRuntimeClientSync,
    tool_name: str,
    args: dict[str, Any],
    tracker: GroundingTracker,
    protected_files: set[str],
    skill_loader: Any | None = None,
    context_config: ContextConfig | None = None,  # NEW
) -> str:
```

`dispatch_parallel()` similarly receives and passes through `context_config`:

```
def dispatch_parallel(
    vm: MiniRuntimeClientSync,
    tool_calls: list[ToolCall],
    tracker: GroundingTracker,
    protected_files: set[str],
    skill_loader: Any | None = None,
    max_workers: int = 4,
    context_config: ContextConfig | None = None,  # NEW
) -> list[tuple[str, str]]:
```

#### 2.2.2 Compact Tool Handler

A new entry in `DISPATCH_MAP`:

```
"compact": _handle_compact
```

Where `_handle_compact` returns `COMPACT_SENTINEL` from `context.py`. This is a pure sentinel -- the actual compaction logic lives in `loop.py`.

```
def _handle_compact(vm, args, tracker, protected_files, skill_loader) -> str:
    return COMPACT_SENTINEL
```

The handler does not interact with the VM, tracker, or any external systems. It returns the sentinel string that `loop.py` will detect.

---

### 2.3 Component: `agent/tools.py` (Modified)

**Purpose**: Add the `compact` tool schema to `TOOL_SCHEMAS`.

**Traceability**: Req 6.1, 6.4

#### 2.3.1 New Schema Entry

Add to `TOOL_SCHEMAS`:

```
{
    "type": "function",
    "function": {
        "name": "compact",
        "description": "Trigger immediate context summarization. Use when the conversation feels too long or you are losing track of earlier work. This compresses the full conversation into a summary.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}
```

The `compact` tool is included in `TOOL_SCHEMAS` (available to the executor) but excluded from `SCOUT_TOOL_SCHEMAS` because `_SCOUT_TOOL_NAMES` only includes `{"tree", "list_dir", "read_file", "search"}` (Req 6.4). No changes to `_SCOUT_TOOL_NAMES` or `SCOUT_TOOL_SCHEMAS` are needed.

---

### 2.4 Component: `agent/loop.py` (Modified)

**Purpose**: Orchestrate all three compression layers in the executor loop. Handle auto-compact and compact tool sentinel.

**Traceability**: Req 2.1, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 6.2, 6.3, 7.1, 7.2, 7.3, 7.4, 7.5, 9.3, 9.4, 9.5

#### 2.4.1 Initialization in `run_agent()`

At the top of `run_agent()`, after existing initialization:

```python
from agent.context import ContextConfig, estimate_tokens, micro_compact, COMPACT_SENTINEL

context_config = ContextConfig.from_env()
```

Pass `context_config` to all `dispatch_parallel()` and `dispatch_tool()` calls.

#### 2.4.2 Pre-LLM Compression (Before Each `call_llm()`)

Insert before each `call_llm()` invocation in the executor loop:

```
# Layer 2: Micro-compact old tool results
cleared_count, chars_saved = _apply_micro_compact(messages, context_config)
if cleared_count > 0:
    log.debug("Micro-compact: cleared %d messages, ~%d chars saved", cleared_count, chars_saved)

# Layer 3: Auto-compact if threshold exceeded
tokens_est = estimate_tokens(messages)
if tokens_est > context_config.auto_compact_threshold:
    messages[:] = _apply_auto_compact(messages, context_config, executor_model, trace_metadata)
```

The helper `_apply_micro_compact` wraps `micro_compact()` and returns the count of cleared messages and characters saved (for logging, Req 7.1).

The helper `_apply_auto_compact` encapsulates:
1. Save transcript to disk (Req 3.6).
2. Call LLM with summarization prompt (Req 3.3).
3. Replace messages with system + summary + acknowledgment (Req 3.4, 3.5).
4. Log at INFO level (Req 3.7, 7.2).

#### 2.4.3 `_apply_micro_compact()` Helper

**Signature**:
```
def _apply_micro_compact(
    messages: list[dict[str, Any]],
    config: ContextConfig,
) -> tuple[int, int]:
```

Captures message content lengths before calling `micro_compact()`, then compares after to compute `cleared_count` and `chars_saved`. Returns `(cleared_count, chars_saved)`.

#### 2.4.4 `_apply_auto_compact()` Helper

**Signature**:
```
def _apply_auto_compact(
    messages: list[dict[str, Any]],
    config: ContextConfig,
    model: str,
    trace_metadata: dict[str, Any],
) -> list[dict[str, Any]]:
```

**Steps**:
1. Save full transcript to `{config.transcript_dir}/transcript_{timestamp}.jsonl` with metadata header (Req 3.6, 7.5):
   ```
   {"_meta": {"timestamp": "...", "trace_id": "...", "estimated_tokens": N, "reason": "threshold_exceeded|compact_tool"}}
   ```
   Followed by one JSON line per message.
2. Build summarization prompt (Req 3.3):
   ```
   Summarize this conversation for continuity. Preserve:
   1) What has been accomplished so far
   2) Current state of the task
   3) Key decisions and their rationale
   4) Files read and modified
   5) Pending actions or next steps
   6) The original task instruction and system prompt rules

   Be concise but preserve critical details for continued execution.
   ```
   Include the conversation text (truncated to 80,000 chars to stay within LLM limits).
3. Call `call_llm()` for summarization with `max_tokens=2000`, passing `trace_metadata` for Langfuse grouping (Req 7.4). No tools parameter (text-only completion).
4. Build replacement messages (Req 3.4, 3.5):
   ```python
   [
       messages[0],  # Preserve original system message
       {"role": "user", "content": f"[Conversation compressed. Transcript: {transcript_path}]\n\n{summary}"},
       {"role": "assistant", "content": "Understood. I have the context from the summary. Continuing with the task."},
   ]
   ```
5. Log at INFO level: estimated tokens before, message count before, summary length (Req 3.7).

**Returns**: The new messages list.

#### 2.4.5 Compact Tool Sentinel Detection

After dispatching tool calls and appending results, check for the compact sentinel (same structural location as the existing `report_completion` check):

```python
compact_requested = False
for tool_call_id, result_text in results:
    if result_text == COMPACT_SENTINEL:
        compact_requested = True
    messages.append({
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": result_text if result_text != COMPACT_SENTINEL else "Compacting context...",
    })

if compact_requested:
    log.info("Compact tool invoked by LLM")
    messages[:] = _apply_auto_compact(messages, context_config, executor_model, trace_metadata)
```

The sentinel is replaced with a human-readable placeholder before being appended to messages, then `_apply_auto_compact()` replaces the entire conversation. The tool result message with the placeholder is included in the transcript saved during auto-compact (Req 6.3).

---

### 2.5 Component: `agent/scout.py` (Modified)

**Purpose**: Apply micro-compact to the scout LLM explorer loop.

**Traceability**: Req 5.1, 5.2, 5.3, 5.4

#### 2.5.1 Changes to `_run_llm_explorer()`

Add `context_config: ContextConfig` parameter to `_run_llm_explorer()`. Before each `call_llm()` in the loop, invoke:

```python
micro_compact(messages, scout_context_config)
```

Where `scout_context_config` is a separate `ContextConfig` instance with independently tunable values for the scout phase (Req 5.2). The scout phase does NOT run auto-compact (Req 5.3).

The `ContextConfig` for scout may use different defaults:
- `micro_compact_keep_batches`: 2 (scout conversations are shorter)
- `micro_compact_min_length`: 100 (same as executor)

These are configured via dedicated environment variables (or shared with executor defaults when unset):
- `CTX_SCOUT_MICRO_COMPACT_KEEP_BATCHES`
- `CTX_SCOUT_MICRO_COMPACT_MIN_LENGTH`

#### 2.5.2 Changes to `run_scout()`

Accept `context_config: ContextConfig | None = None` and pass it through to `_run_llm_explorer()`. Also pass to `dispatch_tool` / `dispatch_parallel` calls so truncation (Req 5.4) applies to scout tool calls.

#### 2.5.3 Changes to `ScoutConfig`

No changes to `ScoutConfig`. The context config is passed separately to keep scout configuration (model, task, steps) orthogonal from context management configuration.

---

### 2.6 Component: `.env.example` (Modified)

**Purpose**: Document all context management environment variables.

**Traceability**: Req 8.3

Add a new section:

```
# =============================================================================
# Context Management (optional -- sensible defaults are built-in)
# =============================================================================
# CTX_TRUNCATION_LIMIT=10000           # Max chars per tool result before truncation
# CTX_MICRO_COMPACT_KEEP_BATCHES=3     # Number of recent tool-result batches to preserve
# CTX_MICRO_COMPACT_MIN_LENGTH=100     # Min content length (chars) to trigger clearing
# CTX_AUTO_COMPACT_THRESHOLD=80000     # Estimated tokens to trigger auto-compact
# CTX_TRANSCRIPT_DIR=.transcripts/     # Directory for pre-compaction transcript files

# Scout-specific overrides (optional -- falls back to values above):
# CTX_SCOUT_MICRO_COMPACT_KEEP_BATCHES=2
# CTX_SCOUT_MICRO_COMPACT_MIN_LENGTH=100
```

---

## 3. Interface Contracts

### 3.1 `context.py` Public Interface

```
@dataclass
class ContextConfig:
    truncation_limit: int = 10_000
    micro_compact_keep_batches: int = 3
    micro_compact_min_length: int = 100
    auto_compact_threshold: int = 80_000
    transcript_dir: str = ".transcripts/"

    @classmethod
    def from_env(cls) -> ContextConfig: ...

COMPACT_SENTINEL: str = "__COMPACT_SENTINEL__"

def estimate_tokens(messages: list[dict[str, Any]]) -> int: ...

def truncate_tool_result(result_text: str, config: ContextConfig) -> str: ...

def micro_compact(messages: list[dict[str, Any]], config: ContextConfig) -> None: ...
```

### 3.2 Modified `dispatch_tool()` Signature

```
def dispatch_tool(
    vm: MiniRuntimeClientSync,
    tool_name: str,
    args: dict[str, Any],
    tracker: GroundingTracker,
    protected_files: set[str],
    skill_loader: Any | None = None,
    context_config: ContextConfig | None = None,
) -> str: ...
```

### 3.3 Modified `dispatch_parallel()` Signature

```
def dispatch_parallel(
    vm: MiniRuntimeClientSync,
    tool_calls: list[ToolCall],
    tracker: GroundingTracker,
    protected_files: set[str],
    skill_loader: Any | None = None,
    max_workers: int = 4,
    context_config: ContextConfig | None = None,
) -> list[tuple[str, str]]: ...
```

### 3.4 Modified `run_scout()` Signature

```
def run_scout(
    vm: Any,
    tracker: GroundingTracker,
    config: ScoutConfig,
    context_config: ContextConfig | None = None,
) -> ScoutSummary: ...
```

### 3.5 Auto-Compact Summarization Prompt Contract

The summarization prompt sent to the LLM during auto-compact must instruct it to preserve:
1. What has been accomplished so far.
2. Current state of the task.
3. Key decisions and their rationale.
4. Files read and modified.
5. Pending actions or next steps.
6. Awareness of the original task instruction and system prompt rules (Req 9.4).

The conversation text passed to the summarization call is truncated to 80,000 characters to stay within LLM input limits.

### 3.6 Transcript File Format

Each transcript file is a JSONL file at `{config.transcript_dir}/transcript_{unix_timestamp}.jsonl`:

- **Line 1**: Metadata header JSON object:
  ```json
  {"_meta": {"timestamp": "2026-03-20T22:30:00Z", "trace_id": "uuid-or-empty", "estimated_tokens": 85000, "reason": "threshold_exceeded"}}
  ```
- **Lines 2+**: One JSON object per message from the `messages` list (as-is, serialized with `default=str`).

---

## 4. Data Flow

### 4.1 Tool Result Truncation Flow (Every Tool Dispatch)

```
dispatch_tool() called
    |
    v
handler(vm, args, ...) returns result_text
    |
    v
tool_name == "report_completion"?
    |── yes ──> return result_text unchanged
    |── no
    v
context_config is None?
    |── yes ──> return result_text unchanged (backward compat)
    |── no
    v
truncate_tool_result(result_text, config)
    |
    ├── len(result_text) <= limit? ──> return unchanged
    |
    ├── try json.loads(result_text) -> dict?
    |   |── yes ──> find largest string value, truncate it, re-serialize
    |   |── no  ──> truncate raw string
    |
    v
return truncated_text (with indicator appended)
```

### 4.2 Pre-LLM Compression Flow (Before Each `call_llm()` in Executor)

```
Executor loop iteration starts
    |
    v
micro_compact(messages, config)        # Layer 2: prune old tool results
    |
    v
tokens = estimate_tokens(messages)
    |
    v
tokens > config.auto_compact_threshold?
    |── no  ──> proceed to call_llm()
    |── yes
    v
_apply_auto_compact(messages, config, model, metadata)
    |
    ├── save transcript to disk
    ├── call LLM for summarization
    ├── replace messages with [system, summary, ack]
    └── log at INFO level
    |
    v
call_llm(model, messages, tools, metadata)
```

### 4.3 Compact Tool Flow (LLM-Triggered)

```
LLM response includes tool_call: compact
    |
    v
dispatch_parallel() -> dispatch_tool("compact", ...)
    |
    v
_handle_compact() returns COMPACT_SENTINEL
    |
    v
loop.py detects sentinel in results
    |
    v
Append placeholder to messages: "Compacting context..."
    |
    v
_apply_auto_compact(messages, config, model, metadata)
    |
    v
Continue executor loop with compressed messages
```

---

## 5. Key Design Decisions

### 5.1 Pure Leaf Module (`context.py`)

**Decision**: All context management pure functions live in a single new leaf module `context.py` with zero imports from other `agent/` modules.

**Rationale**: Follows the existing architecture pattern where leaf modules (`tracker.py`, `tools.py`, `llm.py`, `prompt.py`, `skills.py`) have no internal dependencies. Ensures testability (functions can be tested with plain dicts, no mocking needed) and prevents circular imports. Orchestration logic (LLM calls for summarization, transcript I/O, sentinel detection) stays in `loop.py` where it belongs.

**Traceability**: Architectural constraint from agent-analysis.md Section "Architecture Overview".

### 5.2 Batch-Based Micro-Compact

**Decision**: Micro-compact identifies "batches" of tool results by detecting assistant messages with `tool_calls` keys, rather than counting individual tool result messages.

**Rationale**: The OpenAI-compatible API format allows an assistant to make multiple parallel tool calls in one turn. All tool results from one turn form a logical batch. Preserving the most recent N batches (not N individual tool messages) ensures the LLM retains the complete context of its most recent turns, including all parallel tool results from each turn.

**Traceability**: Req 2.2, 2.6 -- "3 most recent tool-use turns".

### 5.3 JSON-Aware Truncation

**Decision**: Tool result truncation first attempts JSON parsing and truncates the largest string value within the JSON structure, preserving the JSON envelope. Falls back to raw string truncation.

**Rationale**: Tool results from the VM (via `dispatch_tool`) are JSON-serialized protobuf responses (e.g., `{"content": "...large file content..."}` for `read_file`). Truncating the raw JSON string would produce invalid JSON, potentially confusing the LLM. By truncating only the content value, the LLM still receives a valid JSON response with metadata intact.

**Traceability**: Req 1.5.

### 5.4 Compact Tool Sentinel Pattern

**Decision**: The `compact` tool handler returns a sentinel string. `loop.py` detects the sentinel after dispatch and triggers auto-compact.

**Rationale**: Follows the existing architectural pattern used by `report_completion` -- the handler performs the "report" side effect, then the loop detects and acts on it. The compact tool cannot perform compaction itself because it needs access to the full messages list and LLM, which are orchestrator-level concerns. The sentinel pattern keeps the handler simple and the dispatch layer free of orchestration logic.

**Traceability**: Req 6.2.

### 5.5 Backward-Compatible `None` Default

**Decision**: `context_config` parameters default to `None` on `dispatch_tool()`, `dispatch_parallel()`, and `run_scout()`. When `None`, no truncation or micro-compact is applied.

**Rationale**: Ensures the agent behaves identically to the current implementation when context management is not configured (Req 9.2). Existing test suites continue to pass without modification. New functionality is opt-in via `ContextConfig.from_env()` in `run_agent()`.

**Traceability**: Req 9.2.

### 5.6 System Message Preservation

**Decision**: Auto-compact preserves `messages[0]` (the system message) unchanged and places the summary as a user message.

**Rationale**: The system message contains the full system prompt (role, security rules, scout context, completion format). Losing it would degrade behavior. Placing the summary as a user message followed by an assistant acknowledgment maintains a valid conversation structure for the LLM API and ensures the LLM is aware the conversation was compressed.

**Traceability**: Req 3.4, 3.5, 9.4.

---

## 6. Observability Integration

### 6.1 Logging

| Event | Level | Fields | Req |
|-------|-------|--------|-----|
| Tool result truncated | DEBUG | tool_name, original_size, truncated_size | 1.4 |
| Micro-compact executed | DEBUG | messages_cleared, chars_saved | 7.1 |
| Auto-compact triggered | INFO | reason, tokens_before, tokens_after, messages_before, summary_length | 3.7, 7.2 |
| Compact tool invoked | INFO | reason, tokens_before, tokens_after, messages_before, summary_length | 7.3 |

All logging uses the standard `logging` module via `log = logging.getLogger(__name__)`, consistent with the existing codebase pattern.

### 6.2 Langfuse Tracing

Auto-compact LLM calls use the same `trace_metadata` dict as the executor loop, ensuring they appear in the same Langfuse trace (Req 7.4). The summarization call is a regular `call_llm()` invocation and is automatically captured by the existing Langfuse callbacks registered in `observability.py`.

### 6.3 Transcript Files

Transcript files include a metadata header for debugging (Req 7.5): timestamp, trace_id (from `trace_metadata`), estimated token count, and compaction reason (`"threshold_exceeded"` or `"compact_tool"`).

---

## 7. Error Handling

### 7.1 Truncation Errors

If `json.loads()` fails during JSON-aware truncation, the function falls back to raw string truncation silently. No exception is raised.

### 7.2 Auto-Compact LLM Failure

If the summarization LLM call fails (after retries in `call_llm()`), the exception propagates to the executor loop. The agent may fail the current task. This is acceptable because:
- The failure is transient (LLM service issue) and the existing retry logic in `call_llm()` already handles common failures.
- Silently continuing without compaction would likely hit token limits on the next `call_llm()` anyway.

### 7.3 Transcript Write Failure

If transcript directory creation or file writing fails, the error is logged at WARNING level and auto-compact proceeds without saving the transcript. The summarization and message replacement still occur. Transcript saving is a debugging aid, not a critical path operation.

### 7.4 Micro-Compact Safety

`micro_compact()` never raises exceptions. It operates on the messages list in-place and tolerates:
- Empty messages lists (returns immediately).
- Messages without `"content"` keys (skips them).
- Non-string content values (skips them).
- Messages without `"tool_calls"` keys on assistant messages (not counted as batch boundaries).

---

## 8. Testing Strategy

### 8.1 Unit Tests: `tests/test_context.py` (New)

Test `context.py` pure functions with plain dict messages, no mocking required.

| Test | Covers |
|------|--------|
| `test_estimate_tokens_empty` | Req 4.1, 4.2 |
| `test_estimate_tokens_known_input` | Req 4.1 |
| `test_truncate_tool_result_under_limit` | Req 1.1 |
| `test_truncate_tool_result_over_limit_json` | Req 1.1, 1.5 |
| `test_truncate_tool_result_over_limit_raw` | Req 1.1 |
| `test_truncate_tool_result_json_fallback` | Req 1.5 |
| `test_micro_compact_no_batches` | Req 2.6 |
| `test_micro_compact_within_keep_window` | Req 2.6 |
| `test_micro_compact_clears_old_batches` | Req 2.2, 2.3 |
| `test_micro_compact_preserves_tool_call_id` | Req 2.4, 9.1 |
| `test_micro_compact_preserves_non_tool_messages` | Req 2.5 |
| `test_micro_compact_preserves_short_content` | Req 2.3 |
| `test_micro_compact_batch_detection` | Req 2.2 |
| `test_context_config_defaults` | Req 8.1 |
| `test_context_config_from_env` | Req 8.2 |

### 8.2 Unit Tests: `tests/test_dispatch.py` (Extended)

| Test | Covers |
|------|--------|
| `test_dispatch_tool_truncation` | Req 1.1, 1.6 |
| `test_dispatch_tool_no_truncation_when_config_none` | Req 9.2 |
| `test_dispatch_report_completion_exempt` | Req 1.3 |
| `test_dispatch_compact_returns_sentinel` | Req 6.2 |

### 8.3 Unit Tests: `tests/test_loop.py` (Extended)

| Test | Covers |
|------|--------|
| `test_micro_compact_called_before_llm` | Req 2.1 |
| `test_auto_compact_triggered_on_threshold` | Req 3.1, 3.2 |
| `test_auto_compact_saves_transcript` | Req 3.6 |
| `test_auto_compact_preserves_system_message` | Req 3.5, 9.4 |
| `test_auto_compact_replaces_messages` | Req 3.4 |
| `test_compact_sentinel_triggers_compaction` | Req 6.2 |
| `test_report_completion_after_compaction` | Req 9.5 |

### 8.4 Unit Tests: `tests/test_scout.py` (Extended)

| Test | Covers |
|------|--------|
| `test_scout_micro_compact_applied` | Req 5.1 |
| `test_scout_no_auto_compact` | Req 5.3 |
| `test_scout_truncation_applied` | Req 5.4 |

---

## 9. Requirements Traceability Matrix

| Req | Component(s) | Section |
|-----|-------------|---------|
| 1.1 | context.py `truncate_tool_result()` | 2.1.3, 4.1 |
| 1.2 | context.py `ContextConfig.truncation_limit` | 2.1.1 |
| 1.3 | dispatch.py (exempt `report_completion`) | 2.2.1 |
| 1.4 | dispatch.py (DEBUG log on truncation) | 2.2.1, 6.1 |
| 1.5 | context.py `truncate_tool_result()` JSON-aware path | 2.1.3, 5.3 |
| 1.6 | dispatch.py `dispatch_parallel()` passthrough | 2.2.1 |
| 2.1 | loop.py pre-LLM compression | 2.4.2 |
| 2.2 | context.py `micro_compact()` batch detection | 2.1.4, 5.2 |
| 2.3 | context.py `micro_compact()` min length check | 2.1.4 |
| 2.4 | context.py `micro_compact()` preserves `tool_call_id` | 2.1.4 |
| 2.5 | context.py `micro_compact()` only modifies tool messages | 2.1.4 |
| 2.6 | context.py `micro_compact()` preserves recent batches | 2.1.4 |
| 2.7 | context.py `micro_compact()` pure function | 2.1.4 |
| 3.1 | loop.py token estimation before LLM call | 2.4.2 |
| 3.2 | loop.py threshold check | 2.4.2 |
| 3.3 | loop.py `_apply_auto_compact()` summarization prompt | 2.4.4, 3.5 |
| 3.4 | loop.py `_apply_auto_compact()` message replacement | 2.4.4 |
| 3.5 | loop.py `_apply_auto_compact()` system message preservation | 2.4.4, 5.6 |
| 3.6 | loop.py `_apply_auto_compact()` transcript saving | 2.4.4, 3.6 |
| 3.7 | loop.py `_apply_auto_compact()` INFO logging | 2.4.4, 6.1 |
| 3.8 | context.py `ContextConfig.auto_compact_threshold` env var | 2.1.1 |
| 4.1 | context.py `estimate_tokens()` | 2.1.2 |
| 4.2 | context.py `estimate_tokens()` pure, no deps | 2.1.2 |
| 4.3 | context.py `estimate_tokens()` usable independently | 2.1.2 |
| 5.1 | scout.py `_run_llm_explorer()` micro-compact call | 2.5.1 |
| 5.2 | scout.py independent config | 2.5.1 |
| 5.3 | scout.py no auto-compact | 2.5.1 |
| 5.4 | scout.py truncation via dispatch | 2.5.2 |
| 6.1 | tools.py compact schema | 2.3.1 |
| 6.2 | dispatch.py sentinel, loop.py detection | 2.2.2, 2.4.5 |
| 6.3 | loop.py compact tool confirmation + auto_compact | 2.4.5 |
| 6.4 | tools.py excluded from `SCOUT_TOOL_SCHEMAS` | 2.3.1 |
| 6.5 | Design: compact is secondary to auto layers | 5.4 |
| 7.1 | loop.py micro-compact DEBUG log | 2.4.2, 6.1 |
| 7.2 | loop.py auto-compact INFO log | 2.4.4, 6.1 |
| 7.3 | loop.py compact tool INFO log | 2.4.5, 6.1 |
| 7.4 | loop.py `_apply_auto_compact()` Langfuse metadata | 2.4.4, 6.2 |
| 7.5 | loop.py transcript metadata header | 2.4.4, 3.6 |
| 8.1 | context.py `ContextConfig` defaults | 2.1.1 |
| 8.2 | context.py `ContextConfig.from_env()` | 2.1.1 |
| 8.3 | `.env.example` documentation | 2.6 |
| 9.1 | context.py `micro_compact()` preserves `tool_call_id` | 2.1.4 |
| 9.2 | dispatch.py `context_config=None` passthrough | 2.2.1, 5.5 |
| 9.3 | context.py `micro_compact()` only modifies historical messages | 2.1.4, 2.4.2 |
| 9.4 | loop.py summarization prompt preserves task awareness | 2.4.4, 3.5 |
| 9.5 | loop.py `report_completion` works after compaction | 2.4.4 |

---

## 10. Files Changed

| File | Action | Description |
|------|--------|-------------|
| `sandbox/py/agent/context.py` | **Create** | New leaf module: `ContextConfig`, `estimate_tokens()`, `truncate_tool_result()`, `micro_compact()`, `COMPACT_SENTINEL` |
| `sandbox/py/agent/dispatch.py` | **Modify** | Add `context_config` param to `dispatch_tool()` and `dispatch_parallel()`; add `_handle_compact` handler; apply truncation after handler call |
| `sandbox/py/agent/tools.py` | **Modify** | Add `compact` tool schema to `TOOL_SCHEMAS` |
| `sandbox/py/agent/loop.py` | **Modify** | Add pre-LLM compression (micro-compact + auto-compact); add `_apply_micro_compact()` and `_apply_auto_compact()` helpers; add compact sentinel detection; pass `context_config` to dispatch calls |
| `sandbox/py/agent/scout.py` | **Modify** | Add `context_config` param to `run_scout()` and `_run_llm_explorer()`; call `micro_compact()` before each `call_llm()`; pass `context_config` to dispatch calls |
| `sandbox/py/.env.example` | **Modify** | Add context management environment variable documentation |
| `sandbox/py/tests/test_context.py` | **Create** | Unit tests for all `context.py` functions |
| `sandbox/py/tests/test_dispatch.py` | **Modify** | Add tests for truncation integration and compact sentinel |
| `sandbox/py/tests/test_loop.py` | **Modify** | Add tests for pre-LLM compression, auto-compact, and sentinel detection |
| `sandbox/py/tests/test_scout.py` | **Modify** | Add tests for scout micro-compact and truncation |
