"""Scout phase: two-phase LLM-driven workspace discovery.

Phase 1 (Deterministic Bootstrap): tree("/") + read root meta-files.
Phase 2 (LLM Explorer): tool-use loop using call_llm + dispatch_parallel.

Imports from llm, dispatch, tracker, tools, prompt, and context.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from agent.dispatch import dispatch_tool, dispatch_parallel
from agent.llm import call_llm
from agent.prompt import build_scout_prompt
from agent.tools import SCOUT_TOOL_SCHEMAS
from agent.tracker import GroundingTracker
from agent.context import ContextConfig, micro_compact

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Meta-file detection patterns (retained from original)
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

# Redirect patterns in read content (retained)
_REDIRECT_RE = re.compile(
    r"(?:see|refer to|check|read)\s+['\"`]?(\S+\.(?:md|txt))['\"`]?",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

def _default_tree_level() -> int:
    """Read SCOUT_TREE_LEVEL env var at instance creation time, default 3."""
    return int(os.environ.get("SCOUT_TREE_LEVEL", "3"))


@dataclass
class ScoutConfig:
    """Configuration for the two-phase scout. Extended with tree_level."""

    model: str                  # Required: LiteLLM model identifier for scout LLM
    task_instruction: str       # Required: user's task text for task-aware exploration
    max_steps: int = 20        # Maximum LLM call rounds in Phase 2
    max_workers: int = 4       # Thread pool size for parallel tool dispatch
    tree_level: int = field(default_factory=_default_tree_level)  # Configurable via SCOUT_TREE_LEVEL env var


@dataclass
class BootstrapContext:
    """Internal: results from Phase 1 deterministic bootstrap."""

    directory_tree: str                 # Raw JSON output from tree("/")
    root_policy_files: dict[str, str]   # path -> content for root .md/.txt files
    root_vault_skills: dict[str, str]   # path -> content for root skill-*.* files
    files_read: set[str]                # All files read during bootstrap
    folders_discovered: list[str]       # Top-level folders from tree output


@dataclass
class ScoutSummary:
    """Summary returned by the scout phase, injected into executor context.

    All fields are plain Python types (no protobuf or LLM dependency).
    """

    # Existing fields (backward-compatible)
    directory_tree: str = ""
    policy_files: dict[str, str] = field(default_factory=dict)
    vault_skills: dict[str, str] = field(default_factory=dict)
    files_read: set[str] = field(default_factory=set)
    folders_explored: list[str] = field(default_factory=list)

    # New additive fields
    llm_summary: str | None = None       # LLM's final structured text analysis
    mode: str = "llm"                    # Always "llm" in new architecture
    total_llm_steps: int = 0             # Number of LLM call rounds in Phase 2
    completed_fully: bool = False        # True if LLM returned text naturally


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def is_meta_file(filename: str) -> bool:
    """Check if a filename matches any meta-file pattern (case-insensitive)."""
    return any(p.match(filename) for p in META_PATTERNS)


def _build_scout_context_config(context_config: ContextConfig | None) -> ContextConfig:
    """Build a scout-specific ContextConfig with independently tunable values.

    Scout uses separate environment variables for micro-compact settings,
    defaulting to keep_batches=2 (shorter conversations).
    """
    if context_config is None:
        return ContextConfig()

    return ContextConfig(
        truncation_limit=context_config.truncation_limit,
        micro_compact_keep_batches=int(
            os.environ.get("CTX_SCOUT_MICRO_COMPACT_KEEP_BATCHES", "2")
        ),
        micro_compact_min_length=int(
            os.environ.get("CTX_SCOUT_MICRO_COMPACT_MIN_LENGTH",
                           str(context_config.micro_compact_min_length))
        ),
        auto_compact_threshold=context_config.auto_compact_threshold,
        transcript_dir=context_config.transcript_dir,
    )


# ---------------------------------------------------------------------------
# Phase 1: Deterministic Bootstrap
# ---------------------------------------------------------------------------

def _run_bootstrap(
    vm: Any,
    tracker: GroundingTracker,
    protected_files: set[str],
    context_config: ContextConfig | None = None,
    config: ScoutConfig | None = None,
) -> BootstrapContext:
    """Phase 1: tree("/") + read root-level text files.

    Args:
        vm: MiniRuntimeClientSync instance.
        tracker: GroundingTracker to record files read.
        protected_files: Set of protected file paths.
        context_config: Optional context config for tool result truncation.
        config: Optional ScoutConfig for tree_level and other settings.

    Returns:
        BootstrapContext with directory tree, root files, and folder list.
    """
    # Step 1: Get depth-limited directory tree (SDK v2: configurable tree_level)
    tree_level = config.tree_level if config is not None else 3
    tree_result = dispatch_tool(
        vm, "tree", {"path": "/", "level": tree_level}, tracker, protected_files,
        context_config=context_config,
    )

    directory_tree = tree_result
    folders_discovered: list[str] = []
    root_files: list[str] = []

    try:
        data = json.loads(tree_result)
        folders_discovered = data.get("folders", [])
        raw_files = data.get("files", [])
        for f in raw_files:
            if isinstance(f, dict):
                root_files.append(f.get("path", ""))
            else:
                root_files.append(str(f))
    except (json.JSONDecodeError, TypeError):
        log.warning("Failed to parse tree response, proceeding with empty bootstrap")

    # Step 2: Read root-level .md and .txt files
    root_policy_files: dict[str, str] = {}
    root_vault_skills: dict[str, str] = {}
    files_read: set[str] = set()

    for filename in root_files:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ("md", "txt"):
            continue

        file_path = f"/{filename}"
        read_result = dispatch_tool(
            vm, "read_file", {"path": file_path}, tracker, protected_files,
            context_config=context_config,
        )

        try:
            read_data = json.loads(read_result)
            content = read_data.get("content", "")
        except (json.JSONDecodeError, TypeError):
            content = ""

        files_read.add(filename)

        # Classify
        basename = filename.rsplit("/", 1)[-1] if "/" in filename else filename
        if basename.lower().startswith("skill-"):
            root_vault_skills[filename] = content
        if is_meta_file(basename):
            root_policy_files[filename] = content

    log.debug(
        "Bootstrap: %d folders, %d policy files, %d vault skills",
        len(folders_discovered), len(root_policy_files), len(root_vault_skills),
    )

    return BootstrapContext(
        directory_tree=directory_tree,
        root_policy_files=root_policy_files,
        root_vault_skills=root_vault_skills,
        files_read=files_read,
        folders_discovered=folders_discovered,
    )


def _format_bootstrap_for_prompt(ctx: BootstrapContext) -> str:
    """Format bootstrap context as a human-readable string for the scout prompt.

    Includes the directory tree and each root policy file's content.
    """
    parts: list[str] = []

    parts.append("## Directory Tree")
    parts.append(ctx.directory_tree)

    if ctx.root_policy_files:
        parts.append("\n## Root Policy Files")
        for path, content in sorted(ctx.root_policy_files.items()):
            parts.append(f"### {path}")
            parts.append(content)

    if ctx.root_vault_skills:
        parts.append("\n## Root Vault Skills")
        for path, content in sorted(ctx.root_vault_skills.items()):
            parts.append(f"### {path}")
            parts.append(content)

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Phase 2: LLM Explorer
# ---------------------------------------------------------------------------

def _run_llm_explorer(
    vm: Any,
    tracker: GroundingTracker,
    config: ScoutConfig,
    bootstrap: BootstrapContext,
    protected_files: set[str],
    context_config: ContextConfig | None = None,
) -> tuple[str | None, int, bool, list[tuple[str, str, str]], list[str]]:
    """Phase 2: LLM-driven exploration loop.

    Args:
        context_config: Optional context config. When provided, micro-compact
            is applied before each call_llm and truncation applies to tool results.
            Auto-compact is NOT applied in the scout phase.

    Returns:
        (llm_summary, total_steps, completed_fully, accumulated_reads, phase2_folders)
        where accumulated_reads is a list of (tool_name, file_path, result_json) tuples.
    """
    # Build scout-specific context config for micro-compact
    scout_ctx_config = _build_scout_context_config(context_config) if context_config else None

    # Build scout prompt
    formatted_context = _format_bootstrap_for_prompt(bootstrap)
    scout_prompt = build_scout_prompt(config.task_instruction, formatted_context)

    # Initialize messages (user message required by some providers like Bedrock)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": scout_prompt},
        {"role": "user", "content": "Begin workspace exploration."},
    ]

    # Scout-specific trace metadata
    trace_metadata = {
        "trace_id": str(uuid.uuid4()),
        "trace_name": "scout_llm_explorer",
        "session_id": os.environ.get("SESSION_ID", ""),
        "trace_metadata": {
            "model": config.model,
            "phase": "scout",
        },
    }

    llm_summary: str | None = None
    completed_fully = False
    total_steps = 0
    accumulated_reads: list[tuple[str, str, str]] = []
    phase2_folders: list[str] = []

    for step in range(config.max_steps):
        total_steps += 1

        # Micro-compact old tool results before each LLM call (no auto-compact)
        if scout_ctx_config is not None:
            micro_compact(messages, scout_ctx_config)

        response = call_llm(
            config.model,
            messages,
            tools=SCOUT_TOOL_SCHEMAS,
            metadata=trace_metadata,
        )

        # Build assistant message
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": response.content}
        if response.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "type": "function",
                    "id": tc.id,
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in response.tool_calls
            ]
        messages.append(assistant_msg)

        # Check for natural completion (text response, no tool calls)
        if not response.tool_calls:
            llm_summary = response.content
            completed_fully = True
            log.debug("Scout LLM completed naturally at step %d", total_steps)
            break

        # Track list_dir calls for folders_explored
        for tc in response.tool_calls:
            if tc.name == "list_dir":
                path = tc.arguments.get("path", "/")
                phase2_folders.append(path)

        # Dispatch tool calls (with truncation if context_config provided)
        results = dispatch_parallel(
            vm, response.tool_calls, tracker, protected_files,
            max_workers=config.max_workers,
            context_config=context_config,
        )

        # Accumulate read_file results for later classification
        for tc in response.tool_calls:
            if tc.name == "read_file":
                file_path = tc.arguments.get("path", "")
                # Find the matching result
                for result_id, result_json in results:
                    if result_id == tc.id:
                        accumulated_reads.append((tc.name, file_path, result_json))
                        break

        # Append tool result messages
        for tool_call_id, result_text in results:
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": result_text,
            })

    if not completed_fully:
        log.warning(
            "Scout LLM hit step limit (%d steps)", config.max_steps,
        )

    return (llm_summary, total_steps, completed_fully, accumulated_reads, phase2_folders)


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------

def _build_summary(
    bootstrap: BootstrapContext,
    tracker: GroundingTracker,
    llm_summary: str | None,
    total_steps: int,
    completed_fully: bool,
    accumulated_reads: list[tuple[str, str, str]],
    phase2_folders: list[str],
) -> ScoutSummary:
    """Merge Phase 1 and Phase 2 results into a ScoutSummary."""
    # Start with bootstrap data
    policy_files = dict(bootstrap.root_policy_files)
    vault_skills = dict(bootstrap.root_vault_skills)

    # Classify Phase 2 read_file results
    for tool_name, file_path, result_json in accumulated_reads:
        try:
            data = json.loads(result_json)
            content = data.get("content", "")
        except (json.JSONDecodeError, TypeError):
            content = ""

        basename = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path
        normalized_path = file_path.lstrip("/")

        if is_meta_file(basename):
            policy_files[normalized_path] = content
        if basename.lower().startswith("skill-"):
            vault_skills[normalized_path] = content

    # Merge folders
    folders_explored = list(bootstrap.folders_discovered) + phase2_folders

    return ScoutSummary(
        directory_tree=bootstrap.directory_tree,
        policy_files=policy_files,
        vault_skills=vault_skills,
        files_read=bootstrap.files_read | tracker.all(),
        folders_explored=folders_explored,
        llm_summary=llm_summary,
        mode="llm",
        total_llm_steps=total_steps,
        completed_fully=completed_fully,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_scout(
    vm: Any,
    tracker: GroundingTracker,
    config: ScoutConfig,
    context_config: ContextConfig | None = None,
) -> ScoutSummary:
    """Run the two-phase scout: deterministic bootstrap + LLM-driven explorer.

    Args:
        vm: MiniRuntimeClientSync instance for VM operations.
        tracker: GroundingTracker to record all files read during both phases.
        config: ScoutConfig with model, task_instruction, max_steps, max_workers.
        context_config: Optional ContextConfig for tool result truncation and
            micro-compact. Auto-compact is NOT applied in the scout phase.

    Returns:
        ScoutSummary with directory tree, policy files, vault skills,
        files read, folders explored, LLM summary, and completion metadata.
    """
    protected_files: set[str] = set()

    # Phase 1: Deterministic Bootstrap
    print("  Scout Phase 1: Bootstrap (tree + root files)...", flush=True)
    bootstrap = _run_bootstrap(vm, tracker, protected_files, context_config=context_config, config=config)
    print(
        f"  Bootstrap: {len(bootstrap.folders_discovered)} folders, "
        f"{len(bootstrap.root_policy_files)} policy files, "
        f"{len(bootstrap.root_vault_skills)} vault skills",
    )

    # Phase 2: LLM Explorer
    print(f"  Scout Phase 2: LLM Explorer (model={config.model}, max_steps={config.max_steps})...", flush=True)
    llm_summary, total_steps, completed_fully, reads, folders = _run_llm_explorer(
        vm, tracker, config, bootstrap, protected_files,
        context_config=context_config,
    )
    print(
        f"  Explorer: {total_steps} steps, "
        f"completed_fully={completed_fully}, "
        f"{len(reads)} files classified",
    )

    # Build summary
    return _build_summary(
        bootstrap, tracker, llm_summary, total_steps, completed_fully, reads, folders,
    )
