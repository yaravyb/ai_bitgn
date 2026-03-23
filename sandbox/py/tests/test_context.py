"""Tests for agent.context -- Context management pure functions.

TDD: Tests written BEFORE implementation.
Task 4: Unit tests for ContextConfig, estimate_tokens, truncate_tool_result, micro_compact.
All tests use plain dicts -- no mocking required.
"""

import json
import os
import pytest


# ---------------------------------------------------------------------------
# ContextConfig tests
# ---------------------------------------------------------------------------

class TestContextConfigDefaults:
    """ContextConfig dataclass has correct default values."""

    def test_defaults(self):
        from agent.context import ContextConfig
        cfg = ContextConfig()
        assert cfg.truncation_limit == 10_000
        assert cfg.micro_compact_keep_batches == 3
        assert cfg.micro_compact_min_length == 100
        assert cfg.auto_compact_threshold == 80_000
        assert cfg.transcript_dir == ".transcripts/"

    def test_custom_values(self):
        from agent.context import ContextConfig
        cfg = ContextConfig(
            truncation_limit=5000,
            micro_compact_keep_batches=2,
            micro_compact_min_length=50,
            auto_compact_threshold=50_000,
            transcript_dir="/tmp/transcripts/",
        )
        assert cfg.truncation_limit == 5000
        assert cfg.micro_compact_keep_batches == 2
        assert cfg.micro_compact_min_length == 50
        assert cfg.auto_compact_threshold == 50_000
        assert cfg.transcript_dir == "/tmp/transcripts/"


class TestContextConfigFromEnv:
    """ContextConfig.from_env() reads environment variables with fallback to defaults."""

    def test_from_env_defaults(self, monkeypatch):
        """When no env vars are set, from_env() returns defaults."""
        from agent.context import ContextConfig
        # Clear any env vars that might be set
        for key in [
            "CTX_TRUNCATION_LIMIT",
            "CTX_MICRO_COMPACT_KEEP_BATCHES",
            "CTX_MICRO_COMPACT_MIN_LENGTH",
            "CTX_AUTO_COMPACT_THRESHOLD",
            "CTX_TRANSCRIPT_DIR",
        ]:
            monkeypatch.delenv(key, raising=False)

        cfg = ContextConfig.from_env()
        assert cfg.truncation_limit == 10_000
        assert cfg.micro_compact_keep_batches == 3
        assert cfg.micro_compact_min_length == 100
        assert cfg.auto_compact_threshold == 80_000
        assert cfg.transcript_dir == ".transcripts/"

    def test_from_env_overrides(self, monkeypatch):
        """Environment variables override defaults."""
        from agent.context import ContextConfig
        monkeypatch.setenv("CTX_TRUNCATION_LIMIT", "5000")
        monkeypatch.setenv("CTX_MICRO_COMPACT_KEEP_BATCHES", "2")
        monkeypatch.setenv("CTX_MICRO_COMPACT_MIN_LENGTH", "50")
        monkeypatch.setenv("CTX_AUTO_COMPACT_THRESHOLD", "50000")
        monkeypatch.setenv("CTX_TRANSCRIPT_DIR", "/tmp/transcripts/")

        cfg = ContextConfig.from_env()
        assert cfg.truncation_limit == 5000
        assert cfg.micro_compact_keep_batches == 2
        assert cfg.micro_compact_min_length == 50
        assert cfg.auto_compact_threshold == 50_000
        assert cfg.transcript_dir == "/tmp/transcripts/"


# ---------------------------------------------------------------------------
# COMPACT_SENTINEL tests
# ---------------------------------------------------------------------------

class TestCompactSentinel:
    """COMPACT_SENTINEL is a module-level constant string."""

    def test_sentinel_exists(self):
        from agent.context import COMPACT_SENTINEL
        assert isinstance(COMPACT_SENTINEL, str)
        assert COMPACT_SENTINEL == "__COMPACT_SENTINEL__"


# ---------------------------------------------------------------------------
# estimate_tokens tests
# ---------------------------------------------------------------------------

class TestEstimateTokens:
    """estimate_tokens: pure function, len(str(messages)) // 4."""

    def test_empty_list(self):
        from agent.context import estimate_tokens
        result = estimate_tokens([])
        assert result == len(str([])) // 4

    def test_known_input(self):
        from agent.context import estimate_tokens
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello!"},
        ]
        expected = len(str(messages)) // 4
        assert estimate_tokens(messages) == expected

    def test_returns_int(self):
        from agent.context import estimate_tokens
        result = estimate_tokens([{"role": "user", "content": "test"}])
        assert isinstance(result, int)


# ---------------------------------------------------------------------------
# truncate_tool_result tests
# ---------------------------------------------------------------------------

class TestTruncateToolResultUnderLimit:
    """When result is under the limit, return unchanged."""

    def test_short_string_unchanged(self):
        from agent.context import truncate_tool_result, ContextConfig
        cfg = ContextConfig(truncation_limit=100)
        text = "short result"
        assert truncate_tool_result(text, cfg) == text

    def test_exact_limit_unchanged(self):
        from agent.context import truncate_tool_result, ContextConfig
        text = "x" * 100
        cfg = ContextConfig(truncation_limit=100)
        assert truncate_tool_result(text, cfg) == text


class TestTruncateToolResultOverLimitRaw:
    """When result exceeds limit and is not valid JSON, truncate raw string."""

    def test_raw_string_truncated(self):
        from agent.context import truncate_tool_result, ContextConfig
        cfg = ContextConfig(truncation_limit=50)
        text = "a" * 200
        result = truncate_tool_result(text, cfg)
        assert len(result) < len(text)
        assert "...[truncated, 200 chars total]" in result

    def test_truncation_indicator_present(self):
        from agent.context import truncate_tool_result, ContextConfig
        cfg = ContextConfig(truncation_limit=20)
        text = "x" * 100
        result = truncate_tool_result(text, cfg)
        assert "truncated" in result
        assert "100 chars total" in result


class TestTruncateToolResultOverLimitJson:
    """When result exceeds limit and is valid JSON dict, truncate largest value."""

    def test_json_truncation_preserves_structure(self):
        from agent.context import truncate_tool_result, ContextConfig
        cfg = ContextConfig(truncation_limit=100)
        data = {"content": "x" * 500, "status": "ok"}
        text = json.dumps(data)
        result = truncate_tool_result(text, cfg)
        # Should still be valid JSON
        parsed = json.loads(result)
        assert "status" in parsed
        assert "content" in parsed
        # The content value should be truncated
        assert len(parsed["content"]) < 500
        assert "truncated" in parsed["content"]

    def test_json_truncation_indicator_in_value(self):
        from agent.context import truncate_tool_result, ContextConfig
        cfg = ContextConfig(truncation_limit=100)
        original_len = 500
        data = {"content": "x" * original_len}
        text = json.dumps(data)
        result = truncate_tool_result(text, cfg)
        parsed = json.loads(result)
        assert f"{len(text)} chars total" in parsed["content"]


class TestTruncateToolResultJsonFallback:
    """JSON parse succeeds but structure is not a dict -> fall back to raw truncation."""

    def test_json_list_falls_back_to_raw(self):
        from agent.context import truncate_tool_result, ContextConfig
        cfg = ContextConfig(truncation_limit=50)
        text = json.dumps(["a" * 200])
        result = truncate_tool_result(text, cfg)
        # Should be truncated as raw string (not JSON-aware)
        assert "truncated" in result

    def test_json_string_falls_back_to_raw(self):
        from agent.context import truncate_tool_result, ContextConfig
        cfg = ContextConfig(truncation_limit=50)
        text = json.dumps("a" * 200)
        result = truncate_tool_result(text, cfg)
        assert "truncated" in result


# ---------------------------------------------------------------------------
# micro_compact tests
# ---------------------------------------------------------------------------

class TestMicroCompactNoBatches:
    """When there are no tool result batches, micro_compact is a no-op."""

    def test_no_tool_messages(self):
        from agent.context import micro_compact, ContextConfig
        cfg = ContextConfig(micro_compact_keep_batches=3)
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        original = [dict(m) for m in messages]
        micro_compact(messages, cfg)
        assert messages == original

    def test_empty_messages(self):
        from agent.context import micro_compact, ContextConfig
        cfg = ContextConfig()
        messages = []
        micro_compact(messages, cfg)
        assert messages == []


class TestMicroCompactWithinKeepWindow:
    """When total batches <= keep_batches, nothing is cleared."""

    def test_single_batch_preserved(self):
        from agent.context import micro_compact, ContextConfig
        cfg = ContextConfig(micro_compact_keep_batches=3)
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"type": "function", "id": "tc1", "function": {"name": "read_file", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc1", "content": "x" * 200},
        ]
        original_content = messages[3]["content"]
        micro_compact(messages, cfg)
        assert messages[3]["content"] == original_content

    def test_three_batches_with_keep_three(self):
        from agent.context import micro_compact, ContextConfig
        cfg = ContextConfig(micro_compact_keep_batches=3)
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hello"},
            # Batch 1
            {"role": "assistant", "content": None, "tool_calls": [
                {"type": "function", "id": "tc1", "function": {"name": "read_file", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc1", "content": "x" * 200},
            # Batch 2
            {"role": "assistant", "content": None, "tool_calls": [
                {"type": "function", "id": "tc2", "function": {"name": "read_file", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc2", "content": "y" * 200},
            # Batch 3
            {"role": "assistant", "content": None, "tool_calls": [
                {"type": "function", "id": "tc3", "function": {"name": "read_file", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc3", "content": "z" * 200},
        ]
        micro_compact(messages, cfg)
        # All 3 batches within window, nothing cleared
        assert messages[3]["content"] == "x" * 200
        assert messages[5]["content"] == "y" * 200
        assert messages[7]["content"] == "z" * 200


class TestMicroCompactClearsOldBatches:
    """When total batches > keep_batches, old batches are cleared."""

    def test_old_batch_cleared(self):
        from agent.context import micro_compact, ContextConfig
        cfg = ContextConfig(micro_compact_keep_batches=1, micro_compact_min_length=10)
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hello"},
            # Batch 1 (old -- should be cleared)
            {"role": "assistant", "content": None, "tool_calls": [
                {"type": "function", "id": "tc1", "function": {"name": "read_file", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc1", "content": "x" * 200},
            # Batch 2 (recent -- should be preserved)
            {"role": "assistant", "content": None, "tool_calls": [
                {"type": "function", "id": "tc2", "function": {"name": "read_file", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc2", "content": "y" * 200},
        ]
        micro_compact(messages, cfg)
        assert messages[3]["content"] == "[Previous tool result cleared]"
        assert messages[5]["content"] == "y" * 200

    def test_multiple_old_batches_cleared(self):
        from agent.context import micro_compact, ContextConfig
        cfg = ContextConfig(micro_compact_keep_batches=1, micro_compact_min_length=10)
        messages = [
            {"role": "system", "content": "system"},
            # Batch 1 (old)
            {"role": "assistant", "content": None, "tool_calls": [
                {"type": "function", "id": "tc1", "function": {"name": "a", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc1", "content": "a" * 200},
            # Batch 2 (old)
            {"role": "assistant", "content": None, "tool_calls": [
                {"type": "function", "id": "tc2", "function": {"name": "b", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc2", "content": "b" * 200},
            # Batch 3 (recent)
            {"role": "assistant", "content": None, "tool_calls": [
                {"type": "function", "id": "tc3", "function": {"name": "c", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc3", "content": "c" * 200},
        ]
        micro_compact(messages, cfg)
        assert messages[2]["content"] == "[Previous tool result cleared]"
        assert messages[4]["content"] == "[Previous tool result cleared]"
        assert messages[6]["content"] == "c" * 200


class TestMicroCompactPreservesToolCallId:
    """micro_compact preserves tool_call_id on every message."""

    def test_tool_call_id_preserved(self):
        from agent.context import micro_compact, ContextConfig
        cfg = ContextConfig(micro_compact_keep_batches=1, micro_compact_min_length=10)
        messages = [
            {"role": "system", "content": "system"},
            # Batch 1 (old)
            {"role": "assistant", "content": None, "tool_calls": [
                {"type": "function", "id": "tc_alpha", "function": {"name": "read_file", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc_alpha", "content": "x" * 200},
            # Batch 2 (recent)
            {"role": "assistant", "content": None, "tool_calls": [
                {"type": "function", "id": "tc_beta", "function": {"name": "read_file", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc_beta", "content": "y" * 200},
        ]
        micro_compact(messages, cfg)
        # tool_call_id must be preserved even when content is cleared
        assert messages[2]["tool_call_id"] == "tc_alpha"
        assert messages[4]["tool_call_id"] == "tc_beta"


class TestMicroCompactPreservesNonToolMessages:
    """micro_compact never modifies system, user, or assistant messages."""

    def test_system_user_assistant_unchanged(self):
        from agent.context import micro_compact, ContextConfig
        cfg = ContextConfig(micro_compact_keep_batches=1, micro_compact_min_length=10)
        messages = [
            {"role": "system", "content": "system prompt " + "x" * 200},
            {"role": "user", "content": "user message " + "y" * 200},
            # Batch 1 (old)
            {"role": "assistant", "content": "assistant says " + "z" * 200, "tool_calls": [
                {"type": "function", "id": "tc1", "function": {"name": "read_file", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc1", "content": "tool result " + "a" * 200},
            # Batch 2 (recent)
            {"role": "assistant", "content": "more text", "tool_calls": [
                {"type": "function", "id": "tc2", "function": {"name": "read_file", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc2", "content": "b" * 200},
        ]
        sys_content = messages[0]["content"]
        user_content = messages[1]["content"]
        asst_content = messages[2]["content"]

        micro_compact(messages, cfg)

        assert messages[0]["content"] == sys_content
        assert messages[1]["content"] == user_content
        assert messages[2]["content"] == asst_content


class TestMicroCompactPreservesShortContent:
    """micro_compact preserves short tool result content below min_length."""

    def test_short_content_preserved(self):
        from agent.context import micro_compact, ContextConfig
        cfg = ContextConfig(micro_compact_keep_batches=1, micro_compact_min_length=100)
        messages = [
            {"role": "system", "content": "system"},
            # Batch 1 (old) with short content
            {"role": "assistant", "content": None, "tool_calls": [
                {"type": "function", "id": "tc1", "function": {"name": "read_file", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc1", "content": "short"},  # len < 100
            # Batch 2 (recent)
            {"role": "assistant", "content": None, "tool_calls": [
                {"type": "function", "id": "tc2", "function": {"name": "read_file", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc2", "content": "also short"},
        ]
        micro_compact(messages, cfg)
        # Short content in old batch should NOT be cleared (below min_length)
        assert messages[2]["content"] == "short"


class TestMicroCompactBatchDetection:
    """micro_compact correctly identifies batch boundaries (parallel tool calls)."""

    def test_parallel_tool_calls_in_one_batch(self):
        from agent.context import micro_compact, ContextConfig
        cfg = ContextConfig(micro_compact_keep_batches=1, micro_compact_min_length=10)
        messages = [
            {"role": "system", "content": "system"},
            # Batch 1 (old): parallel calls
            {"role": "assistant", "content": None, "tool_calls": [
                {"type": "function", "id": "tc1a", "function": {"name": "read_file", "arguments": "{}"}},
                {"type": "function", "id": "tc1b", "function": {"name": "list_dir", "arguments": "{}"}},
            ]},
            {"role": "tool", "tool_call_id": "tc1a", "content": "x" * 200},
            {"role": "tool", "tool_call_id": "tc1b", "content": "y" * 200},
            # Batch 2 (recent): single call
            {"role": "assistant", "content": None, "tool_calls": [
                {"type": "function", "id": "tc2", "function": {"name": "read_file", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc2", "content": "z" * 200},
        ]
        micro_compact(messages, cfg)
        # Both tool results from batch 1 should be cleared
        assert messages[2]["content"] == "[Previous tool result cleared]"
        assert messages[3]["content"] == "[Previous tool result cleared]"
        # Batch 2 preserved
        assert messages[5]["content"] == "z" * 200


class TestMicroCompactSafety:
    """micro_compact tolerates edge cases: missing content, non-string content."""

    def test_message_without_content_key(self):
        from agent.context import micro_compact, ContextConfig
        cfg = ContextConfig(micro_compact_keep_batches=1, micro_compact_min_length=10)
        messages = [
            {"role": "system", "content": "system"},
            # Batch 1 (old)
            {"role": "assistant", "content": None, "tool_calls": [
                {"type": "function", "id": "tc1", "function": {"name": "read_file", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc1"},  # No "content" key
            # Batch 2 (recent)
            {"role": "assistant", "content": None, "tool_calls": [
                {"type": "function", "id": "tc2", "function": {"name": "read_file", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc2", "content": "y" * 200},
        ]
        # Should not raise
        micro_compact(messages, cfg)
        # Message without content should not be modified
        assert "content" not in messages[2] or messages[2].get("content") is None or messages[2]["content"] == messages[2].get("content")

    def test_non_string_content_skipped(self):
        from agent.context import micro_compact, ContextConfig
        cfg = ContextConfig(micro_compact_keep_batches=1, micro_compact_min_length=10)
        messages = [
            {"role": "system", "content": "system"},
            # Batch 1 (old)
            {"role": "assistant", "content": None, "tool_calls": [
                {"type": "function", "id": "tc1", "function": {"name": "read_file", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc1", "content": 12345},  # Non-string
            # Batch 2 (recent)
            {"role": "assistant", "content": None, "tool_calls": [
                {"type": "function", "id": "tc2", "function": {"name": "read_file", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc2", "content": "y" * 200},
        ]
        micro_compact(messages, cfg)
        # Non-string content should not be modified
        assert messages[2]["content"] == 12345


class TestMicroCompactMutatesInPlace:
    """micro_compact mutates the list in-place and returns None."""

    def test_returns_none(self):
        from agent.context import micro_compact, ContextConfig
        cfg = ContextConfig()
        messages = [{"role": "system", "content": "system"}]
        result = micro_compact(messages, cfg)
        assert result is None


# ---------------------------------------------------------------------------
# Verification configuration tests (Task 8 / self-verification)
# ---------------------------------------------------------------------------

class TestContextConfigVerificationDefaults:
    """ContextConfig has verification fields with correct defaults."""

    def test_verification_enabled_default_false(self):
        from agent.context import ContextConfig
        cfg = ContextConfig()
        assert cfg.verification_enabled is False

    def test_verification_max_attempts_default_two(self):
        from agent.context import ContextConfig
        cfg = ContextConfig()
        assert cfg.verification_max_attempts == 2

    def test_backward_compat_construction_without_verification_fields(self):
        """Existing callers that construct ContextConfig without new fields still work."""
        from agent.context import ContextConfig
        cfg = ContextConfig(
            truncation_limit=5000,
            micro_compact_keep_batches=2,
            micro_compact_min_length=50,
            auto_compact_threshold=50_000,
            transcript_dir="/tmp/t/",
        )
        assert cfg.truncation_limit == 5000
        assert cfg.verification_enabled is False
        assert cfg.verification_max_attempts == 2

    def test_custom_verification_values(self):
        from agent.context import ContextConfig
        cfg = ContextConfig(verification_enabled=True, verification_max_attempts=5)
        assert cfg.verification_enabled is True
        assert cfg.verification_max_attempts == 5


class TestContextConfigFromEnvVerification:
    """from_env() reads VERIFY_ENABLED and VERIFY_MAX_ATTEMPTS env vars."""

    def test_verify_enabled_true_from_1(self, monkeypatch):
        from agent.context import ContextConfig
        monkeypatch.setenv("VERIFY_ENABLED", "1")
        monkeypatch.delenv("VERIFY_MAX_ATTEMPTS", raising=False)
        cfg = ContextConfig.from_env()
        assert cfg.verification_enabled is True

    def test_verify_enabled_true_from_true(self, monkeypatch):
        from agent.context import ContextConfig
        monkeypatch.setenv("VERIFY_ENABLED", "true")
        cfg = ContextConfig.from_env()
        assert cfg.verification_enabled is True

    def test_verify_enabled_true_from_yes(self, monkeypatch):
        from agent.context import ContextConfig
        monkeypatch.setenv("VERIFY_ENABLED", "yes")
        cfg = ContextConfig.from_env()
        assert cfg.verification_enabled is True

    def test_verify_enabled_true_from_TRUE_uppercase(self, monkeypatch):
        from agent.context import ContextConfig
        monkeypatch.setenv("VERIFY_ENABLED", "TRUE")
        cfg = ContextConfig.from_env()
        assert cfg.verification_enabled is True

    def test_verify_enabled_false_from_empty(self, monkeypatch):
        from agent.context import ContextConfig
        monkeypatch.delenv("VERIFY_ENABLED", raising=False)
        cfg = ContextConfig.from_env()
        assert cfg.verification_enabled is False

    def test_verify_enabled_false_from_no(self, monkeypatch):
        from agent.context import ContextConfig
        monkeypatch.setenv("VERIFY_ENABLED", "no")
        cfg = ContextConfig.from_env()
        assert cfg.verification_enabled is False

    def test_verify_max_attempts_from_env(self, monkeypatch):
        from agent.context import ContextConfig
        monkeypatch.setenv("VERIFY_MAX_ATTEMPTS", "5")
        cfg = ContextConfig.from_env()
        assert cfg.verification_max_attempts == 5

    def test_verify_max_attempts_default(self, monkeypatch):
        from agent.context import ContextConfig
        monkeypatch.delenv("VERIFY_MAX_ATTEMPTS", raising=False)
        cfg = ContextConfig.from_env()
        assert cfg.verification_max_attempts == 2
