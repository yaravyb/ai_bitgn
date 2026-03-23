"""Self-verification: pure functions for verification state, prompt, and outcome.

Leaf module: ZERO imports from other agent/ modules.
Provides pure functions and dataclasses only.
All orchestration (interception, dispatch) belongs in loop.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class VerificationState:
    """Tracks verification state within a single task execution.

    Created once per run_agent() invocation. Mutated by loop.py
    as verification cycles proceed.
    """

    in_verification: bool = False
    attempts: int = 0
    original_answer: str = ""
    original_code: str = ""


class VerificationOutcome(str, Enum):
    """Classification of a verification cycle result (for logging)."""

    CONFIRMED = "confirmed"
    REVISED = "revised"


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------

def should_verify(
    state: VerificationState,
    verification_enabled: bool,
    verification_max_attempts: int,
) -> bool:
    """Determine whether a verification cycle should be initiated.

    Returns True when verification is enabled and the number of
    completed attempts is below the configured maximum.
    """
    if not verification_enabled:
        return False
    if state.attempts >= verification_max_attempts:
        return False
    return True


def build_verification_prompt(
    answer: str,
    code: str,
    policy_contents: dict[str, str],
) -> str:
    """Construct the verification prompt injected as a user message.

    The prompt includes the proposed answer/code verbatim, policy file
    contents, a verification checklist, and submission instructions.
    """
    parts: list[str] = []
    parts.append("<verification>")
    parts.append(
        "You are about to submit the following answer. "
        "Before submitting, verify it is correct."
    )
    parts.append("")
    parts.append("## Proposed Answer")
    parts.append(f"Code: {code}")
    parts.append(f"Answer: {answer}")

    if policy_contents:
        parts.append("")
        parts.append("## Policy Files")
        for path, content in sorted(policy_contents.items()):
            parts.append(f"### {path}")
            parts.append(content)

    parts.append("")
    parts.append("## Verification Checklist")
    parts.append(
        "1. Re-read the policy files above. Does the answer comply with "
        "ALL format rules (exact casing, whitespace, punctuation, response codes)?"
    )
    parts.append(
        "2. If you performed file operations (write_file, delete_file), "
        "verify they succeeded by re-reading or listing the affected paths."
    )
    parts.append(
        "3. Check that all grounding references point to files that actually exist."
    )
    parts.append(
        "4. Verify the answer is complete and addresses the full task requirement."
    )

    parts.append("")
    parts.append("## Instructions")
    parts.append(
        "- If the answer is correct, use the report_completion tool with the SAME answer and code."
    )
    parts.append(
        "- If the answer needs correction, use the report_completion tool with the CORRECTED answer."
    )
    parts.append(
        "- You may use other tools (read_file, list_dir, etc.) to verify file operations before submitting."
    )
    parts.append(
        "- IMPORTANT: Submit ONLY by calling the report_completion tool. "
        "Do NOT write the answer as plain text or JSON."
    )
    parts.append("</verification>")

    return "\n".join(parts)


def detect_verification_outcome(
    original_answer: str,
    new_answer: str,
) -> VerificationOutcome:
    """Compare original and verified answers using exact string equality.

    Returns CONFIRMED if the answers are identical, REVISED otherwise.
    Used purely for logging purposes.
    """
    if original_answer == new_answer:
        return VerificationOutcome.CONFIRMED
    return VerificationOutcome.REVISED
