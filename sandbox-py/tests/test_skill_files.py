"""Tests for built-in skill files (content files, not code).

TDD: Tests written BEFORE skill file creation.
Task 8.1: workspace-discovery skill and references
Task 8.2: pattern-match-create skill and references
Task 8.3: policy-gate skill
Task 8.4: security-posture skill
"""

import re
from pathlib import Path

import pytest

# Skills directory relative to this test file
SKILLS_DIR = Path(__file__).parent.parent / "skills"


def _read_skill(skill_name: str) -> str:
    """Read a SKILL.md file and return its content."""
    path = SKILLS_DIR / skill_name / "SKILL.md"
    assert path.is_file(), f"SKILL.md not found at {path}"
    return path.read_text(encoding="utf-8")


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Extract YAML frontmatter fields from text."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    assert match is not None, "SKILL.md must start with --- delimited YAML frontmatter"
    fields = {}
    for field_match in re.finditer(r"^(\w+)\s*:\s*(.+)$", match.group(1), re.MULTILINE):
        fields[field_match.group(1)] = field_match.group(2).strip()
    return fields


def _get_body(text: str) -> str:
    """Extract the body content (after frontmatter) from a SKILL.md."""
    match = re.match(r"^---\s*\n.*?\n---\s*\n", text, re.DOTALL)
    assert match is not None
    return text[match.end():].strip()


class TestSkillDirectoryStructure:
    """All four skills must exist as subdirectories with SKILL.md files."""

    def test_skills_directory_exists(self):
        assert SKILLS_DIR.is_dir(), f"Skills directory not found at {SKILLS_DIR}"

    @pytest.mark.parametrize("skill_name", [
        "workspace-discovery",
        "pattern-match-create",
        "policy-gate",
        "security-posture",
    ])
    def test_skill_folder_exists(self, skill_name):
        skill_dir = SKILLS_DIR / skill_name
        assert skill_dir.is_dir(), f"Skill folder not found: {skill_dir}"

    @pytest.mark.parametrize("skill_name", [
        "workspace-discovery",
        "pattern-match-create",
        "policy-gate",
        "security-posture",
    ])
    def test_skill_md_exists(self, skill_name):
        skill_file = SKILLS_DIR / skill_name / "SKILL.md"
        assert skill_file.is_file(), f"SKILL.md not found: {skill_file}"


class TestSkillFrontmatter:
    """All SKILL.md files must have valid YAML frontmatter with name and description."""

    @pytest.mark.parametrize("skill_name", [
        "workspace-discovery",
        "pattern-match-create",
        "policy-gate",
        "security-posture",
    ])
    def test_frontmatter_has_name(self, skill_name):
        text = _read_skill(skill_name)
        fields = _parse_frontmatter(text)
        assert "name" in fields, f"{skill_name}/SKILL.md frontmatter missing 'name'"
        assert fields["name"] == skill_name

    @pytest.mark.parametrize("skill_name", [
        "workspace-discovery",
        "pattern-match-create",
        "policy-gate",
        "security-posture",
    ])
    def test_frontmatter_has_description(self, skill_name):
        text = _read_skill(skill_name)
        fields = _parse_frontmatter(text)
        assert "description" in fields, f"{skill_name}/SKILL.md frontmatter missing 'description'"
        assert len(fields["description"]) > 10, "Description should be meaningful"

    @pytest.mark.parametrize("skill_name", [
        "workspace-discovery",
        "pattern-match-create",
        "policy-gate",
        "security-posture",
    ])
    def test_body_is_nonempty(self, skill_name):
        text = _read_skill(skill_name)
        body = _get_body(text)
        assert len(body) > 50, f"{skill_name} body should be substantive (got {len(body)} chars)"


class TestWorkspaceDiscoverySkill:
    """Task 8.1: workspace-discovery skill content."""

    def test_body_mentions_tree(self):
        body = _get_body(_read_skill("workspace-discovery"))
        assert "tree" in body.lower(), "Should describe tree operation"

    def test_body_mentions_list_folders(self):
        body = _get_body(_read_skill("workspace-discovery"))
        assert "list" in body.lower() or "folder" in body.lower(), "Should describe listing folders"

    def test_body_mentions_meta_files(self):
        body = _get_body(_read_skill("workspace-discovery"))
        assert "meta" in body.lower() or "_rules" in body.lower(), "Should describe meta-file identification"

    def test_references_directory_exists(self):
        refs_dir = SKILLS_DIR / "workspace-discovery" / "references"
        assert refs_dir.is_dir(), "references/ directory should exist"

    def test_meta_file_patterns_reference_exists(self):
        ref_file = SKILLS_DIR / "workspace-discovery" / "references" / "meta-file-patterns.md"
        assert ref_file.is_file(), "meta-file-patterns.md reference should exist"

    def test_meta_file_patterns_contains_patterns(self):
        ref_file = SKILLS_DIR / "workspace-discovery" / "references" / "meta-file-patterns.md"
        content = ref_file.read_text(encoding="utf-8")
        # Must list all the meta-file patterns from the design
        assert "_rules" in content.lower()
        assert "rules." in content.lower() or "RULES" in content
        assert "skill-" in content.lower()
        assert "_config" in content.lower()
        assert "_meta" in content.lower()
        assert "agents" in content.lower()
        assert "readme" in content.lower()
        assert ".rules" in content.lower()

    def test_description_mentions_exploration(self):
        text = _read_skill("workspace-discovery")
        fields = _parse_frontmatter(text)
        desc = fields["description"].lower()
        assert "explor" in desc or "discover" in desc or "vault" in desc


class TestPatternMatchCreateSkill:
    """Task 8.2: pattern-match-create skill content."""

    def test_body_mentions_inspect_files(self):
        body = _get_body(_read_skill("pattern-match-create"))
        assert "inspect" in body.lower() or "existing" in body.lower()

    def test_body_mentions_numbering_patterns(self):
        body = _get_body(_read_skill("pattern-match-create"))
        assert "number" in body.lower() or "pattern" in body.lower()

    def test_body_mentions_meta_files(self):
        body = _get_body(_read_skill("pattern-match-create"))
        assert "meta" in body.lower() or "_rules" in body.lower()

    def test_body_mentions_create(self):
        body = _get_body(_read_skill("pattern-match-create"))
        assert "creat" in body.lower()

    def test_references_directory_exists(self):
        refs_dir = SKILLS_DIR / "pattern-match-create" / "references"
        assert refs_dir.is_dir(), "references/ directory should exist"

    def test_numbering_detection_reference_exists(self):
        ref_file = SKILLS_DIR / "pattern-match-create" / "references" / "numbering-detection.md"
        assert ref_file.is_file(), "numbering-detection.md reference should exist"

    def test_numbering_detection_describes_algorithm(self):
        ref_file = SKILLS_DIR / "pattern-match-create" / "references" / "numbering-detection.md"
        content = ref_file.read_text(encoding="utf-8")
        assert "prefix" in content.lower() or "group" in content.lower()
        assert "extension" in content.lower() or "suffix" in content.lower()

    def test_description_mentions_pattern(self):
        text = _read_skill("pattern-match-create")
        fields = _parse_frontmatter(text)
        desc = fields["description"].lower()
        assert "pattern" in desc or "numbering" in desc or "match" in desc


class TestPolicyGateSkill:
    """Task 8.3: policy-gate skill content."""

    def test_body_mentions_agents_md(self):
        body = _get_body(_read_skill("policy-gate"))
        assert "agents" in body.lower() or "AGENTS" in body

    def test_body_mentions_conditions(self):
        body = _get_body(_read_skill("policy-gate"))
        assert "condition" in body.lower() or "policy" in body.lower()

    def test_body_mentions_refuse_or_halt(self):
        body = _get_body(_read_skill("policy-gate"))
        assert "refuse" in body.lower() or "halt" in body.lower() or "reject" in body.lower()

    def test_body_mentions_parse(self):
        body = _get_body(_read_skill("policy-gate"))
        assert "parse" in body.lower() or "extract" in body.lower() or "read" in body.lower()

    def test_description_mentions_policy(self):
        text = _read_skill("policy-gate")
        fields = _parse_frontmatter(text)
        desc = fields["description"].lower()
        assert "polic" in desc or "conditional" in desc or "gate" in desc


class TestSecurityPostureSkill:
    """Task 8.4: security-posture skill content."""

    def test_body_mentions_injection(self):
        body = _get_body(_read_skill("security-posture"))
        assert "inject" in body.lower()

    def test_body_mentions_untrusted(self):
        body = _get_body(_read_skill("security-posture"))
        assert "untrusted" in body.lower() or "user-provided" in body.lower()

    def test_body_mentions_protected_files(self):
        body = _get_body(_read_skill("security-posture"))
        assert "protect" in body.lower() or "never delete" in body.lower() or "never modify" in body.lower()

    def test_body_mentions_override_patterns(self):
        body = _get_body(_read_skill("security-posture"))
        assert "override" in body.lower() or "ignore" in body.lower()

    def test_body_mentions_system_prompt(self):
        body = _get_body(_read_skill("security-posture"))
        assert "system" in body.lower() or "prompt" in body.lower()

    def test_description_mentions_security_or_defense(self):
        text = _read_skill("security-posture")
        fields = _parse_frontmatter(text)
        desc = fields["description"].lower()
        assert "secur" in desc or "defense" in desc or "injection" in desc


class TestSkillsLoadableBySkillLoader:
    """Verify the SkillLoader can actually parse all built-in skills."""

    def test_loader_finds_all_four_skills(self):
        from agent.skills import SkillLoader
        loader = SkillLoader(SKILLS_DIR)
        names = loader.list_names()
        assert "workspace-discovery" in names
        assert "pattern-match-create" in names
        assert "policy-gate" in names
        assert "security-posture" in names

    def test_loader_parses_descriptions(self):
        from agent.skills import SkillLoader
        loader = SkillLoader(SKILLS_DIR)
        desc = loader.get_descriptions()
        assert "workspace-discovery" in desc
        assert "pattern-match-create" in desc
        assert "policy-gate" in desc
        assert "security-posture" in desc

    def test_loader_gets_content_for_each_skill(self):
        from agent.skills import SkillLoader
        loader = SkillLoader(SKILLS_DIR)
        for name in ["workspace-discovery", "pattern-match-create", "policy-gate", "security-posture"]:
            content = loader.get_content(name)
            assert "<skill" in content, f"Content for {name} should be wrapped in <skill> tags"
            assert "</skill>" in content

    def test_security_posture_body_is_substantial(self):
        """Security posture body is embedded in system prompt, so it must be substantive."""
        from agent.skills import SkillLoader
        loader = SkillLoader(SKILLS_DIR)
        content = loader.get_content("security-posture")
        # The body between <skill> tags should be at least 200 chars
        assert len(content) > 200
