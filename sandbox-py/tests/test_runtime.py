"""Tests for agent.runtime — RuntimeAdapter protocol and implementations."""

import json
import pytest
from unittest.mock import MagicMock, patch


class TestRuntimeAdapterProtocol:
    """The RuntimeAdapter protocol defines the unified interface."""

    def test_protocol_exists(self):
        from agent.runtime import RuntimeAdapter
        assert hasattr(RuntimeAdapter, 'tree')
        assert hasattr(RuntimeAdapter, 'list_dir')
        assert hasattr(RuntimeAdapter, 'read')
        assert hasattr(RuntimeAdapter, 'write')
        assert hasattr(RuntimeAdapter, 'delete')
        assert hasattr(RuntimeAdapter, 'search')
        assert hasattr(RuntimeAdapter, 'answer')
        assert hasattr(RuntimeAdapter, 'find')
        assert hasattr(RuntimeAdapter, 'mkdir')
        assert hasattr(RuntimeAdapter, 'move')

    def test_runtime_type_attribute(self):
        from agent.runtime import RuntimeAdapter
        assert hasattr(RuntimeAdapter, 'runtime_type')

    def test_extra_tools_attribute(self):
        from agent.runtime import RuntimeAdapter
        assert hasattr(RuntimeAdapter, 'extra_tools')


class TestCreateRuntime:
    """Factory function selects runtime by benchmark ID."""

    def test_create_mini_runtime(self):
        from agent.runtime import create_runtime
        rt = create_runtime("bitgn/sandbox", "http://localhost:8080")
        assert rt.runtime_type == "mini"

    def test_create_pcm_runtime(self):
        from agent.runtime import create_runtime
        rt = create_runtime("bitgn/pac1-dev", "http://localhost:8080")
        assert rt.runtime_type == "pcm"

    def test_create_pcm_runtime_prod(self):
        from agent.runtime import create_runtime
        rt = create_runtime("bitgn/pac1", "http://localhost:8080")
        assert rt.runtime_type == "pcm"

    def test_unknown_benchmark_defaults_to_mini(self):
        from agent.runtime import create_runtime
        rt = create_runtime("bitgn/unknown", "http://localhost:8080")
        assert rt.runtime_type == "mini"


class TestMiniRuntime:
    """MiniRuntime wraps MiniRuntimeClientSync."""

    def test_tree_calls_outline(self):
        from agent.runtime import MiniRuntime
        vm = MagicMock()
        vm.outline.return_value = MagicMock(DESCRIPTOR=MagicMock())
        rt = MiniRuntime(vm)
        rt.tree("/")
        vm.outline.assert_called_once()

    def test_search_passes_count(self):
        from agent.runtime import MiniRuntime
        from bitgn.vm.mini_pb2 import SearchRequest as MiniSearchRequest
        vm = MagicMock()
        vm.search.return_value = MagicMock(DESCRIPTOR=MagicMock())
        rt = MiniRuntime(vm)
        rt.search("/", "pattern", 10)
        vm.search.assert_called_once()
        # Verify the SearchRequest constructor was called with count=10
        MiniSearchRequest.assert_called_with(path="/", pattern="pattern", count=10)

    def test_answer_uses_answer_field(self):
        from agent.runtime import MiniRuntime
        vm = MagicMock()
        vm.answer.return_value = MagicMock(DESCRIPTOR=MagicMock())
        rt = MiniRuntime(vm)
        rt.answer("the answer", ["ref.md"], "completed")
        vm.answer.assert_called_once()

    def test_find_raises_not_implemented(self):
        from agent.runtime import MiniRuntime
        vm = MagicMock()
        rt = MiniRuntime(vm)
        with pytest.raises(NotImplementedError):
            rt.find("/", "name", "all", 10)

    def test_mkdir_raises_not_implemented(self):
        from agent.runtime import MiniRuntime
        vm = MagicMock()
        rt = MiniRuntime(vm)
        with pytest.raises(NotImplementedError):
            rt.mkdir("/dir")

    def test_move_raises_not_implemented(self):
        from agent.runtime import MiniRuntime
        vm = MagicMock()
        rt = MiniRuntime(vm)
        with pytest.raises(NotImplementedError):
            rt.move("/a", "/b")

    def test_extra_tools_empty(self):
        from agent.runtime import MiniRuntime
        vm = MagicMock()
        rt = MiniRuntime(vm)
        assert rt.extra_tools == frozenset()

    def test_runtime_type_is_mini(self):
        from agent.runtime import MiniRuntime
        vm = MagicMock()
        rt = MiniRuntime(vm)
        assert rt.runtime_type == "mini"


class TestPcmRuntime:
    """PcmRuntime wraps PcmRuntimeClientSync."""

    def test_tree_calls_tree(self):
        from agent.runtime import PcmRuntime
        vm = MagicMock()
        vm.tree.return_value = MagicMock(DESCRIPTOR=MagicMock())
        rt = PcmRuntime(vm)
        rt.tree("/")
        vm.tree.assert_called_once()

    def test_search_passes_limit(self):
        from agent.runtime import PcmRuntime
        vm = MagicMock()
        vm.search.return_value = MagicMock(DESCRIPTOR=MagicMock())
        rt = PcmRuntime(vm)
        rt.search("/", "pattern", 10)
        vm.search.assert_called_once()

    def test_answer_maps_completed_to_outcome_ok(self):
        from agent.runtime import PcmRuntime
        vm = MagicMock()
        vm.answer.return_value = MagicMock(DESCRIPTOR=MagicMock())
        rt = PcmRuntime(vm)
        rt.answer("done", ["ref.md"], "completed")
        vm.answer.assert_called_once()

    def test_answer_maps_failed_to_outcome_err_internal(self):
        from agent.runtime import PcmRuntime
        vm = MagicMock()
        vm.answer.return_value = MagicMock(DESCRIPTOR=MagicMock())
        rt = PcmRuntime(vm)
        rt.answer("failed", [], "failed")
        vm.answer.assert_called_once()

    def test_find_calls_vm_find(self):
        from agent.runtime import PcmRuntime
        vm = MagicMock()
        vm.find.return_value = MagicMock(DESCRIPTOR=MagicMock())
        rt = PcmRuntime(vm)
        rt.find("/", "name", "files", 10)
        vm.find.assert_called_once()

    def test_mkdir_calls_vm_mk_dir(self):
        from agent.runtime import PcmRuntime
        vm = MagicMock()
        vm.mk_dir.return_value = MagicMock(DESCRIPTOR=MagicMock())
        rt = PcmRuntime(vm)
        rt.mkdir("/newdir")
        vm.mk_dir.assert_called_once()

    def test_move_calls_vm_move(self):
        from agent.runtime import PcmRuntime
        vm = MagicMock()
        vm.move.return_value = MagicMock(DESCRIPTOR=MagicMock())
        rt = PcmRuntime(vm)
        rt.move("/a", "/b")
        vm.move.assert_called_once()

    def test_extra_tools(self):
        from agent.runtime import PcmRuntime
        vm = MagicMock()
        rt = PcmRuntime(vm)
        assert rt.extra_tools == frozenset({"find", "mkdir", "move"})

    def test_runtime_type_is_pcm(self):
        from agent.runtime import PcmRuntime
        vm = MagicMock()
        rt = PcmRuntime(vm)
        assert rt.runtime_type == "pcm"
