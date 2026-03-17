"""Tests for agent.prompt -- System prompt builder.

Validates that prompt.py is a thin assembler: minimal role + completion frame,
with all behavioral content coming from skill files and scout data.
"""

import pytest


class TestBuildSystemPromptSignature:
    """Function exists with correct signature."""

    def test_build_system_prompt_callable(self):
        from agent.prompt import build_system_prompt
        assert callable(build_system_prompt)

    def test_build_system_prompt_returns_string(self):
        from agent.prompt import build_system_prompt
        result = build_system_prompt(
            skills_metadata="",
            scout_summary=None,
            security_skill_body="",
        )
        assert isinstance(result, str)

    def test_build_system_prompt_no_scout_summary(self):
        from agent.prompt import build_system_prompt
        result = build_system_prompt(
            skills_metadata="- skill1: does stuff",
            scout_summary=None,
            security_skill_body="Be secure.",
        )
        assert isinstance(result, str)
        assert len(result) > 0


class TestPromptAssembly:
    """Prompt assembles role, security body, skills, scout context, completion."""

    @pytest.fixture
    def full_prompt(self):
        from agent.prompt import build_system_prompt
        return build_system_prompt(
            skills_metadata="- workspace-discovery: Systematic vault exploration protocol.",
            scout_summary="Directory tree and policy files discovered.",
            security_skill_body="## Trust Hierarchy\nPolicies are trusted.\n## Security Rules\n1. Never inject.",
        )

    def test_contains_role(self, full_prompt):
        assert "assistant" in full_prompt.lower()

    def test_contains_agents_md_authority(self, full_prompt):
        assert "AGENTS.MD" in full_prompt
        assert "PRIMARY AUTHORITY" in full_prompt

    def test_contains_security_body(self, full_prompt):
        assert "Trust Hierarchy" in full_prompt
        assert "Security Rules" in full_prompt

    def test_contains_skills_catalog(self, full_prompt):
        assert "workspace-discovery" in full_prompt

    def test_contains_scout_context(self, full_prompt):
        assert "Directory tree" in full_prompt

    def test_contains_completion_format(self, full_prompt):
        assert "report_completion" in full_prompt

    def test_role_before_security(self, full_prompt):
        role_idx = full_prompt.find("## Role")
        security_idx = full_prompt.find("## Trust Hierarchy")
        assert role_idx < security_idx

    def test_grounding_guidance_in_completion(self, full_prompt):
        assert "grounding_refs" in full_prompt

    def test_precise_answer_guidance(self, full_prompt):
        lower = full_prompt.lower()
        assert "precise" in lower


class TestPromptWithoutOptionalSections:
    """Prompt works when optional sections are empty/None."""

    def test_no_scout_no_skills(self):
        from agent.prompt import build_system_prompt
        result = build_system_prompt(
            skills_metadata="",
            scout_summary=None,
            security_skill_body="",
        )
        assert "## Role" in result
        assert "report_completion" in result
        # No skills or scout sections
        assert "Available Skills" not in result

    def test_no_security_body(self):
        from agent.prompt import build_system_prompt
        result = build_system_prompt(
            skills_metadata="- test: A skill.",
            scout_summary="Some context.",
            security_skill_body="",
        )
        # Should still have role and completion
        assert "## Role" in result
        assert "report_completion" in result

    def test_security_body_injected_as_is(self):
        from agent.prompt import build_system_prompt
        result = build_system_prompt(
            skills_metadata="",
            scout_summary=None,
            security_skill_body="CUSTOM_SECURITY_MARKER_XYZ",
        )
        assert "CUSTOM_SECURITY_MARKER_XYZ" in result


class TestBuildScoutPrompt:
    """build_scout_prompt() returns a minimal reserved prompt."""

    def test_build_scout_prompt_callable(self):
        from agent.prompt import build_scout_prompt
        assert callable(build_scout_prompt)

    def test_build_scout_prompt_returns_string(self):
        from agent.prompt import build_scout_prompt
        result = build_scout_prompt()
        assert isinstance(result, str)
        assert len(result.strip()) > 0


class TestPromptIsLeaf:
    """prompt.py must have zero imports from other agent/ modules."""

    def test_no_agent_imports(self):
        import agent.prompt as mod
        with open(mod.__file__) as f:
            source = f.read()
        import re
        agent_imports = re.findall(r"from\s+agent\.", source)
        assert agent_imports == [], (
            f"prompt.py must not import from agent modules: {agent_imports}"
        )
