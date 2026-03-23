"""Task DAG: reactive task dependency graph.

Pure data module: no I/O, no imports from other agent/ modules.
Provides Task dataclass, TaskType/TaskStatus enums, and TaskGraph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class TaskType(StrEnum):
    """Types of operations a task can represent."""

    TREE = "tree"
    LIST = "list"
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    SEARCH = "search"
    DECIDE = "decide"
    REPORT = "report"


class TaskStatus(StrEnum):
    """Lifecycle states of a task."""

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    """A single unit of work in the reactive DAG."""

    id: str
    type: TaskType
    args: dict[str, str]
    status: TaskStatus = TaskStatus.PENDING
    blocked_by: set[str] = field(default_factory=set)
    result: str | None = None
    parent_id: str | None = None
    spawn_reason: str | None = None


class TaskGraph:
    """Reactive task dependency graph with wave-based execution support.

    Invariants:
    - A task transitions to READY when blocked_by becomes empty.
    - complete() removes the completed ID from all dependents' blocked_by sets.
    - cancel() removes the cancelled ID from dependents' blocked_by sets
      (not transitive unless explicitly requested by the caller).
    """

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._counter: int = 0

    def _next_id(self, task_type: TaskType) -> str:
        """Generate a monotonic auto-ID based on task type."""
        self._counter += 1
        return f"{task_type}-{self._counter:04d}"

    def add(self, task: Task) -> str:
        """Add a task to the graph. Returns the task ID.

        If the task's id is empty, an auto-generated ID is assigned.
        If blocked_by is empty, the task immediately becomes READY.
        Raises ValueError if a task with the same ID already exists.
        """
        # Auto-generate ID if empty
        if not task.id:
            task.id = self._next_id(task.type)

        if task.id in self._tasks:
            raise ValueError(f"Duplicate task ID: {task.id}")

        # Compute initial status
        if not task.blocked_by:
            task.status = TaskStatus.READY
        else:
            task.status = TaskStatus.PENDING

        self._tasks[task.id] = task
        return task.id

    def complete(self, task_id: str, result: str) -> list[str]:
        """Mark a task as completed and unblock dependents.

        Returns a list of task IDs that became READY as a result.
        """
        task = self._tasks[task_id]
        task.status = TaskStatus.COMPLETED
        task.result = result
        return self._unblock(task_id)

    def cancel(self, task_id: str, reason: str) -> list[str]:
        """Mark a task as cancelled and unblock dependents.

        The cancellation is NOT transitive: dependents whose only blocker
        was this task will become READY, not cancelled.

        Returns a list of task IDs that became READY as a result.
        """
        task = self._tasks[task_id]
        task.status = TaskStatus.CANCELLED
        task.result = reason
        return self._unblock(task_id)

    def _unblock(self, completed_id: str) -> list[str]:
        """Remove completed_id from all dependents' blocked_by sets.

        Returns IDs of tasks that transitioned to READY.
        """
        newly_ready: list[str] = []
        for t in self._tasks.values():
            if completed_id in t.blocked_by:
                t.blocked_by.discard(completed_id)
                if not t.blocked_by and t.status == TaskStatus.PENDING:
                    t.status = TaskStatus.READY
                    newly_ready.append(t.id)
        return newly_ready

    def ready_tasks(self) -> list[Task]:
        """Return all tasks with status READY."""
        return [t for t in self._tasks.values() if t.status == TaskStatus.READY]

    def has_pending(self) -> bool:
        """Return True if any task is PENDING or READY."""
        return any(
            t.status in (TaskStatus.PENDING, TaskStatus.READY)
            for t in self._tasks.values()
        )

    def get(self, task_id: str) -> Task:
        """Look up a task by ID. Raises KeyError if not found."""
        return self._tasks[task_id]

    def all_tasks(self) -> list[Task]:
        """Return a snapshot of all tasks for observability."""
        return list(self._tasks.values())
