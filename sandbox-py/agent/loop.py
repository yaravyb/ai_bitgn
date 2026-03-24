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
from agent.dispatch import dispatch_parallel, dispatch_tool
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
    estimate_tokens,
    micro_compact,
    COMPACT_SENTINEL,
)

log = logging.getLogger(__name__)

CLI_RED = "\x1B[31m"
CLI_GREEN = "\x1B[32m"
CLI_BLUE = "\x1B[34m"
CLI_CLR = "\x1B[0m"


def _normalize_path(path: str) -> str:
    """Normalize a path for protected-file comparison (lowercase, no leading /)."""
    stripped = path.lstrip("/")
    normalized = posixpath.normpath(stripped)
    return normalized.lower()


_FILE_PATH_RE = re.compile(
    r"(?:^|\s|/)(\S+/[\w\-]+(?:\.\w+)+)",
)


def _extract_source_basename(task_text: str) -> str | None:
    """Extract the source file basename from task text.

    Looks for file paths in the task and returns the basename of the first
    match. Returns None if no file path is found.
    """
    match = _FILE_PATH_RE.search(task_text)
    if match:
        return posixpath.basename(match.group(1))
    return None


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

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
    ]

    # Add scout context as user message
    messages.append({
        "role": "user",
        "content": scout_context_str,
    })

    # Add task as user message with <task> wrapping (Req 4.4)
    source_basename = _extract_source_basename(task_text)
    task_msg = (
        "Execute the following task.\n\n"
        f"<task>\n{task_text}\n</task>"
    )
    if source_basename:
        task_msg += (
            f"\n\nSource filename: `{source_basename}` — "
            "when creating derived files, use this exact basename."
        )
    messages.append({"role": "user", "content": task_msg})

    # Detect scope constraints in task text for programmatic write-guards
    _SCOPE_PHRASES = ("keep the diff focused", "don't touch anything else",
                      "do not touch anything else", "focused diff")
    scope_constrained = any(p in task_text.lower() for p in _SCOPE_PHRASES)

    print(f"--- Executor start (model={executor_model}) ---")
    print(f"  Scout context: {len(scout_context_str)} chars")
    print(f"  Policy files in context: {list(summary.policy_files.keys())}")
    print(f"  Vault skills in context: {list(summary.vault_skills.keys())}")

    # Verification state (self-verification feature)
    verification_state = VerificationState()

    step_num = 0
    for step in range(30):  # 30 step limit (Req 12.1)
        step_num = step + 1
        print(f"\nStep {step_num}... ", end="", flush=True)

        # Layer 2: Micro-compact old tool results
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
            for tc in response.tool_calls:
                args_preview = json.dumps(tc.arguments)
                if len(args_preview) > 150:
                    args_preview = args_preview[:150] + "..."
                print(f"  {CLI_BLUE}call{CLI_CLR}: {tc.name}({args_preview})")
        else:
            # LLM responded with text only -- no tool calls.
            if response.content and response.content.strip():
                raw_text = response.content.strip()

                # Weaker models sometimes output tool calls as text instead of
                # using the tool mechanism. Extract the answer if possible.
                extracted = _try_extract_completion(raw_text)
                text_answer = extracted["answer"] if extracted else raw_text
                if extracted:
                    print(f"  (extracted answer from structured text)")

                # --- VERIFICATION INTERCEPTION: text-only path (Task 6.2) ---
                if should_verify(verification_state, context_config.verification_enabled,
                                 context_config.verification_max_attempts):
                    # Intercept text-only auto-submit for verification
                    if not verification_state.in_verification:
                        verification_state.original_answer = text_answer
                        verification_state.original_code = extracted.get("code", "OUTCOME_OK") if extracted else "OUTCOME_OK"
                    verification_state.in_verification = True
                    verification_state.attempts += 1

                    # Log verification start (Task 7)
                    print(f"  [verify] attempt {verification_state.attempts}: "
                          f"intercepted text-only auto-submit")
                    log.info("Verification attempt %d: intercepted text-only auto-submit",
                             verification_state.attempts)

                    # Build and inject verification prompt
                    prompt = build_verification_prompt(
                        text_answer, "OUTCOME_OK", summary.policy_files,
                        checklist_body=verification_checklist,
                        source_basename=source_basename,
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
                dispatch_tool(
                    runtime, "report_completion",
                    {"answer": verification_state.original_answer, "grounding_refs": [],
                     "steps": [], "code": verification_state.original_code},
                    tracker, protected_files, skill_loader,
                    context_config=context_config,
                )
                print(f"  Auto-submitted answer: {verification_state.original_answer[:120]}")
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
                source_basename=source_basename,
                scope_constrained=scope_constrained,
            )

            # Append tool results, detect compact sentinel
            for tool_call_id, result_text in results:
                if result_text == COMPACT_SENTINEL:
                    compact_requested = True
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": "Compacting context...",
                    })
                else:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": result_text,
                    })
                preview = result_text[:200].replace("\n", "\\n")
                if len(result_text) > 200:
                    preview += "..."
                print(f"  {CLI_GREEN}result({tool_call_id}){CLI_CLR}: {preview}")

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

                # Log verification start (Task 7)
                answer_preview = answer[:120]
                print(f"  [verify] attempt {verification_state.attempts}: "
                      f"intercepted report_completion, answer preview: {answer_preview}")
                log.info("Verification attempt %d: intercepted report_completion",
                         verification_state.attempts)

                # Build and inject verification prompt
                prompt = build_verification_prompt(
                    answer, code, summary.policy_files,
                    checklist_body=verification_checklist,
                    source_basename=source_basename,
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

    # Fallback: if the loop ended while verification was in progress
    # (step limit reached or empty response), ensure an answer is submitted.
    if verification_state.in_verification and verification_state.original_answer:
        # Check if an answer was already submitted by inspecting the loop exit
        # (this fallback only runs if the for-loop exhausted its range)
        log.info("Loop ended during verification -- original answer may have been submitted as fallback")

    print(f"\n--- Executor finished after {step_num} steps. "
          f"Tracker: {len(tracker)} files ---")
