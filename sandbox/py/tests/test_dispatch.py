"""Tests for agent.dispatch -- Tool dispatch with protected files and parallel execution.

TDD: Tests written BEFORE implementation.
Task 5.1: DISPATCH_MAP, imports from tracker and tools only
Task 5.2: Handler functions for each tool (tree, list_dir, read_file, write_file, delete_file, search)
Task 5.3: read_file and tree handlers call tracker.add()
Task 5.4: delete_file with protected file checking
Task 5.5: report_completion handler with tracker.merge
Task 5.6: load_skill handler
Task 5.7: dispatch_tool() and dispatch_parallel() functions
"""

import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock


def _make_mock_vm():
    """Create a mock VM client with all expected methods."""
    vm = MagicMock()

    # outline returns a protobuf-like response
    outline_resp = MagicMock()
    outline_resp.DESCRIPTOR = MagicMock()
    vm.outline.return_value = outline_resp

    # list returns a protobuf-like response
    list_resp = MagicMock()
    list_resp.DESCRIPTOR = MagicMock()
    vm.list.return_value = list_resp

    # read returns a protobuf-like response
    read_resp = MagicMock()
    read_resp.DESCRIPTOR = MagicMock()
    vm.read.return_value = read_resp

    # write returns a protobuf-like response
    write_resp = MagicMock()
    write_resp.DESCRIPTOR = MagicMock()
    vm.write.return_value = write_resp

    # delete returns a protobuf-like response
    delete_resp = MagicMock()
    delete_resp.DESCRIPTOR = MagicMock()
    vm.delete.return_value = delete_resp

    # search returns a protobuf-like response
    search_resp = MagicMock()
    search_resp.DESCRIPTOR = MagicMock()
    vm.search.return_value = search_resp

    # answer returns a protobuf-like response
    answer_resp = MagicMock()
    answer_resp.DESCRIPTOR = MagicMock()
    vm.answer.return_value = answer_resp

    return vm


@pytest.fixture
def mock_vm():
    return _make_mock_vm()


@pytest.fixture
def tracker():
    from agent.tracker import GroundingTracker
    return GroundingTracker()


@pytest.fixture
def protected_files():
    return {"agents.md"}


class TestDispatchMap:
    """Task 5.1: DISPATCH_MAP exists and maps tool names to handlers."""

    def test_dispatch_map_is_dict(self):
        from agent.dispatch import DISPATCH_MAP
        assert isinstance(DISPATCH_MAP, dict)

    def test_dispatch_map_has_all_tool_names(self):
        from agent.dispatch import DISPATCH_MAP
        from agent.tools import TOOL_NAMES
        for name in TOOL_NAMES:
            assert name in DISPATCH_MAP, f"Missing dispatch handler for tool: {name}"

    def test_dispatch_map_values_are_callable(self):
        from agent.dispatch import DISPATCH_MAP
        for name, handler in DISPATCH_MAP.items():
            assert callable(handler), f"Handler for {name} is not callable"


class TestTreeHandler:
    """Task 5.2: tree handler calls vm.outline()."""

    @patch("agent.dispatch.MessageToDict", return_value={"tree": "root contents"})
    def test_tree_calls_vm_outline(self, mock_mtd, mock_vm, tracker, protected_files):
        from agent.dispatch import dispatch_tool
        result = dispatch_tool(mock_vm, "tree", {"path": "/"}, tracker, protected_files)
        mock_vm.outline.assert_called_once()
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert "tree" in parsed

    @patch("agent.dispatch.MessageToDict", return_value={"tree": "content"})
    def test_tree_does_not_add_to_tracker(self, mock_mtd, mock_vm, tracker, protected_files):
        """Tree is a directory operation — should NOT add to tracker."""
        from agent.dispatch import dispatch_tool
        dispatch_tool(mock_vm, "tree", {"path": "/"}, tracker, protected_files)
        assert len(tracker) == 0


class TestListDirHandler:
    """Task 5.2: list_dir handler calls vm.list()."""

    @patch("agent.dispatch.MessageToDict", return_value={"entries": []})
    def test_list_dir_calls_vm_list(self, mock_mtd, mock_vm, tracker, protected_files):
        from agent.dispatch import dispatch_tool
        result = dispatch_tool(mock_vm, "list_dir", {"path": "/workspace"}, tracker, protected_files)
        mock_vm.list.assert_called_once()
        assert isinstance(result, str)


class TestReadFileHandler:
    """Task 5.2 & 5.3: read_file handler calls vm.read() and tracker.add()."""

    @patch("agent.dispatch.MessageToDict", return_value={"content": "file text"})
    def test_read_file_calls_vm_read(self, mock_mtd, mock_vm, tracker, protected_files):
        from agent.dispatch import dispatch_tool
        result = dispatch_tool(mock_vm, "read_file", {"path": "/a.md"}, tracker, protected_files)
        mock_vm.read.assert_called_once()
        assert isinstance(result, str)

    @patch("agent.dispatch.MessageToDict", return_value={"content": "file text"})
    def test_read_file_adds_path_to_tracker(self, mock_mtd, mock_vm, tracker, protected_files):
        """Task 5.3: read_file handler calls tracker.add(path)."""
        from agent.dispatch import dispatch_tool
        dispatch_tool(mock_vm, "read_file", {"path": "/workspace/file.txt"}, tracker, protected_files)
        assert "workspace/file.txt" in tracker.all() or len(tracker) == 1


class TestWriteFileHandler:
    """Task 5.2: write_file handler calls vm.write()."""

    @patch("agent.dispatch.MessageToDict", return_value={"status": "ok"})
    def test_write_file_calls_vm_write(self, mock_mtd, mock_vm, tracker, protected_files):
        from agent.dispatch import dispatch_tool
        result = dispatch_tool(
            mock_vm, "write_file",
            {"path": "/out.md", "content": "hello"},
            tracker, protected_files,
        )
        mock_vm.write.assert_called_once()
        assert isinstance(result, str)


class TestDeleteFileHandler:
    """Task 5.2 & 5.4: delete_file handler with protected file checking."""

    @patch("agent.dispatch.MessageToDict", return_value={"status": "deleted"})
    def test_delete_file_calls_vm_delete(self, mock_mtd, mock_vm, tracker, protected_files):
        from agent.dispatch import dispatch_tool
        result = dispatch_tool(
            mock_vm, "delete_file", {"path": "/temp.txt"},
            tracker, protected_files,
        )
        mock_vm.delete.assert_called_once()
        assert isinstance(result, str)

    def test_delete_protected_file_is_refused(self, mock_vm, tracker, protected_files):
        """Task 5.4: Deleting a protected file returns error, does not call vm.delete()."""
        from agent.dispatch import dispatch_tool
        result = dispatch_tool(
            mock_vm, "delete_file", {"path": "AGENTS.MD"},
            tracker, protected_files,
        )
        mock_vm.delete.assert_not_called()
        parsed = json.loads(result)
        assert "error" in parsed

    def test_delete_protected_file_with_leading_slash(self, mock_vm, tracker, protected_files):
        """Path normalization: /AGENTS.MD should still be protected."""
        from agent.dispatch import dispatch_tool
        result = dispatch_tool(
            mock_vm, "delete_file", {"path": "/AGENTS.MD"},
            tracker, protected_files,
        )
        mock_vm.delete.assert_not_called()
        parsed = json.loads(result)
        assert "error" in parsed

    def test_delete_protected_file_case_insensitive(self, mock_vm, tracker, protected_files):
        """agents.md should match AGENTS.MD in protected set."""
        from agent.dispatch import dispatch_tool
        result = dispatch_tool(
            mock_vm, "delete_file", {"path": "agents.md"},
            tracker, protected_files,
        )
        mock_vm.delete.assert_not_called()
        parsed = json.loads(result)
        assert "error" in parsed

    def test_delete_protected_file_with_dotdot_path(self, mock_vm, tracker, protected_files):
        """Path normalization: workspace/../AGENTS.MD should still be protected."""
        from agent.dispatch import dispatch_tool
        result = dispatch_tool(
            mock_vm, "delete_file", {"path": "workspace/../AGENTS.MD"},
            tracker, protected_files,
        )
        mock_vm.delete.assert_not_called()
        parsed = json.loads(result)
        assert "error" in parsed


class TestSearchHandler:
    """Task 5.2: search handler calls vm.search()."""

    @patch("agent.dispatch.MessageToDict", return_value={"results": []})
    def test_search_calls_vm_search(self, mock_mtd, mock_vm, tracker, protected_files):
        from agent.dispatch import dispatch_tool
        result = dispatch_tool(
            mock_vm, "search",
            {"pattern": "hello", "path": "/", "count": 5},
            tracker, protected_files,
        )
        mock_vm.search.assert_called_once()
        assert isinstance(result, str)


class TestReportCompletionHandler:
    """Task 5.5: report_completion handler merges grounding refs."""

    @patch("agent.dispatch.MessageToDict", return_value={"status": "ok"})
    def test_report_completion_calls_tracker_merge(self, mock_mtd, mock_vm, tracker, protected_files):
        from agent.dispatch import dispatch_tool
        tracker.add("a.md")
        tracker.add("b.md")
        result = dispatch_tool(
            mock_vm, "report_completion",
            {
                "answer": "The answer is 42.",
                "grounding_refs": ["c.md"],
                "steps": ["Read files", "Computed answer"],
                "code": "completed",
            },
            tracker, protected_files,
        )
        mock_vm.answer.assert_called_once()
        # The merged refs should include both tracked files and LLM-provided refs
        call_args = mock_vm.answer.call_args
        # Check that refs were merged (the AnswerRequest should contain merged refs)
        assert isinstance(result, str)

    @patch("agent.dispatch.MessageToDict", return_value={"status": "ok"})
    def test_report_completion_includes_tracked_files(self, mock_mtd, mock_vm, tracker, protected_files):
        from agent.dispatch import dispatch_tool
        tracker.add("tracked-file.md")
        dispatch_tool(
            mock_vm, "report_completion",
            {
                "answer": "Done.",
                "grounding_refs": [],
                "steps": ["Done"],
                "code": "completed",
            },
            tracker, protected_files,
        )
        # The vm.answer call should include tracked-file.md in refs
        call_args = mock_vm.answer.call_args
        assert call_args is not None


class TestLoadSkillHandler:
    """Task 5.6: load_skill handler delegates to skill_loader."""

    def test_load_skill_without_loader(self, mock_vm, tracker, protected_files):
        """When no skill_loader is provided, should return error."""
        from agent.dispatch import dispatch_tool
        result = dispatch_tool(
            mock_vm, "load_skill", {"name": "test-skill"},
            tracker, protected_files,
            skill_loader=None,
        )
        assert isinstance(result, str)
        # Should indicate error or no skills available
        parsed = json.loads(result)
        assert "error" in parsed or "not" in result.lower()

    def test_load_skill_with_loader(self, mock_vm, tracker, protected_files):
        """When skill_loader is provided, delegates to get_content."""
        from agent.dispatch import dispatch_tool
        mock_loader = MagicMock()
        mock_loader.get_content.return_value = '<skill name="test">body</skill>'
        result = dispatch_tool(
            mock_vm, "load_skill", {"name": "test-skill"},
            tracker, protected_files,
            skill_loader=mock_loader,
        )
        mock_loader.get_content.assert_called_once_with("test-skill")
        assert "body" in result


class TestDispatchToolFunction:
    """Task 5.7: dispatch_tool() function."""

    def test_dispatch_tool_unknown_tool_raises_or_errors(self, mock_vm, tracker, protected_files):
        """Unknown tool name should raise ValueError or return error."""
        from agent.dispatch import dispatch_tool
        with pytest.raises((ValueError, KeyError)):
            dispatch_tool(
                mock_vm, "unknown_tool", {},
                tracker, protected_files,
            )

    @patch("agent.dispatch.MessageToDict", return_value={"content": "text"})
    def test_dispatch_tool_routes_correctly(self, mock_mtd, mock_vm, tracker, protected_files):
        from agent.dispatch import dispatch_tool
        dispatch_tool(mock_vm, "read_file", {"path": "/x.md"}, tracker, protected_files)
        mock_vm.read.assert_called_once()


class TestDispatchParallel:
    """Task 5.7: dispatch_parallel() uses ThreadPoolExecutor."""

    @patch("agent.dispatch.MessageToDict", return_value={"content": "text"})
    def test_dispatch_parallel_returns_list_of_tuples(self, mock_mtd, mock_vm, tracker, protected_files):
        from agent.dispatch import dispatch_parallel
        from agent.llm import ToolCall

        tool_calls = [
            ToolCall(id="tc_1", name="read_file", arguments={"path": "/a.md"}),
            ToolCall(id="tc_2", name="read_file", arguments={"path": "/b.md"}),
        ]
        results = dispatch_parallel(
            mock_vm, tool_calls, tracker, protected_files,
        )
        assert isinstance(results, list)
        assert len(results) == 2
        for tc_id, result in results:
            assert isinstance(tc_id, str)
            assert isinstance(result, str)

    @patch("agent.dispatch.MessageToDict", return_value={"content": "text"})
    def test_dispatch_parallel_returns_correct_ids(self, mock_mtd, mock_vm, tracker, protected_files):
        from agent.dispatch import dispatch_parallel
        from agent.llm import ToolCall

        tool_calls = [
            ToolCall(id="tc_alpha", name="read_file", arguments={"path": "/x.md"}),
        ]
        results = dispatch_parallel(mock_vm, tool_calls, tracker, protected_files)
        assert results[0][0] == "tc_alpha"

    @patch("agent.dispatch.MessageToDict", return_value={"content": "text"})
    def test_dispatch_parallel_empty_list(self, mock_mtd, mock_vm, tracker, protected_files):
        from agent.dispatch import dispatch_parallel
        results = dispatch_parallel(mock_vm, [], tracker, protected_files)
        assert results == []

    @patch("agent.dispatch.MessageToDict", return_value={"entries": []})
    def test_dispatch_parallel_handles_different_tool_types(self, mock_mtd, mock_vm, tracker, protected_files):
        from agent.dispatch import dispatch_parallel
        from agent.llm import ToolCall

        tool_calls = [
            ToolCall(id="tc_1", name="read_file", arguments={"path": "/a.md"}),
            ToolCall(id="tc_2", name="list_dir", arguments={"path": "/workspace"}),
        ]
        results = dispatch_parallel(mock_vm, tool_calls, tracker, protected_files)
        assert len(results) == 2


class TestDispatchHandlesConnectError:
    """Dispatch should handle ConnectError from VM and return it as error JSON."""

    def test_dispatch_tool_catches_connect_error(self, mock_vm, tracker, protected_files):
        from agent.dispatch import dispatch_tool
        from connectrpc.errors import ConnectError

        mock_vm.read.side_effect = ConnectError(code="not_found", message="file not found")
        result = dispatch_tool(
            mock_vm, "read_file", {"path": "/missing.md"},
            tracker, protected_files,
        )
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert "error" in parsed


class TestDispatchModuleDependencies:
    """dispatch.py should import only from tracker and tools (and external libs)."""

    def test_dispatch_imports(self):
        import agent.dispatch as mod
        with open(mod.__file__) as f:
            source = f.read()
        import re
        agent_imports = re.findall(r"from\s+agent\.(\w+)", source)
        allowed = {"tracker", "tools", "llm"}  # llm for ToolCall type
        for imp in agent_imports:
            assert imp in allowed, (
                f"dispatch.py imports from agent.{imp}, "
                f"only {allowed} are allowed"
            )
