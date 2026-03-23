# Design: self-verification

> Pre-submission verification loop that intercepts report_completion to let the LLM double-check its answer against policy rules, verify file operations succeeded, and confirm answer format correctness before final submission. Targets improved accuracy for smaller/cheaper models that frequently produce near-correct but format-mismatched answers. Addresses weakness #9 (Single-Attempt Completion) from agent-analysis.md.

## Status: Generated

---

## 1. Architecture Overview

The self-verification feature introduces a verification sub-loop into the executor phase. When verification is enabled and the LLM attempts to submit an answer (via `report_completion` tool call or text-only auto-submit), the system intercepts the submission, injects a verification prompt into the conversation, and gives the LLM an opportunity to confirm or correct its answer before the harness receives it.

The feature follows the established pure-leaf-module pattern: `verify.py` provides pure functions and dataclasses (no agent/ imports), while `loop.py` orchestrates the verification flow.

```
                         +---------------------------------------------+
                         |               Executor Loop                 |
                         |               (loop.py)                     |
                         |                                             |
                         |  +---------------------------------------+  |
                         |  |  LLM responds with tool_calls         |  |
                         |  |                                       |  |
                         |  |  report_completion in tool_calls?     |  |
                         |  |    |-- no --> dispatch_parallel()     |  |
                         |  |    |-- yes                            |  |
                         |  |    v                                  |  |
                         |  |  should_verify(state, config)?        |  |
                         |  |    |-- no --> dispatch report_comp.   |  |
                         |  |    |-- yes                            |  |
                         |  |    v                                  |  |
                         |  |  PRE-FILTER report_completion out     |  |
                         |  |  dispatch remaining tool_calls        |  |
                         |  |  build_verification_prompt(answer,    |  |
                         |  |      code, policy_contents)           |  |
                         |  |  inject prompt as user message        |  |
                         |  |  state.attempts += 1                  |  |
                         |  |  continue loop (next LLM call)        |  |
                         |  +---------------------------------------+  |
                         |                                             |
                         |  +---------------------------------------+  |
                         |  |  LLM responds with text only           |  |
                         |  |  (auto-submit path)                    |  |
                         |  |                                        |  |
                         |  |  should_verify(state, config)?         |  |
                         |  |    |-- no --> auto-submit to harness   |  |
                         |  |    |-- yes                             |  |
                         |  |    v                                   |  |
                         |  |  build_verification_prompt(text,       |  |
                         |  |      "completed", policy_contents)     |  |
                         |  |  inject prompt as user message         |  |
                         |  |  state.attempts += 1                   |  |
                         |  |  continue loop (next LLM call)         |  |
                         |  +---------------------------------------+  |
                         |                                             |
                         +---------------------------------------------+

                         +---------------------------------------------+
                         |          verify.py (new leaf module)         |
                         |                                              |
                         |  Pure functions, no agent/ imports:           |
                         |  - VerificationState (dataclass)              |
                         |  - should_verify(state, config) -> bool       |
                         |  - build_verification_prompt(answer, code,    |
                         |        policy_contents) -> str                |
                         |  - detect_verification_outcome(old_answer,    |
                         |        new_answer) -> VerificationOutcome     |
                         +---------------------------------------------+

                         +---------------------------------------------+
                         |       context.py (modified: 2 new fields)    |
                         |                                              |
                         |  ContextConfig:                               |
                         |    ...existing fields...                      |
                         |    verification_enabled: bool = False          |
                         |    verification_max_attempts: int = 2          |
                         +---------------------------------------------+
```

### Module Dependency Update

```
main.py -> agent/loop.py (orchestrator)
             |-- verify.py           (NEW leaf -- no agent/ imports)
             |-- context.py          (MODIFIED: 2 new optional fields)
             |-- scout.py  -> llm.py, dispatch.py, tracker.py, tools.py, prompt.py, context.py
             |-- llm.py              (leaf, unchanged)
             |-- dispatch.py         (leaf, unchanged)
             |-- prompt.py           (leaf, unchanged)
             |-- skills.py           (leaf, unchanged)
             |-- tracker.py          (leaf, unchanged)
             |-- tools.py            (leaf, unchanged)
             +-- observability.py    (leaf, unchanged)
```

`verify.py` is a **pure leaf module** with zero imports from other `agent/` modules. It provides pure functions and dataclasses only. All orchestration (intercepting report_completion, managing the verification sub-loop, dispatching non-verification tool calls) remains in `loop.py`.

---

## 2. Component Design

### 2.1 Component: `agent/verify.py` (New Module)

**Purpose**: Pure functions for verification state management, prompt construction, and outcome detection. Dataclass for tracking verification state within a single task execution.

**Traceability**: Req 1, 2, 3, 4, 6

#### 2.1.1 `VerificationState` Dataclass

```
@dataclass
class VerificationState:
    in_verification: bool           # True when a verification cycle is active
    attempts: int                   # Number of verification cycles completed so far
    original_answer: str            # The first proposed answer (before any verification)
    original_code: str              # The completion code from the first proposal
```

**Defaults**: `in_verification=False`, `attempts=0`, `original_answer=""`, `original_code=""`.

Created once per `run_agent()` invocation at executor loop initialization. Mutated by `loop.py` as verification cycles proceed. The `original_answer` and `original_code` are captured from the first intercepted `report_completion` call to enable answer comparison logging (Req 6.2, 6.3).

#### 2.1.2 `VerificationOutcome` Enum

```
class VerificationOutcome(str, Enum):
    CONFIRMED = "confirmed"
    REVISED = "revised"
```

Used by `detect_verification_outcome()` to classify the result of a verification cycle for logging purposes.

#### 2.1.3 `should_verify(state: VerificationState, verification_enabled: bool, verification_max_attempts: int) -> bool`

**Traceability**: Req 1.1, 1.2, 4.1, 4.2, 5.1, 5.3

Pure function. Returns `True` when all of the following hold:

1. `verification_enabled` is `True` (Req 1.2, 5.1)
2. `state.attempts < verification_max_attempts` (Req 4.1, 4.2)

Returns `False` otherwise. When `False`, the caller dispatches the answer directly to the harness.

Note: This function is intentionally decoupled from `ContextConfig` -- it receives the two configuration values as plain parameters. This keeps the verify module independent of context.py (zero agent/ imports). The caller (`loop.py`) extracts these values from `ContextConfig`.

**Parameters**:
- `state: VerificationState` -- Current verification state.
- `verification_enabled: bool` -- Whether the feature is enabled.
- `verification_max_attempts: int` -- Maximum verification attempts allowed.

**Returns**: `bool`.

#### 2.1.4 `build_verification_prompt(answer: str, code: str, policy_contents: dict[str, str]) -> str`

**Traceability**: Req 2.1, 2.2, 2.3, 2.4, 2.5

Pure function. Constructs the verification prompt injected as a user message into the conversation.

The prompt includes:

1. **Proposed answer and code** (Req 2.1): The answer and completion code are embedded verbatim so the LLM can review them.
2. **Policy file contents** (Req 2.2): Each policy file path and its full content are included directly in the prompt. This saves LLM steps (no need to re-read files) at the cost of tokens. The policy contents are sourced from the scout summary's `policy_files` dict, which `loop.py` already has access to.
3. **File operation verification instruction** (Req 2.3): The prompt instructs the LLM to use `read_file` or `list_dir` to confirm that any file operations it performed (writes, deletes) were successful.
4. **Format correctness instruction** (Req 2.4): The prompt instructs the LLM to verify exact format correctness -- casing, whitespace, punctuation, and code values defined by policies.
5. **Grounding reference check instruction** (Req 2.5): The prompt instructs the LLM to verify that all grounding references are accurate and complete (no missing files, no non-existent paths).
6. **Submission instruction**: The prompt instructs the LLM to call `report_completion` with either the original answer (if correct) or a corrected answer.

**Prompt structure**:

```
<verification>
You are about to submit the following answer. Before submitting, verify it is correct.

## Proposed Answer
Code: {code}
Answer: {answer}

## Policy Files
{for each path, content in policy_contents:}
### {path}
{content}

## Verification Checklist
1. Re-read the policy files above. Does the answer comply with ALL format rules (exact casing, whitespace, punctuation, response codes)?
2. If you performed file operations (write_file, delete_file), verify they succeeded by re-reading or listing the affected paths.
3. Check that all grounding references point to files that actually exist.
4. Verify the answer is complete and addresses the full task requirement.

## Instructions
- If the answer is correct, call report_completion with the SAME answer and code.
- If the answer needs correction, call report_completion with the CORRECTED answer.
- You may use tools (read_file, list_dir, etc.) to verify file operations before submitting.
</verification>
```

**Parameters**:
- `answer: str` -- The proposed answer text.
- `code: str` -- The proposed completion code ("completed" or "failed").
- `policy_contents: dict[str, str]` -- Map of policy file paths to their content (from scout summary).

**Returns**: `str` -- The complete verification prompt.

#### 2.1.5 `detect_verification_outcome(original_answer: str, new_answer: str) -> VerificationOutcome`

**Traceability**: Req 6.2, 6.3

Pure function. Compares the original proposed answer with the verified answer using exact string match (as specified in the gap analysis). Returns `VerificationOutcome.CONFIRMED` if the answers are identical, `VerificationOutcome.REVISED` otherwise.

**Parameters**:
- `original_answer: str` -- The answer from the first `report_completion` call.
- `new_answer: str` -- The answer from the post-verification `report_completion` call.

**Returns**: `VerificationOutcome`.

---

### 2.2 Component: `agent/context.py` (Modified)

**Purpose**: Extend `ContextConfig` with two new optional fields for verification configuration.

**Traceability**: Req 5.1, 5.2, 7.2

#### 2.2.1 New Fields on `ContextConfig`

```
@dataclass
class ContextConfig:
    # ...existing fields...
    truncation_limit: int = 10_000
    micro_compact_keep_batches: int = 3
    micro_compact_min_length: int = 100
    auto_compact_threshold: int = 80_000
    transcript_dir: str = ".transcripts/"

    # NEW: Verification configuration (Req 5.1, 5.2)
    verification_enabled: bool = False
    verification_max_attempts: int = 2
```

**Defaults**: `verification_enabled=False` (disabled by default, Req 5.1), `verification_max_attempts=2` (Req 4.1).

#### 2.2.2 Updated `from_env()` Factory Method

Two new environment variable mappings added to `from_env()`:

- `VERIFY_ENABLED` -> `verification_enabled` (parsed as truthy: `"1"`, `"true"`, `"yes"` -> `True`; default: `False`)
- `VERIFY_MAX_ATTEMPTS` -> `verification_max_attempts` (parsed as `int`; default: `2`)

```
@classmethod
def from_env(cls) -> ContextConfig:
    return cls(
        # ...existing fields...
        verification_enabled=os.environ.get("VERIFY_ENABLED", "").lower() in ("1", "true", "yes"),
        verification_max_attempts=int(os.environ.get("VERIFY_MAX_ATTEMPTS", "2")),
    )
```

**No existing function signatures are modified** (Req 7.2). The two new fields are optional with defaults, so all existing callers of `ContextConfig()` and `ContextConfig.from_env()` continue to work without changes.

---

### 2.3 Component: `agent/loop.py` (Modified)

**Purpose**: Orchestrate the verification sub-loop by intercepting `report_completion` and text-only auto-submit paths. Manage verification state and logging.

**Traceability**: Req 1.1, 1.2, 1.3, 3.1, 3.2, 3.3, 3.4, 4.2, 4.3, 6.1, 6.2, 6.3, 6.4, 7.1

#### 2.3.1 Initialization in `run_agent()`

At the top of the executor phase (after existing initialization), import and create verification state:

```python
from agent.verify import (
    VerificationState,
    VerificationOutcome,
    should_verify,
    build_verification_prompt,
    detect_verification_outcome,
)

verification_state = VerificationState()
```

The `policy_contents` for verification prompts are sourced from `summary.policy_files` (the scout summary dict already available in scope).

#### 2.3.2 Interception Point 1: `report_completion` in Tool Calls

The current code path dispatches all tool calls (including `report_completion`) via `dispatch_parallel()`, which immediately sends the answer to the harness. The verification feature must intercept `report_completion` **before** dispatch.

Modified flow within the executor loop's tool-call handling section:

```python
if response.tool_calls:
    # --- VERIFICATION INTERCEPTION (Req 1.1) ---
    # Separate report_completion from other tool calls
    completion_tc = None
    other_tool_calls = []
    for tc in response.tool_calls:
        if tc.name == "report_completion":
            completion_tc = tc
        else:
            other_tool_calls.append(tc)

    # Dispatch non-completion tool calls (may be empty)
    if other_tool_calls:
        results = dispatch_parallel(
            vm, other_tool_calls, tracker, protected_files, skill_loader,
            context_config=context_config,
        )
        # Append tool results to messages
        for tool_call_id, result_text in results:
            # ...existing result handling (sentinel detection, etc.)...

    if completion_tc is not None:
        answer = completion_tc.arguments.get("answer", "")
        code = completion_tc.arguments.get("code", "completed")

        if should_verify(verification_state, context_config.verification_enabled,
                         context_config.verification_max_attempts):
            # INTERCEPT: initiate verification cycle
            if not verification_state.in_verification:
                verification_state.original_answer = answer
                verification_state.original_code = code
            verification_state.in_verification = True
            verification_state.attempts += 1

            # Log verification start (Req 6.1)
            answer_preview = answer[:120]
            print(f"  [verify] attempt {verification_state.attempts}: "
                  f"intercepted report_completion, answer preview: {answer_preview}")
            log.info("Verification attempt %d: intercepted report_completion",
                     verification_state.attempts)

            # Build and inject verification prompt (Req 2.1-2.5)
            prompt = build_verification_prompt(
                answer, code, summary.policy_files,
            )

            # Append a synthetic tool result for report_completion
            # (required to maintain valid message sequence for the LLM API)
            messages.append({
                "role": "tool",
                "tool_call_id": completion_tc.id,
                "content": "[Verification in progress -- answer held for review]",
            })

            # Inject verification prompt as user message
            messages.append({
                "role": "user",
                "content": prompt,
            })

            continue  # Next iteration of executor loop
        else:
            # Dispatch report_completion normally (Req 1.2, 4.2)
            # (verification disabled OR max attempts reached)
            dispatch_tool(
                vm, "report_completion", completion_tc.arguments,
                tracker, protected_files, skill_loader,
                context_config=context_config,
            )
            # Append tool result message
            messages.append({
                "role": "tool",
                "tool_call_id": completion_tc.id,
                "content": '{"status": "submitted"}',
            })

            # Log verification outcome if we were in a verification cycle
            if verification_state.in_verification:
                outcome = detect_verification_outcome(
                    verification_state.original_answer, answer
                )
                if outcome == VerificationOutcome.CONFIRMED:
                    print(f"  [verify] answer CONFIRMED after "
                          f"{verification_state.attempts} attempt(s)")
                    log.info("Verification: answer confirmed (unchanged)")
                else:
                    orig_preview = verification_state.original_answer[:80]
                    new_preview = answer[:80]
                    print(f"  [verify] answer REVISED after "
                          f"{verification_state.attempts} attempt(s)")
                    print(f"    original: {orig_preview}")
                    print(f"    revised:  {new_preview}")
                    log.info("Verification: answer revised. "
                             "original=%r, revised=%r",
                             orig_preview, new_preview)

            completion_called = True
            # ...existing completion logging...
```

**Key design point**: `report_completion` is PRE-FILTERED out of the tool_calls list before `dispatch_parallel()` is invoked. This prevents the harness from receiving the answer prematurely. Other tool calls in the same response are dispatched normally.

#### 2.3.3 Interception Point 2: Text-Only Auto-Submit

The current code auto-submits the LLM's text content when no tool calls are present. The verification feature intercepts this path as well.

Modified flow:

```python
if not response.tool_calls:
    if response.content and response.content.strip():
        text_answer = response.content.strip()

        if should_verify(verification_state, context_config.verification_enabled,
                         context_config.verification_max_attempts):
            # INTERCEPT: initiate verification for text-only response
            if not verification_state.in_verification:
                verification_state.original_answer = text_answer
                verification_state.original_code = "completed"
            verification_state.in_verification = True
            verification_state.attempts += 1

            # Log verification start (Req 6.1)
            print(f"  [verify] attempt {verification_state.attempts}: "
                  f"intercepted text-only auto-submit")
            log.info("Verification attempt %d: intercepted text-only auto-submit",
                     verification_state.attempts)

            # Build and inject verification prompt
            prompt = build_verification_prompt(
                text_answer, "completed", summary.policy_files,
            )
            messages.append({
                "role": "user",
                "content": prompt,
            })

            continue  # Next iteration of executor loop
        else:
            # Auto-submit normally (Req 1.2)
            dispatch_tool(
                vm, "report_completion",
                {"answer": text_answer, "grounding_refs": [],
                 "steps": [], "code": "completed"},
                tracker, protected_files, skill_loader,
                context_config=context_config,
            )

            # Log verification outcome if applicable
            if verification_state.in_verification:
                outcome = detect_verification_outcome(
                    verification_state.original_answer, text_answer
                )
                # ...same logging as 2.3.2...

            fallback_refs = tracker.merge([])
            print(f"  Auto-submitted answer: {text_answer[:120]}")
            break
```

#### 2.3.4 Verification Steps Count Against Executor Limit

No additional changes are needed for Req 3.4. The existing `for step in range(30)` loop naturally counts verification iterations as regular steps. Each verification cycle uses one or more iterations of this loop (the verification prompt injection followed by the LLM's response). This means verification steps are automatically bounded by the 30-step executor limit.

#### 2.3.5 Tool Use During Verification (Req 3.2)

When the LLM uses tools (e.g., `read_file`, `list_dir`) during a verification cycle (i.e., `verification_state.in_verification is True`), those tool calls flow through the normal dispatch path. The only tool call that receives special treatment is `report_completion`, which triggers the verification outcome logic (section 2.3.2). All other tools are dispatched normally during verification, allowing the LLM to re-read files and verify operations.

---

## 3. Interface Contracts

### 3.1 `verify.py` Public Interface

```
class VerificationOutcome(str, Enum):
    CONFIRMED = "confirmed"
    REVISED = "revised"

@dataclass
class VerificationState:
    in_verification: bool = False
    attempts: int = 0
    original_answer: str = ""
    original_code: str = ""

def should_verify(
    state: VerificationState,
    verification_enabled: bool,
    verification_max_attempts: int,
) -> bool: ...

def build_verification_prompt(
    answer: str,
    code: str,
    policy_contents: dict[str, str],
) -> str: ...

def detect_verification_outcome(
    original_answer: str,
    new_answer: str,
) -> VerificationOutcome: ...
```

### 3.2 Modified `ContextConfig` (in `context.py`)

```
@dataclass
class ContextConfig:
    truncation_limit: int = 10_000
    micro_compact_keep_batches: int = 3
    micro_compact_min_length: int = 100
    auto_compact_threshold: int = 80_000
    transcript_dir: str = ".transcripts/"
    verification_enabled: bool = False                 # NEW
    verification_max_attempts: int = 2                 # NEW

    @classmethod
    def from_env(cls) -> ContextConfig: ...
```

### 3.3 Unchanged Signatures

The following function signatures remain **unchanged** (Req 7.2):

- `dispatch_tool()` in `dispatch.py`
- `dispatch_parallel()` in `dispatch.py`
- `build_system_prompt()` in `prompt.py`
- `run_scout()` in `scout.py`
- All functions in `tools.py`

---

## 4. Data Flow

### 4.1 Verification Interception Flow (report_completion Path)

```
LLM response includes tool_calls: [report_completion, ...]
    |
    v
Separate report_completion from other tool_calls
    |
    v
Dispatch other tool_calls via dispatch_parallel()
    |
    v
should_verify(state, config.verification_enabled,
              config.verification_max_attempts)?
    |-- no --> dispatch report_completion to harness
    |          (log verification outcome if in_verification)
    |          break loop
    |-- yes
    v
Capture answer and code from report_completion args
    |
    v
First verification? (state.in_verification == False)
    |-- yes --> state.original_answer = answer
    |-- no  --> (already captured)
    |
    v
state.in_verification = True
state.attempts += 1
    |
    v
Log: "[verify] attempt N: intercepted report_completion"
    |
    v
build_verification_prompt(answer, code, policy_contents)
    |
    v
Append synthetic tool result for report_completion
Append verification prompt as user message
    |
    v
continue (next executor loop iteration -> call_llm)
```

### 4.2 Verification Interception Flow (Text-Only Auto-Submit Path)

```
LLM response has no tool_calls, content is non-empty
    |
    v
should_verify(state, config.verification_enabled,
              config.verification_max_attempts)?
    |-- no --> auto-submit text to harness
    |          (log verification outcome if in_verification)
    |          break loop
    |-- yes
    v
Capture text as answer, code = "completed"
    |
    v
First verification? -> capture original_answer
state.in_verification = True
state.attempts += 1
    |
    v
Log: "[verify] attempt N: intercepted text-only auto-submit"
    |
    v
build_verification_prompt(text, "completed", policy_contents)
    |
    v
Append verification prompt as user message
    |
    v
continue (next executor loop iteration -> call_llm)
```

### 4.3 Verification Cycle During Execution

```
[Normal executor step]
    |
    v
call_llm() with verification prompt in messages
    |
    v
LLM responds:
    |
    |-- tool_calls with report_completion
    |   --> Re-enter flow 4.1 (may intercept again or dispatch)
    |
    |-- tool_calls without report_completion
    |   --> Dispatch tools normally (e.g., read_file to verify)
    |       Continue loop for next LLM call
    |
    |-- text only (no tool_calls)
    |   --> Re-enter flow 4.2 (may intercept again or dispatch)
```

### 4.4 Verification Disabled Flow

```
report_completion or text-only response
    |
    v
should_verify() returns False
    (verification_enabled == False)
    |
    v
Dispatch directly to harness (identical to current behavior)
```

---

## 5. Key Design Decisions

### 5.1 Pure Leaf Module (`verify.py`)

**Decision**: All verification pure functions live in a single new leaf module `verify.py` with zero imports from other `agent/` modules.

**Rationale**: Follows the established architecture pattern used by `context.py`, `tracker.py`, `tools.py`, and other leaf modules. Pure functions are testable with plain values (strings, dicts, dataclasses) without any mocking. The `should_verify()` function receives configuration values as plain parameters rather than importing `ContextConfig` from `context.py`, maintaining strict zero-dependency isolation.

**Traceability**: Architectural constraint from agent-analysis.md Section "Architecture Overview"; matches `context.py` design from the context-management specification.

### 5.2 Pre-Filter report_completion Before dispatch_parallel

**Decision**: `report_completion` is extracted from the tool_calls list before `dispatch_parallel()` is invoked. Other tool calls in the same response are dispatched normally.

**Rationale**: `dispatch_parallel()` sends `report_completion` to the harness immediately via the VM `answer()` RPC. Once sent, the answer cannot be retracted. Pre-filtering ensures the answer is held for verification while other tool calls (which may include file operations the LLM wants to perform alongside submission) are still executed. This is critical because some LLMs batch `report_completion` with other tool calls in a single response.

**Traceability**: Gap analysis key context item #2.

### 5.3 Configuration on ContextConfig (Not Separate Dataclass)

**Decision**: Verification configuration (`verification_enabled`, `verification_max_attempts`) is added as two new optional fields on the existing `ContextConfig` dataclass rather than creating a separate `VerificationConfig`.

**Rationale**: Follows the established pattern where `ContextConfig.from_env()` is the single configuration entry point in `run_agent()`. Adding fields with defaults preserves backward compatibility -- existing code that constructs `ContextConfig()` without these fields continues to work. The two fields are simple and do not warrant a separate dataclass with its own `from_env()` method.

**Traceability**: Gap analysis key context item #3; Req 5.1, 5.2.

### 5.4 Policy Contents Embedded in Verification Prompt (Not Re-Read)

**Decision**: The verification prompt includes policy file contents directly from the scout summary's `policy_files` dict, rather than instructing the LLM to re-read them.

**Rationale**: Re-reading policy files would cost 1+ tool-use steps per verification cycle (each counting against the 30-step limit). Including the content inline costs tokens but saves steps and ensures the LLM has the policies immediately available. The policy files are already in memory (they were read during the scout phase and are stored in `summary.policy_files`).

**Traceability**: Gap analysis key context item #5; Req 2.2.

### 5.5 Exact String Match for Answer Comparison

**Decision**: `detect_verification_outcome()` uses exact string equality (`==`) to determine whether the answer was confirmed or revised.

**Rationale**: Fuzzy matching would introduce ambiguity in logging. The comparison is used purely for observability (logging whether the answer changed), not for decision-making. Exact match is simple, deterministic, and sufficient for the stated purpose.

**Traceability**: Gap analysis key context item #6; Req 6.2, 6.3.

### 5.6 Synthetic Tool Result for Intercepted report_completion

**Decision**: When `report_completion` is intercepted (not dispatched), a synthetic tool result message is appended to the messages list with content `"[Verification in progress -- answer held for review]"`.

**Rationale**: The OpenAI-compatible messages API requires that every tool_call in an assistant message has a corresponding tool result message. If `report_completion` is called alongside other tools, omitting its result would break the message sequence. The synthetic result maintains API validity while signaling to the LLM that its submission was not yet sent.

### 5.7 Verification Steps Use Existing Executor Limit

**Decision**: Verification cycles count against the existing 30-step executor limit. No separate verification step counter is needed for bounding.

**Rationale**: The `verification_max_attempts` config bounds the number of verification cycles (default: 2). Each cycle consumes at least 1 step of the 30-step loop. This provides defense in depth: `verification_max_attempts` prevents unbounded re-verification, while the 30-step limit prevents unbounded total execution regardless of verification.

**Traceability**: Req 3.4; gap analysis key context item #4.

---

## 6. Observability Integration

### 6.1 Logging

| Event | Level | Fields | Req |
|-------|-------|--------|-----|
| Verification cycle begins | INFO | attempt_number, answer_preview (truncated to 120 chars) | 6.1 |
| Verification: answer confirmed | INFO | attempt_count | 6.2 |
| Verification: answer revised | INFO | original_preview, revised_preview (truncated to 80 chars each) | 6.3 |
| Verification interception (text-only) | INFO | attempt_number | 6.1 |

All logging uses the standard `logging` module via `log = logging.getLogger(__name__)` and `print()`-based console output, consistent with the existing patterns in `loop.py` (Req 6.4).

### 6.2 Console Output

Verification events are printed with the `[verify]` tag prefix for easy grep-ability:

```
  [verify] attempt 1: intercepted report_completion, answer preview: TODO
  [verify] answer CONFIRMED after 1 attempt(s)
```

or:

```
  [verify] attempt 1: intercepted report_completion, answer preview: TODO
  [verify] answer REVISED after 1 attempt(s)
    original: TODO
    revised:  TBD
```

---

## 7. Error Handling

### 7.1 Verification Prompt Construction

`build_verification_prompt()` is a pure string formatting function. It cannot fail (empty `policy_contents` dict simply omits the policy section). No error handling needed.

### 7.2 Verification State Consistency

The `VerificationState` dataclass is created once per `run_agent()` call and is only mutated by `loop.py` within the executor loop. There is no concurrency concern since the executor loop is single-threaded.

### 7.3 LLM Does Not Call report_completion After Verification

If the LLM responds to the verification prompt with text only (no tool calls) and does not call `report_completion`, the text-only auto-submit path handles it (section 2.3.3, Req 3.3). If the LLM responds with tool calls but none are `report_completion`, tools are dispatched normally and the loop continues (Req 3.2). The 30-step executor limit ensures termination.

### 7.4 Empty Policy Files

If `summary.policy_files` is empty (no policy files discovered during scout), the verification prompt omits the policy section. The verification cycle still provides value by prompting the LLM to re-examine format correctness and file operations.

---

## 8. Testing Strategy

### 8.1 Unit Tests: `tests/test_verify.py` (New)

Test `verify.py` pure functions with plain values -- no mocking required.

| Test | Covers |
|------|--------|
| `test_verification_state_defaults` | VerificationState default values |
| `test_should_verify_enabled_under_limit` | Req 1.1, 5.1 -- returns True when enabled and attempts < max |
| `test_should_verify_disabled` | Req 1.2, 5.3 -- returns False when disabled |
| `test_should_verify_at_max_attempts` | Req 4.1, 4.2 -- returns False when attempts >= max |
| `test_should_verify_at_zero_max` | Edge: max_attempts=0 always returns False |
| `test_build_verification_prompt_includes_answer` | Req 2.1 -- answer and code in prompt |
| `test_build_verification_prompt_includes_policies` | Req 2.2 -- policy contents in prompt |
| `test_build_verification_prompt_empty_policies` | Req 2.2 -- graceful with empty dict |
| `test_build_verification_prompt_includes_checklist` | Req 2.3, 2.4, 2.5 -- checklist items |
| `test_detect_outcome_confirmed` | Req 6.2 -- same answer returns CONFIRMED |
| `test_detect_outcome_revised` | Req 6.3 -- different answer returns REVISED |
| `test_detect_outcome_empty_strings` | Edge: both empty returns CONFIRMED |
| `test_detect_outcome_whitespace_difference` | Whitespace-only change returns REVISED |

### 8.2 Unit Tests: `tests/test_context.py` (Extended)

| Test | Covers |
|------|--------|
| `test_context_config_verification_defaults` | Req 5.1 -- verification_enabled=False, max_attempts=2 |
| `test_context_config_from_env_verification_enabled` | Req 5.1 -- VERIFY_ENABLED env var |
| `test_context_config_from_env_verification_max_attempts` | Req 5.2 -- VERIFY_MAX_ATTEMPTS env var |
| `test_context_config_backward_compat` | Req 7.2 -- existing construction still works |

### 8.3 Unit Tests: `tests/test_loop.py` (Extended)

| Test | Covers |
|------|--------|
| `test_verification_intercepts_report_completion` | Req 1.1 -- report_completion held when verification enabled |
| `test_verification_disabled_dispatches_immediately` | Req 1.2 -- no interception when disabled |
| `test_verification_intercepts_text_only_autosubmit` | Req 1.3 -- text-only path intercepted |
| `test_verification_dispatches_other_tools_during_intercept` | Req 3.2 -- non-completion tools dispatched |
| `test_verification_max_attempts_then_dispatch` | Req 4.2 -- dispatched after max attempts reached |
| `test_verification_steps_count_against_limit` | Req 3.4 -- 30-step limit applies |
| `test_verification_outcome_confirmed_log` | Req 6.2 -- confirmed answer logged |
| `test_verification_outcome_revised_log` | Req 6.3 -- revised answer logged |
| `test_existing_tests_pass_with_verification_disabled` | Req 7.1, 7.4 -- backward compat |

---

## 9. Requirements Traceability Matrix

| Req | Component(s) | Section |
|-----|-------------|---------|
| 1.1 | loop.py interception of report_completion; verify.py `should_verify()` | 2.3.2, 4.1 |
| 1.2 | loop.py bypass when disabled; verify.py `should_verify()` | 2.3.2, 4.4 |
| 1.3 | loop.py interception of text-only auto-submit | 2.3.3, 4.2 |
| 2.1 | verify.py `build_verification_prompt()` -- answer and code | 2.1.4 |
| 2.2 | verify.py `build_verification_prompt()` -- policy contents | 2.1.4, 5.4 |
| 2.3 | verify.py `build_verification_prompt()` -- file operation check | 2.1.4 |
| 2.4 | verify.py `build_verification_prompt()` -- format correctness | 2.1.4 |
| 2.5 | verify.py `build_verification_prompt()` -- grounding refs | 2.1.4 |
| 3.1 | loop.py dispatches verified answer via report_completion | 2.3.2 |
| 3.2 | loop.py dispatches non-completion tools normally during verification | 2.3.5 |
| 3.3 | loop.py text-only auto-submit during verification cycle | 2.3.3 |
| 3.4 | loop.py 30-step executor limit encompasses verification | 2.3.4, 5.7 |
| 4.1 | verify.py `should_verify()` max attempts check; ContextConfig default=2 | 2.1.3, 2.2.1 |
| 4.2 | loop.py dispatches when max attempts reached | 2.3.2 |
| 4.3 | loop.py auto-submits text when max attempts reached | 2.3.3 |
| 5.1 | context.py `ContextConfig.verification_enabled` + `from_env()` | 2.2.1, 2.2.2 |
| 5.2 | context.py `ContextConfig.verification_max_attempts` + `from_env()` | 2.2.1, 2.2.2 |
| 5.3 | verify.py `should_verify()` returns False when disabled; zero overhead | 2.1.3, 5.1 |
| 6.1 | loop.py prints and logs verification start with answer preview | 2.3.2, 2.3.3, 6.1 |
| 6.2 | loop.py logs confirmed outcome; verify.py `detect_verification_outcome()` | 2.3.2, 2.1.5, 6.1 |
| 6.3 | loop.py logs revised outcome with original/corrected previews | 2.3.2, 2.1.5, 6.1 |
| 6.4 | loop.py uses `logging` module and `print()` pattern | 6.1, 6.2 |
| 7.1 | loop.py identical message sequences when verification disabled | 2.3.2, 2.3.3, 4.4 |
| 7.2 | No existing function signatures modified in dispatch, tools, prompt, context | 3.3 |
| 7.3 | verify.py uses only Python standard library | 2.1 |
| 7.4 | Existing tests pass with verification_enabled=False (default) | 8.2, 8.3 |

---

## 10. Files Changed

| File | Action | Description |
|------|--------|-------------|
| `sandbox/py/agent/verify.py` | **Create** | New leaf module: `VerificationState`, `VerificationOutcome`, `should_verify()`, `build_verification_prompt()`, `detect_verification_outcome()` |
| `sandbox/py/agent/context.py` | **Modify** | Add `verification_enabled` and `verification_max_attempts` fields to `ContextConfig`; update `from_env()` with `VERIFY_ENABLED` and `VERIFY_MAX_ATTEMPTS` env vars |
| `sandbox/py/agent/loop.py` | **Modify** | Import verify.py; create `VerificationState`; intercept `report_completion` pre-filter before dispatch; intercept text-only auto-submit; manage verification state and logging |
| `sandbox/py/.env.example` | **Modify** | Add verification environment variable documentation (`VERIFY_ENABLED`, `VERIFY_MAX_ATTEMPTS`) |
| `sandbox/py/tests/test_verify.py` | **Create** | Unit tests for all `verify.py` functions |
| `sandbox/py/tests/test_context.py` | **Modify** | Add tests for new `ContextConfig` verification fields and `from_env()` |
| `sandbox/py/tests/test_loop.py` | **Modify** | Add tests for verification interception, outcome logging, backward compatibility |
