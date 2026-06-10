"""Killer demo report for the CLI-Anything macrocli -> mermaid workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbn_core.manifest import ManifestRegistry
from cbn_protocol.bridge_contract import workflow_bridge_contract_report
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


def killer_demo_report(
    registry: ManifestRegistry,
    workflow_runner: WorkflowRunner | None = None,
    workflow_path: str = DEFAULT_KILLER_WORKFLOW_PATH,
    run: bool = True,
    dry_run: bool = True,
    confirmed: bool = False,
    include_payloads: bool = False,
    run_smoke_suite: bool = True,
    event_tail: list[dict[str, Any]] | None = None,
    audit_tail: list[dict[str, Any]] | None = None,
    artifact_list: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return one product-facing evidence bundle for the MVP killer demo."""

    manifests = _manifest_evidence(registry)
    workflow = inspect_workflow(Path(workflow_path), registry=registry)
    contract = workflow_bridge_contract_report(registry, workflow_path=workflow_path)
    run_result = (
        _run_workflow(workflow_runner, workflow_path, dry_run=dry_run, confirmed=confirmed)
        if run
        else _skipped_run()
    )
    protocol_exports = export_all_workflow_protocols(registry, workflow_path=workflow_path)
    smoke = (
        protocol_smoke_suite(
            registry,
            capability_ids=("git.version",),
            workflow_paths=(workflow_path,),
            workflow_dry_run=True,
            workflow_confirmed=confirmed,
            include_payloads=include_payloads,
        )
        if run_smoke_suite
        else {
            "ok": None,
            "run": False,
            "status": "not_run",
            "reason": "smoke suite disabled",
        }
    )
    lab = bridge_lab_report(
        registry,
        workflow_runner,
        workflow_paths=(workflow_path,),
        run=run,
        dry_run=dry_run,
        confirmed=confirmed,
        include_payloads=include_payloads,
        run_smoke_suite=run_smoke_suite,
    )
    evidence = _runtime_evidence(
        run_result=run_result,
        event_tail=event_tail or [],
        audit_tail=audit_tail or [],
        artifact_list=artifact_list or [],
    )
    stages = _stages(
        manifests=manifests,
        workflow=workflow,
        contract=contract,
        run_result=run_result,
        evidence=evidence,
        smoke=smoke,
        lab=lab,
    )
    summary = _summary(stages, contract, run_result, evidence, smoke, lab)
    return {
        "ok": bool(summary["ok"]),
        "apiVersion": "demo.cbn.dev/v1alpha1",
        "kind": "CbnKillerDemoReport",
        "workflow_path": workflow_path,
        "run": run,
        "dry_run": dry_run,
        "confirmed": confirmed,
        "include_payloads": include_payloads,
        "run_smoke_suite": run_smoke_suite,
        "summary": summary,
        "stages": stages,
        "manifests": manifests,
        "workflow": workflow,
        "contract": contract,
        "run_result": run_result if include_payloads else _bounded_run_result(run_result),
        "evidence": evidence,
        "protocol_exports": protocol_exports,
        "protocol_smoke_suite": smoke,
        "bridge_lab": lab if include_payloads else _bounded_bridge_lab(lab),
        "next_commands": _next_commands(workflow_path, run_smoke_suite),
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


def _stages(
    manifests: list[dict[str, Any]],
    workflow: dict[str, Any],
    contract: dict[str, Any],
    run_result: dict[str, Any],
    evidence: dict[str, Any],
    smoke: dict[str, Any],
    lab: dict[str, Any],
) -> list[dict[str, Any]]:
    run_status = run_result.get("status")
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
        {
            "id": "show_artifact_event_audit",
            "title": "Show artifact, event and audit evidence",
            "status": "completed" if evidence["task_artifact_count"] > 0 else "blocked",
            "evidence": {
                "run_id": evidence.get("run_id"),
                "task_artifact_count": evidence["task_artifact_count"],
                "event_count": evidence["event_count"],
                "audit_count": evidence["audit_count"],
            },
        },
        {
            "id": "export_mcp_a2a_smoke",
            "title": "Export MCP/A2A/ACP smoke",
            "status": "completed" if smoke.get("ok") is True else "not_run" if smoke.get("ok") is None else "blocked",
            "evidence": {
                "run": smoke.get("run"),
                "ok": smoke.get("ok"),
                "failed_count": (smoke.get("summary") or {}).get("failed_count"),
            },
        },
        {
            "id": "workflow_studio_ready",
            "title": "Workflow Studio display bundle",
            "status": "completed" if workflow.get("valid") and lab.get("ok") and run_status == "completed" else "blocked",
            "evidence": {
                "workflow_valid": workflow.get("valid"),
                "bridge_lab_ok": lab.get("ok"),
                "run_status": run_status,
            },
        },
    ]


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
