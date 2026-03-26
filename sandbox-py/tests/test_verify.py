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
# build_verification_prompt -- template-driven path tests (Task 4)
# ---------------------------------------------------------------------------

# Reusable template fixture matching the design specification
_FRAME_TEMPLATE = """\
<verification>
You are about to submit the following answer. Before submitting, verify it is correct.

## Proposed Answer
Code: {{CODE}}
Answer: {{ANSWER}}

{{POLICY_SECTION}}

{{CHECKLIST_SECTION}}

{{SOURCE_BASENAME_SECTION}}

## Instructions
- If the answer is correct, use the report_completion tool with the SAME answer and code.
- If the answer needs correction, use the report_completion tool with the CORRECTED answer.
- You may use other tools (read_file, list_dir, etc.) to verify file operations before submitting.
- IMPORTANT: Submit ONLY by calling the report_completion tool. Do NOT write the answer as plain text or JSON.
</verification>"""


class TestBuildVerificationPromptWithTemplate:
    """build_verification_prompt with frame_template: template-driven path."""

    def test_template_substitutes_answer(self):
        from agent.verify import build_verification_prompt
        prompt = build_verification_prompt(
            answer="The answer is 42",
            code="OUTCOME_OK",
            policy_contents={},
            frame_template=_FRAME_TEMPLATE,
        )
        assert "The answer is 42" in prompt
        assert "{{ANSWER}}" not in prompt

    def test_template_substitutes_code(self):
        from agent.verify import build_verification_prompt
        prompt = build_verification_prompt(
            answer="ans",
            code="OUTCOME_OK",
            policy_contents={},
            frame_template=_FRAME_TEMPLATE,
        )
        assert "OUTCOME_OK" in prompt
        assert "{{CODE}}" not in prompt

    def test_template_substitutes_policy_section(self):
        from agent.verify import build_verification_prompt
        policies = {
            "workspace/RULES.md": "Rule 1: Always respond in lowercase.",
        }
        prompt = build_verification_prompt(
            answer="ans",
            code="code",
            policy_contents=policies,
            frame_template=_FRAME_TEMPLATE,
        )
        assert "workspace/RULES.md" in prompt
        assert "Rule 1: Always respond in lowercase." in prompt
        assert "{{POLICY_SECTION}}" not in prompt

    def test_template_empty_policies_no_header(self):
        from agent.verify import build_verification_prompt
        prompt = build_verification_prompt(
            answer="ans",
            code="code",
            policy_contents={},
            frame_template=_FRAME_TEMPLATE,
        )
        assert "## Policy Files" not in prompt
        assert "{{POLICY_SECTION}}" not in prompt

    def test_template_substitutes_checklist_section(self):
        from agent.verify import build_verification_prompt
        checklist = "## Verification Checklist\n1. Check format."
        prompt = build_verification_prompt(
            answer="ans",
            code="code",
            policy_contents={},
            checklist_body=checklist,
            frame_template=_FRAME_TEMPLATE,
        )
        assert "Check format." in prompt
        assert "{{CHECKLIST_SECTION}}" not in prompt

    def test_template_empty_checklist(self):
        from agent.verify import build_verification_prompt
        prompt = build_verification_prompt(
            answer="ans",
            code="code",
            policy_contents={},
            checklist_body="",
            frame_template=_FRAME_TEMPLATE,
        )
        assert "{{CHECKLIST_SECTION}}" not in prompt

    def test_template_substitutes_source_basename_section(self):
        from agent.verify import build_verification_prompt
        prompt = build_verification_prompt(
            answer="ans",
            code="code",
            policy_contents={},
            source_basename="report.csv",
            frame_template=_FRAME_TEMPLATE,
        )
        assert "report.csv" in prompt
        assert "{{SOURCE_BASENAME_SECTION}}" not in prompt

    def test_template_no_source_basename(self):
        from agent.verify import build_verification_prompt
        prompt = build_verification_prompt(
            answer="ans",
            code="code",
            policy_contents={},
            source_basename=None,
            frame_template=_FRAME_TEMPLATE,
        )
        assert "{{SOURCE_BASENAME_SECTION}}" not in prompt
        assert "Source Filename Check" not in prompt

    def test_template_includes_verification_tags(self):
        from agent.verify import build_verification_prompt
        prompt = build_verification_prompt(
            answer="ans",
            code="code",
            policy_contents={},
            frame_template=_FRAME_TEMPLATE,
        )
        assert "<verification>" in prompt
        assert "</verification>" in prompt

    def test_template_includes_instructions(self):
        from agent.verify import build_verification_prompt
        prompt = build_verification_prompt(
            answer="ans",
            code="code",
            policy_contents={},
            frame_template=_FRAME_TEMPLATE,
        )
        assert "report_completion" in prompt
        assert "Do NOT" in prompt

    def test_template_returns_string(self):
        from agent.verify import build_verification_prompt
        result = build_verification_prompt(
            "a", "b", {},
            frame_template=_FRAME_TEMPLATE,
        )
        assert isinstance(result, str)

    def test_template_all_placeholders_substituted(self):
        """No {{...}} placeholders remain after substitution."""
        from agent.verify import build_verification_prompt
        prompt = build_verification_prompt(
            answer="my answer",
            code="OUTCOME_OK",
            policy_contents={"p.md": "policy content"},
            checklist_body="## Checklist\n1. Check it.",
            source_basename="data.json",
            frame_template=_FRAME_TEMPLATE,
        )
        assert "{{" not in prompt
        assert "}}" not in prompt


class TestBuildVerificationPromptFallback:
    """build_verification_prompt with frame_template=None: fallback inline path."""

    def test_fallback_when_none(self):
        """When frame_template is None, the inline frame is used."""
        from agent.verify import build_verification_prompt
        prompt = build_verification_prompt(
            answer="ans",
            code="code",
            policy_contents={},
            frame_template=None,
        )
        assert "<verification>" in prompt
        assert "</verification>" in prompt
        assert "## Proposed Answer" in prompt
        assert "## Instructions" in prompt
        assert "report_completion" in prompt

    def test_fallback_not_provided(self):
        """When frame_template is not passed at all, default is None -> fallback."""
        from agent.verify import build_verification_prompt
        prompt = build_verification_prompt("ans", "code", {})
        assert "<verification>" in prompt
        assert "## Proposed Answer" in prompt

    def test_fallback_includes_answer_and_code(self):
        from agent.verify import build_verification_prompt
        prompt = build_verification_prompt(
            answer="The answer is 42",
            code="OUTCOME_OK",
            policy_contents={},
            frame_template=None,
        )
        assert "The answer is 42" in prompt
        assert "OUTCOME_OK" in prompt

    def test_fallback_includes_policies(self):
        from agent.verify import build_verification_prompt
        policies = {"rules.md": "Rule content"}
        prompt = build_verification_prompt(
            answer="ans",
            code="code",
            policy_contents=policies,
            frame_template=None,
        )
        assert "rules.md" in prompt
        assert "Rule content" in prompt

    def test_fallback_includes_checklist(self):
        from agent.verify import build_verification_prompt
        prompt = build_verification_prompt(
            answer="ans",
            code="code",
            policy_contents={},
            checklist_body="## Checklist\n1. Verify.",
            frame_template=None,
        )
        assert "Verify." in prompt

    def test_fallback_includes_source_basename(self):
        from agent.verify import build_verification_prompt
        prompt = build_verification_prompt(
            answer="ans",
            code="code",
            policy_contents={},
            source_basename="report.csv",
            frame_template=None,
        )
        assert "report.csv" in prompt

    def test_fallback_and_template_produce_equivalent_content(self):
        """Both paths should contain the same key content elements."""
        from agent.verify import build_verification_prompt
        common_kwargs = dict(
            answer="test answer",
            code="OUTCOME_OK",
            policy_contents={"p.md": "policy"},
            checklist_body="## Checklist\n1. Check.",
            source_basename="file.txt",
        )
        fallback = build_verification_prompt(**common_kwargs, frame_template=None)
        templated = build_verification_prompt(**common_kwargs, frame_template=_FRAME_TEMPLATE)

        # Both should contain the same dynamic content
        for expected in ["test answer", "OUTCOME_OK", "p.md", "policy",
                         "Check.", "file.txt", "report_completion",
                         "<verification>", "</verification>"]:
            assert expected in fallback, f"Fallback missing: {expected}"
            assert expected in templated, f"Template missing: {expected}"


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


# ---------------------------------------------------------------------------
# build_verification_prompt -- plan_status parameter tests (Task 7.4)
# ---------------------------------------------------------------------------

# Template with the new {{PLAN_STATUS_SECTION}} placeholder
_FRAME_TEMPLATE_WITH_PLAN = """\
<verification>
You are about to submit the following answer. Before submitting, verify it is correct.

## Proposed Answer
Code: {{CODE}}
Answer: {{ANSWER}}

{{POLICY_SECTION}}

{{CHECKLIST_SECTION}}

{{SOURCE_BASENAME_SECTION}}

{{PLAN_STATUS_SECTION}}

## Instructions
- If the answer is correct, use the report_completion tool with the SAME answer and code.
- If the answer needs correction, use the report_completion tool with the CORRECTED answer.
- You may use other tools (read_file, list_dir, etc.) to verify file operations before submitting.
- IMPORTANT: Submit ONLY by calling the report_completion tool. Do NOT write the answer as plain text or JSON.
</verification>"""


class TestBuildVerificationPromptPlanStatus:
    """Task 7.4: plan_status parameter substitutes {{PLAN_STATUS_SECTION}}."""

    def test_template_substitutes_plan_status(self):
        from agent.verify import build_verification_prompt
        plan_text = "## Plan Status\nAll 3 plan steps completed."
        prompt = build_verification_prompt(
            answer="ans",
            code="code",
            policy_contents={},
            frame_template=_FRAME_TEMPLATE_WITH_PLAN,
            plan_status=plan_text,
        )
        assert "All 3 plan steps completed" in prompt
        assert "{{PLAN_STATUS_SECTION}}" not in prompt

    def test_template_empty_plan_status_no_change(self):
        from agent.verify import build_verification_prompt
        prompt = build_verification_prompt(
            answer="ans",
            code="code",
            policy_contents={},
            frame_template=_FRAME_TEMPLATE_WITH_PLAN,
            plan_status="",
        )
        assert "{{PLAN_STATUS_SECTION}}" not in prompt
        assert "Plan Status" not in prompt

    def test_fallback_includes_plan_status_when_provided(self):
        from agent.verify import build_verification_prompt
        plan_text = "## Plan Status -- Incomplete Steps Detected\nStep 1 pending."
        prompt = build_verification_prompt(
            answer="ans",
            code="code",
            policy_contents={},
            plan_status=plan_text,
        )
        assert "Incomplete Steps Detected" in prompt

    def test_fallback_no_plan_status_when_empty(self):
        from agent.verify import build_verification_prompt
        prompt = build_verification_prompt(
            answer="ans",
            code="code",
            policy_contents={},
            plan_status="",
        )
        assert "Plan Status" not in prompt

    def test_all_placeholders_substituted_with_plan_status(self):
        from agent.verify import build_verification_prompt
        prompt = build_verification_prompt(
            answer="my answer",
            code="OUTCOME_OK",
            policy_contents={"p.md": "policy content"},
            checklist_body="## Checklist\n1. Check it.",
            source_basename="data.json",
            frame_template=_FRAME_TEMPLATE_WITH_PLAN,
            plan_status="## Plan Status\nAll done.",
        )
        assert "{{" not in prompt
        assert "}}" not in prompt
