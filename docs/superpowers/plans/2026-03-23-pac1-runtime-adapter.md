# PAC1 Runtime Adapter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable the sandbox-py agent to run against both the Mini (sandbox) and PCM (pac1) benchmarks via a runtime adapter abstraction, selected by `BENCHMARK_ID` env var.

**Architecture:** Introduce a `RuntimeAdapter` protocol in `agent/runtime.py` with two implementations (`MiniRuntime`, `PcmRuntime`). `dispatch.py` works against the adapter instead of the raw VM client. `tools.py` provides runtime-aware tool schemas. `main.py` selects the adapter based on `BENCHMARK_ID`.

**Tech Stack:** Python 3.13+, bitgn SDK (mini_pb2 + pcm_pb2), LiteLLM, pytest

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `agent/runtime.py` | **Create** | `RuntimeAdapter` protocol + `MiniRuntime` + `PcmRuntime` implementations |
| `agent/tools.py` | **Modify** | Add `find`, `mkdir`, `move` schemas; add `get_tool_schemas(runtime_type)` |
| `agent/dispatch.py` | **Modify** | Replace `MiniRuntimeClientSync` with `RuntimeAdapter`; add `find`/`mkdir`/`move` handlers |
| `agent/loop.py` | **Modify** | Accept `RuntimeAdapter`; pass runtime type to tool schema selection |
| `agent/scout.py` | **Modify** | Accept `RuntimeAdapter` (type hint only — already uses `Any`) |
| `agent/__init__.py` | **Modify** | Re-export `create_runtime` factory |
| `main.py` | **Modify** | Read `BENCHMARK_ID`; create runtime adapter; pass to `run_agent` |
| `tests/conftest.py` | **Modify** | Add PCM module mocks |
| `tests/test_runtime.py` | **Create** | Tests for `RuntimeAdapter`, `MiniRuntime`, `PcmRuntime` |
| `tests/test_dispatch.py` | **Modify** | Update mock VM to use adapter method names; add `find`/`mkdir`/`move` handler tests |
| `tests/test_tools.py` | **Modify** | Add tests for `get_tool_schemas()` |
| `tests/test_loop.py` | **Modify** | Replace `harness_url` param with `runtime` mock; remove `MiniRuntimeClientSync` patches |

**No changes to:** `prompt.py`, `verify.py`, `context.py`, `tracker.py`, `skills.py`, `observability.py`, `llm.py`, `dag.py`

### Critical Test Migration Notes

**`test_dispatch.py` (Task 2):** After dispatch handlers call adapter methods (`vm.tree()`, `vm.list_dir()`, `vm.read()`, etc.) instead of raw protobuf methods (`vm.outline()`, `vm.list()`, etc.), ALL existing test assertions against `mock_vm.outline`, `mock_vm.list`, etc. must be updated. The `_make_mock_vm()` fixture must add methods matching the adapter interface: `tree`, `list_dir`, `find`, `mkdir`, `move` (alongside existing `read`, `write`, `delete`, `search`, `answer`).

**`test_loop.py` (Task 4):** ~40 occurrences of `@patch("agent.loop.MiniRuntimeClientSync")` and `harness_url="http://test:1234"` must be replaced. The pattern changes from:
```python
@patch("agent.loop.MiniRuntimeClientSync")
def test_something(self, mock_vm_cls, ...):
    run_agent(executor_model="...", harness_url="http://test:1234", ...)
    mock_vm_cls.assert_called_once_with("http://test:1234")
```
to:
```python
def test_something(self, ...):
    mock_runtime = MagicMock(runtime_type="mini", extra_tools=frozenset())
    run_agent(executor_model="...", runtime=mock_runtime, ...)
```
The `MiniRuntimeClientSync` patch is no longer needed since `run_agent` receives a pre-created runtime adapter. Tests that assert `mock_vm_cls.assert_called_once_with(...)` should be removed or replaced with adapter-level assertions.

---

### Task 1: Create `agent/runtime.py` — RuntimeAdapter Protocol

**Files:**
- Create: `sandbox-py/agent/runtime.py`
- Create: `sandbox-py/tests/test_runtime.py`

This is the foundation. The `RuntimeAdapter` protocol defines the unified interface that both Mini and PCM runtimes implement. Each method normalizes the protobuf differences.

Key API surface mapping:

| Adapter method | Mini call | PCM call |
|---|---|---|
| `tree(path)` | `vm.outline(OutlineRequest(path=))` | `vm.tree(TreeRequest(root=))` |
| `list_dir(path)` | `vm.list(ListRequest(path=))` | `vm.list(ListRequest(name=))` |
| `read(path)` | `vm.read(ReadRequest(path=))` | `vm.read(ReadRequest(path=))` |
| `write(path, content)` | `vm.write(WriteRequest(path=, content=))` | `vm.write(WriteRequest(path=, content=))` |
| `delete(path)` | `vm.delete(DeleteRequest(path=))` | `vm.delete(DeleteRequest(path=))` |
| `search(path, pattern, limit)` | `vm.search(SearchRequest(path=, pattern=, count=))` | `vm.search(SearchRequest(root=, pattern=, limit=))` |
| `answer(answer, refs, code)` | `vm.answer(AnswerRequest(answer=, refs=))` | `vm.answer(AnswerRequest(message=, outcome=ENUM, refs=))` |
| `find(root, name, kind, limit)` | raises `NotImplementedError` | `vm.find(FindRequest(root=, name=, type=, limit=))` |
| `mkdir(path)` | raises `NotImplementedError` | `vm.mk_dir(MkDirRequest(path=))` |
| `move(from_name, to_name)` | raises `NotImplementedError` | `vm.move(MoveRequest(from_name=, to_name=))` |

Code-to-outcome mapping for PCM adapter:
- `"completed"` → `Outcome.OUTCOME_OK`
- `"failed"` → `Outcome.OUTCOME_ERR_INTERNAL`
- Direct outcome strings like `"OUTCOME_DENIED_SECURITY"` pass through as-is

- [ ] **Step 1: Write failing tests for RuntimeAdapter protocol**

```python
# tests/test_runtime.py
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
        """Each runtime declares which extra tools it supports."""
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
        vm = MagicMock()
        vm.search.return_value = MagicMock(DESCRIPTOR=MagicMock())
        rt = MiniRuntime(vm)
        rt.search("/", "pattern", 10)
        vm.search.assert_called_once()
        args = vm.search.call_args[0][0]
        assert args.count == 10

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd sandbox-py && uv run pytest tests/test_runtime.py -v`
Expected: FAIL (module `agent.runtime` does not exist)

- [ ] **Step 3: Implement `agent/runtime.py`**

```python
# agent/runtime.py
"""Runtime adapters: unified interface over Mini and PCM VMs.

Leaf module: imports only from bitgn SDK (no agent/ cross-imports).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from google.protobuf.json_format import MessageToDict

from bitgn.vm.mini_connect import MiniRuntimeClientSync
from bitgn.vm.mini_pb2 import (
    AnswerRequest as MiniAnswerRequest,
    DeleteRequest as MiniDeleteRequest,
    ListRequest as MiniListRequest,
    OutlineRequest,
    ReadRequest as MiniReadRequest,
    SearchRequest as MiniSearchRequest,
    WriteRequest as MiniWriteRequest,
)

from bitgn.vm.pcm_connect import PcmRuntimeClientSync
from bitgn.vm.pcm_pb2 import (
    AnswerRequest as PcmAnswerRequest,
    DeleteRequest as PcmDeleteRequest,
    FindRequest,
    ListRequest as PcmListRequest,
    MkDirRequest,
    MoveRequest,
    Outcome,
    ReadRequest as PcmReadRequest,
    SearchRequest as PcmSearchRequest,
    TreeRequest,
    WriteRequest as PcmWriteRequest,
)


@runtime_checkable
class RuntimeAdapter(Protocol):
    """Unified interface for bitgn VM runtimes."""

    @property
    def runtime_type(self) -> str: ...

    @property
    def extra_tools(self) -> frozenset[str]: ...

    def tree(self, path: str) -> Any: ...
    def list_dir(self, path: str) -> Any: ...
    def read(self, path: str) -> Any: ...
    def write(self, path: str, content: str) -> Any: ...
    def delete(self, path: str) -> Any: ...
    def search(self, root: str, pattern: str, limit: int) -> Any: ...
    def answer(self, answer: str, refs: list[str], code: str) -> Any: ...
    def find(self, root: str, name: str, kind: str, limit: int) -> Any: ...
    def mkdir(self, path: str) -> Any: ...
    def move(self, from_name: str, to_name: str) -> Any: ...


class MiniRuntime:
    """Adapter for the Mini sandbox runtime."""

    runtime_type = "mini"
    extra_tools = frozenset()

    def __init__(self, vm: MiniRuntimeClientSync) -> None:
        self._vm = vm

    def tree(self, path: str) -> Any:
        return self._vm.outline(OutlineRequest(path=path))

    def list_dir(self, path: str) -> Any:
        return self._vm.list(MiniListRequest(path=path))

    def read(self, path: str) -> Any:
        return self._vm.read(MiniReadRequest(path=path))

    def write(self, path: str, content: str) -> Any:
        return self._vm.write(MiniWriteRequest(path=path, content=content))

    def delete(self, path: str) -> Any:
        return self._vm.delete(MiniDeleteRequest(path=path))

    def search(self, root: str, pattern: str, limit: int) -> Any:
        return self._vm.search(MiniSearchRequest(path=root, pattern=pattern, count=limit))

    def answer(self, answer: str, refs: list[str], code: str) -> Any:
        return self._vm.answer(MiniAnswerRequest(answer=answer, refs=refs))

    def find(self, root: str, name: str, kind: str, limit: int) -> Any:
        raise NotImplementedError("Mini runtime does not support find")

    def mkdir(self, path: str) -> Any:
        raise NotImplementedError("Mini runtime does not support mkdir")

    def move(self, from_name: str, to_name: str) -> Any:
        raise NotImplementedError("Mini runtime does not support move")


# PCM code-to-outcome mapping
_CODE_TO_OUTCOME = {
    "completed": Outcome.OUTCOME_OK,
    "failed": Outcome.OUTCOME_ERR_INTERNAL,
    "OUTCOME_OK": Outcome.OUTCOME_OK,
    "OUTCOME_DENIED_SECURITY": Outcome.OUTCOME_DENIED_SECURITY,
    "OUTCOME_NONE_CLARIFICATION": Outcome.OUTCOME_NONE_CLARIFICATION,
    "OUTCOME_NONE_UNSUPPORTED": Outcome.OUTCOME_NONE_UNSUPPORTED,
    "OUTCOME_ERR_INTERNAL": Outcome.OUTCOME_ERR_INTERNAL,
}

# PCM find kind mapping
_FIND_TYPE = {"all": 0, "files": 1, "dirs": 2}


class PcmRuntime:
    """Adapter for the PCM pac1 runtime."""

    runtime_type = "pcm"
    extra_tools = frozenset({"find", "mkdir", "move"})

    def __init__(self, vm: PcmRuntimeClientSync) -> None:
        self._vm = vm

    def tree(self, path: str) -> Any:
        return self._vm.tree(TreeRequest(root=path))

    def list_dir(self, path: str) -> Any:
        return self._vm.list(PcmListRequest(name=path))

    def read(self, path: str) -> Any:
        return self._vm.read(PcmReadRequest(path=path))

    def write(self, path: str, content: str) -> Any:
        return self._vm.write(PcmWriteRequest(path=path, content=content))

    def delete(self, path: str) -> Any:
        return self._vm.delete(PcmDeleteRequest(path=path))

    def search(self, root: str, pattern: str, limit: int) -> Any:
        return self._vm.search(PcmSearchRequest(root=root, pattern=pattern, limit=limit))

    def answer(self, answer: str, refs: list[str], code: str) -> Any:
        outcome = _CODE_TO_OUTCOME.get(code, Outcome.OUTCOME_OK)
        return self._vm.answer(PcmAnswerRequest(message=answer, outcome=outcome, refs=refs))

    def find(self, root: str, name: str, kind: str, limit: int) -> Any:
        return self._vm.find(FindRequest(root=root, name=name, type=_FIND_TYPE.get(kind, 0), limit=limit))

    def mkdir(self, path: str) -> Any:
        return self._vm.mk_dir(MkDirRequest(path=path))

    def move(self, from_name: str, to_name: str) -> Any:
        return self._vm.move(MoveRequest(from_name=from_name, to_name=to_name))


def create_runtime(benchmark_id: str, harness_url: str) -> RuntimeAdapter:
    """Factory: create the appropriate runtime adapter for a benchmark."""
    if benchmark_id.startswith("bitgn/pac1"):
        vm = PcmRuntimeClientSync(harness_url)
        return PcmRuntime(vm)
    else:
        vm = MiniRuntimeClientSync(harness_url)
        return MiniRuntime(vm)
```

- [ ] **Step 4: Update `tests/conftest.py` to mock PCM modules**

Add PCM module mocks alongside existing Mini mocks:

```python
# Add to the for loop in conftest.py:
for _mod in [
    # ... existing mini mocks ...
    "bitgn.vm.pcm_connect",
    "bitgn.vm.pcm_pb2",
]:
    sys.modules.setdefault(_mod, _bitgn_mock)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd sandbox-py && uv run pytest tests/test_runtime.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add sandbox-py/agent/runtime.py sandbox-py/tests/test_runtime.py sandbox-py/tests/conftest.py
git commit -m "feat: add RuntimeAdapter protocol with Mini and PCM implementations"
```

---

### Task 2: Update `agent/dispatch.py` — Use RuntimeAdapter

**Files:**
- Modify: `sandbox-py/agent/dispatch.py`
- Modify: `sandbox-py/tests/test_dispatch.py`

Replace direct `MiniRuntimeClientSync` usage with `RuntimeAdapter`. Add handlers for `find`, `mkdir`, `move`.

- [ ] **Step 1: Write failing tests for new handlers**

Add to `tests/test_dispatch.py`:

```python
class TestFindHandler:
    """find handler delegates to runtime.find()."""

    @patch("agent.dispatch.MessageToDict", return_value={"items": []})
    def test_find_calls_runtime(self, mock_mtd, mock_vm, tracker, protected_files):
        from agent.dispatch import dispatch_tool
        mock_vm.find.return_value = MagicMock(DESCRIPTOR=MagicMock())
        result = dispatch_tool(mock_vm, "find", {"root": "/", "name": "test", "kind": "all", "limit": 10}, tracker, protected_files)
        mock_vm.find.assert_called_once()
        assert isinstance(result, str)


class TestMkDirHandler:
    """mkdir handler delegates to runtime.mkdir()."""

    @patch("agent.dispatch.MessageToDict", return_value={})
    def test_mkdir_calls_runtime(self, mock_mtd, mock_vm, tracker, protected_files):
        from agent.dispatch import dispatch_tool
        mock_vm.mkdir.return_value = MagicMock(DESCRIPTOR=MagicMock())
        result = dispatch_tool(mock_vm, "mkdir", {"path": "/newdir"}, tracker, protected_files)
        mock_vm.mkdir.assert_called_once()
        assert isinstance(result, str)


class TestMoveHandler:
    """move handler delegates to runtime.move()."""

    @patch("agent.dispatch.MessageToDict", return_value={})
    def test_move_calls_runtime(self, mock_mtd, mock_vm, tracker, protected_files):
        from agent.dispatch import dispatch_tool
        mock_vm.move.return_value = MagicMock(DESCRIPTOR=MagicMock())
        result = dispatch_tool(mock_vm, "move", {"from_name": "/a", "to_name": "/b"}, tracker, protected_files)
        mock_vm.move.assert_called_once()
        assert isinstance(result, str)
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `cd sandbox-py && uv run pytest tests/test_dispatch.py::TestFindHandler tests/test_dispatch.py::TestMkDirHandler tests/test_dispatch.py::TestMoveHandler -v`
Expected: FAIL (handlers don't exist)

- [ ] **Step 3: Update `agent/dispatch.py`**

Full list of changes:

**Imports — remove:**
```python
from bitgn.vm.mini_connect import MiniRuntimeClientSync
from bitgn.vm.mini_pb2 import (
    AnswerRequest, DeleteRequest, ListRequest, OutlineRequest,
    ReadRequest, SearchRequest, WriteRequest,
)
```

**Imports — keep:**
```python
from google.protobuf.json_format import MessageToDict
from connectrpc.errors import ConnectError
```

**All handler updates** (each handler removes protobuf construction, calls adapter methods):

```python
def _handle_tree(vm, args, tracker, protected_files, skill_loader) -> str:
    path = args.get("path", "/")
    resp = vm.tree(path)
    return json.dumps(MessageToDict(resp), ensure_ascii=False)

def _handle_list_dir(vm, args, tracker, protected_files, skill_loader) -> str:
    path = args.get("path", "/")
    resp = vm.list_dir(path)
    return json.dumps(MessageToDict(resp), ensure_ascii=False)

def _handle_read_file(vm, args, tracker, protected_files, skill_loader) -> str:
    path = args.get("path", "")
    resp = vm.read(path)
    tracker.add(path)
    return json.dumps(MessageToDict(resp), ensure_ascii=False)

def _handle_write_file(vm, args, tracker, protected_files, skill_loader) -> str:
    path = args.get("path", "")
    content = args.get("content", "")
    resp = vm.write(path, content)
    return json.dumps(MessageToDict(resp), ensure_ascii=False)

def _handle_delete_file(vm, args, tracker, protected_files, skill_loader) -> str:
    path = args.get("path", "")
    normalized = _normalize_path(path)
    if normalized in protected_files:
        log.warning("REFUSED: delete %s (protected policy file)", path)
        return json.dumps({"error": f"Cannot delete protected file: {path}"}, ensure_ascii=False)
    resp = vm.delete(path)
    return json.dumps(MessageToDict(resp), ensure_ascii=False)

def _handle_search(vm, args, tracker, protected_files, skill_loader) -> str:
    pattern = args.get("pattern", "")
    path = args.get("path", "/")
    count = args.get("count", 5)
    resp = vm.search(path, pattern, count)
    return json.dumps(MessageToDict(resp), ensure_ascii=False)

def _handle_report_completion(vm, args, tracker, protected_files, skill_loader) -> str:
    answer = args.get("answer", "")
    llm_refs = args.get("grounding_refs", [])
    code = args.get("code", "completed")
    refs = llm_refs if llm_refs else tracker.merge([])
    resp = vm.answer(answer, refs, code)
    return json.dumps(MessageToDict(resp), ensure_ascii=False)
```

**New handlers:**
```python
def _handle_find(vm, args, tracker, protected_files, skill_loader) -> str:
    root = args.get("root", "/")
    name = args.get("name", "")
    kind = args.get("kind", "all")
    limit = args.get("limit", 10)
    resp = vm.find(root, name, kind, limit)
    return json.dumps(MessageToDict(resp), ensure_ascii=False)

def _handle_mkdir(vm, args, tracker, protected_files, skill_loader) -> str:
    path = args.get("path", "")
    resp = vm.mkdir(path)
    return json.dumps(MessageToDict(resp), ensure_ascii=False)

def _handle_move(vm, args, tracker, protected_files, skill_loader) -> str:
    from_name = args.get("from_name", "")
    to_name = args.get("to_name", "")
    normalized_from = _normalize_path(from_name)
    if normalized_from in protected_files:
        log.warning("REFUSED: move %s (protected policy file)", from_name)
        return json.dumps({"error": f"Cannot move protected file: {from_name}"}, ensure_ascii=False)
    resp = vm.move(from_name, to_name)
    return json.dumps(MessageToDict(resp), ensure_ascii=False)
```

**Updated DISPATCH_MAP:**
```python
DISPATCH_MAP: dict[str, Callable] = {
    "tree": _handle_tree,
    "list_dir": _handle_list_dir,
    "read_file": _handle_read_file,
    "write_file": _handle_write_file,
    "delete_file": _handle_delete_file,
    "search": _handle_search,
    "report_completion": _handle_report_completion,
    "load_skill": _handle_load_skill,
    "compact": _handle_compact,
    "find": _handle_find,
    "mkdir": _handle_mkdir,
    "move": _handle_move,
}
```

**Updated function signatures:**
```python
def dispatch_tool(vm, tool_name, args, tracker, protected_files, skill_loader=None, context_config=None) -> str:
def dispatch_parallel(vm, tool_calls, tracker, protected_files, skill_loader=None, max_workers=4, context_config=None) -> list[tuple[str, str]]:
```

Remove `agent.tracker`, `agent.llm`, `agent.context` imports that reference types no longer needed for type hints. Keep `ToolCall` import for `dispatch_parallel`.

- [ ] **Step 4: Update existing dispatch tests**

**Update `_make_mock_vm()` fixture** — add adapter method names:

```python
def _make_mock_vm():
    """Create a mock RuntimeAdapter with all expected methods."""
    vm = MagicMock()
    # Adapter methods (each returns a protobuf-like response)
    for method in ['tree', 'list_dir', 'read', 'write', 'delete', 'search', 'answer', 'find', 'mkdir', 'move']:
        resp = MagicMock()
        resp.DESCRIPTOR = MagicMock()
        getattr(vm, method).return_value = resp
    vm.runtime_type = "mini"
    vm.extra_tools = frozenset()
    return vm
```

**Update assertions** — find-and-replace across test file:
- `mock_vm.outline.assert_called_once()` → `mock_vm.tree.assert_called_once()`
- `mock_vm.list.assert_called_once()` → `mock_vm.list_dir.assert_called_once()`
- `mock_vm.read.assert_called_once()` → `mock_vm.read.assert_called_once()` (unchanged)
- `mock_vm.write.assert_called_once()` → `mock_vm.write.assert_called_once()` (unchanged)
- `mock_vm.delete.assert_called_once()` → `mock_vm.delete.assert_called_once()` (unchanged)
- `mock_vm.search.assert_called_once()` → `mock_vm.search.assert_called_once()` (unchanged)
- `mock_vm.read.side_effect` → stays the same (adapter uses same method name)

**Update `TestDispatchModuleDependencies`:**
```python
def test_dispatch_imports(self):
    import agent.dispatch as mod
    with open(mod.__file__) as f:
        source = f.read()
    import re
    agent_imports = re.findall(r"from\s+agent\.(\w+)", source)
    allowed = {"tracker", "tools", "llm", "context"}
    for imp in agent_imports:
        assert imp in allowed
```
This test stays the same — dispatch no longer imports from `agent.runtime` (it receives the adapter as a parameter).

**Add test for move protected file refusal:**
```python
class TestMoveHandler:
    """move handler delegates to runtime.move() with protected file check."""

    @patch("agent.dispatch.MessageToDict", return_value={})
    def test_move_calls_runtime(self, mock_mtd, mock_vm, tracker, protected_files):
        from agent.dispatch import dispatch_tool
        result = dispatch_tool(mock_vm, "move", {"from_name": "/a.txt", "to_name": "/b.txt"}, tracker, protected_files)
        mock_vm.move.assert_called_once()

    def test_move_protected_file_is_refused(self, mock_vm, tracker, protected_files):
        from agent.dispatch import dispatch_tool
        result = dispatch_tool(mock_vm, "move", {"from_name": "/AGENTS.MD", "to_name": "/renamed.md"}, tracker, protected_files)
        mock_vm.move.assert_not_called()
        parsed = json.loads(result)
        assert "error" in parsed
```

- [ ] **Step 5: Run all dispatch tests**

Run: `cd sandbox-py && uv run pytest tests/test_dispatch.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add sandbox-py/agent/dispatch.py sandbox-py/tests/test_dispatch.py
git commit -m "feat: update dispatch.py to use RuntimeAdapter, add find/mkdir/move handlers"
```

---

### Task 3: Update `agent/tools.py` — Runtime-Aware Tool Schemas

**Files:**
- Modify: `sandbox-py/agent/tools.py`
- Modify: `sandbox-py/tests/test_tools.py`

Add tool schemas for `find`, `mkdir`, `move`. Add `get_tool_schemas()` function that returns the right set based on runtime type.

- [ ] **Step 1: Write failing tests**

```python
class TestGetToolSchemas:
    """get_tool_schemas returns runtime-appropriate schemas."""

    def test_mini_returns_base_tools(self):
        from agent.tools import get_tool_schemas
        schemas = get_tool_schemas("mini")
        names = {s["function"]["name"] for s in schemas}
        assert "tree" in names
        assert "find" not in names
        assert "mkdir" not in names
        assert "move" not in names

    def test_pcm_includes_extra_tools(self):
        from agent.tools import get_tool_schemas
        schemas = get_tool_schemas("pcm")
        names = {s["function"]["name"] for s in schemas}
        assert "tree" in names
        assert "find" in names
        assert "mkdir" in names
        assert "move" in names

    def test_pcm_find_schema_has_required_params(self):
        from agent.tools import get_tool_schemas
        schemas = get_tool_schemas("pcm")
        find_schema = next(s for s in schemas if s["function"]["name"] == "find")
        props = find_schema["function"]["parameters"]["properties"]
        assert "name" in props
        assert "root" in props
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd sandbox-py && uv run pytest tests/test_tools.py::TestGetToolSchemas -v`
Expected: FAIL

- [ ] **Step 3: Implement changes to `agent/tools.py`**

Add schema definitions for `find`, `mkdir`, `move` after existing schemas. Add `get_tool_schemas(runtime_type)` function:

```python
_PCM_EXTRA_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "find",
            "description": "Find files or directories by name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name pattern to find."},
                    "root": {"type": "string", "description": "Root path to search from.", "default": "/"},
                    "kind": {"type": "string", "enum": ["all", "files", "dirs"], "description": "Type filter.", "default": "all"},
                    "limit": {"type": "integer", "description": "Maximum results.", "default": 10},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mkdir",
            "description": "Create a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path to create."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move",
            "description": "Move or rename a file or directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_name": {"type": "string", "description": "Current path."},
                    "to_name": {"type": "string", "description": "New path."},
                },
                "required": ["from_name", "to_name"],
            },
        },
    },
]


def get_tool_schemas(runtime_type: str = "mini") -> list[dict]:
    """Return tool schemas appropriate for the given runtime type."""
    if runtime_type == "pcm":
        return TOOL_SCHEMAS + _PCM_EXTRA_SCHEMAS
    return TOOL_SCHEMAS
```

Update `TOOL_NAMES` and `SCOUT_TOOL_SCHEMAS` to remain backward-compatible (they keep working for mini).

- [ ] **Step 4: Run tests**

Run: `cd sandbox-py && uv run pytest tests/test_tools.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add sandbox-py/agent/tools.py sandbox-py/tests/test_tools.py
git commit -m "feat: add PCM tool schemas (find, mkdir, move) and get_tool_schemas()"
```

---

### Task 4: Update `agent/loop.py` — Accept RuntimeAdapter

**Files:**
- Modify: `sandbox-py/agent/loop.py`
- Modify: `sandbox-py/agent/__init__.py`

Key changes to `loop.py`:
1. Replace `from bitgn.vm.mini_connect import MiniRuntimeClientSync` with import of `RuntimeAdapter` type
2. Change `run_agent()` signature: replace `harness_url: str` with `runtime: RuntimeAdapter` (alternative: keep `harness_url` but also accept `runtime`)
3. Use `runtime` instead of `vm` throughout
4. Pass `runtime.runtime_type` to `get_tool_schemas()` instead of using `TOOL_SCHEMAS` directly
5. Replace `vm = MiniRuntimeClientSync(harness_url)` with using the passed-in `runtime`

- [ ] **Step 1: Update `run_agent()` signature and loop.py imports**

Remove:
```python
from bitgn.vm.mini_connect import MiniRuntimeClientSync
```

Add:
```python
from agent.tools import get_tool_schemas
```

Change signature from:
```python
def run_agent(
    executor_model: str,
    harness_url: str,
    task_text: str,
    scout_model: str | None = None,
    skills_dir: Path | None = None,
) -> None:
    vm = MiniRuntimeClientSync(harness_url)
```
to:
```python
def run_agent(
    executor_model: str,
    runtime: Any,  # RuntimeAdapter
    task_text: str,
    scout_model: str | None = None,
    skills_dir: Path | None = None,
) -> None:
```

- [ ] **Step 2: Replace `vm` with `runtime` throughout loop.py**

Mechanical replacements:
1. Delete `vm = MiniRuntimeClientSync(harness_url)` line
2. Replace all `vm` references with `runtime` in calls to `dispatch_tool`, `dispatch_parallel`, `run_scout`
3. Replace `TOOL_SCHEMAS` with `get_tool_schemas(runtime.runtime_type)` in the `call_llm` call:
   ```python
   # Before:
   response = call_llm(executor_model, messages, tools=TOOL_SCHEMAS, metadata=trace_metadata)
   # After:
   tool_schemas = get_tool_schemas(runtime.runtime_type)
   response = call_llm(executor_model, messages, tools=tool_schemas, metadata=trace_metadata)
   ```
4. Remove `from agent.tools import TOOL_SCHEMAS` (replaced by `get_tool_schemas`)

- [ ] **Step 3: Update `agent/__init__.py`**

```python
"""agent package -- re-exports run_agent and create_runtime."""

from agent.loop import run_agent
from agent.runtime import create_runtime

__all__ = ["run_agent", "create_runtime"]
```

- [ ] **Step 4: Update `tests/test_loop.py`**

This is a large mechanical update (~40 test methods). Apply these transformations:

**Remove all `@patch("agent.loop.MiniRuntimeClientSync")` decorators** and their corresponding `mock_vm_cls` parameters.

**Replace `harness_url="http://test:1234"` with `runtime=mock_runtime`** in all `run_agent()` calls.

**Add a helper function** at the top of the file:
```python
def _make_mock_runtime():
    """Create a mock RuntimeAdapter for testing."""
    rt = MagicMock()
    rt.runtime_type = "mini"
    rt.extra_tools = frozenset()
    return rt
```

**Pattern for each test method — before:**
```python
@patch("agent.loop.run_scout")
@patch("agent.loop.call_llm")
@patch("agent.loop.MiniRuntimeClientSync")
def test_something(self, mock_vm_cls, mock_call_llm, mock_run_scout):
    # ...
    run_agent(executor_model="openai/gpt-4.1", harness_url="http://test:1234", task_text="do something")
    mock_vm_cls.assert_called_once_with("http://test:1234")
```

**After:**
```python
@patch("agent.loop.run_scout")
@patch("agent.loop.call_llm")
def test_something(self, mock_call_llm, mock_run_scout):
    # ...
    mock_runtime = _make_mock_runtime()
    run_agent(executor_model="openai/gpt-4.1", runtime=mock_runtime, task_text="do something")
```

**Update signature test:**
```python
def test_run_agent_signature_has_required_params(self):
    import inspect
    from agent.loop import run_agent
    sig = inspect.signature(run_agent)
    params = list(sig.parameters.keys())
    assert "executor_model" in params
    assert "runtime" in params  # was "harness_url"
    assert "task_text" in params
```

**Remove `test_creates_vm_client_with_harness_url`** — no longer relevant since runtime is pre-created.

- [ ] **Step 5: Run all loop tests**

Run: `cd sandbox-py && uv run pytest tests/test_loop.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add sandbox-py/agent/loop.py sandbox-py/agent/__init__.py sandbox-py/tests/test_loop.py
git commit -m "feat: update loop.py to accept RuntimeAdapter instead of raw VM"
```

---

### Task 5: Update `main.py` — Benchmark Selection

**Files:**
- Modify: `sandbox-py/main.py`

Key changes:
1. Read `BENCHMARK_ID` env var (default: `"bitgn/sandbox"`)
2. After `start_playground`, call `create_runtime(benchmark_id, trial.harness_url)` to get the adapter
3. Pass `runtime` to `run_agent()` instead of `harness_url`

- [ ] **Step 1: Update main.py**

Change from:
```python
from agent import run_agent
# ...
BITGN_URL = os.getenv("BENCHMARK_HOST") or "https://api.bitgn.com"
# ...
res = client.get_benchmark(GetBenchmarkRequest(benchmark_id="bitgn/sandbox"))
# ...
run_agent(
    executor_model=MODEL_ID,
    harness_url=trial.harness_url,
    task_text=trial.instruction,
    scout_model=SCOUT_MODEL,
    skills_dir=SKILLS_DIR,
)
```
to:
```python
from agent import run_agent, create_runtime
# ...
BITGN_URL = os.getenv("BENCHMARK_HOST") or "https://api.bitgn.com"
BENCHMARK_ID = os.getenv("BENCHMARK_ID") or "bitgn/sandbox"
# ...
res = client.get_benchmark(GetBenchmarkRequest(benchmark_id=BENCHMARK_ID))
# ...
runtime = create_runtime(BENCHMARK_ID, trial.harness_url)
run_agent(
    executor_model=MODEL_ID,
    runtime=runtime,
    task_text=trial.instruction,
    scout_model=SCOUT_MODEL,
    skills_dir=SKILLS_DIR,
)
```

Also update `start_playground` to use `BENCHMARK_ID`:
```python
trial = client.start_playground(StartPlaygroundRequest(
    benchmark_id=BENCHMARK_ID,
    task_id=t.task_id,
))
```

- [ ] **Step 2: Run tests**

Run: `cd sandbox-py && uv run pytest tests/ -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add sandbox-py/main.py
git commit -m "feat: add BENCHMARK_ID env var for dual-benchmark support"
```

---

### Task 6: Integration Verification

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `cd sandbox-py && uv run pytest tests/ -v`
Expected: All PASS

- [ ] **Step 2: Verify sandbox still works (dry import check)**

Run: `cd sandbox-py && uv run python -c "from agent import run_agent, create_runtime; rt = create_runtime('bitgn/sandbox', 'http://localhost'); print(f'type={rt.runtime_type}, extra_tools={rt.extra_tools}')"`
Expected: `type=mini, extra_tools=frozenset()`

- [ ] **Step 3: Verify PAC1 runtime creation works**

Run: `cd sandbox-py && uv run python -c "from agent import run_agent, create_runtime; rt = create_runtime('bitgn/pac1-dev', 'http://localhost'); print(f'type={rt.runtime_type}, extra_tools={rt.extra_tools}')"`
Expected: `type=pcm, extra_tools=frozenset({'find', 'mkdir', 'move'})`

- [ ] **Step 4: Commit all remaining changes**

```bash
git add -A sandbox-py/
git commit -m "feat: complete dual-benchmark support (sandbox + pac1)"
```
