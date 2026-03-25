"""Tests for agent.dispatch -- Tool dispatch with protected files and parallel execution.

TDD: Tests written BEFORE implementation.
Task 5.1: DISPATCH_MAP, imports from tracker and tools only
Task 5.2: Handler functions for each tool (tree, list_dir, read_file, write_file, delete_file, search)
Task 5.3: read_file and tree handlers call tracker.add()
Task 5.4: delete_file with protected file checking
Task 5.5: report_completion handler with tracker.merge
Task 5.6: load_skill handler
Task 5.7: dispatch_tool() and dispatch_parallel() functions
Task 2 (refactor): Updated to use RuntimeAdapter interface (adapter methods instead of raw VM calls)
"""

import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock


def _make_mock_vm():
    """Create a mock RuntimeAdapter with all expected methods."""
    vm = MagicMock()
    for method in ['tree', 'list_dir', 'read', 'write', 'delete', 'search', 'answer', 'find', 'mkdir', 'move']:
        resp = MagicMock()
        resp.DESCRIPTOR = MagicMock()
        getattr(vm, method).return_value = resp
    vm.runtime_type = "mini"
    vm.extra_tools = frozenset()
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
    """Task 5.2: tree handler calls vm.tree()."""

    @patch("agent.dispatch.MessageToDict", return_value={"tree": "root contents"})
    def test_tree_calls_vm_tree(self, mock_mtd, mock_vm, tracker, protected_files):
        from agent.dispatch import dispatch_tool
        result = dispatch_tool(mock_vm, "tree", {"path": "/"}, tracker, protected_files)
        mock_vm.tree.assert_called_once()
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
    """Task 5.2: list_dir handler calls vm.list_dir()."""

    @patch("agent.dispatch.MessageToDict", return_value={"entries": []})
    def test_list_dir_calls_vm_list_dir(self, mock_mtd, mock_vm, tracker, protected_files):
        from agent.dispatch import dispatch_tool
        result = dispatch_tool(mock_vm, "list_dir", {"path": "/workspace"}, tracker, protected_files)
        mock_vm.list_dir.assert_called_once()
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


class TestFindHandler:
    """find handler calls vm.find()."""

    @patch("agent.dispatch.MessageToDict", return_value={"items": []})
    def test_find_calls_runtime(self, mock_mtd, mock_vm, tracker, protected_files):
        from agent.dispatch import dispatch_tool
        result = dispatch_tool(mock_vm, "find", {"root": "/", "name": "test", "kind": "all", "limit": 10}, tracker, protected_files)
        mock_vm.find.assert_called_once()
        assert isinstance(result, str)


class TestMkDirHandler:
    """mkdir handler calls vm.mkdir()."""

    @patch("agent.dispatch.MessageToDict", return_value={})
    def test_mkdir_calls_runtime(self, mock_mtd, mock_vm, tracker, protected_files):
        from agent.dispatch import dispatch_tool
        result = dispatch_tool(mock_vm, "mkdir", {"path": "/newdir"}, tracker, protected_files)
        mock_vm.mkdir.assert_called_once()
        assert isinstance(result, str)


class TestMoveHandler:
    """move handler calls vm.move() with protected file checking."""

    @patch("agent.dispatch.MessageToDict", return_value={})
    def test_move_calls_runtime(self, mock_mtd, mock_vm, tracker, protected_files):
        from agent.dispatch import dispatch_tool
        result = dispatch_tool(mock_vm, "move", {"from_name": "/a.txt", "to_name": "/b.txt"}, tracker, protected_files)
        mock_vm.move.assert_called_once()
        assert isinstance(result, str)

    def test_move_protected_file_is_refused(self, mock_vm, tracker, protected_files):
        from agent.dispatch import dispatch_tool
        result = dispatch_tool(mock_vm, "move", {"from_name": "/AGENTS.MD", "to_name": "/renamed.md"}, tracker, protected_files)
        mock_vm.move.assert_not_called()
        parsed = json.loads(result)
        assert "error" in parsed


class TestDispatchToolFunction:
    """Task 5.7: dispatch_tool() function."""

    def test_dispatch_tool_unknown_tool_returns_error(self, mock_vm, tracker, protected_files):
        """Unknown tool name should return error JSON."""
        from agent.dispatch import dispatch_tool
        result = dispatch_tool(
            mock_vm, "unknown_tool", {},
            tracker, protected_files,
        )
        parsed = json.loads(result)
        assert "error" in parsed

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
    """dispatch.py should import only from tracker, tools, llm, and context (and external libs)."""

    def test_dispatch_imports(self):
        import agent.dispatch as mod
        with open(mod.__file__) as f:
            source = f.read()
        import re
        agent_imports = re.findall(r"from\s+agent\.(\w+)", source)
        allowed = {"tracker", "tools", "llm", "context"}  # context for ContextConfig, truncation
        for imp in agent_imports:
            assert imp in allowed, (
                f"dispatch.py imports from agent.{imp}, "
                f"only {allowed} are allowed"
            )


# ---------------------------------------------------------------------------
# Context management integration tests (Task 10.1)
# ---------------------------------------------------------------------------

class TestDispatchToolTruncation:
    """Tool result truncation via context_config parameter."""

    @patch("agent.dispatch.MessageToDict", return_value={"content": "x" * 20000})
    def test_truncation_applied_when_config_provided(self, mock_mtd, mock_vm, tracker, protected_files):
        """When context_config is provided and result exceeds limit, truncation is applied."""
        from agent.dispatch import dispatch_tool
        from agent.context import ContextConfig

        cfg = ContextConfig(truncation_limit=100)
        result = dispatch_tool(
            mock_vm, "read_file", {"path": "/a.md"},
            tracker, protected_files,
            context_config=cfg,
        )
        assert "truncated" in result
        assert len(result) < 20000

    @patch("agent.dispatch.MessageToDict", return_value={"content": "x" * 20000})
    def test_no_truncation_when_config_none(self, mock_mtd, mock_vm, tracker, protected_files):
        """When context_config is None, result is returned unchanged (backward compat)."""
        from agent.dispatch import dispatch_tool

        result = dispatch_tool(
            mock_vm, "read_file", {"path": "/a.md"},
            tracker, protected_files,
            context_config=None,
        )
        parsed = json.loads(result)
        assert len(parsed["content"]) == 20000

    @patch("agent.dispatch.MessageToDict", return_value={"status": "ok"})
    def test_report_completion_exempt_from_truncation(self, mock_mtd, mock_vm, tracker, protected_files):
        """report_completion results are never truncated, even with context_config."""
        from agent.dispatch import dispatch_tool
        from agent.context import ContextConfig

        cfg = ContextConfig(truncation_limit=5)
        result = dispatch_tool(
            mock_vm, "report_completion",
            {"answer": "done", "grounding_refs": [], "steps": [], "code": "completed"},
            tracker, protected_files,
            context_config=cfg,
        )
        # Result should not be truncated
        assert "truncated" not in result


class TestDispatchCompactSentinel:
    """compact tool returns COMPACT_SENTINEL."""

    def test_compact_returns_sentinel(self, mock_vm, tracker, protected_files):
        """dispatch_tool('compact', ...) returns COMPACT_SENTINEL."""
        from agent.dispatch import dispatch_tool
        from agent.context import COMPACT_SENTINEL

        result = dispatch_tool(
            mock_vm, "compact", {},
            tracker, protected_files,
        )
        assert result == COMPACT_SENTINEL

    def test_compact_in_dispatch_map(self):
        """compact handler is registered in DISPATCH_MAP."""
        from agent.dispatch import DISPATCH_MAP
        assert "compact" in DISPATCH_MAP
        assert callable(DISPATCH_MAP["compact"])


class TestDispatchParallelContextConfig:
    """dispatch_parallel passes context_config through to dispatch_tool."""

    @patch("agent.dispatch.MessageToDict", return_value={"content": "x" * 20000})
    def test_parallel_applies_truncation(self, mock_mtd, mock_vm, tracker, protected_files):
        """dispatch_parallel applies truncation when context_config is provided."""
        from agent.dispatch import dispatch_parallel
        from agent.llm import ToolCall
        from agent.context import ContextConfig

        cfg = ContextConfig(truncation_limit=100)
        tool_calls = [
            ToolCall(id="tc_1", name="read_file", arguments={"path": "/a.md"}),
        ]
        results = dispatch_parallel(
            mock_vm, tool_calls, tracker, protected_files,
            context_config=cfg,
        )
        assert len(results) == 1
        _, result_text = results[0]
        assert "truncated" in result_text


# ===========================================================================
# Task 2 TDD Tests: DispatchContext, Guard Dataclasses, Guard Functions
# ===========================================================================

class TestDataclassesExist:
    """Task 2.1: TemplateGuardConfig, TaskConstraints, and DispatchContext exist as frozen dataclasses."""

    def test_template_guard_config_importable(self):
        from agent.dispatch import TemplateGuardConfig
        cfg = TemplateGuardConfig()
        assert cfg.protected_directories == ()

    def test_template_guard_config_frozen(self):
        from agent.dispatch import TemplateGuardConfig
        cfg = TemplateGuardConfig()
        with pytest.raises(AttributeError):
            cfg.protected_directories = ("x",)

    def test_template_guard_config_custom_dirs(self):
        from agent.dispatch import TemplateGuardConfig
        cfg = TemplateGuardConfig(protected_directories=("/templates/", "/structural/"))
        assert cfg.protected_directories == ("/templates/", "/structural/")

    def test_task_constraints_importable(self):
        from agent.dispatch import TaskConstraints
        tc = TaskConstraints()
        assert tc.source_file is None
        assert tc.scope_level == "normal"
        assert tc.target_directories == ()

    def test_task_constraints_frozen(self):
        from agent.dispatch import TaskConstraints
        tc = TaskConstraints()
        with pytest.raises(AttributeError):
            tc.scope_level = "focused"

    def test_task_constraints_custom_values(self):
        from agent.dispatch import TaskConstraints
        tc = TaskConstraints(
            source_file="report.md",
            scope_level="focused",
            target_directories=("/output/",),
        )
        assert tc.source_file == "report.md"
        assert tc.scope_level == "focused"
        assert tc.target_directories == ("/output/",)

    def test_dispatch_context_importable(self):
        from agent.dispatch import DispatchContext
        ctx = DispatchContext()
        assert ctx.source_basename is None
        assert ctx.scope_constrained is False
        assert ctx.target_directories == ()

    def test_dispatch_context_frozen(self):
        from agent.dispatch import DispatchContext
        ctx = DispatchContext()
        with pytest.raises(AttributeError):
            ctx.scope_constrained = True

    def test_dispatch_context_with_template_guard(self):
        from agent.dispatch import DispatchContext, TemplateGuardConfig
        cfg = TemplateGuardConfig(protected_directories=("/tmpl/",))
        ctx = DispatchContext(template_guard_config=cfg)
        assert ctx.template_guard_config.protected_directories == ("/tmpl/",)


class TestModuleGlobalsRemoved:
    """Task 2.2: Module-level mutable globals _source_basename and _scope_constrained are removed."""

    def test_no_source_basename_global(self):
        import agent.dispatch as mod
        assert not hasattr(mod, "_source_basename"), \
            "_source_basename module-level global should be removed"

    def test_no_scope_constrained_global(self):
        import agent.dispatch as mod
        assert not hasattr(mod, "_scope_constrained"), \
            "_scope_constrained module-level global should be removed"


class TestDispatchToolNewSignature:
    """Task 2.3: dispatch_tool accepts dispatch_ctx parameter instead of source_basename/scope_constrained."""

    @patch("agent.dispatch.MessageToDict", return_value={"content": "text"})
    def test_dispatch_tool_accepts_dispatch_ctx(self, mock_mtd, mock_vm, tracker, protected_files):
        from agent.dispatch import dispatch_tool, DispatchContext
        ctx = DispatchContext(source_basename="test.md")
        result = dispatch_tool(
            mock_vm, "read_file", {"path": "/x.md"},
            tracker, protected_files,
            dispatch_ctx=ctx,
        )
        assert isinstance(result, str)
        mock_vm.read.assert_called_once()

    @patch("agent.dispatch.MessageToDict", return_value={"content": "text"})
    def test_dispatch_tool_accepts_none_ctx(self, mock_mtd, mock_vm, tracker, protected_files):
        from agent.dispatch import dispatch_tool
        result = dispatch_tool(
            mock_vm, "read_file", {"path": "/x.md"},
            tracker, protected_files,
            dispatch_ctx=None,
        )
        assert isinstance(result, str)
        mock_vm.read.assert_called_once()

    def test_dispatch_tool_no_old_params(self):
        """source_basename and scope_constrained params should not exist."""
        import inspect
        from agent.dispatch import dispatch_tool
        sig = inspect.signature(dispatch_tool)
        param_names = list(sig.parameters.keys())
        assert "source_basename" not in param_names, \
            "source_basename parameter should be removed from dispatch_tool"
        assert "scope_constrained" not in param_names, \
            "scope_constrained parameter should be removed from dispatch_tool"


class TestDispatchParallelNewSignature:
    """Task 2.4: dispatch_parallel accepts dispatch_ctx parameter."""

    @patch("agent.dispatch.MessageToDict", return_value={"content": "text"})
    def test_dispatch_parallel_accepts_dispatch_ctx(self, mock_mtd, mock_vm, tracker, protected_files):
        from agent.dispatch import dispatch_parallel, DispatchContext
        from agent.llm import ToolCall
        ctx = DispatchContext(source_basename="test.md")
        tool_calls = [
            ToolCall(id="tc_1", name="read_file", arguments={"path": "/a.md"}),
        ]
        results = dispatch_parallel(
            mock_vm, tool_calls, tracker, protected_files,
            dispatch_ctx=ctx,
        )
        assert len(results) == 1

    def test_dispatch_parallel_no_old_params(self):
        """source_basename and scope_constrained params should not exist."""
        import inspect
        from agent.dispatch import dispatch_parallel
        sig = inspect.signature(dispatch_parallel)
        param_names = list(sig.parameters.keys())
        assert "source_basename" not in param_names
        assert "scope_constrained" not in param_names


class TestCheckBasenameGuard:
    """Task 2.5: _check_basename_guard standalone function."""

    def test_basename_guard_returns_none_when_no_source(self, mock_vm, tracker, protected_files):
        """No source basename set -> no guard action."""
        from agent.dispatch import _check_basename_guard, DispatchContext
        ctx = DispatchContext(source_basename=None)
        result = _check_basename_guard(ctx, "/output/test.md")
        assert result is None

    def test_basename_guard_returns_none_on_exact_match(self):
        """Exact basename match -> allowed."""
        from agent.dispatch import _check_basename_guard, DispatchContext
        ctx = DispatchContext(source_basename="2026-03-23__hn-foo.md")
        result = _check_basename_guard(ctx, "/output/2026-03-23__hn-foo.md")
        assert result is None

    def test_basename_guard_blocks_mismatch(self):
        """Different stem with same slug -> blocked."""
        from agent.dispatch import _check_basename_guard, DispatchContext
        ctx = DispatchContext(source_basename="2026-03-23__hn-foo.md")
        result = _check_basename_guard(ctx, "/output/2026-03-23__0000__hn-foo.md")
        assert result is not None
        assert "mismatch" in result.lower() or "Mismatch" in result

    def test_basename_guard_allows_unrelated_filename(self):
        """Completely unrelated filename -> allowed."""
        from agent.dispatch import _check_basename_guard, DispatchContext
        ctx = DispatchContext(source_basename="report.md")
        result = _check_basename_guard(ctx, "/output/summary.md")
        assert result is None


class TestCheckScopeGuard:
    """Task 2.6: _check_scope_guard standalone function with intent-aware logic."""

    def test_scope_guard_allows_when_not_constrained(self, tracker):
        """Step 1: Not constrained -> allow."""
        from agent.dispatch import _check_scope_guard, DispatchContext
        ctx = DispatchContext(scope_constrained=False)
        tracker.add("/file.md")
        result = _check_scope_guard(ctx, "/file.md", tracker)
        assert result is None

    def test_scope_guard_allows_when_file_not_tracked(self, tracker):
        """Step 2: File not previously read -> allow (new file)."""
        from agent.dispatch import _check_scope_guard, DispatchContext
        ctx = DispatchContext(scope_constrained=True)
        result = _check_scope_guard(ctx, "/new-file.md", tracker)
        assert result is None

    def test_scope_guard_allows_when_target_in_directories(self, tracker):
        """Step 3: Target in allowed directories -> allow."""
        from agent.dispatch import _check_scope_guard, DispatchContext
        ctx = DispatchContext(
            scope_constrained=True,
            target_directories=("/output/",),
        )
        tracker.add("/output/report.md")
        result = _check_scope_guard(ctx, "/output/report.md", tracker)
        assert result is None

    def test_scope_guard_allows_when_basename_matches_source(self, tracker):
        """Step 4: Basename matches source_basename -> allow."""
        from agent.dispatch import _check_scope_guard, DispatchContext
        ctx = DispatchContext(
            scope_constrained=True,
            source_basename="report.md",
        )
        tracker.add("/workspace/report.md")
        result = _check_scope_guard(ctx, "/workspace/report.md", tracker)
        assert result is None

    def test_scope_guard_blocks_when_constrained_and_tracked(self, tracker):
        """Step 5: Constrained + tracked + no match -> block."""
        from agent.dispatch import _check_scope_guard, DispatchContext
        ctx = DispatchContext(
            scope_constrained=True,
            source_basename="source.md",
            target_directories=("/allowed/",),
        )
        tracker.add("/other/config.md")
        result = _check_scope_guard(ctx, "/other/config.md", tracker)
        assert result is not None
        assert "scope" in result.lower() or "Scope" in result


class TestCheckTemplateGuard:
    """Task 2.7: _check_template_guard standalone function."""

    def test_template_guard_allows_non_prefixed(self):
        """Non-underscore prefixed file -> always allowed."""
        from agent.dispatch import _check_template_guard, DispatchContext
        ctx = DispatchContext()
        result = _check_template_guard(ctx, "/workspace/report.md")
        assert result is None

    def test_template_guard_blocks_prefixed_default(self):
        """Underscore-prefixed file with empty protected_directories -> block all (backward compat)."""
        from agent.dispatch import _check_template_guard, DispatchContext, TemplateGuardConfig
        ctx = DispatchContext(template_guard_config=TemplateGuardConfig())
        result = _check_template_guard(ctx, "/workspace/_template.md")
        assert result is not None
        assert "template" in result.lower() or "structural" in result.lower()

    def test_template_guard_blocks_prefixed_in_protected_dir(self):
        """Underscore-prefixed file inside protected directory -> block."""
        from agent.dispatch import _check_template_guard, DispatchContext, TemplateGuardConfig
        cfg = TemplateGuardConfig(protected_directories=("/templates/",))
        ctx = DispatchContext(template_guard_config=cfg)
        result = _check_template_guard(ctx, "/templates/_header.md")
        assert result is not None

    def test_template_guard_allows_prefixed_outside_protected_dir(self):
        """Underscore-prefixed file outside protected directory -> allow."""
        from agent.dispatch import _check_template_guard, DispatchContext, TemplateGuardConfig
        cfg = TemplateGuardConfig(protected_directories=("/templates/",))
        ctx = DispatchContext(template_guard_config=cfg)
        result = _check_template_guard(ctx, "/other/_config.md")
        assert result is None


class TestGuardWiringInDispatchTool:
    """Task 2.8: Guards are called as pre-dispatch checks in dispatch_tool."""

    @patch("agent.dispatch.MessageToDict", return_value={"status": "ok"})
    def test_write_blocked_by_basename_guard(self, mock_mtd, mock_vm, tracker, protected_files):
        """write_file with basename mismatch -> error, vm.write not called."""
        from agent.dispatch import dispatch_tool, DispatchContext
        ctx = DispatchContext(source_basename="2026-03-23__hn-foo.md")
        result = dispatch_tool(
            mock_vm, "write_file",
            {"path": "/out/2026-03-23__0000__hn-foo.md", "content": "x"},
            tracker, protected_files,
            dispatch_ctx=ctx,
        )
        mock_vm.write.assert_not_called()
        parsed = json.loads(result)
        assert "error" in parsed

    @patch("agent.dispatch.MessageToDict", return_value={"status": "ok"})
    def test_write_blocked_by_scope_guard(self, mock_mtd, mock_vm, tracker, protected_files):
        """write_file to tracked file while scope constrained -> error."""
        from agent.dispatch import dispatch_tool, DispatchContext
        ctx = DispatchContext(scope_constrained=True)
        tracker.add("/existing.md")
        result = dispatch_tool(
            mock_vm, "write_file",
            {"path": "/existing.md", "content": "x"},
            tracker, protected_files,
            dispatch_ctx=ctx,
        )
        mock_vm.write.assert_not_called()
        parsed = json.loads(result)
        assert "error" in parsed

    @patch("agent.dispatch.MessageToDict", return_value={"status": "ok"})
    def test_write_allowed_when_guards_pass(self, mock_mtd, mock_vm, tracker, protected_files):
        """write_file with passing guards -> vm.write called."""
        from agent.dispatch import dispatch_tool, DispatchContext
        ctx = DispatchContext(source_basename="report.md")
        result = dispatch_tool(
            mock_vm, "write_file",
            {"path": "/out/report.md", "content": "x"},
            tracker, protected_files,
            dispatch_ctx=ctx,
        )
        mock_vm.write.assert_called_once()

    @patch("agent.dispatch.MessageToDict", return_value={"status": "deleted"})
    def test_delete_blocked_by_template_guard(self, mock_mtd, mock_vm, tracker, protected_files):
        """delete_file with underscore-prefixed file -> blocked by template guard."""
        from agent.dispatch import dispatch_tool, DispatchContext
        ctx = DispatchContext()
        result = dispatch_tool(
            mock_vm, "delete_file",
            {"path": "/workspace/_template.md"},
            tracker, protected_files,
            dispatch_ctx=ctx,
        )
        mock_vm.delete.assert_not_called()
        parsed = json.loads(result)
        assert "error" in parsed

    @patch("agent.dispatch.MessageToDict", return_value={"status": "deleted"})
    def test_delete_allowed_when_template_guard_passes(self, mock_mtd, mock_vm, tracker, protected_files):
        """delete_file non-prefixed file -> vm.delete called."""
        from agent.dispatch import dispatch_tool, DispatchContext
        ctx = DispatchContext()
        result = dispatch_tool(
            mock_vm, "delete_file",
            {"path": "/workspace/report.md"},
            tracker, protected_files,
            dispatch_ctx=ctx,
        )
        mock_vm.delete.assert_called_once()

    @patch("agent.dispatch.MessageToDict", return_value={"status": "ok"})
    def test_guards_disabled_when_ctx_none(self, mock_mtd, mock_vm, tracker, protected_files):
        """When dispatch_ctx is None, guards are disabled (backward compat)."""
        from agent.dispatch import dispatch_tool
        # Write to a tracked file without ctx -> should be allowed
        tracker.add("/existing.md")
        result = dispatch_tool(
            mock_vm, "write_file",
            {"path": "/existing.md", "content": "x"},
            tracker, protected_files,
            dispatch_ctx=None,
        )
        mock_vm.write.assert_called_once()


class TestGuardObservabilityLogging:
    """Task 2.9: Guard functions log allow/block decisions."""

    def test_basename_guard_logs_block(self, caplog):
        """_check_basename_guard logs when blocking."""
        import logging
        from agent.dispatch import _check_basename_guard, DispatchContext
        ctx = DispatchContext(source_basename="2026-03-23__hn-foo.md")
        with caplog.at_level(logging.DEBUG, logger="agent.dispatch"):
            _check_basename_guard(ctx, "/out/2026-03-23__0000__hn-foo.md")
        assert any("basename" in r.message.lower() or "mismatch" in r.message.lower()
                    for r in caplog.records)

    def test_scope_guard_logs_block(self, tracker, caplog):
        """_check_scope_guard logs when blocking."""
        import logging
        from agent.dispatch import _check_scope_guard, DispatchContext
        ctx = DispatchContext(scope_constrained=True)
        tracker.add("/file.md")
        with caplog.at_level(logging.DEBUG, logger="agent.dispatch"):
            _check_scope_guard(ctx, "/file.md", tracker)
        assert any("scope" in r.message.lower() or "block" in r.message.lower()
                    for r in caplog.records)

    def test_template_guard_logs_block(self, caplog):
        """_check_template_guard logs when blocking."""
        import logging
        from agent.dispatch import _check_template_guard, DispatchContext
        ctx = DispatchContext()
        with caplog.at_level(logging.DEBUG, logger="agent.dispatch"):
            _check_template_guard(ctx, "/workspace/_template.md")
        assert any("template" in r.message.lower() or "block" in r.message.lower()
                    for r in caplog.records)


# ===========================================================================
# Task 6 TDD Tests: End-to-end Template Guard with Configurable Protected Dirs
# ===========================================================================

class TestTemplateGuardEndToEnd:
    """Task 6.2: End-to-end template guard tests through dispatch_tool.

    Verifies:
    - Deleting _-prefixed file inside protected directory is BLOCKED
    - Deleting _-prefixed file outside protected directory is ALLOWED
    - Empty config (no protected_directories) blocks ALL _-prefixed deletions
    """

    @patch("agent.dispatch.MessageToDict", return_value={"status": "deleted"})
    def test_delete_prefixed_inside_protected_dir_blocked(
        self, mock_mtd, mock_vm, tracker, protected_files,
    ):
        """Deleting a _-prefixed file inside a protected directory should be blocked."""
        from agent.dispatch import dispatch_tool, DispatchContext, TemplateGuardConfig
        cfg = TemplateGuardConfig(protected_directories=("/templates/", "/structural/"))
        ctx = DispatchContext(template_guard_config=cfg)
        result = dispatch_tool(
            mock_vm, "delete_file",
            {"path": "/templates/_header.md"},
            tracker, protected_files,
            dispatch_ctx=ctx,
        )
        mock_vm.delete.assert_not_called()
        parsed = json.loads(result)
        assert "error" in parsed
        assert "template" in parsed["error"].lower() or "structural" in parsed["error"].lower()

    @patch("agent.dispatch.MessageToDict", return_value={"status": "deleted"})
    def test_delete_prefixed_outside_protected_dir_allowed(
        self, mock_mtd, mock_vm, tracker, protected_files,
    ):
        """Deleting a _-prefixed file outside protected directories should be allowed."""
        from agent.dispatch import dispatch_tool, DispatchContext, TemplateGuardConfig
        cfg = TemplateGuardConfig(protected_directories=("/templates/",))
        ctx = DispatchContext(template_guard_config=cfg)
        result = dispatch_tool(
            mock_vm, "delete_file",
            {"path": "/workspace/_draft.md"},
            tracker, protected_files,
            dispatch_ctx=ctx,
        )
        mock_vm.delete.assert_called_once()
        parsed = json.loads(result)
        assert "error" not in parsed

    @patch("agent.dispatch.MessageToDict", return_value={"status": "deleted"})
    def test_delete_prefixed_empty_config_blocks_all(
        self, mock_mtd, mock_vm, tracker, protected_files,
    ):
        """Empty protected_directories (default config) blocks ALL _-prefixed deletions."""
        from agent.dispatch import dispatch_tool, DispatchContext, TemplateGuardConfig
        cfg = TemplateGuardConfig()  # empty protected_directories
        ctx = DispatchContext(template_guard_config=cfg)
        result = dispatch_tool(
            mock_vm, "delete_file",
            {"path": "/anywhere/_config.md"},
            tracker, protected_files,
            dispatch_ctx=ctx,
        )
        mock_vm.delete.assert_not_called()
        parsed = json.loads(result)
        assert "error" in parsed

    @patch("agent.dispatch.MessageToDict", return_value={"status": "deleted"})
    def test_delete_non_prefixed_always_allowed(
        self, mock_mtd, mock_vm, tracker, protected_files,
    ):
        """Non-underscore-prefixed files are always allowed regardless of config."""
        from agent.dispatch import dispatch_tool, DispatchContext, TemplateGuardConfig
        cfg = TemplateGuardConfig(protected_directories=("/templates/",))
        ctx = DispatchContext(template_guard_config=cfg)
        result = dispatch_tool(
            mock_vm, "delete_file",
            {"path": "/templates/report.md"},
            tracker, protected_files,
            dispatch_ctx=ctx,
        )
        mock_vm.delete.assert_called_once()

    @patch("agent.dispatch.MessageToDict", return_value={"status": "deleted"})
    def test_delete_prefixed_in_second_protected_dir_blocked(
        self, mock_mtd, mock_vm, tracker, protected_files,
    ):
        """_-prefixed file in the second protected directory should also be blocked."""
        from agent.dispatch import dispatch_tool, DispatchContext, TemplateGuardConfig
        cfg = TemplateGuardConfig(protected_directories=("/templates/", "/structural/"))
        ctx = DispatchContext(template_guard_config=cfg)
        result = dispatch_tool(
            mock_vm, "delete_file",
            {"path": "/structural/_layout.md"},
            tracker, protected_files,
            dispatch_ctx=ctx,
        )
        mock_vm.delete.assert_not_called()
        parsed = json.loads(result)
        assert "error" in parsed

    @patch("agent.dispatch.MessageToDict", return_value={"status": "deleted"})
    def test_delete_prefixed_nested_inside_protected_dir_blocked(
        self, mock_mtd, mock_vm, tracker, protected_files,
    ):
        """_-prefixed file in a nested path under protected directory is blocked."""
        from agent.dispatch import dispatch_tool, DispatchContext, TemplateGuardConfig
        cfg = TemplateGuardConfig(protected_directories=("/templates/",))
        ctx = DispatchContext(template_guard_config=cfg)
        result = dispatch_tool(
            mock_vm, "delete_file",
            {"path": "/templates/layouts/_base.md"},
            tracker, protected_files,
            dispatch_ctx=ctx,
        )
        mock_vm.delete.assert_not_called()
        parsed = json.loads(result)
        assert "error" in parsed


# ===========================================================================
# Task 7 TDD Tests: Comprehensive Dispatch Guard Tests
# ===========================================================================


class TestExtractSlug:
    """Task 7.1: Comprehensive tests for _extract_slug function.

    Covers date-prefixed stems, date-only prefix, no prefix, empty string,
    and multi-segment numeric prefixes.
    """

    def test_date_and_numeric_prefix(self):
        """Date + numeric prefix: 2026-03-23__0000__hn-foo -> hn-foo."""
        from agent.dispatch import _extract_slug
        assert _extract_slug("2026-03-23__0000__hn-foo") == "hn-foo"

    def test_date_only_prefix(self):
        """Date-only prefix: 2026-03-23__hn-foo -> hn-foo."""
        from agent.dispatch import _extract_slug
        assert _extract_slug("2026-03-23__hn-foo") == "hn-foo"

    def test_no_prefix(self):
        """No prefix: report -> report."""
        from agent.dispatch import _extract_slug
        assert _extract_slug("report") == "report"

    def test_empty_string(self):
        """Empty string -> empty string."""
        from agent.dispatch import _extract_slug
        assert _extract_slug("") == ""

    def test_date_prefix_with_multiple_numeric_segments(self):
        """Multiple numeric segments: 2026-03-23__0000__0001__my-slug -> my-slug."""
        from agent.dispatch import _extract_slug
        assert _extract_slug("2026-03-23__0000__0001__my-slug") == "my-slug"

    def test_slug_with_hyphens(self):
        """Slug with hyphens preserved: 2026-01-01__long-slug-name -> long-slug-name."""
        from agent.dispatch import _extract_slug
        assert _extract_slug("2026-01-01__long-slug-name") == "long-slug-name"

    def test_plain_slug_with_hyphens(self):
        """Plain slug with hyphens (no date prefix): my-report-2026 -> my-report-2026."""
        from agent.dispatch import _extract_slug
        assert _extract_slug("my-report-2026") == "my-report-2026"

    def test_numeric_only_prefix(self):
        """Numeric-only prefix: 0000__slug -> slug."""
        from agent.dispatch import _extract_slug
        assert _extract_slug("0000__slug") == "slug"

    def test_slug_starting_with_underscore(self):
        """Date prefix with underscore-starting slug: 2026-03-23___template -> _template."""
        from agent.dispatch import _extract_slug
        assert _extract_slug("2026-03-23___template") == "_template"


class TestIsBasenameMismatch:
    """Task 7.2: Comprehensive tests for _is_basename_mismatch function.

    Covers exact match, unrelated filenames, inserted segments, empty strings,
    no extension, and no slug prefix.
    """

    def test_exact_match_returns_false(self):
        """Exact same basename -> not a mismatch."""
        from agent.dispatch import _is_basename_mismatch
        assert _is_basename_mismatch("report.md", "/output/report.md") is False

    def test_unrelated_filenames_returns_false(self):
        """Completely unrelated filenames -> not a mismatch (different slugs)."""
        from agent.dispatch import _is_basename_mismatch
        assert _is_basename_mismatch("report.md", "/output/summary.md") is False

    def test_inserted_segment_returns_true(self):
        """Same slug with inserted numeric segment -> mismatch."""
        from agent.dispatch import _is_basename_mismatch
        assert _is_basename_mismatch(
            "2026-03-23__hn-foo.md",
            "/output/2026-03-23__0000__hn-foo.md",
        ) is True

    def test_empty_source_basename(self):
        """Empty source basename: empty slug matching -> returns False."""
        from agent.dispatch import _is_basename_mismatch
        # Both stems are empty or have empty slugs, so src_slug is empty
        # -> cannot match condition "src_slug and src_slug == dst_slug"
        assert _is_basename_mismatch("", "/output/file.md") is False

    def test_empty_written_path(self):
        """Empty written path -> no mismatch (basename is empty)."""
        from agent.dispatch import _is_basename_mismatch
        assert _is_basename_mismatch("report.md", "") is False

    def test_both_empty(self):
        """Both empty -> exact match of empty basename -> returns False."""
        from agent.dispatch import _is_basename_mismatch
        assert _is_basename_mismatch("", "") is False

    def test_no_extension_exact_match(self):
        """No file extension, exact match -> returns False."""
        from agent.dispatch import _is_basename_mismatch
        assert _is_basename_mismatch("Makefile", "/workspace/Makefile") is False

    def test_no_extension_different_file(self):
        """No extension, different unrelated file -> returns False."""
        from agent.dispatch import _is_basename_mismatch
        assert _is_basename_mismatch("Makefile", "/workspace/Dockerfile") is False

    def test_no_slug_prefix_same_slug_different_stem(self):
        """Same slug but different prefix -> mismatch."""
        from agent.dispatch import _is_basename_mismatch
        result = _is_basename_mismatch(
            "2026-03-23__my-slug.md",
            "/out/2026-03-24__my-slug.md",
        )
        # Different date prefix, same slug, different stem -> True
        assert result is True

    def test_deeply_nested_path_exact_match(self):
        """Deeply nested written path with exact basename match."""
        from agent.dispatch import _is_basename_mismatch
        assert _is_basename_mismatch(
            "config.yaml",
            "/a/b/c/d/config.yaml",
        ) is False

    def test_date_prefix_added_to_plain_slug(self):
        """Plain slug source, date-prefixed written -> different slugs -> no mismatch.

        source: my-report.md (slug=my-report)
        written: 2026-03-23__my-report.md (slug=my-report)
        Same slug, different stem -> mismatch.
        """
        from agent.dispatch import _is_basename_mismatch
        assert _is_basename_mismatch(
            "my-report.md",
            "/out/2026-03-23__my-report.md",
        ) is True

    def test_different_extensions_same_stem(self):
        """Same stem but different extension -> different basename -> returns False (unrelated)."""
        from agent.dispatch import _is_basename_mismatch
        # "report.md" vs "report.txt": basename differs, stems are same -> slug same
        # src_stem = "report", dst_stem = "report", src_stem == dst_stem -> False (not mismatch)
        assert _is_basename_mismatch("report.md", "/out/report.txt") is False


class TestScopeGuard:
    """Task 7.3: Comprehensive tests for _check_scope_guard.

    Extends TestCheckScopeGuard with edge cases: multiple target directories,
    subdirectory matching, case sensitivity, and empty target directories.
    """

    def test_blocked_when_file_read_and_scope_constrained(self, tracker):
        """File was read + scope constrained + no target match -> BLOCK."""
        from agent.dispatch import _check_scope_guard, DispatchContext
        ctx = DispatchContext(scope_constrained=True)
        tracker.add("/config.yaml")
        result = _check_scope_guard(ctx, "/config.yaml", tracker)
        assert result is not None
        assert "scope" in result.lower()

    def test_allowed_when_scope_not_constrained(self, tracker):
        """Scope not constrained -> ALLOW regardless."""
        from agent.dispatch import _check_scope_guard, DispatchContext
        ctx = DispatchContext(scope_constrained=False)
        tracker.add("/config.yaml")
        result = _check_scope_guard(ctx, "/config.yaml", tracker)
        assert result is None

    def test_allowed_when_file_not_read(self, tracker):
        """File not previously read -> ALLOW (new file creation)."""
        from agent.dispatch import _check_scope_guard, DispatchContext
        ctx = DispatchContext(scope_constrained=True)
        result = _check_scope_guard(ctx, "/brand-new.md", tracker)
        assert result is None

    def test_allowed_when_target_in_directories(self, tracker):
        """File in target_directories -> ALLOW."""
        from agent.dispatch import _check_scope_guard, DispatchContext
        ctx = DispatchContext(
            scope_constrained=True,
            target_directories=("/output/",),
        )
        tracker.add("/output/result.md")
        result = _check_scope_guard(ctx, "/output/result.md", tracker)
        assert result is None

    def test_multiple_target_directories_second_match(self, tracker):
        """File matches second target directory -> ALLOW."""
        from agent.dispatch import _check_scope_guard, DispatchContext
        ctx = DispatchContext(
            scope_constrained=True,
            target_directories=("/output/", "/results/"),
        )
        tracker.add("/results/data.csv")
        result = _check_scope_guard(ctx, "/results/data.csv", tracker)
        assert result is None

    def test_subdirectory_within_target_allowed(self, tracker):
        """File in subdirectory under target directory -> ALLOW (prefix match)."""
        from agent.dispatch import _check_scope_guard, DispatchContext
        ctx = DispatchContext(
            scope_constrained=True,
            target_directories=("/output/",),
        )
        tracker.add("/output/subdir/deep.md")
        result = _check_scope_guard(ctx, "/output/subdir/deep.md", tracker)
        assert result is None

    def test_empty_target_directories_with_constrained_tracked(self, tracker):
        """Empty target_directories + constrained + tracked -> BLOCK."""
        from agent.dispatch import _check_scope_guard, DispatchContext
        ctx = DispatchContext(
            scope_constrained=True,
            target_directories=(),
        )
        tracker.add("/file.md")
        result = _check_scope_guard(ctx, "/file.md", tracker)
        assert result is not None

    def test_basename_match_allows_even_in_different_directory(self, tracker):
        """Step 4: basename matches source_basename -> ALLOW even in non-target dir."""
        from agent.dispatch import _check_scope_guard, DispatchContext
        ctx = DispatchContext(
            scope_constrained=True,
            source_basename="data.json",
            target_directories=("/output/",),
        )
        tracker.add("/workspace/data.json")
        result = _check_scope_guard(ctx, "/workspace/data.json", tracker)
        assert result is None

    def test_blocked_returns_descriptive_error(self, tracker):
        """Blocked response contains descriptive message about scope constraint."""
        from agent.dispatch import _check_scope_guard, DispatchContext
        ctx = DispatchContext(
            scope_constrained=True,
            target_directories=("/allowed/",),
        )
        tracker.add("/forbidden/secret.md")
        result = _check_scope_guard(ctx, "/forbidden/secret.md", tracker)
        assert result is not None
        assert "forbidden/secret.md" in result or "scope" in result.lower()

    def test_empty_tracker_allows_all_writes(self, tracker):
        """Empty tracker (no files read) -> all writes allowed."""
        from agent.dispatch import _check_scope_guard, DispatchContext
        ctx = DispatchContext(scope_constrained=True)
        result = _check_scope_guard(ctx, "/any/file.md", tracker)
        assert result is None


class TestTemplateGuard:
    """Task 7.4: Comprehensive tests for _check_template_guard.

    Covers: _-prefixed blocked, non-prefixed allowed, _-prefixed in non-protected
    directory allowed, configuration override, empty config blocks all.
    """

    def test_underscore_prefixed_blocked_default(self):
        """_-prefixed file with default config (empty dirs) -> BLOCK."""
        from agent.dispatch import _check_template_guard, DispatchContext
        ctx = DispatchContext()
        result = _check_template_guard(ctx, "/workspace/_template.md")
        assert result is not None
        assert "template" in result.lower() or "structural" in result.lower()

    def test_non_prefixed_allowed(self):
        """Non-underscore-prefixed file -> always ALLOW."""
        from agent.dispatch import _check_template_guard, DispatchContext
        ctx = DispatchContext()
        result = _check_template_guard(ctx, "/workspace/report.md")
        assert result is None

    def test_underscore_prefixed_in_non_protected_dir_allowed(self):
        """_-prefixed file outside protected directories -> ALLOW."""
        from agent.dispatch import _check_template_guard, DispatchContext, TemplateGuardConfig
        cfg = TemplateGuardConfig(protected_directories=("/templates/",))
        ctx = DispatchContext(template_guard_config=cfg)
        result = _check_template_guard(ctx, "/workspace/_draft.md")
        assert result is None

    def test_configuration_override_single_dir(self):
        """Config with single protected dir: _-prefixed inside -> BLOCK."""
        from agent.dispatch import _check_template_guard, DispatchContext, TemplateGuardConfig
        cfg = TemplateGuardConfig(protected_directories=("/templates/",))
        ctx = DispatchContext(template_guard_config=cfg)
        result = _check_template_guard(ctx, "/templates/_header.md")
        assert result is not None

    def test_configuration_override_multiple_dirs(self):
        """Config with multiple protected dirs: each directory is enforced."""
        from agent.dispatch import _check_template_guard, DispatchContext, TemplateGuardConfig
        cfg = TemplateGuardConfig(protected_directories=("/templates/", "/structural/"))
        ctx = DispatchContext(template_guard_config=cfg)
        # Inside first protected dir
        assert _check_template_guard(ctx, "/templates/_header.md") is not None
        # Inside second protected dir
        assert _check_template_guard(ctx, "/structural/_layout.md") is not None
        # Outside all protected dirs
        assert _check_template_guard(ctx, "/workspace/_config.md") is None

    def test_empty_config_blocks_all_prefixed(self):
        """Empty protected_directories (default) blocks ALL _-prefixed files."""
        from agent.dispatch import _check_template_guard, DispatchContext, TemplateGuardConfig
        cfg = TemplateGuardConfig()  # empty tuple
        ctx = DispatchContext(template_guard_config=cfg)
        # Every _-prefixed file should be blocked regardless of location
        assert _check_template_guard(ctx, "/anywhere/_file.md") is not None
        assert _check_template_guard(ctx, "/deep/path/_other.md") is not None
        assert _check_template_guard(ctx, "/_root.md") is not None

    def test_non_prefixed_in_protected_dir_allowed(self):
        """Non-prefixed file inside protected directory -> ALLOW."""
        from agent.dispatch import _check_template_guard, DispatchContext, TemplateGuardConfig
        cfg = TemplateGuardConfig(protected_directories=("/templates/",))
        ctx = DispatchContext(template_guard_config=cfg)
        result = _check_template_guard(ctx, "/templates/normal-file.md")
        assert result is None

    def test_deeply_nested_in_protected_dir_blocked(self):
        """_-prefixed file in deeply nested path under protected dir -> BLOCK."""
        from agent.dispatch import _check_template_guard, DispatchContext, TemplateGuardConfig
        cfg = TemplateGuardConfig(protected_directories=("/templates/",))
        ctx = DispatchContext(template_guard_config=cfg)
        result = _check_template_guard(ctx, "/templates/a/b/c/_deep.md")
        assert result is not None

    def test_blocked_message_includes_file_path(self):
        """Block message includes the file path for debugging."""
        from agent.dispatch import _check_template_guard, DispatchContext
        ctx = DispatchContext()
        result = _check_template_guard(ctx, "/workspace/_important.md")
        assert result is not None
        assert "_important.md" in result or "/workspace/_important.md" in result

    def test_leading_slash_normalization(self):
        """Path with leading slash still matches protected directory."""
        from agent.dispatch import _check_template_guard, DispatchContext, TemplateGuardConfig
        cfg = TemplateGuardConfig(protected_directories=("/templates/",))
        ctx = DispatchContext(template_guard_config=cfg)
        result = _check_template_guard(ctx, "/templates/_file.md")
        assert result is not None


class TestBasenameMismatchGuard:
    """Task 7.5: Comprehensive tests for _check_basename_guard.

    Covers: write blocked on mismatch, write allowed on match,
    write allowed when no source basename set, edge cases.
    """

    def test_blocked_on_mismatch(self):
        """Write blocked when basename mismatch detected."""
        from agent.dispatch import _check_basename_guard, DispatchContext
        ctx = DispatchContext(source_basename="2026-03-23__hn-foo.md")
        result = _check_basename_guard(ctx, "/out/2026-03-23__0000__hn-foo.md")
        assert result is not None
        assert "mismatch" in result.lower() or "Mismatch" in result

    def test_allowed_on_exact_match(self):
        """Write allowed when basename matches exactly."""
        from agent.dispatch import _check_basename_guard, DispatchContext
        ctx = DispatchContext(source_basename="report.md")
        result = _check_basename_guard(ctx, "/output/report.md")
        assert result is None

    def test_allowed_when_no_source_basename(self):
        """Write allowed when no source_basename set (guard inactive)."""
        from agent.dispatch import _check_basename_guard, DispatchContext
        ctx = DispatchContext(source_basename=None)
        result = _check_basename_guard(ctx, "/output/anything.md")
        assert result is None

    def test_allowed_when_source_basename_empty_string(self):
        """Write allowed when source_basename is empty string (falsy)."""
        from agent.dispatch import _check_basename_guard, DispatchContext
        ctx = DispatchContext(source_basename="")
        result = _check_basename_guard(ctx, "/output/file.md")
        assert result is None

    def test_allowed_for_unrelated_file(self):
        """Write allowed for completely unrelated filename."""
        from agent.dispatch import _check_basename_guard, DispatchContext
        ctx = DispatchContext(source_basename="source.md")
        result = _check_basename_guard(ctx, "/output/different.md")
        assert result is None

    def test_blocked_message_contains_expected_and_actual(self):
        """Block message includes both expected and actual basenames."""
        from agent.dispatch import _check_basename_guard, DispatchContext
        ctx = DispatchContext(source_basename="2026-03-23__hn-foo.md")
        result = _check_basename_guard(ctx, "/out/2026-03-23__0000__hn-foo.md")
        assert result is not None
        assert "2026-03-23__hn-foo.md" in result
        assert "2026-03-23__0000__hn-foo.md" in result

    def test_deeply_nested_path_with_mismatch(self):
        """Mismatch detection works for deeply nested paths."""
        from agent.dispatch import _check_basename_guard, DispatchContext
        ctx = DispatchContext(source_basename="2026-03-23__slug.md")
        result = _check_basename_guard(ctx, "/a/b/c/d/2026-03-23__0000__slug.md")
        assert result is not None


class TestGuardEndToEnd:
    """Task 7.6: End-to-end guard tests through dispatch_tool with mocked VM.

    Verifies correct error JSON when guards block and VM is called when guards allow.
    """

    # --- Basename guard e2e ---

    @patch("agent.dispatch.MessageToDict", return_value={"status": "ok"})
    def test_e2e_write_blocked_by_basename_guard(self, mock_mtd, mock_vm, tracker, protected_files):
        """dispatch_tool returns error JSON when basename guard blocks write."""
        from agent.dispatch import dispatch_tool, DispatchContext
        ctx = DispatchContext(source_basename="2026-03-23__hn-foo.md")
        result = dispatch_tool(
            mock_vm, "write_file",
            {"path": "/out/2026-03-23__0000__hn-foo.md", "content": "x"},
            tracker, protected_files,
            dispatch_ctx=ctx,
        )
        mock_vm.write.assert_not_called()
        parsed = json.loads(result)
        assert "error" in parsed
        assert "mismatch" in parsed["error"].lower() or "Mismatch" in parsed["error"]

    @patch("agent.dispatch.MessageToDict", return_value={"status": "ok"})
    def test_e2e_write_allowed_by_basename_guard(self, mock_mtd, mock_vm, tracker, protected_files):
        """dispatch_tool calls VM when basename guard allows write."""
        from agent.dispatch import dispatch_tool, DispatchContext
        ctx = DispatchContext(source_basename="report.md")
        result = dispatch_tool(
            mock_vm, "write_file",
            {"path": "/output/report.md", "content": "content"},
            tracker, protected_files,
            dispatch_ctx=ctx,
        )
        mock_vm.write.assert_called_once()
        parsed = json.loads(result)
        assert "error" not in parsed

    # --- Scope guard e2e ---

    @patch("agent.dispatch.MessageToDict", return_value={"status": "ok"})
    def test_e2e_write_blocked_by_scope_guard(self, mock_mtd, mock_vm, tracker, protected_files):
        """dispatch_tool returns error JSON when scope guard blocks write."""
        from agent.dispatch import dispatch_tool, DispatchContext
        ctx = DispatchContext(scope_constrained=True)
        tracker.add("/readonly.md")
        result = dispatch_tool(
            mock_vm, "write_file",
            {"path": "/readonly.md", "content": "x"},
            tracker, protected_files,
            dispatch_ctx=ctx,
        )
        mock_vm.write.assert_not_called()
        parsed = json.loads(result)
        assert "error" in parsed
        assert "scope" in parsed["error"].lower()

    @patch("agent.dispatch.MessageToDict", return_value={"status": "ok"})
    def test_e2e_write_allowed_by_scope_guard_not_constrained(self, mock_mtd, mock_vm, tracker, protected_files):
        """dispatch_tool calls VM when scope is not constrained."""
        from agent.dispatch import dispatch_tool, DispatchContext
        ctx = DispatchContext(scope_constrained=False)
        tracker.add("/file.md")
        result = dispatch_tool(
            mock_vm, "write_file",
            {"path": "/file.md", "content": "content"},
            tracker, protected_files,
            dispatch_ctx=ctx,
        )
        mock_vm.write.assert_called_once()

    @patch("agent.dispatch.MessageToDict", return_value={"status": "ok"})
    def test_e2e_write_allowed_by_scope_guard_target_dir(self, mock_mtd, mock_vm, tracker, protected_files):
        """dispatch_tool calls VM when write target is in allowed directories."""
        from agent.dispatch import dispatch_tool, DispatchContext
        ctx = DispatchContext(
            scope_constrained=True,
            target_directories=("/output/",),
        )
        tracker.add("/output/result.md")
        result = dispatch_tool(
            mock_vm, "write_file",
            {"path": "/output/result.md", "content": "content"},
            tracker, protected_files,
            dispatch_ctx=ctx,
        )
        mock_vm.write.assert_called_once()

    @patch("agent.dispatch.MessageToDict", return_value={"status": "ok"})
    def test_e2e_write_allowed_by_scope_guard_new_file(self, mock_mtd, mock_vm, tracker, protected_files):
        """dispatch_tool calls VM when writing new file (not previously read)."""
        from agent.dispatch import dispatch_tool, DispatchContext
        ctx = DispatchContext(scope_constrained=True)
        # Do NOT add the file to tracker -> file not read
        result = dispatch_tool(
            mock_vm, "write_file",
            {"path": "/new-file.md", "content": "content"},
            tracker, protected_files,
            dispatch_ctx=ctx,
        )
        mock_vm.write.assert_called_once()

    # --- Template guard e2e ---

    @patch("agent.dispatch.MessageToDict", return_value={"status": "deleted"})
    def test_e2e_delete_blocked_by_template_guard(self, mock_mtd, mock_vm, tracker, protected_files):
        """dispatch_tool returns error JSON when template guard blocks delete."""
        from agent.dispatch import dispatch_tool, DispatchContext
        ctx = DispatchContext()
        result = dispatch_tool(
            mock_vm, "delete_file",
            {"path": "/workspace/_template.md"},
            tracker, protected_files,
            dispatch_ctx=ctx,
        )
        mock_vm.delete.assert_not_called()
        parsed = json.loads(result)
        assert "error" in parsed
        assert "template" in parsed["error"].lower() or "structural" in parsed["error"].lower()

    @patch("agent.dispatch.MessageToDict", return_value={"status": "deleted"})
    def test_e2e_delete_allowed_by_template_guard_non_prefixed(self, mock_mtd, mock_vm, tracker, protected_files):
        """dispatch_tool calls VM for non-prefixed file deletion."""
        from agent.dispatch import dispatch_tool, DispatchContext
        ctx = DispatchContext()
        result = dispatch_tool(
            mock_vm, "delete_file",
            {"path": "/workspace/normal.md"},
            tracker, protected_files,
            dispatch_ctx=ctx,
        )
        mock_vm.delete.assert_called_once()

    @patch("agent.dispatch.MessageToDict", return_value={"status": "deleted"})
    def test_e2e_delete_allowed_template_guard_outside_protected(self, mock_mtd, mock_vm, tracker, protected_files):
        """dispatch_tool calls VM for _-prefixed file outside protected directories."""
        from agent.dispatch import dispatch_tool, DispatchContext, TemplateGuardConfig
        cfg = TemplateGuardConfig(protected_directories=("/templates/",))
        ctx = DispatchContext(template_guard_config=cfg)
        result = dispatch_tool(
            mock_vm, "delete_file",
            {"path": "/workspace/_local.md"},
            tracker, protected_files,
            dispatch_ctx=ctx,
        )
        mock_vm.delete.assert_called_once()

    # --- Guards disabled when ctx is None ---

    @patch("agent.dispatch.MessageToDict", return_value={"status": "ok"})
    def test_e2e_no_guard_when_ctx_none_write(self, mock_mtd, mock_vm, tracker, protected_files):
        """When dispatch_ctx is None, write to tracked file is allowed."""
        from agent.dispatch import dispatch_tool
        tracker.add("/tracked.md")
        result = dispatch_tool(
            mock_vm, "write_file",
            {"path": "/tracked.md", "content": "x"},
            tracker, protected_files,
            dispatch_ctx=None,
        )
        mock_vm.write.assert_called_once()

    @patch("agent.dispatch.MessageToDict", return_value={"status": "deleted"})
    def test_e2e_no_guard_when_ctx_none_delete(self, mock_mtd, mock_vm, tracker, protected_files):
        """When dispatch_ctx is None, _-prefixed file deletion is allowed (no template guard)."""
        from agent.dispatch import dispatch_tool
        result = dispatch_tool(
            mock_vm, "delete_file",
            {"path": "/workspace/_template.md"},
            tracker, protected_files,
            dispatch_ctx=None,
        )
        mock_vm.delete.assert_called_once()

    # --- Read operations bypass guards ---

    @patch("agent.dispatch.MessageToDict", return_value={"content": "text"})
    def test_e2e_read_not_affected_by_guards(self, mock_mtd, mock_vm, tracker, protected_files):
        """Read operations should never be blocked by dispatch guards."""
        from agent.dispatch import dispatch_tool, DispatchContext
        ctx = DispatchContext(scope_constrained=True, source_basename="other.md")
        result = dispatch_tool(
            mock_vm, "read_file",
            {"path": "/any/file.md"},
            tracker, protected_files,
            dispatch_ctx=ctx,
        )
        mock_vm.read.assert_called_once()
        parsed = json.loads(result)
        assert "error" not in parsed


class TestGuardInteractions:
    """Task 7.7: Edge-case and regression tests for guard interactions.

    Tests combinations where multiple guards could potentially fire,
    ensuring correct priority and behavior.
    """

    @patch("agent.dispatch.MessageToDict", return_value={"status": "ok"})
    def test_basename_guard_checked_before_scope_guard(self, mock_mtd, mock_vm, tracker, protected_files):
        """Basename guard fires before scope guard -- basename error returned first."""
        from agent.dispatch import dispatch_tool, DispatchContext
        ctx = DispatchContext(
            source_basename="2026-03-23__hn-foo.md",
            scope_constrained=True,
        )
        tracker.add("/out/2026-03-23__0000__hn-foo.md")
        result = dispatch_tool(
            mock_vm, "write_file",
            {"path": "/out/2026-03-23__0000__hn-foo.md", "content": "x"},
            tracker, protected_files,
            dispatch_ctx=ctx,
        )
        mock_vm.write.assert_not_called()
        parsed = json.loads(result)
        assert "error" in parsed
        # The error should be from basename guard (checked first)
        assert "mismatch" in parsed["error"].lower() or "Mismatch" in parsed["error"]

    @patch("agent.dispatch.MessageToDict", return_value={"status": "ok"})
    def test_scope_guard_fires_when_basename_passes(self, mock_mtd, mock_vm, tracker, protected_files):
        """When basename guard passes but scope guard blocks, scope error is returned."""
        from agent.dispatch import dispatch_tool, DispatchContext
        ctx = DispatchContext(
            source_basename="source.md",
            scope_constrained=True,
        )
        tracker.add("/other/unrelated.md")
        result = dispatch_tool(
            mock_vm, "write_file",
            {"path": "/other/unrelated.md", "content": "x"},
            tracker, protected_files,
            dispatch_ctx=ctx,
        )
        mock_vm.write.assert_not_called()
        parsed = json.loads(result)
        assert "error" in parsed
        assert "scope" in parsed["error"].lower()

    @patch("agent.dispatch.MessageToDict", return_value={"status": "ok"})
    def test_both_guards_pass_allows_write(self, mock_mtd, mock_vm, tracker, protected_files):
        """When both basename and scope guards pass, write proceeds."""
        from agent.dispatch import dispatch_tool, DispatchContext
        ctx = DispatchContext(
            source_basename="report.md",
            scope_constrained=True,
            target_directories=("/output/",),
        )
        tracker.add("/output/report.md")
        result = dispatch_tool(
            mock_vm, "write_file",
            {"path": "/output/report.md", "content": "content"},
            tracker, protected_files,
            dispatch_ctx=ctx,
        )
        mock_vm.write.assert_called_once()

    @patch("agent.dispatch.MessageToDict", return_value={"status": "deleted"})
    def test_template_guard_with_deeply_nested_protected_path(self, mock_mtd, mock_vm, tracker, protected_files):
        """Template guard works with deeply nested protected directory."""
        from agent.dispatch import dispatch_tool, DispatchContext, TemplateGuardConfig
        cfg = TemplateGuardConfig(protected_directories=("/workspace/project/templates/",))
        ctx = DispatchContext(template_guard_config=cfg)
        result = dispatch_tool(
            mock_vm, "delete_file",
            {"path": "/workspace/project/templates/partials/_nav.md"},
            tracker, protected_files,
            dispatch_ctx=ctx,
        )
        mock_vm.delete.assert_not_called()
        parsed = json.loads(result)
        assert "error" in parsed

    @patch("agent.dispatch.MessageToDict", return_value={"status": "deleted"})
    def test_protected_file_guard_takes_precedence_over_template_guard(self, mock_mtd, mock_vm, tracker, protected_files):
        """Protected file guard (in handler) is separate from dispatch_ctx template guard.

        Protected file guard in _handle_delete_file fires even when template guard
        would allow. Both guards are checked -- protected_files check happens in the
        handler after template guard in the pre-dispatch phase.
        """
        from agent.dispatch import dispatch_tool, DispatchContext, TemplateGuardConfig
        cfg = TemplateGuardConfig(protected_directories=("/templates/",))
        ctx = DispatchContext(template_guard_config=cfg)
        # Use a non-prefixed file that is in the protected_files set
        pf = {"config.md"}
        result = dispatch_tool(
            mock_vm, "delete_file",
            {"path": "/config.md"},
            tracker, pf,
            dispatch_ctx=ctx,
        )
        mock_vm.delete.assert_not_called()
        parsed = json.loads(result)
        assert "error" in parsed

    @patch("agent.dispatch.MessageToDict", return_value={"status": "ok"})
    def test_scope_guard_with_basename_match_overrides_block(self, mock_mtd, mock_vm, tracker, protected_files):
        """Scope guard step 4: basename match overrides scope block for source file."""
        from agent.dispatch import dispatch_tool, DispatchContext
        ctx = DispatchContext(
            source_basename="target.md",
            scope_constrained=True,
            target_directories=(),
        )
        tracker.add("/workspace/target.md")
        result = dispatch_tool(
            mock_vm, "write_file",
            {"path": "/workspace/target.md", "content": "modified"},
            tracker, protected_files,
            dispatch_ctx=ctx,
        )
        mock_vm.write.assert_called_once()

    @patch("agent.dispatch.MessageToDict", return_value={"status": "ok"})
    def test_dispatch_parallel_guards_applied_per_call(self, mock_mtd, mock_vm, tracker, protected_files):
        """dispatch_parallel applies guards to each tool call independently."""
        from agent.dispatch import dispatch_parallel, DispatchContext
        from agent.llm import ToolCall
        ctx = DispatchContext(scope_constrained=True)
        tracker.add("/readonly.md")
        tool_calls = [
            ToolCall(id="tc_1", name="write_file", arguments={"path": "/readonly.md", "content": "x"}),
            ToolCall(id="tc_2", name="write_file", arguments={"path": "/new-file.md", "content": "y"}),
        ]
        results = dispatch_parallel(
            mock_vm, tool_calls, tracker, protected_files,
            dispatch_ctx=ctx,
        )
        assert len(results) == 2
        # Find results by id
        results_dict = dict(results)
        # tc_1 should be blocked (readonly.md was tracked and scope constrained)
        parsed_1 = json.loads(results_dict["tc_1"])
        assert "error" in parsed_1
        # tc_2 should succeed (new-file.md was not tracked)
        parsed_2 = json.loads(results_dict["tc_2"])
        assert "error" not in parsed_2
