"""Skill loader: reads SKILL.md files with YAML frontmatter.

Leaf module: no imports from other agent/ modules.
Provides Layer 1 metadata (descriptions) and Layer 2 body content.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Regex to extract YAML frontmatter between --- delimiters
_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n",
    re.DOTALL,
)

# Regex to extract key: value from simple YAML
_YAML_FIELD_RE = re.compile(r"^(\w+)\s*:\s*(.+)$", re.MULTILINE)


@dataclass
class SkillEntry:
    """A single skill parsed from a SKILL.md file."""

    name: str
    description: str
    body: str
    path: str


class SkillLoader:
    """Loads skills from a directory of skill folders.

    Each skill is a subdirectory containing a SKILL.md file with
    YAML frontmatter (name, description) and a body.

    Example structure:
        skills/
            workspace-discovery/
                SKILL.md
                references/
                    meta-file-patterns.md
            policy-gate/
                SKILL.md
    """

    def __init__(self, skills_dir: Path) -> None:
        self._skills: dict[str, SkillEntry] = {}
        self._scan(skills_dir)

    def _scan(self, skills_dir: Path) -> None:
        """Scan skills_dir for subdirectories containing SKILL.md."""
        if not skills_dir.is_dir():
            log.warning("Skills directory does not exist: %s", skills_dir)
            return

        for child in sorted(skills_dir.iterdir()):
            if not child.is_dir():
                continue
            skill_file = child / "SKILL.md"
            if not skill_file.is_file():
                continue
            entry = self._parse_skill(skill_file)
            if entry is not None:
                self._skills[entry.name] = entry

    def _parse_skill(self, skill_file: Path) -> SkillEntry | None:
        """Parse a SKILL.md file into a SkillEntry."""
        try:
            text = skill_file.read_text(encoding="utf-8")
        except OSError as exc:
            log.warning("Could not read %s: %s", skill_file, exc)
            return None

        # Extract frontmatter
        match = _FRONTMATTER_RE.match(text)
        if not match:
            log.warning("No valid frontmatter in %s, skipping", skill_file)
            return None

        frontmatter_text = match.group(1)
        body = text[match.end():]

        # Parse simple YAML fields
        fields: dict[str, str] = {}
        for field_match in _YAML_FIELD_RE.finditer(frontmatter_text):
            key = field_match.group(1)
            value = field_match.group(2).strip()
            fields[key] = value

        name = fields.get("name", "")
        description = fields.get("description", "")

        if not name:
            log.warning("SKILL.md at %s has no 'name' in frontmatter, skipping", skill_file)
            return None

        return SkillEntry(
            name=name,
            description=description,
            body=body.strip(),
            path=str(skill_file),
        )

    def get_descriptions(self) -> str:
        """Layer 1: One-line per skill for system prompt."""
        if not self._skills:
            return ""
        lines = []
        for name in sorted(self._skills):
            entry = self._skills[name]
            lines.append(f"- {entry.name}: {entry.description}")
        return "\n".join(lines)

    def get_content(self, name: str) -> str:
        """Layer 2: Full SKILL.md body wrapped in <skill> tags."""
        entry = self._skills.get(name)
        if entry is None:
            return f'{{"error": "Skill not found: {name}"}}'
        return f'<skill name="{entry.name}">\n{entry.body}\n</skill>'

    def list_names(self) -> list[str]:
        """Return sorted list of available skill names."""
        return sorted(self._skills.keys())
