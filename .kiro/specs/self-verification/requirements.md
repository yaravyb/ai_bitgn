# Requirements: self-verification

> Pre-submission verification loop that intercepts report_completion to let the LLM double-check its answer against policy rules, verify file operations succeeded, and confirm answer format correctness before final submission. Targets improved accuracy for smaller/cheaper models that frequently produce near-correct but format-mismatched answers. Addresses weakness #9 (Single-Attempt Completion) from agent-analysis.md.

## Status: Generated

## Context

The agent currently submits answers in a single attempt: when the LLM calls `report_completion` (or produces a text-only response that is auto-submitted), the answer goes directly to the harness with no opportunity for self-review. This is identified as weakness #9 in `docs/agent-analysis.md`. Smaller and cheaper models frequently produce near-correct answers that fail on format details (e.g., wrong casing, extra whitespace, missing file extensions in grounding refs). A verification step before final submission can catch these errors without requiring a more expensive model.

The verification loop must integrate into the existing executor loop in `loop.py`, intercepting `report_completion` tool calls before they reach `dispatch.py`, and injecting a verification prompt that asks the LLM to re-examine its answer against the discovered policy files and task requirements.

---

## 1. Verification Interception

When the executor LLM calls `report_completion`, the system shall intercept the call before dispatching it to the harness, hold the proposed answer, and initiate a verification cycle instead of immediately submitting.

### Acceptance Criteria

- **AC 1.1**: When `report_completion` is called by the LLM and verification is enabled, the system shall withhold the answer from the harness and inject a verification prompt into the conversation.
- **AC 1.2**: When `report_completion` is called by the LLM and verification is disabled, the system shall dispatch the call to the harness immediately, preserving the current behavior.
- **AC 1.3**: When a text-only response triggers auto-submission (no tool calls) and verification is enabled, the system shall intercept the auto-submission and initiate a verification cycle for the auto-submitted answer.

---

## 2. Verification Prompt Construction

The verification prompt shall instruct the LLM to re-read relevant policy files, check the proposed answer against format rules, and verify that any file operations completed successfully.

### Acceptance Criteria

- **AC 2.1**: The verification prompt shall include the original proposed answer and completion code so the LLM can review them.
- **AC 2.2**: The verification prompt shall instruct the LLM to re-read policy files discovered during the scout phase (available in the scout context) to confirm format compliance.
- **AC 2.3**: The verification prompt shall instruct the LLM to verify that any file operations it performed (writes, deletes) were successful by re-reading or listing affected paths.
- **AC 2.4**: The verification prompt shall instruct the LLM to check the answer for exact format correctness, including casing, whitespace, punctuation, and code values defined by policies.
- **AC 2.5**: The verification prompt shall instruct the LLM to check that grounding references are accurate and complete (no missing files, no non-existent paths).

---

## 3. Verification Outcome Handling

After the verification prompt, the LLM shall either confirm the original answer or provide a corrected answer, and the system shall handle both outcomes.

### Acceptance Criteria

- **AC 3.1**: When the LLM calls `report_completion` after a verification prompt, the system shall treat this as the verified (possibly corrected) answer and dispatch it to the harness.
- **AC 3.2**: When the LLM uses tools (e.g., `read_file`) during the verification cycle, the system shall execute those tool calls normally and continue the verification cycle.
- **AC 3.3**: When the LLM responds with text only (no tool calls) during the verification cycle, the system shall treat the text as the verified answer and auto-submit it to the harness, consistent with the existing auto-submit behavior.
- **AC 3.4**: The system shall count each verification cycle against the existing 30-step executor limit to prevent unbounded verification loops.

---

## 4. Verification Attempt Limits

The system shall enforce a configurable maximum number of verification attempts to prevent infinite self-correction loops.

### Acceptance Criteria

- **AC 4.1**: The system shall support a configurable maximum number of verification attempts (default: 2).
- **AC 4.2**: When the maximum number of verification attempts is reached and the LLM calls `report_completion` again, the system shall dispatch the answer to the harness without initiating another verification cycle.
- **AC 4.3**: When the maximum number of verification attempts is reached and the LLM responds with text only, the system shall auto-submit the text to the harness without further verification.

---

## 5. Configuration

The self-verification feature shall be fully configurable via environment variables, consistent with the existing configuration pattern used by `ContextConfig`.

### Acceptance Criteria

- **AC 5.1**: The system shall support an environment variable to enable or disable the verification feature (default: disabled).
- **AC 5.2**: The system shall support an environment variable to set the maximum number of verification attempts (default: 2).
- **AC 5.3**: When verification is disabled, the system shall behave identically to the current implementation with no performance overhead beyond a single boolean check.

---

## 6. Transparency and Logging

The verification process shall produce sufficient logging output for operators to understand what happened during verification.

### Acceptance Criteria

- **AC 6.1**: When a verification cycle begins, the system shall log the proposed answer (truncated preview) and the verification attempt number.
- **AC 6.2**: When a verification cycle concludes with a confirmed answer (unchanged), the system shall log that the original answer was confirmed.
- **AC 6.3**: When a verification cycle concludes with a corrected answer, the system shall log that the answer was revised, showing both the original and corrected answer previews.
- **AC 6.4**: All verification log output shall use the existing logging infrastructure (`logging` module) and print-based console output pattern established in `loop.py`.

---

## 7. Backward Compatibility

The self-verification feature shall not alter the behavior of the existing agent when the feature is disabled.

### Acceptance Criteria

- **AC 7.1**: When verification is disabled, the executor loop shall produce identical message sequences and harness calls as the current implementation.
- **AC 7.2**: The feature shall not modify any existing function signatures in `dispatch.py`, `tools.py`, `prompt.py`, or `context.py`.
- **AC 7.3**: The feature shall not introduce new dependencies beyond the Python standard library and existing project dependencies.
- **AC 7.4**: All existing tests shall continue to pass without modification when verification is disabled.
