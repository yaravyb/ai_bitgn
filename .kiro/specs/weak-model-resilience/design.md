# Design: weak-model-resilience

> Generated: 2026-03-25
> Status: pending approval

## 1. Overview

This design adds resilience mechanisms to the executor loop in `loop.py` to handle three weak-model failure modes: empty LLM responses, tool calls emitted as plain text, and lack of error recovery. All changes are confined to `loop.py` (plus a new `ResilienceConfig` dataclass and `ResilienceState` tracker). No new modules are introduced.

**Requirements coverage**: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17

**Patterns from example agents (s01-s12, s_full.py)**:
- **s03 nag pattern** → Req 14 (checkpoint after N steps without completion)
- **s06 micro-compact as reset** → Req 16 (auto-compact before re-plan to force fresh perspective)
- **s_full identity re-injection** → Req 17 (tool schema reminder in nudge messages)
- **s11 idle→auto-claim** → Req 14 (re-plan prompt asks model to reassess, like transitioning from stuck to exploration)
- **s07/s09 external state** → ResilienceState dataclass (survives context compression)

## 2. Data Structures

### 2.1 ResilienceConfig (frozen dataclass)

Located in `context.py`, alongside `ContextConfig`. Follows the same `from_env()` factory pattern. Frozen and immutable -- constructed once per `run_agent` call.

```
@dataclass(frozen=True)
class ResilienceConfig:
    empty_retry_max: int          # env: RESILIENCE_EMPTY_RETRY_MAX, default 3
    text_tool_max: int            # env: RESILIENCE_TEXT_TOOL_MAX, default 2
    error_threshold: int          # env: RESILIENCE_ERROR_THRESHOLD, default 3

    @classmethod
    def from_env(cls) -> ResilienceConfig: ...
```

**Req 12**: All three thresholds configurable via environment variables.
**Req 7**: Zero overhead -- config is read once; counters are checked only on the specific code paths that already handle the respective conditions.

### 2.2 ResilienceState (mutable dataclass)

Located in `loop.py` (module-private). Mutable counters reset during execution. Constructed once per `run_agent` call, alongside `VerificationState`.

```
@dataclass
class ResilienceState:
    consecutive_empty: int = 0        # resets on any non-empty response
    consecutive_text_tool: int = 0    # resets on any non-text-tool response
    consecutive_errors: int = 0       # resets on successful tool dispatch
    completion_submitted: bool = False # set True when report_completion dispatched
```

**Req 10**: No separate retry budget. Each retry/re-prompt consumes one iteration of the existing `for step in range(30)` loop.

## 3. Modified Executor Loop Flow

The executor loop (`for step in range(30)`) is modified at three intervention points plus a post-loop guard. The existing flow is preserved; resilience logic is additive.

### 3.1 Intervention Point A: Empty Response Handler

**Location**: Inside the `else` branch (no tool calls), replacing the unconditional `break` when `response.content` is empty/whitespace.

**Current behavior** (lines ~617-629): When `response.content` is falsy or whitespace and NOT in verification, the loop breaks. During verification, it submits the captured answer.

**New behavior**:

```
# Pseudocode -- NOT implementation code
if response has no tool calls and content is empty/whitespace:
    if verification_state.in_verification:
        ... existing verification fallback (unchanged) ...
    else:
        state.consecutive_empty += 1
        if state.consecutive_empty < config.empty_retry_max:
            log.warning("Empty response at step %d (retry %d/%d)", ...)
            inject nudge message into messages[]
            continue  # next loop iteration (consumes a step)
        else:
            log.warning("Empty response retry exhausted at step %d", ...)
            submit fallback via report_completion(OUTCOME_ERR_INTERNAL)
            state.completion_submitted = True
            break
```

**Nudge message content** (Req 6): `"Your previous response was empty. Continue working on the task using the available tools. Do not repeat yourself -- take the next action."`

**Req 1**: Retry with nudge. **Req 2**: Fallback submission after exhaustion. **Req 8**: Warning-level logging with step number and retry count. **Req 10**: Each retry consumes one step from the 30-step limit.

### 3.2 Intervention Point B: Text-as-Tool Detector

**Location**: Inside the text-only branch, AFTER `_try_extract_completion()` succeeds or fails, BEFORE the auto-submit path.

**Current behavior** (lines ~541-549): `_try_extract_completion()` is called. If extraction succeeds, the extracted answer is used. If extraction fails, the raw text is auto-submitted as the answer.

**New behavior**:

```
# Pseudocode
extracted = _try_extract_completion(raw_text)
if extracted:
    state.consecutive_text_tool = 0  # valid completion, reset counter
    ... existing auto-submit / verification flow (unchanged) ...
else:
    if _looks_like_tool_call(raw_text):  # NEW function
        state.consecutive_text_tool += 1
        if state.consecutive_text_tool <= config.text_tool_max:
            detected_tool = _detect_tool_name(raw_text)
            log.info("Text-as-tool detected: tool=%s, text=%s", detected_tool, raw_text[:120])
            inject correction message into messages[]
            continue  # next loop iteration
        else:
            # Exhausted re-prompts, fall through to auto-submit
            state.consecutive_text_tool = 0
    # ... existing auto-submit path ...
```

**Req 4**: `_try_extract_completion()` remains the first check -- unchanged.
**Req 3**: Malformed tool calls detected and re-prompted. Raw JSON not auto-submitted.
**Req 7**: `_looks_like_tool_call` is a lightweight JSON parse + key check -- no LLM call.

### 3.3 Helper Functions (module-private)

Two small helper functions added to `loop.py`:

**`_looks_like_tool_call(text: str) -> bool`**:
1. **Pre-check**: If `text.strip()` does not start with `{` and end with `}`, return False immediately (Req 7: zero overhead for non-JSON text).
2. Attempt `json.loads(text.strip())`. If parse fails, return False.
3. If result is not a dict, return False.
4. If dict contains `"answer"` key, return False (handled by `_try_extract_completion`).
5. Check for **distinguishing parameter combinations** (not just `"path"` alone — too many false positives):
   - `{"path", "content"}` → likely `write_file`
   - `{"path", "level"}` → likely `tree`
   - `{"path", "number"}` or `{"path", "start_line"}` → likely `read_file`
   - `{"pattern"}` → likely `search`
   - `{"name"}` with `"root"` or `"kind"` → likely `find`
   - `{"path"}` alone → **ambiguous** — return False (too many false positives)
6. Return True only if a distinguishing combo is matched.

**`_detect_tool_name(text: str) -> str | None`**: Uses the same combo matching to identify the most likely tool. Returns tool name or None.

**Known tool parameter signatures** (derived from `tools.py`):

| Tool | Distinguishing param combo | `"path"` alone? |
|------|---------------------------|-----------------|
| tree | `path` + `level` | No (ambiguous) |
| list_dir | `path` only | No (ambiguous) |
| read_file | `path` + (`number` or `start_line` or `end_line`) | No (ambiguous) |
| write_file | `path` + `content` | No — requires `content` |
| search | `pattern` |
| find | `name` |
| report_completion | `answer` (handled by `_try_extract_completion`) |

**Correction message content** (Req 6): `"You wrote a tool call as plain text instead of using the function calling mechanism. Please invoke the '{tool_name}' tool properly using function calling. Do not output JSON directly in your response."`

### 3.4 Intervention Point C: Error Recovery Hint Injector

**Location**: After tool dispatch results are appended to `messages[]`, before the next loop iteration. Inside the `if other_tool_calls:` block (lines ~643-668).

**New behavior**:

```
# Pseudocode -- after appending tool results to messages[]
any_error = False
for tool_call_id, result_text in results:
    ... existing append logic ...
    if '"error"' in result_text:
        any_error = True
        state.consecutive_errors += 1
        if "not_found" in result_text.lower() or "NOT_FOUND" in result_text:
            # Inject NOT_FOUND-specific hint (Req 5, Req 6)
            hint = f"The file was not found. Try using list_dir or tree on the parent directory to find the correct filename. Path attempted: {extract_path(result_text)}"
            append hint as additional content to the tool result message
    else:
        state.consecutive_errors = 0  # reset on success

if state.consecutive_errors >= config.error_threshold:
    # Inject escalated recovery (Req 5)
    inject user message: "You have encountered {N} consecutive errors. Consider an alternative approach. Available tools: tree, list_dir, read_file, search, find, write_file, report_completion."
    state.consecutive_errors = 0  # reset after escalation
```

**Req 5**: NOT_FOUND hints + escalated recovery after threshold. **Req 7**: Only triggers when errors actually occur -- zero overhead on success path. **Req 8**: Info-level logging for each hint injection.

### 3.5 Post-Loop Guard: Guaranteed Answer Submission

**Location**: After the `for step in range(30)` loop exits (line ~772+), replacing the current weak verification fallback.

```
# Pseudocode -- after the for-loop
if not state.completion_submitted:
    log.warning("Loop exited without report_completion (step=%d)", step_num)
    if verification_state.in_verification and verification_state.original_answer:
        # Submit the captured original answer (Req 13)
        dispatch_tool(runtime, "report_completion", {
            "answer": verification_state.original_answer,
            "code": verification_state.original_code,
            ...
        })
    else:
        # Generic fallback (Req 13)
        dispatch_tool(runtime, "report_completion", {
            "answer": "Agent loop ended without producing an answer.",
            "code": "OUTCOME_ERR_INTERNAL",
            ...
        })
    state.completion_submitted = True
```

**Req 13**: `report_completion` guaranteed to be called before `run_agent` returns, regardless of exit reason.

The `completion_submitted` flag is set to `True` at every existing `dispatch_tool(... "report_completion" ...)` call site. To handle edge cases (exceptions during dispatch), the flag is set BEFORE the dispatch call — if the dispatch fails, the guard still won't double-submit because the harness already received the (failed) attempt.

**Exit-point mapping** (every way the loop can end):

| Exit Point | How | `completion_submitted`? | Guard fires? |
|---|---|---|---|
| Normal tool-call completion | `break` after `dispatch_tool("report_completion")` | True (set before dispatch) | No |
| Text-only auto-submit | `break` after `dispatch_tool("report_completion")` | True (set before dispatch) | No |
| Empty-during-verification | `break` after `dispatch_tool("report_completion")` | True | No |
| Empty-retry exhaustion (Req 2) | `break` after fallback `dispatch_tool("report_completion")` | True | No |
| Text-tool re-prompt exhaustion | Falls through to auto-submit → same as text-only | True | No |
| 30-step limit reached | `for` loop ends naturally | **Maybe False** | **Yes — guard fires** |
| Exception in dispatch | Loop continues (ConnectError caught) | **Maybe False** | **Yes — guard fires** |

## 4. Counter Reset Rules

| Counter | Reset to 0 when | Incremented when |
|---------|-----------------|------------------|
| `consecutive_empty` | Any non-empty LLM response (text or tool calls) | Empty/whitespace response with no tool calls |
| `consecutive_text_tool` | Valid tool call response OR valid `_try_extract_completion` | `_looks_like_tool_call()` returns True |
| `consecutive_errors` | Any tool dispatch returns non-error result | Any tool dispatch returns error result |

Resets are placed at the top of each branch so strong models never accumulate counts.

## 5. Sequence Diagram

```
LLM Response
    |
    v
+-- Has tool_calls? --YES--> dispatch tools --> [Point C: error hint?] --> continue
|
NO (text-only)
    |
    v
+-- Content empty/whitespace? --YES--> [Point A: empty handler]
|                                          |
|                                   retry < max? --YES--> nudge, continue
|                                          |
|                                          NO --> fallback submit, break
|
NO (has text)
    |
    v
    _try_extract_completion()
    |
+-- extracted? --YES--> auto-submit / verification (existing flow)
|
NO
    |
    v
    [Point B: _looks_like_tool_call()?]
    |
+-- YES and retries < max? --> correction message, continue
|
NO (or exhausted)
    |
    v
    auto-submit raw text (existing flow)
    |
    v
=== for-loop ends ===
    |
    v
[Point D: post-loop guard]
    completion_submitted? --YES--> done
                          --NO---> submit fallback
```

## 6. Re-Planning Mechanism (Req 14, 15)

Inspired by the `s_full.py` reference agent's "todo nag" pattern: track rounds since last meaningful progress, inject a checkpoint prompt when the model appears stuck.

### 6.1 ResilienceState Extensions

```
@dataclass
class ResilienceState:
    ... existing fields ...
    steps_since_completion_attempt: int = 0   # reset when report_completion is called
    recent_tool_calls: list = field(default_factory=list)  # rolling window of (name, args_hash)
```

### 6.2 ResilienceConfig Extensions

```
@dataclass(frozen=True)
class ResilienceConfig:
    ... existing fields ...
    replan_interval: int          # env: RESILIENCE_REPLAN_INTERVAL, default 8
```

### 6.3 Intervention Point E: Checkpoint / Re-Plan Prompt

**Location**: At the TOP of each loop iteration, before the LLM call.

**Trigger conditions** (checked in order):
1. **Repetition detection** (Req 15): If the last 3 entries in `recent_tool_calls` have the same `(name, args_hash)` → stuck on same action.
2. **Progress stall** (Req 14): If `steps_since_completion_attempt >= config.replan_interval` → no progress toward completion.

**When triggered** (Req 14, 15, 16):
```
# Pseudocode (inspired by s_full.py todo nag + s06 compact-as-reset)
if repetition_detected or steps_since_completion_attempt >= config.replan_interval:

    # Step 1: Auto-compact context for fresh perspective (Req 16)
    # Only compact if context is substantial (>20K tokens); skip if small
    if estimate_tokens(messages) > 20_000:
        messages[:] = _apply_auto_compact(
            messages, context_config, executor_model, trace_metadata,
            reason="replan_recovery",
        )
        log.info("Re-plan: auto-compacted context at step %d", step_num)

    # Step 2: Inject checkpoint prompt (Req 14)
    checkpoint_msg = (
        "<checkpoint>\n"
        f"You have been working for {steps_since_completion_attempt} steps without completing.\n"
        "Step back and assess:\n"
        "1. What have you accomplished so far?\n"
        "2. What remains to be done?\n"
        "3. Are you stuck? If so, try a different approach.\n"
        "4. If the task is done, call report_completion.\n"
        "</checkpoint>"
    )
    messages.append({"role": "user", "content": checkpoint_msg})
    state.steps_since_completion_attempt = 0  # reset after checkpoint
    state.recent_tool_calls.clear()
    log.info("Re-plan checkpoint injected at step %d", step_num)
```

**Rolling window tracking**:
```
# After dispatching each tool call:
args_hash = hash(json.dumps(tc.arguments, sort_keys=True))
state.recent_tool_calls.append((tc.name, args_hash))
if len(state.recent_tool_calls) > 5:
    state.recent_tool_calls.pop(0)

# Repetition check: last 3 identical
if len(state.recent_tool_calls) >= 3:
    last3 = state.recent_tool_calls[-3:]
    if len(set(last3)) == 1:
        # repetition detected
```

**Req 14**: Periodic checkpoint after N steps. **Req 15**: Repetition detection via rolling window. **Req 7**: Only a counter increment + comparison on each step — zero overhead for strong models that complete quickly.

## 7. Files to Modify

| File | Change |
|------|--------|
| `sandbox-py/agent/context.py` | Add `ResilienceConfig` dataclass with `from_env()` |
| `sandbox-py/agent/loop.py` | Import `ResilienceConfig`; add `ResilienceState`, `_looks_like_tool_call()`, `_detect_tool_name()`; modify `run_agent()` with 3 intervention points + post-loop guard |
| `sandbox-py/tests/test_loop.py` | Add test cases for empty retry, empty fallback, text-as-tool detection, error recovery hints, guaranteed submission, re-planning checkpoint, repetition detection |
| `docs/agent-analysis.md` | Update Weakness #1, add Strength entry, update scorecard (Req 11) |

## 7. Test Strategy

All tests use mock `call_llm` responses. No real LLM calls.

| Test | Simulates | Asserts |
|------|-----------|---------|
| `test_empty_response_retry` | 2 empty responses then valid tool call | Nudge injected twice, loop continues, no fallback |
| `test_empty_response_fallback` | 3 consecutive empty responses (max) | `report_completion` called with `OUTCOME_ERR_INTERNAL` |
| `test_empty_response_counter_reset` | Empty, valid, empty | Counter resets; no fallback after 1+1 empties |
| `test_text_tool_detection` | JSON `{"path": "/foo"}` as text | Correction message injected, not auto-submitted |
| `test_text_tool_max_exceeded` | 3 consecutive text-tool responses | After 2 re-prompts, 3rd is auto-submitted |
| `test_try_extract_completion_priority` | Text with `{"answer": "..."}` | Goes through existing path, no text-tool detection |
| `test_error_recovery_not_found` | Tool returns `{"error": "NOT_FOUND: ..."}` | Recovery hint appended to messages |
| `test_error_escalation` | 3 consecutive tool errors | Escalated recovery message injected |
| `test_guaranteed_submission_step_limit` | 30 steps with no completion | Post-loop guard calls `report_completion` |
| `test_guaranteed_submission_verification` | Loop ends during verification | Original answer submitted |
| `test_strong_model_no_overhead` | Normal tool calls, valid completion | Zero resilience interventions, `consecutive_*` all 0 |
| `test_replan_checkpoint_injected` | 8 steps without report_completion | Checkpoint message injected after step 8 |
| `test_replan_counter_resets` | Checkpoint at step 8, then 4 more steps | Counter reset after checkpoint, no double-trigger |
| `test_repetition_detection` | Same tool+args called 3x in a row | Checkpoint triggered by repetition, not interval |
| `test_repetition_with_different_args` | Same tool, different args 3x | No checkpoint (args differ, not stuck) |
