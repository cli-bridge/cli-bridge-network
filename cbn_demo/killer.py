"""Killer demo report for the CLI-Anything macrocli -> mermaid workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cbn_core.message import validate_bridge_message
from cbn_core.manifest import ManifestRegistry
from cbn_core.bridge_contract import workflow_bridge_contract_report
from cbn_core.selector import bridge_value_to_arg, select_bridge_value
from cbn_protocol.bridge_lab import bridge_lab_report
from cbn_protocol.exports import export_all_workflow_protocols
from cbn_protocol.smoke_suite import protocol_smoke_suite
from cbn_workflow.catalog import inspect_workflow
from cbn_workflow.runner import WorkflowRunner
from cbn_execution.graph import WorkflowGraph


DEFAULT_KILLER_WORKFLOW_PATH = "workflows/cli-anything-macrocli-mermaid-routing.example.json"
KILLER_CAPABILITIES = (
    "cli-anything.macrocli.backends",
    "cbn.transform.macrocli-backends-to-mermaid",
    "cli-anything.mermaid.set-diagram",
)


@dataclass(frozen=True)
class KillerDemoRequest:
    workflow_path: str
    run: bool
    dry_run: bool
    confirmed: bool
    include_payloads: bool
    run_smoke_suite: bool
    event_tail: list[dict[str, Any]]
    audit_tail: list[dict[str, Any]]
    artifact_list: list[dict[str, Any]]


_KILLER_OPTION_NAMES = (
    "workflow_path",
    "run",
    "dry_run",
    "confirmed",
    "include_payloads",
    "run_smoke_suite",
    "event_tail",
    "audit_tail",
    "artifact_list",
)


def killer_demo_report(
    registry: ManifestRegistry,
    workflow_runner: WorkflowRunner | None = None,
    *args: Any,
    **options: Any,
) -> dict[str, Any]:
    """Return one product-facing evidence bundle for the MVP killer demo."""

    request = killer_demo_request(args, options)
    bundle = _killer_evidence_bundle(
        registry=registry,
        workflow_runner=workflow_runner,
        request=request,
    )
    return _killer_report_payload(request, bundle)


def killer_demo_request(args: tuple[Any, ...], options: dict[str, Any]) -> KillerDemoRequest:
    values = _killer_demo_options(args, options)
    return KillerDemoRequest(
        workflow_path=values["workflow_path"],
        run=values["run"],
        dry_run=values["dry_run"],
        confirmed=values["confirmed"],
        include_payloads=values["include_payloads"],
        run_smoke_suite=values["run_smoke_suite"],
        event_tail=values["event_tail"] or [],
        audit_tail=values["audit_tail"] or [],
        artifact_list=values["artifact_list"] or [],
    )


def _killer_demo_options(args: tuple[Any, ...], options: dict[str, Any]) -> dict[str, Any]:
    if len(args) > len(_KILLER_OPTION_NAMES):
        raise TypeError(f"killer_demo_report expected at most {len(_KILLER_OPTION_NAMES) + 2} arguments")
    values = _default_killer_demo_options()
    for name, value in zip(_KILLER_OPTION_NAMES, args):
        if name in options:
            raise TypeError(f"killer_demo_report got multiple values for argument '{name}'")
        values[name] = value
    unknown = sorted(set(options) - set(_KILLER_OPTION_NAMES))
    if unknown:
        raise TypeError(f"unknown killer demo option(s): {', '.join(unknown)}")
    values.update(options)
    return values


def _default_killer_demo_options() -> dict[str, Any]:
    return {
        "workflow_path": DEFAULT_KILLER_WORKFLOW_PATH,
        "run": True,
        "dry_run": True,
        "confirmed": False,
        "include_payloads": False,
        "run_smoke_suite": True,
        "event_tail": None,
        "audit_tail": None,
        "artifact_list": None,
    }


def _killer_evidence_bundle(
    *,
    registry: ManifestRegistry,
    workflow_runner: WorkflowRunner | None,
    request: KillerDemoRequest,
) -> dict[str, Any]:
    base = _killer_base_evidence(registry, request.workflow_path)
    runtime = _killer_runtime_bundle(
        registry=registry,
        workflow_runner=workflow_runner,
        workflow=base["workflow"],
        request=request,
    )
    stages = _killer_stages(base, runtime)
    summary = _killer_summary(stages, base, runtime)
    return _killer_bundle_payload(summary, stages, base, runtime)


def _killer_stages(base: dict[str, Any], runtime: dict[str, Any]) -> list[dict[str, Any]]:
    return _stages(
        manifests=base["manifests"],
        workflow=base["workflow"],
        contract=base["contract"],
        run_result=runtime["run_result"],
        evidence=runtime["evidence"],
        smoke=runtime["smoke"],
        lab=runtime["lab"],
    )


def _killer_summary(
    stages: list[dict[str, Any]],
    base: dict[str, Any],
    runtime: dict[str, Any],
) -> dict[str, Any]:
    return _summary(
        stages,
        base["contract"],
        runtime["run_result"],
        runtime["evidence"],
        runtime["smoke"],
        runtime["lab"],
        runtime["communication_trace"],
    )


def _killer_bundle_payload(
    summary: dict[str, Any],
    stages: list[dict[str, Any]],
    base: dict[str, Any],
    runtime: dict[str, Any],
) -> dict[str, Any]:
    return {
        "summary": summary,
        "stages": stages,
        **base,
        **runtime,
    }


def _killer_base_evidence(registry: ManifestRegistry, workflow_path: str) -> dict[str, Any]:
    return {
        "manifests": _manifest_evidence(registry),
        "workflow": inspect_workflow(Path(workflow_path), registry=registry),
        "contract": workflow_bridge_contract_report(registry, workflow_path=workflow_path),
        "protocol_exports": export_all_workflow_protocols(registry, workflow_path=workflow_path),
    }


def _killer_runtime_bundle(
    *,
    registry: ManifestRegistry,
    workflow_runner: WorkflowRunner | None,
    workflow: dict[str, Any],
    request: KillerDemoRequest,
) -> dict[str, Any]:
    run_result = (
        _run_workflow(workflow_runner, request.workflow_path, dry_run=request.dry_run, confirmed=request.confirmed)
        if request.run
        else _skipped_run()
    )
    return {
        "run_result": run_result,
        "communication_trace": _communication_trace(workflow=workflow, run_result=run_result),
        "evidence": _runtime_evidence(run_result, request.event_tail, request.audit_tail, request.artifact_list),
        "smoke": _smoke_suite_evidence(
            registry,
            request.workflow_path,
            request.confirmed,
            request.include_payloads,
            request.run_smoke_suite,
        ),
        "lab": _bridge_lab_evidence(registry, workflow_runner, request),
    }


def _smoke_suite_evidence(
    registry: ManifestRegistry,
    workflow_path: str,
    confirmed: bool,
    include_payloads: bool,
    run_smoke_suite: bool,
) -> dict[str, Any]:
    if not run_smoke_suite:
        return {
            "ok": None,
            "run": False,
            "status": "not_run",
            "reason": "smoke suite disabled",
        }
    return protocol_smoke_suite(
        registry,
        capability_ids=("git.version",),
        workflow_paths=(workflow_path,),
        workflow_dry_run=True,
        workflow_confirmed=confirmed,
        include_payloads=include_payloads,
    )


def _bridge_lab_evidence(
    registry: ManifestRegistry,
    workflow_runner: WorkflowRunner | None,
    request: KillerDemoRequest,
) -> dict[str, Any]:
    return bridge_lab_report(
        registry,
        workflow_runner,
        workflow_paths=(request.workflow_path,),
        run=request.run,
        dry_run=request.dry_run,
        confirmed=request.confirmed,
        include_payloads=request.include_payloads,
        run_smoke_suite=request.run_smoke_suite,
    )


def _killer_report_payload(request: KillerDemoRequest, bundle: dict[str, Any]) -> dict[str, Any]:
    summary = bundle["summary"]
    run_result = bundle["run_result"]
    lab = bundle["lab"]
    return {
        "ok": bool(summary["ok"]),
        "apiVersion": "demo.cbn.dev/v1alpha1",
        "kind": "CbnKillerDemoReport",
        "workflow_path": request.workflow_path,
        "run": request.run,
        "dry_run": request.dry_run,
        "confirmed": request.confirmed,
        "include_payloads": request.include_payloads,
        "run_smoke_suite": request.run_smoke_suite,
        "summary": summary,
        "stages": bundle["stages"],
        "manifests": bundle["manifests"],
        "workflow": bundle["workflow"],
        "contract": bundle["contract"],
        "run_result": run_result if request.include_payloads else _bounded_run_result(run_result),
        "communication_trace": bundle["communication_trace"],
        "evidence": bundle["evidence"],
        "protocol_exports": bundle["protocol_exports"],
        "protocol_smoke_suite": bundle["smoke"],
        "bridge_lab": lab if request.include_payloads else _bounded_bridge_lab(lab),
        "next_commands": _next_commands(request.workflow_path, request.run_smoke_suite),
    }


def _manifest_evidence(registry: ManifestRegistry) -> list[dict[str, Any]]:
    rows = []
    for capability_id in KILLER_CAPABILITIES:
        try:
            manifest = registry.require(capability_id)
            rows.append(
                {
                    "capability_id": capability_id,
                    "ready": True,
                    "title": manifest.title,
                    "transport": manifest.transport.kind,
                    "parser_ref": manifest.output.parser_ref,
                    "output_verified": manifest.output.verified,
                    "risk": manifest.policy.risk,
                    "requires_confirmation": manifest.policy.requires_confirmation,
                }
            )
        except KeyError as exc:
            rows.append(
                {
                    "capability_id": capability_id,
                    "ready": False,
                    "error": str(exc),
                }
            )
    return rows


def _run_workflow(
    workflow_runner: WorkflowRunner | None,
    workflow_path: str,
    dry_run: bool,
    confirmed: bool,
) -> dict[str, Any]:
    if workflow_runner is None:
        return {
            "status": "not_run",
            "ok": False,
            "skipped": True,
            "reason": "workflow_runner was not provided",
        }
    graph = WorkflowGraph.from_file(Path(workflow_path))
    result = workflow_runner.run(graph, dry_run=dry_run, confirmed=confirmed)
    result["ok"] = result.get("status") == "completed"
    return result


def _skipped_run() -> dict[str, Any]:
    return {
        "status": "not_run",
        "ok": None,
        "skipped": True,
        "reason": "run disabled",
    }


def _runtime_evidence(
    run_result: dict[str, Any],
    event_tail: list[dict[str, Any]],
    audit_tail: list[dict[str, Any]],
    artifact_list: list[dict[str, Any]],
) -> dict[str, Any]:
    task_artifacts = []
    for task in run_result.get("tasks", []):
        result = task.get("result") if isinstance(task, dict) else None
        if not isinstance(result, dict):
            continue
        for artifact in result.get("artifacts", []):
            if isinstance(artifact, dict):
                task_artifacts.append(artifact)
    return {
        "run_id": run_result.get("run_id"),
        "task_artifact_count": len(task_artifacts),
        "task_artifacts": task_artifacts[:20],
        "event_count": len(event_tail),
        "events": event_tail[:30],
        "audit_count": len(audit_tail),
        "audit": audit_tail[:30],
        "artifact_count": len(artifact_list),
        "artifacts": artifact_list[:30],
    }


def _communication_trace(*, workflow: dict[str, Any], run_result: dict[str, Any]) -> dict[str, Any]:
    """Build a bounded CLI-CLI handoff trace from BridgeMessage selector routes."""

    handoffs = _communication_handoffs(workflow=workflow, run_result=run_result)
    ready = bool(handoffs) and all(item.get("message_valid") for item in handoffs)
    return {
        "kind": "CliCliCommunicationTrace",
        "status": "ready" if ready else "needs_attention",
        "workflow_id": workflow.get("workflow_id"),
        "handoff_count": len(handoffs),
        "message_valid_count": sum(1 for handoff in handoffs if handoff.get("message_valid")),
        "handoffs": handoffs,
    }


def _communication_handoffs(
    *,
    workflow: dict[str, Any],
    run_result: dict[str, Any],
) -> list[dict[str, Any]]:
    tasks = _workflow_tasks(workflow)
    task_results = _task_results_by_id(run_result)
    handoffs: list[dict[str, Any]] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        consumer_id = str(task.get("id") or task.get("task_id") or "")
        args_from = task.get("argsFrom") if isinstance(task.get("argsFrom"), list) else []
        consumer_result = task_results.get(consumer_id, {})
        resolved_args = consumer_result.get("resolved_args") if isinstance(consumer_result.get("resolved_args"), list) else []
        for route_index, route in enumerate(args_from):
            if not isinstance(route, dict):
                continue
            handoffs.append(
                _communication_handoff(
                    index=len(handoffs) + 1,
                    task=task,
                    route=route,
                    route_index=route_index,
                    consumer_id=consumer_id,
                    task_results=task_results,
                    resolved_args=resolved_args,
                )
            )
    return handoffs


def _workflow_tasks(workflow: dict[str, Any]) -> list[Any]:
    return workflow.get("tasks") if isinstance(workflow.get("tasks"), list) else []


def _task_results_by_id(run_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(task.get("task_id")): task
        for task in run_result.get("tasks", [])
        if isinstance(task, dict) and task.get("task_id")
    }


def _communication_handoff(
    *,
    index: int,
    task: dict[str, Any],
    route: dict[str, Any],
    route_index: int,
    consumer_id: str,
    task_results: dict[str, dict[str, Any]],
    resolved_args: list[Any],
) -> dict[str, Any]:
    producer_id = str(route.get("task") or "")
    selector = str(route.get("selector") or "")
    producer_result = task_results.get(producer_id, {})
    producer_call = producer_result.get("result") if isinstance(producer_result.get("result"), dict) else {}
    message = producer_call.get("message") if isinstance(producer_call.get("message"), dict) else {}
    validation = validate_bridge_message(message) if message else {"valid": False, "errors": ["message missing"]}
    selected = _selected_value(message, selector)
    selected_value = selected.get("value")
    resolved_arg = _resolved_handoff_arg(resolved_args, route_index, selected, selected_value)
    return {
        "index": index,
        "kind": "CliCliBridgeHandoff",
        "communication": "BridgeMessage argsFrom",
        "producer_task": producer_id,
        "producer_capability": producer_result.get("uses"),
        "consumer_task": consumer_id,
        "consumer_capability": task.get("uses"),
        "selector": selector,
        "message_kind": message.get("kind"),
        "message_channel": _message_channel(message),
        "parser_ref": _message_parser_ref(message),
        "message_valid": validation.get("valid"),
        "message_errors": validation.get("errors", [])[:3],
        "selected_type": _value_type(selected_value) if selected.get("ok") else None,
        "selected_preview": _preview_value(selected_value) if selected.get("ok") else selected.get("error"),
        "resolved_arg_preview": _preview_value(resolved_arg),
        "artifact_ids": _artifact_ids(producer_call),
    }


def _resolved_handoff_arg(
    resolved_args: list[Any],
    route_index: int,
    selected: dict[str, Any],
    selected_value: Any,
) -> Any:
    if route_index < len(resolved_args):
        return resolved_args[route_index]
    return bridge_value_to_arg(selected_value) if selected.get("ok") else None


def _message_metadata(message: dict[str, Any]) -> dict[str, Any]:
    return message.get("metadata") if isinstance(message.get("metadata"), dict) else {}


def _message_channel(message: dict[str, Any]) -> Any:
    metadata = _message_metadata(message)
    return metadata.get("channel") or message.get("channel")


def _message_parser_ref(message: dict[str, Any]) -> Any:
    return _message_metadata(message).get("parser_ref")


def _selected_value(message: dict[str, Any], selector: str) -> dict[str, Any]:
    if not message or not selector:
        return {"ok": False, "error": "message or selector missing"}
    try:
        selected = select_bridge_value(message, selector)
        return {"ok": True, "value": selected.get("value")}
    except (KeyError, ValueError, TypeError) as exc:
        return {"ok": False, "error": str(exc)}


def _artifact_ids(result: dict[str, Any]) -> list[str]:
    artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), list) else []
    return [
        str(artifact.get("artifact_id"))
        for artifact in artifacts
        if isinstance(artifact, dict) and artifact.get("artifact_id")
    ][:6]


def _value_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if value is None:
        return "null"
    return type(value).__name__


def _preview_value(value: Any, *, limit: int = 180) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value
    else:
        text = str(value)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _stages(
    manifests: list[dict[str, Any]],
    workflow: dict[str, Any],
    contract: dict[str, Any],
    run_result: dict[str, Any],
    evidence: dict[str, Any],
    smoke: dict[str, Any],
    lab: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        *_manifest_stage_rows(manifests),
        *_workflow_stage_rows(contract, run_result),
        *_runtime_stage_rows(workflow, run_result, evidence, smoke, lab),
    ]


def _manifest_stage_rows(manifests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": "import_cli_anything_harness",
            "title": "Import CLI-Anything harness",
            "status": "completed" if manifests[0].get("ready") and manifests[2].get("ready") else "blocked",
            "evidence": {
                "macrocli_manifest_ready": manifests[0].get("ready"),
                "mermaid_manifest_ready": manifests[2].get("ready"),
            },
        },
        {
            "id": "generate_manifest",
            "title": "Generate or reuse ToolManifest",
            "status": "completed" if all(row.get("ready") for row in manifests) else "blocked",
            "evidence": {"capabilities": [row["capability_id"] for row in manifests if row.get("ready")]},
        },
    ]


def _workflow_stage_rows(contract: dict[str, Any], run_result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": "run_macrocli",
            "title": "Run macrocli backend listing",
            "status": _task_stage_status(run_result, "macrocli-backends"),
            "evidence": _task_evidence(run_result, "macrocli-backends"),
        },
        {
            "id": "parse_payload",
            "title": "Parse BridgeMessage payload",
            "status": "completed" if contract.get("ok") else "blocked",
            "evidence": {
                "contract_ok": contract.get("ok"),
                "route_count": (contract.get("summary") or {}).get("route_count"),
            },
        },
        {
            "id": "transform_to_mermaid",
            "title": "Transform payload to Mermaid source",
            "status": _task_stage_status(run_result, "backend-diagram-source"),
            "evidence": _task_evidence(run_result, "backend-diagram-source"),
        },
        {
            "id": "run_mermaid",
            "title": "Run mermaid consumer",
            "status": _task_stage_status(run_result, "mermaid-consumer"),
            "evidence": _task_evidence(run_result, "mermaid-consumer"),
        },
    ]


def _runtime_stage_rows(
    workflow: dict[str, Any],
    run_result: dict[str, Any],
    evidence: dict[str, Any],
    smoke: dict[str, Any],
    lab: dict[str, Any],
) -> list[dict[str, Any]]:
    run_status = run_result.get("status")
    return [
        _artifact_event_audit_stage(evidence),
        _protocol_smoke_stage(smoke),
        _workflow_studio_stage(workflow, lab, run_status),
    ]


def _artifact_event_audit_stage(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "show_artifact_event_audit",
        "title": "Show artifact, event and audit evidence",
        "status": "completed" if evidence["task_artifact_count"] > 0 else "blocked",
        "evidence": {
            "run_id": evidence.get("run_id"),
            "task_artifact_count": evidence["task_artifact_count"],
            "event_count": evidence["event_count"],
            "audit_count": evidence["audit_count"],
        },
    }


def _protocol_smoke_stage(smoke: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "export_mcp_a2a_smoke",
        "title": "Export MCP/A2A/ACP smoke",
        "status": "completed" if smoke.get("ok") is True else "not_run" if smoke.get("ok") is None else "blocked",
        "evidence": {
            "run": smoke.get("run"),
            "ok": smoke.get("ok"),
            "failed_count": (smoke.get("summary") or {}).get("failed_count"),
        },
    }


def _workflow_studio_stage(workflow: dict[str, Any], lab: dict[str, Any], run_status: Any) -> dict[str, Any]:
    return {
        "id": "workflow_studio_ready",
        "title": "Workflow Studio display bundle",
        "status": "completed" if workflow.get("valid") and lab.get("ok") and run_status == "completed" else "blocked",
        "evidence": {
            "workflow_valid": workflow.get("valid"),
            "bridge_lab_ok": lab.get("ok"),
            "run_status": run_status,
        },
    }


def _task_stage_status(run_result: dict[str, Any], task_id: str) -> str:
    if run_result.get("status") == "not_run":
        return "not_run"
    task = _task(run_result, task_id)
    if not task:
        return "blocked"
    return "completed" if task.get("status") == "completed" else str(task.get("status") or "blocked")


def _task_evidence(run_result: dict[str, Any], task_id: str) -> dict[str, Any]:
    task = _task(run_result, task_id)
    if not task:
        return {}
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    parsed = result.get("parsed") if isinstance(result.get("parsed"), dict) else {}
    return {
        "task_id": task.get("task_id"),
        "uses": task.get("uses"),
        "status": task.get("status"),
        "parser_ref": parsed.get("parser_ref"),
        "parser_ok": parsed.get("ok"),
        "artifact_ids": [
            artifact.get("artifact_id")
            for artifact in result.get("artifacts", [])
            if isinstance(artifact, dict)
        ],
    }


def _task(run_result: dict[str, Any], task_id: str) -> dict[str, Any] | None:
    for task in run_result.get("tasks", []):
        if isinstance(task, dict) and task.get("task_id") == task_id:
            return task
    return None


def _summary(
    stages: list[dict[str, Any]],
    contract: dict[str, Any],
    run_result: dict[str, Any],
    evidence: dict[str, Any],
    smoke: dict[str, Any],
    lab: dict[str, Any],
    communication_trace: dict[str, Any],
) -> dict[str, Any]:
    completed = sum(1 for stage in stages if stage["status"] == "completed")
    blocked = sum(1 for stage in stages if stage["status"] not in {"completed", "not_run"})
    smoke_ok = smoke.get("ok")
    ok = bool(
        blocked == 0
        and contract.get("ok")
        and run_result.get("status") in {"completed", "not_run"}
        and evidence.get("task_artifact_count", 0) > 0
        and smoke_ok is not False
        and lab.get("ok")
    )
    return {
        "ok": ok,
        "stage_count": len(stages),
        "completed_stage_count": completed,
        "blocked_stage_count": blocked,
        "workflow_status": run_result.get("status"),
        "route_count": (contract.get("summary") or {}).get("route_count", 0),
        "artifact_count": evidence.get("task_artifact_count", 0),
        "communication_handoff_count": communication_trace.get("handoff_count", 0),
        "communication_trace_status": communication_trace.get("status"),
        "smoke_ok": smoke_ok,
        "bridge_lab_ok": lab.get("ok"),
        "recommended_next_action": "open_workflow_studio_demo" if ok else _next_action(stages),
    }


def _next_action(stages: list[dict[str, Any]]) -> str:
    for stage in stages:
        if stage["status"] not in {"completed", "not_run"}:
            return f"fix_{stage['id']}"
    return "run_protocol_smoke_suite"


def _bounded_run_result(run_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": run_result.get("ok"),
        "run_id": run_result.get("run_id"),
        "workflow_id": run_result.get("workflow_id"),
        "status": run_result.get("status"),
        "summary": run_result.get("summary"),
        "recovery": run_result.get("recovery"),
        "tasks": [
            {
                "task_id": task.get("task_id"),
                "uses": task.get("uses"),
                "status": task.get("status"),
                "recovery": task.get("recovery"),
            }
            for task in run_result.get("tasks", [])
            if isinstance(task, dict)
        ],
    }


def _bounded_bridge_lab(lab: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": lab.get("ok"),
        "kind": lab.get("kind"),
        "workflow_paths": lab.get("workflow_paths"),
        "summary": lab.get("summary"),
        "route_catalog": lab.get("route_catalog"),
        "wire_compatible": lab.get("wire_compatible"),
    }


def _next_commands(workflow_path: str, run_smoke_suite: bool) -> list[str]:
    commands = [
        f"python -m cbn demo killer --workflow-path {workflow_path} --run --dry-run",
        f"python -m cbn protocol bridge-lab --workflow-path {workflow_path} --run --dry-run",
        f"python -m cbn protocol export-workflows all --path {workflow_path}",
    ]
    if not run_smoke_suite:
        commands.append(f"python -m cbn demo killer --workflow-path {workflow_path} --smoke-suite")
    return commands
