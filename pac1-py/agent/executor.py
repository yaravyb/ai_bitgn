import json
import logging
import re
import time
from pathlib import Path

import litellm
from bitgn.vm.pcm_connect import PcmRuntimeClientSync
from bitgn.vm.pcm_pb2 import AnswerRequest, Outcome, ReadRequest
from google.protobuf.json_format import MessageToDict

from agent.bootstrap import phase1_bootstrap
from agent.config import AgentConfig
from agent.context import auto_compact, build_executor_context, build_task_message
from agent.dispatch import dispatch
from agent.llm import call_llm
from agent.outcomes import (
    OUTCOME_BY_NAME,
    OUTCOME_DENIED_SECURITY,
    OUTCOME_ERR_INTERNAL,
    OUTCOME_OK,
)
from agent.planner import plan_task
from agent.prompts import (
    CLI_BOLD,
    CLI_CLR,
    CLI_CYAN,
    CLI_DIM,
    CLI_GREEN,
    CLI_RED,
    CLI_YELLOW,
    build_executor_system,
)
from agent.validator import validate_completion
from skills import SkillLoader
from tasks import TaskManager
from tools import EXECUTOR_TOOLS

litellm.suppress_debug_info = True
logging.getLogger("LiteLLM").setLevel(logging.CRITICAL)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)


def _parse_strategy_steps(strategy: str) -> list[str]:
    """Parse numbered steps from a planner strategy string."""
    steps = []
    for line in strategy.strip().split("\n"):
        line = line.strip()
        m = re.match(r"^\d+\.\s+(.+)", line)
        if m:
            steps.append(m.group(1))
    return steps


def _build_tree_stem_index(tree_json: str) -> dict[str, str]:
    """Build a map from file stem (e.g. 'mgr_002') to full path (e.g. 'contacts/mgr_002.json').

    Generic: indexes ALL .json files from the workspace tree.
    """
    stem_to_path: dict[str, str] = {}
    try:
        tree_data = json.loads(tree_json) if tree_json else {}
    except (json.JSONDecodeError, TypeError):
        return stem_to_path

    def _walk(node: dict, prefix: str = "") -> None:
        name = node.get("name", "")
        current = "" if name == "/" else (f"{prefix}/{name}" if prefix else name)
        if not node.get("isDir") and name.endswith(".json"):
            stem = name.rsplit(".", 1)[0]
            stem_to_path[stem] = current
        for child in node.get("children", []):
            _walk(child, current)

    root = tree_data.get("root", tree_data)
    if root:
        _walk(root)
    return stem_to_path


def _follow_cross_references(
    vm: PcmRuntimeClientSync,
    grounding: list[str],
    files_read: list[str],
    stem_index: dict[str, str],
) -> list[str]:
    """Follow cross-references in read JSON files and auto-read referenced entities.

    For each file the executor read, re-reads it, parses as JSON, and checks
    if any string field value matches a known file stem from the workspace tree.
    If so, reads that referenced file and adds it to grounding.

    Fully generic — works for any folder/entity structure. No hardcoded paths.
    """
    refs = list(grounding)
    read_set = set(f.lstrip("/") for f in files_read)

    # Follow references up to 2 levels deep (file → referenced file → its references)
    to_scan = list(files_read)
    for _depth in range(2):
        newly_discovered: list[str] = []
        for path in to_scan:
            try:
                result = vm.read(ReadRequest(path=path))
                content = MessageToDict(result).get("content", "") if result else ""
                if not content:
                    continue
                data = json.loads(content)
                if not isinstance(data, dict):
                    continue
                for value in data.values():
                    if isinstance(value, str) and value in stem_index:
                        ref_path = stem_index[value]
                        ref_norm = ref_path.lstrip("/")
                        if ref_norm not in read_set:
                            try:
                                vm.read(ReadRequest(path=ref_path))
                                read_set.add(ref_norm)
                                newly_discovered.append(ref_path)
                                if ref_path not in refs:
                                    refs.append(ref_path)
                                print(f"  {CLI_DIM}cross-ref: {ref_path}{CLI_CLR}")
                            except Exception:
                                pass
            except (json.JSONDecodeError, Exception):
                continue
        if not newly_discovered:
            break
        to_scan = newly_discovered

    # For folders found ONLY via cross-references (not already visited by executor),
    # read sibling files so all related entities in that folder are grounded
    executor_dirs = set()
    for f in files_read:
        parts = f.lstrip("/").rsplit("/", 1)
        if len(parts) == 2:
            executor_dirs.add(parts[0])

    crossref_only_dirs: set[str] = set()
    for ref in refs:
        parts = ref.lstrip("/").rsplit("/", 1)
        if len(parts) == 2 and parts[0] not in executor_dirs:
            crossref_only_dirs.add(parts[0])

    for stem, path in stem_index.items():
        path_norm = path.lstrip("/")
        dir_part = path_norm.rsplit("/", 1)[0] if "/" in path_norm else ""
        if dir_part in crossref_only_dirs and path_norm not in read_set:
            try:
                vm.read(ReadRequest(path=path))
                read_set.add(path_norm)
                if path not in refs:
                    refs.append(path)
                print(f"  {CLI_DIM}sibling: {path}{CLI_CLR}")
            except Exception:
                pass

    # Merge all tracked reads
    for f in files_read:
        if f not in refs:
            refs.append(f)

    return refs


def _run_executor(
    config: AgentConfig,
    model: str,
    vm: PcmRuntimeClientSync,
    skill_loader: SkillLoader,
    executor_system: str,
    context_msg: str,
    task_msg: str,
    metadata: dict | None = None,
    run_id: str = "",
    defer: bool = True,
    instructions: list | None = None,
    strategy_steps: list[str] | None = None,
) -> tuple[dict | None, TaskManager]:
    """Run one executor session. Returns (result dict, task manager)."""
    tm = TaskManager()
    if instructions:
        tm.set_instructions(instructions)

    messages: list[dict] = [
        {"role": "system", "content": executor_system},
        {"role": "user", "content": context_msg},
        {"role": "assistant", "content": "I have the workspace context. Ready to execute."},
        {"role": "user", "content": task_msg},
    ]

    print(f"\n{CLI_BOLD}{'─' * 50}{CLI_CLR}")
    print(f"{CLI_BOLD}Executor {run_id}{CLI_CLR} {CLI_DIM}(full tools, {config.max_executor_steps} steps max){CLI_CLR}")
    print(f"{CLI_BOLD}{'─' * 50}{CLI_CLR}")

    for _ in range(config.max_executor_steps):
        started = time.time()
        resp = call_llm(config, model, messages, EXECUTOR_TOOLS, metadata)
        elapsed_ms = int((time.time() - started) * 1000)
        choice = resp.choices[0]

        assistant_msg: dict = {"role": "assistant", "content": choice.message.content or ""}
        if choice.message.tool_calls:
            assistant_msg["tool_calls"] = [tc.model_dump() for tc in choice.message.tool_calls]
        messages.append(assistant_msg)

        if not choice.message.tool_calls:
            text = (choice.message.content or "").strip()
            print(f"  {CLI_DIM}LLM → text ({elapsed_ms} ms){CLI_CLR}")
            if text:
                print(f"  {CLI_YELLOW}⚠ text response rescued as report_completion{CLI_CLR}")
                return {
                    "outcome": OUTCOME_OK,
                    "message": text,
                    "confidence": 0.7,
                    "grounding_refs": [],
                    "execution_context": tm.render(),
                }, tm
            return None, tm

        n_calls = len(choice.message.tool_calls)
        print(f"  {CLI_DIM}LLM → {n_calls} tool call{'s' if n_calls > 1 else ''} ({elapsed_ms} ms){CLI_CLR}")

        for tc in choice.message.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            brief = ", ".join(
                f"{k}={v!r}" for k, v in args.items()
                if k not in ("content",)
            )

            if name == "report_completion":
                outcome = args.get("outcome", OUTCOME_ERR_INTERNAL)
                message = args.get("message", "")
                confidence = args.get("confidence", 1.0)
                grounding = args.get("grounding_refs", [])
                # Guard: reject empty message for OK outcomes
                if outcome == OUTCOME_OK and not message.strip():
                    print(f"    {CLI_YELLOW}⚠ empty message — nudging model{CLI_CLR}")
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": (
                        "Error: message is empty. You MUST include the actual answer "
                        "data in the message field. Call report_completion again with "
                        "the answer. Also include grounding_refs with file paths you read."
                    )})
                    continue
                # Auto-merge all tracked read files into grounding_refs
                tracked = list(tm._files_read)
                merged = list(dict.fromkeys(grounding + tracked))
                print(f"    {CLI_CYAN}■ report_completion{CLI_CLR} → {outcome}")
                return {
                    "outcome": outcome,
                    "message": message,
                    "confidence": confidence,
                    "grounding_refs": merged,
                    "execution_context": tm.render(),
                }, tm

            if name == "report_threat":
                reason = args.get("reason", "")
                print(f"    {CLI_RED}⚠ report_threat{CLI_CLR}")
                return {
                    "outcome": OUTCOME_DENIED_SECURITY,
                    "message": reason,
                    "confidence": 1.0,
                    "grounding_refs": [],
                    "execution_context": tm.render(),
                }, tm

            # Intercept plan_create: override with planner's strategy steps
            if name == "plan_create" and strategy_steps:
                args = {"steps": strategy_steps}

            try:
                txt = dispatch(vm, name, args, config, tm, defer_writes=defer, skill_loader=skill_loader)
                status = f"{CLI_GREEN}✓{CLI_CLR}"
                detail = f"{len(txt)} chars" if len(txt) > 200 else ""
            except Exception as exc:
                txt = f"Error: {exc}"
                status = f"{CLI_RED}✗{CLI_CLR}"
                detail = str(exc)[:80]

            if name == "write":
                path = args.get("path", "?")
                content_len = len(args.get("content", ""))
                print(f"    {status} {CLI_CYAN}{name}{CLI_CLR} {path} ({content_len} chars)")
            else:
                print(f"    {status} {CLI_CYAN}{name}{CLI_CLR}({brief}){f' — {detail}' if detail else ''}")

            messages.append({"role": "tool", "tool_call_id": tc.id, "content": txt})

        auto_compact(config, model, messages, metadata)
    return None, tm


def run_agent(
    model: str, harness_url: str, task_text: str, metadata: dict | None = None,
) -> None:
    config = AgentConfig.from_env()
    vm = PcmRuntimeClientSync(harness_url)
    skill_loader = SkillLoader(Path(__file__).parent.parent / "skills")

    # Phase 1: Deterministic bootstrap
    phase1_ctx = phase1_bootstrap(vm)

    # Planner: classify task and generate strategy
    plan = plan_task(config, model, task_text, phase1_ctx, skill_loader, metadata)
    if plan["rejection"]:
        try:
            vm.answer(AnswerRequest(
                message=plan["rejection"]["message"],
                outcome=OUTCOME_BY_NAME[plan["rejection"]["outcome"]],
                refs=[],
            ))
        except Exception as exc:
            log.warning("Planner rejection: vm.answer failed: %s", exc)
        return

    # Parse planner strategy into steps for the executor
    strategy_steps = _parse_strategy_steps(plan.get("strategy", ""))

    # Build stem index from workspace tree for cross-reference resolution
    stem_index = _build_tree_stem_index(phase1_ctx.get("directory_tree", ""))

    # Build executor context and task message
    executor_system = build_executor_system()
    context_msg = build_executor_context(phase1_ctx, skill_loader)
    task_msg = build_task_message(task_text, plan, skill_loader)

    # Single executor with deferred writes
    result, tm_exec = _run_executor(
        config, model, vm, skill_loader,
        executor_system, context_msg, task_msg,
        metadata, run_id="", defer=True,
        instructions=plan.get("instructions", []),
        strategy_steps=strategy_steps,
    )

    if not result:
        print(f"{CLI_RED}Executor returned no result{CLI_CLR}")
        try:
            vm.answer(AnswerRequest(
                message="Agent failed to produce a result",
                outcome=Outcome.OUTCOME_ERR_INTERNAL,
                refs=[],
            ))
        except Exception:
            pass
        return

    # Validate before applying writes
    outcome = result["outcome"]
    message = result["message"]
    execution_context = result.get("execution_context", "")

    correction = validate_completion(
        config, model, task_text, message, outcome,
        phase1_ctx.get("agents_md", ""),
        execution_context, metadata,
        vm=vm, files_read=list(tm_exec._files_read),
    )
    if correction:
        outcome = correction["outcome"]
        message = correction["message"]

    # Apply deferred writes only for OK outcomes
    pending = tm_exec.get_pending_writes()
    if outcome == OUTCOME_OK and pending:
        print(f"\n{CLI_BOLD}Applying {len(pending)} writes{CLI_CLR}")
        for op in pending:
            try:
                dispatch(vm, op["op"], op["args"], config)
                print(f"  {CLI_GREEN}✓{CLI_CLR} {op['op']}({op['args'].get('path', op['args'].get('to_name', '?'))})")
            except Exception as exc:
                print(f"  {CLI_RED}✗{CLI_CLR} {op['op']}: {exc}")
    elif pending:
        print(f"\n{CLI_DIM}Skipping {len(pending)} writes (outcome: {outcome}){CLI_CLR}")

    # Follow cross-references: scan read files for entity IDs matching other files
    grounding = result.get("grounding_refs", [])
    if outcome == OUTCOME_OK and stem_index:
        grounding = _follow_cross_references(
            vm, grounding, list(tm_exec._files_read), stem_index,
        )

    # Submit the final answer
    outcome_style = CLI_GREEN if outcome == OUTCOME_OK else CLI_YELLOW
    print(f"\n{CLI_BOLD}Final{CLI_CLR} → {outcome_style}{outcome}{CLI_CLR}")
    print(f"  {message}")
    try:
        vm.answer(AnswerRequest(
            message=message,
            outcome=OUTCOME_BY_NAME.get(outcome, Outcome.OUTCOME_ERR_INTERNAL),
            refs=grounding,
        ))
    except Exception as exc:
        log.warning("Final answer failed: %s", exc)
