"""Tests for agent.observability -- LLM observability via LiteLLM callbacks.

TDD: Tests written BEFORE implementation.
Task 2: Verify observability dependency group exists in pyproject.toml
Task 3: configure_observability() function behavior
Task 4: Metadata parameter forwarding in call_llm and trace grouping in loop
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import litellm


# ---------------------------------------------------------------------------
# Task 2: Verify observability dependency group in pyproject.toml
# ---------------------------------------------------------------------------

class TestObservabilityDependencyGroup:
    """Task 2: pyproject.toml has an observability dependency group."""

    def test_pyproject_has_observability_group(self):
        """The pyproject.toml must contain an 'observability' dependency group."""
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        content = pyproject_path.read_text()
        assert "observability" in content
        assert "langfuse" in content

    def test_observability_group_has_langfuse_version_constraint(self):
        """The observability group must require langfuse>=2.0.0."""
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        content = pyproject_path.read_text()
        assert 'langfuse>=2.0.0' in content


# ---------------------------------------------------------------------------
# Task 3.1: configure_observability() function
# ---------------------------------------------------------------------------

class TestConfigureObservabilityModule:
    """Task 3.1: Module exists and exports configure_observability."""

    def test_module_importable(self):
        from agent import observability
        assert hasattr(observability, "configure_observability")

    def test_configure_observability_is_callable(self):
        from agent.observability import configure_observability
        assert callable(configure_observability)

    def test_configure_observability_returns_none(self):
        from agent.observability import configure_observability
        result = configure_observability()
        assert result is None


class TestConfigureObservabilityNoOp:
    """Task 3.1: When env vars are missing, configure_observability is a no-op."""

    def setup_method(self):
        """Clear litellm callbacks and relevant env vars before each test."""
        litellm.success_callback = []
        litellm.failure_callback = []
        # Remove Langfuse env vars if set
        for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
            os.environ.pop(key, None)

    def test_noop_when_no_env_vars_set(self):
        """When LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are not set, callbacks stay empty."""
        from agent.observability import configure_observability
        configure_observability()
        assert "langfuse" not in litellm.success_callback
        assert "langfuse" not in litellm.failure_callback

    def test_noop_when_only_public_key_set(self):
        """When only LANGFUSE_PUBLIC_KEY is set, callbacks stay empty."""
        from agent.observability import configure_observability
        os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-lf-test"
        try:
            configure_observability()
            assert "langfuse" not in litellm.success_callback
            assert "langfuse" not in litellm.failure_callback
        finally:
            os.environ.pop("LANGFUSE_PUBLIC_KEY", None)

    def test_noop_when_only_secret_key_set(self):
        """When only LANGFUSE_SECRET_KEY is set, callbacks stay empty."""
        from agent.observability import configure_observability
        os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-test"
        try:
            configure_observability()
            assert "langfuse" not in litellm.success_callback
            assert "langfuse" not in litellm.failure_callback
        finally:
            os.environ.pop("LANGFUSE_SECRET_KEY", None)


class TestConfigureObservabilityImportError:
    """Task 3.1: When langfuse is not installed, graceful degradation."""

    def setup_method(self):
        litellm.success_callback = []
        litellm.failure_callback = []

    def test_handles_langfuse_import_error_gracefully(self):
        """When langfuse cannot be imported, function logs warning and returns (no crash)."""
        from agent.observability import configure_observability
        os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-lf-test"
        os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-test"

        try:
            # Simulate langfuse not being installed by temporarily hiding it
            with patch.dict(sys.modules, {"langfuse": None}):
                # The import inside configure_observability should fail
                # but the function should NOT raise
                configure_observability()

            # Callbacks should NOT be registered
            assert "langfuse" not in litellm.success_callback
            assert "langfuse" not in litellm.failure_callback
        finally:
            os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
            os.environ.pop("LANGFUSE_SECRET_KEY", None)


class TestConfigureObservabilityHostUnreachable:
    """When keys are set but the Langfuse host is down, callbacks must NOT be registered."""

    def setup_method(self):
        litellm.success_callback = []
        litellm.failure_callback = []

    def test_noop_when_host_unreachable(self):
        """When both keys are set but Langfuse host is unreachable, callbacks stay empty."""
        from agent.observability import configure_observability
        os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-lf-test"
        os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-test"

        try:
            mock_langfuse = MagicMock()
            with (
                patch.dict(sys.modules, {"langfuse": mock_langfuse}),
                patch("agent.observability._langfuse_host_reachable", return_value=False),
            ):
                configure_observability()

            assert "langfuse" not in litellm.success_callback
            assert "langfuse" not in litellm.failure_callback
        finally:
            os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
            os.environ.pop("LANGFUSE_SECRET_KEY", None)


class TestConfigureObservabilitySuccess:
    """Task 3.1: When both env vars are set and langfuse is importable, callbacks are registered."""

    def setup_method(self):
        litellm.success_callback = []
        litellm.failure_callback = []

    def test_registers_callbacks_when_configured(self):
        """When both keys are set, langfuse is importable, and host is reachable, callbacks are registered."""
        from agent.observability import configure_observability
        os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-lf-test"
        os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-test"

        try:
            mock_langfuse = MagicMock()
            with (
                patch.dict(sys.modules, {"langfuse": mock_langfuse}),
                patch("agent.observability._langfuse_host_reachable", return_value=True),
            ):
                configure_observability()

            assert "langfuse" in litellm.success_callback
            assert "langfuse" in litellm.failure_callback
        finally:
            os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
            os.environ.pop("LANGFUSE_SECRET_KEY", None)

    def test_never_raises_exception(self):
        """configure_observability must never raise, regardless of state."""
        from agent.observability import configure_observability
        # No env vars -- should not raise
        configure_observability()

        # With env vars but no langfuse -- should not raise
        os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-lf-test"
        os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-test"
        try:
            with patch.dict(sys.modules, {"langfuse": None}):
                configure_observability()
        finally:
            os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
            os.environ.pop("LANGFUSE_SECRET_KEY", None)


# ---------------------------------------------------------------------------
# Task 3.2: configure_observability called from main.py
# ---------------------------------------------------------------------------

class TestMainCallsConfigureObservability:
    """Task 3.2: main.py imports and calls configure_observability at startup."""

    def test_main_py_imports_configure_observability(self):
        """main.py must import configure_observability."""
        main_path = Path(__file__).parent.parent / "main.py"
        content = main_path.read_text()
        assert "configure_observability" in content
        assert "from agent.observability import configure_observability" in content

    def test_main_py_calls_configure_observability_before_loop(self):
        """configure_observability() call appears before the benchmark loop in main()."""
        main_path = Path(__file__).parent.parent / "main.py"
        content = main_path.read_text()
        # configure_observability() should be called before run_agent
        obs_pos = content.index("configure_observability()")
        loop_pos = content.index("for t in res.tasks:")
        assert obs_pos < loop_pos, (
            "configure_observability() must be called before the benchmark loop"
        )


# ---------------------------------------------------------------------------
# Task 4.1: call_llm metadata parameter
# ---------------------------------------------------------------------------

class TestCallLlmMetadataParameter:
    """Task 4.1: call_llm accepts optional metadata and forwards to litellm.completion."""

    @patch("agent.llm.completion")
    def test_call_llm_accepts_metadata_parameter(self, mock_completion):
        """call_llm should accept an optional metadata parameter."""
        import inspect
        from agent.llm import call_llm

        sig = inspect.signature(call_llm)
        assert "metadata" in sig.parameters
        # Default should be None
        assert sig.parameters["metadata"].default is None

    @patch("agent.llm.completion")
    def test_metadata_forwarded_to_litellm_completion(self, mock_completion):
        """When metadata is provided, it should be in kwargs to litellm.completion."""
        from agent.llm import call_llm

        mock_msg = MagicMock()
        mock_msg.content = "response"
        mock_msg.tool_calls = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_completion.return_value = mock_response

        metadata = {
            "trace_id": "abc-123",
            "trace_name": "run_agent",
            "session_id": "session-1",
        }
        call_llm(
            model="openai/gpt-4.1",
            messages=[{"role": "user", "content": "hello"}],
            metadata=metadata,
        )

        call_kwargs = mock_completion.call_args
        all_kwargs = call_kwargs.kwargs if call_kwargs.kwargs else call_kwargs[1]
        assert all_kwargs.get("metadata") == metadata

    @patch("agent.llm.completion")
    def test_no_metadata_key_when_none(self, mock_completion):
        """When metadata is None (default), metadata should not be in kwargs."""
        from agent.llm import call_llm

        mock_msg = MagicMock()
        mock_msg.content = "response"
        mock_msg.tool_calls = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_completion.return_value = mock_response

        call_llm(
            model="openai/gpt-4.1",
            messages=[{"role": "user", "content": "hello"}],
        )

        call_kwargs = mock_completion.call_args
        all_kwargs = call_kwargs.kwargs if call_kwargs.kwargs else call_kwargs[1]
        assert "metadata" not in all_kwargs


# ---------------------------------------------------------------------------
# Task 4.2: Trace metadata in run_agent / loop.py
# ---------------------------------------------------------------------------

class TestLoopTraceMetadata:
    """Task 4.2: run_agent generates trace metadata and passes to call_llm."""

    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    @patch("agent.loop.MiniRuntimeClientSync")
    def test_call_llm_receives_metadata_with_trace_id(
        self, mock_vm_cls, mock_call_llm, mock_run_scout, mock_dp,
    ):
        """call_llm should receive metadata containing a trace_id (UUID4)."""
        from agent.loop import run_agent
        import uuid

        mock_run_scout.return_value = MagicMock(
            policy_files={}, vault_skills={}, directory_tree="",
            files_read=set(), folders_explored=[],
            llm_summary=None, mode="llm", total_llm_steps=0, completed_fully=True,
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
        metadata = llm_call.kwargs.get("metadata") or llm_call[1].get("metadata")
        assert metadata is not None, "metadata must be passed to call_llm"
        assert "trace_id" in metadata
        # Verify it's a valid UUID4
        uuid.UUID(metadata["trace_id"], version=4)

    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    @patch("agent.loop.MiniRuntimeClientSync")
    def test_call_llm_receives_metadata_with_trace_name(
        self, mock_vm_cls, mock_call_llm, mock_run_scout, mock_dp,
    ):
        """Metadata should contain trace_name = 'run_agent'."""
        from agent.loop import run_agent

        mock_run_scout.return_value = MagicMock(
            policy_files={}, vault_skills={}, directory_tree="",
            files_read=set(), folders_explored=[],
            llm_summary=None, mode="llm", total_llm_steps=0, completed_fully=True,
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
        metadata = llm_call.kwargs.get("metadata") or llm_call[1].get("metadata")
        assert metadata["trace_name"] == "run_agent"

    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    @patch("agent.loop.MiniRuntimeClientSync")
    def test_call_llm_receives_metadata_with_session_id_from_env(
        self, mock_vm_cls, mock_call_llm, mock_run_scout, mock_dp,
    ):
        """Metadata should contain session_id from SESSION_ID env var."""
        from agent.loop import run_agent

        mock_run_scout.return_value = MagicMock(
            policy_files={}, vault_skills={}, directory_tree="",
            files_read=set(), folders_explored=[],
            llm_summary=None, mode="llm", total_llm_steps=0, completed_fully=True,
        )
        mock_call_llm.return_value = MagicMock(
            content="done", tool_calls=[], raw=None,
        )

        os.environ["SESSION_ID"] = "bench-run-42"
        try:
            run_agent(
                executor_model="openai/gpt-4.1",
                harness_url="http://test:1234",
                task_text="do something",
            )
        finally:
            os.environ.pop("SESSION_ID", None)

        llm_call = mock_call_llm.call_args
        metadata = llm_call.kwargs.get("metadata") or llm_call[1].get("metadata")
        assert metadata["session_id"] == "bench-run-42"

    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    @patch("agent.loop.MiniRuntimeClientSync")
    def test_session_id_empty_when_env_not_set(
        self, mock_vm_cls, mock_call_llm, mock_run_scout, mock_dp,
    ):
        """When SESSION_ID is not set, session_id should be empty string."""
        from agent.loop import run_agent

        mock_run_scout.return_value = MagicMock(
            policy_files={}, vault_skills={}, directory_tree="",
            files_read=set(), folders_explored=[],
            llm_summary=None, mode="llm", total_llm_steps=0, completed_fully=True,
        )
        mock_call_llm.return_value = MagicMock(
            content="done", tool_calls=[], raw=None,
        )

        os.environ.pop("SESSION_ID", None)
        run_agent(
            executor_model="openai/gpt-4.1",
            harness_url="http://test:1234",
            task_text="do something",
        )

        llm_call = mock_call_llm.call_args
        metadata = llm_call.kwargs.get("metadata") or llm_call[1].get("metadata")
        assert metadata["session_id"] == ""

    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    @patch("agent.loop.MiniRuntimeClientSync")
    def test_trace_metadata_contains_model_and_task(
        self, mock_vm_cls, mock_call_llm, mock_run_scout, mock_dp,
    ):
        """trace_metadata should contain the executor model and truncated task text."""
        from agent.loop import run_agent

        mock_run_scout.return_value = MagicMock(
            policy_files={}, vault_skills={}, directory_tree="",
            files_read=set(), folders_explored=[],
            llm_summary=None, mode="llm", total_llm_steps=0, completed_fully=True,
        )
        mock_call_llm.return_value = MagicMock(
            content="done", tool_calls=[], raw=None,
        )

        run_agent(
            executor_model="anthropic/claude-sonnet-4-6",
            harness_url="http://test:1234",
            task_text="A very long task description",
        )

        llm_call = mock_call_llm.call_args
        metadata = llm_call.kwargs.get("metadata") or llm_call[1].get("metadata")
        trace_meta = metadata["trace_metadata"]
        assert trace_meta["model"] == "anthropic/claude-sonnet-4-6"
        assert "A very long task description" in trace_meta["task"]

    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    @patch("agent.loop.MiniRuntimeClientSync")
    def test_task_text_truncated_at_200_chars(
        self, mock_vm_cls, mock_call_llm, mock_run_scout, mock_dp,
    ):
        """Task text in trace_metadata should be truncated to 200 chars."""
        from agent.loop import run_agent

        mock_run_scout.return_value = MagicMock(
            policy_files={}, vault_skills={}, directory_tree="",
            files_read=set(), folders_explored=[],
            llm_summary=None, mode="llm", total_llm_steps=0, completed_fully=True,
        )
        mock_call_llm.return_value = MagicMock(
            content="done", tool_calls=[], raw=None,
        )

        long_task = "x" * 500
        run_agent(
            executor_model="openai/gpt-4.1",
            harness_url="http://test:1234",
            task_text=long_task,
        )

        llm_call = mock_call_llm.call_args
        metadata = llm_call.kwargs.get("metadata") or llm_call[1].get("metadata")
        assert len(metadata["trace_metadata"]["task"]) <= 200

    @patch("agent.loop.dispatch_parallel")
    @patch("agent.loop.run_scout")
    @patch("agent.loop.call_llm")
    @patch("agent.loop.MiniRuntimeClientSync")
    def test_same_trace_id_for_all_calls_in_one_run(
        self, mock_vm_cls, mock_call_llm, mock_run_scout, mock_dp,
    ):
        """All call_llm calls within one run_agent must share the same trace_id."""
        from agent.loop import run_agent
        from agent.llm import ToolCall

        mock_run_scout.return_value = MagicMock(
            policy_files={}, vault_skills={}, directory_tree="",
            files_read=set(), folders_explored=[],
            llm_summary=None, mode="llm", total_llm_steps=0, completed_fully=True,
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

        # Both call_llm calls should have the same trace_id
        assert mock_call_llm.call_count == 2
        first_metadata = mock_call_llm.call_args_list[0].kwargs.get("metadata") or mock_call_llm.call_args_list[0][1].get("metadata")
        second_metadata = mock_call_llm.call_args_list[1].kwargs.get("metadata") or mock_call_llm.call_args_list[1][1].get("metadata")
        assert first_metadata["trace_id"] == second_metadata["trace_id"]


# ---------------------------------------------------------------------------
# Task 5: .env.example documents observability env vars
# ---------------------------------------------------------------------------

class TestEnvExampleObservabilitySection:
    """Task 5: .env.example documents all observability env vars."""

    def _read_env_example(self) -> str:
        env_path = Path(__file__).parent.parent / ".env.example"
        return env_path.read_text()

    def test_env_example_contains_langfuse_public_key(self):
        content = self._read_env_example()
        assert "LANGFUSE_PUBLIC_KEY" in content

    def test_env_example_contains_langfuse_secret_key(self):
        content = self._read_env_example()
        assert "LANGFUSE_SECRET_KEY" in content

    def test_env_example_contains_langfuse_host(self):
        content = self._read_env_example()
        assert "LANGFUSE_HOST" in content

    def test_env_example_contains_session_id(self):
        content = self._read_env_example()
        assert "SESSION_ID" in content

    def test_env_example_has_observability_section_header(self):
        content = self._read_env_example()
        assert "Observability" in content or "observability" in content
