# Requirements: weak-model-resilience

> Initialized: 2026-03-25T14:00:00Z
> Status: pending

## Problem Statement

The agent framework scores 81% with minimax-m2.1 but drops to 47% with openai.gpt-oss-120b — a weaker model. Analysis of all 9 failures reveals 3 distinct root causes, all framework-fixable:

### Root Cause 1: Empty LLM Response → Silent Loop Exit (5/9 failures)
**Tasks**: t01, t03, t11, t14, t16
**Symptom**: Model returns empty response (no tool calls, no text). The executor loop breaks silently without calling `report_completion`. Harness sees "no answer provided."
**Code location**: `loop.py` lines ~425-511, the text-only handler's `break` path when `response.content` is empty/whitespace and NOT in verification.
**Fix needed**: When LLM returns empty response, either retry with a "continue" nudge or auto-submit with `OUTCOME_ERR_INTERNAL`.

### Root Cause 2: Tool Calls as Plain Text (3/9 failures)
**Tasks**: t10, t13, t17
**Symptom**: Model outputs tool-call JSON as raw text (e.g., `{"path": "contacts"}`) instead of using function calling. `_try_extract_completion()` only catches `report_completion`-format text. The raw JSON gets auto-submitted as the "answer."
**Code location**: `loop.py` `_try_extract_completion()` and the text-only auto-submit path.
**Fix needed**: Detect non-completion tool JSON in text responses. Parse and dispatch as actual tool calls, or re-prompt the model to use the tool mechanism.

### Root Cause 3: No Error Recovery (1/9 failures)
**Task**: t07
**Symptom**: Model makes a typo in filename (`000_exec-approval_needed.md` vs `000_exec-approval-needed.md`), gets NOT_FOUND error, then stops.
**Code location**: General executor loop — no mechanism to detect "stuck" state after errors.
**Fix needed**: When a tool returns an error, inject a recovery hint (e.g., "The file was not found. Try listing the directory to find the correct filename.").

## Requirements

### 1. Empty Response Retry

**Description**: The executor loop shall detect empty LLM responses (no tool calls and no text content) and retry instead of silently exiting.

**Acceptance Criteria**:
- When the executor loop receives an LLM response that contains no tool calls and no text content (or only whitespace), the executor loop shall inject a nudge message into the conversation and continue to the next iteration instead of breaking.
- When the executor loop retries after an empty response, the executor loop shall increment a consecutive-empty-response counter.
- When the consecutive empty response counter reaches a configurable maximum (default: 3), the executor loop shall stop retrying and proceed to the empty-response fallback (Requirement 2).
- When the executor loop receives a non-empty response after one or more empty responses, the executor loop shall reset the consecutive empty response counter to zero.

### 2. Empty Response Fallback Submission

**Description**: When retry attempts for empty responses are exhausted, the executor loop shall submit a fallback completion rather than exiting silently.

**Acceptance Criteria**:
- When the consecutive empty response counter reaches the configured maximum, the executor loop shall call `report_completion` with outcome code `OUTCOME_ERR_INTERNAL` and an answer indicating that the model stopped responding.
- When the executor loop is in a verification cycle and the empty response retry limit is reached, the executor loop shall submit the captured original answer from the verification state instead of a generic fallback.

### 3. Text-as-Tool-Call Detection

**Description**: The executor loop shall detect when an LLM outputs tool-call-like JSON as plain text and recover by re-prompting the model.

**Acceptance Criteria**:
- When the executor loop receives a text-only response that contains a JSON object matching a known tool schema (by containing a key that corresponds to a required parameter of any available tool), the executor loop shall treat this as a malformed tool call rather than a text answer.
- When a malformed tool call is detected in a text response, the executor loop shall inject a corrective user message instructing the model to use the function calling mechanism, and continue to the next loop iteration.
- When the executor loop detects a malformed tool call, the executor loop shall not auto-submit the raw JSON text as an answer.
- When the executor loop re-prompts for a malformed tool call and the model responds with another text-based tool call, the executor loop shall count this toward a consecutive-text-tool-call counter (maximum: 2 re-prompts) to prevent infinite correction loops.

### 4. Text-Based report_completion Extraction

**Description**: The existing `_try_extract_completion()` function shall remain the first check for text-only responses, preserving backward compatibility.

**Acceptance Criteria**:
- When the executor loop receives a text-only response, the executor loop shall first attempt to extract a `report_completion` call from the text using `_try_extract_completion()` before checking for malformed tool calls.
- When `_try_extract_completion()` successfully extracts an answer, the executor loop shall proceed with the normal auto-submit or verification flow without triggering malformed-tool-call detection.

### 5. Error Recovery Hints

**Description**: The executor loop shall inject recovery hints after tool errors to help the model self-correct.

**Acceptance Criteria**:
- When a tool dispatch returns an error result containing a NOT_FOUND indicator (or equivalent file-system error), the executor loop shall append a recovery hint to the tool result message suggesting the model list the parent directory to find the correct path.
- When a tool dispatch returns any error result, the executor loop shall increment a consecutive-error counter for tracking stuck states.
- When the consecutive error counter reaches a configurable threshold (default: 3), the executor loop shall inject an escalated recovery message reminding the model of available tools and suggesting an alternative approach.
- When a tool dispatch returns a successful (non-error) result, the executor loop shall reset the consecutive error counter to zero.

### 6. Nudge Message Content

**Description**: Nudge and recovery messages shall be clear, concise, and model-agnostic.

**Acceptance Criteria**:
- When the executor loop injects an empty-response nudge, the nudge message shall instruct the model to continue working on the task using the available tools.
- When the executor loop injects a malformed-tool-call correction, the correction message shall include the detected tool name (if identifiable) and instruct the model to invoke it via the function calling mechanism.
- When the executor loop injects a file-not-found recovery hint, the hint shall suggest listing the parent directory and shall include the path that was not found.

### 7. No Latency Penalty for Strong Models

**Description**: Resilience mechanisms shall add zero overhead when the model behaves correctly.

**Acceptance Criteria**:
- When the LLM returns valid tool calls on every step, the executor loop shall not perform any additional LLM calls, string parsing, or message injections related to resilience handling.
- When the LLM returns valid text-only responses that pass `_try_extract_completion()` or are genuine text answers, the executor loop shall not trigger malformed-tool-call detection logic beyond lightweight JSON-key checking.

### 8. Observability and Logging

**Description**: All resilience interventions shall be logged for debugging and benchmark analysis.

**Acceptance Criteria**:
- When the executor loop retries after an empty response, the executor loop shall log a warning-level message including the step number and retry count.
- When the executor loop detects a malformed tool call in text, the executor loop shall log an info-level message including the detected tool name and the raw text snippet.
- When the executor loop injects an error recovery hint, the executor loop shall log an info-level message including the tool name, error type, and recovery action taken.
- When the executor loop submits a fallback completion due to empty-response exhaustion, the executor loop shall log a warning-level message indicating the fallback was triggered.

### 9. Existing Test Compatibility

**Description**: All resilience changes shall maintain backward compatibility with the existing test suite.

**Acceptance Criteria**:
- When the existing test suite is executed after resilience changes, all previously passing tests shall continue to pass without modification.
- When resilience features are tested, the tests shall use mock LLM responses to simulate weak model behaviors (empty responses, text-based tool calls, error sequences) without requiring an actual LLM.

### 10. Step Limit Integrity

**Description**: Resilience retry mechanisms shall operate within the existing 30-step executor limit.

**Acceptance Criteria**:
- When the executor loop retries after an empty response, each retry shall consume one step from the 30-step limit.
- When the executor loop re-prompts after a malformed tool call, each re-prompt shall consume one step from the 30-step limit.
- When the 30-step limit is reached regardless of the reason (retries, re-prompts, or normal execution), the executor loop shall exit as it does today.

### 11. Architecture Documentation Update

**Description**: Update `docs/agent-analysis.md` to reflect the new resilience mechanisms and close Weakness #1.

**Acceptance Criteria**:
- When the resilience features are implemented, `agent-analysis.md` Weakness #1 ("No Error Recovery or Re-Planning") shall be marked as addressed with references to the new mechanisms (empty response retry, text-as-tool detection, error recovery hints).
- When the resilience features are implemented, a new Strength entry shall be added documenting the weak-model resilience system: retry nudges, text-as-tool detection, error recovery hints, and their configurability.
- When the resilience features are implemented, the new Root Cause 2 (tool calls as plain text) shall be documented as a known model behavior pattern in the analysis, since it was not previously identified.
- When the resilience features are implemented, the Summary Scorecard "Error handling" rating shall be updated from "Moderate" to "Strong" with notes about the resilience mechanisms.

### 12. Configurable Retry Parameters

**Description**: All retry thresholds and nudge behavior shall be configurable via environment variables, consistent with the existing `ContextConfig` pattern.

**Acceptance Criteria**:
- When the empty response retry maximum needs to be adjusted, it shall be configurable via `RESILIENCE_EMPTY_RETRY_MAX` environment variable (default: 3).
- When the text-as-tool re-prompt maximum needs to be adjusted, it shall be configurable via `RESILIENCE_TEXT_TOOL_MAX` environment variable (default: 2).
- When the consecutive error threshold needs to be adjusted, it shall be configurable via `RESILIENCE_ERROR_THRESHOLD` environment variable (default: 3).
- When no environment variables are set, all resilience mechanisms shall use their default values and function without additional configuration.

### 13. Guaranteed Answer Submission

**Description**: The executor loop shall guarantee that `report_completion` is called before exiting, regardless of how the loop terminates.

**Acceptance Criteria**:
- When the executor loop exits for any reason (step limit reached, empty response exhaustion, or normal completion), the executor loop shall verify that `report_completion` was called at least once.
- When the executor loop exits without having called `report_completion`, it shall submit a fallback answer with `OUTCOME_ERR_INTERNAL` and a message describing why no answer was produced.
- When the executor loop exits during a verification cycle without a final submission, it shall submit the captured original answer from the verification state rather than a generic fallback.

### 14. Stuck Detection and Re-Planning

**Description**: The executor loop shall detect when the model is stuck (repeating actions or making no progress) and inject a re-planning prompt to redirect the model's approach.

**Acceptance Criteria**:
- When the executor loop detects that the same tool has been called 3 or more consecutive times with similar arguments, it shall inject a re-planning prompt asking the model to step back, summarize progress, and try a different approach.
- When the executor loop has completed N steps (configurable via `RESILIENCE_REPLAN_INTERVAL`, default: 8) without a `report_completion` call, it shall inject a periodic checkpoint prompt asking the model to summarize what has been accomplished and plan the remaining steps.
- When a re-planning prompt is injected, it shall include a summary of what the model has done so far (tools called, files read/written) to help the model reorient.
- When the model responds to a re-planning prompt, the stuck-detection counters shall be reset.
- When the re-planning mechanism is triggered, it shall consume one step from the 30-step limit.
- When the model is behaving correctly (diverse tool calls, making progress), the re-planning mechanism shall add zero overhead — no string comparisons or counter updates beyond lightweight step tracking.

### 15. Repetition Detection

**Description**: The executor loop shall track consecutive identical or near-identical tool calls to detect repetition loops.

**Acceptance Criteria**:
- When the executor loop dispatches a tool call, it shall record the tool name and a hash of the arguments in a rolling window (last 5 calls).
- When 3 or more entries in the rolling window have the same tool name and argument hash, the repetition detector shall flag the model as stuck.
- When the repetition detector flags a stuck state, the executor loop shall trigger the re-planning mechanism from Requirement 14.
- When a non-repeated tool call is dispatched, the repetition counter shall be reset.

### 16. Context Compaction as Recovery (s06 pattern)

**Description**: When the re-planning checkpoint (Req 14) is triggered, the executor loop shall trigger auto-compaction of the conversation context to force the model to re-read the task with a fresh perspective, following the s06 example agent pattern.

**Acceptance Criteria**:
- When a re-planning checkpoint is triggered (by repetition or stall), the executor loop shall trigger auto-compact (conversation summarization) before injecting the checkpoint prompt, so the model receives a clean summary + checkpoint in the same turn.
- When auto-compact is triggered for recovery, the transcript shall be saved to disk (same as threshold-triggered compaction) for audit purposes.
- When the model receives the post-compaction checkpoint, it shall see: [system prompt] + [compacted summary] + [checkpoint prompt asking to reassess], giving it a fresh start without losing critical context.

### 17. Tool Schema Reminder in Nudge Messages (s_full pattern)

**Description**: When nudge or recovery messages are injected, they shall include a brief summary of available tools, following the s_full.py pattern of re-injecting identity/context after compression.

**Acceptance Criteria**:
- When an empty-response nudge (Req 1) is injected, the nudge message shall include a brief list of available tool names to remind the model what actions it can take.
- When an error escalation (Req 5) is injected, the escalation message shall include available tool names.
- When a re-planning checkpoint (Req 14) is injected, the checkpoint shall NOT include tool names (the model should think about strategy, not tools).
