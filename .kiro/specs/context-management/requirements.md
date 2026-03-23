# Requirements: context-management

> Three-layer context compression pipeline adapted from s06_context_compact.py to prevent unbounded message growth and tool result blowup in the executor loop. Addresses weaknesses #2 (No Memory/Context Management) and #7 (No Tool Result Validation) from agent-analysis.md.

## Status: Generated

## Context

The agent's executor loop (`sandbox/py/agent/loop.py`) runs up to 30 steps, appending every assistant message and tool result to the `messages` list without any pruning or summarization. Large tool results (e.g., `read_file` returning full file contents) are stored as raw JSON strings and remain in context indefinitely. The scout phase (`agent/scout.py`) has a similar pattern over 20 steps.

This leads to two documented weaknesses:

- **Weakness #2 (No Memory / Context Management)**: The message list grows unboundedly. May hit token limits; performance and reasoning quality degrade with excessive context.
- **Weakness #7 (No Tool Result Validation)**: `dispatch_tool()` returns raw serialized results without size limits. A large file in the sandbox could blow up context or increase costs.

The solution is a three-layer compression pipeline adapted from the reference example `s06_context_compact.py`:

| Layer | Trigger | Mechanism |
|-------|---------|-----------|
| 1. Tool result truncation | Every tool dispatch | Truncate oversized tool results at the dispatch layer |
| 2. Micro-compact | Every turn (before LLM call) | Replace old tool result messages with placeholders |
| 3. Auto-compact | Token threshold exceeded | LLM-generated summary replaces full conversation |

Key constraints:
- Must preserve `tool_call_id` linkage required by the OpenAI-compatible API format.
- Must not break existing executor loop behavior or scout phase behavior.
- Langfuse observability should trace compaction events.
- The optional LLM-triggered `compact` tool is secondary to the automatic layers.

---

## Requirement 1: Tool Result Truncation at Dispatch

Tool results returned by `dispatch_tool()` must be truncated when they exceed a configurable size limit, preventing oversized payloads from entering the message history.

### Acceptance Criteria

1. **When** a tool result returned by `dispatch_tool()` exceeds a configurable character limit, **the dispatch layer shall** truncate the result to the limit and append a truncation indicator (e.g., `\n...[truncated, {original_length} chars total]`).
2. **The truncation character limit shall** be configurable with a sensible default (e.g., 10,000 characters) and overridable without code changes.
3. **The truncation shall** apply to all tool handlers uniformly -- no tool is exempt except `report_completion`.
4. **When** a tool result is truncated, **the dispatch layer shall** log the tool name, original size, and truncated size at DEBUG level.
5. **The truncation shall** preserve valid JSON structure where possible by truncating the content value within the JSON, not the JSON envelope itself.
6. **The `dispatch_parallel()` function shall** inherit truncation behavior automatically since it delegates to `dispatch_tool()`.

---

## Requirement 2: Micro-Compact (Silent Per-Turn Pruning)

The executor loop must silently prune old tool result messages before each LLM call to prevent stale, large payloads from consuming context window budget.

### Acceptance Criteria

1. **The agent shall** run a micro-compact pass on the messages list before every `call_llm()` invocation in the executor loop.
2. **The micro-compact pass shall** identify tool result messages (role == "tool") that are older than the most recent N tool result messages, where N is configurable (default: 3 batches of tool results, corresponding to the 3 most recent tool-use turns).
3. **When** an eligible tool result message has content exceeding a configurable character threshold (default: 100 characters), **the micro-compact pass shall** replace its content with a placeholder string (e.g., `"[Previous tool result cleared]"`).
4. **The micro-compact pass shall** preserve the `tool_call_id` field on every replaced message to maintain API-required linkage between assistant tool_calls and tool result messages.
5. **The micro-compact pass shall** never modify system messages, user messages, or assistant messages -- only tool result messages.
6. **The micro-compact pass shall** never modify the most recent N batches of tool results, ensuring the LLM always has access to the latest tool outputs.
7. **The micro-compact function shall** be a pure function that takes the messages list and configuration, returning or mutating the list in-place -- it must not call the LLM or perform I/O.

---

## Requirement 3: Auto-Compact (Threshold-Triggered Summarization)

When the estimated token count of the conversation exceeds a configurable threshold, the agent must trigger an LLM-powered summarization that compresses the full conversation into a compact summary, freeing context budget for further execution.

### Acceptance Criteria

1. **Before each `call_llm()` invocation in the executor loop, the agent shall** estimate the token count of the current messages list using a rough heuristic (e.g., `len(str(messages)) // 4`).
2. **When** the estimated token count exceeds a configurable threshold (default value suitable for production, e.g., 80,000 tokens), **the agent shall** trigger an auto-compact operation before making the next LLM call.
3. **The auto-compact operation shall** call the LLM with a summarization prompt that instructs it to compress the conversation while preserving: (a) what has been accomplished so far, (b) the current state of the task, (c) key decisions and their rationale, (d) files read and modified, (e) any pending actions or next steps.
4. **After receiving the summary, the auto-compact operation shall** replace all messages (except the system message) with two new messages: a user message containing the compressed summary, and an assistant acknowledgment message.
5. **The auto-compact operation shall** preserve the original system message unchanged.
6. **The auto-compact operation shall** save the full pre-compaction transcript to a configurable directory (e.g., `.transcripts/`) as a JSONL file before replacing messages, for debugging and audit purposes.
7. **The auto-compact operation shall** log the event at INFO level, including: estimated token count before compaction, number of messages before compaction, and the summary length.
8. **The auto-compact threshold shall** be configurable without code changes.

---

## Requirement 4: Token Estimation

The agent must provide a token estimation utility that supports both the auto-compact threshold check and observability reporting.

### Acceptance Criteria

1. **The agent shall** provide a function that estimates the token count for a given messages list using a character-based heuristic (e.g., total character count divided by 4).
2. **The token estimation function shall** be a pure function with no external dependencies -- it must not call any tokenizer library or external service.
3. **The token estimation function shall** be usable independently by both the executor loop (for auto-compact threshold) and by any observability or logging code.

---

## Requirement 5: Scout Phase Context Management

The scout phase (`agent/scout.py`) must benefit from the same micro-compact mechanism as the executor loop to prevent context exhaustion during the LLM explorer phase.

### Acceptance Criteria

1. **The scout LLM explorer loop shall** run the micro-compact pass before each `call_llm()` invocation, using the same function as the executor loop.
2. **The micro-compact configuration for the scout phase shall** be independently tunable (separate N and character threshold values), allowing the scout to use different settings than the executor.
3. **The auto-compact operation shall not** be applied in the scout phase -- the scout's 20-step limit and shorter conversations make full summarization unnecessary and its cost disproportionate.
4. **The tool result truncation (Requirement 1) shall** apply equally to scout tool calls since the scout reuses `dispatch_tool()` and `dispatch_parallel()`.

---

## Requirement 6: Compact Tool (LLM-Triggered Manual Compaction)

The agent may optionally expose a `compact` tool that allows the LLM to trigger an immediate summarization when it judges the context is becoming unwieldy, independent of the automatic threshold.

### Acceptance Criteria

1. **The agent shall** define a `compact` tool schema in `agent/tools.py` with a description indicating it triggers immediate context summarization.
2. **When** the LLM calls the `compact` tool, **the dispatch layer shall** execute the same summarization mechanism used by auto-compact (Requirement 3), replacing the conversation with a summary.
3. **The `compact` tool shall** return a confirmation message to the LLM indicating that context was summarized and the approximate token reduction achieved.
4. **The `compact` tool schema shall** be included in `TOOL_SCHEMAS` (available to the executor) but not in `SCOUT_TOOL_SCHEMAS` (not available to the scout).
5. **The `compact` tool shall** be a lower priority than the automatic layers -- it provides a safety valve for edge cases where the LLM detects context degradation before the auto-compact threshold is reached.

---

## Requirement 7: Observability Integration

Context management operations must be visible in the observability layer so operators can monitor compaction frequency, token savings, and potential issues.

### Acceptance Criteria

1. **When** a micro-compact pass clears tool result messages, **the agent shall** log the number of messages cleared and the estimated characters saved at DEBUG level.
2. **When** an auto-compact operation is triggered, **the agent shall** log at INFO level: the trigger reason (threshold exceeded), estimated tokens before and after compaction, and the number of messages replaced.
3. **When** the compact tool is invoked by the LLM, **the agent shall** log the invocation at INFO level with the same detail as auto-compact.
4. **When** Langfuse observability is active, **auto-compact LLM calls shall** appear as traced LLM calls in the same trace as the executor, using the existing `metadata` parameter mechanism for trace grouping.
5. **Transcript files saved during auto-compact (Requirement 3) shall** include a metadata header with: timestamp, trace ID (if available), estimated token count, and compaction reason.

---

## Requirement 8: Configuration Surface

All configurable parameters for the context management pipeline must be centralized and overridable without code changes.

### Acceptance Criteria

1. **The context management module shall** define the following configurable parameters with sensible defaults:
   - Tool result truncation limit (characters, default: 10,000)
   - Micro-compact recency window (number of recent tool-result batches to preserve, default: 3)
   - Micro-compact minimum content length to clear (characters, default: 100)
   - Auto-compact token threshold (estimated tokens, default suitable for production use)
   - Transcript save directory (path, default: `.transcripts/`)
2. **All configurable parameters shall** be overridable via environment variables or constructor arguments -- no code changes required to tune the pipeline.
3. **The `.env.example` file shall** document all context management environment variables with descriptions and default values.

---

## Requirement 9: Backward Compatibility and Safety

The context management pipeline must not break existing agent behavior, API contracts, or tool dispatch integrity.

### Acceptance Criteria

1. **The context management pipeline shall** preserve `tool_call_id` linkage on all tool result messages -- micro-compact must never remove a tool result message entirely, only replace its content.
2. **When** context management is disabled or not configured, **the agent shall** behave identically to the current implementation with no performance overhead.
3. **The context management pipeline shall** not modify messages from the current turn (the turn about to be sent to the LLM) -- only historical messages are eligible for compaction.
4. **The auto-compact summarization prompt shall** instruct the LLM to preserve awareness of the original task instruction and system prompt rules, so post-compaction behavior remains aligned.
5. **The existing `report_completion` flow shall** work correctly after any compaction event -- the LLM must retain enough context to produce a valid completion answer with grounding references.
