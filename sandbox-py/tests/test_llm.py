"""Tests for agent.llm -- LiteLLM wrapper.

TDD: Tests written BEFORE implementation.
Task 4.1: LLMResponse and ToolCall dataclasses
Task 4.2: call_llm wrapping litellm.completion with parallel_tool_calls
Task 4.3: Parse tool_calls into ToolCall objects, handle None
Task 4.4: Error handling and retry for transient failures
"""

import json
import pytest
from dataclasses import fields
from unittest.mock import MagicMock, patch


class TestToolCallDataclass:
    """Task 4.1: ToolCall dataclass."""

    def test_tool_call_has_expected_fields(self):
        from agent.llm import ToolCall
        tc = ToolCall(id="tc_1", name="read_file", arguments={"path": "/a.md"})
        assert tc.id == "tc_1"
        assert tc.name == "read_file"
        assert tc.arguments == {"path": "/a.md"}

    def test_tool_call_is_dataclass(self):
        from agent.llm import ToolCall
        field_names = {f.name for f in fields(ToolCall)}
        assert field_names == {"id", "name", "arguments"}


class TestLLMResponseDataclass:
    """Task 4.1: LLMResponse dataclass."""

    def test_llm_response_has_expected_fields(self):
        from agent.llm import LLMResponse
        resp = LLMResponse(content="hello", tool_calls=[], raw=None)
        assert resp.content == "hello"
        assert resp.tool_calls == []
        assert resp.raw is None

    def test_llm_response_is_dataclass(self):
        from agent.llm import LLMResponse
        field_names = {f.name for f in fields(LLMResponse)}
        assert field_names == {"content", "tool_calls", "raw"}

    def test_llm_response_content_can_be_none(self):
        from agent.llm import LLMResponse
        resp = LLMResponse(content=None, tool_calls=[], raw=None)
        assert resp.content is None


class TestCallLlmSignature:
    """Task 4.2: call_llm function signature and basic behavior."""

    @patch("agent.llm.completion")
    def test_call_llm_calls_litellm_completion(self, mock_completion):
        from agent.llm import call_llm
        # Set up mock response
        mock_msg = MagicMock()
        mock_msg.content = "test response"
        mock_msg.tool_calls = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_completion.return_value = mock_response

        result = call_llm(
            model="openai/gpt-4.1",
            messages=[{"role": "user", "content": "hello"}],
        )

        mock_completion.assert_called_once()
        assert result.content == "test response"

    @patch("agent.llm.completion")
    def test_call_llm_passes_tools_and_parallel_flag(self, mock_completion):
        from agent.llm import call_llm
        mock_msg = MagicMock()
        mock_msg.content = None
        mock_msg.tool_calls = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_completion.return_value = mock_response

        tools = [{"type": "function", "function": {"name": "test"}}]
        call_llm(
            model="openai/gpt-4.1",
            messages=[{"role": "user", "content": "hello"}],
            tools=tools,
        )

        call_kwargs = mock_completion.call_args
        assert call_kwargs.kwargs.get("tools") == tools or call_kwargs[1].get("tools") == tools
        # parallel_tool_calls should be True when tools are provided
        all_kwargs = call_kwargs.kwargs if call_kwargs.kwargs else call_kwargs[1]
        assert all_kwargs.get("parallel_tool_calls") is True

    @patch("agent.llm.completion")
    def test_call_llm_no_parallel_flag_without_tools(self, mock_completion):
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
        assert "parallel_tool_calls" not in all_kwargs

    @patch("agent.llm.completion")
    def test_call_llm_passes_max_tokens(self, mock_completion):
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
            max_tokens=4096,
        )

        call_kwargs = mock_completion.call_args
        all_kwargs = call_kwargs.kwargs if call_kwargs.kwargs else call_kwargs[1]
        assert all_kwargs["max_tokens"] == 4096

    @patch("agent.llm.completion")
    def test_call_llm_default_max_tokens_is_16384(self, mock_completion):
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
        assert all_kwargs["max_tokens"] == 16384


class TestToolCallParsing:
    """Task 4.3: Parse tool_calls from response."""

    @patch("agent.llm.completion")
    def test_parses_tool_calls_into_typed_objects(self, mock_completion):
        from agent.llm import call_llm, ToolCall

        # Create mock tool call
        mock_fn = MagicMock()
        mock_fn.name = "read_file"
        mock_fn.arguments = json.dumps({"path": "/a.md"})
        mock_tc = MagicMock()
        mock_tc.id = "tc_1"
        mock_tc.function = mock_fn

        mock_msg = MagicMock()
        mock_msg.content = None
        mock_msg.tool_calls = [mock_tc]
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_completion.return_value = mock_response

        result = call_llm("openai/gpt-4.1", [{"role": "user", "content": "x"}])

        assert len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert isinstance(tc, ToolCall)
        assert tc.id == "tc_1"
        assert tc.name == "read_file"
        assert tc.arguments == {"path": "/a.md"}

    @patch("agent.llm.completion")
    def test_handles_none_tool_calls(self, mock_completion):
        """When tool_calls is None, result.tool_calls should be empty list."""
        from agent.llm import call_llm

        mock_msg = MagicMock()
        mock_msg.content = "I'll help you with that."
        mock_msg.tool_calls = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_completion.return_value = mock_response

        result = call_llm("openai/gpt-4.1", [{"role": "user", "content": "x"}])

        assert result.tool_calls == []
        assert result.content == "I'll help you with that."

    @patch("agent.llm.completion")
    def test_parses_multiple_parallel_tool_calls(self, mock_completion):
        from agent.llm import call_llm, ToolCall

        mock_tcs = []
        for i, name in enumerate(["read_file", "list_dir"]):
            mock_fn = MagicMock()
            mock_fn.name = name
            mock_fn.arguments = json.dumps({"path": f"/path{i}"})
            mock_tc = MagicMock()
            mock_tc.id = f"tc_{i}"
            mock_tc.function = mock_fn
            mock_tcs.append(mock_tc)

        mock_msg = MagicMock()
        mock_msg.content = None
        mock_msg.tool_calls = mock_tcs
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_completion.return_value = mock_response

        result = call_llm("openai/gpt-4.1", [{"role": "user", "content": "x"}])

        assert len(result.tool_calls) == 2
        assert result.tool_calls[0].name == "read_file"
        assert result.tool_calls[1].name == "list_dir"

    @patch("agent.llm.completion")
    def test_preserves_raw_response(self, mock_completion):
        from agent.llm import call_llm

        mock_msg = MagicMock()
        mock_msg.content = "hello"
        mock_msg.tool_calls = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_completion.return_value = mock_response

        result = call_llm("openai/gpt-4.1", [{"role": "user", "content": "x"}])

        assert result.raw is mock_response


class TestErrorHandling:
    """Task 4.4: Error handling and retry for transient failures."""

    @patch("agent.llm.completion")
    def test_retries_on_connection_error(self, mock_completion):
        from agent.llm import call_llm
        import litellm

        # First call fails, second succeeds
        mock_msg = MagicMock()
        mock_msg.content = "success"
        mock_msg.tool_calls = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_completion.side_effect = [
            ConnectionError("connection reset"),
            mock_response,
        ]

        result = call_llm("openai/gpt-4.1", [{"role": "user", "content": "x"}])
        assert result.content == "success"
        assert mock_completion.call_count == 2

    @patch("agent.llm.completion")
    def test_retries_on_rate_limit(self, mock_completion):
        from agent.llm import call_llm
        import litellm

        mock_msg = MagicMock()
        mock_msg.content = "success"
        mock_msg.tool_calls = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_completion.side_effect = [
            litellm.RateLimitError(
                message="Rate limit exceeded",
                llm_provider="openai",
                model="gpt-4.1",
            ),
            mock_response,
        ]

        result = call_llm("openai/gpt-4.1", [{"role": "user", "content": "x"}])
        assert result.content == "success"
        assert mock_completion.call_count == 2

    @patch("agent.llm.completion")
    def test_raises_after_max_retries(self, mock_completion):
        from agent.llm import call_llm

        mock_completion.side_effect = ConnectionError("always fails")

        with pytest.raises(ConnectionError):
            call_llm("openai/gpt-4.1", [{"role": "user", "content": "x"}])

        # Should have retried multiple times
        assert mock_completion.call_count > 1

    @patch("agent.llm.completion")
    def test_non_retryable_error_raises_immediately(self, mock_completion):
        from agent.llm import call_llm
        import litellm

        mock_completion.side_effect = litellm.AuthenticationError(
            message="Invalid API key",
            llm_provider="openai",
            model="gpt-4.1",
        )

        with pytest.raises(litellm.AuthenticationError):
            call_llm("openai/gpt-4.1", [{"role": "user", "content": "x"}])

        # Should NOT have retried
        assert mock_completion.call_count == 1


class TestLlmIsLeaf:
    """llm.py must have zero imports from other agent/ modules."""

    def test_no_agent_imports(self):
        import agent.llm as mod
        with open(mod.__file__) as f:
            source = f.read()
        import re
        agent_imports = re.findall(r"from\s+agent\.", source)
        assert agent_imports == [], (
            f"llm.py must not import from agent modules: {agent_imports}"
        )
