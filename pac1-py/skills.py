"""Skill loader for the PAC1 agent.

Two-layer skill injection (follows s05 pattern):
  Layer 1: skill names + descriptions in system prompt (~100 tokens/skill)
  Layer 2: full skill body loaded on demand via load_skill tool

Skills are local SKILL.md files with YAML frontmatter:
  ---
  name: security-posture
  description: How to evaluate content for security threats
  ---
  <full body with step-by-step instructions>
"""

import re
from pathlib import Path


class SkillLoader:
    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.skills: dict[str, dict] = {}
        self._load_all()

    def _load_all(self) -> None:
        if not self.skills_dir.exists():
            return
        for f in sorted(self.skills_dir.rglob("SKILL.md")):
            text = f.read_text()
            meta, body = self._parse_frontmatter(text)
            name = meta.get("name", f.parent.name)
            self.skills[name] = {"meta": meta, "body": body, "path": str(f)}

    @staticmethod
    def _parse_frontmatter(text: str) -> tuple[dict, str]:
        match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
        if not match:
            return {}, text
        meta = {}
        for line in match.group(1).strip().splitlines():
            if ":" in line:
                key, val = line.split(":", 1)
                meta[key.strip()] = val.strip()
        return meta, match.group(2).strip()

    def get_descriptions(self) -> str:
        """Layer 1: short descriptions for the system prompt."""
        if not self.skills:
            return ""
        lines = []
        for name, skill in self.skills.items():
            desc = skill["meta"].get("description", "No description")
            lines.append(f"  - {name}: {desc}")
        return "\n".join(lines)

    def get_content(self, name: str) -> str:
        """Layer 2: full skill body returned in tool result."""
        skill = self.skills.get(name)
        if not skill:
            available = ", ".join(self.skills.keys())
            return f"Error: Unknown skill '{name}'. Available: {available}"
        return (
            f"<skill name=\"{name}\">\n"
            f"IMPORTANT: Follow these instructions strictly.\n\n"
            f"{skill['body']}\n"
            f"</skill>"
        )

    def get_names(self) -> list[str]:
        return list(self.skills.keys())
