# Tasks: weak-model-resilience

> Generated: 2026-03-25
> Status: pending approval

## Task 1 (P): Add ResilienceConfig dataclass to context.py [x]

**Requirements**: 12

Add a frozen `ResilienceConfig` dataclass alongside the existing `ContextConfig` in `context.py`. Follow the identical `from_env()` factory pattern. The dataclass has four fields: `empty_retry_max` (env: `RESILIENCE_EMPTY_RETRY_MAX`, default 3), `text_tool_max` (env: `RESILIENCE_TEXT_TOOL_MAX`, default 2), `error_threshold` (env: `RESILIENCE_ERROR_THRESHOLD`, default 3), and `replan_interval` (env: `RESILIENCE_REPLAN_INTERVAL`, default 8). All fields are integers. When no environment variables are set, defaults apply without additional configuration.

## Task 2 (P): Add ResilienceState dataclass and helpers to loop.py [x]

**Requirements**: 10, 15

Add a module-private mutable `ResilienceState` dataclass at the top of `loop.py`. Fields: `consecutive_empty` (int, default 0), `consecutive_text_tool` (int, default 0), `consecutive_errors` (int, default 0), `completion_submitted` (bool, default False), `steps_since_completion_attempt` (int, default 0), and `recent_tool_calls` (list, default empty). Also add two module-private helper functions: `_looks_like_tool_call(text)` that returns True only when the text parses as a JSON dict matching a distinguishing tool parameter combination (as specified in the design -- `path+content`, `path+level`, `pattern`, etc., but NOT `path` alone and NOT dicts containing `answer`), and `_detect_tool_name(text)` that returns the most likely tool name based on the same combos. Both functions must return False/None immediately when text does not start with `{` and end with `}` to ensure zero overhead for non-JSON text.

## Task 3: Implement post-loop guaranteed answer submission (Point D) [x]

**Requirements**: 13

**Depends on**: Task 2

This is the highest-priority intervention: it prevents ALL "no answer provided" failures. After the `for step in range(30)` loop exits, add a guard that checks `state.completion_submitted`. If False, log a warning and submit a fallback: if in a verification cycle with a captured original answer, submit that answer with the original outcome code; otherwise submit a generic fallback with `OUTCOME_ERR_INTERNAL`. Also set `state.completion_submitted = True` at every existing `dispatch_tool(... "report_completion" ...)` call site inside the loop (set it BEFORE the dispatch call to handle edge cases). Replace the current weak verification fallback at the end of `run_agent()` with this robust guard.

## Task 4 (P): Implement empty response retry and fallback (Point A) [x]

**Requirements**: 1, 2, 6, 8, 17

**Depends on**: Task 2, Task 3

Modify the text-only branch in the executor loop where `response.content` is empty/whitespace and the model is NOT in a verification cycle. Instead of breaking unconditionally, increment `state.consecutive_empty` and check against `config.empty_retry_max`. If under the limit, log a warning with step number and retry count, inject a nudge user message that includes the list of available tool names (from `get_tool_schemas`), and `continue` to the next loop iteration. If the limit is reached, log a warning about exhaustion, call `report_completion` with `OUTCOME_ERR_INTERNAL`, set `completion_submitted = True`, and break. On any non-empty LLM response (text or tool calls), reset `consecutive_empty` to zero.

## Task 5 (P): Implement text-as-tool-call detection and correction (Point B) [x]

**Requirements**: 3, 4, 6, 8, 17

**Depends on**: Task 2, Task 3

Modify the text-only branch in the executor loop, after `_try_extract_completion()` fails. Before falling through to the auto-submit path, call `_looks_like_tool_call(raw_text)`. If it returns True and `state.consecutive_text_tool` is under `config.text_tool_max`, increment the counter, log an info message with the detected tool name and a snippet of the raw text, inject a correction user message that names the detected tool and instructs the model to use function calling, and `continue`. If the counter exceeds the max, reset it and fall through to the existing auto-submit path. When `_try_extract_completion()` succeeds, reset `consecutive_text_tool` to zero. The correction message must include available tool names.

## Task 6 (P): Implement error recovery hint injector (Point C) [x]

**Requirements**: 5, 6, 8, 17

**Depends on**: Task 2, Task 3

After tool dispatch results are appended to `messages[]` in the `if other_tool_calls:` block, inspect each result for error indicators. When a result contains a NOT_FOUND indicator, append a file-specific recovery hint to the tool result message suggesting the model list the parent directory, including the attempted path. Increment `consecutive_errors` on any error; reset to zero on any non-error result. When `consecutive_errors` reaches `config.error_threshold`, inject an escalated recovery user message that lists available tool names and suggests an alternative approach, then reset the counter. Log each hint injection at info level with tool name, error type, and recovery action.

## Task 7: Implement re-planning checkpoint and repetition detection (Point E) [x]

**Requirements**: 14, 15, 16

**Depends on**: Tasks 4, 5, 6

At the top of each loop iteration (before the LLM call), check for two trigger conditions: (1) repetition -- if the last 3 entries in `state.recent_tool_calls` have the same name and argument hash; (2) progress stall -- if `steps_since_completion_attempt >= config.replan_interval`. When either triggers: if context is substantial (estimated >20K tokens), call `_apply_auto_compact` with reason `replan_recovery` to force a fresh perspective; then inject a checkpoint user message asking the model to summarize progress, reassess, and try a different approach if stuck. The checkpoint message must NOT include tool names. After injection, reset `steps_since_completion_attempt` and clear `recent_tool_calls`. After each tool dispatch, record the tool name and a hash of sorted JSON arguments in the rolling window (max 5 entries). Increment `steps_since_completion_attempt` each iteration; reset when `report_completion` is dispatched.

## Task 8: Compose nudge message content with tool schema reminder [x]

**Requirements**: 6, 17

**Depends on**: Tasks 4, 5, 6

Create a private helper function `_build_tool_name_list(runtime_type)` that returns a brief comma-separated string of available tool names extracted from `get_tool_schemas()`. Wire this into the three nudge/recovery paths: (1) the empty-response nudge (Task 4) includes tool names, (2) the error escalation message (Task 6) includes tool names, (3) the re-planning checkpoint (Task 7) does NOT include tool names. Verify that the correction message for text-as-tool (Task 5) already includes the detected tool name. This task ensures all nudge messages follow the s_full pattern of re-injecting tool awareness after any intervention.

- [x]* Verify nudge message content matches acceptance criteria for each scenario

## Task 9: Add observability logging for all resilience interventions [x]

**Requirements**: 7, 8

**Depends on**: Tasks 4, 5, 6, 7

Audit all resilience intervention paths to ensure correct log levels and message content: empty response retry (warning, with step number and retry count), malformed tool call detection (info, with tool name and text snippet), error recovery hint (info, with tool name, error type, and action), fallback submission (warning, indicating fallback triggered), re-planning checkpoint (info, with step number and trigger reason). Ensure that when the model behaves correctly (valid tool calls, valid text answers), no resilience-related logging or processing occurs beyond lightweight counter checks.

## Task 10: Add tests for all resilience mechanisms [x]

**Requirements**: 9, 10

**Depends on**: Tasks 3, 4, 5, 6, 7

Add test cases to `test_loop.py` using mock LLM responses (no real LLM calls). Cover all scenarios from the design test strategy table:
- `test_empty_response_retry`: 2 empty responses then valid tool call -- nudge injected, loop continues
- `test_empty_response_fallback`: 3 consecutive empties -- `report_completion` called with `OUTCOME_ERR_INTERNAL`
- `test_empty_response_counter_reset`: empty, valid, empty -- counter resets, no fallback
- `test_text_tool_detection`: JSON as text -- correction injected, not auto-submitted
- `test_text_tool_max_exceeded`: 3 consecutive text-tool responses -- after 2 re-prompts, 3rd auto-submitted
- `test_try_extract_completion_priority`: text with `{"answer": "..."}` -- existing path, no text-tool detection
- `test_error_recovery_not_found`: tool returns NOT_FOUND error -- hint appended
- `test_error_escalation`: 3 consecutive tool errors -- escalated message injected
- `test_guaranteed_submission_step_limit`: 30 steps with no completion -- post-loop guard fires
- `test_guaranteed_submission_verification`: loop ends during verification -- original answer submitted
- `test_strong_model_no_overhead`: normal tool calls -- zero interventions, all counters at 0
- `test_replan_checkpoint_injected`: 8 steps without completion -- checkpoint injected
- `test_replan_counter_resets`: checkpoint at step 8, then more steps -- no double-trigger
- `test_repetition_detection`: same tool+args 3x -- checkpoint triggered
- `test_repetition_with_different_args`: same tool, different args -- no checkpoint

Verify all previously passing tests remain green.

## Task 11: Update architecture documentation [x]

**Requirements**: 11

**Depends on**: Tasks 3, 4, 5, 6, 7

Update `docs/agent-analysis.md`: (1) Mark Weakness #1 ("No Error Recovery or Re-Planning") as addressed with references to empty response retry, text-as-tool detection, error recovery hints, re-planning checkpoints, and guaranteed answer submission. (2) Add a new Strength entry documenting the weak-model resilience system with its five intervention points, configurability via environment variables, and zero-overhead design for strong models. (3) Document Root Cause 2 (tool calls as plain text) as a known model behavior pattern. (4) Update the Summary Scorecard "Error handling" rating from "Moderate" to "Strong" with notes about the resilience mechanisms.
