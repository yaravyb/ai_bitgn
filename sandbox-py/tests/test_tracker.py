"""Tests for agent.tracker -- GroundingTracker.

TDD: Tests written BEFORE implementation.
Task 2.1: GroundingTracker class with add, add_many, merge, all, __len__, __repr__
Task 2.2: Path normalization -- strip leading /, resolve .., lowercase for comparison, preserve casing
Task 2.3: merge() returns sorted union, never empty if files were read
"""

import pytest


class TestGroundingTrackerBasic:
    """Task 2.1: Core API."""

    def test_empty_tracker_has_length_zero(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        assert len(t) == 0

    def test_add_single_path(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("workspace/file.txt")
        assert len(t) == 1

    def test_add_duplicate_path_does_not_increase_count(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("workspace/file.txt")
        t.add("workspace/file.txt")
        assert len(t) == 1

    def test_all_returns_set_copy(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("a.md")
        t.add("b.md")
        result = t.all()
        assert isinstance(result, set)
        assert result == {"a.md", "b.md"}
        # Must be a copy, not the internal set
        result.add("c.md")
        assert len(t) == 2

    def test_add_many(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add_many(["a.md", "b.md", "c.md"])
        assert len(t) == 3

    def test_add_many_with_duplicates(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("a.md")
        t.add_many(["a.md", "b.md"])
        assert len(t) == 2

    def test_repr_contains_count(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("a.md")
        t.add("b.md")
        r = repr(t)
        assert "2" in r
        assert "GroundingTracker" in r


class TestPathNormalization:
    """Task 2.2: Path normalization rules."""

    def test_strip_leading_slash(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("/workspace/file.txt")
        assert "workspace/file.txt" in t.all()

    def test_resolve_dotdot(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("workspace/../workspace/file.txt")
        result = t.all()
        assert "workspace/file.txt" in result

    def test_leading_slash_and_dotdot(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("/workspace/../data/file.txt")
        result = t.all()
        assert "data/file.txt" in result

    def test_case_insensitive_dedup(self):
        """Lowercase used for comparison, but original casing is preserved."""
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("AGENTS.MD")
        t.add("agents.md")
        # Should be treated as the same file
        assert len(t) == 1

    def test_preserves_original_casing(self):
        """The first casing encountered should be preserved."""
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("AGENTS.MD")
        result = t.all()
        # At least one of the casings should be present
        assert len(result) == 1
        # The stored value should be the first one added
        assert "AGENTS.MD" in result

    def test_second_casing_does_not_override(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("AGENTS.MD")
        t.add("agents.md")
        result = t.all()
        assert len(result) == 1
        assert "AGENTS.MD" in result

    def test_normalize_double_slashes(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("//workspace//file.txt")
        result = t.all()
        assert "workspace/file.txt" in result


class TestMerge:
    """Task 2.3: merge() returns sorted union, never empty."""

    def test_merge_with_no_llm_refs(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("b.md")
        t.add("a.md")
        result = t.merge([])
        assert result == ["a.md", "b.md"]

    def test_merge_unions_llm_refs_and_tracked(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("a.md")
        result = t.merge(["b.md", "c.md"])
        assert "a.md" in result
        assert "b.md" in result
        assert "c.md" in result

    def test_merge_deduplicates(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("a.md")
        result = t.merge(["a.md", "b.md"])
        assert result.count("a.md") == 1

    def test_merge_result_is_sorted(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("z.md")
        t.add("a.md")
        result = t.merge(["m.md"])
        assert result == sorted(result)

    def test_merge_never_empty_when_files_read(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("a.md")
        # Even if LLM provides empty list, merge should include tracked files
        result = t.merge([])
        assert len(result) > 0

    def test_merge_empty_when_nothing_read(self):
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        result = t.merge([])
        assert result == []

    def test_merge_normalizes_llm_refs(self):
        """LLM refs should also be normalized."""
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("a.md")
        result = t.merge(["/b.md"])
        assert "b.md" in result

    def test_merge_deduplicates_across_casing(self):
        """If tracker has AGENTS.MD and LLM provides agents.md, no duplicate."""
        from agent.tracker import GroundingTracker
        t = GroundingTracker()
        t.add("AGENTS.MD")
        result = t.merge(["agents.md"])
        # Should only have one entry for AGENTS.MD
        assert len(result) == 1


class TestTrackerIsLeaf:
    """tracker.py must have zero imports from other agent/ modules."""

    def test_no_agent_imports(self):
        import agent.tracker as mod
        with open(mod.__file__) as f:
            source = f.read()
        import re
        agent_imports = re.findall(r"from\s+agent\.", source)
        assert agent_imports == [], (
            f"tracker.py must not import from agent modules: {agent_imports}"
        )
