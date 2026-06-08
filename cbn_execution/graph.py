"""Workflow graph primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TaskNode:
    task_id: str
    uses: str
    args: tuple[str, ...] = ()
    needs: tuple[str, ...] = ()
    dry_run: bool = False
    approval_id: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TaskNode":
        return cls(
            task_id=raw["id"],
            uses=raw["uses"],
            args=tuple(str(arg) for arg in raw.get("args", [])),
            needs=tuple(raw.get("needs", [])),
            dry_run=bool(raw.get("dryRun", False)),
            approval_id=raw.get("approvalId"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.task_id,
            "uses": self.uses,
            "args": list(self.args),
            "needs": list(self.needs),
            "dryRun": self.dry_run,
            "approvalId": self.approval_id,
        }


@dataclass
class WorkflowGraph:
    workflow_id: str = "workflow"
    title: str = "Workflow"
    tasks: list[TaskNode] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "WorkflowGraph":
        if raw.get("apiVersion") != "bridge.dev/v1alpha1":
            raise ValueError(f"unsupported workflow apiVersion: {raw.get('apiVersion')}")
        if raw.get("kind") != "Workflow":
            raise ValueError(f"unsupported workflow kind: {raw.get('kind')}")
        metadata = raw.get("metadata", {})
        spec = raw.get("spec", {})
        return cls(
            workflow_id=metadata.get("id", "workflow"),
            title=metadata.get("title", metadata.get("id", "Workflow")),
            tasks=[TaskNode.from_dict(task) for task in spec.get("tasks", [])],
        )

    @classmethod
    def from_file(cls, path: Path) -> "WorkflowGraph":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def validate(self) -> None:
        if not self.tasks:
            raise ValueError("workflow must contain at least one task")
        seen: set[str] = set()
        for task in self.tasks:
            if task.task_id in seen:
                raise ValueError(f"duplicate task id: {task.task_id}")
            seen.add(task.task_id)
        for task in self.tasks:
            missing = [dep for dep in task.needs if dep not in seen]
            if missing:
                raise ValueError(f"task {task.task_id} depends on missing tasks: {missing}")
        self.topological_order()

    def topological_order(self) -> list[TaskNode]:
        by_id = {task.task_id: task for task in self.tasks}
        remaining = set(by_id)
        completed: set[str] = set()
        ordered: list[TaskNode] = []
        while remaining:
            ready = sorted(
                task_id
                for task_id in remaining
                if all(dep in completed for dep in by_id[task_id].needs)
            )
            if not ready:
                raise ValueError(f"workflow contains a dependency cycle: {sorted(remaining)}")
            for task_id in ready:
                ordered.append(by_id[task_id])
                completed.add(task_id)
                remaining.remove(task_id)
        return ordered

    def as_plan(self) -> dict[str, Any]:
        self.validate()
        return {
            "workflow_id": self.workflow_id,
            "title": self.title,
            "tasks": [task.as_dict() for task in self.topological_order()],
        }
