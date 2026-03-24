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

    def tree(self, path: str, level: int = 0) -> Any: ...
    def list_dir(self, path: str) -> Any: ...
    def read(self, path: str, number: bool = False, start_line: int = 0, end_line: int = 0) -> Any: ...
    def write(self, path: str, content: str, start_line: int = 0, end_line: int = 0) -> Any: ...
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

    def tree(self, path: str, level: int = 0) -> Any:
        return self._vm.outline(OutlineRequest(path=path))

    def list_dir(self, path: str) -> Any:
        return self._vm.list(MiniListRequest(path=path))

    def read(self, path: str, number: bool = False, start_line: int = 0, end_line: int = 0) -> Any:
        return self._vm.read(MiniReadRequest(path=path))

    def write(self, path: str, content: str, start_line: int = 0, end_line: int = 0) -> Any:
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


_CODE_TO_OUTCOME = {
    "completed": Outcome.OUTCOME_OK,
    "failed": Outcome.OUTCOME_ERR_INTERNAL,
    "unsupported": Outcome.OUTCOME_NONE_UNSUPPORTED,
    "denied": Outcome.OUTCOME_DENIED_SECURITY,
    "clarification": Outcome.OUTCOME_NONE_CLARIFICATION,
    "OUTCOME_OK": Outcome.OUTCOME_OK,
    "OUTCOME_DENIED_SECURITY": Outcome.OUTCOME_DENIED_SECURITY,
    "OUTCOME_NONE_CLARIFICATION": Outcome.OUTCOME_NONE_CLARIFICATION,
    "OUTCOME_NONE_UNSUPPORTED": Outcome.OUTCOME_NONE_UNSUPPORTED,
    "OUTCOME_ERR_INTERNAL": Outcome.OUTCOME_ERR_INTERNAL,
}

_FIND_TYPE = {"all": 0, "files": 1, "dirs": 2}


class PcmRuntime:
    """Adapter for the PCM pac1 runtime."""

    runtime_type = "pcm"
    extra_tools = frozenset({"find", "mkdir", "move"})

    def __init__(self, vm: PcmRuntimeClientSync) -> None:
        self._vm = vm

    def tree(self, path: str, level: int = 0) -> Any:
        return self._vm.tree(TreeRequest(root=path, level=level))

    def list_dir(self, path: str) -> Any:
        return self._vm.list(PcmListRequest(name=path))

    def read(self, path: str, number: bool = False, start_line: int = 0, end_line: int = 0) -> Any:
        return self._vm.read(PcmReadRequest(path=path, number=number, start_line=start_line, end_line=end_line))

    def write(self, path: str, content: str, start_line: int = 0, end_line: int = 0) -> Any:
        return self._vm.write(PcmWriteRequest(path=path, content=content, start_line=start_line, end_line=end_line))

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
