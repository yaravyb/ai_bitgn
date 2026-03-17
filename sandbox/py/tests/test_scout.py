"""Tests for agent.scout -- Reactive DAG scout phase.

TDD: Tests written BEFORE implementation.
Task 9.1: ScoutSummary dataclass, imports from dag/dispatch/tracker only
Task 9.2: run_scout() wave loop with seed, ready, execute, react
Task 9.3: Reactor rules (tree -> read/list, list -> read/list, read -> read redirect)
Task 9.4: Meta-file detection regex patterns
Task 9.5: Numbered file detection (group by prefix+ext, 3+ sequential, read highest)
Task 9.6: Wave observability logging
"""

import json
import re
import logging
import pytest
from dataclasses import fields as dc_fields
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Helper: build canned VM responses for the mock dispatch
# ---------------------------------------------------------------------------

def _tree_response(folders: list[str], files: list[str]) -> str:
    """Build a JSON tree response matching OutlineResponse protobuf format.

    OutlineResponse has: path (str), folders (list[str]), files (list[Outline])
    where Outline has: path (str), headers (list[str])
    """
    file_entries = [{"path": f, "headers": []} for f in files]
    return json.dumps({"path": "/", "folders": folders, "files": file_entries})


def _list_response(folders: list[str], files: list[str]) -> str:
    """Build a JSON list_dir response matching ListResponse protobuf format.

    ListResponse has: folders (list[str]), files (list[str])
    """
    return json.dumps({"folders": folders, "files": files})


def _read_response(content: str) -> str:
    """Build a JSON read_file response."""
    return json.dumps({"content": content})


def _make_dispatch_side_effect(responses: dict[str, str]):
    """Create a side_effect function for dispatch_tool that returns canned responses.

    responses: dict mapping (tool_name, path) -> response_json
    """
    def side_effect(vm, tool_name, args, tracker, protected_files, skill_loader=None):
        path = args.get("path", "/")
        key = (tool_name, path)
        if key in responses:
            # Track the file if it's a read (tree is directory op, not tracked)
            if tool_name == "read_file":
                tracker.add(path)
            return responses[key]
        # Default empty responses
        if tool_name == "tree":
            return _tree_response([], [])
        if tool_name == "list_dir":
            return _list_response([], [])
        if tool_name == "read_file":
            tracker.add(path)
            return _read_response("")
        return "{}"
    return side_effect


# ---------------------------------------------------------------------------
# Task 9.1: ScoutSummary dataclass
# ---------------------------------------------------------------------------

class TestScoutSummaryDataclass:
    """Task 9.1: ScoutSummary has the expected fields."""

    def test_scout_summary_exists(self):
        from agent.scout import ScoutSummary
        assert ScoutSummary is not None

    def test_scout_summary_fields(self):
        from agent.scout import ScoutSummary
        field_names = {f.name for f in dc_fields(ScoutSummary)}
        expected = {"directory_tree", "policy_files", "vault_skills", "files_read", "folders_explored"}
        assert field_names == expected

    def test_scout_summary_construction(self):
        from agent.scout import ScoutSummary
        summary = ScoutSummary(
            directory_tree="root\n  workspace/\n  skills/",
            policy_files={"AGENTS.MD": "See README.MD"},
            vault_skills={"skills/skill-todo.md": "todo skill content"},
            files_read={"AGENTS.MD", "README.MD"},
            folders_explored=["workspace", "skills"],
        )
        assert summary.directory_tree.startswith("root")
        assert "AGENTS.MD" in summary.policy_files
        assert "skills/skill-todo.md" in summary.vault_skills
        assert "AGENTS.MD" in summary.files_read
        assert "workspace" in summary.folders_explored


class TestScoutModuleDependencies:
    """Task 9.1: scout.py imports from dag, dispatch, tracker only."""

    def test_no_llm_import(self):
        import agent.scout as mod
        with open(mod.__file__) as f:
            source = f.read()
        agent_imports = re.findall(r"from\s+agent\.(\w+)", source)
        forbidden = {"llm", "prompt", "skills", "loop"}
        for imp in agent_imports:
            assert imp not in forbidden, (
                f"scout.py imports from agent.{imp}, "
                f"only dag, dispatch, tracker are allowed"
            )

    def test_allowed_imports_only(self):
        import agent.scout as mod
        with open(mod.__file__) as f:
            source = f.read()
        agent_imports = re.findall(r"from\s+agent\.(\w+)", source)
        allowed = {"dag", "dispatch", "tracker"}
        for imp in agent_imports:
            assert imp in allowed, (
                f"scout.py imports from agent.{imp}, "
                f"only {allowed} are allowed"
            )


# ---------------------------------------------------------------------------
# Task 9.2: run_scout wave loop
# ---------------------------------------------------------------------------

class TestRunScoutBasic:
    """Task 9.2: run_scout creates graph, seeds with tree, runs wave loop."""

    @patch("agent.scout.dispatch_tool")
    def test_run_scout_returns_scout_summary(self, mock_dispatch):
        from agent.scout import run_scout, ScoutSummary
        from agent.tracker import GroundingTracker

        mock_dispatch.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): _tree_response([], []),
        })

        vm = MagicMock()
        tracker = GroundingTracker()
        result = run_scout(vm, tracker)
        assert isinstance(result, ScoutSummary)

    @patch("agent.scout.dispatch_tool")
    def test_run_scout_calls_tree_root(self, mock_dispatch):
        from agent.scout import run_scout
        from agent.tracker import GroundingTracker

        mock_dispatch.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): _tree_response([], []),
        })

        vm = MagicMock()
        tracker = GroundingTracker()
        run_scout(vm, tracker)

        # Should have called dispatch_tool with tree and path "/"
        tree_calls = [
            c for c in mock_dispatch.call_args_list
            if c[0][1] == "tree" or (len(c[0]) > 1 and c[0][1] == "tree")
        ]
        assert len(tree_calls) >= 1

    @patch("agent.scout.dispatch_tool")
    def test_run_scout_populates_directory_tree(self, mock_dispatch):
        from agent.scout import run_scout
        from agent.tracker import GroundingTracker

        tree_output = _tree_response(["workspace", "skills"], ["AGENTS.MD"])
        mock_dispatch.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): tree_output,
        })

        vm = MagicMock()
        tracker = GroundingTracker()
        result = run_scout(vm, tracker)
        assert result.directory_tree != ""

    @patch("agent.scout.dispatch_tool")
    def test_run_scout_terminates_on_empty_workspace(self, mock_dispatch):
        """Scout should terminate when no pending tasks remain."""
        from agent.scout import run_scout
        from agent.tracker import GroundingTracker

        mock_dispatch.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): _tree_response([], []),
        })

        vm = MagicMock()
        tracker = GroundingTracker()
        result = run_scout(vm, tracker)
        assert isinstance(result.files_read, set)


# ---------------------------------------------------------------------------
# Task 9.3: Reactor rules
# ---------------------------------------------------------------------------

class TestReactorTreeCompletion:
    """Task 9.3: tree completion spawns read for AGENTS.MD and list for folders."""

    @patch("agent.scout.dispatch_tool")
    def test_tree_spawns_read_for_agents_md(self, mock_dispatch):
        from agent.scout import run_scout
        from agent.tracker import GroundingTracker

        mock_dispatch.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): _tree_response(["workspace"], ["AGENTS.MD"]),
            ("read_file", "/AGENTS.MD"): _read_response("Agent policies here"),
            ("list_dir", "/workspace"): _list_response([], []),
        })

        vm = MagicMock()
        tracker = GroundingTracker()
        result = run_scout(vm, tracker)

        # AGENTS.MD should have been read
        assert "AGENTS.MD" in result.policy_files or any(
            "agents" in k.lower() for k in result.policy_files
        )

    @patch("agent.scout.dispatch_tool")
    def test_tree_spawns_list_for_each_folder(self, mock_dispatch):
        from agent.scout import run_scout
        from agent.tracker import GroundingTracker

        mock_dispatch.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): _tree_response(["workspace", "data", "skills"], ["AGENTS.MD"]),
            ("read_file", "/AGENTS.MD"): _read_response("Policies"),
            ("list_dir", "/workspace"): _list_response([], []),
            ("list_dir", "/data"): _list_response([], []),
            ("list_dir", "/skills"): _list_response([], []),
        })

        vm = MagicMock()
        tracker = GroundingTracker()
        result = run_scout(vm, tracker)

        # All three folders should be explored
        assert len(result.folders_explored) >= 3


class TestReactorListCompletion:
    """Task 9.3: list completion spawns read for meta-files and list for subfolders."""

    @patch("agent.scout.dispatch_tool")
    def test_list_spawns_read_for_meta_files(self, mock_dispatch):
        from agent.scout import run_scout
        from agent.tracker import GroundingTracker

        mock_dispatch.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): _tree_response(["workspace"], []),
            ("list_dir", "/workspace"): _list_response(
                [], ["RULES.md", "data.txt"]
            ),
            ("read_file", "/workspace/RULES.md"): _read_response("Some rules"),
        })

        vm = MagicMock()
        tracker = GroundingTracker()
        result = run_scout(vm, tracker)

        # RULES.md should be in policy_files
        matching = [k for k in result.policy_files if "RULES" in k.upper()]
        assert len(matching) >= 1

    @patch("agent.scout.dispatch_tool")
    def test_list_spawns_list_for_subfolders(self, mock_dispatch):
        from agent.scout import run_scout
        from agent.tracker import GroundingTracker

        mock_dispatch.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): _tree_response(["workspace"], []),
            ("list_dir", "/workspace"): _list_response(["subfolder"], []),
            ("list_dir", "/workspace/subfolder"): _list_response([], []),
        })

        vm = MagicMock()
        tracker = GroundingTracker()
        result = run_scout(vm, tracker)

        # The subfolder should have been listed
        # We verify by checking that list_dir was called for the subfolder
        list_calls = [
            c for c in mock_dispatch.call_args_list
            if c[0][1] == "list_dir" and "subfolder" in str(c[0][2])
        ]
        assert len(list_calls) >= 1

    @patch("agent.scout.dispatch_tool")
    def test_list_spawns_read_for_skill_files(self, mock_dispatch):
        """Files matching skill-*.* should be read as vault skills."""
        from agent.scout import run_scout
        from agent.tracker import GroundingTracker

        mock_dispatch.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): _tree_response(["skills"], []),
            ("list_dir", "/skills"): _list_response(
                [], ["skill-todo.md", "_rules.txt"]
            ),
            ("read_file", "/skills/skill-todo.md"): _read_response("Todo skill"),
            ("read_file", "/skills/_rules.txt"): _read_response("Rules here"),
        })

        vm = MagicMock()
        tracker = GroundingTracker()
        result = run_scout(vm, tracker)

        # skill-todo.md should be in vault_skills
        matching = [k for k in result.vault_skills if "skill-todo" in k]
        assert len(matching) >= 1


class TestReactorReadCompletion:
    """Task 9.3: read completion spawns read for redirect targets."""

    @patch("agent.scout.dispatch_tool")
    def test_read_spawns_read_for_redirect(self, mock_dispatch):
        from agent.scout import run_scout
        from agent.tracker import GroundingTracker

        mock_dispatch.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): _tree_response([], ["AGENTS.MD"]),
            ("read_file", "/AGENTS.MD"): _read_response("See README.MD"),
            ("read_file", "/README.MD"): _read_response("Actual policies here"),
        })

        vm = MagicMock()
        tracker = GroundingTracker()
        result = run_scout(vm, tracker)

        # README.MD should also have been read as a policy file
        readme_found = any("README" in k for k in result.policy_files)
        assert readme_found, f"Expected README.MD in policy_files, got: {list(result.policy_files.keys())}"


# ---------------------------------------------------------------------------
# Task 9.4: Meta-file detection
# ---------------------------------------------------------------------------

class TestMetaFileDetection:
    """Task 9.4: Meta-file detection using regex patterns (case-insensitive)."""

    def test_meta_patterns_exist(self):
        from agent.scout import META_PATTERNS
        assert isinstance(META_PATTERNS, list)
        assert len(META_PATTERNS) >= 8  # 8 patterns from design

    @pytest.mark.parametrize("filename,expected", [
        ("_rules.md", True),
        ("_rules.txt", True),
        ("_RULES.MD", True),
        ("RULES.md", True),
        ("Rules.txt", True),
        ("skill-todo.md", True),
        ("SKILL-TEMPLATE.txt", True),
        ("_config.yaml", True),
        ("_config.json", True),
        ("_meta.md", True),
        ("_META.json", True),
        ("AGENTS.MD", True),
        ("agents.md", True),
        ("README.md", True),
        ("readme.txt", True),
        ("formatting.rules", True),
        ("naming.rules", True),
        # Non-meta files
        ("data.txt", False),
        ("report.pdf", False),
        ("PAY-1.md", False),
        ("invoice.csv", False),
    ])
    def test_is_meta_file(self, filename, expected):
        from agent.scout import is_meta_file
        result = is_meta_file(filename)
        assert result == expected, f"is_meta_file('{filename}') should be {expected}"


# ---------------------------------------------------------------------------
# Task 9.5: Numbered file detection
# ---------------------------------------------------------------------------

class TestNumberedFileDetection:
    """Task 9.5: Group files by prefix+ext, 3+ sequential -> read highest only."""

    def test_detect_numbered_group(self):
        from agent.scout import detect_numbered_files
        files = ["PAY-1.md", "PAY-2.md", "PAY-3.md", "PAY-12.md", "RULES.md"]
        result = detect_numbered_files(files)
        # Should return a dict: {prefix_key: highest_filename}
        assert isinstance(result, dict)
        # PAY group should exist with highest being PAY-12.md
        assert any("PAY-12.md" in v for v in result.values())

    def test_no_numbered_group_when_fewer_than_three(self):
        from agent.scout import detect_numbered_files
        files = ["PAY-1.md", "PAY-2.md", "RULES.md"]
        result = detect_numbered_files(files)
        # PAY group has only 2 members, should not be in result
        assert len(result) == 0

    def test_multiple_numbered_groups(self):
        from agent.scout import detect_numbered_files
        files = [
            "PAY-1.md", "PAY-2.md", "PAY-3.md",
            "LOG-001.txt", "LOG-002.txt", "LOG-003.txt",
            "README.md",
        ]
        result = detect_numbered_files(files)
        assert len(result) == 2  # Two groups: PAY and LOG
        # Each group should have its highest
        values = list(result.values())
        assert "PAY-3.md" in values
        assert "LOG-003.txt" in values

    def test_non_numbered_files_ignored(self):
        from agent.scout import detect_numbered_files
        files = ["README.md", "RULES.md", "config.yaml"]
        result = detect_numbered_files(files)
        assert len(result) == 0

    @patch("agent.scout.dispatch_tool")
    def test_scout_reads_only_highest_numbered(self, mock_dispatch):
        """When a numbered group is detected, scout reads only the highest."""
        from agent.scout import run_scout
        from agent.tracker import GroundingTracker

        mock_dispatch.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): _tree_response(["workspace"], []),
            ("list_dir", "/workspace"): _list_response(
                [], ["PAY-1.md", "PAY-2.md", "PAY-3.md", "PAY-12.md"]
            ),
            ("read_file", "/workspace/PAY-12.md"): _read_response("Payment 12"),
        })

        vm = MagicMock()
        tracker = GroundingTracker()
        result = run_scout(vm, tracker)

        # Should have read PAY-12.md (highest) but not PAY-1, PAY-2, PAY-3
        read_calls = [
            c for c in mock_dispatch.call_args_list
            if c[0][1] == "read_file"
        ]
        read_paths = [c[0][2].get("path", "") for c in read_calls]
        assert any("PAY-12" in p for p in read_paths), f"Should read PAY-12.md, got: {read_paths}"
        # Should NOT have read PAY-1, PAY-2, PAY-3
        for p in read_paths:
            assert "PAY-1.md" not in p or "PAY-12" in p, f"Should not read PAY-1.md, got: {read_paths}"
            assert "PAY-2" not in p, f"Should not read PAY-2.md, got: {read_paths}"
            assert "PAY-3" not in p, f"Should not read PAY-3.md, got: {read_paths}"


# ---------------------------------------------------------------------------
# Task 9.6: Wave observability logging
# ---------------------------------------------------------------------------

class TestWaveObservability:
    """Task 9.6: Logging of wave number, tasks, spawned provenance, cancellations."""

    @patch("agent.scout.dispatch_tool")
    def test_logs_wave_number(self, mock_dispatch, capsys):
        from agent.scout import run_scout
        from agent.tracker import GroundingTracker

        mock_dispatch.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): _tree_response([], []),
        })

        vm = MagicMock()
        tracker = GroundingTracker()
        run_scout(vm, tracker)

        captured = capsys.readouterr()
        assert "wave 1" in captured.out.lower(), (
            f"Expected wave logging in stdout, got: {captured.out[:500]}"
        )

    @patch("agent.scout.dispatch_tool")
    def test_logs_spawned_tasks(self, mock_dispatch, capsys):
        from agent.scout import run_scout
        from agent.tracker import GroundingTracker

        mock_dispatch.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): _tree_response(["workspace"], ["AGENTS.MD"]),
            ("read_file", "/AGENTS.MD"): _read_response("Policy"),
            ("list_dir", "/workspace"): _list_response([], []),
        })

        vm = MagicMock()
        tracker = GroundingTracker()
        run_scout(vm, tracker)

        captured = capsys.readouterr()
        assert "spawn" in captured.out.lower(), (
            f"Expected spawn logging in stdout, got: {captured.out[:500]}"
        )


# ---------------------------------------------------------------------------
# Integration: full workspace scenario
# ---------------------------------------------------------------------------

class TestScoutFullScenario:
    """Integration test: scout explores a realistic workspace."""

    @patch("agent.scout.dispatch_tool")
    def test_full_workspace_exploration(self, mock_dispatch):
        """Simulate a workspace with AGENTS.MD redirect, meta-files, skills, numbered files."""
        from agent.scout import run_scout
        from agent.tracker import GroundingTracker

        mock_dispatch.side_effect = _make_dispatch_side_effect({
            # Wave 1: tree root
            ("tree", "/"): _tree_response(
                ["workspace", "skills", "data"], ["AGENTS.MD"]
            ),
            # Wave 2: read AGENTS.MD (redirect), list folders
            ("read_file", "/AGENTS.MD"): _read_response("See README.MD"),
            ("list_dir", "/workspace"): _list_response(
                [], ["RULES.md", "PAY-1.md", "PAY-2.md", "PAY-3.md", "PAY-12.md"]
            ),
            ("list_dir", "/skills"): _list_response(
                [], ["skill-todo.md", "_rules.txt"]
            ),
            ("list_dir", "/data"): _list_response([], ["report.csv"]),
            # Wave 3: follow redirect, read meta-files, read highest numbered
            ("read_file", "/README.MD"): _read_response("# Main Policy\nDo good things."),
            ("read_file", "/workspace/RULES.md"): _read_response("Naming: PAY-N.md"),
            ("read_file", "/workspace/PAY-12.md"): _read_response("Payment 12 content"),
            ("read_file", "/skills/skill-todo.md"): _read_response("Todo skill content"),
            ("read_file", "/skills/_rules.txt"): _read_response("Skills rules"),
        })

        vm = MagicMock()
        tracker = GroundingTracker()
        result = run_scout(vm, tracker)

        # Verify ScoutSummary
        assert result.directory_tree != ""

        # Policy files should include AGENTS.MD, README.MD, RULES.md, _rules.txt
        policy_paths = set(result.policy_files.keys())
        assert any("AGENTS" in p for p in policy_paths), f"Missing AGENTS.MD in {policy_paths}"
        assert any("README" in p for p in policy_paths), f"Missing README.MD in {policy_paths}"
        assert any("RULES" in p for p in policy_paths), f"Missing RULES in {policy_paths}"

        # Vault skills should include skill-todo.md
        assert any("skill-todo" in p for p in result.vault_skills), (
            f"Missing skill-todo in vault_skills: {list(result.vault_skills.keys())}"
        )

        # files_read should have all read files
        assert len(result.files_read) >= 5  # At least AGENTS, README, RULES, PAY-12, skill-todo

        # folders_explored should have all three top-level folders
        assert len(result.folders_explored) >= 3

    @patch("agent.scout.dispatch_tool")
    def test_scout_populates_tracker(self, mock_dispatch):
        """The tracker should contain all files read during scout."""
        from agent.scout import run_scout
        from agent.tracker import GroundingTracker

        mock_dispatch.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): _tree_response(["workspace"], ["AGENTS.MD"]),
            ("read_file", "/AGENTS.MD"): _read_response("Policy"),
            ("list_dir", "/workspace"): _list_response([], ["RULES.md"]),
            ("read_file", "/workspace/RULES.md"): _read_response("Rules"),
        })

        vm = MagicMock()
        tracker = GroundingTracker()
        run_scout(vm, tracker)

        # Tracker should have files added during scout (read operations only)
        assert len(tracker) >= 2  # At least AGENTS.MD and RULES.md

    @patch("agent.scout.dispatch_tool")
    def test_scout_handles_empty_tree(self, mock_dispatch):
        """Scout should handle gracefully when tree returns nothing."""
        from agent.scout import run_scout
        from agent.tracker import GroundingTracker

        mock_dispatch.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): _tree_response([], []),
        })

        vm = MagicMock()
        tracker = GroundingTracker()
        result = run_scout(vm, tracker)

        assert result.policy_files == {}
        assert result.vault_skills == {}
        assert result.folders_explored == []
