"""Shared test fixtures.

Mocks the ``bitgn`` and ``connectrpc`` packages at import time so that the
``agent`` package can be imported without a working protobuf runtime.  The
bitgn SDK is compiled against a newer protobuf gencode version than the
runtime in the lockfile, which causes an ImportError during test collection.
"""

import sys
import types
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Pre-populate sys.modules with mocks for bitgn / connectrpc before any test
# file imports from the ``agent`` package (which triggers agent/__init__.py
# -> agent.loop -> bitgn.vm.mini_connect -> protobuf version check).
# ---------------------------------------------------------------------------

_bitgn_mock = MagicMock()

for _mod in [
    "bitgn",
    "bitgn.vm",
    "bitgn.vm.mini_connect",
    "bitgn.vm.mini_pb2",
    "bitgn.harness_connect",
    "bitgn.harness_pb2",
]:
    sys.modules.setdefault(_mod, _bitgn_mock)


# connectrpc.errors needs a real ConnectError exception class so that
# ``except ConnectError`` works in dispatch.py.
class _ConnectError(Exception):
    def __init__(self, *, code: str = "", message: str = ""):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


_connectrpc = types.ModuleType("connectrpc")
_connectrpc_errors = types.ModuleType("connectrpc.errors")
_connectrpc_errors.ConnectError = _ConnectError  # type: ignore[attr-defined]
_connectrpc.errors = _connectrpc_errors  # type: ignore[attr-defined]

sys.modules.setdefault("connectrpc", _connectrpc)
sys.modules.setdefault("connectrpc.errors", _connectrpc_errors)
