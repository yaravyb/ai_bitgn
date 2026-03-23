# Tasks: self-verification

> Pre-submission verification loop that intercepts report_completion to let the LLM double-check its answer against policy rules, verify file operations succeeded, and confirm answer format correctness before final submission.

## Task 1: Extend `ContextConfig` with verification fields in `agent/context.py` [x]

Add two new optional fields to the `ContextConfig` dataclass: `verification_enabled: bool = False` and `verification_max_attempts: int = 2`. Update the `from_env()` factory method to read `VERIFY_ENABLED` (truthy: `"1"`, `"true"`, `"yes"`) and `VERIFY_MAX_ATTEMPTS` (int, default 2) from environment variables. Both fields must have defaults so all existing callers continue to work without modification.

**Requirements**: 5

## Task 2: Create `agent/verify.py` with `VerificationState`, `VerificationOutcome`, and `should_verify` [x]

Create the new pure leaf module `sandbox/py/agent/verify.py` with zero imports from other `agent/` modules. Implement the `VerificationState` dataclass (fields: `in_verification=False`, `attempts=0`, `original_answer=""`, `original_code=""`), the `VerificationOutcome` string enum (`CONFIRMED`, `REVISED`), and the `should_verify(state, verification_enabled, verification_max_attempts)` pure function that returns `True` only when verification is enabled and attempts are below the maximum.

**Requirements**: 1, 4, 5

## Task 3: Implement `build_verification_prompt` in `agent/verify.py` [x]

Add the `build_verification_prompt(answer, code, policy_contents)` pure function to `verify.py`. The prompt must include the proposed answer and completion code verbatim, embed all policy file contents from the scout summary dict (each with path heading and full content), and present a verification checklist covering: policy format compliance, file operation success verification, grounding reference accuracy, and answer completeness. Include submission instructions directing the LLM to call `report_completion` with the same or corrected answer. Handle empty `policy_contents` gracefully by omitting the policy section.

**Requirements**: 2

## Task 4: Implement `detect_verification_outcome` in `agent/verify.py` (P) [x]

Add the `detect_verification_outcome(original_answer, new_answer)` pure function to `verify.py`. Compare the two answers using exact string equality: return `VerificationOutcome.CONFIRMED` if identical, `VerificationOutcome.REVISED` otherwise. This function is used purely for logging purposes.

**Requirements**: 3, 6

## Task 5: Unit tests for `verify.py` pure functions (P) [x]

Create `sandbox/py/tests/test_verify.py` with tests covering: `VerificationState` default values, `should_verify` (enabled and under limit returns True, disabled returns False, at max attempts returns False, zero max always returns False), `build_verification_prompt` (answer and code included, policy contents included, empty policies handled, checklist items present), `detect_verification_outcome` (same answer returns CONFIRMED, different answer returns REVISED, both empty returns CONFIRMED, whitespace-only difference returns REVISED). All tests use plain values with no mocking required. Run with `cd sandbox/py && uv run pytest tests/test_verify.py -x -v`.

**Requirements**: 1, 2, 3, 4, 6

## Task 6: Integrate verification interception into the executor loop in `agent/loop.py` [x]

Modify `run_agent()` in `loop.py` to import `verify.py` functions and create a `VerificationState` at executor loop initialization. Implement both interception points: (1) pre-filter `report_completion` from tool_calls before `dispatch_parallel()`, dispatch remaining tools normally, then check `should_verify()` to either initiate a verification cycle or dispatch `report_completion` to the harness; (2) intercept text-only auto-submit responses when `should_verify()` returns True. When intercepting, capture the original answer on first verification, increment attempts, build the verification prompt from `summary.policy_files`, append a synthetic tool result for `report_completion` (to maintain valid message sequence), inject the verification prompt as a user message, and continue the loop. Verification steps count against the existing 30-step executor limit with no additional changes needed. Allow normal tool use (read_file, list_dir, etc.) during verification cycles by dispatching non-completion tool calls through the standard path.

**Requirements**: 1, 3, 4

### Task 6.1: Implement `report_completion` pre-filter and verification interception in the tool-call path

Separate `report_completion` from other tool calls in the response. Dispatch non-completion tool calls via `dispatch_parallel()`. When `should_verify()` returns True, capture answer/code, set verification state, build and inject the verification prompt with synthetic tool result, and continue the loop. When False, dispatch `report_completion` normally to the harness.

### Task 6.2: Implement verification interception in the text-only auto-submit path

When the LLM responds with text only (no tool calls) and `should_verify()` returns True, capture the text as the answer with code "completed", set verification state, build and inject the verification prompt, and continue the loop. When False, auto-submit to the harness as before.

## Task 7: Add verification outcome logging to `agent/loop.py` [x]

Add logging for all verification events using the existing `logging` module and `print()`-based console output pattern. When a verification cycle begins, log the attempt number and a truncated answer preview (120 chars) with the `[verify]` tag. When the verified answer is dispatched (either after interception or at max attempts), call `detect_verification_outcome()` and log whether the answer was confirmed (unchanged) or revised (showing original and corrected previews truncated to 80 chars each).

**Requirements**: 6

## Task 8: Extend `tests/test_context.py` with verification configuration tests (P) [x]

Add tests to `sandbox/py/tests/test_context.py` verifying: `ContextConfig` has `verification_enabled=False` and `verification_max_attempts=2` as defaults, `from_env()` reads `VERIFY_ENABLED` env var correctly (including truthy parsing), `from_env()` reads `VERIFY_MAX_ATTEMPTS` env var correctly, and existing `ContextConfig()` construction still works without the new fields (backward compatibility). Run with `cd sandbox/py && uv run pytest tests/test_context.py -x -v`.

**Requirements**: 5, 7

## Task 9: Extend `tests/test_loop.py` with verification integration tests [x]

Add tests to `sandbox/py/tests/test_loop.py` verifying: `report_completion` is intercepted when verification is enabled, `report_completion` dispatches immediately when verification is disabled, text-only auto-submit is intercepted when verification is enabled, non-completion tool calls are dispatched normally during a verification cycle, `report_completion` dispatches after max attempts are reached, verification steps count against the 30-step executor limit, confirmed and revised outcomes produce correct log output, and all existing tests continue to pass with verification disabled (default). Run with `cd sandbox/py && uv run pytest tests/test_verify.py tests/test_context.py tests/test_loop.py -x -v`.

**Requirements**: 1, 3, 4, 6, 7

## Task 10: Update `.env.example` with verification environment variables (P) [x]

Add a "Self-Verification" section to `sandbox/py/.env.example` documenting the `VERIFY_ENABLED` and `VERIFY_MAX_ATTEMPTS` environment variables with descriptions, default values, and example values as comments.

**Requirements**: 5
