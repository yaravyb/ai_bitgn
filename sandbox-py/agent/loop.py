"""Orchestrator: scout phase -> executor phase lifecycle.

This is the top-level module that connects all other agent modules.
Only loop.py is permitted to import from all other agent/ modules
(orchestrator privilege per design section 2).
"""

from __future__ import annotations

import json
import logging
import os
import posixpath
import re
import time
import uuid
from pathlib import Path
from typing import Any

from agent.scout import run_scout, ScoutSummary, ScoutConfig
from agent.llm import call_llm, LLMResponse
from agent.dispatch import dispatch_parallel, dispatch_tool, DispatchContext, TemplateGuardConfig, TaskConstraints, init_plan_storage, get_plan_file_path
from agent.verify import (
    VerificationState,
    VerificationOutcome,
    should_verify,
    build_verification_prompt,
    detect_verification_outcome,
)
from agent.prompt import build_system_prompt
from agent.skills import SkillLoader
from agent.tracker import GroundingTracker
from agent.tools import get_tool_schemas
from agent.context import (
    ContextConfig,
    ResilienceConfig,
    estimate_tokens,
    micro_compact,
    COMPACT_SENTINEL,
)

from dataclasses import dataclass, field

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Resilience data structures (weak-model-resilience)
# ---------------------------------------------------------------------------

@dataclass
class ResilienceState:
    """Mutable counters for weak-model resilience mechanisms.

    Constructed once per ``run_agent`` call, alongside ``VerificationState``.
    """

    consecutive_empty: int = 0
    consecutive_text_tool: int = 0
    consecutive_errors: int = 0
    completion_submitted: bool = False
    steps_since_completion_attempt: int = 0
    recent_tool_calls: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Plan helpers (persistent-task-planner)
# ---------------------------------------------------------------------------

def _read_plan_for_checkpoint() -> str | None:
    """Read plan from local storage and format for checkpoint injection.

    Returns a formatted string with plan status and revision guidance,
    or None if no plan exists.
    Errors are silently caught (fail-open: checkpoint works without plan).
    """
    plan_path = get_plan_file_path()
    if not os.path.isfile(plan_path):
        return None
    try:
        with open(plan_path, encoding="utf-8") as f:
            plan = json.load(f)
    except (json.JSONDecodeError, ValueError, OSError):
        return None

    steps = plan.get("steps", [])
    if not steps:
        return None

    total = plan.get("total", len(steps))
    completed = plan.get("completed", 0)
    skipped = plan.get("skipped", 0)
    pending_count = sum(1 for s in steps if s.get("status") == "pending")

    # Build summary line
    actionable = total - skipped
    if skipped > 0:
        summary = f"{completed}/{actionable} actionable steps completed, {skipped} skipped"
    else:
        summary = f"{completed}/{total} steps completed"

    # Build numbered list
    lines = [f"<plan-status>", f"Your execution plan ({summary}):"]
    for step in steps:
        status = step.get("status", "pending")
        marker = {"done": "[DONE]", "pending": "[PENDING]", "skipped": "[SKIPPED]"}.get(status, "[PENDING]")
        desc = step.get("description", "")
        lines.append(f"{step.get('index', 0) + 1}. {marker} {desc}")

    # Include saved notes
    notes = plan.get("notes", [])
    if notes:
        lines.append("")
        lines.append("Your saved notes:")
        for note in notes:
            lines.append(f"- {note}")

    lines.append("")

    if pending_count > 0:
        lines.append("If your current approach is not working, you can:")
        lines.append("- Call plan_create with a revised step list to replace this plan.")
        lines.append("- Call plan_step_skip to skip steps that are unnecessary or blocked.")
        lines.append("You may also continue with the current plan if it is still viable.")
    else:
        lines.append("All plan steps are completed. Consider calling report_completion.")

    lines.append("</plan-status>")
    return "\n".join(lines)


def _read_plan_for_verification() -> str:
    """Read plan from local storage and format as a verification section.

    Returns formatted plan status string, or empty string if no plan exists.
    """
    plan_path = get_plan_file_path()
    if not os.path.isfile(plan_path):
        return ""
    try:
        with open(plan_path, encoding="utf-8") as f:
            plan = json.load(f)
    except (json.JSONDecodeError, ValueError, OSError):
        return ""

    steps = plan.get("steps", [])
    if not steps:
        return ""

    total = plan.get("total", len(steps))
    completed = plan.get("completed", 0)
    skipped = plan.get("skipped", 0)
    pending_steps = [s for s in steps if s.get("status") == "pending"]
    actionable = total - skipped

    if pending_steps:
        lines = [f"## Plan Status -- Incomplete Steps Detected"]
        lines.append(f"Your execution plan has {len(pending_steps)} of {actionable} actionable steps still pending:")
        for s in pending_steps:
            lines.append(f"- Step {s.get('index', 0)}: [PENDING] {s.get('description', '')}")
        lines.append("")
        lines.append("Review these incomplete steps. Either complete them before re-submitting,")
        lines.append("or confirm they are intentionally skipped by calling plan_step_skip.")
        return "\n".join(lines)
    else:
        skipped_note = f" ({skipped} skipped)" if skipped > 0 else ""
        return f"## Plan Status\nAll {completed} plan steps completed{skipped_note}."


# ---------------------------------------------------------------------------
# Resilience helper functions (weak-model-resilience)
# ---------------------------------------------------------------------------

# Distinguishing parameter combinations for tool-call detection.
# Each entry: (required_keys_frozenset, tool_name)
_TOOL_PARAM_COMBOS: list[tuple[frozenset[str], str]] = [
    (frozenset({"path", "content"}), "write_file"),
    (frozenset({"path", "level"}), "tree"),
    (frozenset({"path", "number"}), "read_file"),
    (frozenset({"path", "start_line"}), "read_file"),
    (frozenset({"pattern"}), "search"),
    (frozenset({"name", "root"}), "find"),
    (frozenset({"name", "kind"}), "find"),
]


def _looks_like_tool_call(text: str) -> bool:
    """Return True if *text* looks like a tool-call JSON dict (not a completion).

    Pre-check: return False immediately if text does not start with ``{`` and
    end with ``}`` (zero overhead for non-JSON text).
    """
    stripped = text.strip()
    if not stripped.startswith("{") or not stripped.endswith("}"):
        return False

    try:
        data = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return False

    if not isinstance(data, dict):
        return False

    # Dicts with "answer" key are handled by _try_extract_completion
    if "answer" in data:
        return False

    keys = set(data.keys())
    for combo, _tool_name in _TOOL_PARAM_COMBOS:
        if combo.issubset(keys):
            return True

    return False


def _detect_tool_name(text: str) -> str | None:
    """Return the most likely tool name for a text-based tool call, or None."""
    stripped = text.strip()
    if not stripped.startswith("{") or not stripped.endswith("}"):
        return None

    try:
        data = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    keys = set(data.keys())
    for combo, tool_name in _TOOL_PARAM_COMBOS:
        if combo.issubset(keys):
            return tool_name

    return None


def _build_tool_name_list(runtime_type: str = "mini") -> str:
    """Return a comma-separated string of available tool names."""
    schemas = get_tool_schemas(runtime_type)
    names = [s["function"]["name"] for s in schemas]
    return ", ".join(names)


CLI_RED = "\x1B[31m"
CLI_GREEN = "\x1B[32m"
CLI_BLUE = "\x1B[34m"
CLI_CLR = "\x1B[0m"


def _normalize_path(path: str) -> str:
    """Normalize a path for protected-file comparison (lowercase, no leading /)."""
    stripped = path.lstrip("/")
    normalized = posixpath.normpath(stripped)
    return normalized.lower()


def _extract_task_constraints_llm(
    model: str,
    task_text: str,
    trace_metadata: dict[str, Any],
) -> TaskConstraints:
    """LLM-path: prompt the model to extract structured constraints.

    Returns TaskConstraints parsed from LLM JSON response. Falls back to
    default TaskConstraints(source_file=None, scope_level="normal",
    target_directories=()) on any error (fail-open).
    """
    _DEFAULT = TaskConstraints()

    extraction_prompt = (
        "Extract task constraints from the following task instruction.\n"
        "Return a JSON object with these fields:\n"
        '- "source_file": basename of the primary source file (string or null)\n'
        '- "scope_level": "focused" if the task restricts modifications, "normal" otherwise\n'
        '- "target_directories": list of directory paths or file paths that the task\n'
        "  explicitly allows modifications to\n\n"
        "Task:\n"
        f"<task>\n{task_text}\n</task>\n\n"
        "Respond with ONLY the JSON object, no additional text."
    )

    try:
        response = call_llm(
            model,
            [{"role": "user", "content": extraction_prompt}],
            tools=None,
            max_tokens=500,
            metadata=trace_metadata,
        )
    except Exception:
        log.warning("LLM constraint extraction failed (exception); using defaults")
        return _DEFAULT

    content = response.content
    if not content:
        log.warning("LLM constraint extraction returned empty content; using defaults")
        return _DEFAULT

    # Try to parse JSON from the response, handling markdown code fences
    text = content.strip()
    if text.startswith("```"):
        # Strip markdown code fence
        lines = text.split("\n")
        # Remove first and last lines (``` markers)
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        log.warning("LLM constraint extraction returned unparseable JSON; using defaults")
        return _DEFAULT

    if not isinstance(data, dict):
        log.warning("LLM constraint extraction returned non-dict JSON; using defaults")
        return _DEFAULT

    # Build TaskConstraints from parsed data
    source_file = data.get("source_file")
    scope_level = data.get("scope_level", "normal")
    target_dirs = data.get("target_directories", [])

    if scope_level not in ("focused", "normal"):
        scope_level = "normal"

    return TaskConstraints(
        source_file=source_file if isinstance(source_file, str) else None,
        scope_level=scope_level,
        target_directories=tuple(target_dirs) if isinstance(target_dirs, list) else (),
    )


def _try_extract_completion(text: str) -> dict[str, Any] | None:
    """Try to extract report_completion arguments from structured text.

    Weaker models sometimes output tool calls as plain text (JSON blobs or
    ``report_completion({...})`` syntax) instead of using the tool mechanism.
    Returns the parsed arguments dict when extraction succeeds, None otherwise.
    """
    # Try 1: entire text is a JSON object with an "answer" key
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "answer" in data:
            return data
    except (json.JSONDecodeError, ValueError):
        pass

    # Try 2: report_completion({...}) function-call with JSON arg
    match = re.search(r"report_completion\s*\(\s*(\{.*\})\s*\)", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict) and "answer" in data:
                return data
        except (json.JSONDecodeError, ValueError):
            pass

    # Try 3: report_completion(answer="...", ...) Python kwargs syntax
    match = re.search(r'report_completion\s*\(\s*(?:.*,\s*)?answer\s*=\s*"([^"]*)"', text)
    if match:
        result: dict[str, Any] = {"answer": match.group(1)}
        code_match = re.search(r'code\s*=\s*"([^"]*)"', text)
        if code_match:
            result["code"] = code_match.group(1)
        refs_match = re.search(r"grounding_refs\s*=\s*\[([^\]]*)\]", text)
        if refs_match:
            result["grounding_refs"] = [
                r.strip().strip("\"'") for r in refs_match.group(1).split(",") if r.strip()
            ]
        return result

    return None


def _format_scout_context(summary: ScoutSummary) -> str:
    """Format the scout summary for injection into executor messages."""
    parts: list[str] = ["<scout-summary>"]

    parts.append("## Directory Structure")
    parts.append(summary.directory_tree)

    if summary.policy_files:
        parts.append("\n## Policy Files")
        for path, content in sorted(summary.policy_files.items()):
            parts.append(f"### {path}")
            parts.append(content)

    if summary.vault_skills:
        parts.append("\n## Vault Skills")
        for path, content in sorted(summary.vault_skills.items()):
            parts.append(f'<vault-skill path="{path}">')
            parts.append(content)
            parts.append("</vault-skill>")

    if summary.files_read:
        parts.append("\n## Files Read During Scout")
        for f in sorted(summary.files_read):
            parts.append(f"- {f}")

    # New: Scout Analysis section from LLM explorer (additive)
    llm_summary = getattr(summary, "llm_summary", None)
    completed_fully = getattr(summary, "completed_fully", True)
    total_llm_steps = getattr(summary, "total_llm_steps", 0)

    if llm_summary and llm_summary.strip():
        parts.append("\n## Scout Analysis")
        parts.append(llm_summary)

    if not completed_fully:
        if not (llm_summary and llm_summary.strip()):
            parts.append("\n## Scout Analysis")
        parts.append(
            f"\n**Warning: Scout exploration was truncated by the step limit. "
            f"Some areas may not have been fully explored. The scout completed "
            f"{total_llm_steps} LLM rounds.**"
        )

    parts.append("</scout-summary>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Context management helpers (Task 7.1, 7.2)
# ---------------------------------------------------------------------------

def _apply_micro_compact(
    messages: list[dict[str, Any]],
    config: ContextConfig,
) -> tuple[int, int]:
    """Wrap micro_compact() and return (cleared_count, chars_saved)."""
    # Snapshot content lengths before compaction
    before: dict[int, int] = {}
    for idx, msg in enumerate(messages):
        if msg.get("role") == "tool":
            content = msg.get("content")
            if isinstance(content, str):
                before[idx] = len(content)

    micro_compact(messages, config)

    # Compute what changed
    cleared_count = 0
    chars_saved = 0
    for idx, old_len in before.items():
        content = messages[idx].get("content", "")
        new_len = len(content) if isinstance(content, str) else 0
        if new_len < old_len:
            cleared_count += 1
            chars_saved += old_len - new_len

    return (cleared_count, chars_saved)


def _apply_auto_compact(
    messages: list[dict[str, Any]],
    config: ContextConfig,
    model: str,
    trace_metadata: dict[str, Any],
    reason: str = "threshold_exceeded",
) -> list[dict[str, Any]]:
    """Summarize the conversation via LLM and return replacement messages.

    Steps:
    1. Save full transcript to disk as JSONL with metadata header.
    2. Call LLM with summarization prompt.
    3. Return [system_message, summary_user_message, assistant_ack].
    """
    tokens_before = estimate_tokens(messages)
    messages_before = len(messages)

    # Step 1: Save transcript
    timestamp = int(time.time())
    transcript_path = f"{config.transcript_dir}/transcript_{timestamp}.jsonl"
    try:
        os.makedirs(config.transcript_dir, exist_ok=True)
        with open(transcript_path, "w", encoding="utf-8") as f:
            meta = {
                "_meta": {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "trace_id": trace_metadata.get("trace_id", ""),
                    "estimated_tokens": tokens_before,
                    "reason": reason,
                }
            }
            f.write(json.dumps(meta, default=str) + "\n")
            for msg in messages:
                f.write(json.dumps(msg, default=str) + "\n")
    except OSError as exc:
        log.warning("Failed to save transcript: %s", exc)
        transcript_path = "(failed to save)"

    # Step 2: Build summarization prompt and call LLM
    conversation_text = str(messages)[:80_000]
    summarization_prompt = (
        "Summarize this conversation for continuity. Preserve:\n"
        "1) What has been accomplished so far\n"
        "2) Current state of the task\n"
        "3) Key decisions and their rationale\n"
        "4) Files read and modified\n"
        "5) Pending actions or next steps\n"
        "6) The original task instruction and system prompt rules\n\n"
        "Be concise but preserve critical details for continued execution.\n\n"
        f"Conversation:\n{conversation_text}"
    )

    summary_response = call_llm(
        model,
        [{"role": "user", "content": summarization_prompt}],
        tools=None,
        max_tokens=2000,
        metadata=trace_metadata,
    )
    summary_text = summary_response.content or "Summary unavailable."

    # Step 3: Build replacement messages
    system_msg = messages[0]  # Preserve original system message
    new_messages = [
        system_msg,
        {
            "role": "user",
            "content": f"[Conversation compressed. Transcript: {transcript_path}]\n\n{summary_text}",
        },
        {
            "role": "assistant",
            "content": "Understood. I have the context from the summary. Continuing with the task.",
        },
    ]

    tokens_after = estimate_tokens(new_messages)
    log.info(
        "Auto-compact (%s): tokens %d -> %d, messages %d -> %d, summary %d chars",
        reason, tokens_before, tokens_after, messages_before, len(new_messages),
        len(summary_text),
    )

    return new_messages


def run_agent(
    executor_model: str,
    runtime: Any,
    task_text: str,
    scout_model: str | None = None,
    skills_dir: Path | None = None,
) -> None:
    """Run the full agent lifecycle: init -> scout -> prompt -> executor loop.

    Args:
        executor_model: LiteLLM model identifier for the executor phase.
        runtime: RuntimeAdapter instance for VM operations.
        task_text: The task instruction text.
        scout_model: Optional model for future LLM-augmented scout (unused).
        skills_dir: Path to the skills directory, or None.
    """
    # ------------------------------------------------------------------
    # 1. Initialize
    # ------------------------------------------------------------------
    tracker = GroundingTracker()
    protected_files: set[str] = {"agents.md"}
    context_config = ContextConfig.from_env()

    skill_loader: SkillLoader | None = None
    if skills_dir is not None and skills_dir.is_dir():
        skill_loader = SkillLoader(skills_dir)

    print(f"Agent initialized: model={executor_model}")

    # ------------------------------------------------------------------
    # 2. Scout Phase (two-phase: bootstrap + LLM explorer)
    # ------------------------------------------------------------------
    print("Scout phase starting...", flush=True)
    scout_config = ScoutConfig(
        model=scout_model or executor_model,
        task_instruction=task_text,
    )
    summary = run_scout(runtime, tracker, scout_config, context_config=context_config)

    # Expand protected_files with scout-discovered policy files
    for policy_path in summary.policy_files:
        normalized = _normalize_path(policy_path)
        protected_files.add(normalized)

    print(
        f"Scout complete: {len(summary.policy_files)} policy files, "
        f"{len(summary.vault_skills)} vault skills, "
        f"{len(summary.files_read)} files read, "
        f"protected={protected_files}",
    )

    # ------------------------------------------------------------------
    # 3. Build System Prompt
    # ------------------------------------------------------------------
    skills_metadata = ""
    embedded_bodies: list[str] = []
    # Skills that are always embedded in the system prompt (not on-demand)
    _EMBEDDED_SKILLS = ("security-posture", "execution-discipline")
    verification_checklist = ""
    verification_frame: str | None = None
    if skill_loader is not None:
        skills_metadata = skill_loader.get_descriptions()
        for skill_name in _EMBEDDED_SKILLS:
            body = skill_loader.get_content(skill_name)
            if body and not body.startswith("{"):  # skip error JSON
                embedded_bodies.append(body)
        # Load verification checklist (used by build_verification_prompt)
        vb = skill_loader.get_content("self-verification")
        if vb and not vb.startswith("{"):
            verification_checklist = vb
        # Load verification frame template (Task 4: externalized frame)
        vf = skill_loader.get_content("verification-frame")
        if vf and not vf.startswith("{"):
            verification_frame = vf
        else:
            log.warning(
                "verification-frame skill not found or unreadable; "
                "using inline fallback frame"
            )
        print(f"Skills loaded: {skill_loader.list_names()}")

    scout_context_str = _format_scout_context(summary)

    system_prompt = build_system_prompt(
        skills_metadata=skills_metadata,
        scout_summary=scout_context_str,
        embedded_skill_bodies=embedded_bodies,
    )

    print(f"System prompt: {len(system_prompt)} chars")

    # ------------------------------------------------------------------
    # 4. Executor Phase (LLM-driven tool-use loop)
    # ------------------------------------------------------------------
    trace_metadata = {
        "trace_id": str(uuid.uuid4()),
        "trace_name": "run_agent",
        "session_id": os.environ.get("SESSION_ID", ""),
        "trace_metadata": {
            "model": executor_model,
            "task": task_text[:200],
        },
    }

    # Initialise local plan storage with this run's UUID
    init_plan_storage(trace_metadata["trace_id"])

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
    ]

    # Add scout context as user message
    messages.append({
        "role": "user",
        "content": scout_context_str,
    })

    # --- LLM-driven task constraint extraction ---
    constraints = _extract_task_constraints_llm(
        executor_model, task_text, trace_metadata
    )

    # Add task as user message with <task> wrapping (Req 4.4)
    task_msg = (
        "Execute the following task.\n\n"
        f"<task>\n{task_text}\n</task>"
    )
    messages.append({"role": "user", "content": task_msg})

    # Read template guard config from environment (Task 6)
    template_dirs_env = os.environ.get("TEMPLATE_PROTECTED_DIRS", "")
    template_protected_dirs = tuple(
        d.strip() for d in template_dirs_env.split(",") if d.strip()
    )
    template_guard_config = TemplateGuardConfig(protected_directories=template_protected_dirs)

    # Construct DispatchContext with safety-only guards (template deletion).
    # Behavioral decisions (scope, filenames) are left to the LLM + skills.
    # TaskConstraints are extracted by LLM but NOT used for programmatic guards —
    # they flow into DispatchContext for observability/logging purposes only.
    dispatch_ctx = DispatchContext(
        template_guard_config=template_guard_config,
    )

    print(f"--- Executor start (model={executor_model}) ---")
    print(f"  Scout context: {len(scout_context_str)} chars")
    print(f"  Policy files in context: {list(summary.policy_files.keys())}")
    print(f"  Vault skills in context: {list(summary.vault_skills.keys())}")

    # Verification state (self-verification feature)
    verification_state = VerificationState()

    # Resilience state (weak-model-resilience)
    resilience_config = ResilienceConfig.from_env()
    resilience_state = ResilienceState()

    step_num = 0
    for step in range(30):  # 30 step limit (Req 12.1)
        step_num = step + 1
        print(f"\nStep {step_num}... ", end="", flush=True)

        # --- Point E: Re-planning checkpoint (Req 14, 15, 16) ---
        _replan_triggered = False
        if resilience_state.recent_tool_calls:
            # Repetition detection: last 3 entries identical (strict)
            if len(resilience_state.recent_tool_calls) >= 3:
                last3 = resilience_state.recent_tool_calls[-3:]
                if len(set(last3)) == 1:
                    _replan_triggered = True
                    log.info("Re-plan: repetition detected at step %d (tool=%s)", step_num, last3[0][0])
            # Cycling detection: duplicate tool+args in a full window
            if not _replan_triggered and len(resilience_state.recent_tool_calls) >= 6:
                unique_calls = set(resilience_state.recent_tool_calls)
                if len(unique_calls) <= len(resilience_state.recent_tool_calls) // 2:
                    _replan_triggered = True
                    log.info("Re-plan: cycling detected at step %d (%d unique in %d calls)",
                             step_num, len(unique_calls), len(resilience_state.recent_tool_calls))
        if not _replan_triggered and resilience_state.steps_since_completion_attempt >= resilience_config.replan_interval:
            _replan_triggered = True
            log.info("Re-plan: progress stall at step %d (%d steps since last completion attempt)",
                     step_num, resilience_state.steps_since_completion_attempt)

        if _replan_triggered:
            # Step 1: Auto-compact if context is substantial (Req 16)
            if estimate_tokens(messages) > 20_000:
                messages[:] = _apply_auto_compact(
                    messages, context_config, executor_model, trace_metadata,
                    reason="replan_recovery",
                )
                log.info("Re-plan: auto-compacted context at step %d", step_num)
                print(f"  [replan] auto-compacted context")

            # Step 2: Inject checkpoint prompt (Req 14) -- NO tool names list (Req 17)
            # Build a brief summary of recent tool calls for context (Req 14:
            # "shall include a summary of what the model has done so far")
            history_lines: list[str] = []
            if resilience_state.recent_tool_calls:
                seen: dict[str, int] = {}
                for name, _h in resilience_state.recent_tool_calls:
                    seen[name] = seen.get(name, 0) + 1
                history_lines.append("Recent actions: " + ", ".join(
                    f"{name} x{count}" if count > 1 else name
                    for name, count in seen.items()
                ))
            history_section = "\n".join(history_lines) + "\n" if history_lines else ""

            checkpoint_msg = (
                "<checkpoint>\n"
                f"You have been working for {resilience_state.steps_since_completion_attempt} steps without completing.\n"
                f"{history_section}"
                "Step back and assess:\n"
                "1. What have you accomplished so far?\n"
                "2. What remains to be done?\n"
                "3. Are you stuck repeating the same reads? If so, try a DIFFERENT approach.\n"
                "4. If the task is done, call report_completion with OUTCOME_OK.\n"
                "5. If you cannot complete the task or need more information, call "
                "report_completion with OUTCOME_NONE_CLARIFICATION.\n"
                "</checkpoint>"
            )
            # --- Plan-aware checkpoint augmentation ---
            plan_section = _read_plan_for_checkpoint()
            if plan_section:
                checkpoint_msg = checkpoint_msg.replace("</checkpoint>", plan_section + "\n</checkpoint>")
                log.info("Re-plan checkpoint: plan steps included (%d/%d completed)", 0, 0)  # counts already logged

            messages.append({"role": "user", "content": checkpoint_msg})
            resilience_state.steps_since_completion_attempt = 0
            resilience_state.recent_tool_calls.clear()
            log.info("Re-plan checkpoint injected at step %d", step_num)
            print(f"  [replan] checkpoint injected")

        # Layer 2: Micro-compact old tool results
        # Skip when replan just fired -- preserve context for reflection
        if not _replan_triggered:
            cleared_count, chars_saved = _apply_micro_compact(messages, context_config)
            if cleared_count > 0:
                log.debug("Micro-compact: cleared %d messages, ~%d chars saved", cleared_count, chars_saved)
                print(f"  [micro-compact] cleared {cleared_count} old tool results (~{chars_saved} chars)")

        # Layer 3: Auto-compact if threshold exceeded
        tokens_est = estimate_tokens(messages)
        if tokens_est > context_config.auto_compact_threshold:
            print(f"  [auto-compact] {tokens_est} est. tokens exceeds threshold {context_config.auto_compact_threshold}, summarizing...")
            messages[:] = _apply_auto_compact(
                messages, context_config, executor_model, trace_metadata,
                reason="threshold_exceeded",
            )
            print(f"  [auto-compact] conversation compressed to {len(messages)} messages")

        tool_schemas = get_tool_schemas(runtime.runtime_type)
        response = call_llm(executor_model, messages, tools=tool_schemas, metadata=trace_metadata)

        # Increment steps_since_completion_attempt (Req 14)
        resilience_state.steps_since_completion_attempt += 1

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

        # Print assistant reasoning/content
        if response.content:
            preview = response.content[:200].replace("\n", "\\n")
            print(f"\n  {CLI_BLUE}LLM says{CLI_CLR}: {preview}")

        # Print tool calls with arguments
        if response.tool_calls:
            # Reset consecutive_empty on any response with tool calls
            resilience_state.consecutive_empty = 0

            for tc in response.tool_calls:
                args_preview = json.dumps(tc.arguments)
                if len(args_preview) > 150:
                    args_preview = args_preview[:150] + "..."
                print(f"  {CLI_BLUE}call{CLI_CLR}: {tc.name}({args_preview})")
        else:
            # LLM responded with text only -- no tool calls.
            if response.content and response.content.strip():
                # Reset consecutive_empty on non-empty text
                resilience_state.consecutive_empty = 0
                raw_text = response.content.strip()

                # Weaker models sometimes output tool calls as text instead of
                # using the tool mechanism. Extract the answer if possible.
                extracted = _try_extract_completion(raw_text)
                if extracted:
                    # Valid completion extracted -- reset text-tool counter
                    resilience_state.consecutive_text_tool = 0
                    text_answer = extracted["answer"]
                    print(f"  (extracted answer from structured text)")
                else:
                    # --- Point B: Text-as-Tool Detector (Req 3, 4) ---
                    if _looks_like_tool_call(raw_text):
                        resilience_state.consecutive_text_tool += 1
                        if resilience_state.consecutive_text_tool <= resilience_config.text_tool_max:
                            detected_tool = _detect_tool_name(raw_text) or "unknown"
                            log.info("Text-as-tool detected: tool=%s, text=%s",
                                     detected_tool, raw_text[:120])
                            tool_names = _build_tool_name_list(runtime.runtime_type)
                            correction_msg = (
                                f"You wrote a tool call as plain text instead of using the "
                                f"function calling mechanism. Please invoke the '{detected_tool}' "
                                f"tool properly using function calling. Do not output JSON "
                                f"directly in your response. Available tools: {tool_names}."
                            )
                            messages.append({"role": "user", "content": correction_msg})
                            print(f"  [resilience] text-as-tool correction injected (tool={detected_tool})")
                            continue  # Next iteration
                        else:
                            # Exhausted re-prompts, fall through to auto-submit
                            resilience_state.consecutive_text_tool = 0
                            log.info("Text-as-tool max exceeded, falling through to auto-submit")

                    text_answer = raw_text

                # --- VERIFICATION INTERCEPTION: text-only path (Task 6.2) ---
                if should_verify(verification_state, context_config.verification_enabled,
                                 context_config.verification_max_attempts):
                    # Intercept text-only auto-submit for verification
                    if not verification_state.in_verification:
                        verification_state.original_answer = text_answer
                        verification_state.original_code = extracted.get("code", "OUTCOME_OK") if extracted else "OUTCOME_OK"
                    verification_state.in_verification = True
                    verification_state.attempts += 1
                    # Reset replan timer — don't let the replan checkpoint fire
                    # during the verification cycle (causes post-completion damage)
                    resilience_state.steps_since_completion_attempt = 0

                    # Log verification start (Task 7)
                    print(f"  [verify] attempt {verification_state.attempts}: "
                          f"intercepted text-only auto-submit")
                    log.info("Verification attempt %d: intercepted text-only auto-submit",
                             verification_state.attempts)

                    # Build and inject verification prompt
                    plan_status_text = _read_plan_for_verification()
                    prompt = build_verification_prompt(
                        text_answer, "OUTCOME_OK", summary.policy_files,
                        checklist_body=verification_checklist,
                        source_basename=None,
                        frame_template=verification_frame,
                        plan_status=plan_status_text,
                    )
                    messages.append({
                        "role": "user",
                        "content": prompt,
                    })
                    continue  # Next iteration of executor loop
                else:
                    # Auto-submit normally
                    print(f"  (no tool calls -- auto-submitting text as answer)")
                    submit_args: dict[str, Any] = {
                        "answer": text_answer,
                        "grounding_refs": extracted.get("grounding_refs", []) if extracted else [],
                        "steps": extracted.get("steps", []) if extracted else [],
                        "code": extracted.get("code", "OUTCOME_OK") if extracted else "OUTCOME_OK",
                    }
                    resilience_state.completion_submitted = True
                    dispatch_tool(
                        runtime, "report_completion", submit_args,
                        tracker, protected_files, skill_loader,
                        context_config=context_config,
                    )

                    # Log verification outcome if we were in a verification cycle (Task 7)
                    if verification_state.in_verification:
                        outcome = detect_verification_outcome(
                            verification_state.original_answer, text_answer
                        )
                        if outcome == VerificationOutcome.CONFIRMED:
                            print(f"  [verify] answer CONFIRMED after "
                                  f"{verification_state.attempts} attempt(s)")
                            log.info("Verification: answer confirmed (unchanged)")
                        else:
                            orig_preview = verification_state.original_answer[:80]
                            new_preview = text_answer[:80]
                            print(f"  [verify] answer REVISED after "
                                  f"{verification_state.attempts} attempt(s)")
                            print(f"    original: {orig_preview}")
                            print(f"    revised:  {new_preview}")
                            log.info("Verification: answer revised. "
                                     "original=%r, revised=%r",
                                     orig_preview, new_preview)

                    actual_refs = submit_args["grounding_refs"] or tracker.merge([])
                    print(f"  Auto-submitted answer: {text_answer[:120]}")
                    print(f"  Refs sent to harness: {actual_refs}")
            elif verification_state.in_verification:
                # Empty/whitespace LLM response during verification cycle.
                # Submit the captured answer rather than dropping it.
                print(f"  (empty response during verification -- submitting captured answer)")
                resilience_state.completion_submitted = True
                dispatch_tool(
                    runtime, "report_completion",
                    {"answer": verification_state.original_answer, "grounding_refs": [],
                     "steps": [], "code": verification_state.original_code},
                    tracker, protected_files, skill_loader,
                    context_config=context_config,
                )
                print(f"  Auto-submitted answer: {verification_state.original_answer[:120]}")
            else:
                # --- Point A: Empty Response Handler (Req 1, 2) ---
                resilience_state.consecutive_empty += 1
                if resilience_state.consecutive_empty < resilience_config.empty_retry_max:
                    log.warning("Empty response at step %d (retry %d/%d)",
                                step_num, resilience_state.consecutive_empty,
                                resilience_config.empty_retry_max)
                    tool_names = _build_tool_name_list(runtime.runtime_type)
                    nudge_msg = (
                        "Your previous response was empty. Continue working on the task "
                        f"using the available tools: {tool_names}. "
                        "Do not repeat yourself -- take the next action."
                    )
                    messages.append({"role": "user", "content": nudge_msg})
                    print(f"  [resilience] empty response nudge injected "
                          f"(retry {resilience_state.consecutive_empty}/{resilience_config.empty_retry_max})")
                    continue  # Next iteration (consumes a step)
                else:
                    log.warning("Empty response retry exhausted at step %d", step_num)
                    resilience_state.completion_submitted = True
                    dispatch_tool(
                        runtime, "report_completion",
                        {"answer": "Agent loop ended: model stopped responding after "
                         f"{resilience_config.empty_retry_max} empty responses.",
                         "grounding_refs": [], "steps": [],
                         "code": "OUTCOME_ERR_INTERNAL"},
                        tracker, protected_files, skill_loader,
                        context_config=context_config,
                    )
                    print(f"  [resilience] empty response fallback submitted")
            break

        # --- VERIFICATION INTERCEPTION: tool-call path (Task 6.1) ---
        # Separate report_completion from other tool calls
        completion_tc = None
        other_tool_calls = []
        for tc in response.tool_calls:
            if tc.name == "report_completion":
                completion_tc = tc
            else:
                other_tool_calls.append(tc)

        # Dispatch non-completion tool calls (may be empty)
        compact_requested = False
        if other_tool_calls:
            results = dispatch_parallel(
                runtime, other_tool_calls, tracker, protected_files, skill_loader,
                context_config=context_config,
                dispatch_ctx=dispatch_ctx,
            )

            # Append tool results, detect compact sentinel
            # --- Point C: Error Recovery Hint Injector (Req 5) ---
            for tool_call_id, result_text in results:
                if result_text == COMPACT_SENTINEL:
                    compact_requested = True
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": "Compacting context...",
                    })
                else:
                    # Check for errors in tool results (Req 5)
                    content_to_append = result_text
                    if '"error"' in result_text:
                        resilience_state.consecutive_errors += 1
                        if "not_found" in result_text.lower():
                            # Extract path from error for hint
                            hint = (
                                "\n\n[Hint: The file was not found. Try using list_dir or "
                                "tree on the parent directory to find the correct filename.]"
                            )
                            content_to_append = result_text + hint
                            log.info("Error recovery hint injected for NOT_FOUND (tool_call=%s)", tool_call_id)
                    else:
                        resilience_state.consecutive_errors = 0

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": content_to_append,
                    })
                preview = result_text[:200].replace("\n", "\\n")
                if len(result_text) > 200:
                    preview += "..."
                print(f"  {CLI_GREEN}result({tool_call_id}){CLI_CLR}: {preview}")

            # Error escalation (Req 5)
            if resilience_state.consecutive_errors >= resilience_config.error_threshold:
                tool_names = _build_tool_name_list(runtime.runtime_type)
                escalation_msg = (
                    f"You have encountered {resilience_state.consecutive_errors} "
                    f"consecutive errors. Consider an alternative approach. "
                    f"Available tools: {tool_names}."
                )
                messages.append({"role": "user", "content": escalation_msg})
                resilience_state.consecutive_errors = 0
                log.info("Error escalation message injected after %d consecutive errors",
                         resilience_config.error_threshold)
                print(f"  [resilience] error escalation injected")

            # Track tool calls in rolling window (Req 15)
            for tc in other_tool_calls:
                args_hash = hash(json.dumps(tc.arguments, sort_keys=True))
                resilience_state.recent_tool_calls.append((tc.name, args_hash))
                if len(resilience_state.recent_tool_calls) > 10:
                    resilience_state.recent_tool_calls.pop(0)

        # Handle compact sentinel
        if compact_requested:
            log.info("Compact tool invoked by LLM")
            print(f"  [compact tool] LLM requested context compaction, summarizing...")
            messages[:] = _apply_auto_compact(
                messages, context_config, executor_model, trace_metadata,
                reason="compact_tool",
            )
            print(f"  [compact tool] conversation compressed to {len(messages)} messages")

        # Handle report_completion with verification interception
        if completion_tc is not None:
            answer = completion_tc.arguments.get("answer", "")
            code = completion_tc.arguments.get("code", "OUTCOME_OK")

            if should_verify(verification_state, context_config.verification_enabled,
                             context_config.verification_max_attempts):
                # INTERCEPT: initiate verification cycle
                if not verification_state.in_verification:
                    verification_state.original_answer = answer
                    verification_state.original_code = code
                verification_state.in_verification = True
                verification_state.attempts += 1
                # Reset replan timer — don't let the replan checkpoint fire
                # during the verification cycle (causes post-completion damage)
                resilience_state.steps_since_completion_attempt = 0

                # Log verification start (Task 7)
                answer_preview = answer[:120]
                print(f"  [verify] attempt {verification_state.attempts}: "
                      f"intercepted report_completion, answer preview: {answer_preview}")
                log.info("Verification attempt %d: intercepted report_completion",
                         verification_state.attempts)

                # Build and inject verification prompt
                plan_status_text = _read_plan_for_verification()
                prompt = build_verification_prompt(
                    answer, code, summary.policy_files,
                    checklist_body=verification_checklist,
                    source_basename=None,
                    frame_template=verification_frame,
                    plan_status=plan_status_text,
                )

                # Append synthetic tool result for report_completion
                # (required to maintain valid message sequence for the LLM API)
                messages.append({
                    "role": "tool",
                    "tool_call_id": completion_tc.id,
                    "content": "[Verification in progress -- answer held for review]",
                })

                # Inject verification prompt as user message
                messages.append({
                    "role": "user",
                    "content": prompt,
                })

                continue  # Next iteration of executor loop
            else:
                # Dispatch report_completion normally (verification disabled or max attempts reached)
                resilience_state.completion_submitted = True
                resilience_state.steps_since_completion_attempt = 0
                dispatch_tool(
                    runtime, "report_completion", completion_tc.arguments,
                    tracker, protected_files, skill_loader,
                    context_config=context_config,
                )
                # Append tool result message
                messages.append({
                    "role": "tool",
                    "tool_call_id": completion_tc.id,
                    "content": '{"status": "submitted"}',
                })

                # Log verification outcome if we were in a verification cycle (Task 7)
                if verification_state.in_verification:
                    outcome = detect_verification_outcome(
                        verification_state.original_answer, answer
                    )
                    if outcome == VerificationOutcome.CONFIRMED:
                        print(f"  [verify] answer CONFIRMED after "
                              f"{verification_state.attempts} attempt(s)")
                        log.info("Verification: answer confirmed (unchanged)")
                    else:
                        orig_preview = verification_state.original_answer[:80]
                        new_preview = answer[:80]
                        print(f"  [verify] answer REVISED after "
                              f"{verification_state.attempts} attempt(s)")
                        print(f"    original: {orig_preview}")
                        print(f"    revised:  {new_preview}")
                        log.info("Verification: answer revised. "
                                 "original=%r, revised=%r",
                                 orig_preview, new_preview)

                # Completion logging
                llm_refs = completion_tc.arguments.get("grounding_refs", [])
                steps = completion_tc.arguments.get("steps", [])
                actual_refs = llm_refs if llm_refs else tracker.merge([])
                print(f"\n  {CLI_GREEN}=== COMPLETION ==={CLI_CLR}")
                print(f"  Code: {code}")
                print(f"  Answer: {answer[:200]}")
                print(f"  Refs sent to harness: {actual_refs}")
                print(f"  Steps: {steps}")
                print(f"  (tracker has {len(tracker)} files: {sorted(tracker.all())})")

                print(f"\n{CLI_GREEN}Agent completed.{CLI_CLR}")
                break

    # --- Point D: Post-loop guard -- guaranteed answer submission (Req 13) ---
    if not resilience_state.completion_submitted:
        log.warning("Loop exited without report_completion (step=%d)", step_num)
        if verification_state.in_verification and verification_state.original_answer:
            # Submit the captured original answer from verification state
            dispatch_tool(
                runtime, "report_completion",
                {"answer": verification_state.original_answer,
                 "grounding_refs": [], "steps": [],
                 "code": verification_state.original_code},
                tracker, protected_files, skill_loader,
                context_config=context_config,
            )
            print(f"  [guard] submitted captured verification answer")
        else:
            # Generic fallback -- use OUTCOME_NONE_CLARIFICATION because
            # exhausting the step limit means the model couldn't figure out
            # how to complete the task, not that an internal error occurred.
            dispatch_tool(
                runtime, "report_completion",
                {"answer": "Agent was unable to complete the task within the step limit. "
                 "The task may require clarification or a different approach.",
                 "grounding_refs": [], "steps": [],
                 "code": "OUTCOME_NONE_CLARIFICATION"},
                tracker, protected_files, skill_loader,
                context_config=context_config,
            )
            print(f"  [guard] submitted fallback answer (OUTCOME_NONE_CLARIFICATION)")
        resilience_state.completion_submitted = True

    print(f"\n--- Executor finished after {step_num} steps. "
          f"Tracker: {len(tracker)} files ---")
