"""In-memory task manager for the PAC1 agent.

Tracks execution plan with dependency graph, instructions, and notes.
Tasks have blockedBy/blocks arrays — completing a task auto-unblocks
dependent tasks. Deferred write operations are associated with tasks.
"""


class TaskManager:
    def __init__(self):
        self._tasks: list[dict] = []
        self._next_id: int = 1
        self._notes: list[str] = []
        self._instructions: list[str] = []
        self._files_written: list[str] = []
        self._files_deleted: list[str] = []
        self._files_read: list[str] = []
        self._pending_writes: list[dict] = []

    # -- Instructions --

    def set_instructions(self, instructions: list[str]) -> None:
        self._instructions = [i.strip() for i in instructions if i.strip()]

    def add_instruction(self, instruction: str) -> str:
        self._instructions.append(instruction.strip())
        return self.render()

    def replace_instructions(self, instructions: list[str]) -> str:
        self._instructions = [i.strip() for i in instructions if i.strip()]
        return self.render()

    # -- Plan steps with dependencies --

    def create(self, steps: list[str]) -> str:
        """Create a new plan. Replaces existing steps."""
        self._tasks = []
        self._next_id = 1
        for text in steps:
            self._tasks.append({
                "id": self._next_id,
                "text": text.strip(),
                "status": "pending",
                "blockedBy": [],
                "blocks": [],
            })
            self._next_id += 1
        return self.render()

    def update(self, task_id: int, status: str) -> str:
        """Update a task's status. Completing auto-unblocks dependents."""
        if status not in ("pending", "in_progress", "completed", "skipped"):
            return f"Error: invalid status '{status}'"
        task = self._find(task_id)
        if not task:
            return f"Error: task {task_id} not found"
        # Check if blocked
        if status == "in_progress" and task["blockedBy"]:
            return f"Error: task {task_id} is blocked by {task['blockedBy']}"
        task["status"] = status
        # Auto-unblock dependents when completing
        if status in ("completed", "skipped"):
            self._clear_dependency(task_id)
        return self.render()

    def add(self, text: str, blocked_by: list[int] | None = None) -> str:
        """Add a single new task, optionally blocked by other tasks."""
        task = {
            "id": self._next_id,
            "text": text.strip(),
            "status": "pending",
            "blockedBy": list(blocked_by) if blocked_by else [],
            "blocks": [],
        }
        self._tasks.append(task)
        # Bidirectional: update blockers' blocks list
        if blocked_by:
            for blocker_id in blocked_by:
                blocker = self._find(blocker_id)
                if blocker and self._next_id not in blocker["blocks"]:
                    blocker["blocks"].append(self._next_id)
        self._next_id += 1
        return self.render()

    def add_dependency(self, task_id: int, blocked_by: int) -> str:
        """Add a dependency: task_id is blocked by blocked_by."""
        task = self._find(task_id)
        blocker = self._find(blocked_by)
        if not task:
            return f"Error: task {task_id} not found"
        if not blocker:
            return f"Error: task {blocked_by} not found"
        if blocked_by not in task["blockedBy"]:
            task["blockedBy"].append(blocked_by)
        if task_id not in blocker["blocks"]:
            blocker["blocks"].append(task_id)
        return self.render()

    def _clear_dependency(self, completed_id: int) -> None:
        """Remove completed_id from all tasks' blockedBy lists."""
        for task in self._tasks:
            if completed_id in task["blockedBy"]:
                task["blockedBy"].remove(completed_id)

    # -- File tracking --

    def track_read(self, path: str) -> None:
        if path and path not in self._files_read:
            self._files_read.append(path)

    def track_write(self, path: str) -> None:
        if path and path not in self._files_written:
            self._files_written.append(path)

    def track_delete(self, path: str) -> None:
        if path and path not in self._files_deleted:
            self._files_deleted.append(path)

    def defer_write(self, operation: str, args: dict) -> None:
        self._pending_writes.append({"op": operation, "args": args})

    def get_pending_writes(self) -> list[dict]:
        return self._pending_writes

    # -- Notes --

    def add_note(self, note: str) -> str:
        self._notes.append(note.strip())
        return self.render()

    # -- Query --

    def list_all(self) -> str:
        return self.render()

    def render(self) -> str:
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
                blocked = f" (blocked by: {t['blockedBy']})" if t["blockedBy"] else ""
                lines.append(f"  {marker} #{t['id']}: {t['text']}{blocked}")
            done = sum(1 for t in self._tasks if t["status"] in ("completed", "skipped"))
            total = len(self._tasks)
            lines.append(f"\n({done}/{total} done)")
        if self._files_written:
            lines.append("\nFiles written:")
            for f in self._files_written:
                lines.append(f"  📝 {f}")
        if self._files_deleted:
            lines.append("\nFiles deleted:")
            for f in self._files_deleted:
                lines.append(f"  🗑️ {f}")
        return "\n".join(lines) if lines else "No plan."

    def _find(self, task_id: int) -> dict | None:
        for t in self._tasks:
            if t["id"] == task_id:
                return t
        return None
