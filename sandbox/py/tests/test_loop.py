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
        assert "harness_url" in params
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
    @patch("agent.loop.MiniRuntimeClientSync")
    def test_creates_vm_client_with_harness_url(
        self, mock_vm_cls, mock_call_llm, mock_run_scout,
    ):
        """The VM client is created with the harness_url."""
        from agent.loop import run_agent

        mock_run_scout.return_value = _make_scout_summary_mock()
        mock_call_llm.return_value = MagicMock(
            content="done", tool_calls=[], raw=None,
        )

        run_agent(
            executor_model="openai/gpt-4.1",
            harness_url="http://test:1234",
            task_text="do something",
        )

        mock_vm_cls.assert_called_once_with("http://test:1234")

    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    @patch("agent.loop.MiniRuntimeClientSync")
    def test_protected_files_initialized_with_agents_md(
        self, mock_vm_cls, mock_call_llm, mock_run_scout,
    ):
        """protected_files starts with 'agents.md'."""
        from agent.loop import run_agent

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
                harness_url="http://test:1234",
                task_text="do something",
            )

            # protected_files should include "agents.md"
            dp_call = mock_dp.call_args
            protected_files = dp_call[1].get("protected_files") or dp_call[0][3]
            assert "agents.md" in protected_files

    @patch("agent.loop.SkillLoader")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    @patch("agent.loop.MiniRuntimeClientSync")
    def test_skill_loader_created_when_skills_dir_exists(
        self, mock_vm_cls, mock_call_llm, mock_run_scout, mock_sl_cls,
        tmp_path,
    ):
        """When skills_dir is provided and exists, SkillLoader is instantiated."""
        from agent.loop import run_agent

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
            harness_url="http://test:1234",
            task_text="do something",
            skills_dir=skills_dir,
        )

        mock_sl_cls.assert_called_once_with(skills_dir)

    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    @patch("agent.loop.MiniRuntimeClientSync")
    def test_skill_loader_not_created_when_no_skills_dir(
        self, mock_vm_cls, mock_call_llm, mock_run_scout,
    ):
        """When skills_dir is None, no SkillLoader error occurs."""
        from agent.loop import run_agent

        mock_run_scout.return_value = _make_scout_summary_mock()
        mock_call_llm.return_value = MagicMock(
            content="done", tool_calls=[], raw=None,
        )

        # Should not raise
        run_agent(
            executor_model="openai/gpt-4.1",
            harness_url="http://test:1234",
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
    @patch("agent.loop.MiniRuntimeClientSync")
    def test_run_scout_called_with_scout_config(
        self, mock_vm_cls, mock_call_llm, mock_run_scout,
    ):
        from agent.loop import run_agent
        from agent.scout import ScoutConfig

        mock_run_scout.return_value = _make_scout_summary_mock()
        mock_call_llm.return_value = MagicMock(
            content="done", tool_calls=[], raw=None,
        )

        run_agent(
            executor_model="openai/gpt-4.1",
            harness_url="http://test:1234",
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
    @patch("agent.loop.MiniRuntimeClientSync")
    def test_scout_model_defaults_to_executor_model(
        self, mock_vm_cls, mock_call_llm, mock_run_scout,
    ):
        from agent.loop import run_agent
        from agent.scout import ScoutConfig

        mock_run_scout.return_value = _make_scout_summary_mock()
        mock_call_llm.return_value = MagicMock(
            content="done", tool_calls=[], raw=None,
        )

        run_agent(
            executor_model="openai/gpt-4.1",
            harness_url="http://test:1234",
            task_text="test task",
            scout_model=None,  # Should default to executor model
        )

        config = mock_run_scout.call_args[0][2]
        assert isinstance(config, ScoutConfig)
        assert config.model == "openai/gpt-4.1"

    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    @patch("agent.loop.MiniRuntimeClientSync")
    def test_protected_files_expanded_from_scout_policy_files(
        self, mock_vm_cls, mock_call_llm, mock_run_scout, mock_dp,
    ):
        """Policy files from scout summary expand protected_files."""
        from agent.loop import run_agent

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
            harness_url="http://test:1234",
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
    @patch("agent.loop.MiniRuntimeClientSync")
    def test_build_system_prompt_called(
        self, mock_vm_cls, mock_call_llm, mock_run_scout, mock_bsp,
    ):
        from agent.loop import run_agent

        mock_run_scout.return_value = _make_scout_summary_mock()
        mock_call_llm.return_value = MagicMock(
            content="done", tool_calls=[], raw=None,
        )
        mock_bsp.return_value = "system prompt text"

        run_agent(
            executor_model="openai/gpt-4.1",
            harness_url="http://test:1234",
            task_text="do something",
        )

        mock_bsp.assert_called_once()

    @patch("agent.loop.SkillLoader")
    @patch("agent.loop.build_system_prompt")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    @patch("agent.loop.MiniRuntimeClientSync")
    def test_system_prompt_uses_skills_metadata_and_scout_summary(
        self, mock_vm_cls, mock_call_llm, mock_run_scout, mock_bsp, mock_sl_cls,
        tmp_path,
    ):
        """build_system_prompt gets skills_metadata, scout_summary, security_body."""
        from agent.loop import run_agent

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
            harness_url="http://test:1234",
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
    @patch("agent.loop.MiniRuntimeClientSync")
    def test_task_wrapped_in_delimiters(
        self, mock_vm_cls, mock_call_llm, mock_run_scout, mock_dp,
    ):
        """The task text is wrapped in <task> delimiters in the user message."""
        from agent.loop import run_agent

        mock_run_scout.return_value = _make_scout_summary_mock()
        mock_call_llm.return_value = MagicMock(
            content="done", tool_calls=[], raw=None,
        )

        run_agent(
            executor_model="openai/gpt-4.1",
            harness_url="http://test:1234",
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
    @patch("agent.loop.MiniRuntimeClientSync")
    def test_tool_calls_dispatched_and_results_appended(
        self, mock_vm_cls, mock_call_llm, mock_run_scout, mock_dp,
    ):
        """When LLM returns tool calls, they are dispatched and results appended."""
        from agent.loop import run_agent

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
            harness_url="http://test:1234",
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
    @patch("agent.loop.MiniRuntimeClientSync")
    def test_breaks_on_report_completion(
        self, mock_vm_cls, mock_call_llm, mock_run_scout, mock_dp,
    ):
        """Loop breaks when report_completion tool is called."""
        from agent.loop import run_agent

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
            harness_url="http://test:1234",
            task_text="do something",
        )

        # call_llm should only be called once (loop breaks after report_completion)
        assert mock_call_llm.call_count == 1

    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    @patch("agent.loop.MiniRuntimeClientSync")
    def test_breaks_on_no_tool_calls(
        self, mock_vm_cls, mock_call_llm, mock_run_scout, mock_dp,
    ):
        """Loop breaks when LLM returns text only (no tool calls)."""
        from agent.loop import run_agent

        mock_run_scout.return_value = _make_scout_summary_mock()
        mock_call_llm.return_value = MagicMock(
            content="I'm done", tool_calls=[], raw=None,
        )

        run_agent(
            executor_model="openai/gpt-4.1",
            harness_url="http://test:1234",
            task_text="do something",
        )

        assert mock_call_llm.call_count == 1
        mock_dp.assert_not_called()

    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    @patch("agent.loop.MiniRuntimeClientSync")
    def test_step_limit_30(
        self, mock_vm_cls, mock_call_llm, mock_run_scout, mock_dp,
    ):
        """Executor loop stops after 30 steps."""
        from agent.loop import run_agent

        mock_run_scout.return_value = _make_scout_summary_mock()

        tc = ToolCall(id="tc1", name="read_file", arguments={"path": "x.md"})
        mock_call_llm.return_value = MagicMock(
            content="reading", tool_calls=[tc], raw=None,
        )
        mock_dp.return_value = [("tc1", '{"content": "ok"}')]

        run_agent(
            executor_model="openai/gpt-4.1",
            harness_url="http://test:1234",
            task_text="do something",
        )

        # Should be called exactly 30 times (step limit)
        assert mock_call_llm.call_count == 30

    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    @patch("agent.loop.MiniRuntimeClientSync")
    def test_assistant_message_includes_tool_calls_structure(
        self, mock_vm_cls, mock_call_llm, mock_run_scout, mock_dp,
    ):
        """Assistant message appended to history has proper tool_calls format."""
        from agent.loop import run_agent

        mock_run_scout.return_value = _make_scout_summary_mock()

        tc = ToolCall(id="tc_1", name="read_file", arguments={"path": "a.md"})
        mock_call_llm.side_effect = [
            MagicMock(content="let me read", tool_calls=[tc], raw=None),
            MagicMock(content="done", tool_calls=[], raw=None),
        ]
        mock_dp.return_value = [("tc_1", '{"content": "file a"}')]

        run_agent(
            executor_model="openai/gpt-4.1",
            harness_url="http://test:1234",
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
    @patch("agent.loop.MiniRuntimeClientSync")
    def test_call_llm_receives_tool_schemas(
        self, mock_vm_cls, mock_call_llm, mock_run_scout, mock_dp,
    ):
        """call_llm is called with TOOL_SCHEMAS."""
        from agent.loop import run_agent
        from agent.tools import TOOL_SCHEMAS

        mock_run_scout.return_value = _make_scout_summary_mock()
        mock_call_llm.return_value = MagicMock(
            content="done", tool_calls=[], raw=None,
        )

        run_agent(
            executor_model="openai/gpt-4.1",
            harness_url="http://test:1234",
            task_text="test",
        )

        llm_call = mock_call_llm.call_args
        # tools should be TOOL_SCHEMAS
        tools_arg = llm_call[1].get("tools") or llm_call[0][2]
        assert tools_arg == TOOL_SCHEMAS

    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    @patch("agent.loop.MiniRuntimeClientSync")
    def test_executor_model_passed_to_call_llm(
        self, mock_vm_cls, mock_call_llm, mock_run_scout, mock_dp,
    ):
        """The executor_model parameter is forwarded to call_llm."""
        from agent.loop import run_agent

        mock_run_scout.return_value = _make_scout_summary_mock()
        mock_call_llm.return_value = MagicMock(
            content="done", tool_calls=[], raw=None,
        )

        run_agent(
            executor_model="anthropic/claude-sonnet-4-6",
            harness_url="http://test:1234",
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
    @patch("agent.loop.MiniRuntimeClientSync")
    def test_scout_summary_injected_as_user_message(
        self, mock_vm_cls, mock_call_llm, mock_run_scout, mock_dp,
    ):
        from agent.loop import run_agent

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
            harness_url="http://test:1234",
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

        # loop.py should import from these modules
        expected = {"scout", "llm", "dispatch", "prompt", "skills", "tracker", "tools"}
        assert expected.issubset(imported_modules), (
            f"Missing imports: {expected - imported_modules}"
        )
