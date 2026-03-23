# Tasks: context-management

> Three-layer context compression pipeline (tool result truncation, micro-compact, auto-compact) to prevent unbounded message growth in the executor loop and scout phase.

## Task 1: Create `ContextConfig` dataclass and `estimate_tokens` in `agent/context.py` [x]

Create the new leaf module `sandbox/py/agent/context.py` with the `ContextConfig` dataclass (all configurable parameters with sensible defaults), the `from_env()` factory method that reads environment variables with fallback to defaults, the `COMPACT_SENTINEL` constant, and the `estimate_tokens()` pure function that computes token count via `len(str(messages)) // 4`.

**Requirements**: 4, 8

## Task 2: Implement `truncate_tool_result` in `agent/context.py` [x]

Add the `truncate_tool_result(result_text, config)` pure function to `context.py`. Implement the JSON-aware truncation path (parse JSON, find the largest string value, truncate it within the character budget, re-serialize) and the raw-string fallback path. Append the truncation indicator `\n...[truncated, {original_length} chars total]` when truncation occurs. Return the input unchanged when under the limit.

**Requirements**: 1

## Task 3: Implement `micro_compact` in `agent/context.py` [x]

Add the `micro_compact(messages, config)` pure function to `context.py`. Implement batch detection by scanning for assistant messages with `tool_calls` keys, identify batches older than the most recent N batches, and replace oversized `role == "tool"` content with `"[Previous tool result cleared]"`. Preserve `tool_call_id` on every message, never remove messages, never modify system/user/assistant messages.

**Requirements**: 2

## Task 4: Unit tests for `context.py` pure functions (P) [x]

Create `sandbox/py/tests/test_context.py` with tests covering: `estimate_tokens` (empty list, known input), `truncate_tool_result` (under limit, over limit JSON, over limit raw, JSON fallback), `micro_compact` (no batches, within keep window, clears old batches, preserves `tool_call_id`, preserves non-tool messages, preserves short content, batch detection), `ContextConfig` defaults, and `ContextConfig.from_env` with environment variable overrides. All tests use plain dicts -- no mocking required. Run with `cd sandbox/py && uv run pytest tests/test_context.py -x -v`.

**Requirements**: 1, 2, 4, 8, 9

## Task 5: Integrate tool result truncation into `agent/dispatch.py` [x]

Add `context_config: ContextConfig | None = None` parameter to `dispatch_tool()` and `dispatch_parallel()`. After the handler returns a result, apply `truncate_tool_result()` when `context_config` is not `None` and the tool is not `report_completion`. Log truncation events at DEBUG level (tool name, original size, truncated size). Add `_handle_compact` handler returning `COMPACT_SENTINEL` and register it in `DISPATCH_MAP`. Ensure `dispatch_parallel()` passes `context_config` through to `dispatch_tool()`.

**Requirements**: 1, 6, 9

## Task 6: Add `compact` tool schema to `agent/tools.py` (P) [x]

Add the `compact` tool schema to `TOOL_SCHEMAS` with an empty parameters object and a description indicating it triggers immediate context summarization. Verify it is automatically excluded from `SCOUT_TOOL_SCHEMAS` because `_SCOUT_TOOL_NAMES` does not include `"compact"`.

**Requirements**: 6

## Task 7: Integrate pre-LLM compression and auto-compact into `agent/loop.py` [x]

In `run_agent()`, initialize `ContextConfig.from_env()` and pass `context_config` to all `dispatch_parallel()` calls. Before each `call_llm()` in the executor loop, call `_apply_micro_compact()` (wraps `micro_compact`, returns cleared count and chars saved, logs at DEBUG) and then check `estimate_tokens()` against the threshold to trigger `_apply_auto_compact()`. Implement `_apply_auto_compact()` to: save the pre-compaction transcript as JSONL with metadata header (timestamp, trace_id, estimated tokens, reason), call `call_llm()` with the summarization prompt (preserving task awareness per Req 9.4), replace all messages with [system message, summary user message, assistant acknowledgment], and log at INFO level. Add compact sentinel detection after dispatching tool calls (same pattern as `report_completion`), replacing the sentinel content with a placeholder before triggering `_apply_auto_compact()`. Pass `context_config` to the `run_scout()` call.

**Requirements**: 2, 3, 6, 7, 9

### Task 7.1: Implement `_apply_micro_compact()` helper

Create the `_apply_micro_compact(messages, config)` helper that captures content lengths before calling `micro_compact()`, compares after to compute `cleared_count` and `chars_saved`, and returns `(cleared_count, chars_saved)`.

### Task 7.2: Implement `_apply_auto_compact()` helper with transcript saving

Create the `_apply_auto_compact(messages, config, model, trace_metadata)` helper that saves the transcript to `{config.transcript_dir}/transcript_{timestamp}.jsonl` with the metadata header, calls `call_llm()` for summarization (with `max_tokens=2000`, no tools, passing `trace_metadata` for Langfuse grouping), builds the replacement messages list `[system, summary, ack]`, and logs at INFO level. Handle transcript write failures gracefully (log WARNING, continue without saving).

### Task 7.3: Wire pre-LLM compression and sentinel detection into the executor loop

Insert the micro-compact and auto-compact calls before `call_llm()` in the executor loop. Add compact sentinel detection after `dispatch_parallel()` results are appended. Initialize `ContextConfig.from_env()` at the top of `run_agent()` and pass `context_config` to `dispatch_parallel()`, the auto-submit `dispatch_tool()` fallback, and `run_scout()`.

## Task 8: Integrate micro-compact into `agent/scout.py` [x]

Add `context_config: ContextConfig | None = None` parameter to `run_scout()` and pass it through to `_run_llm_explorer()`. In `_run_llm_explorer()`, call `micro_compact(messages, scout_context_config)` before each `call_llm()` invocation, using a scout-specific `ContextConfig` with independently tunable values (read from `CTX_SCOUT_MICRO_COMPACT_KEEP_BATCHES` and `CTX_SCOUT_MICRO_COMPACT_MIN_LENGTH` environment variables, defaulting to `keep_batches=2`). Do NOT apply auto-compact in the scout phase. Pass `context_config` to `dispatch_parallel()` and `dispatch_tool()` calls so tool result truncation applies.

**Requirements**: 5

## Task 9: Update `.env.example` with context management variables (P) [x]

Add a new "Context Management" section to `sandbox/py/.env.example` documenting all environment variables: `CTX_TRUNCATION_LIMIT`, `CTX_MICRO_COMPACT_KEEP_BATCHES`, `CTX_MICRO_COMPACT_MIN_LENGTH`, `CTX_AUTO_COMPACT_THRESHOLD`, `CTX_TRANSCRIPT_DIR`, and scout-specific overrides `CTX_SCOUT_MICRO_COMPACT_KEEP_BATCHES` and `CTX_SCOUT_MICRO_COMPACT_MIN_LENGTH`. Include descriptions and default values as comments.

**Requirements**: 8

## Task 10: Extend dispatch and loop tests for context management integration [x]

Add tests to `sandbox/py/tests/test_dispatch.py`: truncation applied when `context_config` provided, no truncation when `context_config` is `None` (backward compatibility), `report_completion` exempt from truncation, compact tool returns sentinel. Add tests to `sandbox/py/tests/test_loop.py`: micro-compact called before `call_llm()`, auto-compact triggered when token threshold exceeded, auto-compact saves transcript file, auto-compact preserves system message, auto-compact replaces messages correctly, compact sentinel triggers compaction, `report_completion` works after compaction. Run with `cd sandbox/py && uv run pytest tests/test_dispatch.py tests/test_loop.py -x -v`.

**Requirements**: 1, 3, 6, 9

### Task 10.1: Extend `tests/test_dispatch.py` with truncation and compact sentinel tests

Add tests verifying: `dispatch_tool` applies truncation when `context_config` is provided and result exceeds limit; `dispatch_tool` returns result unchanged when `context_config` is `None`; `report_completion` is exempt from truncation; `dispatch_tool("compact", ...)` returns `COMPACT_SENTINEL`.

### Task 10.2: Extend `tests/test_loop.py` with pre-LLM compression and sentinel tests

Add tests verifying: micro-compact is called before each `call_llm()`; auto-compact triggers when estimated tokens exceed threshold; transcript file is saved during auto-compact; system message is preserved after compaction; messages are replaced with [system, summary, ack]; compact sentinel in dispatch results triggers `_apply_auto_compact`; `report_completion` flow works correctly after a compaction event.

## Task 11: Extend scout tests for context management integration (P) [x]

Add tests to `sandbox/py/tests/test_scout.py`: micro-compact is applied in the LLM explorer loop before each `call_llm()`; auto-compact is NOT applied in the scout phase; tool result truncation applies to scout tool calls via `dispatch_parallel` with `context_config`. Run with `cd sandbox/py && uv run pytest tests/test_scout.py -x -v`.

**Requirements**: 5
