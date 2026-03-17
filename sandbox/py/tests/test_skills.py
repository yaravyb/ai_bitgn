"""Tests for agent.skills -- SkillLoader with folder structure.

TDD: Tests written BEFORE implementation.
Task 7.1: SkillEntry dataclass and SkillLoader class
Task 7.2: __init__(skills_dir) scans SKILL.md files, parses YAML frontmatter
Task 7.3: get_descriptions(), get_content(), list_names()
"""

import os
import pytest
import tempfile
from pathlib import Path


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    """Create a temporary skills directory with two skill folders."""
    # Skill 1: workspace-discovery
    ws_dir = tmp_path / "workspace-discovery"
    ws_dir.mkdir()
    (ws_dir / "SKILL.md").write_text(
        "---\n"
        "name: workspace-discovery\n"
        "description: Systematic vault exploration protocol for meta-file identification.\n"
        "---\n"
        "\n"
        "# Workspace Discovery\n"
        "\n"
        "When exploring a workspace:\n"
        "1. Tree the root first\n"
        "2. List all top-level folders\n"
        "3. Read all meta-files\n"
    )
    refs_dir = ws_dir / "references"
    refs_dir.mkdir()
    (refs_dir / "meta-file-patterns.md").write_text("Pattern list here.")

    # Skill 2: policy-gate
    pg_dir = tmp_path / "policy-gate"
    pg_dir.mkdir()
    (pg_dir / "SKILL.md").write_text(
        "---\n"
        "name: policy-gate\n"
        "description: Parse conditional policies and refuse when unmet.\n"
        "---\n"
        "\n"
        "# Policy Gate\n"
        "\n"
        "Check AGENTS.MD for conditions.\n"
    )

    return tmp_path


@pytest.fixture
def empty_skills_dir(tmp_path: Path) -> Path:
    """A skills directory with no skill folders."""
    return tmp_path


@pytest.fixture
def malformed_skills_dir(tmp_path: Path) -> Path:
    """A skills directory with a malformed SKILL.md (no frontmatter)."""
    bad_dir = tmp_path / "bad-skill"
    bad_dir.mkdir()
    (bad_dir / "SKILL.md").write_text("No frontmatter here, just plain text.")
    return tmp_path


class TestSkillEntryDataclass:
    """Task 7.1: SkillEntry dataclass."""

    def test_skill_entry_has_expected_fields(self):
        from agent.skills import SkillEntry
        entry = SkillEntry(
            name="test-skill",
            description="A test skill.",
            body="Skill body text.",
            path="/some/path/SKILL.md",
        )
        assert entry.name == "test-skill"
        assert entry.description == "A test skill."
        assert entry.body == "Skill body text."
        assert entry.path == "/some/path/SKILL.md"

    def test_skill_entry_is_dataclass(self):
        from agent.skills import SkillEntry
        from dataclasses import fields
        field_names = {f.name for f in fields(SkillEntry)}
        assert field_names == {"name", "description", "body", "path"}


class TestSkillLoaderInit:
    """Task 7.2: __init__ scans skills/<name>/SKILL.md files."""

    def test_loader_discovers_two_skills(self, skills_dir):
        from agent.skills import SkillLoader
        loader = SkillLoader(skills_dir)
        assert len(loader.list_names()) == 2

    def test_loader_indexes_by_name(self, skills_dir):
        from agent.skills import SkillLoader
        loader = SkillLoader(skills_dir)
        names = loader.list_names()
        assert "workspace-discovery" in names
        assert "policy-gate" in names

    def test_loader_empty_directory(self, empty_skills_dir):
        from agent.skills import SkillLoader
        loader = SkillLoader(empty_skills_dir)
        assert loader.list_names() == []

    def test_loader_nonexistent_directory(self, tmp_path):
        from agent.skills import SkillLoader
        loader = SkillLoader(tmp_path / "nonexistent")
        assert loader.list_names() == []

    def test_loader_parses_frontmatter_name(self, skills_dir):
        from agent.skills import SkillLoader
        loader = SkillLoader(skills_dir)
        content = loader.get_content("workspace-discovery")
        assert "Workspace Discovery" in content

    def test_loader_parses_frontmatter_description(self, skills_dir):
        from agent.skills import SkillLoader
        loader = SkillLoader(skills_dir)
        desc = loader.get_descriptions()
        assert "workspace-discovery" in desc
        assert "vault exploration" in desc.lower()

    def test_loader_skips_malformed_skill(self, malformed_skills_dir):
        """A SKILL.md without valid frontmatter should be skipped or handled gracefully."""
        from agent.skills import SkillLoader
        loader = SkillLoader(malformed_skills_dir)
        # Should not crash; skill is either skipped or has empty description
        names = loader.list_names()
        # Malformed skill might be skipped entirely
        assert isinstance(names, list)

    def test_loader_ignores_non_directory_items(self, skills_dir):
        """Files directly in skills_dir (not subdirectories) should be ignored."""
        from agent.skills import SkillLoader
        (skills_dir / "README.md").write_text("This is not a skill folder.")
        loader = SkillLoader(skills_dir)
        names = loader.list_names()
        assert "README" not in names
        # Still finds only our two skills
        assert len(names) == 2


class TestSkillLoaderGetDescriptions:
    """Task 7.3: get_descriptions() returns Layer 1 one-liner per skill."""

    def test_descriptions_returns_string(self, skills_dir):
        from agent.skills import SkillLoader
        loader = SkillLoader(skills_dir)
        desc = loader.get_descriptions()
        assert isinstance(desc, str)

    def test_descriptions_contains_all_skill_names(self, skills_dir):
        from agent.skills import SkillLoader
        loader = SkillLoader(skills_dir)
        desc = loader.get_descriptions()
        assert "workspace-discovery" in desc
        assert "policy-gate" in desc

    def test_descriptions_contains_description_text(self, skills_dir):
        from agent.skills import SkillLoader
        loader = SkillLoader(skills_dir)
        desc = loader.get_descriptions()
        assert "meta-file identification" in desc.lower() or "vault exploration" in desc.lower()
        assert "conditional policies" in desc.lower() or "refuse when unmet" in desc.lower()

    def test_descriptions_empty_when_no_skills(self, empty_skills_dir):
        from agent.skills import SkillLoader
        loader = SkillLoader(empty_skills_dir)
        desc = loader.get_descriptions()
        assert isinstance(desc, str)
        # Empty or minimal
        assert len(desc.strip()) == 0 or "no skills" in desc.lower() or desc.strip() == ""


class TestSkillLoaderGetContent:
    """Task 7.3: get_content(name) returns Layer 2 full body in <skill> tags."""

    def test_get_content_returns_string(self, skills_dir):
        from agent.skills import SkillLoader
        loader = SkillLoader(skills_dir)
        content = loader.get_content("workspace-discovery")
        assert isinstance(content, str)

    def test_get_content_wrapped_in_skill_tags(self, skills_dir):
        from agent.skills import SkillLoader
        loader = SkillLoader(skills_dir)
        content = loader.get_content("workspace-discovery")
        assert "<skill" in content
        assert "</skill>" in content

    def test_get_content_includes_name_attribute(self, skills_dir):
        from agent.skills import SkillLoader
        loader = SkillLoader(skills_dir)
        content = loader.get_content("workspace-discovery")
        assert 'name="workspace-discovery"' in content

    def test_get_content_includes_body(self, skills_dir):
        from agent.skills import SkillLoader
        loader = SkillLoader(skills_dir)
        content = loader.get_content("workspace-discovery")
        assert "Tree the root first" in content
        assert "Read all meta-files" in content

    def test_get_content_excludes_frontmatter(self, skills_dir):
        from agent.skills import SkillLoader
        loader = SkillLoader(skills_dir)
        content = loader.get_content("workspace-discovery")
        # The YAML frontmatter delimiters should not be in the body
        # (the body is what comes AFTER the closing ---)
        lines = content.split("\n")
        # There should be at most 1 occurrence of "---" (not the yaml block)
        assert content.count("---") <= 1  # possibly 0

    def test_get_content_unknown_skill_returns_error(self, skills_dir):
        from agent.skills import SkillLoader
        loader = SkillLoader(skills_dir)
        content = loader.get_content("nonexistent-skill")
        # Should return an error message, not crash
        assert isinstance(content, str)
        assert "not found" in content.lower() or "unknown" in content.lower() or "error" in content.lower()


class TestSkillLoaderListNames:
    """Task 7.3: list_names() returns sorted list of skill names."""

    def test_list_names_returns_list(self, skills_dir):
        from agent.skills import SkillLoader
        loader = SkillLoader(skills_dir)
        names = loader.list_names()
        assert isinstance(names, list)

    def test_list_names_sorted(self, skills_dir):
        from agent.skills import SkillLoader
        loader = SkillLoader(skills_dir)
        names = loader.list_names()
        assert names == sorted(names)

    def test_list_names_empty_when_no_skills(self, empty_skills_dir):
        from agent.skills import SkillLoader
        loader = SkillLoader(empty_skills_dir)
        assert loader.list_names() == []


class TestSkillsIsLeaf:
    """skills.py must have zero imports from other agent/ modules."""

    def test_no_agent_imports(self):
        import agent.skills as mod
        with open(mod.__file__) as f:
            source = f.read()
        import re
        agent_imports = re.findall(r"from\s+agent\.", source)
        assert agent_imports == [], (
            f"skills.py must not import from agent modules: {agent_imports}"
        )
