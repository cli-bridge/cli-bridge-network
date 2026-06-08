"""Minimal deterministic workflow DAG runner."""

from __future__ import annotations

import uuid
from typing import Any

from cbn_audit.log import AuditLog
from cbn_events.bus import EventBus
from cbn_execution.executor import CapabilityExecutor
from cbn_execution.graph import WorkflowGraph
from protocol import EventType


class WorkflowRunner:
    def __init__(
        self,
        executor: CapabilityExecutor,
        event_bus: EventBus | None = None,
        audit_log: AuditLog | None = None,
    ) -> None:
        self.executor = executor
        self.event_bus = event_bus
        self.audit_log = audit_log

    def plan(self, graph: WorkflowGraph) -> dict[str, Any]:
        return graph.as_plan()

    def run(
        self,
        graph: WorkflowGraph,
        dry_run: bool = False,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        graph.validate()
        run_id = str(uuid.uuid4())
        self._audit("workflow.started", run_id, graph.workflow_id, {"dry_run": dry_run})
        self._publish(EventType.WORKFLOW_STARTED, graph.workflow_id, {"dry_run": dry_run}, run_id)
        task_results: list[dict[str, Any]] = []
        status = "completed"

        for task in graph.topological_order():
            self._publish(
                EventType.WORKFLOW_TASK_STARTED,
                graph.workflow_id,
                {"task": task.as_dict()},
                run_id,
            )
            result = self.executor.call(
                task.uses,
                extra_args=task.args,
                dry_run=dry_run or task.dry_run,
                confirmed=confirmed,
                approval_id=task.approval_id,
            )
            task_result = {
                "task_id": task.task_id,
                "uses": task.uses,
                "result": result,
            }
            task_results.append(task_result)
            self._publish(
                EventType.WORKFLOW_TASK_COMPLETED,
                graph.workflow_id,
                task_result,
                run_id,
            )
            if not result.get("allowed"):
                status = "blocked"
                break
            if result.get("exit_code") not in (0, None):
                status = "failed"
                break

        payload = {
            "run_id": run_id,
            "workflow_id": graph.workflow_id,
            "status": status,
            "tasks": task_results,
        }
        self._audit("workflow.completed", run_id, graph.workflow_id, payload)
        self._publish(EventType.WORKFLOW_COMPLETED, graph.workflow_id, payload, run_id)
        return payload

    def _publish(
        self,
        event_type: EventType,
        subject: str,
        payload: dict[str, Any],
        run_id: str,
    ) -> None:
        if self.event_bus is None:
            return
        self.event_bus.publish(str(event_type), subject, payload, correlation_id=run_id)

    def _audit(
        self,
        event_type: str,
        run_id: str,
        workflow_id: str,
        payload: dict[str, Any],
    ) -> None:
        if self.audit_log is None:
            return
        self.audit_log.append(
            {
                "type": event_type,
                "workflow_run_id": run_id,
                "workflow_id": workflow_id,
                "payload": payload,
            }
        )
