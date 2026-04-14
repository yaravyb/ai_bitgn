import json
from pathlib import Path
from unittest.mock import Mock, MagicMock

from agent.config import AgentConfig
from agent.dispatch import dispatch, truncate_output, _normalize_yaml_quoting, _normalize_write_content
from skills import SkillLoader
from tasks import TaskManager


def _make_proto_response(data: dict):
    """Create a mock protobuf response that MessageToDict converts to data."""
    mock = Mock()
    # MessageToDict is called on the result; we patch it at the call site
    # Instead, just return a string for task manager tools
    return mock


class TestDispatch:
    def test_shadow_read_deleted_file_returns_not_found(self, mock_vm):
        tm = TaskManager()
        config = AgentConfig()
        # Defer a delete
        tm.defer_write("delete", {"path": "/test.md"})
        tm.track_delete("/test.md")
        # Now shadow-read the deleted file
        result = dispatch(mock_vm, "read", {"path": "/test.md"}, config, tm, defer_writes=True)
        parsed = json.loads(result)
        assert "error" in parsed
        assert "deleted" in parsed["error"]

    def test_shadow_read_rewritten_after_delete(self, mock_vm):
        tm = TaskManager()
        config = AgentConfig()
        # Defer a delete, then a write to same path
        tm.defer_write("delete", {"path": "/test.md"})
        tm.track_delete("/test.md")
        tm.defer_write("write", {"path": "/test.md", "content": "new content"})
        # Shadow read should NOT return "deleted" since write came after
        # The mock_vm.read returns None, which MessageToDict handles
        # Since last_op is "write", it falls through to the normal handler
        result = dispatch(mock_vm, "read", {"path": "/test.md"}, config, tm, defer_writes=True)
        # Should NOT contain "deleted" error
        assert "deleted" not in result.lower()

    def test_shadow_list_filters_deferred_deletes(self, mock_vm):
        tm = TaskManager()
        config = AgentConfig()
        tm.defer_write("delete", {"path": "/dir/old.md"})
        tm.track_delete("/dir/old.md")

        # Mock the list response
        list_response = Mock()
        # We need to handle MessageToDict
        mock_vm.list.return_value = list_response

        # Patch MessageToDict indirectly by making the response work
        import agent.dispatch as dispatch_mod
        original_mtd = dispatch_mod.MessageToDict
        dispatch_mod.MessageToDict = lambda r: {
            "entries": [
                {"name": "old.md", "isDir": False},
                {"name": "new.md", "isDir": False},
            ]
        }
        try:
            result = dispatch(mock_vm, "list", {"path": "/dir"}, config, tm, defer_writes=True)
            parsed = json.loads(result)
            names = [e["name"] for e in parsed.get("entries", [])]
            assert "old.md" not in names
            assert "new.md" in names
        finally:
            dispatch_mod.MessageToDict = original_mtd

    def test_deferred_write_stored_not_executed(self, mock_vm):
        tm = TaskManager()
        config = AgentConfig()
        result = dispatch(
            mock_vm, "write", {"path": "/new.md", "content": "hello"},
            config, tm, defer_writes=True,
        )
        assert result == "{}"
        assert len(tm.get_pending_writes()) == 1
        assert tm.get_pending_writes()[0]["op"] == "write"
        # The actual write should NOT have been called
        mock_vm.write.assert_not_called()

    def test_deferred_write_tracks_file_operations(self, mock_vm):
        tm = TaskManager()
        config = AgentConfig()
        dispatch(mock_vm, "write", {"path": "/a.md", "content": "x"}, config, tm, defer_writes=True)
        dispatch(mock_vm, "delete", {"path": "/b.md"}, config, tm, defer_writes=True)
        assert "/a.md" in tm._files_written
        assert "/b.md" in tm._files_deleted

    def test_unknown_tool_returns_error(self, mock_vm):
        config = AgentConfig()
        result = dispatch(mock_vm, "nonexistent_tool", {}, config)
        assert "Unknown tool" in result

    def test_task_management_tools(self, mock_vm):
        tm = TaskManager()
        config = AgentConfig()
        result = dispatch(mock_vm, "plan_create", {"steps": ["A", "B"]}, config, tm)
        assert "A" in result
        assert "B" in result


class TestTruncateOutput:
    def test_no_truncation_needed(self):
        text = "short text"
        assert truncate_output(text, 100) == text

    def test_naive_truncation(self):
        text = "a" * 200
        result = truncate_output(text, 100)
        assert len(result) < 200
        assert "[truncated]" in result

    def test_smart_truncation_plain_text(self):
        lines = "\n".join(f"line {i}" for i in range(50))
        result = truncate_output(lines, 100, smart=True)
        assert "[truncated]" in result
        # Should truncate at a line boundary
        assert result.count("\n") >= 1

    def test_smart_truncation_json(self):
        data = {"items": [f"item_{i}" for i in range(50)]}
        text = json.dumps(data, indent=2)
        result = truncate_output(text, 200, smart=True)
        assert "[truncated]" in result


class TestYamlQuotingNormalizer:
    def test_no_frontmatter_passthrough(self):
        content = "Just plain text\nNo YAML here."
        assert _normalize_yaml_quoting(content) == content

    def test_valid_frontmatter_unchanged(self):
        content = "---\ntitle: Hello World\ndate: 2026-01-01\n---\nBody text."
        assert _normalize_yaml_quoting(content) == content

    def test_colon_in_subject_gets_quoted(self):
        content = "---\nsubject: Re: Invoice request\nto: alice@test.com\n---\nBody."
        result = _normalize_yaml_quoting(content)
        assert "yaml" not in result.lower() or "---" in result  # shouldn't error
        # The fixed content should parse as valid YAML
        import yaml
        end = result.find("\n---", 3)
        fm = result[4:end]
        parsed = yaml.safe_load(fm)
        assert parsed["subject"] == "Re: Invoice request"
        assert parsed["to"] == "alice@test.com"

    def test_multiple_colons_in_value(self):
        content = "---\nsubject: Fwd: Re: Meeting notes: Q3\nfrom: bob@test.com\n---\nBody."
        result = _normalize_yaml_quoting(content)
        import yaml
        end = result.find("\n---", 3)
        parsed = yaml.safe_load(result[4:end])
        assert "Meeting notes" in parsed["subject"]

    def test_already_quoted_values_unchanged(self):
        content = '---\nsubject: "Re: Already quoted"\nto: alice@test.com\n---\nBody.'
        result = _normalize_yaml_quoting(content)
        import yaml
        end = result.find("\n---", 3)
        parsed = yaml.safe_load(result[4:end])
        assert parsed["subject"] == "Re: Already quoted"

    def test_inner_double_quotes_escaped(self):
        content = '---\nsubject: Re: He said "hello"\nto: x@y.com\n---\nBody.'
        result = _normalize_yaml_quoting(content)
        import yaml
        end = result.find("\n---", 3)
        parsed = yaml.safe_load(result[4:end])
        assert 'He said "hello"' in parsed["subject"]

    def test_chained_normalizer(self):
        # Gap + quoting combined
        content = "---\nsubject: Re: Test\nto: a@b.com\n---\n\n\nBody."
        result = _normalize_write_content(content)
        # Gap should be normalized
        assert "\n---\n\n\n" not in result
        # YAML should be valid
        import yaml
        end = result.find("\n---", 3)
        parsed = yaml.safe_load(result[4:end])
        assert parsed["subject"] == "Re: Test"
