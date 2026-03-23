"""Tool dispatch: maps tool names to VM operations.

Imports from agent.tracker, agent.tools, and agent.llm (ToolCall type only).
Enforces protected files, tracks grounding, supports concurrent execution.
"""

from __future__ import annotations

import json
import logging
import posixpath
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from google.protobuf.json_format import MessageToDict
from connectrpc.errors import ConnectError

from agent.tracker import GroundingTracker
from agent.llm import ToolCall
from agent.context import ContextConfig, truncate_tool_result, COMPACT_SENTINEL

log = logging.getLogger(__name__)


def _normalize_path(path: str) -> str:
    """Normalize a file path for protected-file comparison.

    - Strip leading '/'
    - Resolve '..' segments via posixpath.normpath
    - Lowercase for comparison
    """
    stripped = path.lstrip("/")
    normalized = posixpath.normpath(stripped)
    return normalized.lower()


# ---------------------------------------------------------------------------
# Handler functions: each takes (vm, args, tracker, protected_files, skill_loader)
# and returns a JSON string result.
# ---------------------------------------------------------------------------

def _handle_tree(
    vm,
    args: dict[str, Any],
    tracker: GroundingTracker,
    protected_files: set[str],
    skill_loader: Any | None,
) -> str:
    path = args.get("path", "/")
    resp = vm.tree(path)
    # tree is a directory operation, not a file read — do not add to tracker
    return json.dumps(MessageToDict(resp), ensure_ascii=False)


def _handle_list_dir(
    vm,
    args: dict[str, Any],
    tracker: GroundingTracker,
    protected_files: set[str],
    skill_loader: Any | None,
) -> str:
    path = args.get("path", "/")
    resp = vm.list_dir(path)
    return json.dumps(MessageToDict(resp), ensure_ascii=False)


def _handle_read_file(
    vm,
    args: dict[str, Any],
    tracker: GroundingTracker,
    protected_files: set[str],
    skill_loader: Any | None,
) -> str:
    path = args.get("path", "")
    resp = vm.read(path)
    tracker.add(path)
    return json.dumps(MessageToDict(resp), ensure_ascii=False)


def _handle_write_file(
    vm,
    args: dict[str, Any],
    tracker: GroundingTracker,
    protected_files: set[str],
    skill_loader: Any | None,
) -> str:
    path = args.get("path", "")
    content = args.get("content", "")
    resp = vm.write(path, content)
    return json.dumps(MessageToDict(resp), ensure_ascii=False)


def _handle_delete_file(
    vm,
    args: dict[str, Any],
    tracker: GroundingTracker,
    protected_files: set[str],
    skill_loader: Any | None,
) -> str:
    path = args.get("path", "")
    normalized = _normalize_path(path)

    if normalized in protected_files:
        log.warning("REFUSED: delete %s (protected policy file)", path)
        return json.dumps(
            {"error": f"Cannot delete protected file: {path}"},
            ensure_ascii=False,
        )

    resp = vm.delete(path)
    return json.dumps(MessageToDict(resp), ensure_ascii=False)


def _handle_search(
    vm,
    args: dict[str, Any],
    tracker: GroundingTracker,
    protected_files: set[str],
    skill_loader: Any | None,
) -> str:
    pattern = args.get("pattern", "")
    path = args.get("path", "/")
    count = args.get("count", 5)
    resp = vm.search(path, pattern, count)
    return json.dumps(MessageToDict(resp), ensure_ascii=False)


def _handle_report_completion(
    vm,
    args: dict[str, Any],
    tracker: GroundingTracker,
    protected_files: set[str],
    skill_loader: Any | None,
) -> str:
    answer = args.get("answer", "")
    llm_refs = args.get("grounding_refs", [])
    code = args.get("code", "completed")
    # Trust the LLM's refs when provided; fall back to tracker only when empty
    if llm_refs:
        refs = llm_refs
    else:
        refs = tracker.merge([])
    resp = vm.answer(answer, refs, code)
    return json.dumps(MessageToDict(resp), ensure_ascii=False)


def _handle_find(
    vm,
    args: dict[str, Any],
    tracker: GroundingTracker,
    protected_files: set[str],
    skill_loader: Any | None,
) -> str:
    root = args.get("root", "/")
    name = args.get("name", "")
    kind = args.get("kind", "all")
    limit = args.get("limit", 10)
    resp = vm.find(root, name, kind, limit)
    return json.dumps(MessageToDict(resp), ensure_ascii=False)


def _handle_mkdir(
    vm,
    args: dict[str, Any],
    tracker: GroundingTracker,
    protected_files: set[str],
    skill_loader: Any | None,
) -> str:
    path = args.get("path", "")
    resp = vm.mkdir(path)
    return json.dumps(MessageToDict(resp), ensure_ascii=False)


def _handle_move(
    vm,
    args: dict[str, Any],
    tracker: GroundingTracker,
    protected_files: set[str],
    skill_loader: Any | None,
) -> str:
    from_name = args.get("from_name", "")
    to_name = args.get("to_name", "")
    normalized_from = _normalize_path(from_name)
    if normalized_from in protected_files:
        log.warning("REFUSED: move %s (protected policy file)", from_name)
        return json.dumps(
            {"error": f"Cannot move protected file: {from_name}"},
            ensure_ascii=False,
        )
    resp = vm.move(from_name, to_name)
    return json.dumps(MessageToDict(resp), ensure_ascii=False)


def _handle_load_skill(
    vm,
    args: dict[str, Any],
    tracker: GroundingTracker,
    protected_files: set[str],
    skill_loader: Any | None,
) -> str:
    name = args.get("name", "")
    if skill_loader is None:
        return json.dumps(
            {"error": "No skill loader available. Skills are not configured."},
            ensure_ascii=False,
        )
    content = skill_loader.get_content(name)
    return content


def _handle_compact(
    vm,
    args: dict[str, Any],
    tracker: GroundingTracker,
    protected_files: set[str],
    skill_loader: Any | None,
) -> str:
    """Return the compact sentinel. Actual compaction logic lives in loop.py."""
    return COMPACT_SENTINEL


# ---------------------------------------------------------------------------
# Dispatch map: tool name -> handler (Req 12.2)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Public dispatch functions
# ---------------------------------------------------------------------------

def dispatch_tool(
    vm,
    tool_name: str,
    args: dict[str, Any],
    tracker: GroundingTracker,
    protected_files: set[str],
    skill_loader: Any | None = None,
    context_config: ContextConfig | None = None,
) -> str:
    """Dispatch a single tool call and return the result as a JSON string.

    When context_config is provided, tool results (except report_completion)
    are truncated if they exceed the configured limit.

    Returns error JSON if the tool_name is not recognized.
    """
    handler = DISPATCH_MAP.get(tool_name)
    if handler is None:
        log.warning("Unknown tool: %s", tool_name)
        return json.dumps(
            {"error": f"Unknown tool: {tool_name}"},
            ensure_ascii=False,
        )

    try:
        result = handler(vm, args, tracker, protected_files, skill_loader)
    except ConnectError as exc:
        log.warning("Tool %s error: %s %s", tool_name, exc.code, exc.message)
        return json.dumps(
            {"error": f"{exc.code}: {exc.message}"},
            ensure_ascii=False,
        )

    # Apply truncation when context_config is provided and tool is not exempt
    if context_config is not None and tool_name != "report_completion":
        original_len = len(result)
        result = truncate_tool_result(result, context_config)
        if len(result) < original_len:
            log.debug(
                "Tool %s result truncated: %d -> %d chars",
                tool_name, original_len, len(result),
            )
            print(f"  [truncated] {tool_name}: {original_len} -> {len(result)} chars")

    return result


def dispatch_parallel(
    vm,
    tool_calls: list[ToolCall],
    tracker: GroundingTracker,
    protected_files: set[str],
    skill_loader: Any | None = None,
    max_workers: int = 4,
    context_config: ContextConfig | None = None,
) -> list[tuple[str, str]]:
    """Execute multiple tool calls concurrently.

    Returns a list of (tool_call_id, result_json) tuples.
    """
    if not tool_calls:
        return []

    results: list[tuple[str, str]] = []

    def _execute(tc: ToolCall) -> tuple[str, str]:
        result = dispatch_tool(
            vm, tc.name, tc.arguments,
            tracker, protected_files, skill_loader,
            context_config=context_config,
        )
        return (tc.id, result)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_execute, tc) for tc in tool_calls]
        for future in futures:
            results.append(future.result())

    return results
