"""System prompt builder for the agent.

Leaf module: no imports from other agent/ modules.
Assembles the system prompt from skill content and scout data.
All behavioral rules come from skill files — this module only provides
the minimal structural frame (role + completion format).
"""

from __future__ import annotations


def build_system_prompt(
    skills_metadata: str,
    scout_summary: str | None = None,
    embedded_skill_bodies: list[str] | None = None,
) -> str:
    """Build the executor system prompt.

    The prompt is assembled from:
    - A minimal role definition (structural only)
    - Embedded skill bodies (always-on skills like security-posture,
      execution-discipline)
    - Skills catalog (Layer 1 descriptions)
    - Scout context (discovered workspace data)
    - A minimal completion format (structural only)

    All behavioral rules (security, policy compliance, grounding, exploration)
    live in skill files, not hardcoded here.
    """
    sections: list[str] = []

    # Role — minimal frame, behavioral details come from skills and vault policies
    sections.append(
        "## Role\n"
        "\n"
        "You are a personal business assistant operating in a sandbox VM.\n"
        "AGENTS.MD (and any file it redirects to) is your PRIMARY AUTHORITY.\n"
        "Follow its instructions precisely, including exact response formats, "
        "specific codes, or canned responses it defines.\n"
        "If a policy says to respond with a specific word (e.g. 'TODO', 'TBD'), "
        "respond with EXACTLY that word.\n"
        "If AGENTS.MD redirects (e.g. 'See CLAUDE.MD'), the target is your policy."
    )

    # Embedded skills — always-on behavioral rules from skill files
    if embedded_skill_bodies:
        for body in embedded_skill_bodies:
            if body and body.strip():
                sections.append(body)

    # Skills catalog (Layer 1 descriptions)
    if skills_metadata and skills_metadata.strip():
        sections.append(
            "## Available Skills\n"
            "\n"
            "Call `load_skill(name)` to access full instructions for any skill:\n"
            f"{skills_metadata}"
        )

    # Scout context — content comes from the scout phase
    if scout_summary is not None:
        sections.append(
            "## Scout Context\n"
            "\n"
            "The following information was discovered during the scout phase:\n"
            f"{scout_summary}"
        )

    # Completion format — minimal structural frame (no behavioral rules)
    sections.append(
        "## Completion Format\n"
        "\n"
        "ALWAYS call `report_completion` to submit your answer. Parameters:\n"
        "- `answer`: Your final answer. Be PRECISE — if the policy defines an "
        "exact response code, use ONLY that code.\n"
        "  Use relative paths without leading '/' (e.g. 'work/tmp/file.md').\n"
        "- `grounding_refs`: Relative file paths that informed your answer — "
        "policy files you followed, skill/hint files that guided your approach, "
        "data files you read or created, rules files that defined formats. "
        "Exclude pure redirects and irrelevant files.\n"
        "- `steps`: Brief list of what you did.\n"
        "- `code`: PCM outcome that best matches the situation."
    )

    return "\n\n".join(sections)


def build_scout_prompt(
    task_instruction: str,
    bootstrap_context: str,
) -> str:
    """Build the scout LLM system prompt.

    Args:
        task_instruction: The user's task text (for task-aware exploration).
        bootstrap_context: Pre-formatted string with directory tree and root policy contents.

    Returns:
        Complete system prompt string for the scout LLM.
    """
    sections: list[str] = []

    # 1. Role definition
    sections.append(
        "## Role\n"
        "\n"
        "You are a workspace reconnaissance agent. Your mission is to discover "
        "and catalog workspace contents to help a downstream executor agent. "
        "You do NOT solve the task -- you only explore and report."
    )

    # 2. Bootstrap context
    sections.append(
        "## Bootstrap Context\n"
        "\n"
        "The following workspace structure and root-level file contents were "
        "discovered during the deterministic bootstrap phase:\n"
        "\n"
        "<bootstrap>\n"
        f"{bootstrap_context}\n"
        "</bootstrap>"
    )

    # 3. Task context
    sections.append(
        "## Task Context\n"
        "\n"
        "Use this to prioritize which areas of the workspace to explore. "
        "Do NOT attempt to solve this task.\n"
        "\n"
        "<task>\n"
        f"{task_instruction}\n"
        "</task>"
    )

    # 4. Exploration instructions
    sections.append(
        "## Exploration Instructions\n"
        "\n"
        "1. Read policy/rules files first (AGENTS.MD, README.MD, _rules.*, etc.).\n"
        "2. If a policy file redirects to another file (e.g., 'See CLAUDE.MD'), "
        "follow the redirect and read that file.\n"
        "3. Explore directories that are relevant to the task instruction.\n"
        "4. Use `search()` when looking for specific content patterns.\n"
        "5. Use parallel tool calls to batch multiple reads or listings.\n"
        "6. Skip clearly irrelevant directories (e.g., `node_modules`, `.git`).\n"
        "7. You have the full directory tree already -- jump directly to any "
        "path at any depth. No level-by-level traversal needed.\n"
        "8. For files exceeding ~200 lines (visible from tree/list output), "
        "use start_line/end_line parameters to read only relevant sections "
        "rather than loading the entire file."
    )

    # 5. Completion instructions
    sections.append(
        "## Completion Instructions\n"
        "\n"
        "When you have gathered sufficient context, end your exploration by "
        "responding with a structured text summary containing:\n"
        "\n"
        "1. **Policy files found** and key rules from each.\n"
        "2. **Files read** and why each was relevant.\n"
        "3. **Areas explored vs. skipped** with reasons.\n"
        "4. **Patterns detected** in the workspace.\n"
        "5. **Recommended focus areas** for the executor agent."
    )

    # 6. Constraints
    sections.append(
        "## Constraints\n"
        "\n"
        "- You MUST NOT attempt to solve the task.\n"
        "- You MUST NOT call write_file or delete_file. You are read-only.\n"
        "- Your only purpose is to discover and catalog workspace contents."
    )

    return "\n\n".join(sections)
