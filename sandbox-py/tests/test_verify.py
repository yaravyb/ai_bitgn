"""Tests for agent.verify -- Self-verification pure functions.

TDD: Tests written BEFORE implementation.
Task 5: Unit tests for VerificationState, should_verify, build_verification_prompt,
         detect_verification_outcome.
All tests use plain values -- no mocking required.
"""

import pytest


# ---------------------------------------------------------------------------
# VerificationState tests
# ---------------------------------------------------------------------------

class TestVerificationStateDefaults:
    """VerificationState dataclass has correct default values."""

    def test_in_verification_default_false(self):
        from agent.verify import VerificationState
        state = VerificationState()
        assert state.in_verification is False

    def test_attempts_default_zero(self):
        from agent.verify import VerificationState
        state = VerificationState()
        assert state.attempts == 0

    def test_original_answer_default_empty(self):
        from agent.verify import VerificationState
        state = VerificationState()
        assert state.original_answer == ""

    def test_original_code_default_empty(self):
        from agent.verify import VerificationState
        state = VerificationState()
        assert state.original_code == ""

    def test_custom_values(self):
        from agent.verify import VerificationState
        state = VerificationState(
            in_verification=True,
            attempts=3,
            original_answer="my answer",
            original_code="completed",
        )
        assert state.in_verification is True
        assert state.attempts == 3
        assert state.original_answer == "my answer"
        assert state.original_code == "completed"

    def test_mutable(self):
        """VerificationState fields can be mutated after creation."""
        from agent.verify import VerificationState
        state = VerificationState()
        state.in_verification = True
        state.attempts = 1
        state.original_answer = "test"
        state.original_code = "completed"
        assert state.in_verification is True
        assert state.attempts == 1


# ---------------------------------------------------------------------------
# should_verify tests
# ---------------------------------------------------------------------------

class TestShouldVerify:
    """should_verify: pure function returning bool based on state and config."""

    def test_enabled_and_under_limit_returns_true(self):
        from agent.verify import VerificationState, should_verify
        state = VerificationState(attempts=0)
        assert should_verify(state, verification_enabled=True, verification_max_attempts=2) is True

    def test_enabled_with_one_attempt_under_limit(self):
        from agent.verify import VerificationState, should_verify
        state = VerificationState(attempts=1)
        assert should_verify(state, verification_enabled=True, verification_max_attempts=2) is True

    def test_disabled_returns_false(self):
        from agent.verify import VerificationState, should_verify
        state = VerificationState(attempts=0)
        assert should_verify(state, verification_enabled=False, verification_max_attempts=2) is False

    def test_at_max_attempts_returns_false(self):
        from agent.verify import VerificationState, should_verify
        state = VerificationState(attempts=2)
        assert should_verify(state, verification_enabled=True, verification_max_attempts=2) is False

    def test_over_max_attempts_returns_false(self):
        from agent.verify import VerificationState, should_verify
        state = VerificationState(attempts=5)
        assert should_verify(state, verification_enabled=True, verification_max_attempts=2) is False

    def test_zero_max_always_returns_false(self):
        from agent.verify import VerificationState, should_verify
        state = VerificationState(attempts=0)
        assert should_verify(state, verification_enabled=True, verification_max_attempts=0) is False

    def test_disabled_and_at_max_returns_false(self):
        from agent.verify import VerificationState, should_verify
        state = VerificationState(attempts=2)
        assert should_verify(state, verification_enabled=False, verification_max_attempts=2) is False


# ---------------------------------------------------------------------------
# build_verification_prompt tests
# ---------------------------------------------------------------------------

class TestBuildVerificationPrompt:
    """build_verification_prompt: pure function building the verification prompt."""

    def test_includes_answer_and_code(self):
        from agent.verify import build_verification_prompt
        prompt = build_verification_prompt(
            answer="The answer is 42",
            code="completed",
            policy_contents={},
        )
        assert "The answer is 42" in prompt
        assert "completed" in prompt

    def test_includes_verification_tag(self):
        from agent.verify import build_verification_prompt
        prompt = build_verification_prompt("ans", "code", {})
        assert "<verification>" in prompt
        assert "</verification>" in prompt

    def test_includes_policy_contents(self):
        from agent.verify import build_verification_prompt
        policies = {
            "workspace/RULES.md": "Rule 1: Always respond in lowercase.",
            "config/FORMAT.txt": "Format: JSON only.",
        }
        prompt = build_verification_prompt("ans", "code", policies)
        assert "workspace/RULES.md" in prompt
        assert "Rule 1: Always respond in lowercase." in prompt
        assert "config/FORMAT.txt" in prompt
        assert "Format: JSON only." in prompt

    def test_empty_policies_no_policy_section(self):
        from agent.verify import build_verification_prompt
        prompt = build_verification_prompt("ans", "code", {})
        assert "## Policy Files" not in prompt

    def test_includes_checklist_when_provided(self):
        from agent.verify import build_verification_prompt
        checklist = (
            "## Verification Checklist\n"
            "1. Check format rules and casing.\n"
            "2. Verify file operations (write_file, delete_file).\n"
            "3. Check grounding references.\n"
            "4. Verify completeness."
        )
        prompt = build_verification_prompt(
            "ans", "code", {"p.md": "content"}, checklist_body=checklist,
        )
        assert "format" in prompt.lower() or "casing" in prompt.lower()
        assert "file operation" in prompt.lower() or "write_file" in prompt.lower()
        assert "grounding" in prompt.lower()
        assert "complete" in prompt.lower()

    def test_no_checklist_when_not_provided(self):
        from agent.verify import build_verification_prompt
        prompt = build_verification_prompt("ans", "code", {"p.md": "content"})
        # Without checklist_body, no checklist content is injected
        assert "grounding" not in prompt.lower()

    def test_includes_submission_instructions(self):
        from agent.verify import build_verification_prompt
        prompt = build_verification_prompt("ans", "code", {})
        assert "report_completion" in prompt

    def test_returns_string(self):
        from agent.verify import build_verification_prompt
        result = build_verification_prompt("a", "b", {})
        assert isinstance(result, str)

    def test_proposed_answer_section(self):
        from agent.verify import build_verification_prompt
        prompt = build_verification_prompt("my answer", "failed", {})
        assert "## Proposed Answer" in prompt
        assert "my answer" in prompt
        assert "failed" in prompt

    def test_includes_tool_mechanism_instruction(self):
        """Prompt must instruct LLM to use the tool mechanism, not text."""
        from agent.verify import build_verification_prompt
        prompt = build_verification_prompt("ans", "code", {})
        assert "tool" in prompt.lower()
        assert "Do NOT write" in prompt or "Do NOT" in prompt


# ---------------------------------------------------------------------------
# detect_verification_outcome tests
# ---------------------------------------------------------------------------

class TestDetectVerificationOutcome:
    """detect_verification_outcome: exact string comparison for logging."""

    def test_same_answer_returns_confirmed(self):
        from agent.verify import detect_verification_outcome, VerificationOutcome
        result = detect_verification_outcome("hello", "hello")
        assert result == VerificationOutcome.CONFIRMED

    def test_different_answer_returns_revised(self):
        from agent.verify import detect_verification_outcome, VerificationOutcome
        result = detect_verification_outcome("hello", "world")
        assert result == VerificationOutcome.REVISED

    def test_both_empty_returns_confirmed(self):
        from agent.verify import detect_verification_outcome, VerificationOutcome
        result = detect_verification_outcome("", "")
        assert result == VerificationOutcome.CONFIRMED

    def test_whitespace_only_difference_returns_revised(self):
        from agent.verify import detect_verification_outcome, VerificationOutcome
        result = detect_verification_outcome("hello", "hello ")
        assert result == VerificationOutcome.REVISED

    def test_case_difference_returns_revised(self):
        from agent.verify import detect_verification_outcome, VerificationOutcome
        result = detect_verification_outcome("Hello", "hello")
        assert result == VerificationOutcome.REVISED

    def test_multiline_same_returns_confirmed(self):
        from agent.verify import detect_verification_outcome, VerificationOutcome
        text = "line 1\nline 2\nline 3"
        result = detect_verification_outcome(text, text)
        assert result == VerificationOutcome.CONFIRMED


# ---------------------------------------------------------------------------
# VerificationOutcome enum tests
# ---------------------------------------------------------------------------

class TestVerificationOutcome:
    """VerificationOutcome enum has expected values."""

    def test_confirmed_value(self):
        from agent.verify import VerificationOutcome
        assert VerificationOutcome.CONFIRMED == "confirmed"

    def test_revised_value(self):
        from agent.verify import VerificationOutcome
        assert VerificationOutcome.REVISED == "revised"

    def test_is_string_enum(self):
        from agent.verify import VerificationOutcome
        assert isinstance(VerificationOutcome.CONFIRMED, str)
        assert isinstance(VerificationOutcome.REVISED, str)
