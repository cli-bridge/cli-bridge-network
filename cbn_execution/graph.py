"""Workflow graph primitives."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TaskNode:
    task_id: str
    uses: str
    needs: tuple[str, ...] = ()


@dataclass
class WorkflowGraph:
    tasks: list[TaskNode] = field(default_factory=list)

    def validate(self) -> None:
        seen: set[str] = set()
        for task in self.tasks:
            if task.task_id in seen:
                raise ValueError(f"duplicate task id: {task.task_id}")
            seen.add(task.task_id)
        for task in self.tasks:
            missing = [dep for dep in task.needs if dep not in seen]
            if missing:
                raise ValueError(f"task {task.task_id} depends on missing tasks: {missing}")

