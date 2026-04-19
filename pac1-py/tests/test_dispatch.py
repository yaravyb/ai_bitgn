import json
from pathlib import Path
from unittest.mock import Mock, MagicMock

from agent.config import AgentConfig
from agent.dispatch import dispatch, truncate_output, _normalize_yaml_quoting, _normalize_write_content, _normalize_ascii_tables, _parse_ascii_table, _text_match
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

    def test_shadow_read_returns_pending_write_content(self, mock_vm):
        """Reading a path with a pending write returns that write's content.

        Without this, an agent reading back its own deferred write would
        hit the VM (which hasn't applied the write yet) and get a false
        'file not found' that triggers spurious fabrication detection.
        """
        tm = TaskManager()
        config = AgentConfig()
        # Agent defers a write to a new outbox file
        tm.defer_write("write", {"path": "/60_outbox/outbox/eml_X.md", "content": "---\nto: a@b\n---\nhi"})
        tm.track_write("/60_outbox/outbox/eml_X.md")
        # Agent reads it back (self-verification)
        result = dispatch(mock_vm, "read", {"path": "/60_outbox/outbox/eml_X.md"}, config, tm, defer_writes=True)
        parsed = json.loads(result)
        # Should return the written content, NOT a not-found error
        assert "content" in parsed
        assert "---\nto: a@b" in parsed["content"]
        assert "error" not in parsed

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


class TestAsciiTableNormalizer:
    def test_no_tables_passthrough(self):
        content = "Just plain text\nNo tables here."
        assert _normalize_ascii_tables(content) == content

    def test_consistent_table_unchanged(self):
        content = (
            "```text\n"
            "+---+-------+\n"
            "| # | item  |\n"
            "+---+-------+\n"
            "| 1 | hello |\n"
            "+---+-------+\n"
            "```"
        )
        result = _normalize_ascii_tables(content)
        assert "+---+-------+" in result

    def test_inconsistent_column_widths_fixed(self):
        # Simulate LLM output where header has different widths than data
        content = (
            "```text\n"
            "+---+-------------------+-----+----------+----------+\n"
            "| # | item              | qty | unit_eur | line_eur |\n"
            "+---+-------------------+-----+----------+----------+\n"
            "| 1 | 2 TB SATA SSD     | 1   | 89       | 89       |\n"
            "| 2 | USB clone adapter | 1   | 16       | 16       |\n"
            "+---+-------------------+-----+----------+------+\n"
            "|   | TOTAL             |     |          | 105      |\n"
            "+---+-------------------+-----+----------+------+\n"
            "```"
        )
        result = _normalize_ascii_tables(content)
        # All separator lines should have same widths
        sep_lines = [l for l in result.split("\n") if l.startswith("+")]
        assert len(set(sep_lines)) == 1, f"Separators differ: {set(sep_lines)}"

    def test_preserves_non_table_content(self):
        content = (
            "# Title\n\nSome text.\n\n"
            "```text\n"
            "+---+------+\n"
            "| a | b    |\n"
            "+---+------+\n"
            "| 1 | test |\n"
            "+---+------+\n"
            "```\n\n"
            "## Notes\n\nMore text."
        )
        result = _normalize_ascii_tables(content)
        assert "# Title" in result
        assert "## Notes" in result
        assert "More text." in result


class TestAsciiTableParser:
    def test_parse_basic_table(self):
        text = (
            "# Bill\n\n```text\n"
            "+----------------+-----------------------------+\n"
            "| field          | value                       |\n"
            "+----------------+-----------------------------+\n"
            "| record_type    | bill                        |\n"
            "| purchased_on   | 2026-02-07                  |\n"
            "| total_eur      | 105                         |\n"
            "| counterparty   | Acme Corp                   |\n"
            "+----------------+-----------------------------+\n"
            "```\n"
        )
        record = _parse_ascii_table(text)
        assert record is not None
        assert record["record_type"] == "bill"
        assert record["purchased_on"] == "2026-02-07"
        assert record["total_eur"] == "105"
        assert record["counterparty"] == "Acme Corp"

    def test_no_table_returns_none(self):
        text = "Just plain text\nNo tables here."
        assert _parse_ascii_table(text) is None

    def test_too_few_fields_returns_none(self):
        text = (
            "+---+---+\n"
            "| a | b |\n"
            "+---+---+\n"
        )
        assert _parse_ascii_table(text) is None


class TestTextMatch:
    def test_all_keywords_present(self):
        assert _text_match("2 TB SATA SSD drive", "SATA SSD") is True

    def test_case_insensitive(self):
        assert _text_match("PLA Spool Mixed Colors", "pla spool mixed") is True

    def test_missing_keyword(self):
        assert _text_match("PLA Spool", "PLA spool mixed") is False

    def test_single_keyword(self):
        assert _text_match("relay modules and boards", "relay") is True

    def test_non_string_returns_false(self):
        assert _text_match(None, "test") is False
        assert _text_match("test", None) is False


class TestCheckIncompleteRequest:
    """Structural checks run without any LLM call — verify short-circuits."""

    def test_non_ok_outcome_skips(self):
        from agent.executor import _check_incomplete_request
        config = AgentConfig()
        tm = TaskManager()
        tm.defer_write("write", {"path": "a.md", "content": ""})
        result = {"outcome": "OUTCOME_NONE_CLARIFICATION", "message": "x"}
        # Should return None without calling LLM (outcome is not OK)
        assert _check_incomplete_request(config, "m", "t", result, tm, None) is None

    def test_no_pending_writes_skips(self):
        from agent.executor import _check_incomplete_request
        config = AgentConfig()
        tm = TaskManager()
        result = {"outcome": "OUTCOME_OK", "message": "x"}
        # Should return None without calling LLM (no pending writes)
        assert _check_incomplete_request(config, "m", "t", result, tm, None) is None

    def test_no_inbox_delete_skips(self):
        from agent.executor import _check_incomplete_request
        config = AgentConfig()
        tm = TaskManager()
        # Pending write without inbox delete — judge should NOT run
        tm.defer_write("write", {"path": "note.md", "content": ""})
        result = {"outcome": "OUTCOME_OK", "message": "done"}
        # Should return None without calling LLM (no inbox delete gate)
        assert _check_incomplete_request(config, "m", "t", result, tm, None) is None

    def test_empty_message_skips(self):
        from agent.executor import _check_incomplete_request
        config = AgentConfig()
        tm = TaskManager()
        tm.defer_write("delete", {"path": "00_inbox/msg.md"})
        tm.defer_write("write", {"path": "other.md", "content": ""})
        result = {"outcome": "OUTCOME_OK", "message": ""}
        # Should return None without calling LLM (empty completion message)
        assert _check_incomplete_request(config, "m", "t", result, tm, None) is None


class TestFixDateLookupClarification:
    def test_non_clarification_outcome_skips(self):
        from agent.executor import _fix_date_lookup_clarification
        config = AgentConfig()
        result = {"outcome": "OUTCOME_OK", "message": "x"}
        # Should return None without calling LLM (not a CLARIFICATION)
        assert _fix_date_lookup_clarification(config, "m", "t", result, None) is None

    def test_empty_message_skips(self):
        from agent.executor import _fix_date_lookup_clarification
        config = AgentConfig()
        result = {"outcome": "OUTCOME_NONE_CLARIFICATION", "message": ""}
        # Should return None without calling LLM (empty message)
        assert _fix_date_lookup_clarification(config, "m", "t", result, None) is None


class TestExpandAnswerToFullName:
    def _make_vm(self, files: dict[str, str]):
        """Mock vm where read(path) returns the mapped content."""
        vm = Mock()

        def read_side_effect(req):
            path = getattr(req, "path", None) or req  # flexible for test
            if hasattr(req, "path"):
                path = req.path
            content = files.get(path, "")
            resp = MagicMock()
            # MessageToDict returns a dict, we need {"content": content}
            return resp

        vm.read.side_effect = read_side_effect

        # Patch MessageToDict globally for this test
        return vm

    def test_empty_message_returns_none(self, mock_vm):
        from agent.executor import _expand_answer_to_full_name
        assert _expand_answer_to_full_name("", [], mock_vm) is None

    def test_no_files_returns_none(self, mock_vm):
        from agent.executor import _expand_answer_to_full_name
        assert _expand_answer_to_full_name("Lukas", [], mock_vm) is None

    def test_expands_first_word_to_full_name(self, monkeypatch):
        """Works regardless of which YAML field holds the long value."""
        from agent import executor as exec_mod
        vm = Mock()
        vm.read.side_effect = lambda req: Mock()
        # Field named full_name — common case
        monkeypatch.setattr(
            exec_mod, "MessageToDict",
            lambda obj: {"content": "---\nfull_name: Lukas Brenner\nbirthday: 1988-03-26\n---\n"},
        )
        result = exec_mod._expand_answer_to_full_name(
            "Lukas", ["10_entities/cast/lukas.md"], vm,
        )
        assert result == "Lukas Brenner"

    def test_expands_regardless_of_field_name(self, monkeypatch):
        """Schema-agnostic: works with any field name."""
        from agent import executor as exec_mod
        vm = Mock()
        vm.read.side_effect = lambda req: Mock()
        # Different schema: field named `display_name` instead of `full_name`
        monkeypatch.setattr(
            exec_mod, "MessageToDict",
            lambda obj: {"content": "---\ndisplay_name: Jane Smith\nrole: admin\n---\n"},
        )
        result = exec_mod._expand_answer_to_full_name(
            "Jane", ["someone.md"], vm,
        )
        assert result == "Jane Smith"

    def test_already_full_name_returns_none(self, monkeypatch):
        from agent import executor as exec_mod
        vm = Mock()
        vm.read.side_effect = lambda req: Mock()
        monkeypatch.setattr(
            exec_mod, "MessageToDict",
            lambda obj: {"content": "---\nfull_name: Lukas Brenner\n---\n"},
        )
        # Message is already the full name, no expansion needed
        result = exec_mod._expand_answer_to_full_name(
            "Lukas Brenner", ["file.md"], vm,
        )
        assert result is None

    def test_multi_line_answer_expands_each_line(self, monkeypatch):
        from agent import executor as exec_mod
        vm = Mock()
        # Track which file is requested and return different content per file
        path_contents = {
            "a.md": "---\nfull_name: Lukas Brenner\n---\n",
            "b.md": "---\nfull_name: Miles Novak\n---\n",
        }

        def fake_read(req):
            resp = Mock()
            resp._fake_path = req.path
            return resp
        vm.read.side_effect = fake_read
        monkeypatch.setattr(
            exec_mod, "MessageToDict",
            lambda obj: {"content": path_contents.get(obj._fake_path, "")},
        )

        result = exec_mod._expand_answer_to_full_name(
            "Lukas\nMiles", ["a.md", "b.md"], vm,
        )
        assert result == "Lukas Brenner\nMiles Novak"

    def test_ambiguous_first_name_does_not_expand(self, monkeypatch):
        """If two entities share a first name, do not auto-expand."""
        from agent import executor as exec_mod
        vm = Mock()
        path_contents = {
            "a.md": "---\nfull_name: John Smith\n---\n",
            "b.md": "---\nfull_name: John Doe\n---\n",
        }

        def fake_read(req):
            resp = Mock()
            resp._fake_path = req.path
            return resp
        vm.read.side_effect = fake_read
        monkeypatch.setattr(
            exec_mod, "MessageToDict",
            lambda obj: {"content": path_contents.get(obj._fake_path, "")},
        )

        result = exec_mod._expand_answer_to_full_name(
            "John", ["a.md", "b.md"], vm,
        )
        # Ambiguous — should NOT expand (too risky)
        assert result is None

    def test_numeric_answer_not_expanded(self, monkeypatch):
        """Dates, amounts, numbers must never be expanded."""
        from agent import executor as exec_mod
        vm = Mock()
        vm.read.side_effect = lambda req: Mock()
        monkeypatch.setattr(
            exec_mod, "MessageToDict",
            lambda obj: {"content": "---\nnote: 42 units of stock\n---\n"},
        )
        # Answer "42" must NOT be expanded to "42 units of stock"
        assert exec_mod._expand_answer_to_full_name("42", ["x.md"], vm) is None
        # Date answers must not be expanded
        assert exec_mod._expand_answer_to_full_name("2026-03-26", ["x.md"], vm) is None

    def test_lowercase_word_not_expanded(self, monkeypatch):
        """Non-proper-noun tokens should not be treated as identifiers."""
        from agent import executor as exec_mod
        vm = Mock()
        vm.read.side_effect = lambda req: Mock()
        monkeypatch.setattr(
            exec_mod, "MessageToDict",
            lambda obj: {"content": "---\nnote: total sum required\n---\n"},
        )
        # Answer "total" (lowercase) should NOT expand — not an identifier
        assert exec_mod._expand_answer_to_full_name("total", ["x.md"], vm) is None

    def test_already_multiword_not_expanded(self, monkeypatch):
        """Multi-word answers aren't single-name truncations."""
        from agent import executor as exec_mod
        vm = Mock()
        vm.read.side_effect = lambda req: Mock()
        monkeypatch.setattr(
            exec_mod, "MessageToDict",
            lambda obj: {"content": "---\nfull_name: Lukas Brenner Junior\n---\n"},
        )
        # "Lukas Brenner" already has a space — don't try to expand further
        assert exec_mod._expand_answer_to_full_name(
            "Lukas Brenner", ["x.md"], vm,
        ) is None

    def test_too_short_token_not_expanded(self, monkeypatch):
        """2-char answers are too ambiguous to safely expand."""
        from agent import executor as exec_mod
        vm = Mock()
        vm.read.side_effect = lambda req: Mock()
        monkeypatch.setattr(
            exec_mod, "MessageToDict",
            lambda obj: {"content": "---\ncode: AB Corp Ltd\n---\n"},
        )
        assert exec_mod._expand_answer_to_full_name("AB", ["x.md"], vm) is None


class TestDropFabricatedWrites:
    def test_no_failed_reads_is_noop(self):
        from agent.executor import _drop_fabricated_writes
        tm = TaskManager()
        pending = [{"op": "write", "args": {"path": "/a.md", "content": "x"}}]
        _drop_fabricated_writes(pending, tm)
        assert len(pending) == 1  # unchanged

    def test_drops_write_matching_failed_read(self):
        from agent.executor import _drop_fabricated_writes
        tm = TaskManager()
        tm.track_read_error("/bad.md")
        pending = [
            {"op": "write", "args": {"path": "/good.md", "content": "ok"}},
            {"op": "write", "args": {"path": "/bad.md", "content": "fabricated"}},
        ]
        _drop_fabricated_writes(pending, tm)
        assert len(pending) == 1
        assert pending[0]["args"]["path"] == "/good.md"

    def test_keeps_writes_to_unread_paths(self):
        """Writes to NEW paths (never read) are legitimate creations."""
        from agent.executor import _drop_fabricated_writes
        tm = TaskManager()
        tm.track_read_error("/missing.md")
        pending = [
            {"op": "write", "args": {"path": "/outbox/new.md", "content": "new"}},
        ]
        _drop_fabricated_writes(pending, tm)
        assert len(pending) == 1  # untouched — never attempted to read it

    def test_preserves_delete_ops(self):
        """Only write ops are subject to the drop rule."""
        from agent.executor import _drop_fabricated_writes
        tm = TaskManager()
        tm.track_read_error("/some.md")
        pending = [
            {"op": "delete", "args": {"path": "/some.md"}},  # delete is fine
            {"op": "write", "args": {"path": "/some.md", "content": "x"}},  # write is fabrication
        ]
        _drop_fabricated_writes(pending, tm)
        assert len(pending) == 1
        assert pending[0]["op"] == "delete"

    def test_path_leading_slash_normalization(self):
        """Handles paths with and without leading slash equivalently."""
        from agent.executor import _drop_fabricated_writes
        tm = TaskManager()
        tm.track_read_error("some/dir/file.md")  # no leading slash
        pending = [
            {"op": "write", "args": {"path": "/some/dir/file.md", "content": "x"}},
        ]
        _drop_fabricated_writes(pending, tm)
        assert len(pending) == 0  # should still match and drop


class TestDropDuplicateReplyWrites:
    def test_no_writes_is_noop(self):
        from agent.executor import _drop_duplicate_reply_writes
        pending = []
        _drop_duplicate_reply_writes(pending)
        assert pending == []

    def test_single_write_is_kept(self):
        from agent.executor import _drop_duplicate_reply_writes
        pending = [
            {"op": "write", "args": {
                "path": "/outbox/a.md",
                "content": "---\nto: alice@example.com\n---\nhi",
            }},
        ]
        _drop_duplicate_reply_writes(pending)
        assert len(pending) == 1

    def test_duplicate_to_field_keeps_last(self):
        """Two writes to same folder, identical `to:` → keep last."""
        from agent.executor import _drop_duplicate_reply_writes
        pending = [
            {"op": "write", "args": {
                "path": "/outbox/eml_draft.md",
                "content": "---\nto: alice@example.com\n---\ndraft",
            }},
            {"op": "write", "args": {
                "path": "/outbox/eml_final.md",
                "content": "---\nto: alice@example.com\n---\nfinal",
            }},
        ]
        _drop_duplicate_reply_writes(pending)
        assert len(pending) == 1
        assert "final" in pending[0]["args"]["content"]  # last one kept

    def test_different_recipients_both_kept(self):
        """Writes to different recipients are NOT duplicates."""
        from agent.executor import _drop_duplicate_reply_writes
        pending = [
            {"op": "write", "args": {
                "path": "/outbox/to_alice.md",
                "content": "---\nto: alice@example.com\n---\nhi",
            }},
            {"op": "write", "args": {
                "path": "/outbox/to_bob.md",
                "content": "---\nto: bob@example.com\n---\nhi",
            }},
        ]
        _drop_duplicate_reply_writes(pending)
        assert len(pending) == 2  # different recipients, both kept

    def test_different_folders_both_kept(self):
        """Same `to:` in different folders is NOT a duplicate (could be
        different workflow stages like drafts/ and outbox/)."""
        from agent.executor import _drop_duplicate_reply_writes
        pending = [
            {"op": "write", "args": {
                "path": "/drafts/a.md",
                "content": "---\nto: alice@example.com\n---\n",
            }},
            {"op": "write", "args": {
                "path": "/outbox/a.md",
                "content": "---\nto: alice@example.com\n---\n",
            }},
        ]
        _drop_duplicate_reply_writes(pending)
        assert len(pending) == 2

    def test_no_yaml_frontmatter_not_dedup(self):
        """Writes without YAML frontmatter aren't subject to YAML-based dedup."""
        from agent.executor import _drop_duplicate_reply_writes
        pending = [
            {"op": "write", "args": {"path": "/outbox/a.md", "content": "plain text"}},
            {"op": "write", "args": {"path": "/outbox/b.md", "content": "plain text"}},
        ]
        _drop_duplicate_reply_writes(pending)
        assert len(pending) == 2  # different paths + no YAML

    def test_same_path_collapses_to_last(self):
        """Two writes to the SAME path: last wins (overwrite semantics)."""
        from agent.executor import _drop_duplicate_reply_writes
        pending = [
            {"op": "write", "args": {"path": "/outbox/x.md", "content": "first"}},
            {"op": "write", "args": {"path": "/outbox/x.md", "content": "second"}},
        ]
        _drop_duplicate_reply_writes(pending)
        assert len(pending) == 1
        assert pending[0]["args"]["content"] == "second"

    def test_same_path_collapses_with_intervening_op(self):
        """Same-path collapse still fires even if a delete sits between."""
        from agent.executor import _drop_duplicate_reply_writes
        pending = [
            {"op": "write", "args": {"path": "/outbox/x.md", "content": "first"}},
            {"op": "delete", "args": {"path": "/inbox/y.md"}},
            {"op": "write", "args": {"path": "/outbox/x.md", "content": "second"}},
        ]
        _drop_duplicate_reply_writes(pending)
        assert len(pending) == 2
        # Delete preserved, only latest write remains
        assert pending[0]["op"] == "delete"
        assert pending[1]["args"]["content"] == "second"
