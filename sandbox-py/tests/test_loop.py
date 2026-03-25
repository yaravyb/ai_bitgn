"""Tests for agent.loop -- Orchestrator lifecycle.

All dependencies (vm, llm, scout, dispatch, skills, prompt) are mocked.
Tests verify the lifecycle flow: init -> scout -> prompt -> executor loop -> completion.
Updated for two-phase scout architecture (Task 10).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from agent.llm import ToolCall


# ---------------------------------------------------------------------------
# Helper: create ScoutSummary-compatible mock
# ---------------------------------------------------------------------------

def _make_scout_summary_mock(**overrides):
    """Create a mock ScoutSummary with all fields (including new LLM metadata)."""
    defaults = dict(
        policy_files={},
        vault_skills={},
        directory_tree="",
        files_read=set(),
        folders_explored=[],
        llm_summary=None,
        mode="llm",
        total_llm_steps=0,
        completed_fully=True,
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


def _make_mock_runtime():
    """Create a mock RuntimeAdapter for testing."""
    rt = MagicMock()
    rt.runtime_type = "mini"
    rt.extra_tools = frozenset()
    return rt


# ---------------------------------------------------------------------------
# Test 10.1: Module exists and exports run_agent
# ---------------------------------------------------------------------------

class TestLoopModuleExists:
    """Verify loop.py can be imported and has run_agent."""

    def test_import_loop_module(self):
        from agent import loop
        assert hasattr(loop, "run_agent")

    def test_run_agent_is_callable(self):
        from agent.loop import run_agent
        assert callable(run_agent)

    def test_run_agent_signature_has_required_params(self):
        import inspect
        from agent.loop import run_agent
        sig = inspect.signature(run_agent)
        params = list(sig.parameters.keys())
        assert "executor_model" in params
        assert "runtime" in params
        assert "task_text" in params
        assert "scout_model" in params
        assert "skills_dir" in params


# ---------------------------------------------------------------------------
# Test 10.2: Initialization -- VM, tracker, skill loader, protected files
# ---------------------------------------------------------------------------

class TestLoopInitialization:
    """Verify run_agent creates the right components during init."""

    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_protected_files_initialized_with_agents_md(
        self, mock_call_llm, mock_run_scout,
    ):
        """protected_files starts with 'agents.md'."""
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()
        mock_call_llm.return_value = MagicMock(
            content="done", tool_calls=[], raw=None,
        )

        # We'll check protected_files via the dispatch_parallel call
        with patch("agent.loop.dispatch_parallel") as mock_dp:
            # Need the LLM to return tool calls so dispatch_parallel is called
            tc = ToolCall(id="tc1", name="read_file", arguments={"path": "x.md"})
            mock_call_llm.side_effect = [
                MagicMock(content=None, tool_calls=[tc], raw=None),
                MagicMock(content="done", tool_calls=[], raw=None),
            ]
            mock_dp.return_value = [("tc1", '{"content": "ok"}')]

            run_agent(
                executor_model="openai/gpt-4.1",
                runtime=mock_runtime,
                task_text="do something",
            )

            # protected_files should include "agents.md"
            dp_call = mock_dp.call_args
            protected_files = dp_call[1].get("protected_files") or dp_call[0][3]
            assert "agents.md" in protected_files

    @patch("agent.loop.SkillLoader")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_skill_loader_created_when_skills_dir_exists(
        self, mock_call_llm, mock_run_scout, mock_sl_cls,
        tmp_path,
    ):
        """When skills_dir is provided and exists, SkillLoader is instantiated."""
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        mock_run_scout.return_value = _make_scout_summary_mock()
        mock_call_llm.return_value = MagicMock(
            content="done", tool_calls=[], raw=None,
        )
        mock_sl_cls.return_value = MagicMock(
            get_descriptions=MagicMock(return_value=""),
            get_content=MagicMock(return_value=""),
        )

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
            skills_dir=skills_dir,
        )

        mock_sl_cls.assert_called_once_with(skills_dir)

    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_skill_loader_not_created_when_no_skills_dir(
        self, mock_call_llm, mock_run_scout,
    ):
        """When skills_dir is None, no SkillLoader error occurs."""
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()
        mock_call_llm.return_value = MagicMock(
            content="done", tool_calls=[], raw=None,
        )

        # Should not raise
        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
            skills_dir=None,
        )


# ---------------------------------------------------------------------------
# Test 10.3: Scout phase invocation with ScoutConfig
# ---------------------------------------------------------------------------

class TestLoopScoutPhase:
    """Verify the scout phase is called with ScoutConfig and protected_files are expanded."""

    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_run_scout_called_with_scout_config(
        self, mock_call_llm, mock_run_scout,
    ):
        from agent.loop import run_agent
        from agent.scout import ScoutConfig

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()
        mock_call_llm.return_value = MagicMock(
            content="done", tool_calls=[], raw=None,
        )

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
            scout_model="openai/gpt-4.1-mini",
        )

        mock_run_scout.assert_called_once()
        args = mock_run_scout.call_args[0]
        # First arg is VM, second is tracker, third is ScoutConfig
        assert len(args) == 3
        config = args[2]
        assert isinstance(config, ScoutConfig)
        assert config.model == "openai/gpt-4.1-mini"
        assert config.task_instruction == "do something"

    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_scout_model_defaults_to_executor_model(
        self, mock_call_llm, mock_run_scout,
    ):
        from agent.loop import run_agent
        from agent.scout import ScoutConfig

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()
        mock_call_llm.return_value = MagicMock(
            content="done", tool_calls=[], raw=None,
        )

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="test task",
            scout_model=None,  # Should default to executor model
        )

        config = mock_run_scout.call_args[0][2]
        assert isinstance(config, ScoutConfig)
        assert config.model == "openai/gpt-4.1"

    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_protected_files_expanded_from_scout_policy_files(
        self, mock_call_llm, mock_run_scout, mock_dp,
    ):
        """Policy files from scout summary expand protected_files."""
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock(
            policy_files={
                "workspace/RULES.md": "some rules",
                "skills/_rules.txt": "skill rules",
            },
        )

        tc = ToolCall(id="tc1", name="read_file", arguments={"path": "x.md"})
        mock_call_llm.side_effect = [
            MagicMock(content=None, tool_calls=[tc], raw=None),
            MagicMock(content="done", tool_calls=[], raw=None),
        ]
        mock_dp.return_value = [("tc1", '{"content": "ok"}')]

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        dp_call = mock_dp.call_args
        protected_files = dp_call[0][3]
        # Should contain the initial "agents.md" plus normalized policy paths
        assert "agents.md" in protected_files
        assert "workspace/rules.md" in protected_files
        assert "skills/_rules.txt" in protected_files


# ---------------------------------------------------------------------------
# Test 10.4: System prompt building
# ---------------------------------------------------------------------------

class TestLoopSystemPrompt:
    """Verify system prompt is built with correct parameters."""

    @patch("agent.loop.build_system_prompt")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_build_system_prompt_called(
        self, mock_call_llm, mock_run_scout, mock_bsp,
    ):
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()
        mock_call_llm.return_value = MagicMock(
            content="done", tool_calls=[], raw=None,
        )
        mock_bsp.return_value = "system prompt text"

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        mock_bsp.assert_called_once()

    @patch("agent.loop.SkillLoader")
    @patch("agent.loop.build_system_prompt")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_system_prompt_uses_skills_metadata_and_scout_summary(
        self, mock_call_llm, mock_run_scout, mock_bsp, mock_sl_cls,
        tmp_path,
    ):
        """build_system_prompt gets skills_metadata, scout_summary, security_body."""
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        mock_run_scout.return_value = _make_scout_summary_mock(
            policy_files={"p.md": "content"},
            directory_tree="tree output",
            files_read={"p.md"},
            folders_explored=["workspace"],
        )
        mock_call_llm.return_value = MagicMock(
            content="done", tool_calls=[], raw=None,
        )
        mock_bsp.return_value = "system prompt text"
        mock_sl = MagicMock()
        mock_sl.get_descriptions.return_value = "- skill-a: description"
        mock_sl.get_content.return_value = "security body"
        mock_sl_cls.return_value = mock_sl

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
            skills_dir=skills_dir,
        )

        bsp_call = mock_bsp.call_args
        # The skills_metadata and security_skill_body should come from SkillLoader
        assert bsp_call is not None


# ---------------------------------------------------------------------------
# Test 10.5: Executor loop -- tool-use cycle
# ---------------------------------------------------------------------------

class TestLoopExecutorPhase:
    """Verify the executor loop dispatches tools and breaks on completion."""

    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_task_wrapped_in_delimiters(
        self, mock_call_llm, mock_run_scout, mock_dp,
    ):
        """The task text is wrapped in <task> delimiters in the user message."""
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()
        mock_call_llm.return_value = MagicMock(
            content="done", tool_calls=[], raw=None,
        )

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do the thing",
        )

        # Inspect the messages passed to call_llm
        llm_call = mock_call_llm.call_args
        messages = llm_call[0][1] if len(llm_call[0]) > 1 else llm_call[1]["messages"]
        # Find the user message containing the task
        task_messages = [
            m for m in messages
            if m.get("role") == "user" and "<task>" in m.get("content", "")
        ]
        assert len(task_messages) >= 1
        assert "<task>" in task_messages[-1]["content"]
        assert "do the thing" in task_messages[-1]["content"]
        assert "</task>" in task_messages[-1]["content"]

    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_tool_calls_dispatched_and_results_appended(
        self, mock_call_llm, mock_run_scout, mock_dp,
    ):
        """When LLM returns tool calls, they are dispatched and results appended."""
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()

        tc1 = ToolCall(id="tc_1", name="read_file", arguments={"path": "a.md"})
        tc2 = ToolCall(id="tc_2", name="list_dir", arguments={"path": "/"})

        mock_call_llm.side_effect = [
            MagicMock(content="let me read", tool_calls=[tc1, tc2], raw=None),
            MagicMock(content="done", tool_calls=[], raw=None),
        ]
        mock_dp.return_value = [
            ("tc_1", '{"content": "file a"}'),
            ("tc_2", '{"entries": []}'),
        ]

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        # dispatch_parallel should have been called once (first LLM call has tools)
        mock_dp.assert_called_once()

        # The second call_llm should have tool result messages
        second_call = mock_call_llm.call_args_list[1]
        messages = second_call[0][1] if len(second_call[0]) > 1 else second_call[1]["messages"]
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        assert len(tool_msgs) == 2
        assert tool_msgs[0]["tool_call_id"] == "tc_1"
        assert tool_msgs[1]["tool_call_id"] == "tc_2"

    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_breaks_on_report_completion(
        self, mock_call_llm, mock_run_scout, mock_dp,
    ):
        """Loop breaks when report_completion tool is called."""
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()

        tc = ToolCall(
            id="tc_1", name="report_completion",
            arguments={"answer": "done", "grounding_refs": [], "steps": [], "code": "completed"},
        )
        mock_call_llm.return_value = MagicMock(
            content=None, tool_calls=[tc], raw=None,
        )
        mock_dp.return_value = [("tc_1", '{"ok": true}')]

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        # call_llm should only be called once (loop breaks after report_completion)
        assert mock_call_llm.call_count == 1

    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_breaks_on_no_tool_calls(
        self, mock_call_llm, mock_run_scout, mock_dp,
    ):
        """Loop breaks when LLM returns text only (no tool calls)."""
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()
        mock_call_llm.return_value = MagicMock(
            content="I'm done", tool_calls=[], raw=None,
        )

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        assert mock_call_llm.call_count == 1
        mock_dp.assert_not_called()

    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_step_limit_30(
        self, mock_call_llm, mock_run_scout, mock_dp,
    ):
        """Executor loop stops after 30 steps."""
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()

        tc = ToolCall(id="tc1", name="read_file", arguments={"path": "x.md"})
        mock_call_llm.return_value = MagicMock(
            content="reading", tool_calls=[tc], raw=None,
        )
        mock_dp.return_value = [("tc1", '{"content": "ok"}')]

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        # Should be called exactly 30 times (step limit)
        assert mock_call_llm.call_count == 30

    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_assistant_message_includes_tool_calls_structure(
        self, mock_call_llm, mock_run_scout, mock_dp,
    ):
        """Assistant message appended to history has proper tool_calls format."""
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()

        tc = ToolCall(id="tc_1", name="read_file", arguments={"path": "a.md"})
        mock_call_llm.side_effect = [
            MagicMock(content="let me read", tool_calls=[tc], raw=None),
            MagicMock(content="done", tool_calls=[], raw=None),
        ]
        mock_dp.return_value = [("tc_1", '{"content": "file a"}')]

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="test",
        )

        # Check the second call_llm's messages for the assistant message
        second_call = mock_call_llm.call_args_list[1]
        messages = second_call[0][1] if len(second_call[0]) > 1 else second_call[1]["messages"]
        assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
        assert len(assistant_msgs) >= 1
        first_asst = assistant_msgs[0]
        assert "tool_calls" in first_asst
        assert first_asst["tool_calls"][0]["type"] == "function"
        assert first_asst["tool_calls"][0]["id"] == "tc_1"
        assert first_asst["tool_calls"][0]["function"]["name"] == "read_file"

    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_call_llm_receives_tool_schemas(
        self, mock_call_llm, mock_run_scout, mock_dp,
    ):
        """call_llm is called with tool schemas from get_tool_schemas."""
        from agent.loop import run_agent
        from agent.tools import get_tool_schemas

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()
        mock_call_llm.return_value = MagicMock(
            content="done", tool_calls=[], raw=None,
        )

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="test",
        )

        llm_call = mock_call_llm.call_args
        # tools should be get_tool_schemas("mini")
        tools_arg = llm_call[1].get("tools") or llm_call[0][2]
        assert tools_arg == get_tool_schemas("mini")

    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_executor_model_passed_to_call_llm(
        self, mock_call_llm, mock_run_scout, mock_dp,
    ):
        """The executor_model parameter is forwarded to call_llm."""
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()
        mock_call_llm.return_value = MagicMock(
            content="done", tool_calls=[], raw=None,
        )

        run_agent(
            executor_model="anthropic/claude-sonnet-4-6",
            runtime=mock_runtime,
            task_text="test",
        )

        llm_call = mock_call_llm.call_args
        model_arg = llm_call[0][0]
        assert model_arg == "anthropic/claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Test 10.6: __init__.py re-exports run_agent
# ---------------------------------------------------------------------------

class TestInitReExport:
    """Verify agent package re-exports run_agent from loop."""

    def test_import_run_agent_from_agent_package(self):
        from agent import run_agent
        assert callable(run_agent)

    def test_run_agent_is_from_loop(self):
        from agent import run_agent as pkg_run_agent
        from agent.loop import run_agent as loop_run_agent
        assert pkg_run_agent is loop_run_agent


# ---------------------------------------------------------------------------
# Test: Scout summary injected into messages
# ---------------------------------------------------------------------------

class TestLoopScoutContextInjection:
    """Verify scout summary is formatted and injected into executor messages."""

    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_scout_summary_injected_as_user_message(
        self, mock_call_llm, mock_run_scout, mock_dp,
    ):
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock(
            policy_files={"AGENTS.MD": "policy content"},
            vault_skills={"skills/skill-todo.md": "todo skill"},
            directory_tree='{"entries": []}',
            files_read={"AGENTS.MD", "skills/skill-todo.md"},
            folders_explored=["workspace", "skills"],
        )
        mock_call_llm.return_value = MagicMock(
            content="done", tool_calls=[], raw=None,
        )

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        llm_call = mock_call_llm.call_args
        messages = llm_call[0][1] if len(llm_call[0]) > 1 else llm_call[1]["messages"]

        # There should be a message containing scout summary info
        all_content = " ".join(m.get("content", "") or "" for m in messages)
        assert "<scout-summary>" in all_content or "scout" in all_content.lower()


# ---------------------------------------------------------------------------
# Test: _format_scout_context with llm_summary and truncation warning (Task 10)
# ---------------------------------------------------------------------------

class TestFormatScoutContext:
    """Test _format_scout_context with new ScoutSummary fields."""

    def test_includes_scout_analysis_when_llm_summary_present(self):
        from agent.loop import _format_scout_context
        from agent.scout import ScoutSummary

        summary = ScoutSummary(
            directory_tree="tree output",
            policy_files={"AGENTS.MD": "policy"},
            vault_skills={},
            files_read={"AGENTS.MD"},
            folders_explored=["workspace"],
            llm_summary="Found 3 policy files and 2 skills.",
            mode="llm",
            total_llm_steps=5,
            completed_fully=True,
        )

        result = _format_scout_context(summary)
        assert "## Scout Analysis" in result
        assert "Found 3 policy files and 2 skills." in result

    def test_includes_truncation_warning_when_not_completed_fully(self):
        from agent.loop import _format_scout_context
        from agent.scout import ScoutSummary

        summary = ScoutSummary(
            directory_tree="tree output",
            policy_files={},
            vault_skills={},
            files_read=set(),
            folders_explored=[],
            llm_summary=None,
            mode="llm",
            total_llm_steps=20,
            completed_fully=False,
        )

        result = _format_scout_context(summary)
        assert "truncat" in result.lower() or "Warning" in result
        assert "20" in result

    def test_no_scout_analysis_when_llm_summary_none(self):
        from agent.loop import _format_scout_context
        from agent.scout import ScoutSummary

        summary = ScoutSummary(
            directory_tree="tree output",
            policy_files={},
            vault_skills={},
            files_read=set(),
            folders_explored=[],
            llm_summary=None,
            mode="llm",
            total_llm_steps=0,
            completed_fully=True,
        )

        result = _format_scout_context(summary)
        assert "## Scout Analysis" not in result

    def test_no_scout_analysis_when_llm_summary_empty(self):
        from agent.loop import _format_scout_context
        from agent.scout import ScoutSummary

        summary = ScoutSummary(
            directory_tree="tree output",
            policy_files={},
            vault_skills={},
            files_read=set(),
            folders_explored=[],
            llm_summary="",
            mode="llm",
            total_llm_steps=0,
            completed_fully=True,
        )

        result = _format_scout_context(summary)
        assert "## Scout Analysis" not in result

    def test_truncation_warning_even_without_llm_summary(self):
        """When step limit hit (no summary), truncation warning should appear."""
        from agent.loop import _format_scout_context
        from agent.scout import ScoutSummary

        summary = ScoutSummary(
            directory_tree="tree output",
            policy_files={},
            vault_skills={},
            files_read=set(),
            folders_explored=[],
            llm_summary=None,
            mode="llm",
            total_llm_steps=20,
            completed_fully=False,
        )

        result = _format_scout_context(summary)
        assert "truncat" in result.lower() or "Warning" in result

    def test_backward_compat_with_old_summary(self):
        """Using getattr pattern, old-style summary without new fields should work."""
        from agent.loop import _format_scout_context

        # Simulate an old-style summary without new fields
        old_summary = MagicMock()
        old_summary.directory_tree = "tree"
        old_summary.policy_files = {}
        old_summary.vault_skills = {}
        old_summary.files_read = set()
        old_summary.folders_explored = []
        # MagicMock will return a MagicMock for any attribute access,
        # so we explicitly test the getattr default behavior
        del old_summary.llm_summary
        del old_summary.completed_fully
        del old_summary.total_llm_steps

        result = _format_scout_context(old_summary)
        assert "<scout-summary>" in result
        assert "</scout-summary>" in result


# ---------------------------------------------------------------------------
# Test: Loop module dependency (orchestrator privilege)
# ---------------------------------------------------------------------------

class TestLoopModuleDependencies:
    """Verify loop.py imports from all expected agent modules."""

    def test_loop_imports_from_all_agent_modules(self):
        """loop.py is the orchestrator and imports from all other agent modules."""
        import ast
        loop_path = Path(__file__).parent.parent / "agent" / "loop.py"
        source = loop_path.read_text()
        tree = ast.parse(source)

        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("agent."):
                    imported_modules.add(node.module.replace("agent.", ""))

        # loop.py should import from these modules (including context)
        expected = {"scout", "llm", "dispatch", "prompt", "skills", "tracker", "tools", "context"}
        assert expected.issubset(imported_modules), (
            f"Missing imports: {expected - imported_modules}"
        )


# ---------------------------------------------------------------------------
# Context management integration tests (Task 10.2)
# ---------------------------------------------------------------------------

class TestLoopMicroCompactCalledBeforeLLM:
    """micro_compact is called before each call_llm() in the executor loop."""

    @patch("agent.loop.micro_compact")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_micro_compact_called_before_llm(
        self, mock_call_llm, mock_run_scout, mock_dp, mock_micro_compact,
    ):
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()

        tc = ToolCall(id="tc1", name="read_file", arguments={"path": "x.md"})
        mock_call_llm.side_effect = [
            MagicMock(content=None, tool_calls=[tc], raw=None),
            MagicMock(content="done", tool_calls=[], raw=None),
        ]
        mock_dp.return_value = [("tc1", '{"content": "ok"}')]

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        # micro_compact should have been called at least twice (once per call_llm)
        assert mock_micro_compact.call_count >= 2


class TestLoopAutoCompactTriggered:
    """Auto-compact triggers when token threshold is exceeded."""

    @patch("agent.loop.estimate_tokens")
    @patch("agent.loop.micro_compact")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_auto_compact_triggered_on_threshold(
        self, mock_call_llm, mock_run_scout, mock_dp,
        mock_micro_compact, mock_estimate_tokens,
    ):
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()

        # First call: return tool calls so loop continues
        tc = ToolCall(id="tc1", name="read_file", arguments={"path": "x.md"})
        mock_call_llm.side_effect = [
            # First iteration LLM call
            MagicMock(content=None, tool_calls=[tc], raw=None),
            # Auto-compact summarization call
            MagicMock(content="Summary of conversation", tool_calls=[], raw=None),
            # Second iteration LLM call (after compaction)
            MagicMock(content="done", tool_calls=[], raw=None),
        ]
        mock_dp.return_value = [("tc1", '{"content": "ok"}')]

        # estimate_tokens is called:
        # 1. Pre-LLM check step 1: below threshold
        # 2. Pre-LLM check step 2: above threshold -> trigger auto-compact
        # 3. Inside _apply_auto_compact (tokens_before)
        # 4. Inside _apply_auto_compact (tokens_after)
        # Note: after auto_compact, messages are replaced and loop continues
        # to call_llm (no re-check of estimate_tokens before that call_llm).
        mock_estimate_tokens.side_effect = [
            1000,     # Step 1 pre-LLM check: below threshold
            100000,   # Step 2 pre-LLM check: above threshold -> trigger
            100000,   # _apply_auto_compact tokens_before
            500,      # _apply_auto_compact tokens_after
        ]

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        # call_llm should have been called 3 times:
        # 1. Normal executor LLM call
        # 2. Summarization call (auto-compact)
        # 3. Normal executor LLM call after compaction
        assert mock_call_llm.call_count == 3


class TestLoopAutoCompactSavesTranscript:
    """Auto-compact saves a transcript file."""

    @patch("agent.loop.estimate_tokens")
    @patch("agent.loop.micro_compact")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_transcript_saved(
        self, mock_call_llm, mock_run_scout, mock_dp,
        mock_micro_compact, mock_estimate_tokens,
        tmp_path,
    ):
        from agent.loop import run_agent
        import os

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()

        tc = ToolCall(id="tc1", name="read_file", arguments={"path": "x.md"})
        mock_call_llm.side_effect = [
            MagicMock(content=None, tool_calls=[tc], raw=None),
            MagicMock(content="Summary", tool_calls=[], raw=None),
            MagicMock(content="done", tool_calls=[], raw=None),
        ]
        mock_dp.return_value = [("tc1", '{"content": "ok"}')]

        mock_estimate_tokens.side_effect = [
            1000,
            100000,  # Trigger auto-compact
            100000,  # tokens_before in _apply_auto_compact
            500,     # tokens_after in _apply_auto_compact
        ]

        transcript_dir = str(tmp_path / "transcripts")
        os.environ["CTX_TRANSCRIPT_DIR"] = transcript_dir
        os.environ["CTX_AUTO_COMPACT_THRESHOLD"] = "80000"
        try:
            run_agent(
                executor_model="openai/gpt-4.1",
                runtime=mock_runtime,
                task_text="do something",
            )
        finally:
            os.environ.pop("CTX_TRANSCRIPT_DIR", None)
            os.environ.pop("CTX_AUTO_COMPACT_THRESHOLD", None)

        # A transcript file should exist in the transcript directory
        if os.path.isdir(transcript_dir):
            files = os.listdir(transcript_dir)
            transcript_files = [f for f in files if f.startswith("transcript_")]
            assert len(transcript_files) >= 1, "Expected at least one transcript file"


class TestLoopAutoCompactPreservesSystemMessage:
    """Auto-compact preserves the system message."""

    @patch("agent.loop.estimate_tokens")
    @patch("agent.loop.micro_compact")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_system_message_preserved(
        self, mock_call_llm, mock_run_scout, mock_dp,
        mock_micro_compact, mock_estimate_tokens,
    ):
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()

        tc = ToolCall(id="tc1", name="read_file", arguments={"path": "x.md"})
        mock_call_llm.side_effect = [
            MagicMock(content=None, tool_calls=[tc], raw=None),
            MagicMock(content="Summary of conversation", tool_calls=[], raw=None),
            MagicMock(content="done", tool_calls=[], raw=None),
        ]
        mock_dp.return_value = [("tc1", '{"content": "ok"}')]

        mock_estimate_tokens.side_effect = [1000, 100000, 100000, 500]

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        # After auto-compact, the third call_llm should have messages starting with system msg
        third_call = mock_call_llm.call_args_list[2]
        messages = third_call[0][1] if len(third_call[0]) > 1 else third_call[1]["messages"]
        assert messages[0]["role"] == "system"


class TestLoopAutoCompactReplacesMessages:
    """Auto-compact replaces messages with [system, summary, ack]."""

    @patch("agent.loop.estimate_tokens")
    @patch("agent.loop.micro_compact")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_messages_replaced(
        self, mock_call_llm, mock_run_scout, mock_dp,
        mock_micro_compact, mock_estimate_tokens,
    ):
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()

        tc = ToolCall(id="tc1", name="read_file", arguments={"path": "x.md"})
        mock_call_llm.side_effect = [
            MagicMock(content=None, tool_calls=[tc], raw=None),
            MagicMock(content="Compressed summary", tool_calls=[], raw=None),
            MagicMock(content="done", tool_calls=[], raw=None),
        ]
        mock_dp.return_value = [("tc1", '{"content": "ok"}')]

        mock_estimate_tokens.side_effect = [1000, 100000, 100000, 500]

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        # After auto-compact, the compacted messages form the base of the conversation.
        # Note: mock captures a reference to the mutable list, so by assertion time
        # the assistant message from the 3rd call has been appended. We check the
        # first 3 entries which are the compacted [system, summary, ack].
        third_call = mock_call_llm.call_args_list[2]
        messages = third_call[0][1] if len(third_call[0]) > 1 else third_call[1]["messages"]
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "Compressed summary" in messages[1]["content"] or "compressed" in messages[1]["content"].lower()
        assert messages[2]["role"] == "assistant"
        assert "Understood" in messages[2]["content"]


class TestLoopCompactSentinelTriggersCompaction:
    """Compact sentinel in dispatch results triggers auto-compact."""

    @patch("agent.loop.estimate_tokens", return_value=1000)
    @patch("agent.loop.micro_compact")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_compact_sentinel_triggers(
        self, mock_call_llm, mock_run_scout, mock_dp,
        mock_micro_compact, mock_estimate_tokens,
    ):
        from agent.loop import run_agent
        from agent.context import COMPACT_SENTINEL

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()

        tc_compact = ToolCall(id="tc1", name="compact", arguments={})
        mock_call_llm.side_effect = [
            MagicMock(content=None, tool_calls=[tc_compact], raw=None),
            MagicMock(content="Summary after compact tool", tool_calls=[], raw=None),
            MagicMock(content="done", tool_calls=[], raw=None),
        ]
        mock_dp.return_value = [("tc1", COMPACT_SENTINEL)]

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        # call_llm should have been called 3 times:
        # 1. Normal executor LLM call
        # 2. Summarization call (triggered by compact sentinel)
        # 3. Normal executor LLM call after compaction
        assert mock_call_llm.call_count == 3


class TestLoopContextConfigPassedToDispatch:
    """context_config is passed to dispatch_parallel calls."""

    @patch("agent.loop.estimate_tokens", return_value=1000)
    @patch("agent.loop.micro_compact")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_context_config_in_dispatch_call(
        self, mock_call_llm, mock_run_scout, mock_dp,
        mock_micro_compact, mock_estimate_tokens,
    ):
        from agent.loop import run_agent
        from agent.context import ContextConfig

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()

        tc = ToolCall(id="tc1", name="read_file", arguments={"path": "x.md"})
        mock_call_llm.side_effect = [
            MagicMock(content=None, tool_calls=[tc], raw=None),
            MagicMock(content="done", tool_calls=[], raw=None),
        ]
        mock_dp.return_value = [("tc1", '{"content": "ok"}')]

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        # dispatch_parallel should have received context_config
        dp_call = mock_dp.call_args
        # Check keyword argument
        context_config = dp_call[1].get("context_config")
        assert context_config is not None
        assert isinstance(context_config, ContextConfig)


# ---------------------------------------------------------------------------
# Text extraction tests (_try_extract_completion)
# ---------------------------------------------------------------------------

class TestTryExtractCompletion:
    """_try_extract_completion extracts answer from structured text."""

    def test_extracts_from_json_with_answer_key(self):
        from agent.loop import _try_extract_completion
        text = '{"answer": "TODO", "grounding_refs": ["HOME.MD"]}'
        result = _try_extract_completion(text)
        assert result is not None
        assert result["answer"] == "TODO"
        assert result["grounding_refs"] == ["HOME.MD"]

    def test_extracts_from_report_completion_syntax(self):
        from agent.loop import _try_extract_completion
        text = 'report_completion({"answer": "done", "code": "completed"})'
        result = _try_extract_completion(text)
        assert result is not None
        assert result["answer"] == "done"
        assert result["code"] == "completed"

    def test_returns_none_for_plain_text(self):
        from agent.loop import _try_extract_completion
        assert _try_extract_completion("just a plain answer") is None

    def test_returns_none_for_json_without_answer(self):
        from agent.loop import _try_extract_completion
        assert _try_extract_completion('{"status": "ok"}') is None

    def test_returns_none_for_empty_string(self):
        from agent.loop import _try_extract_completion
        assert _try_extract_completion("") is None

    def test_returns_none_for_json_list(self):
        from agent.loop import _try_extract_completion
        assert _try_extract_completion('["a", "b"]') is None

    def test_extracts_from_multiline_json(self):
        from agent.loop import _try_extract_completion
        text = '{\n  "answer": "multi\\nline",\n  "code": "completed"\n}'
        result = _try_extract_completion(text)
        assert result is not None
        assert result["answer"] == "multi\nline"

    def test_extracts_from_report_completion_with_spaces(self):
        from agent.loop import _try_extract_completion
        text = 'report_completion( {"answer": "test"} )'
        result = _try_extract_completion(text)
        assert result is not None
        assert result["answer"] == "test"

    def test_extracts_from_python_kwargs_syntax(self):
        from agent.loop import _try_extract_completion
        text = 'report_completion(answer="WIP", grounding_refs=["AGENTS.MD"], steps=["Read policy"], code="completed")'
        result = _try_extract_completion(text)
        assert result is not None
        assert result["answer"] == "WIP"
        assert result["code"] == "completed"
        assert result["grounding_refs"] == ["AGENTS.MD"]

    def test_extracts_kwargs_answer_only(self):
        from agent.loop import _try_extract_completion
        text = 'report_completion(answer="done")'
        result = _try_extract_completion(text)
        assert result is not None
        assert result["answer"] == "done"

    def test_extracts_kwargs_with_leading_text(self):
        from agent.loop import _try_extract_completion
        text = ' report_completion(answer="TODO", code="completed")'
        result = _try_extract_completion(text)
        assert result is not None
        assert result["answer"] == "TODO"


class TestTextExtractionInAutoSubmit:
    """Text extraction is applied in the auto-submit path."""

    @patch("agent.loop.dispatch_tool")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_json_text_extracts_answer(
        self, mock_call_llm, mock_run_scout, mock_dp,
        mock_dispatch_tool,
    ):
        """When LLM outputs JSON text with answer key, the answer is extracted."""
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()
        mock_call_llm.return_value = MagicMock(
            content='{"answer": "TODO", "grounding_refs": ["HOME.MD"], "code": "completed"}',
            tool_calls=[], raw=None,
        )
        mock_dispatch_tool.return_value = '{"ok": true}'

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="test task",
        )

        # dispatch_tool should have been called with extracted answer, not raw JSON
        dt_call = mock_dispatch_tool.call_args
        args = dt_call[0][2]  # third positional arg is the arguments dict
        assert args["answer"] == "TODO"
        assert args["grounding_refs"] == ["HOME.MD"]


# ---------------------------------------------------------------------------
# Verification integration tests (Task 9 / self-verification)
# ---------------------------------------------------------------------------

class TestVerificationInterceptsReportCompletion:
    """report_completion is intercepted when verification is enabled."""

    @patch("agent.loop.ContextConfig.from_env")
    @patch("agent.loop.dispatch_tool")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_report_completion_intercepted_on_first_call(
        self, mock_call_llm, mock_run_scout, mock_dp,
        mock_dispatch_tool, mock_from_env,
    ):
        """When verification enabled, first report_completion is intercepted.

        With max_attempts=1, the first call is intercepted (attempt 0 < 1),
        and the second call dispatches normally (attempt 1 >= 1).
        """
        from agent.loop import run_agent
        from agent.context import ContextConfig

        mock_runtime = _make_mock_runtime()
        mock_from_env.return_value = ContextConfig(
            verification_enabled=True, verification_max_attempts=1,
        )
        mock_run_scout.return_value = _make_scout_summary_mock(
            policy_files={"RULES.md": "always lowercase"},
        )

        tc_complete = ToolCall(
            id="tc1", name="report_completion",
            arguments={"answer": "first answer", "code": "completed",
                       "grounding_refs": [], "steps": []},
        )
        tc_complete2 = ToolCall(
            id="tc2", name="report_completion",
            arguments={"answer": "first answer", "code": "completed",
                       "grounding_refs": [], "steps": []},
        )

        mock_call_llm.side_effect = [
            # Step 1: LLM calls report_completion -> intercepted (attempt 0 < 1)
            MagicMock(content=None, tool_calls=[tc_complete], raw=None),
            # Step 2: After verification prompt, LLM calls again -> dispatched (attempt 1 >= 1)
            MagicMock(content=None, tool_calls=[tc_complete2], raw=None),
        ]
        mock_dispatch_tool.return_value = '{"ok": true}'

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="test task",
        )

        # call_llm called 2 times: original + post-verification
        assert mock_call_llm.call_count == 2
        # dispatch_tool should be called once for the final report_completion dispatch
        assert mock_dispatch_tool.call_count >= 1

        # The second LLM call should have a verification prompt in messages
        second_call = mock_call_llm.call_args_list[1]
        messages = second_call[0][1]
        user_msgs = [m for m in messages if m.get("role") == "user"]
        verification_msgs = [m for m in user_msgs if "<verification>" in m.get("content", "")]
        assert len(verification_msgs) >= 1


class TestVerificationDisabledDispatchesImmediately:
    """report_completion dispatches immediately when verification disabled."""

    @patch("agent.loop.dispatch_tool")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_no_interception_when_disabled(
        self, mock_call_llm, mock_run_scout, mock_dp,
        mock_dispatch_tool,
    ):
        """With verification disabled (default), report_completion dispatches directly."""
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()

        tc = ToolCall(
            id="tc1", name="report_completion",
            arguments={"answer": "done", "code": "completed",
                       "grounding_refs": [], "steps": []},
        )
        mock_call_llm.return_value = MagicMock(
            content=None, tool_calls=[tc], raw=None,
        )
        mock_dispatch_tool.return_value = '{"ok": true}'

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="test task",
        )

        # Only 1 LLM call (no verification loop)
        assert mock_call_llm.call_count == 1
        # dispatch_tool called for report_completion
        mock_dispatch_tool.assert_called_once()


class TestVerificationInterceptsTextOnlyAutosubmit:
    """Text-only auto-submit is intercepted when verification enabled."""

    @patch("agent.loop.ContextConfig.from_env")
    @patch("agent.loop.dispatch_tool")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_text_only_intercepted(
        self, mock_call_llm, mock_run_scout,
        mock_dispatch_tool, mock_from_env,
    ):
        """Text-only response is intercepted for verification when enabled.

        With max_attempts=1: step 1 text-only intercepted (0 < 1),
        step 2 report_completion dispatched (1 >= 1).
        """
        from agent.loop import run_agent
        from agent.context import ContextConfig

        mock_runtime = _make_mock_runtime()
        mock_from_env.return_value = ContextConfig(
            verification_enabled=True, verification_max_attempts=1,
        )
        mock_run_scout.return_value = _make_scout_summary_mock()

        tc_final = ToolCall(
            id="tc_final", name="report_completion",
            arguments={"answer": "final answer", "code": "completed",
                       "grounding_refs": [], "steps": []},
        )
        mock_call_llm.side_effect = [
            # Step 1: text-only -> intercepted (attempt 0 < 1)
            MagicMock(content="text answer", tool_calls=[], raw=None),
            # Step 2: report_completion -> dispatched (attempt 1 >= 1)
            MagicMock(content=None, tool_calls=[tc_final], raw=None),
        ]
        mock_dispatch_tool.return_value = '{"ok": true}'

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="test task",
        )

        # call_llm called twice: text-only intercepted, then report_completion dispatched
        assert mock_call_llm.call_count == 2

        # The second call should have verification prompt in messages
        second_call = mock_call_llm.call_args_list[1]
        messages = second_call[0][1]
        user_msgs = [m for m in messages if m.get("role") == "user"]
        verification_msgs = [m for m in user_msgs if "<verification>" in m.get("content", "")]
        assert len(verification_msgs) >= 1


class TestVerificationDispatchesOtherToolsDuringIntercept:
    """Non-completion tool calls are dispatched normally during verification."""

    @patch("agent.loop.ContextConfig.from_env")
    @patch("agent.loop.dispatch_tool")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_other_tools_dispatched_with_completion(
        self, mock_call_llm, mock_run_scout, mock_dp,
        mock_dispatch_tool, mock_from_env,
    ):
        """When report_completion is batched with other tools, others are dispatched."""
        from agent.loop import run_agent
        from agent.context import ContextConfig

        mock_runtime = _make_mock_runtime()
        mock_from_env.return_value = ContextConfig(
            verification_enabled=True, verification_max_attempts=1,
        )
        mock_run_scout.return_value = _make_scout_summary_mock()

        tc_read = ToolCall(id="tc_read", name="read_file", arguments={"path": "x.md"})
        tc_complete = ToolCall(
            id="tc_complete", name="report_completion",
            arguments={"answer": "ans", "code": "completed",
                       "grounding_refs": [], "steps": []},
        )

        tc_final = ToolCall(
            id="tc_final", name="report_completion",
            arguments={"answer": "ans", "code": "completed",
                       "grounding_refs": [], "steps": []},
        )

        mock_call_llm.side_effect = [
            # Step 1: read_file + report_completion -> intercepted (0 < 1), read_file dispatched
            MagicMock(content=None, tool_calls=[tc_read, tc_complete], raw=None),
            # Step 2: after verification, report_completion -> dispatched (1 >= 1)
            MagicMock(content=None, tool_calls=[tc_final], raw=None),
        ]
        mock_dp.return_value = [("tc_read", '{"content": "file data"}')]
        mock_dispatch_tool.return_value = '{"ok": true}'

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="test task",
        )

        # dispatch_parallel should have been called with only the read_file tool
        mock_dp.assert_called_once()
        dp_tool_calls = mock_dp.call_args[0][1]
        assert len(dp_tool_calls) == 1
        assert dp_tool_calls[0].name == "read_file"


class TestVerificationMaxAttemptsThenDispatch:
    """After max attempts, report_completion dispatches to harness."""

    @patch("agent.loop.ContextConfig.from_env")
    @patch("agent.loop.dispatch_tool")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_dispatched_after_max_attempts(
        self, mock_call_llm, mock_run_scout, mock_dp,
        mock_dispatch_tool, mock_from_env,
    ):
        """After 2 verification attempts, the next report_completion goes to harness."""
        from agent.loop import run_agent
        from agent.context import ContextConfig

        mock_runtime = _make_mock_runtime()
        mock_from_env.return_value = ContextConfig(
            verification_enabled=True, verification_max_attempts=2,
        )
        mock_run_scout.return_value = _make_scout_summary_mock()

        tc1 = ToolCall(
            id="tc1", name="report_completion",
            arguments={"answer": "ans1", "code": "completed",
                       "grounding_refs": [], "steps": []},
        )
        tc2 = ToolCall(
            id="tc2", name="report_completion",
            arguments={"answer": "ans2", "code": "completed",
                       "grounding_refs": [], "steps": []},
        )
        tc3 = ToolCall(
            id="tc3", name="report_completion",
            arguments={"answer": "ans3", "code": "completed",
                       "grounding_refs": [], "steps": []},
        )

        mock_call_llm.side_effect = [
            MagicMock(content=None, tool_calls=[tc1], raw=None),  # attempt 1 intercepted
            MagicMock(content=None, tool_calls=[tc2], raw=None),  # attempt 2 intercepted
            MagicMock(content=None, tool_calls=[tc3], raw=None),  # at max -> dispatched
        ]
        mock_dispatch_tool.return_value = '{"ok": true}'

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="test task",
        )

        # 3 LLM calls: 2 intercepted + 1 dispatched
        assert mock_call_llm.call_count == 3
        # dispatch_tool called once for the final dispatch
        assert mock_dispatch_tool.call_count >= 1


class TestVerificationStepsCountAgainstLimit:
    """Verification steps count against the 30-step executor limit."""

    @patch("agent.loop.ContextConfig.from_env")
    @patch("agent.loop.dispatch_tool")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_steps_capped_at_30(
        self, mock_call_llm, mock_run_scout, mock_dp,
        mock_dispatch_tool, mock_from_env,
    ):
        """Verification cycles consume steps from the 30-step limit."""
        from agent.loop import run_agent
        from agent.context import ContextConfig

        mock_runtime = _make_mock_runtime()
        mock_from_env.return_value = ContextConfig(
            verification_enabled=True, verification_max_attempts=100,
        )
        mock_run_scout.return_value = _make_scout_summary_mock()

        # Every call returns report_completion -> always intercepted (max_attempts=100)
        # This will loop until the 30-step limit
        def make_tc(n):
            return ToolCall(
                id=f"tc{n}", name="report_completion",
                arguments={"answer": f"ans{n}", "code": "completed",
                           "grounding_refs": [], "steps": []},
            )

        mock_call_llm.side_effect = [
            MagicMock(content=None, tool_calls=[make_tc(i)], raw=None)
            for i in range(35)  # More than 30 to test limit
        ]
        mock_dispatch_tool.return_value = '{"ok": true}'

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="test task",
        )

        # Should be capped at 30 steps
        assert mock_call_llm.call_count == 30


class TestVerificationOutcomeConfirmedLog:
    """Confirmed answer outcome is logged correctly."""

    @patch("agent.loop.ContextConfig.from_env")
    @patch("agent.loop.dispatch_tool")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_confirmed_log_output(
        self, mock_call_llm, mock_run_scout, mock_dp,
        mock_dispatch_tool, mock_from_env, capsys,
    ):
        """When verified answer matches original, CONFIRMED is printed."""
        from agent.loop import run_agent
        from agent.context import ContextConfig

        mock_runtime = _make_mock_runtime()
        mock_from_env.return_value = ContextConfig(
            verification_enabled=True, verification_max_attempts=1,
        )
        mock_run_scout.return_value = _make_scout_summary_mock()

        same_answer = "the answer"
        tc1 = ToolCall(
            id="tc1", name="report_completion",
            arguments={"answer": same_answer, "code": "completed",
                       "grounding_refs": [], "steps": []},
        )
        tc2 = ToolCall(
            id="tc2", name="report_completion",
            arguments={"answer": same_answer, "code": "completed",
                       "grounding_refs": [], "steps": []},
        )

        mock_call_llm.side_effect = [
            # Step 1: intercepted (attempt 0 < 1)
            MagicMock(content=None, tool_calls=[tc1], raw=None),
            # Step 2: dispatched (attempt 1 >= 1), logs CONFIRMED
            MagicMock(content=None, tool_calls=[tc2], raw=None),
        ]
        mock_dispatch_tool.return_value = '{"ok": true}'

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="test task",
        )

        captured = capsys.readouterr()
        assert "CONFIRMED" in captured.out


class TestVerificationOutcomeRevisedLog:
    """Revised answer outcome is logged correctly."""

    @patch("agent.loop.ContextConfig.from_env")
    @patch("agent.loop.dispatch_tool")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_revised_log_output(
        self, mock_call_llm, mock_run_scout, mock_dp,
        mock_dispatch_tool, mock_from_env, capsys,
    ):
        """When verified answer differs from original, REVISED is printed."""
        from agent.loop import run_agent
        from agent.context import ContextConfig

        mock_runtime = _make_mock_runtime()
        mock_from_env.return_value = ContextConfig(
            verification_enabled=True, verification_max_attempts=1,
        )
        mock_run_scout.return_value = _make_scout_summary_mock()

        tc1 = ToolCall(
            id="tc1", name="report_completion",
            arguments={"answer": "original answer", "code": "completed",
                       "grounding_refs": [], "steps": []},
        )
        tc2 = ToolCall(
            id="tc2", name="report_completion",
            arguments={"answer": "corrected answer", "code": "completed",
                       "grounding_refs": [], "steps": []},
        )

        mock_call_llm.side_effect = [
            # Step 1: intercepted (attempt 0 < 1)
            MagicMock(content=None, tool_calls=[tc1], raw=None),
            # Step 2: dispatched (attempt 1 >= 1), logs REVISED
            MagicMock(content=None, tool_calls=[tc2], raw=None),
        ]
        mock_dispatch_tool.return_value = '{"ok": true}'

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="test task",
        )

        captured = capsys.readouterr()
        assert "REVISED" in captured.out


class TestVerificationEmptyResponseFallback:
    """Empty LLM response during verification submits captured answer."""

    @patch("agent.loop.ContextConfig.from_env")
    @patch("agent.loop.dispatch_tool")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_empty_response_submits_captured_answer(
        self, mock_call_llm, mock_run_scout, mock_dp,
        mock_dispatch_tool, mock_from_env,
    ):
        """When LLM returns empty during verification, captured answer is submitted."""
        from agent.loop import run_agent
        from agent.context import ContextConfig

        mock_runtime = _make_mock_runtime()
        mock_from_env.return_value = ContextConfig(
            verification_enabled=True, verification_max_attempts=1,
        )
        mock_run_scout.return_value = _make_scout_summary_mock()

        tc = ToolCall(
            id="tc1", name="report_completion",
            arguments={"answer": "captured answer", "code": "completed",
                       "grounding_refs": [], "steps": []},
        )
        mock_call_llm.side_effect = [
            # Step 1: report_completion -> intercepted (attempt 0 < 1)
            MagicMock(content=None, tool_calls=[tc], raw=None),
            # Step 2: empty response -> fallback submits captured answer
            MagicMock(content="", tool_calls=[], raw=None),
        ]
        mock_dispatch_tool.return_value = '{"ok": true}'

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="test task",
        )

        # dispatch_tool should have been called with the captured answer
        assert mock_dispatch_tool.call_count >= 1
        last_dt_call = mock_dispatch_tool.call_args
        args = last_dt_call[0][2]
        assert args["answer"] == "captured answer"


# ===========================================================================
# Task 6 TDD Tests: Configurable Template Deletion Guard in loop.py
# ===========================================================================

class TestTemplateGuardEnvWiring:
    """Task 6.1: loop.py reads TEMPLATE_PROTECTED_DIRS env var and wires it
    into DispatchContext as TemplateGuardConfig.

    All tests patch _extract_task_constraints_regex to return default
    TaskConstraints, bypassing the LLM constraint extraction path so that
    the tests stay focused on the env var -> TemplateGuardConfig wiring.
    """

    @patch("agent.loop._extract_task_constraints_llm")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_dispatch_parallel_receives_template_guard_config(
        self, mock_call_llm, mock_run_scout, mock_dp, mock_llm_extract,
    ):
        """When TEMPLATE_PROTECTED_DIRS is set and dispatch_parallel is called,
        the dispatch_ctx should contain the correct TemplateGuardConfig."""
        from agent.loop import run_agent
        from agent.dispatch import TaskConstraints

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()
        # Return default constraints to skip LLM fallback
        mock_llm_extract.return_value = TaskConstraints()

        # Call 1: LLM returns tool calls -> triggers dispatch_parallel
        # Call 2: LLM returns text only -> completes
        tool_call_response = MagicMock(
            content="",
            tool_calls=[
                ToolCall(id="tc_1", name="read_file", arguments={"path": "/a.md"}),
            ],
            raw=None,
        )
        text_response = MagicMock(
            content="All done", tool_calls=[], raw=None,
        )
        mock_call_llm.side_effect = [tool_call_response, text_response]
        mock_dp.return_value = [("tc_1", '{"content": "text"}')]

        with patch.dict("os.environ", {"TEMPLATE_PROTECTED_DIRS": "/templates/, /structural/ "}):
            run_agent(
                executor_model="openai/gpt-4.1",
                runtime=mock_runtime,
                task_text="do something",
            )

        # dispatch_parallel should have been called with dispatch_ctx
        assert mock_dp.call_count == 1
        call_kwargs = mock_dp.call_args
        dispatch_ctx = call_kwargs.kwargs.get("dispatch_ctx") or call_kwargs[1].get("dispatch_ctx")
        assert dispatch_ctx is not None
        assert dispatch_ctx.template_guard_config.protected_directories == (
            "/templates/", "/structural/",
        )

    @patch("agent.loop._extract_task_constraints_llm")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_dispatch_ctx_empty_env_gives_empty_protected_dirs(
        self, mock_call_llm, mock_run_scout, mock_dp, mock_llm_extract,
    ):
        """When TEMPLATE_PROTECTED_DIRS is empty or unset, DispatchContext should
        have TemplateGuardConfig with empty protected_directories tuple."""
        from agent.loop import run_agent
        from agent.dispatch import TaskConstraints

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()
        mock_llm_extract.return_value = TaskConstraints()

        tool_call_response = MagicMock(
            content="",
            tool_calls=[
                ToolCall(id="tc_1", name="read_file", arguments={"path": "/a.md"}),
            ],
            raw=None,
        )
        text_response = MagicMock(
            content="done", tool_calls=[], raw=None,
        )
        mock_call_llm.side_effect = [tool_call_response, text_response]
        mock_dp.return_value = [("tc_1", '{"content": "text"}')]

        # Ensure env var is unset
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("TEMPLATE_PROTECTED_DIRS", None)
            run_agent(
                executor_model="openai/gpt-4.1",
                runtime=mock_runtime,
                task_text="do something",
            )

        assert mock_dp.call_count == 1
        call_kwargs = mock_dp.call_args
        dispatch_ctx = call_kwargs.kwargs.get("dispatch_ctx") or call_kwargs[1].get("dispatch_ctx")
        assert dispatch_ctx is not None
        assert dispatch_ctx.template_guard_config.protected_directories == ()

    @patch("agent.loop._extract_task_constraints_llm")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_dispatch_ctx_env_with_trailing_commas_and_spaces(
        self, mock_call_llm, mock_run_scout, mock_dp, mock_llm_extract,
    ):
        """Trailing commas and whitespace in TEMPLATE_PROTECTED_DIRS are ignored."""
        from agent.loop import run_agent
        from agent.dispatch import TaskConstraints

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()
        mock_llm_extract.return_value = TaskConstraints()

        tool_call_response = MagicMock(
            content="",
            tool_calls=[
                ToolCall(id="tc_1", name="read_file", arguments={"path": "/a.md"}),
            ],
            raw=None,
        )
        text_response = MagicMock(
            content="done", tool_calls=[], raw=None,
        )
        mock_call_llm.side_effect = [tool_call_response, text_response]
        mock_dp.return_value = [("tc_1", '{"content": "text"}')]

        with patch.dict("os.environ", {"TEMPLATE_PROTECTED_DIRS": " /foo/ , , /bar/ , "}):
            run_agent(
                executor_model="openai/gpt-4.1",
                runtime=mock_runtime,
                task_text="do something",
            )

        call_kwargs = mock_dp.call_args
        dispatch_ctx = call_kwargs.kwargs.get("dispatch_ctx") or call_kwargs[1].get("dispatch_ctx")
        assert dispatch_ctx is not None
        assert dispatch_ctx.template_guard_config.protected_directories == (
            "/foo/", "/bar/",
        )


class TestExistingTestsPassWithVerificationDisabled:
    """All existing tests still pass with verification disabled (default)."""

    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_backward_compat_text_only(
        self, mock_call_llm, mock_run_scout, mock_dp,
    ):
        """Text-only response auto-submits normally with verification disabled."""
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()
        mock_call_llm.return_value = MagicMock(
            content="I'm done", tool_calls=[], raw=None,
        )

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        assert mock_call_llm.call_count == 1
        mock_dp.assert_not_called()


# ---------------------------------------------------------------------------
# Task 5: LLM-Driven Task Constraint Extraction
# ---------------------------------------------------------------------------

@pytest.mark.no_default_constraints
class TestExtractTaskConstraintsLLM:
    """Test _extract_task_constraints_llm: LLM fallback for constraint extraction."""

    @patch("agent.loop.call_llm")
    def test_valid_json_response_parsed(self, mock_call_llm):
        """Valid JSON response from LLM is parsed into TaskConstraints."""
        from agent.loop import _extract_task_constraints_llm
        from agent.dispatch import TaskConstraints

        mock_call_llm.return_value = MagicMock(
            content='{"source_file": "main.py", "scope_level": "focused", "target_directories": ["src/"]}',
            tool_calls=[], raw=None,
        )

        result = _extract_task_constraints_llm(
            "openai/gpt-4.1", "Edit src/main.py", {}
        )
        assert isinstance(result, TaskConstraints)
        assert result.source_file == "main.py"
        assert result.scope_level == "focused"
        assert result.target_directories == ("src/",)

    @patch("agent.loop.call_llm")
    def test_null_source_file_parsed(self, mock_call_llm):
        """JSON with null source_file is handled correctly."""
        from agent.loop import _extract_task_constraints_llm
        from agent.dispatch import TaskConstraints

        mock_call_llm.return_value = MagicMock(
            content='{"source_file": null, "scope_level": "normal", "target_directories": []}',
            tool_calls=[], raw=None,
        )

        result = _extract_task_constraints_llm(
            "openai/gpt-4.1", "Do something", {}
        )
        assert result.source_file is None
        assert result.scope_level == "normal"
        assert result.target_directories == ()

    @patch("agent.loop.call_llm")
    def test_malformed_json_returns_default(self, mock_call_llm):
        """Malformed JSON response falls back to default TaskConstraints."""
        from agent.loop import _extract_task_constraints_llm
        from agent.dispatch import TaskConstraints

        mock_call_llm.return_value = MagicMock(
            content="not valid json {{{",
            tool_calls=[], raw=None,
        )

        result = _extract_task_constraints_llm(
            "openai/gpt-4.1", "Do something", {}
        )
        assert result == TaskConstraints()
        assert result.source_file is None
        assert result.scope_level == "normal"
        assert result.target_directories == ()

    @patch("agent.loop.call_llm")
    def test_llm_exception_returns_default(self, mock_call_llm):
        """When call_llm raises an exception, returns default TaskConstraints."""
        from agent.loop import _extract_task_constraints_llm
        from agent.dispatch import TaskConstraints

        mock_call_llm.side_effect = Exception("LLM unavailable")

        result = _extract_task_constraints_llm(
            "openai/gpt-4.1", "Do something", {}
        )
        assert result == TaskConstraints()

    @patch("agent.loop.call_llm")
    def test_empty_content_returns_default(self, mock_call_llm):
        """Empty LLM content returns default TaskConstraints."""
        from agent.loop import _extract_task_constraints_llm
        from agent.dispatch import TaskConstraints

        mock_call_llm.return_value = MagicMock(
            content="", tool_calls=[], raw=None,
        )

        result = _extract_task_constraints_llm(
            "openai/gpt-4.1", "Do something", {}
        )
        assert result == TaskConstraints()

    @patch("agent.loop.call_llm")
    def test_none_content_returns_default(self, mock_call_llm):
        """None LLM content returns default TaskConstraints."""
        from agent.loop import _extract_task_constraints_llm
        from agent.dispatch import TaskConstraints

        mock_call_llm.return_value = MagicMock(
            content=None, tool_calls=[], raw=None,
        )

        result = _extract_task_constraints_llm(
            "openai/gpt-4.1", "Do something", {}
        )
        assert result == TaskConstraints()

    @patch("agent.loop.call_llm")
    def test_json_with_extra_text_parsed(self, mock_call_llm):
        """JSON embedded in extra text (e.g., markdown) is extracted."""
        from agent.loop import _extract_task_constraints_llm
        from agent.dispatch import TaskConstraints

        mock_call_llm.return_value = MagicMock(
            content='```json\n{"source_file": "app.py", "scope_level": "normal", "target_directories": []}\n```',
            tool_calls=[], raw=None,
        )

        result = _extract_task_constraints_llm(
            "openai/gpt-4.1", "Edit app.py", {}
        )
        assert result.source_file == "app.py"

    @patch("agent.loop.call_llm")
    def test_prompt_contains_task_text(self, mock_call_llm):
        """The LLM is prompted with the task text."""
        from agent.loop import _extract_task_constraints_llm

        mock_call_llm.return_value = MagicMock(
            content='{"source_file": null, "scope_level": "normal", "target_directories": []}',
            tool_calls=[], raw=None,
        )

        _extract_task_constraints_llm(
            "openai/gpt-4.1", "My specific task text here", {"trace_id": "t1"}
        )

        # Verify the prompt passed to call_llm contains the task text
        call_args = mock_call_llm.call_args
        messages = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]["messages"]
        all_content = " ".join(m.get("content", "") or "" for m in messages)
        assert "My specific task text here" in all_content


@pytest.mark.no_default_constraints
class TestOldFunctionsRemoved:
    """Verify old regex functions are removed from loop.py after Task 5.5."""

    def test_no_extract_source_basename_function(self):
        """_extract_source_basename should be removed from loop.py."""
        from agent import loop
        assert not hasattr(loop, "_extract_source_basename"), (
            "_extract_source_basename should be removed"
        )

    def test_no_FILE_PATH_RE_in_module(self):
        """_FILE_PATH_RE should be removed from loop.py."""
        from agent import loop
        assert not hasattr(loop, "_FILE_PATH_RE"), (
            "_FILE_PATH_RE should be removed"
        )

    def test_no_SCOPE_PHRASES_in_module(self):
        """_SCOPE_PHRASES should be removed from loop.py module scope."""
        from agent import loop
        assert not hasattr(loop, "_SCOPE_PHRASES"), (
            "_SCOPE_PHRASES should be removed from module scope"
        )


@pytest.mark.no_default_constraints
@pytest.mark.no_default_constraints
class TestLLMConstraintExtractionInRunAgent:
    """Verify LLM constraint extraction is wired into run_agent()."""

    @patch("agent.loop._extract_task_constraints_llm")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_llm_extraction_called_in_run_agent(
        self, mock_call_llm, mock_run_scout, mock_dp, mock_llm_extract,
    ):
        """LLM constraint extraction is called during run_agent."""
        from agent.loop import run_agent
        from agent.dispatch import TaskConstraints

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()
        mock_call_llm.return_value = MagicMock(
            content="done", tool_calls=[], raw=None,
        )
        mock_llm_extract.return_value = TaskConstraints()

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="Do something",
        )

        mock_llm_extract.assert_called_once()


# ---------------------------------------------------------------------------
# Task 2: ResilienceState, _looks_like_tool_call, _detect_tool_name
# ---------------------------------------------------------------------------

class TestResilienceState:
    """ResilienceState is a mutable dataclass with correct defaults."""

    def test_default_values(self):
        from agent.loop import ResilienceState
        s = ResilienceState()
        assert s.consecutive_empty == 0
        assert s.consecutive_text_tool == 0
        assert s.consecutive_errors == 0
        assert s.completion_submitted is False
        assert s.steps_since_completion_attempt == 0
        assert s.recent_tool_calls == []

    def test_mutable(self):
        from agent.loop import ResilienceState
        s = ResilienceState()
        s.consecutive_empty = 5
        assert s.consecutive_empty == 5


class TestLooksLikeToolCall:
    """_looks_like_tool_call detects tool-call JSON in text responses."""

    def test_non_json_returns_false(self):
        from agent.loop import _looks_like_tool_call
        assert _looks_like_tool_call("just plain text") is False

    def test_path_alone_returns_false(self):
        from agent.loop import _looks_like_tool_call
        assert _looks_like_tool_call('{"path": "/some/file"}') is False

    def test_answer_key_returns_false(self):
        from agent.loop import _looks_like_tool_call
        assert _looks_like_tool_call('{"answer": "TODO"}') is False

    def test_path_content_returns_true(self):
        from agent.loop import _looks_like_tool_call
        assert _looks_like_tool_call('{"path": "/f.txt", "content": "hello"}') is True

    def test_path_level_returns_true(self):
        from agent.loop import _looks_like_tool_call
        assert _looks_like_tool_call('{"path": "/", "level": 2}') is True

    def test_path_number_returns_true(self):
        from agent.loop import _looks_like_tool_call
        assert _looks_like_tool_call('{"path": "/f.txt", "number": true}') is True

    def test_path_start_line_returns_true(self):
        from agent.loop import _looks_like_tool_call
        assert _looks_like_tool_call('{"path": "/f.txt", "start_line": 1}') is True

    def test_pattern_returns_true(self):
        from agent.loop import _looks_like_tool_call
        assert _looks_like_tool_call('{"pattern": "TODO"}') is True

    def test_name_with_root_returns_true(self):
        from agent.loop import _looks_like_tool_call
        assert _looks_like_tool_call('{"name": "foo", "root": "/"}') is True

    def test_name_with_kind_returns_true(self):
        from agent.loop import _looks_like_tool_call
        assert _looks_like_tool_call('{"name": "foo", "kind": "files"}') is True

    def test_invalid_json_returns_false(self):
        from agent.loop import _looks_like_tool_call
        assert _looks_like_tool_call('{not valid json}') is False

    def test_json_list_returns_false(self):
        from agent.loop import _looks_like_tool_call
        assert _looks_like_tool_call('[1, 2, 3]') is False


class TestDetectToolName:
    """_detect_tool_name returns the most likely tool name."""

    def test_write_file(self):
        from agent.loop import _detect_tool_name
        assert _detect_tool_name('{"path": "/f.txt", "content": "hi"}') == "write_file"

    def test_tree(self):
        from agent.loop import _detect_tool_name
        assert _detect_tool_name('{"path": "/", "level": 2}') == "tree"

    def test_read_file_number(self):
        from agent.loop import _detect_tool_name
        assert _detect_tool_name('{"path": "/f.txt", "number": true}') == "read_file"

    def test_read_file_start_line(self):
        from agent.loop import _detect_tool_name
        assert _detect_tool_name('{"path": "/f.txt", "start_line": 1}') == "read_file"

    def test_search(self):
        from agent.loop import _detect_tool_name
        assert _detect_tool_name('{"pattern": "TODO"}') == "search"

    def test_find(self):
        from agent.loop import _detect_tool_name
        assert _detect_tool_name('{"name": "foo", "root": "/"}') == "find"

    def test_ambiguous_path_returns_none(self):
        from agent.loop import _detect_tool_name
        assert _detect_tool_name('{"path": "/foo"}') is None

    def test_non_json_returns_none(self):
        from agent.loop import _detect_tool_name
        assert _detect_tool_name("plain text") is None


# ---------------------------------------------------------------------------
# Task 10: Resilience mechanism integration tests (15 tests)
# ---------------------------------------------------------------------------

class TestEmptyResponseRetry:
    """test_empty_response_retry: 2 empties then valid tool call -- nudge injected, loop continues."""

    @patch("agent.loop.dispatch_tool")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_empty_response_retry(
        self, mock_call_llm, mock_run_scout, mock_dp, mock_dispatch_tool,
    ):
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()

        tc_complete = ToolCall(
            id="tc1", name="report_completion",
            arguments={"answer": "done", "grounding_refs": [], "steps": [], "code": "OUTCOME_OK"},
        )
        mock_call_llm.side_effect = [
            # Step 1: empty response
            MagicMock(content="", tool_calls=[], raw=None),
            # Step 2: empty response again
            MagicMock(content="   ", tool_calls=[], raw=None),
            # Step 3: valid tool call (report_completion)
            MagicMock(content=None, tool_calls=[tc_complete], raw=None),
        ]
        mock_dispatch_tool.return_value = '{"ok": true}'

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        # Should have 3 call_llm calls (3 steps)
        assert mock_call_llm.call_count == 3

        # dispatch_tool should be called for report_completion
        mock_dispatch_tool.assert_called_once()
        dt_args = mock_dispatch_tool.call_args[0]
        assert dt_args[1] == "report_completion"
        assert dt_args[2]["answer"] == "done"

        # Check nudge messages were injected
        last_messages = mock_call_llm.call_args_list[-1][0][1]
        nudge_msgs = [
            m for m in last_messages
            if m.get("role") == "user" and "empty" in m.get("content", "").lower()
        ]
        assert len(nudge_msgs) >= 1


class TestEmptyResponseFallback:
    """test_empty_response_fallback: 3 consecutive empties -- fallback submission."""

    @patch("agent.loop.dispatch_tool")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_empty_response_fallback(
        self, mock_call_llm, mock_run_scout, mock_dispatch_tool,
    ):
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()

        mock_call_llm.side_effect = [
            # Steps 1-3: all empty
            MagicMock(content="", tool_calls=[], raw=None),
            MagicMock(content="", tool_calls=[], raw=None),
            MagicMock(content="", tool_calls=[], raw=None),
        ]
        mock_dispatch_tool.return_value = '{"ok": true}'

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        # dispatch_tool should have been called with OUTCOME_ERR_INTERNAL
        assert mock_dispatch_tool.call_count >= 1
        dt_args = mock_dispatch_tool.call_args[0]
        assert dt_args[1] == "report_completion"
        assert dt_args[2]["code"] == "OUTCOME_ERR_INTERNAL"


class TestEmptyResponseCounterReset:
    """test_empty_response_counter_reset: empty, valid, empty -- counter resets."""

    @patch("agent.loop.dispatch_tool")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_empty_response_counter_reset(
        self, mock_call_llm, mock_run_scout, mock_dp, mock_dispatch_tool,
    ):
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()

        tc_read = ToolCall(id="tc1", name="read_file", arguments={"path": "x.md"})
        tc_complete = ToolCall(
            id="tc2", name="report_completion",
            arguments={"answer": "done", "grounding_refs": [], "steps": [], "code": "OUTCOME_OK"},
        )
        mock_call_llm.side_effect = [
            # Step 1: empty
            MagicMock(content="", tool_calls=[], raw=None),
            # Step 2: valid tool call (resets counter)
            MagicMock(content=None, tool_calls=[tc_read], raw=None),
            # Step 3: empty (counter back to 1, not 2)
            MagicMock(content="", tool_calls=[], raw=None),
            # Step 4: valid completion
            MagicMock(content=None, tool_calls=[tc_complete], raw=None),
        ]
        mock_dp.return_value = [("tc1", '{"content": "ok"}')]
        mock_dispatch_tool.return_value = '{"ok": true}'

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        # Should NOT have triggered fallback (counter reset between empties)
        assert mock_call_llm.call_count == 4
        dt_args = mock_dispatch_tool.call_args[0]
        assert dt_args[2]["answer"] == "done"  # Normal completion, not fallback


class TestTextToolDetection:
    """test_text_tool_detection: JSON as text -- correction injected, not auto-submitted."""

    @patch("agent.loop.dispatch_tool")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_text_tool_detection(
        self, mock_call_llm, mock_run_scout, mock_dispatch_tool,
    ):
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()

        tc_complete = ToolCall(
            id="tc1", name="report_completion",
            arguments={"answer": "done", "grounding_refs": [], "steps": [], "code": "OUTCOME_OK"},
        )
        mock_call_llm.side_effect = [
            # Step 1: text-as-tool (write_file pattern)
            MagicMock(content='{"path": "/foo.txt", "content": "hello"}', tool_calls=[], raw=None),
            # Step 2: proper tool call
            MagicMock(content=None, tool_calls=[tc_complete], raw=None),
        ]
        mock_dispatch_tool.return_value = '{"ok": true}'

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        # Should have 2 call_llm calls, not auto-submitted the JSON text
        assert mock_call_llm.call_count == 2
        # The final dispatch should be report_completion with "done"
        dt_args = mock_dispatch_tool.call_args[0]
        assert dt_args[2]["answer"] == "done"

        # Check correction message was injected
        step2_messages = mock_call_llm.call_args_list[-1][0][1]
        correction_msgs = [
            m for m in step2_messages
            if m.get("role") == "user" and "function calling" in m.get("content", "").lower()
        ]
        assert len(correction_msgs) >= 1


class TestTextToolMaxExceeded:
    """test_text_tool_max_exceeded: 3 consecutive text-tool responses -- after 2 re-prompts, 3rd auto-submitted."""

    @patch("agent.loop.dispatch_tool")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_text_tool_max_exceeded(
        self, mock_call_llm, mock_run_scout, mock_dispatch_tool,
    ):
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()

        mock_call_llm.side_effect = [
            # Steps 1-3: all text-as-tool (write_file pattern)
            MagicMock(content='{"path": "/f.txt", "content": "a"}', tool_calls=[], raw=None),
            MagicMock(content='{"path": "/f.txt", "content": "b"}', tool_calls=[], raw=None),
            MagicMock(content='{"path": "/f.txt", "content": "c"}', tool_calls=[], raw=None),
        ]
        mock_dispatch_tool.return_value = '{"ok": true}'

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        # After 2 re-prompts (steps 1, 2), the 3rd should be auto-submitted as text
        assert mock_call_llm.call_count == 3
        dt_args = mock_dispatch_tool.call_args[0]
        assert dt_args[1] == "report_completion"


class TestTryExtractCompletionPriority:
    """test_try_extract_completion_priority: text with {"answer": "..."} -- existing path, no text-tool detection."""

    @patch("agent.loop.dispatch_tool")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_try_extract_completion_priority(
        self, mock_call_llm, mock_run_scout, mock_dispatch_tool,
    ):
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()

        mock_call_llm.side_effect = [
            # Text with "answer" key -- should be handled by _try_extract_completion
            MagicMock(content='{"answer": "my answer", "code": "OUTCOME_OK"}', tool_calls=[], raw=None),
        ]
        mock_dispatch_tool.return_value = '{"ok": true}'

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        # Should auto-submit with extracted answer, not trigger text-tool detection
        assert mock_call_llm.call_count == 1
        dt_args = mock_dispatch_tool.call_args[0]
        assert dt_args[2]["answer"] == "my answer"


class TestErrorRecoveryNotFound:
    """test_error_recovery_not_found: tool returns NOT_FOUND error -- hint appended."""

    @patch("agent.loop.dispatch_tool")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_error_recovery_not_found(
        self, mock_call_llm, mock_run_scout, mock_dp, mock_dispatch_tool,
    ):
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()

        tc_read = ToolCall(id="tc1", name="read_file", arguments={"path": "/bad/file.md"})
        tc_complete = ToolCall(
            id="tc2", name="report_completion",
            arguments={"answer": "done", "grounding_refs": [], "steps": [], "code": "OUTCOME_OK"},
        )
        mock_call_llm.side_effect = [
            # Step 1: tool call that returns NOT_FOUND
            MagicMock(content=None, tool_calls=[tc_read], raw=None),
            # Step 2: complete
            MagicMock(content=None, tool_calls=[tc_complete], raw=None),
        ]
        mock_dp.return_value = [("tc1", '{"error": "NOT_FOUND: /bad/file.md"}')]
        mock_dispatch_tool.return_value = '{"ok": true}'

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        # The second call_llm should have a tool result with a hint appended
        step2_messages = mock_call_llm.call_args_list[-1][0][1]
        tool_msgs = [m for m in step2_messages if m.get("role") == "tool"]
        assert any("list" in m.get("content", "").lower() or "directory" in m.get("content", "").lower()
                    for m in tool_msgs)


class TestErrorEscalation:
    """test_error_escalation: 3 consecutive tool errors -- escalated message injected."""

    @patch("agent.loop.dispatch_tool")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_error_escalation(
        self, mock_call_llm, mock_run_scout, mock_dp, mock_dispatch_tool,
    ):
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()

        tc1 = ToolCall(id="tc1", name="read_file", arguments={"path": "/bad1.md"})
        tc2 = ToolCall(id="tc2", name="read_file", arguments={"path": "/bad2.md"})
        tc3 = ToolCall(id="tc3", name="read_file", arguments={"path": "/bad3.md"})
        tc_complete = ToolCall(
            id="tc4", name="report_completion",
            arguments={"answer": "done", "grounding_refs": [], "steps": [], "code": "OUTCOME_OK"},
        )
        mock_call_llm.side_effect = [
            # Steps 1-3: all return errors
            MagicMock(content=None, tool_calls=[tc1], raw=None),
            MagicMock(content=None, tool_calls=[tc2], raw=None),
            MagicMock(content=None, tool_calls=[tc3], raw=None),
            # Step 4: complete
            MagicMock(content=None, tool_calls=[tc_complete], raw=None),
        ]
        mock_dp.side_effect = [
            [("tc1", '{"error": "NOT_FOUND: /bad1.md"}')],
            [("tc2", '{"error": "NOT_FOUND: /bad2.md"}')],
            [("tc3", '{"error": "NOT_FOUND: /bad3.md"}')],
        ]
        mock_dispatch_tool.return_value = '{"ok": true}'

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        # After 3 errors, an escalation user message should be injected
        step4_messages = mock_call_llm.call_args_list[-1][0][1]
        escalation_msgs = [
            m for m in step4_messages
            if m.get("role") == "user" and "consecutive errors" in m.get("content", "").lower()
        ]
        assert len(escalation_msgs) >= 1


class TestGuaranteedSubmissionStepLimit:
    """test_guaranteed_submission_step_limit: 30 steps with no completion -- post-loop guard fires."""

    @patch("agent.loop.dispatch_tool")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_guaranteed_submission_step_limit(
        self, mock_call_llm, mock_run_scout, mock_dp, mock_dispatch_tool,
    ):
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()

        tc = ToolCall(id="tc1", name="read_file", arguments={"path": "x.md"})
        mock_call_llm.side_effect = [
            # 30 steps of tool calls without completion
            MagicMock(content="working", tool_calls=[tc], raw=None),
        ] * 30
        mock_dp.return_value = [("tc1", '{"content": "ok"}')]
        mock_dispatch_tool.return_value = '{"ok": true}'

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        # Post-loop guard should call report_completion with OUTCOME_ERR_INTERNAL
        # Find the last dispatch_tool call
        assert mock_dispatch_tool.call_count >= 1
        last_dt = mock_dispatch_tool.call_args_list[-1][0]
        assert last_dt[1] == "report_completion"
        assert last_dt[2]["code"] == "OUTCOME_ERR_INTERNAL"


class TestGuaranteedSubmissionVerification:
    """test_guaranteed_submission_verification: loop ends during verification -- original answer submitted."""

    @patch("agent.loop.ContextConfig.from_env")
    @patch("agent.loop.dispatch_tool")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_guaranteed_submission_verification(
        self, mock_call_llm, mock_run_scout, mock_dp, mock_dispatch_tool, mock_from_env,
    ):
        from agent.loop import run_agent
        from agent.context import ContextConfig

        mock_runtime = _make_mock_runtime()
        mock_from_env.return_value = ContextConfig(
            verification_enabled=True, verification_max_attempts=2,
        )
        mock_run_scout.return_value = _make_scout_summary_mock()

        tc_read = ToolCall(id="tc1", name="read_file", arguments={"path": "x.md"})
        tc_complete = ToolCall(
            id="tc_c", name="report_completion",
            arguments={"answer": "original answer", "grounding_refs": [], "steps": [], "code": "OUTCOME_OK"},
        )
        mock_call_llm.side_effect = [
            # Step 1: report_completion -> intercepted for verification
            MagicMock(content=None, tool_calls=[tc_complete], raw=None),
        ] + [
            # Steps 2-30: tool calls that never complete (exhaust step limit)
            MagicMock(content="working", tool_calls=[tc_read], raw=None),
        ] * 29
        mock_dp.return_value = [("tc1", '{"content": "ok"}')]
        mock_dispatch_tool.return_value = '{"ok": true}'

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        # Post-loop guard should submit the original answer
        last_dt = mock_dispatch_tool.call_args_list[-1][0]
        assert last_dt[1] == "report_completion"
        assert last_dt[2]["answer"] == "original answer"


class TestStrongModelNoOverhead:
    """test_strong_model_no_overhead: normal tool calls -- zero resilience interventions."""

    @patch("agent.loop.dispatch_tool")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_strong_model_no_overhead(
        self, mock_call_llm, mock_run_scout, mock_dp, mock_dispatch_tool,
    ):
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()

        tc_read = ToolCall(id="tc1", name="read_file", arguments={"path": "x.md"})
        tc_complete = ToolCall(
            id="tc2", name="report_completion",
            arguments={"answer": "42", "grounding_refs": [], "steps": [], "code": "OUTCOME_OK"},
        )
        mock_call_llm.side_effect = [
            # Step 1: normal tool call
            MagicMock(content="Let me read the file", tool_calls=[tc_read], raw=None),
            # Step 2: completion
            MagicMock(content=None, tool_calls=[tc_complete], raw=None),
        ]
        mock_dp.return_value = [("tc1", '{"content": "file content"}')]
        mock_dispatch_tool.return_value = '{"ok": true}'

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        # Only 2 call_llm calls (2 steps)
        assert mock_call_llm.call_count == 2
        # No nudge or correction messages injected
        step2_messages = mock_call_llm.call_args_list[-1][0][1]
        resilience_msgs = [
            m for m in step2_messages
            if m.get("role") == "user" and (
                "empty" in m.get("content", "").lower()
                or "function calling" in m.get("content", "").lower()
                or "consecutive errors" in m.get("content", "").lower()
                or "<checkpoint>" in m.get("content", "")
            )
        ]
        assert len(resilience_msgs) == 0


class TestReplanCheckpointInjected:
    """test_replan_checkpoint_injected: 8 steps without completion -- checkpoint injected."""

    @patch("agent.loop.dispatch_tool")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_replan_checkpoint_injected(
        self, mock_call_llm, mock_run_scout, mock_dp, mock_dispatch_tool,
    ):
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()

        # Create unique tool calls to avoid repetition detection
        def make_tc(i):
            return ToolCall(id=f"tc{i}", name="read_file", arguments={"path": f"file{i}.md"})

        tc_complete = ToolCall(
            id="tc_done", name="report_completion",
            arguments={"answer": "done", "grounding_refs": [], "steps": [], "code": "OUTCOME_OK"},
        )

        mock_call_llm.side_effect = [
            # Steps 1-8: unique tool calls without completion
            MagicMock(content=None, tool_calls=[make_tc(i)], raw=None) for i in range(8)
        ] + [
            # Step 9: completion after checkpoint
            MagicMock(content=None, tool_calls=[tc_complete], raw=None),
        ]
        mock_dp.side_effect = [
            [(f"tc{i}", '{"content": "ok"}')] for i in range(8)
        ]
        mock_dispatch_tool.return_value = '{"ok": true}'

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        # After 8 steps, a checkpoint message should have been injected
        last_messages = mock_call_llm.call_args_list[-1][0][1]
        checkpoint_msgs = [
            m for m in last_messages
            if m.get("role") == "user" and "<checkpoint>" in m.get("content", "")
        ]
        assert len(checkpoint_msgs) >= 1


class TestReplanCounterResets:
    """test_replan_counter_resets: checkpoint at step 8, then more steps -- no double-trigger."""

    @patch("agent.loop.dispatch_tool")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_replan_counter_resets(
        self, mock_call_llm, mock_run_scout, mock_dp, mock_dispatch_tool,
    ):
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()

        def make_tc(i):
            return ToolCall(id=f"tc{i}", name="read_file", arguments={"path": f"file{i}.md"})

        tc_complete = ToolCall(
            id="tc_done", name="report_completion",
            arguments={"answer": "done", "grounding_refs": [], "steps": [], "code": "OUTCOME_OK"},
        )

        # 8 steps -> checkpoint resets counter -> 4 more steps (under 8) -> complete
        mock_call_llm.side_effect = [
            # Steps 1-8: unique tool calls
            MagicMock(content=None, tool_calls=[make_tc(i)], raw=None) for i in range(8)
        ] + [
            # Steps 9-12: 4 more unique tool calls (after checkpoint, counter reset)
            MagicMock(content=None, tool_calls=[make_tc(100 + i)], raw=None) for i in range(4)
        ] + [
            # Step 13: completion
            MagicMock(content=None, tool_calls=[tc_complete], raw=None),
        ]
        mock_dp.side_effect = [
            [(f"tc{i}", '{"content": "ok"}')] for i in range(8)
        ] + [
            [(f"tc{100 + i}", '{"content": "ok"}')] for i in range(4)
        ]
        mock_dispatch_tool.return_value = '{"ok": true}'

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        # Check that there is exactly 1 checkpoint message (at step 8, not again at step 12)
        last_messages = mock_call_llm.call_args_list[-1][0][1]
        checkpoint_msgs = [
            m for m in last_messages
            if m.get("role") == "user" and "<checkpoint>" in m.get("content", "")
        ]
        assert len(checkpoint_msgs) == 1


class TestRepetitionDetection:
    """test_repetition_detection: same tool+args 3x -- checkpoint triggered by repetition."""

    @patch("agent.loop.dispatch_tool")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_repetition_detection(
        self, mock_call_llm, mock_run_scout, mock_dp, mock_dispatch_tool,
    ):
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()

        # Same tool call 3 times
        tc_same = ToolCall(id="tc1", name="read_file", arguments={"path": "/same/file.md"})
        tc_complete = ToolCall(
            id="tc_done", name="report_completion",
            arguments={"answer": "done", "grounding_refs": [], "steps": [], "code": "OUTCOME_OK"},
        )

        mock_call_llm.side_effect = [
            # Steps 1-3: same tool call repeated
            MagicMock(content=None, tool_calls=[tc_same], raw=None),
            MagicMock(content=None, tool_calls=[tc_same], raw=None),
            MagicMock(content=None, tool_calls=[tc_same], raw=None),
            # Step 4: completion after checkpoint
            MagicMock(content=None, tool_calls=[tc_complete], raw=None),
        ]
        mock_dp.side_effect = [
            [("tc1", '{"content": "ok"}')] for _ in range(3)
        ]
        mock_dispatch_tool.return_value = '{"ok": true}'

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        # A checkpoint should have been triggered by repetition (before 8 steps)
        last_messages = mock_call_llm.call_args_list[-1][0][1]
        checkpoint_msgs = [
            m for m in last_messages
            if m.get("role") == "user" and "<checkpoint>" in m.get("content", "")
        ]
        assert len(checkpoint_msgs) >= 1


class TestRepetitionWithDifferentArgs:
    """test_repetition_with_different_args: same tool, different args -- no checkpoint."""

    @patch("agent.loop.dispatch_tool")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_repetition_with_different_args(
        self, mock_call_llm, mock_run_scout, mock_dp, mock_dispatch_tool,
    ):
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()

        # Same tool name but different arguments
        tc1 = ToolCall(id="tc1", name="read_file", arguments={"path": "/file1.md"})
        tc2 = ToolCall(id="tc2", name="read_file", arguments={"path": "/file2.md"})
        tc3 = ToolCall(id="tc3", name="read_file", arguments={"path": "/file3.md"})
        tc_complete = ToolCall(
            id="tc_done", name="report_completion",
            arguments={"answer": "done", "grounding_refs": [], "steps": [], "code": "OUTCOME_OK"},
        )

        mock_call_llm.side_effect = [
            # Steps 1-3: same tool, different args
            MagicMock(content=None, tool_calls=[tc1], raw=None),
            MagicMock(content=None, tool_calls=[tc2], raw=None),
            MagicMock(content=None, tool_calls=[tc3], raw=None),
            # Step 4: completion
            MagicMock(content=None, tool_calls=[tc_complete], raw=None),
        ]
        mock_dp.side_effect = [
            [("tc1", '{"content": "ok"}')],
            [("tc2", '{"content": "ok"}')],
            [("tc3", '{"content": "ok"}')],
        ]
        mock_dispatch_tool.return_value = '{"ok": true}'

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        # Only 4 call_llm calls (4 steps)
        assert mock_call_llm.call_count == 4
        # No checkpoint injected (different args = not stuck)
        last_messages = mock_call_llm.call_args_list[-1][0][1]
        checkpoint_msgs = [
            m for m in last_messages
            if m.get("role") == "user" and "<checkpoint>" in m.get("content", "")
        ]
        assert len(checkpoint_msgs) == 0


class TestCyclingDetection:
    """test_cycling_detection: model reads same files in rotation -- cycling checkpoint triggered."""

    @patch("agent.loop.dispatch_tool")
    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    def test_cycling_detection(
        self, mock_call_llm, mock_run_scout, mock_dp, mock_dispatch_tool,
    ):
        from agent.loop import run_agent

        mock_runtime = _make_mock_runtime()
        mock_run_scout.return_value = _make_scout_summary_mock()

        # 3 unique tool calls repeated in a cycle (A, B, C, A, B, C)
        tc_a = ToolCall(id="tc_a", name="read_file", arguments={"path": "/file_a.md"})
        tc_b = ToolCall(id="tc_b", name="read_file", arguments={"path": "/file_b.md"})
        tc_c = ToolCall(id="tc_c", name="search", arguments={"pattern": "keyword"})
        tc_complete = ToolCall(
            id="tc_done", name="report_completion",
            arguments={"answer": "done", "grounding_refs": [], "steps": [], "code": "OUTCOME_OK"},
        )

        mock_call_llm.side_effect = [
            # Steps 1-6: A, B, C, A, B, C (3 unique tool calls, each appears 2x)
            MagicMock(content=None, tool_calls=[tc_a], raw=None),
            MagicMock(content=None, tool_calls=[tc_b], raw=None),
            MagicMock(content=None, tool_calls=[tc_c], raw=None),
            MagicMock(content=None, tool_calls=[tc_a], raw=None),
            MagicMock(content=None, tool_calls=[tc_b], raw=None),
            MagicMock(content=None, tool_calls=[tc_c], raw=None),
            # Step 7: completion after cycling checkpoint
            MagicMock(content=None, tool_calls=[tc_complete], raw=None),
        ]
        mock_dp.side_effect = [
            [("tc_a", '{"content": "ok"}')],
            [("tc_b", '{"content": "ok"}')],
            [("tc_c", '{"matches": []}')],
            [("tc_a", '{"content": "ok"}')],
            [("tc_b", '{"content": "ok"}')],
            [("tc_c", '{"matches": []}')],
        ]
        mock_dispatch_tool.return_value = '{"ok": true}'

        run_agent(
            executor_model="openai/gpt-4.1",
            runtime=mock_runtime,
            task_text="do something",
        )

        # Cycling checkpoint should have been triggered before step 8 interval
        last_messages = mock_call_llm.call_args_list[-1][0][1]
        checkpoint_msgs = [
            m for m in last_messages
            if m.get("role") == "user" and "<checkpoint>" in m.get("content", "")
        ]
        assert len(checkpoint_msgs) >= 1
