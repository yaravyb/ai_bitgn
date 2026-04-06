import json
import logging

from agent.config import AgentConfig
from agent.dispatch import compact_tree
from agent.llm import call_llm_no_tools, estimate_tokens
from agent.prompts import CLI_CLR, CLI_YELLOW
from skills import SkillLoader

log = logging.getLogger(__name__)


def build_executor_context(phase1_ctx: dict, skill_loader: SkillLoader) -> str:
    """Assemble the executor context string from phase1 bootstrap results."""
    context = ""
    if phase1_ctx["agents_md"]:
        context += (
            "<agents-md>\n"
            f"{phase1_ctx['agents_md']}\n"
            "</agents-md>\n\n"
        )
    tree_compact = compact_tree(phase1_ctx["directory_tree"])
    context += (
        "<workspace-tree>\n"
        f"{tree_compact}\n"
        "</workspace-tree>"
    )
    readmes = phase1_ctx.get("readmes", "")
    if readmes:
        context += (
            "\n\n<folder-readmes>\n"
            f"{readmes}\n"
            "</folder-readmes>"
        )
    # Available skills: local (generic patterns) + runtime (repo-specific docs)
    local_skills = skill_loader.get_descriptions()
    runtime_skills = phase1_ctx.get("skill_paths", [])
    runtime_list = "\n".join(f"  - {p}" for p in runtime_skills) if runtime_skills else ""
    skills_section = ""
    if local_skills:
        skills_section += f"Agent skills (load by name):\n{local_skills}\n"
    if runtime_list:
        skills_section += f"\nRepo process docs (load by path):\n{runtime_list}\n"
    if skills_section:
        context += (
            "\n\n<available-skills>\n"
            "Use load_skill(name_or_path) BEFORE performing related actions.\n\n"
            f"{skills_section}"
            "</available-skills>"
        )
    return context


def build_task_message(task_text: str, plan: dict, skill_loader: SkillLoader) -> str:
    """Build the task user message with instructions, strategy, and discipline skill."""
    instructions = plan.get("instructions", [])
    strategy = plan["strategy"]

    instructions_section = ""
    if instructions:
        rules_text = "\n".join(f"- {inst}" for inst in instructions)
        instructions_section = (
            f"\n\n<applicable-rules>\n"
            f"These rules from AGENTS.md apply to this task (ordered by priority):\n"
            f"{rules_text}\n"
            f"</applicable-rules>"
        )

    # Always inject execution-discipline skill (the universal default)
    discipline_skill = skill_loader.get_content("execution-discipline")

    strategy_section = f"\n\n<task-strategy>\n{strategy}\n</task-strategy>" if strategy else ""
    return (
        f"{discipline_skill}\n\n"
        f"<task>\n{task_text}\n</task>"
        f"{instructions_section}"
        f"{strategy_section}\n\n"
        "Your plan is already set up from the strategy. "
        "Start executing step 1 immediately — do NOT call plan_create. "
        "Use plan_update to mark each step as you go. "
        "Do NOT skip steps."
    )


def micro_compact(config: AgentConfig, messages: list[dict]) -> None:
    """Replace stale tool results with short placeholders (no LLM call).

    When config.micro_compact_enabled is False: no-op.
    Mutates messages in-place.
    """
    if not config.micro_compact_enabled:
        return

    # Protected zones: system (0), initial context (1-3), recent N turns
    protected_start = 4  # indices 0-3 are system + context + ack + task
    keep_count = config.micro_compact_keep_turns * 2  # each turn = assistant + tool
    protected_end = max(protected_start, len(messages) - keep_count)

    for i in range(protected_start, protected_end):
        msg = messages[i]
        if msg.get("role") == "tool":
            tool_call_id = msg.get("tool_call_id", "")
            content = msg.get("content", "")
            # Determine tool name from the preceding assistant message's tool_calls
            tool_name = "tool"
            for j in range(i - 1, -1, -1):
                prev = messages[j]
                if prev.get("role") == "assistant" and prev.get("tool_calls"):
                    for tc in prev["tool_calls"]:
                        if tc.get("id") == tool_call_id:
                            tool_name = tc.get("function", {}).get("name", "tool")
                            break
                    break
            status = "error" if "error" in content.lower()[:100] else "ok"
            messages[i] = {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": f"{tool_name}: {status}",
            }


def auto_compact(
    config: AgentConfig,
    model: str,
    messages: list[dict],
    metadata: dict | None = None,
) -> None:
    """Summarize conversation when it exceeds the token threshold.

    Runs micro_compact first, then checks if LLM summarization is still needed.
    Mutates messages in-place.
    """
    # Run micro_compact first (AC 9.5)
    micro_compact(config, messages)

    est = estimate_tokens(messages)
    if est < config.auto_compact_threshold:
        return

    print(f"{CLI_YELLOW}[auto-compact] ~{est} tokens, summarizing...{CLI_CLR}")

    try:
        resp = call_llm_no_tools(
            config,
            model,
            [
                {
                    "role": "system",
                    "content": (
                        "Summarize the following agent conversation concisely. "
                        "Preserve: what task was given, what actions were taken, "
                        "what files were read/modified, current state, and what "
                        "remains to be done. Be brief."
                    ),
                },
                {"role": "user", "content": json.dumps(messages[1:], default=str)},
            ],
            metadata=metadata,
            max_tokens=2048,
        )
        summary = resp.choices[0].message.content or ""
    except Exception as exc:
        log.warning("Auto-compact summarization failed: %s", exc)
        return

    sys_msg = messages[0]
    messages.clear()
    messages.append(sys_msg)
    messages.append({
        "role": "user",
        "content": f"<context-summary>\n{summary}\n</context-summary>\nContinue the task.",
    })
    messages.append({"role": "assistant", "content": "Understood. Continuing from the summary."})

    new_est = estimate_tokens(messages)
    print(f"{CLI_YELLOW}[auto-compact] ~{est} -> ~{new_est} tokens{CLI_CLR}")
