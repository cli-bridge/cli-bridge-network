"""Minimal deterministic workflow DAG runner."""

from __future__ import annotations

import uuid
from typing import Any

from cbn_audit.log import AuditLog
from cbn_events.bus import EventBus
from cbn_execution.executor import CapabilityExecutor
from cbn_execution.graph import TaskNode, WorkflowGraph
from cbn_protocol.envelope import bridge_value_to_arg, select_bridge_value
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
        results_by_task: dict[str, dict[str, Any]] = {}
        status = "completed"
        stopped_by: str | None = None

        ordered_tasks = graph.topological_order()
        for index, task in enumerate(ordered_tasks):
            try:
                resolved_args = self._resolve_args(task, results_by_task)
            except (KeyError, ValueError, TypeError) as exc:
                status = "failed"
                stopped_by = task.task_id
                task_result = _failed_task_result(
                    task,
                    error_kind="args_resolution_failed",
                    error=str(exc),
                    recovery_action="fix_args_from_selector",
                )
                task_results.append(task_result)
                results_by_task[task.task_id] = task_result
                self._publish(
                    EventType.WORKFLOW_TASK_COMPLETED,
                    graph.workflow_id,
                    task_result,
                    run_id,
                )
                task_results.extend(_skipped_downstream_tasks(ordered_tasks[index + 1 :], stopped_by))
                break
            self._publish(
                EventType.WORKFLOW_TASK_STARTED,
                graph.workflow_id,
                {"task": task.as_dict(), "resolved_args": list(resolved_args)},
                run_id,
            )
            result = self.executor.call(
                task.uses,
                extra_args=resolved_args,
                dry_run=dry_run or task.dry_run,
                confirmed=confirmed,
                approval_id=task.approval_id,
            )
            task_result = {
                "task_id": task.task_id,
                "uses": task.uses,
                "status": _task_status(result),
                "attempt": 1,
                "resolved_args": list(resolved_args),
                "result": result,
                "recovery": _task_recovery(result),
            }
            task_results.append(task_result)
            results_by_task[task.task_id] = task_result
            self._publish(
                EventType.WORKFLOW_TASK_COMPLETED,
                graph.workflow_id,
                task_result,
                run_id,
            )
            if not result.get("allowed"):
                status = "blocked"
                stopped_by = task.task_id
                task_results.extend(_skipped_downstream_tasks(ordered_tasks[index + 1 :], stopped_by))
                break
            if not result.get("ok"):
                status = "failed"
                stopped_by = task.task_id
                task_results.extend(_skipped_downstream_tasks(ordered_tasks[index + 1 :], stopped_by))
                break

        payload = {
            "run_id": run_id,
            "workflow_id": graph.workflow_id,
            "status": status,
            "summary": _workflow_summary(task_results),
            "recovery": _workflow_recovery(status, stopped_by, task_results),
            "tasks": task_results,
        }
        self._audit("workflow.completed", run_id, graph.workflow_id, payload)
        self._publish(EventType.WORKFLOW_COMPLETED, graph.workflow_id, payload, run_id)
        return payload

    def _resolve_args(
        self,
        task: TaskNode,
        results_by_task: dict[str, dict[str, Any]],
    ) -> tuple[str, ...]:
        args = list(task.args)
        for arg_from in task.args_from:
            source = results_by_task[arg_from.task_id]["result"]["message"]
            selected = select_bridge_value(source, arg_from.selector)["value"]
            args.append(bridge_value_to_arg(selected))
        return tuple(args)

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


def _task_status(result: dict[str, Any]) -> str:
    if not result.get("allowed"):
        return "blocked"
    if result.get("ok"):
        return "completed"
    parsed = result.get("parsed")
    if isinstance(parsed, dict):
        data = parsed.get("data")
        if isinstance(data, dict) and data.get("setup_required"):
            return "setup_required"
    return "failed"


def _task_recovery(result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("allowed"):
        return {
            "retryable": True,
            "action": "request_approval",
            "reason": _decision_reason(result),
            "approval_id": _approval_id(result),
            "resume_mode": "rerun_after_approval",
        }
    parsed = result.get("parsed")
    if isinstance(parsed, dict):
        if parsed.get("ok") is False:
            return {
                "retryable": True,
                "action": "fix_parser_or_command_output",
                "reason": parsed.get("error"),
                "resume_mode": "rerun_task_or_workflow",
            }
        data = parsed.get("data")
        if isinstance(data, dict) and data.get("setup_required"):
            return {
                "retryable": True,
                "action": "complete_setup",
                "reason": data.get("error_type"),
                "next_action": data.get("next_action"),
                "resume_mode": "rerun_after_setup",
            }
    if result.get("ok"):
        return {"retryable": False, "action": None, "resume_mode": None}
    return {
        "retryable": True,
        "action": _recovery_action_for_reason(str(result.get("reason") or "")),
        "reason": result.get("reason"),
        "resume_mode": "rerun_task_or_workflow",
    }


def _decision_reason(result: dict[str, Any]) -> str | None:
    decision = result.get("decision")
    if isinstance(decision, dict):
        reason = decision.get("reason")
        return str(reason) if reason else None
    return None


def _approval_id(result: dict[str, Any]) -> str | None:
    approval = result.get("approval")
    if isinstance(approval, dict):
        approval_id = approval.get("approval_id")
        return str(approval_id) if approval_id else None
    return None


def _recovery_action_for_reason(reason: str) -> str:
    if reason in {"timeout", "spawn_failed"}:
        return "repair_runtime_or_retry"
    if reason == "nonzero_exit":
        return "inspect_stderr_and_retry"
    return "inspect_failure_and_retry"


def _failed_task_result(
    task: TaskNode,
    error_kind: str,
    error: str,
    recovery_action: str,
) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "uses": task.uses,
        "status": "failed",
        "attempt": 1,
        "resolved_args": [],
        "result": {
            "ok": False,
            "allowed": True,
            "reason": error_kind,
            "error": error,
        },
        "recovery": {
            "retryable": True,
            "action": recovery_action,
            "reason": error,
            "resume_mode": "rerun_after_fix",
        },
    }


def _skipped_downstream_tasks(tasks: list[TaskNode], stopped_by: str) -> list[dict[str, Any]]:
    skipped = []
    for task in tasks:
        skipped.append(
            {
                "task_id": task.task_id,
                "uses": task.uses,
                "status": "skipped",
                "attempt": 0,
                "resolved_args": [],
                "result": {
                    "ok": False,
                    "allowed": False,
                    "reason": "upstream_not_completed",
                    "upstream_task_id": stopped_by,
                },
                "recovery": {
                    "retryable": True,
                    "action": "resume_after_upstream_recovery",
                    "reason": f"upstream task {stopped_by} did not complete",
                    "resume_mode": "rerun_after_fix",
                },
            }
        )
    return skipped


def _workflow_summary(task_results: list[dict[str, Any]]) -> dict[str, int]:
    statuses = ("completed", "blocked", "failed", "setup_required", "skipped")
    summary = {"task_count": len(task_results)}
    for status in statuses:
        summary[f"{status}_count"] = sum(1 for task in task_results if task.get("status") == status)
    return summary


def _workflow_recovery(
    status: str,
    stopped_by: str | None,
    task_results: list[dict[str, Any]],
) -> dict[str, Any]:
    blocking_task = next((task for task in task_results if task.get("task_id") == stopped_by), None)
    task_recovery = blocking_task.get("recovery") if isinstance(blocking_task, dict) else None
    if status == "completed":
        return {"retryable": False, "action": None, "stopped_by": None}
    if isinstance(task_recovery, dict):
        return {
            "retryable": bool(task_recovery.get("retryable")),
            "action": task_recovery.get("action"),
            "stopped_by": stopped_by,
            "resume_mode": task_recovery.get("resume_mode"),
            "reason": task_recovery.get("reason"),
        }
    return {
        "retryable": True,
        "action": "inspect_failure_and_retry",
        "stopped_by": stopped_by,
        "resume_mode": "rerun_after_fix",
    }
