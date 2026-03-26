"""Tool dispatch: maps tool names to VM operations.

Imports from agent.tracker, agent.tools, and agent.llm (ToolCall type only).
Enforces protected files, tracks grounding, supports concurrent execution.
"""

from __future__ import annotations

import json
import logging
import os
import posixpath
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, NotRequired, TypedDict

from google.protobuf.json_format import MessageToDict
from connectrpc.errors import ConnectError

from agent.tracker import GroundingTracker
from agent.llm import ToolCall
from agent.context import ContextConfig, truncate_tool_result, COMPACT_SENTINEL

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Plan storage: local filesystem (host-side, not sandbox VM)
# ---------------------------------------------------------------------------

_plan_dir: str = ""


def init_plan_storage(run_id: str) -> None:
    """Initialise local plan directory for this agent run.

    Called once from ``run_agent()`` with the trace-id UUID.
    Plans are stored under ``/tmp/ai-bitgn-plans/<run_id>/`` so they
    never pollute the sandbox VM filesystem (which is scored by benchmarks).
    """
    global _plan_dir
    _plan_dir = os.path.join(tempfile.gettempdir(), "ai-bitgn-plans", run_id)
    os.makedirs(_plan_dir, exist_ok=True)


def get_plan_file_path() -> str:
    """Return the absolute path to the plan file on the host."""
    return os.path.join(_plan_dir, "steps.json")


class _PlanStep(TypedDict):
    index: int
    description: str
    status: str  # "pending" | "done" | "skipped"
    skip_reason: NotRequired[str]


class _PlanData(TypedDict):
    steps: list[_PlanStep]
    total: int
    completed: int
    skipped: int
    notes: NotRequired[list[str]]


def _read_plan() -> tuple[_PlanData | None, str | None]:
    """Read and parse the plan file from local storage.

    Returns (plan_data, None) on success, or (None, error_json) on failure.
    """
    plan_path = get_plan_file_path()
    if not os.path.isfile(plan_path):
        return (None, json.dumps({"error": "No plan exists. Call plan_create first."}, ensure_ascii=False))
    try:
        with open(plan_path, encoding="utf-8") as f:
            plan: _PlanData = json.load(f)
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        log.debug("Plan file read failed: %s", exc)
        return (None, json.dumps({"error": f"Plan file is corrupted: {exc}"}, ensure_ascii=False))
    return (plan, None)


def _format_plan_response(plan: _PlanData) -> str:
    """Format a plan data dict as an indented JSON string with summary."""
    actionable = plan["total"] - plan["skipped"]
    if plan["skipped"] > 0:
        summary = f"{plan['completed']}/{actionable} actionable steps completed, {plan['skipped']} skipped"
    else:
        summary = f"{plan['completed']}/{plan['total']} steps completed"
    plan["summary"] = summary  # type: ignore[typeddict-unknown-key]
    return json.dumps(plan, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Guard configuration dataclasses (frozen, thread-safe by immutability)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TemplateGuardConfig:
    """Configuration for the template deletion guard.

    When protected_directories is empty, the guard defaults to blocking
    all _-prefixed file deletions (backward compatibility).
    """
    protected_directories: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaskConstraints:
    """Structured task constraints extracted by LLM or regex fast-path.

    Immutable value object. Default values disable all constraint-based
    guards (fail-open).
    """
    source_file: str | None = None
    scope_level: str = "normal"            # "focused" | "normal"
    target_directories: tuple[str, ...] = ()


@dataclass(frozen=True)
class DispatchContext:
    """Immutable per-task guard configuration passed through dispatch calls.

    Constructed once per task by loop.py. Passed by reference to
    dispatch_tool() and dispatch_parallel(). Each concurrent thread
    reads from this frozen snapshot without mutation.
    """
    source_basename: str | None = None
    scope_constrained: bool = False
    target_directories: tuple[str, ...] = ()
    template_guard_config: TemplateGuardConfig = field(default_factory=TemplateGuardConfig)


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
    level = args.get("level", 0)
    resp = vm.tree(path, level=level)
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
    number = args.get("number", False)
    start_line = args.get("start_line", 0)
    end_line = args.get("end_line", 0)
    resp = vm.read(path, number=number, start_line=start_line, end_line=end_line)
    tracker.add(path)
    return json.dumps(MessageToDict(resp), ensure_ascii=False)


_SLUG_PREFIX_RE = re.compile(r"^(?:\d[\d\-]*__(?:\d+__)*)")


def _extract_slug(stem: str) -> str:
    """Extract the non-date, non-numeric slug from a filename stem.

    ``2026-03-23__0000__hn-foo`` → ``hn-foo``
    ``2026-03-23__hn-foo``       → ``hn-foo``
    ``report``                   → ``report``
    """
    return _SLUG_PREFIX_RE.sub("", stem)


def _is_basename_mismatch(source_basename: str, written_path: str) -> bool:
    """Detect if written file is a renamed derivative of the source.

    Returns True when the written file shares the source's slug but has
    extra segments inserted (e.g. ``__0000__``).  Returns False for exact
    matches or unrelated filenames.
    """
    written_bn = posixpath.basename(written_path)
    if written_bn == source_basename:
        return False
    src_stem = source_basename.rsplit(".", 1)[0]
    dst_stem = written_bn.rsplit(".", 1)[0]
    src_slug = _extract_slug(src_stem)
    dst_slug = _extract_slug(dst_stem)
    # Same slug but different full stem → segment was inserted
    if src_slug and src_slug == dst_slug and src_stem != dst_stem:
        return True
    return False


def _handle_write_file(
    vm,
    args: dict[str, Any],
    tracker: GroundingTracker,
    protected_files: set[str],
    skill_loader: Any | None,
) -> str:
    path = args.get("path", "")
    content = args.get("content", "")
    start_line = args.get("start_line", 0)
    end_line = args.get("end_line", 0)

    resp = vm.write(path, content, start_line=start_line, end_line=end_line)
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
# Plan tool handlers (persistent-task-planner)
# ---------------------------------------------------------------------------

def _handle_plan_create(
    vm,
    args: dict[str, Any],
    tracker: GroundingTracker,
    protected_files: set[str],
    skill_loader: Any | None,
) -> str:
    steps_input: list[str] = args.get("steps", [])
    if not steps_input:
        return json.dumps(
            {"error": "plan_create requires at least one step"},
            ensure_ascii=False,
        )
    steps: list[_PlanStep] = [
        {"index": i, "description": desc, "status": "pending"}
        for i, desc in enumerate(steps_input)
    ]
    plan: _PlanData = {
        "steps": steps,
        "total": len(steps),
        "completed": 0,
        "skipped": 0,
    }
    json_content = json.dumps(plan, indent=2, ensure_ascii=False)
    plan_path = get_plan_file_path()
    with open(plan_path, "w", encoding="utf-8") as f:
        f.write(json_content)
    log.info("plan_create: %d steps created", len(steps))
    return _format_plan_response(plan)


def _handle_plan_status(
    vm,
    args: dict[str, Any],
    tracker: GroundingTracker,
    protected_files: set[str],
    skill_loader: Any | None,
) -> str:
    plan, error = _read_plan()
    if plan is None:
        return json.dumps(
            {"message": "No plan has been created yet. Use plan_create to create one."},
            ensure_ascii=False,
        )
    log.info("plan_status: %d/%d steps completed", plan["completed"], plan["total"])
    return _format_plan_response(plan)


def _handle_plan_step_done(
    vm,
    args: dict[str, Any],
    tracker: GroundingTracker,
    protected_files: set[str],
    skill_loader: Any | None,
) -> str:
    raw = args.get("step_index", 0)
    # Accept single int or array of ints
    indices: list[int] = raw if isinstance(raw, list) else [raw]
    plan, error = _read_plan()
    if plan is None:
        return error  # type: ignore[return-value]
    for idx in indices:
        if idx < 0 or idx >= plan["total"]:
            return json.dumps(
                {"error": f"step_index {idx} is out of range. Valid range: 0 to {plan['total'] - 1}."},
                ensure_ascii=False,
            )
    for idx in indices:
        plan["steps"][idx]["status"] = "done"
        plan["steps"][idx].pop("skip_reason", None)
    # Recompute counts
    plan["completed"] = sum(1 for s in plan["steps"] if s["status"] == "done")
    plan["skipped"] = sum(1 for s in plan["steps"] if s["status"] == "skipped")
    # Preserve notes if present
    notes = plan.get("notes", [])  # type: ignore[assignment]
    write_data: dict[str, Any] = {
        "steps": plan["steps"], "total": plan["total"],
        "completed": plan["completed"], "skipped": plan["skipped"],
    }
    if notes:
        write_data["notes"] = notes
    json_content = json.dumps(write_data, indent=2, ensure_ascii=False)
    plan_path = get_plan_file_path()
    with open(plan_path, "w", encoding="utf-8") as f:
        f.write(json_content)
    log.info("plan_step_done: marked %d steps done (%d/%d completed)", len(indices), plan["completed"], plan["total"])
    return _format_plan_response(plan)


def _handle_plan_step_skip(
    vm,
    args: dict[str, Any],
    tracker: GroundingTracker,
    protected_files: set[str],
    skill_loader: Any | None,
) -> str:
    step_index: int = args.get("step_index", 0)
    reason: str = args.get("reason", "")
    plan, error = _read_plan()
    if plan is None:
        return error  # type: ignore[return-value]
    if step_index < 0 or step_index >= plan["total"]:
        return json.dumps(
            {"error": f"step_index {step_index} is out of range. Valid range: 0 to {plan['total'] - 1}."},
            ensure_ascii=False,
        )
    plan["steps"][step_index]["status"] = "skipped"
    if reason:
        plan["steps"][step_index]["skip_reason"] = reason
    # Recompute counts
    plan["completed"] = sum(1 for s in plan["steps"] if s["status"] == "done")
    plan["skipped"] = sum(1 for s in plan["steps"] if s["status"] == "skipped")
    notes = plan.get("notes", [])  # type: ignore[assignment]
    write_data: dict[str, Any] = {
        "steps": plan["steps"], "total": plan["total"],
        "completed": plan["completed"], "skipped": plan["skipped"],
    }
    if notes:
        write_data["notes"] = notes
    json_content = json.dumps(write_data, indent=2, ensure_ascii=False)
    plan_path = get_plan_file_path()
    with open(plan_path, "w", encoding="utf-8") as f:
        f.write(json_content)
    desc = plan["steps"][step_index]["description"]
    log.info("plan_step_skip: step %d '%s' skipped (%d/%d completed, %d skipped)", step_index, desc, plan["completed"], plan["total"], plan["skipped"])
    return _format_plan_response(plan)


def _handle_plan_note(
    vm,
    args: dict[str, Any],
    tracker: GroundingTracker,
    protected_files: set[str],
    skill_loader: Any | None,
) -> str:
    note: str = args.get("note", "").strip()
    if not note:
        return json.dumps({"error": "plan_note requires a non-empty note"}, ensure_ascii=False)
    plan_path = get_plan_file_path()
    if os.path.isfile(plan_path):
        with open(plan_path, encoding="utf-8") as f:
            plan: _PlanData = json.load(f)
    else:
        # Allow notes even without a plan — create a minimal plan structure
        plan = {"steps": [], "total": 0, "completed": 0, "skipped": 0, "notes": []}
    notes: list[str] = plan.get("notes", [])  # type: ignore[assignment]
    notes.append(note)
    plan["notes"] = notes  # type: ignore[typeddict-unknown-key]
    json_content = json.dumps(plan, indent=2, ensure_ascii=False)
    with open(plan_path, "w", encoding="utf-8") as f:
        f.write(json_content)
    log.info("plan_note: saved note (%d notes total)", len(notes))
    return json.dumps({"saved": note, "total_notes": len(notes)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Guard functions (standalone, pure, testable -- called by dispatch_tool)
# ---------------------------------------------------------------------------

def _check_basename_guard(
    dispatch_ctx: DispatchContext,
    path: str,
) -> str | None:
    """Return error message if basename mismatch detected, else None.

    Reads source_basename from dispatch_ctx. When no source_basename is
    configured, the guard is inactive (returns None).
    """
    source_basename = dispatch_ctx.source_basename
    if not source_basename:
        log.debug("basename guard: ALLOW %s (no source_basename set)", path)
        return None
    if _is_basename_mismatch(source_basename, path):
        expected = source_basename
        actual = posixpath.basename(path)
        log.warning(
            "basename guard: BLOCK %s (mismatch: expected %s, got %s)",
            path, expected, actual,
        )
        return (
            f"Filename mismatch: expected basename '{expected}', got '{actual}'. "
            f"Use the exact source filename."
        )
    log.debug("basename guard: ALLOW %s (matches source %s)", path, source_basename)
    return None


def _check_scope_guard(
    dispatch_ctx: DispatchContext,
    path: str,
    tracker: GroundingTracker,
) -> str | None:
    """Return error message if scope-constrained write is blocked, else None.

    Implements intent-aware five-step decision logic:
    1. Not constrained -> allow
    2. File not previously read -> allow (new file creation)
    3. Target in allowed directories -> allow
    4. Basename matches source_basename -> allow
    5. Block
    """
    # Step 1: Not constrained -> allow
    if not dispatch_ctx.scope_constrained:
        log.debug("scope guard: ALLOW %s (scope not constrained)", path)
        return None

    # Step 2: File not previously read -> allow
    if not tracker.contains(path):
        log.debug("scope guard: ALLOW %s (file not previously read)", path)
        return None

    # Step 3: Target in allowed directories -> allow
    normalized = _normalize_path(path)
    for target_dir in dispatch_ctx.target_directories:
        normalized_target = _normalize_path(target_dir)
        if normalized.startswith(normalized_target):
            log.debug(
                "scope guard: ALLOW %s (target in allowed directory %s)",
                path, target_dir,
            )
            return None

    # Step 4: Basename matches source_basename -> allow
    if dispatch_ctx.source_basename:
        if posixpath.basename(path) == dispatch_ctx.source_basename:
            log.debug(
                "scope guard: ALLOW %s (basename matches source %s)",
                path, dispatch_ctx.source_basename,
            )
            return None

    # Step 5: Block
    log.warning(
        "scope guard: BLOCK %s (scope constrained, file was already read, "
        "no target match, source_basename=%s, target_dirs=%s)",
        path, dispatch_ctx.source_basename, dispatch_ctx.target_directories,
    )
    return (
        f"Scope constraint: modifying '{path}' blocked. "
        f"The file was read for context and is not in the task's allowed targets. "
        f"Only create new files or modify files in target directories."
    )


def _check_template_guard(
    dispatch_ctx: DispatchContext,
    path: str,
) -> str | None:
    """Return error message if template deletion is blocked, else None.

    Configurable directory-scoped behavior:
    1. If basename does not start with '_': ALLOW
    2. If protected_directories is empty: BLOCK (backward compat default)
    3. If file path is inside any protected_directory: BLOCK
    4. Otherwise: ALLOW (not in protected scope)
    """
    basename = posixpath.basename(path)

    # Step 1: Non-prefixed file -> always allowed
    if not basename.startswith("_"):
        log.debug("template guard: ALLOW %s (no underscore prefix)", path)
        return None

    protected_dirs = dispatch_ctx.template_guard_config.protected_directories

    # Step 2: Empty protected_directories -> block all _-prefixed (backward compat)
    if not protected_dirs:
        log.warning(
            "template guard: BLOCK %s (underscore-prefixed, no protected_dirs configured)",
            path,
        )
        return (
            f"Cannot delete template file: {path}. "
            f"Files prefixed with '_' are structural, not captured content."
        )

    # Step 3: Check if file is inside any protected directory
    normalized = _normalize_path(path)
    for pdir in protected_dirs:
        normalized_pdir = _normalize_path(pdir)
        if normalized.startswith(normalized_pdir):
            log.warning(
                "template guard: BLOCK %s (underscore-prefixed, inside protected dir %s)",
                path, pdir,
            )
            return (
                f"Cannot delete template file: {path}. "
                f"Files prefixed with '_' inside '{pdir}' are structural."
            )

    # Step 4: Not in any protected directory -> allow
    log.debug(
        "template guard: ALLOW %s (underscore-prefixed but outside protected dirs %s)",
        path, protected_dirs,
    )
    return None


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
    "plan_create": _handle_plan_create,
    "plan_step_done": _handle_plan_step_done,
    "plan_step_skip": _handle_plan_step_skip,
    "plan_status": _handle_plan_status,
    "plan_note": _handle_plan_note,
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
    dispatch_ctx: DispatchContext | None = None,
) -> str:
    """Dispatch a single tool call and return the result as a JSON string.

    When context_config is provided, tool results (except report_completion)
    are truncated if they exceed the configured limit.

    When dispatch_ctx is provided, guard functions are executed as pre-dispatch
    checks for write_file and delete_file operations. When None, guards that
    depend on context data are disabled (backward-compatible default).

    Returns error JSON if the tool_name is not recognized.
    """
    # Pre-dispatch guard checks (only when dispatch_ctx is provided)
    # NOTE: Only safety-invariant guards are applied programmatically.
    # Behavioral decisions (scope, filenames) are left to the LLM + skills.
    if dispatch_ctx is not None:
        if tool_name == "delete_file":
            path = args.get("path", "")
            error = _check_template_guard(dispatch_ctx, path)
            if error:
                return json.dumps({"error": error}, ensure_ascii=False)

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
    dispatch_ctx: DispatchContext | None = None,
) -> list[tuple[str, str]]:
    """Execute multiple tool calls concurrently.

    The frozen dispatch_ctx instance is shared across all concurrent
    dispatch_tool invocations without mutation, ensuring thread safety.

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
            dispatch_ctx=dispatch_ctx,
        )
        return (tc.id, result)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_execute, tc) for tc in tool_calls]
        for future in futures:
            results.append(future.result())

    return results
