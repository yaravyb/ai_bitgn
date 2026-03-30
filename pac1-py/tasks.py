"""In-memory task manager for the PAC1 agent.

Tracks execution plan as a list of steps with status.
The model can create, update, replan, and query tasks via tool calls.
State lives in memory — no file I/O, no persistence across runs.
"""


class TaskManager:
    def __init__(self):
        self._tasks: list[dict] = []
        self._next_id: int = 1

    def create(self, steps: list[str]) -> str:
        """Create a new plan from a list of step descriptions.

        Replaces any existing plan.
        """
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

    def list_all(self) -> str:
        """Return current plan status."""
        return self.render()

    def render(self) -> str:
        """Render tasks as readable text."""
        if not self._tasks:
            return "No plan."
        lines = []
        for t in self._tasks:
            marker = {
                "pending": "[ ]",
                "in_progress": "[>]",
                "completed": "[x]",
                "skipped": "[-]",
            }.get(t["status"], "[?]")
            lines.append(f"{marker} #{t['id']}: {t['text']}")
        done = sum(1 for t in self._tasks if t["status"] in ("completed", "skipped"))
        total = len(self._tasks)
        lines.append(f"\n({done}/{total} done)")
        return "\n".join(lines)

    def _find(self, task_id: int) -> dict | None:
        for t in self._tasks:
            if t["id"] == task_id:
                return t
        return None
