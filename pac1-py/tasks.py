"""In-memory task manager for the PAC1 agent.

Tracks execution plan, instructions, and notes.
The model can create, update, replan, and query via tool calls.
State lives in memory — no file I/O, no persistence across runs.
"""


class TaskManager:
    def __init__(self):
        self._tasks: list[dict] = []
        self._next_id: int = 1
        self._notes: list[str] = []
        self._instructions: list[str] = []
        self._files_written: list[str] = []
        self._files_read: list[str] = []

    # -- Instructions (rules from AGENTS.md + discovered during execution) --

    def set_instructions(self, instructions: list[str]) -> None:
        """Set initial instructions from planner. Called once at start."""
        self._instructions = [i.strip() for i in instructions if i.strip()]

    def add_instruction(self, instruction: str) -> str:
        """Add a rule discovered during execution (from README.md, docs, etc.)."""
        self._instructions.append(instruction.strip())
        return self.render()

    def replace_instructions(self, instructions: list[str]) -> str:
        """Replace all instructions. Use when replanning after major discovery."""
        self._instructions = [i.strip() for i in instructions if i.strip()]
        return self.render()

    # -- Plan steps --

    def create(self, steps: list[str]) -> str:
        """Create a new plan. Replaces existing steps (keeps instructions/notes)."""
        self._tasks = []
        self._next_id = 1
        for text in steps:
            self._tasks.append({
                "id": self._next_id,
                "text": text.strip(),
                "status": "pending",
            })
            self._next_id += 1
        return self.render()

    def update(self, task_id: int, status: str) -> str:
        """Update a task's status."""
        if status not in ("pending", "in_progress", "completed", "skipped"):
            return f"Error: invalid status '{status}'"
        task = self._find(task_id)
        if not task:
            return f"Error: task {task_id} not found"
        task["status"] = status
        return self.render()

    def add(self, text: str) -> str:
        """Add a single new task to the plan."""
        self._tasks.append({
            "id": self._next_id,
            "text": text.strip(),
            "status": "pending",
        })
        self._next_id += 1
        return self.render()

    # -- Notes --

    def track_read(self, path: str) -> None:
        """Track a file that was read (for validation context)."""
        if path not in self._files_read:
            self._files_read.append(path)

    def track_write(self, path: str) -> None:
        """Track a file that was written (for validation context)."""
        if path not in self._files_written:
            self._files_written.append(path)

    def add_note(self, note: str) -> str:
        """Save a persistent note (key values, conventions, findings)."""
        self._notes.append(note.strip())
        return self.render()

    # -- Query --

    def list_all(self) -> str:
        """Return full state: instructions + notes + tasks."""
        return self.render()

    def render(self) -> str:
        """Render full state as readable text."""
        lines = []
        if self._instructions:
            lines.append("Instructions:")
            for i in self._instructions:
                lines.append(f"  ⚡ {i}")
            lines.append("")
        if self._notes:
            lines.append("Notes:")
            for n in self._notes:
                lines.append(f"  • {n}")
            lines.append("")
        if self._tasks:
            lines.append("Plan:")
            for t in self._tasks:
                marker = {
                    "pending": "[ ]",
                    "in_progress": "[>]",
                    "completed": "[x]",
                    "skipped": "[-]",
                }.get(t["status"], "[?]")
                lines.append(f"  {marker} #{t['id']}: {t['text']}")
            done = sum(1 for t in self._tasks if t["status"] in ("completed", "skipped"))
            total = len(self._tasks)
            lines.append(f"\n({done}/{total} done)")
        if self._files_written:
            lines.append("\nFiles written:")
            for f in self._files_written:
                lines.append(f"  📝 {f}")
        return "\n".join(lines) if lines else "No plan."

    def _find(self, task_id: int) -> dict | None:
        for t in self._tasks:
            if t["id"] == task_id:
                return t
        return None
