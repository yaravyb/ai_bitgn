import json
import logging
import time
from pathlib import Path

import litellm
from bitgn.vm.pcm_connect import PcmRuntimeClientSync
from bitgn.vm.pcm_pb2 import AnswerRequest, Outcome

from agent.bootstrap import phase1_bootstrap
from agent.config import AgentConfig
from agent.context import auto_compact, build_executor_context, build_task_message
from agent.dispatch import OUTCOME_BY_NAME, dispatch
from agent.llm import call_llm
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
            # If the model returned text instead of calling report_completion,
            # treat the text as the answer with OUTCOME_OK
            if text:
                print(f"  {CLI_YELLOW}⚠ text response rescued as report_completion{CLI_CLR}")
                return {
                    "outcome": "OUTCOME_OK",
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
                outcome = args.get("outcome", "OUTCOME_ERR_INTERNAL")
                message = args.get("message", "")
                confidence = args.get("confidence", 1.0)
                grounding = args.get("grounding_refs", [])
                # Guard: reject empty message for OK outcomes — ask model to retry
                if outcome == "OUTCOME_OK" and not message.strip():
                    print(f"    {CLI_YELLOW}⚠ empty message — nudging model{CLI_CLR}")
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": (
                        "Error: message is empty. You MUST include the actual answer "
                        "data in the message field. Call report_completion again with "
                        "the answer. Also include grounding_refs with file paths you read."
                    )})
                    continue
                print(f"    {CLI_CYAN}■ report_completion{CLI_CLR} → {outcome}")
                return {
                    "outcome": outcome,
                    "message": message,
                    "confidence": confidence,
                    "grounding_refs": grounding,
                    "execution_context": tm.render(),
                }, tm

            if name == "report_threat":
                reason = args.get("reason", "")
                print(f"    {CLI_RED}⚠ report_threat{CLI_CLR}")
                return {
                    "outcome": "OUTCOME_DENIED_SECURITY",
                    "message": reason,
                    "confidence": 1.0,
                    "grounding_refs": [],
                    "execution_context": tm.render(),
                }, tm

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
        execution_context, metadata, tm_exec,
    )
    if correction:
        outcome = correction["outcome"]
        message = correction["message"]

    # Apply deferred writes only for OK outcomes
    pending = tm_exec.get_pending_writes()
    if outcome == "OUTCOME_OK" and pending:
        print(f"\n{CLI_BOLD}Applying {len(pending)} writes{CLI_CLR}")
        for op in pending:
            try:
                dispatch(vm, op["op"], op["args"], config)
                print(f"  {CLI_GREEN}✓{CLI_CLR} {op['op']}({op['args'].get('path', op['args'].get('to_name', '?'))})")
            except Exception as exc:
                print(f"  {CLI_RED}✗{CLI_CLR} {op['op']}: {exc}")
    elif pending:
        print(f"\n{CLI_DIM}Skipping {len(pending)} writes (outcome: {outcome}){CLI_CLR}")

    # Submit the final answer
    outcome_style = CLI_GREEN if outcome == "OUTCOME_OK" else CLI_YELLOW
    print(f"\n{CLI_BOLD}Final{CLI_CLR} → {outcome_style}{outcome}{CLI_CLR}")
    print(f"  {message}")
    try:
        vm.answer(AnswerRequest(
            message=message,
            outcome=OUTCOME_BY_NAME.get(outcome, Outcome.OUTCOME_ERR_INTERNAL),
            refs=result.get("grounding_refs", []),
        ))
    except Exception as exc:
        log.warning("Final answer failed: %s", exc)
