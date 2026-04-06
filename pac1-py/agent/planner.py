import json
import time

from agent.config import AgentConfig
from agent.dispatch import compact_tree
from agent.llm import call_llm
from agent.prompts import (
    CLI_CLR,
    CLI_DIM,
    CLI_BOLD,
    CLI_GREEN,
    CLI_RED,
    build_planner_system,
)
from skills import SkillLoader
from tools import PLANNER_TOOL


def plan_task(
    config: AgentConfig,
    model: str,
    task_text: str,
    phase1_ctx: dict,
    skill_loader: SkillLoader,
    metadata: dict | None = None,
) -> dict:
    """Analyze task and produce an execution plan.

    Returns dict with:
      - strategy: free-form plan text for the executor
      - instructions: list of applicable rules from AGENTS.md
      - rejection: None if feasible, or dict with outcome/message
    """
    print(f"\n{CLI_BOLD}{'─' * 50}{CLI_CLR}")
    print(f"{CLI_BOLD}Planner{CLI_CLR} {CLI_DIM}(single LLM call){CLI_CLR}")
    print(f"{CLI_BOLD}{'─' * 50}{CLI_CLR}")

    tree_compact = compact_tree(phase1_ctx.get("directory_tree", ""))
    agents_md = phase1_ctx.get("agents_md", "")
    readmes = phase1_ctx.get("readmes", "")

    messages: list[dict] = [
        {"role": "system", "content": build_planner_system()},
        {
            "role": "user",
            "content": (
                f"<task>{task_text}</task>\n\n"
                f"<workspace-tree>\n{tree_compact}\n</workspace-tree>\n\n"
                f"<agents-md>\n{agents_md}\n</agents-md>\n\n"
                f"<folder-readmes>\n{readmes}\n</folder-readmes>\n\n"
                f"<available-skills>\n"
                f"Agent skills: {', '.join(skill_loader.get_names())}\n"
                f"Repo docs: {', '.join(phase1_ctx.get('skill_paths', []))}\n"
                f"</available-skills>"
            ),
        },
    ]

    started = time.time()
    try:
        resp = call_llm(config, model, messages, [PLANNER_TOOL], metadata)
        elapsed_ms = int((time.time() - started) * 1000)
        choice = resp.choices[0]

        if choice.message.tool_calls:
            tc = choice.message.tool_calls[0]
            args = json.loads(tc.function.arguments)
            feasible = args.get("feasible", True)
            strategy = args.get("strategy", "")
            raw_instructions = args.get("instructions", [])
            rejection_outcome = args.get("rejection_outcome", "")
            # Fix: weak models sometimes serialize a string as char array
            if raw_instructions and all(len(s) <= 1 for s in raw_instructions):
                instructions = ["".join(raw_instructions)]
            else:
                instructions = raw_instructions
        else:
            feasible = True
            strategy = choice.message.content or ""
            instructions = []
            rejection_outcome = ""

    except Exception as exc:
        elapsed_ms = int((time.time() - started) * 1000)
        print(f"  {CLI_DIM}→ planner failed ({elapsed_ms} ms): {exc}{CLI_CLR}")
        return {"strategy": "", "instructions": [], "rejection": None}

    rejection = None
    if not feasible and rejection_outcome:
        rejection = {"outcome": rejection_outcome, "message": strategy}

    color = CLI_RED if rejection else CLI_GREEN
    label = rejection_outcome if rejection else "FEASIBLE"
    print(f"  {color}→ {label}{CLI_CLR} ({elapsed_ms} ms)")
    if instructions:
        for inst in instructions:
            print(f"  {CLI_DIM}📋 {inst}{CLI_CLR}")
    if strategy:
        preview = strategy[:200] + ("..." if len(strategy) > 200 else "")
        print(f"  {CLI_DIM}{preview}{CLI_CLR}")

    return {"strategy": strategy, "instructions": instructions, "rejection": rejection}
