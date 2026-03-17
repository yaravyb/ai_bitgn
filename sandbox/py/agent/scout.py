"""Scout phase: reactive DAG-based workspace discovery.

Imports from dag, dispatch, and tracker only (no LLM, no prompt, no skills).
Drives a deterministic (LLM-free) exploration of the workspace using
dispatch_tool for VM operations and a reactive TaskGraph.
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from agent.dag import Task, TaskGraph, TaskStatus, TaskType
from agent.dispatch import dispatch_tool
from agent.tracker import GroundingTracker

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Meta-file detection patterns (design section 5.2)
# ---------------------------------------------------------------------------

META_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^_rules\..*$", re.IGNORECASE),
    re.compile(r"^rules\..*$", re.IGNORECASE),
    re.compile(r"^skill-.*\..*$", re.IGNORECASE),
    re.compile(r"^_config\..*$", re.IGNORECASE),
    re.compile(r"^_meta\..*$", re.IGNORECASE),
    re.compile(r"^agents\..*$", re.IGNORECASE),
    re.compile(r"^readme\..*$", re.IGNORECASE),
    re.compile(r".*\.rules$", re.IGNORECASE),
    # Catch files with policy/rules/config anywhere in the name
    re.compile(r".*policy.*\..*$", re.IGNORECASE),
    re.compile(r".*rules.*\..*$", re.IGNORECASE),
    re.compile(r".*config.*\..*$", re.IGNORECASE),
]

# Regex for detecting numbered files: prefix + number + extension
_NUMBERED_FILE_RE = re.compile(r"^(.+?)(\d+)(\.\w+)$")

# Redirect patterns in read content
# Handles: "See CLAUDE.MD", "See 'CLAUDE.MD'", 'See "CLAUDE.MD"', "refer to README.md"
_REDIRECT_RE = re.compile(
    r"(?:see|refer to|check|read)\s+['\"`]?(\S+\.(?:md|txt))['\"`]?",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ScoutSummary:
    """Summary returned by the scout phase, injected into executor context.

    All fields are plain Python types (no protobuf or LLM dependency).
    """

    directory_tree: str = ""
    policy_files: dict[str, str] = field(default_factory=dict)
    vault_skills: dict[str, str] = field(default_factory=dict)
    files_read: set[str] = field(default_factory=set)
    folders_explored: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def is_meta_file(filename: str) -> bool:
    """Check if a filename matches any meta-file pattern (case-insensitive)."""
    return any(p.match(filename) for p in META_PATTERNS)


def detect_numbered_files(filenames: list[str]) -> dict[str, str]:
    """Detect groups of numbered files and return the highest in each group.

    Groups files by (prefix, extension). If a group has 3+ members with
    numeric suffixes, returns {group_key: highest_filename}.

    Returns:
        dict mapping group key to the highest-numbered filename.
    """
    groups: dict[tuple[str, str], list[tuple[int, str]]] = {}

    for fname in filenames:
        m = _NUMBERED_FILE_RE.match(fname)
        if not m:
            continue
        prefix = m.group(1)
        number = int(m.group(2))
        ext = m.group(3)
        key = (prefix, ext)
        if key not in groups:
            groups[key] = []
        groups[key].append((number, fname))

    result: dict[str, str] = {}
    for key, members in groups.items():
        if len(members) >= 3:
            members.sort(key=lambda x: x[0])
            highest_fname = members[-1][1]
            group_key = f"{key[0]}*{key[1]}"
            result[group_key] = highest_fname

    return result


# ---------------------------------------------------------------------------
# Internal collector for accumulating results during exploration
# ---------------------------------------------------------------------------

class _ScoutCollector:
    """Mutable accumulator for scout results during wave execution."""

    def __init__(self) -> None:
        self.directory_tree: str = ""
        self.policy_files: dict[str, str] = {}
        self.vault_skills: dict[str, str] = {}
        self.files_read: set[str] = set()
        self.folders_explored: list[str] = []


# ---------------------------------------------------------------------------
# Reactor rules (deterministic, no LLM)
# ---------------------------------------------------------------------------

def _react_tree(
    task: Task,
    result_json: str,
    graph: TaskGraph,
    collector: _ScoutCollector,
) -> None:
    """React to a completed tree task: spawn reads and lists."""
    try:
        data = json.loads(result_json)
    except (json.JSONDecodeError, TypeError):
        return

    collector.directory_tree = result_json

    # OutlineResponse format: {"path": "/", "folders": ["dir1", ...], "files": [{"path": "f.md", "headers": [...]}]}
    folders: list[str] = data.get("folders", [])
    raw_files = data.get("files", [])
    files: list[str] = []
    for f in raw_files:
        if isinstance(f, dict):
            files.append(f.get("path", ""))
        else:
            files.append(str(f))

    # Spawn read for all root-level text files (AGENTS.MD, README.MD, etc.)
    # Root files are likely policy/config files and should be read during scout
    for f in files:
        ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
        if ext in ("md", "txt"):
            tid = graph.add(Task(
                id="",
                type=TaskType.READ,
                args={"path": f"/{f}"},
                parent_id=task.id,
                spawn_reason=f"tree found root file {f}",
            ))
            log.debug("Spawned read(%s) from %s: tree found root file", tid, task.id)

    # Spawn list for each top-level folder
    for folder in folders:
        tid = graph.add(Task(
            id="",
            type=TaskType.LIST,
            args={"path": f"/{folder}"},
            parent_id=task.id,
            spawn_reason=f"tree found folder /{folder}",
        ))
        collector.folders_explored.append(folder)
        log.debug("Spawned list(%s) from %s: tree found folder /%s", tid, task.id, folder)


def _react_list(
    task: Task,
    result_json: str,
    graph: TaskGraph,
    collector: _ScoutCollector,
) -> None:
    """React to a completed list task: spawn reads for meta-files, lists for subfolders."""
    try:
        data = json.loads(result_json)
    except (json.JSONDecodeError, TypeError):
        return

    parent_path = task.args.get("path", "/")

    # ListResponse format: {"folders": ["dir1", ...], "files": ["file1.md", ...]}
    folders: list[str] = data.get("folders", [])
    files: list[str] = data.get("files", [])

    # Detect numbered file groups
    numbered = detect_numbered_files(files)
    numbered_highest = set(numbered.values())

    # Build set of all files that belong to a numbered group
    numbered_group_members: set[str] = set()
    for fname in files:
        m = _NUMBERED_FILE_RE.match(fname)
        if m:
            prefix = m.group(1)
            ext = m.group(3)
            key = f"{prefix}*{ext}"
            if key in numbered:
                numbered_group_members.add(fname)

    for f in files:
        file_path = f"{parent_path.rstrip('/')}/{f}"

        if is_meta_file(f):
            # Always read meta-files
            tid = graph.add(Task(
                id="",
                type=TaskType.READ,
                args={"path": file_path},
                parent_id=task.id,
                spawn_reason=f"meta-file detected: {f}",
            ))
            log.debug("Spawned read(%s) from %s: meta-file %s", tid, task.id, f)
        elif f in numbered_highest:
            # Highest numbered file in a group
            tid = graph.add(Task(
                id="",
                type=TaskType.READ,
                args={"path": file_path},
                parent_id=task.id,
                spawn_reason=f"highest numbered file in group: {f}",
            ))
            log.debug(
                "Spawned read(%s) from %s: highest numbered %s", tid, task.id, f,
            )
        elif f in numbered_group_members:
            # Skip non-highest members of numbered groups
            log.debug("Skipping %s (member of numbered group, not highest)", f)

    # Spawn list for subfolders
    for folder in folders:
        folder_path = f"{parent_path.rstrip('/')}/{folder}"
        tid = graph.add(Task(
            id="",
            type=TaskType.LIST,
            args={"path": folder_path},
            parent_id=task.id,
            spawn_reason=f"subfolder found: {folder}",
        ))
        log.debug("Spawned list(%s) from %s: subfolder %s", tid, task.id, folder)


def _react_read(
    task: Task,
    result_json: str,
    graph: TaskGraph,
    collector: _ScoutCollector,
) -> None:
    """React to a completed read task: detect redirects, classify content."""
    try:
        data = json.loads(result_json)
    except (json.JSONDecodeError, TypeError):
        return

    file_path = task.args.get("path", "")
    content = data.get("content", "")

    # Classify the file
    filename = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path
    is_skill = filename.lower().startswith("skill-")
    is_meta = is_meta_file(filename)
    # Redirect targets of policy files are also policy files
    is_redirect_target = task.spawn_reason is not None and "redirect" in task.spawn_reason.lower()
    # Root-level files read by the tree reactor are potential policy files
    is_root_file = file_path.lstrip("/").count("/") == 0

    if is_meta or is_redirect_target or is_root_file:
        collector.policy_files[file_path.lstrip("/")] = content
    if is_skill:
        collector.vault_skills[file_path.lstrip("/")] = content

    collector.files_read.add(file_path.lstrip("/"))

    # Detect redirects in content
    if content:
        redirect_match = _REDIRECT_RE.search(content)
        if redirect_match:
            target = redirect_match.group(1).strip("'\"` ")
            if not target.startswith("/"):
                target_path = f"/{target}"
            else:
                target_path = target

            try:
                tid = graph.add(Task(
                    id="",
                    type=TaskType.READ,
                    args={"path": target_path},
                    parent_id=task.id,
                    spawn_reason=(
                        f"redirect from {file_path}: "
                        f"'{redirect_match.group(0).strip()}'"
                    ),
                ))
                log.debug(
                    "Spawned read(%s) from %s: redirect to %s",
                    tid, task.id, target_path,
                )
            except ValueError:
                pass


# ---------------------------------------------------------------------------
# Reactor dispatch table
# ---------------------------------------------------------------------------

_REACTORS = {
    TaskType.TREE: _react_tree,
    TaskType.LIST: _react_list,
    TaskType.READ: _react_read,
}


# ---------------------------------------------------------------------------
# Tool name mapping
# ---------------------------------------------------------------------------

def _tool_name(task_type: TaskType) -> str:
    """Map a DAG TaskType to the dispatch tool name."""
    if task_type == TaskType.LIST:
        return "list_dir"
    if task_type == TaskType.READ:
        return "read_file"
    if task_type == TaskType.TREE:
        return "tree"
    return task_type.value


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_scout(
    vm: Any,
    tracker: GroundingTracker,
) -> ScoutSummary:
    """Run the LLM-free scout phase to discover workspace contents.

    Creates a TaskGraph, seeds it with tree("/"), runs waves until
    no pending tasks remain, and returns a ScoutSummary.

    Args:
        vm: MiniRuntimeClientSync instance for VM operations.
        tracker: GroundingTracker to record all files read.

    Returns:
        ScoutSummary with directory tree, policy files, vault skills,
        files read, and folders explored.
    """
    graph = TaskGraph()
    collector = _ScoutCollector()

    # Seed with tree root
    seed_id = graph.add(Task(
        id="tree-root",
        type=TaskType.TREE,
        args={"path": "/"},
        spawn_reason="seed: initial workspace tree",
    ))
    log.debug("Scout seeded with %s", seed_id)

    wave_number = 0
    protected_files: set[str] = set()

    while graph.has_pending():
        wave_number += 1
        ready = graph.ready_tasks()
        if not ready:
            print(f"  Scout wave {wave_number}: WARNING no ready tasks but pending exist. Breaking.")
            break

        # Log wave info
        task_descs = [f"{t.type.value}({t.args.get('path', '?')})" for t in ready]
        print(f"  Scout wave {wave_number}: {len(ready)} tasks [{', '.join(task_descs)}]")

        # Mark all ready tasks as running
        for t in ready:
            t.status = TaskStatus.RUNNING

        # Execute all ready tasks in parallel
        results: list[tuple[Task, str]] = []

        def _exec(task: Task) -> tuple[Task, str]:
            tool = _tool_name(task.type)
            result = dispatch_tool(
                vm, tool, task.args, tracker, protected_files,
            )
            return (task, result)

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(_exec, t) for t in ready]
            for future in futures:
                results.append(future.result())

        # Process results: complete tasks and run reactors
        for task, result_json in results:
            graph.complete(task.id, result_json)

            # Print result summary
            try:
                rd = json.loads(result_json)
                if task.type == TaskType.TREE:
                    folders = rd.get("folders", [])
                    raw_files = rd.get("files", [])
                    fnames = [f.get("path", f) if isinstance(f, dict) else f for f in raw_files]
                    print(f"    {task.type.value}({task.args.get('path','?')}) -> "
                          f"folders={folders}, files={fnames}")
                elif task.type == TaskType.LIST:
                    folders = rd.get("folders", [])
                    files = rd.get("files", [])
                    print(f"    {task.type.value}({task.args.get('path','?')}) -> "
                          f"folders={folders}, files={files}")
                elif task.type == TaskType.READ:
                    content = rd.get("content", "")
                    preview = content[:80].replace("\n", "\\n") + ("..." if len(content) > 80 else "")
                    print(f"    {task.type.value}({task.args.get('path','?')}) -> "
                          f"\"{preview}\"")
                else:
                    print(f"    {task.type.value}({task.args.get('path','?')}) -> OK")
            except Exception:
                preview = result_json[:80]
                print(f"    {task.type.value}({task.args.get('path','?')}) -> {preview}")

            reactor = _REACTORS.get(task.type)
            if reactor:
                before_count = len(graph.all_tasks())
                reactor(task, result_json, graph, collector)
                after_count = len(graph.all_tasks())
                spawned = after_count - before_count
                if spawned > 0:
                    # Show what was spawned
                    new_tasks = graph.all_tasks()[-spawned:]
                    for nt in new_tasks:
                        print(f"      -> spawned {nt.type.value}({nt.args.get('path','?')}) "
                              f"reason: {nt.spawn_reason}")

    print(f"  Scout done: {wave_number} waves, "
          f"{len(collector.files_read)} files read, "
          f"{len(collector.policy_files)} policy files, "
          f"{len(collector.vault_skills)} vault skills")

    return ScoutSummary(
        directory_tree=collector.directory_tree,
        policy_files=collector.policy_files,
        vault_skills=collector.vault_skills,
        files_read=collector.files_read | tracker.all(),
        folders_explored=collector.folders_explored,
    )
