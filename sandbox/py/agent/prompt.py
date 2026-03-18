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
    security_skill_body: str = "",
) -> str:
    """Build the executor system prompt.

    The prompt is assembled from:
    - A minimal role definition (structural only)
    - Security skill body (injected from skills/security-posture/SKILL.md)
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

    # Security — content comes entirely from the security-posture skill
    if security_skill_body and security_skill_body.strip():
        sections.append(security_skill_body)

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

    # Completion format — minimal structural frame
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
        "- `code`: \"completed\" or \"failed\"."
    )

    return "\n\n".join(sections)


def build_scout_prompt() -> str:
    """Build a minimal scout prompt, reserved for future LLM-based scout extension.

    Currently the scout phase is LLM-free (deterministic). This prompt is
    reserved for future use if a scout model is desired.
    """
    return (
        "You are a workspace discovery assistant. Your sole purpose is to "
        "systematically explore the workspace filesystem and report what you find. "
        "You do not perform any tasks -- only discover and catalog the workspace contents."
    )
