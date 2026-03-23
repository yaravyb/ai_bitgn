"""Tests for agent.scout -- Two-phase LLM scout.

Task 9: Rewritten for two-phase architecture.
Tests for: ScoutConfig, BootstrapContext, ScoutSummary (new fields),
_run_bootstrap, _run_llm_explorer, run_scout, SCOUT_TOOL_SCHEMAS,
build_scout_prompt, module import assertions.
TestMetaFileDetection retained unchanged.
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
    """Build a JSON tree response matching OutlineResponse protobuf format."""
    file_entries = [{"path": f, "headers": []} for f in files]
    return json.dumps({"path": "/", "folders": folders, "files": file_entries})


def _list_response(folders: list[str], files: list[str]) -> str:
    """Build a JSON list_dir response matching ListResponse protobuf format."""
    return json.dumps({"folders": folders, "files": files})


def _read_response(content: str) -> str:
    """Build a JSON read_file response."""
    return json.dumps({"content": content})


def _make_dispatch_side_effect(responses: dict[str, str]):
    """Create a side_effect function for dispatch_tool that returns canned responses."""
    def side_effect(vm, tool_name, args, tracker, protected_files, skill_loader=None, context_config=None):
        path = args.get("path", "/")
        key = (tool_name, path)
        if key in responses:
            if tool_name == "read_file":
                tracker.add(path)
            return responses[key]
        if tool_name == "tree":
            return _tree_response([], [])
        if tool_name == "list_dir":
            return _list_response([], [])
        if tool_name == "read_file":
            tracker.add(path)
            return _read_response("")
        return "{}"
    return side_effect


def _make_llm_response(content=None, tool_calls=None):
    """Create a mock LLMResponse."""
    mock = MagicMock()
    mock.content = content
    mock.tool_calls = tool_calls or []
    mock.raw = None
    return mock


def _make_tool_call(tc_id, name, arguments):
    """Create a mock ToolCall."""
    mock = MagicMock()
    mock.id = tc_id
    mock.name = name
    mock.arguments = arguments
    return mock


# ---------------------------------------------------------------------------
# Task 9: ScoutConfig dataclass
# ---------------------------------------------------------------------------

class TestScoutConfig:
    """ScoutConfig has correct fields, defaults, and required params."""

    def test_scout_config_exists(self):
        from agent.scout import ScoutConfig
        assert ScoutConfig is not None

    def test_scout_config_fields(self):
        from agent.scout import ScoutConfig
        field_names = {f.name for f in dc_fields(ScoutConfig)}
        assert field_names == {"model", "task_instruction", "max_steps", "max_workers"}

    def test_scout_config_required_params(self):
        from agent.scout import ScoutConfig
        # model and task_instruction are required
        with pytest.raises(TypeError):
            ScoutConfig()
        with pytest.raises(TypeError):
            ScoutConfig(model="test-model")
        with pytest.raises(TypeError):
            ScoutConfig(task_instruction="test task")

    def test_scout_config_defaults(self):
        from agent.scout import ScoutConfig
        config = ScoutConfig(model="openai/gpt-4.1", task_instruction="do something")
        assert config.max_steps == 20
        assert config.max_workers == 4

    def test_scout_config_custom_values(self):
        from agent.scout import ScoutConfig
        config = ScoutConfig(
            model="openai/gpt-4.1-mini",
            task_instruction="find invoices",
            max_steps=10,
            max_workers=2,
        )
        assert config.model == "openai/gpt-4.1-mini"
        assert config.task_instruction == "find invoices"
        assert config.max_steps == 10
        assert config.max_workers == 2


# ---------------------------------------------------------------------------
# Task 9: BootstrapContext dataclass
# ---------------------------------------------------------------------------

class TestBootstrapContext:
    """BootstrapContext has correct fields and construction."""

    def test_bootstrap_context_exists(self):
        from agent.scout import BootstrapContext
        assert BootstrapContext is not None

    def test_bootstrap_context_fields(self):
        from agent.scout import BootstrapContext
        field_names = {f.name for f in dc_fields(BootstrapContext)}
        expected = {
            "directory_tree", "root_policy_files", "root_vault_skills",
            "files_read", "folders_discovered",
        }
        assert field_names == expected

    def test_bootstrap_context_construction(self):
        from agent.scout import BootstrapContext
        ctx = BootstrapContext(
            directory_tree="tree output",
            root_policy_files={"AGENTS.MD": "policy"},
            root_vault_skills={"skill-todo.md": "skill"},
            files_read={"AGENTS.MD", "skill-todo.md"},
            folders_discovered=["workspace"],
        )
        assert ctx.directory_tree == "tree output"
        assert "AGENTS.MD" in ctx.root_policy_files
        assert "skill-todo.md" in ctx.root_vault_skills
        assert len(ctx.files_read) == 2
        assert "workspace" in ctx.folders_discovered


# ---------------------------------------------------------------------------
# Task 9: ScoutSummary -- existing + new fields
# ---------------------------------------------------------------------------

class TestScoutSummaryDataclass:
    """ScoutSummary has existing fields + new LLM metadata fields."""

    def test_scout_summary_exists(self):
        from agent.scout import ScoutSummary
        assert ScoutSummary is not None

    def test_scout_summary_existing_fields(self):
        from agent.scout import ScoutSummary
        field_names = {f.name for f in dc_fields(ScoutSummary)}
        existing = {"directory_tree", "policy_files", "vault_skills", "files_read", "folders_explored"}
        assert existing.issubset(field_names)

    def test_scout_summary_new_fields(self):
        from agent.scout import ScoutSummary
        field_names = {f.name for f in dc_fields(ScoutSummary)}
        new_fields = {"llm_summary", "mode", "total_llm_steps", "completed_fully"}
        assert new_fields.issubset(field_names)

    def test_scout_summary_backward_compat(self):
        """Constructing with only existing fields still works."""
        from agent.scout import ScoutSummary
        summary = ScoutSummary(
            directory_tree="tree",
            policy_files={"p.md": "content"},
            vault_skills={},
            files_read={"p.md"},
            folders_explored=["workspace"],
        )
        assert summary.directory_tree == "tree"
        assert summary.llm_summary is None
        assert summary.mode == "llm"
        assert summary.total_llm_steps == 0
        assert summary.completed_fully is False

    def test_scout_summary_all_fields(self):
        from agent.scout import ScoutSummary
        summary = ScoutSummary(
            directory_tree="tree",
            policy_files={"p.md": "content"},
            vault_skills={"skill-a.md": "skill"},
            files_read={"p.md", "skill-a.md"},
            folders_explored=["workspace"],
            llm_summary="Found 3 policy files",
            mode="llm",
            total_llm_steps=5,
            completed_fully=True,
        )
        assert summary.llm_summary == "Found 3 policy files"
        assert summary.mode == "llm"
        assert summary.total_llm_steps == 5
        assert summary.completed_fully is True

    def test_scout_summary_default_construction(self):
        """Empty ScoutSummary() should work with all defaults."""
        from agent.scout import ScoutSummary
        summary = ScoutSummary()
        assert summary.directory_tree == ""
        assert summary.policy_files == {}
        assert summary.vault_skills == {}
        assert isinstance(summary.files_read, set)
        assert isinstance(summary.folders_explored, list)
        assert summary.llm_summary is None
        assert summary.mode == "llm"
        assert summary.total_llm_steps == 0
        assert summary.completed_fully is False


# ---------------------------------------------------------------------------
# Task 9: _run_bootstrap tests
# ---------------------------------------------------------------------------

class TestRunBootstrap:
    """Phase 1: _run_bootstrap calls tree, reads root files, returns BootstrapContext."""

    @patch("agent.scout.dispatch_tool")
    def test_calls_tree_root(self, mock_dispatch):
        from agent.scout import _run_bootstrap
        from agent.tracker import GroundingTracker

        mock_dispatch.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): _tree_response(["workspace"], ["AGENTS.MD"]),
        })

        vm = MagicMock()
        tracker = GroundingTracker()
        _run_bootstrap(vm, tracker, set())

        tree_calls = [
            c for c in mock_dispatch.call_args_list
            if c[0][1] == "tree"
        ]
        assert len(tree_calls) >= 1

    @patch("agent.scout.dispatch_tool")
    def test_reads_root_md_files(self, mock_dispatch):
        from agent.scout import _run_bootstrap
        from agent.tracker import GroundingTracker

        mock_dispatch.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): _tree_response(["workspace"], ["AGENTS.MD", "README.txt"]),
            ("read_file", "/AGENTS.MD"): _read_response("Policy content"),
            ("read_file", "/README.txt"): _read_response("Readme content"),
        })

        vm = MagicMock()
        tracker = GroundingTracker()
        ctx = _run_bootstrap(vm, tracker, set())

        read_calls = [
            c for c in mock_dispatch.call_args_list
            if c[0][1] == "read_file"
        ]
        assert len(read_calls) >= 2

    @patch("agent.scout.dispatch_tool")
    def test_classifies_policy_files(self, mock_dispatch):
        from agent.scout import _run_bootstrap
        from agent.tracker import GroundingTracker

        mock_dispatch.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): _tree_response(["workspace"], ["AGENTS.MD"]),
            ("read_file", "/AGENTS.MD"): _read_response("Policy"),
        })

        vm = MagicMock()
        tracker = GroundingTracker()
        ctx = _run_bootstrap(vm, tracker, set())

        # AGENTS.MD is a meta-file, should be in root_policy_files
        assert any("AGENTS" in k for k in ctx.root_policy_files)

    @patch("agent.scout.dispatch_tool")
    def test_classifies_vault_skills(self, mock_dispatch):
        from agent.scout import _run_bootstrap
        from agent.tracker import GroundingTracker

        mock_dispatch.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): _tree_response([], ["skill-todo.md"]),
            ("read_file", "/skill-todo.md"): _read_response("Todo skill"),
        })

        vm = MagicMock()
        tracker = GroundingTracker()
        ctx = _run_bootstrap(vm, tracker, set())

        assert any("skill-todo" in k for k in ctx.root_vault_skills)

    @patch("agent.scout.dispatch_tool")
    def test_returns_bootstrap_context(self, mock_dispatch):
        from agent.scout import _run_bootstrap, BootstrapContext
        from agent.tracker import GroundingTracker

        mock_dispatch.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): _tree_response(["workspace", "data"], ["AGENTS.MD"]),
            ("read_file", "/AGENTS.MD"): _read_response("Policy"),
        })

        vm = MagicMock()
        tracker = GroundingTracker()
        ctx = _run_bootstrap(vm, tracker, set())

        assert isinstance(ctx, BootstrapContext)
        assert ctx.directory_tree != ""
        assert "workspace" in ctx.folders_discovered
        assert "data" in ctx.folders_discovered

    @patch("agent.scout.dispatch_tool")
    def test_handles_empty_tree(self, mock_dispatch):
        from agent.scout import _run_bootstrap
        from agent.tracker import GroundingTracker

        mock_dispatch.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): _tree_response([], []),
        })

        vm = MagicMock()
        tracker = GroundingTracker()
        ctx = _run_bootstrap(vm, tracker, set())

        assert ctx.root_policy_files == {}
        assert ctx.root_vault_skills == {}
        assert ctx.folders_discovered == []

    @patch("agent.scout.dispatch_tool")
    def test_handles_tree_error(self, mock_dispatch):
        from agent.scout import _run_bootstrap, BootstrapContext
        from agent.tracker import GroundingTracker

        mock_dispatch.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): json.dumps({"error": "connection refused"}),
        })

        vm = MagicMock()
        tracker = GroundingTracker()
        ctx = _run_bootstrap(vm, tracker, set())

        assert isinstance(ctx, BootstrapContext)

    @patch("agent.scout.dispatch_tool")
    def test_skips_non_text_root_files(self, mock_dispatch):
        from agent.scout import _run_bootstrap
        from agent.tracker import GroundingTracker

        mock_dispatch.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): _tree_response([], ["AGENTS.MD", "data.csv", "image.png"]),
            ("read_file", "/AGENTS.MD"): _read_response("Policy"),
        })

        vm = MagicMock()
        tracker = GroundingTracker()
        ctx = _run_bootstrap(vm, tracker, set())

        # Only AGENTS.MD should be read, not data.csv or image.png
        read_calls = [
            c for c in mock_dispatch.call_args_list
            if c[0][1] == "read_file"
        ]
        assert len(read_calls) == 1


# ---------------------------------------------------------------------------
# Task 9: _format_bootstrap_for_prompt tests
# ---------------------------------------------------------------------------

class TestFormatBootstrapForPrompt:
    """_format_bootstrap_for_prompt produces readable string."""

    def test_includes_tree(self):
        from agent.scout import _format_bootstrap_for_prompt, BootstrapContext
        ctx = BootstrapContext(
            directory_tree='{"path": "/", "folders": ["workspace"]}',
            root_policy_files={},
            root_vault_skills={},
            files_read=set(),
            folders_discovered=["workspace"],
        )
        result = _format_bootstrap_for_prompt(ctx)
        assert "workspace" in result

    def test_includes_policy_file_contents(self):
        from agent.scout import _format_bootstrap_for_prompt, BootstrapContext
        ctx = BootstrapContext(
            directory_tree="tree",
            root_policy_files={"AGENTS.MD": "Follow the rules"},
            root_vault_skills={},
            files_read={"AGENTS.MD"},
            folders_discovered=[],
        )
        result = _format_bootstrap_for_prompt(ctx)
        assert "AGENTS.MD" in result
        assert "Follow the rules" in result


# ---------------------------------------------------------------------------
# Task 9: _run_llm_explorer tests
# ---------------------------------------------------------------------------

class TestRunLlmExplorer:
    """Phase 2: LLM explorer loop."""

    @patch("agent.scout.dispatch_parallel")
    @patch("agent.scout.call_llm")
    @patch("agent.scout.build_scout_prompt")
    def test_calls_call_llm_with_scout_tool_schemas(
        self, mock_prompt, mock_call_llm, mock_dispatch,
    ):
        from agent.scout import _run_llm_explorer, ScoutConfig, BootstrapContext
        from agent.tools import SCOUT_TOOL_SCHEMAS
        from agent.tracker import GroundingTracker

        mock_prompt.return_value = "scout prompt"
        mock_call_llm.return_value = _make_llm_response(content="Done exploring")

        config = ScoutConfig(model="openai/gpt-4.1", task_instruction="test task")
        bootstrap = BootstrapContext(
            directory_tree="tree", root_policy_files={},
            root_vault_skills={}, files_read=set(),
            folders_discovered=[],
        )

        vm = MagicMock()
        tracker = GroundingTracker()
        _run_llm_explorer(vm, tracker, config, bootstrap, set())

        # Verify call_llm was called with SCOUT_TOOL_SCHEMAS
        llm_call = mock_call_llm.call_args
        tools_arg = llm_call[1].get("tools") or llm_call[0][2]
        assert tools_arg is SCOUT_TOOL_SCHEMAS

    @patch("agent.scout.dispatch_parallel")
    @patch("agent.scout.call_llm")
    @patch("agent.scout.build_scout_prompt")
    def test_terminates_on_text_response(
        self, mock_prompt, mock_call_llm, mock_dispatch,
    ):
        from agent.scout import _run_llm_explorer, ScoutConfig, BootstrapContext
        from agent.tracker import GroundingTracker

        mock_prompt.return_value = "scout prompt"
        mock_call_llm.return_value = _make_llm_response(content="Exploration summary")

        config = ScoutConfig(model="openai/gpt-4.1", task_instruction="test")
        bootstrap = BootstrapContext(
            directory_tree="tree", root_policy_files={},
            root_vault_skills={}, files_read=set(),
            folders_discovered=[],
        )

        vm = MagicMock()
        tracker = GroundingTracker()
        result = _run_llm_explorer(vm, tracker, config, bootstrap, set())

        llm_summary, total_steps, completed_fully, reads, folders = result
        assert llm_summary == "Exploration summary"
        assert completed_fully is True
        assert total_steps == 1

    @patch("agent.scout.dispatch_parallel")
    @patch("agent.scout.call_llm")
    @patch("agent.scout.build_scout_prompt")
    def test_terminates_on_step_limit(
        self, mock_prompt, mock_call_llm, mock_dispatch,
    ):
        from agent.scout import _run_llm_explorer, ScoutConfig, BootstrapContext
        from agent.tracker import GroundingTracker

        mock_prompt.return_value = "scout prompt"

        # Always return tool calls (never text-only)
        tc = _make_tool_call("tc1", "read_file", {"path": "/test.md"})
        mock_call_llm.return_value = _make_llm_response(content=None, tool_calls=[tc])
        mock_dispatch.return_value = [("tc1", _read_response("content"))]

        config = ScoutConfig(model="openai/gpt-4.1", task_instruction="test", max_steps=3)
        bootstrap = BootstrapContext(
            directory_tree="tree", root_policy_files={},
            root_vault_skills={}, files_read=set(),
            folders_discovered=[],
        )

        vm = MagicMock()
        tracker = GroundingTracker()
        result = _run_llm_explorer(vm, tracker, config, bootstrap, set())

        llm_summary, total_steps, completed_fully, reads, folders = result
        assert completed_fully is False
        assert total_steps == 3
        assert llm_summary is None

    @patch("agent.scout.dispatch_parallel")
    @patch("agent.scout.call_llm")
    @patch("agent.scout.build_scout_prompt")
    def test_accumulates_read_file_results(
        self, mock_prompt, mock_call_llm, mock_dispatch,
    ):
        from agent.scout import _run_llm_explorer, ScoutConfig, BootstrapContext
        from agent.tracker import GroundingTracker

        mock_prompt.return_value = "scout prompt"

        tc1 = _make_tool_call("tc1", "read_file", {"path": "/workspace/rules.md"})
        tc2 = _make_tool_call("tc2", "read_file", {"path": "/data/report.md"})

        mock_call_llm.side_effect = [
            _make_llm_response(content=None, tool_calls=[tc1, tc2]),
            _make_llm_response(content="Done"),
        ]
        mock_dispatch.return_value = [
            ("tc1", _read_response("rules content")),
            ("tc2", _read_response("report content")),
        ]

        config = ScoutConfig(model="openai/gpt-4.1", task_instruction="test")
        bootstrap = BootstrapContext(
            directory_tree="tree", root_policy_files={},
            root_vault_skills={}, files_read=set(),
            folders_discovered=[],
        )

        vm = MagicMock()
        tracker = GroundingTracker()
        result = _run_llm_explorer(vm, tracker, config, bootstrap, set())

        llm_summary, total_steps, completed_fully, reads, folders = result
        assert len(reads) >= 2

    @patch("agent.scout.dispatch_parallel")
    @patch("agent.scout.call_llm")
    @patch("agent.scout.build_scout_prompt")
    def test_tracks_list_dir_folders(
        self, mock_prompt, mock_call_llm, mock_dispatch,
    ):
        from agent.scout import _run_llm_explorer, ScoutConfig, BootstrapContext
        from agent.tracker import GroundingTracker

        mock_prompt.return_value = "scout prompt"

        tc1 = _make_tool_call("tc1", "list_dir", {"path": "/workspace"})

        mock_call_llm.side_effect = [
            _make_llm_response(content=None, tool_calls=[tc1]),
            _make_llm_response(content="Done"),
        ]
        mock_dispatch.return_value = [
            ("tc1", _list_response(["sub"], ["file.md"])),
        ]

        config = ScoutConfig(model="openai/gpt-4.1", task_instruction="test")
        bootstrap = BootstrapContext(
            directory_tree="tree", root_policy_files={},
            root_vault_skills={}, files_read=set(),
            folders_discovered=[],
        )

        vm = MagicMock()
        tracker = GroundingTracker()
        result = _run_llm_explorer(vm, tracker, config, bootstrap, set())

        llm_summary, total_steps, completed_fully, reads, folders = result
        assert "/workspace" in folders

    @patch("agent.scout.dispatch_parallel")
    @patch("agent.scout.call_llm")
    @patch("agent.scout.build_scout_prompt")
    def test_uses_separate_trace_metadata(
        self, mock_prompt, mock_call_llm, mock_dispatch,
    ):
        from agent.scout import _run_llm_explorer, ScoutConfig, BootstrapContext
        from agent.tracker import GroundingTracker

        mock_prompt.return_value = "scout prompt"
        mock_call_llm.return_value = _make_llm_response(content="Done")

        config = ScoutConfig(model="openai/gpt-4.1", task_instruction="test")
        bootstrap = BootstrapContext(
            directory_tree="tree", root_policy_files={},
            root_vault_skills={}, files_read=set(),
            folders_discovered=[],
        )

        vm = MagicMock()
        tracker = GroundingTracker()
        _run_llm_explorer(vm, tracker, config, bootstrap, set())

        llm_call = mock_call_llm.call_args
        metadata = llm_call[1].get("metadata", {})
        assert "trace_id" in metadata
        assert metadata.get("trace_name") == "scout_llm_explorer"

    @patch("agent.scout.dispatch_parallel")
    @patch("agent.scout.call_llm")
    @patch("agent.scout.build_scout_prompt")
    def test_uses_dispatch_parallel_with_max_workers(
        self, mock_prompt, mock_call_llm, mock_dispatch,
    ):
        from agent.scout import _run_llm_explorer, ScoutConfig, BootstrapContext
        from agent.tracker import GroundingTracker

        mock_prompt.return_value = "scout prompt"

        tc = _make_tool_call("tc1", "read_file", {"path": "/test.md"})
        mock_call_llm.side_effect = [
            _make_llm_response(content=None, tool_calls=[tc]),
            _make_llm_response(content="Done"),
        ]
        mock_dispatch.return_value = [("tc1", _read_response("content"))]

        config = ScoutConfig(model="openai/gpt-4.1", task_instruction="test", max_workers=2)
        bootstrap = BootstrapContext(
            directory_tree="tree", root_policy_files={},
            root_vault_skills={}, files_read=set(),
            folders_discovered=[],
        )

        vm = MagicMock()
        tracker = GroundingTracker()
        _run_llm_explorer(vm, tracker, config, bootstrap, set())

        dp_call = mock_dispatch.call_args
        assert dp_call[1].get("max_workers") == 2 or (len(dp_call[0]) >= 5 and dp_call[0][4] == 2)


# ---------------------------------------------------------------------------
# Task 9: run_scout (two-phase orchestration)
# ---------------------------------------------------------------------------

class TestRunScoutBasic:
    """run_scout orchestrates Phase 1 -> Phase 2 -> summary build."""

    @patch("agent.scout.dispatch_parallel")
    @patch("agent.scout.call_llm")
    @patch("agent.scout.build_scout_prompt")
    @patch("agent.scout.dispatch_tool")
    def test_run_scout_returns_scout_summary(
        self, mock_dispatch_tool, mock_prompt, mock_call_llm, mock_dispatch_parallel,
    ):
        from agent.scout import run_scout, ScoutSummary, ScoutConfig
        from agent.tracker import GroundingTracker

        mock_dispatch_tool.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): _tree_response([], []),
        })
        mock_prompt.return_value = "scout prompt"
        mock_call_llm.return_value = _make_llm_response(content="Done exploring")

        vm = MagicMock()
        tracker = GroundingTracker()
        config = ScoutConfig(model="openai/gpt-4.1", task_instruction="test task")
        result = run_scout(vm, tracker, config)
        assert isinstance(result, ScoutSummary)

    @patch("agent.scout.dispatch_parallel")
    @patch("agent.scout.call_llm")
    @patch("agent.scout.build_scout_prompt")
    @patch("agent.scout.dispatch_tool")
    def test_run_scout_populates_directory_tree(
        self, mock_dispatch_tool, mock_prompt, mock_call_llm, mock_dispatch_parallel,
    ):
        from agent.scout import run_scout, ScoutConfig
        from agent.tracker import GroundingTracker

        tree_output = _tree_response(["workspace", "skills"], ["AGENTS.MD"])
        mock_dispatch_tool.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): tree_output,
            ("read_file", "/AGENTS.MD"): _read_response("Policy"),
        })
        mock_prompt.return_value = "scout prompt"
        mock_call_llm.return_value = _make_llm_response(content="Done")

        vm = MagicMock()
        tracker = GroundingTracker()
        config = ScoutConfig(model="openai/gpt-4.1", task_instruction="test")
        result = run_scout(vm, tracker, config)
        assert result.directory_tree != ""

    @patch("agent.scout.dispatch_parallel")
    @patch("agent.scout.call_llm")
    @patch("agent.scout.build_scout_prompt")
    @patch("agent.scout.dispatch_tool")
    def test_run_scout_has_llm_metadata(
        self, mock_dispatch_tool, mock_prompt, mock_call_llm, mock_dispatch_parallel,
    ):
        from agent.scout import run_scout, ScoutConfig
        from agent.tracker import GroundingTracker

        mock_dispatch_tool.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): _tree_response([], []),
        })
        mock_prompt.return_value = "scout prompt"
        mock_call_llm.return_value = _make_llm_response(content="Summary text")

        vm = MagicMock()
        tracker = GroundingTracker()
        config = ScoutConfig(model="openai/gpt-4.1", task_instruction="test")
        result = run_scout(vm, tracker, config)

        assert result.llm_summary == "Summary text"
        assert result.mode == "llm"
        assert result.total_llm_steps >= 1
        assert result.completed_fully is True

    @patch("agent.scout.dispatch_parallel")
    @patch("agent.scout.call_llm")
    @patch("agent.scout.build_scout_prompt")
    @patch("agent.scout.dispatch_tool")
    def test_run_scout_merges_files_read(
        self, mock_dispatch_tool, mock_prompt, mock_call_llm, mock_dispatch_parallel,
    ):
        from agent.scout import run_scout, ScoutConfig
        from agent.tracker import GroundingTracker

        mock_dispatch_tool.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): _tree_response([], ["AGENTS.MD"]),
            ("read_file", "/AGENTS.MD"): _read_response("Policy"),
        })
        mock_prompt.return_value = "scout prompt"

        tc = _make_tool_call("tc1", "read_file", {"path": "/data.md"})
        mock_call_llm.side_effect = [
            _make_llm_response(content=None, tool_calls=[tc]),
            _make_llm_response(content="Done"),
        ]
        mock_dispatch_parallel.return_value = [("tc1", _read_response("data content"))]

        vm = MagicMock()
        tracker = GroundingTracker()
        config = ScoutConfig(model="openai/gpt-4.1", task_instruction="test")
        result = run_scout(vm, tracker, config)

        # files_read should include files from both phases
        assert len(result.files_read) >= 1  # at least AGENTS.MD from Phase 1


# ---------------------------------------------------------------------------
# Task 9: Integration test
# ---------------------------------------------------------------------------

class TestScoutFullScenario:
    """Integration test: scout explores a realistic workspace."""

    @patch("agent.scout.dispatch_parallel")
    @patch("agent.scout.call_llm")
    @patch("agent.scout.build_scout_prompt")
    @patch("agent.scout.dispatch_tool")
    def test_full_workspace_exploration(
        self, mock_dispatch_tool, mock_prompt, mock_call_llm, mock_dispatch_parallel,
    ):
        from agent.scout import run_scout, ScoutConfig
        from agent.tracker import GroundingTracker

        mock_dispatch_tool.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): _tree_response(
                ["workspace", "skills", "data"], ["AGENTS.MD"]
            ),
            ("read_file", "/AGENTS.MD"): _read_response("See README.MD"),
        })
        mock_prompt.return_value = "scout prompt"

        # LLM explorer reads additional files
        tc_readme = _make_tool_call("tc1", "read_file", {"path": "/README.MD"})
        tc_rules = _make_tool_call("tc2", "read_file", {"path": "/workspace/RULES.md"})
        tc_skill = _make_tool_call("tc3", "read_file", {"path": "/skills/skill-todo.md"})
        tc_list = _make_tool_call("tc4", "list_dir", {"path": "/workspace"})

        mock_call_llm.side_effect = [
            _make_llm_response(content=None, tool_calls=[tc_readme, tc_rules, tc_skill, tc_list]),
            _make_llm_response(content="Exploration complete. Found policy files and skills."),
        ]
        mock_dispatch_parallel.return_value = [
            ("tc1", _read_response("# Main Policy\nDo good things.")),
            ("tc2", _read_response("Naming: PAY-N.md")),
            ("tc3", _read_response("Todo skill content")),
            ("tc4", _list_response([], ["PAY-1.md", "PAY-12.md"])),
        ]

        vm = MagicMock()
        tracker = GroundingTracker()
        config = ScoutConfig(model="openai/gpt-4.1", task_instruction="Find invoices")
        result = run_scout(vm, tracker, config)

        assert result.directory_tree != ""
        assert result.llm_summary is not None
        assert result.mode == "llm"
        assert result.completed_fully is True
        assert result.total_llm_steps == 2

        # Policy files should include AGENTS.MD from Phase 1
        assert any("AGENTS" in p for p in result.policy_files)
        # Vault skills from Phase 2
        assert any("skill-todo" in p for p in result.vault_skills)
        # Folders explored from Phase 2
        assert "/workspace" in result.folders_explored or "workspace" in result.folders_explored

    @patch("agent.scout.dispatch_parallel")
    @patch("agent.scout.call_llm")
    @patch("agent.scout.build_scout_prompt")
    @patch("agent.scout.dispatch_tool")
    def test_scout_handles_empty_workspace(
        self, mock_dispatch_tool, mock_prompt, mock_call_llm, mock_dispatch_parallel,
    ):
        from agent.scout import run_scout, ScoutConfig
        from agent.tracker import GroundingTracker

        mock_dispatch_tool.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): _tree_response([], []),
        })
        mock_prompt.return_value = "scout prompt"
        mock_call_llm.return_value = _make_llm_response(content="Empty workspace")

        vm = MagicMock()
        tracker = GroundingTracker()
        config = ScoutConfig(model="openai/gpt-4.1", task_instruction="test")
        result = run_scout(vm, tracker, config)

        assert result.policy_files == {}
        assert result.vault_skills == {}


# ---------------------------------------------------------------------------
# Task 9: SCOUT_TOOL_SCHEMAS test
# ---------------------------------------------------------------------------

class TestScoutToolSchemas:
    """SCOUT_TOOL_SCHEMAS contains exactly the read-only tools."""

    def test_contains_exactly_four_tools(self):
        from agent.tools import SCOUT_TOOL_SCHEMAS
        names = {s["function"]["name"] for s in SCOUT_TOOL_SCHEMAS}
        assert names == {"tree", "list_dir", "read_file", "search"}

    def test_is_subset_of_tool_schemas(self):
        from agent.tools import TOOL_SCHEMAS, SCOUT_TOOL_SCHEMAS
        for s in SCOUT_TOOL_SCHEMAS:
            assert s in TOOL_SCHEMAS


# ---------------------------------------------------------------------------
# Task 9: build_scout_prompt test
# ---------------------------------------------------------------------------

class TestBuildScoutPromptFromScout:
    """build_scout_prompt() accepts params and produces correct prompt."""

    def test_accepts_parameters(self):
        from agent.prompt import build_scout_prompt
        result = build_scout_prompt(
            task_instruction="Find invoices",
            bootstrap_context="tree output",
        )
        assert isinstance(result, str)
        assert "Find invoices" in result
        assert "tree output" in result

    def test_contains_role_section(self):
        from agent.prompt import build_scout_prompt
        result = build_scout_prompt(
            task_instruction="test",
            bootstrap_context="tree",
        )
        assert "reconnaissance" in result.lower()


# ---------------------------------------------------------------------------
# Task 9: Module import assertions
# ---------------------------------------------------------------------------

class TestScoutModuleDependencies:
    """scout.py imports from llm, tools, prompt, dispatch, tracker, context; NOT dag, skills, loop."""

    def test_imports_required_modules(self):
        import agent.scout as mod
        with open(mod.__file__) as f:
            source = f.read()
        agent_imports = re.findall(r"from\s+agent\.(\w+)", source)
        required = {"llm", "tools", "prompt", "dispatch", "tracker", "context"}
        for req in required:
            assert req in agent_imports, (
                f"scout.py must import from agent.{req}"
            )

    def test_no_forbidden_imports(self):
        import agent.scout as mod
        with open(mod.__file__) as f:
            source = f.read()
        agent_imports = re.findall(r"from\s+agent\.(\w+)", source)
        forbidden = {"dag", "skills", "loop"}
        for imp in agent_imports:
            assert imp not in forbidden, (
                f"scout.py must NOT import from agent.{imp}"
            )


# ---------------------------------------------------------------------------
# Context management integration tests (Task 11)
# ---------------------------------------------------------------------------

class TestScoutMicroCompact:
    """Micro-compact is applied in the scout LLM explorer loop."""

    @patch("agent.scout.micro_compact")
    @patch("agent.scout.dispatch_parallel")
    @patch("agent.scout.call_llm")
    @patch("agent.scout.build_scout_prompt")
    def test_micro_compact_called_before_llm(
        self, mock_prompt, mock_call_llm, mock_dispatch, mock_micro_compact,
    ):
        from agent.scout import _run_llm_explorer, ScoutConfig, BootstrapContext
        from agent.context import ContextConfig
        from agent.tracker import GroundingTracker

        mock_prompt.return_value = "scout prompt"

        tc = _make_tool_call("tc1", "read_file", {"path": "/test.md"})
        mock_call_llm.side_effect = [
            _make_llm_response(content=None, tool_calls=[tc]),
            _make_llm_response(content="Done"),
        ]
        mock_dispatch.return_value = [("tc1", _read_response("content"))]

        config = ScoutConfig(model="openai/gpt-4.1", task_instruction="test")
        ctx_config = ContextConfig()
        bootstrap = BootstrapContext(
            directory_tree="tree", root_policy_files={},
            root_vault_skills={}, files_read=set(),
            folders_discovered=[],
        )

        vm = MagicMock()
        tracker = GroundingTracker()
        _run_llm_explorer(vm, tracker, config, bootstrap, set(), context_config=ctx_config)

        # micro_compact should have been called at least twice (once per call_llm)
        assert mock_micro_compact.call_count >= 2


class TestScoutNoAutoCompact:
    """Auto-compact is NOT applied in the scout phase."""

    @patch("agent.scout.dispatch_parallel")
    @patch("agent.scout.call_llm")
    @patch("agent.scout.build_scout_prompt")
    def test_no_auto_compact_in_scout(
        self, mock_prompt, mock_call_llm, mock_dispatch,
    ):
        from agent.scout import _run_llm_explorer, ScoutConfig, BootstrapContext
        from agent.context import ContextConfig
        from agent.tracker import GroundingTracker

        mock_prompt.return_value = "scout prompt"

        # Return many tool calls to simulate a long conversation
        tc = _make_tool_call("tc1", "read_file", {"path": "/test.md"})
        mock_call_llm.side_effect = [
            _make_llm_response(content=None, tool_calls=[tc]),
            _make_llm_response(content="Done"),
        ]
        mock_dispatch.return_value = [("tc1", _read_response("x" * 100000))]

        config = ScoutConfig(model="openai/gpt-4.1", task_instruction="test")
        ctx_config = ContextConfig(auto_compact_threshold=1)  # Very low threshold
        bootstrap = BootstrapContext(
            directory_tree="tree", root_policy_files={},
            root_vault_skills={}, files_read=set(),
            folders_discovered=[],
        )

        vm = MagicMock()
        tracker = GroundingTracker()
        _run_llm_explorer(vm, tracker, config, bootstrap, set(), context_config=ctx_config)

        # Only 2 call_llm calls (no summarization call for auto-compact)
        assert mock_call_llm.call_count == 2


class TestScoutTruncationApplied:
    """Tool result truncation applies to scout tool calls."""

    @patch("agent.scout.dispatch_parallel")
    @patch("agent.scout.call_llm")
    @patch("agent.scout.build_scout_prompt")
    def test_context_config_passed_to_dispatch(
        self, mock_prompt, mock_call_llm, mock_dispatch,
    ):
        from agent.scout import _run_llm_explorer, ScoutConfig, BootstrapContext
        from agent.context import ContextConfig
        from agent.tracker import GroundingTracker

        mock_prompt.return_value = "scout prompt"

        tc = _make_tool_call("tc1", "read_file", {"path": "/test.md"})
        mock_call_llm.side_effect = [
            _make_llm_response(content=None, tool_calls=[tc]),
            _make_llm_response(content="Done"),
        ]
        mock_dispatch.return_value = [("tc1", _read_response("content"))]

        config = ScoutConfig(model="openai/gpt-4.1", task_instruction="test")
        ctx_config = ContextConfig(truncation_limit=5000)
        bootstrap = BootstrapContext(
            directory_tree="tree", root_policy_files={},
            root_vault_skills={}, files_read=set(),
            folders_discovered=[],
        )

        vm = MagicMock()
        tracker = GroundingTracker()
        _run_llm_explorer(vm, tracker, config, bootstrap, set(), context_config=ctx_config)

        # dispatch_parallel should have received context_config
        dp_call = mock_dispatch.call_args
        ctx_arg = dp_call[1].get("context_config")
        assert ctx_arg is not None

    @patch("agent.scout.dispatch_tool")
    @patch("agent.scout.dispatch_parallel")
    @patch("agent.scout.call_llm")
    @patch("agent.scout.build_scout_prompt")
    def test_bootstrap_passes_context_config(
        self, mock_prompt, mock_call_llm, mock_dispatch_parallel,
        mock_dispatch_tool,
    ):
        """run_scout passes context_config to bootstrap dispatch_tool calls."""
        from agent.scout import run_scout, ScoutConfig
        from agent.context import ContextConfig
        from agent.tracker import GroundingTracker

        mock_dispatch_tool.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): _tree_response([], []),
        })
        mock_prompt.return_value = "scout prompt"
        mock_call_llm.return_value = _make_llm_response(content="Done")

        vm = MagicMock()
        tracker = GroundingTracker()
        config = ScoutConfig(model="openai/gpt-4.1", task_instruction="test")
        ctx_config = ContextConfig(truncation_limit=5000)

        run_scout(vm, tracker, config, context_config=ctx_config)

        # dispatch_tool calls from bootstrap should have received context_config
        dt_calls = mock_dispatch_tool.call_args_list
        assert len(dt_calls) >= 1
        # At least the tree call should have context_config
        for dt_call in dt_calls:
            ctx = dt_call[1].get("context_config")
            assert ctx is not None


class TestScoutRunScoutContextConfigParam:
    """run_scout accepts context_config parameter."""

    @patch("agent.scout.dispatch_parallel")
    @patch("agent.scout.call_llm")
    @patch("agent.scout.build_scout_prompt")
    @patch("agent.scout.dispatch_tool")
    def test_run_scout_accepts_context_config(
        self, mock_dispatch_tool, mock_prompt, mock_call_llm, mock_dispatch_parallel,
    ):
        from agent.scout import run_scout, ScoutConfig, ScoutSummary
        from agent.context import ContextConfig
        from agent.tracker import GroundingTracker

        mock_dispatch_tool.side_effect = _make_dispatch_side_effect({
            ("tree", "/"): _tree_response([], []),
        })
        mock_prompt.return_value = "scout prompt"
        mock_call_llm.return_value = _make_llm_response(content="Done")

        vm = MagicMock()
        tracker = GroundingTracker()
        config = ScoutConfig(model="openai/gpt-4.1", task_instruction="test")
        ctx_config = ContextConfig()

        result = run_scout(vm, tracker, config, context_config=ctx_config)
        assert isinstance(result, ScoutSummary)


# ---------------------------------------------------------------------------
# Task 9: Meta-file detection (RETAINED UNCHANGED)
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
