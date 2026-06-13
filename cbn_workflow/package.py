"""Workflow package compiler and runner helpers."""

from __future__ import annotations

import json
import re
import time
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cbn_core.manifest import CapabilityManifest, ManifestRegistry
from cbn_core.bridge_contract import workflow_bridge_contract_report
from cbn_workflow.runner import WorkflowRunner
from cbn_execution.graph import WorkflowGraph


PACKAGE_API_VERSION = "bridge.dev/v1alpha1"
PACKAGE_KIND = "WorkflowPackage"


@dataclass(frozen=True)
class CompileReportInput:
    workflow_path: Path
    package_dir: Path
    package_files: list[Path]
    graph: WorkflowGraph
    bindings: dict[str, Any]
    schema_records: list[dict[str, Any]]
    contract: dict[str, Any]
    registry: ManifestRegistry


@dataclass(frozen=True)
class RunStateInput:
    package_dir: Path
    graph: WorkflowGraph
    run_result: dict[str, Any] | None
    status: str
    schema_validation: list[dict[str, Any]]
    blockers: list[str]
    event_count: int
    dry_run: bool


@dataclass(frozen=True)
class PackageRunResultInput:
    package_dir: Path
    lock_status: dict[str, Any]
    schema_validation: list[dict[str, Any]]
    state_path: Path
    run_result: dict[str, Any]
    golden_path: Path | None
    golden_events: list[dict[str, Any]]
    status: str


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def default_package_dir(workflow_id: str, root: Path = Path("runtime/workflow-packages")) -> Path:
    return root / safe_package_name(workflow_id)


def compile_workflow_package(
    workflow_path: Path,
    output_dir: Path | None,
    registry: ManifestRegistry,
) -> dict[str, Any]:
    graph = WorkflowGraph.from_file(workflow_path)
    graph.validate()
    _require_capabilities(graph, registry)
    package_dir, schema_dir = _prepare_package_dirs(graph, output_dir)
    bindings = _tool_bindings_lock(graph, registry)
    policy_profile = _policy_profile(graph, registry)
    schema_records = _write_artifact_schemas(graph, registry, schema_dir)
    contract = workflow_bridge_contract_report(registry, workflow_path=str(workflow_path))
    files = _package_files(package_dir, schema_records)

    _write_package_files(files, graph, bindings, policy_profile)
    report = _compile_report(CompileReportInput(
        workflow_path=workflow_path,
        package_dir=package_dir,
        package_files=files["all"],
        graph=graph,
        bindings=bindings,
        schema_records=schema_records,
        contract=contract,
        registry=registry,
    ))
    _write_json(files["report"], report)
    return report


def _prepare_package_dirs(graph: WorkflowGraph, output_dir: Path | None) -> tuple[Path, Path]:
    package_dir = output_dir or default_package_dir(graph.workflow_id)
    schema_dir = package_dir / "artifact_schemas"
    package_dir.mkdir(parents=True, exist_ok=True)
    schema_dir.mkdir(parents=True, exist_ok=True)
    return package_dir, schema_dir


def _package_files(package_dir: Path, schema_records: list[dict[str, Any]]) -> dict[str, Any]:
    files = {
        "workflow": package_dir / "workflow.yaml",
        "lock": package_dir / "tool_bindings.lock",
        "policy": package_dir / "policy_profile.yaml",
        "report": package_dir / "compile_report.json",
        "golden": package_dir / "golden_run.jsonl",
    }
    files["schemas"] = [Path(record["path"]) for record in schema_records]
    files["all"] = [files["workflow"], files["lock"], files["policy"], files["report"], files["golden"], *files["schemas"]]
    return files


def _write_package_files(
    files: dict[str, Any],
    graph: WorkflowGraph,
    bindings: dict[str, Any],
    policy_profile: dict[str, Any],
) -> None:
    _write_json_subset_yaml(files["workflow"], _workflow_dict(graph))
    _write_json(files["lock"], bindings)
    _write_json_subset_yaml(files["policy"], policy_profile)
    if not files["golden"].exists():
        files["golden"].write_text("", encoding="utf-8")


def _compile_report(params: CompileReportInput) -> dict[str, Any]:
    return {
        "apiVersion": PACKAGE_API_VERSION,
        "kind": PACKAGE_KIND,
        "compiled_at": now_iso(),
        "workflow_id": params.graph.workflow_id,
        "title": params.graph.title,
        "source_workflow_path": str(params.workflow_path),
        "package_dir": str(params.package_dir),
        "package_files": [str(path) for path in params.package_files],
        "task_count": len(params.graph.tasks),
        "artifact_schema_count": len(params.schema_records),
        "tool_binding_count": len(params.bindings["bindings"]),
        "lock_status": verify_tool_bindings(params.package_dir, params.registry, bindings=params.bindings),
        "bridge_contract": {
            "ok": params.contract.get("ok"),
            "summary": params.contract.get("summary", {}),
        },
        "warnings": _compile_warnings(params.contract, params.bindings),
    }


def load_packaged_workflow(package_dir: Path) -> WorkflowGraph:
    workflow_path = package_dir / "workflow.yaml"
    raw = _read_json_subset_yaml(workflow_path)
    return WorkflowGraph.from_dict(raw)


def run_workflow_package(
    package_dir: Path,
    registry: ManifestRegistry,
    workflow_runner: WorkflowRunner,
    dry_run: bool = False,
    confirmed: bool = False,
    write_golden: bool = False,
) -> dict[str, Any]:
    graph = load_packaged_workflow(package_dir)
    lock_status = verify_tool_bindings(package_dir, registry)
    if not lock_status["ok"]:
        return _lock_mismatch_result(package_dir, graph, lock_status, dry_run)

    result = workflow_runner.run(graph, dry_run=dry_run, confirmed=confirmed)
    schema_validation = validate_run_against_artifact_schemas(package_dir, result)
    status = _package_run_status(result, schema_validation)
    golden_events = normalize_golden_run(result, dry_run=dry_run, schema_validation=schema_validation, status=status)
    state_path = write_run_state(RunStateInput(
        package_dir=package_dir,
        graph=graph,
        run_result=result,
        status=status,
        schema_validation=schema_validation,
        blockers=[],
        event_count=len(golden_events),
        dry_run=dry_run,
    ))
    golden_path = _maybe_write_golden_run(package_dir, golden_events, write_golden)
    return _package_run_result(PackageRunResultInput(
        package_dir=package_dir,
        lock_status=lock_status,
        schema_validation=schema_validation,
        state_path=state_path,
        run_result=result,
        golden_path=golden_path,
        golden_events=golden_events,
        status=status,
    ))


def _maybe_write_golden_run(
    package_dir: Path,
    golden_events: list[dict[str, Any]],
    write_golden: bool,
) -> Path | None:
    if not write_golden:
        return None
    golden_path = package_dir / "golden_run.jsonl"
    write_golden_run(golden_path, golden_events)
    return golden_path


def _lock_mismatch_result(
    package_dir: Path,
    graph: WorkflowGraph,
    lock_status: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    state_path = write_run_state(RunStateInput(
        package_dir=package_dir,
        graph=graph,
        run_result=None,
        status="blocked",
        schema_validation=[],
        blockers=["tool binding lock mismatch"],
        event_count=0,
        dry_run=dry_run,
    ))
    return {
        "ok": False,
        "status": "lock-mismatch",
        "package_dir": str(package_dir),
        "lock_status": lock_status,
        "run_result": None,
        "schema_validation": [],
        "run_state_path": str(state_path),
        "golden_run_path": None,
    }


def _package_run_status(run_result: dict[str, Any], schema_validation: list[dict[str, Any]]) -> str:
    status = str(run_result.get("status"))
    if status == "completed" and not _schema_validation_ok(schema_validation):
        return "schema-failed"
    return status


def _package_run_result(result: PackageRunResultInput) -> dict[str, Any]:
    return {
        "ok": result.status == "completed",
        "status": result.status,
        "package_dir": str(result.package_dir),
        "lock_status": result.lock_status,
        "schema_validation": result.schema_validation,
        "run_state_path": str(result.state_path),
        "run_result": result.run_result,
        "golden_run_path": str(result.golden_path) if result.golden_path else None,
        "golden_events": result.golden_events,
    }


def inspect_workflow_package(
    package_dir: Path,
    registry: ManifestRegistry | None = None,
) -> dict[str, Any]:
    file_status = _package_file_status(package_dir)
    schemas = _package_schema_status(package_dir)
    workflow = _read_optional_json(package_dir / "workflow.yaml")
    compile_report = _read_optional_json(package_dir / "compile_report.json")
    policy_profile = _read_optional_json(package_dir / "policy_profile.yaml")
    lock = _read_optional_json(package_dir / "tool_bindings.lock")
    return {
        "apiVersion": PACKAGE_API_VERSION,
        "kind": "WorkflowPackageInspection",
        "package_dir": str(package_dir),
        "ok": all(item["exists"] for item in file_status) and bool(schemas),
        "workflow_id": ((workflow or {}).get("metadata") or {}).get("id"),
        "title": ((workflow or {}).get("metadata") or {}).get("title"),
        "file_status": file_status,
        "artifact_schemas": schemas,
        "compile_report": _compact_compile_report(compile_report),
        "policy_summary": (policy_profile or {}).get("summary"),
        "lock_status": _optional_lock_status(package_dir, registry, lock),
        "run_state": _read_optional_json(package_dir / "run_state.json"),
        "golden_run": _golden_run_summary(package_dir / "golden_run.jsonl"),
    }


def _package_file_status(package_dir: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": str(package_dir / name),
            "kind": name,
            "exists": (package_dir / name).exists(),
        }
        for name in _required_package_files()
    ]


def _required_package_files() -> list[str]:
    return [
        "workflow.yaml",
        "tool_bindings.lock",
        "policy_profile.yaml",
        "compile_report.json",
        "golden_run.jsonl",
    ]


def _package_schema_status(package_dir: Path) -> list[dict[str, Any]]:
    schema_dir = package_dir / "artifact_schemas"
    if not schema_dir.exists():
        return []
    return [_schema_status(path) for path in sorted(schema_dir.glob("*.schema.json"))]


def _schema_status(path: Path) -> dict[str, Any]:
    schema = _read_json(path)
    metadata = schema.get("x-cbn") or {}
    return {
        "path": str(path),
        "exists": True,
        "task_id": metadata.get("task_id"),
        "capability_id": metadata.get("capability_id"),
    }


def _optional_lock_status(
    package_dir: Path,
    registry: ManifestRegistry | None,
    lock: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if registry is None or lock is None:
        return None
    return verify_tool_bindings(package_dir, registry, bindings=lock)


def verify_tool_bindings(
    package_dir: Path,
    registry: ManifestRegistry,
    bindings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lock = bindings or _read_json(package_dir / "tool_bindings.lock")
    mismatches = []
    checked = []
    for binding in lock.get("bindings", []):
        check, mismatch = _tool_binding_check(binding, registry)
        if check is not None:
            checked.append(check)
        if mismatch is not None:
            mismatches.append(mismatch)
    return {
        "ok": not mismatches,
        "checked_count": len(lock.get("bindings", [])),
        "mismatch_count": len(mismatches),
        "checked": checked,
        "mismatches": mismatches,
    }


def _tool_binding_check(
    binding: dict[str, Any],
    registry: ManifestRegistry,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    task_id = binding.get("task_id")
    capability_id = binding.get("capability_id")
    try:
        manifest = registry.require(str(capability_id))
    except KeyError as exc:
        return None, _missing_capability_mismatch(task_id, capability_id, exc)
    current = manifest_binding_record(task_id=str(task_id), manifest=manifest)
    check = {
        "task_id": task_id,
        "capability_id": capability_id,
        "locked_digest": binding.get("manifest_digest"),
        "current_digest": current["manifest_digest"],
    }
    if binding.get("manifest_digest") != current["manifest_digest"]:
        return check, _digest_mismatch(task_id, capability_id, binding, current)
    return check, None


def _missing_capability_mismatch(task_id: Any, capability_id: Any, error: Exception) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "capability_id": capability_id,
        "type": "missing-capability",
        "error": str(error),
    }


def _digest_mismatch(
    task_id: Any,
    capability_id: Any,
    binding: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "capability_id": capability_id,
        "type": "manifest-digest-mismatch",
        "locked_digest": binding.get("manifest_digest"),
        "current_digest": current["manifest_digest"],
    }


def validate_run_against_artifact_schemas(
    package_dir: Path,
    run_result: dict[str, Any],
) -> list[dict[str, Any]]:
    by_task = {
        task.get("task_id"): task
        for task in run_result.get("tasks", [])
        if isinstance(task, dict)
    }
    results = []
    for schema_path in sorted((package_dir / "artifact_schemas").glob("*.schema.json")):
        schema = _read_json(schema_path)
        task_id = schema.get("x-cbn", {}).get("task_id")
        task = by_task.get(task_id)
        if task is None:
            results.append(
                {
                    "task_id": task_id,
                    "schema_path": str(schema_path),
                    "valid": False,
                    "errors": ["task did not run"],
                }
            )
            continue
        payload = ((task.get("result") or {}).get("parsed") or {})
        errors = _validate_task_payload(schema, payload)
        results.append(
            {
                "task_id": task_id,
                "schema_path": str(schema_path),
                "valid": not errors,
                "errors": errors,
            }
        )
    return results


def write_run_state(params: RunStateInput) -> Path:
    schema_by_task = {item.get("task_id"): item for item in params.schema_validation}
    run_tasks = _run_tasks_by_id(params.run_result)
    tasks = _run_state_tasks(params.graph, run_tasks, schema_by_task, run_started=params.run_result is not None)
    state = _run_state_payload(
        params.graph,
        params.run_result,
        params.status,
        params.dry_run,
        params.blockers,
        params.event_count,
        tasks,
    )
    path = params.package_dir / "run_state.json"
    _write_json(path, state)
    return path


def _run_tasks_by_id(run_result: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not run_result:
        return {}
    return {
        task.get("task_id"): task
        for task in run_result.get("tasks", [])
        if isinstance(task, dict)
    }


def _run_state_tasks(
    graph: WorkflowGraph,
    run_tasks: dict[str, dict[str, Any]],
    schema_by_task: dict[str, dict[str, Any]],
    run_started: bool,
) -> list[dict[str, Any]]:
    tasks = []
    completed_by_task: dict[str, bool] = {}
    for task in graph.topological_order():
        item = _run_state_task(task, run_tasks, schema_by_task, completed_by_task, run_started)
        completed_by_task[task.task_id] = item["status"] == "completed"
        tasks.append(item)
    return tasks


def _run_state_task(
    task: Any,
    run_tasks: dict[str, dict[str, Any]],
    schema_by_task: dict[str, dict[str, Any]],
    completed_by_task: dict[str, bool],
    run_started: bool,
) -> dict[str, Any]:
    run_task = run_tasks.get(task.task_id)
    task_schema = schema_by_task.get(task.task_id)
    task_status = _task_state(
        run_task,
        task_schema,
        run_started=run_started,
        dependency_completed=all(completed_by_task.get(dep, False) for dep in task.needs),
    )
    return {
        "task_id": task.task_id,
        "uses": task.uses,
        "needs": list(task.needs),
        "status": task_status,
        "attempts": 1 if run_task else 0,
        "schema_valid": task_schema.get("valid") if task_schema else None,
    }


def _run_state_payload(
    graph: WorkflowGraph,
    run_result: dict[str, Any] | None,
    status: str,
    dry_run: bool,
    blockers: list[str],
    event_count: int,
    tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "apiVersion": PACKAGE_API_VERSION,
        "kind": "WorkflowRunState",
        "updated_at": now_iso(),
        "run_id": run_result.get("run_id") if run_result else None,
        "workflow_id": graph.workflow_id,
        "status": status,
        "dry_run": dry_run,
        "blockers": blockers,
        "event_count": event_count,
        "last_event_index": event_count - 1 if event_count else None,
        "task_count": len(tasks),
        "completed_task_count": sum(1 for task in tasks if task["status"] == "completed"),
        "failed_task_count": sum(1 for task in tasks if task["status"] == "failed"),
        "blocked_task_count": sum(1 for task in tasks if task["status"] == "blocked"),
        "skipped_task_count": sum(1 for task in tasks if task["status"] == "skipped"),
        "not_started_task_count": sum(1 for task in tasks if task["status"] == "not_started"),
        "tasks": tasks,
    }


def normalize_golden_run(
    run_result: dict[str, Any],
    dry_run: bool = False,
    schema_validation: list[dict[str, Any]] | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    workflow_id = run_result.get("workflow_id")
    schema_by_task = {item.get("task_id"): item for item in schema_validation or []}
    events: list[dict[str, Any]] = [_golden_workflow_started(workflow_id, dry_run)]
    for task in run_result.get("tasks", []):
        if not isinstance(task, dict):
            continue
        events.extend(_golden_task_events(workflow_id, task, schema_by_task))
    events.append(_golden_workflow_completed(workflow_id, run_result, status))
    return events


def _golden_workflow_started(workflow_id: Any, dry_run: bool) -> dict[str, Any]:
    return {"type": "workflow.started", "workflow_id": workflow_id, "dry_run": dry_run}


def _golden_task_events(
    workflow_id: Any,
    task: dict[str, Any],
    schema_by_task: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    result = task.get("result") or {}
    parsed = result.get("parsed") or {}
    message = result.get("message") or {}
    artifacts = result.get("artifacts") or []
    return [
        _golden_task_started(workflow_id, task),
        _golden_bridge_message_created(workflow_id, task, parsed, message, artifacts),
        _golden_task_completed(workflow_id, task, result, parsed, artifacts, schema_by_task),
    ]


def _golden_task_started(workflow_id: Any, task: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "task.started",
        "workflow_id": workflow_id,
        "task_id": task.get("task_id"),
        "uses": task.get("uses"),
        "resolved_args": task.get("resolved_args", []),
    }


def _golden_bridge_message_created(
    workflow_id: Any,
    task: dict[str, Any],
    parsed: dict[str, Any],
    message: dict[str, Any],
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    message_metadata = message.get("metadata") or {}
    return {
        "type": "bridge.message.created",
        "workflow_id": workflow_id,
        "task_id": task.get("task_id"),
        "producer": message_metadata.get("producer"),
        "channel": message_metadata.get("channel"),
        "parser_ref": parsed.get("parser_ref"),
        "parser_ok": parsed.get("ok"),
        "artifact_kinds": _artifact_kinds(artifacts),
    }


def _golden_task_completed(
    workflow_id: Any,
    task: dict[str, Any],
    result: dict[str, Any],
    parsed: dict[str, Any],
    artifacts: list[dict[str, Any]],
    schema_by_task: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "type": "task.completed",
        "workflow_id": workflow_id,
        "task_id": task.get("task_id"),
        "uses": task.get("uses"),
        "allowed": result.get("allowed"),
        "ok": result.get("ok"),
        "exit_code": result.get("exit_code"),
        "reason": result.get("reason"),
        "parser_ref": parsed.get("parser_ref"),
        "parser_ok": parsed.get("ok"),
        "artifact_count": len(artifacts),
        "artifact_kinds": _artifact_kinds(artifacts),
        "schema_valid": (schema_by_task.get(task.get("task_id")) or {}).get("valid"),
    }


def _golden_workflow_completed(
    workflow_id: Any,
    run_result: dict[str, Any],
    status: str | None,
) -> dict[str, Any]:
    return {
        "type": "workflow.completed",
        "workflow_id": workflow_id,
        "status": status or run_result.get("status"),
        "task_count": len(run_result.get("tasks", [])),
    }


def write_golden_run(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in events)
    path.write_text(text, encoding="utf-8")


def manifest_binding_record(task_id: str, manifest: CapabilityManifest) -> dict[str, Any]:
    payload = {
        "capability_id": manifest.capability_id,
        "title": manifest.title,
        "source_path": str(manifest.source_path) if manifest.source_path else None,
        "transport": {
            "kind": manifest.transport.kind,
            "command": manifest.transport.command,
            "argsTemplate": list(manifest.transport.args_template),
            "cwdPolicy": manifest.transport.cwd_policy,
            "timeoutSeconds": manifest.transport.timeout_seconds,
        },
        "policy": {
            "risk": manifest.policy.risk,
            "requiresConfirmation": manifest.policy.requires_confirmation,
            "network": manifest.policy.network,
        },
        "output": {
            "parserRef": manifest.output.parser_ref or "raw.text",
            "verified": manifest.output.verified,
        },
        "labels": manifest.labels,
        "annotations": manifest.annotations,
    }
    return {
        "task_id": task_id,
        **payload,
        "manifest_digest": _digest(payload),
    }


def safe_package_name(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip()).strip("-._")
    return safe or "workflow"


def _require_capabilities(graph: WorkflowGraph, registry: ManifestRegistry) -> None:
    missing = []
    for task in graph.tasks:
        if registry.get(task.uses) is None:
            missing.append({"task_id": task.task_id, "capability_id": task.uses})
    if missing:
        raise KeyError(f"workflow references missing capabilities: {missing}")


def _workflow_dict(graph: WorkflowGraph) -> dict[str, Any]:
    return {
        "apiVersion": "bridge.dev/v1alpha1",
        "kind": "Workflow",
        "metadata": {
            "id": graph.workflow_id,
            "title": graph.title,
            "compiledAs": "workflow-package",
        },
        "spec": {
            "tasks": [task.as_dict() for task in graph.topological_order()],
        },
    }


def _tool_bindings_lock(graph: WorkflowGraph, registry: ManifestRegistry) -> dict[str, Any]:
    return {
        "apiVersion": PACKAGE_API_VERSION,
        "kind": "ToolBindingsLock",
        "workflow_id": graph.workflow_id,
        "generated_at": now_iso(),
        "bindings": [
            manifest_binding_record(task.task_id, registry.require(task.uses))
            for task in graph.topological_order()
        ],
    }


def _policy_profile(graph: WorkflowGraph, registry: ManifestRegistry) -> dict[str, Any]:
    tasks = []
    risk_counts: dict[str, int] = {}
    network_counts: dict[str, int] = {}
    requires_confirmation = False
    for task in graph.topological_order():
        manifest = registry.require(task.uses)
        risk_counts[manifest.policy.risk] = risk_counts.get(manifest.policy.risk, 0) + 1
        network_counts[manifest.policy.network] = network_counts.get(manifest.policy.network, 0) + 1
        requires_confirmation = requires_confirmation or manifest.policy.requires_confirmation
        tasks.append(
            {
                "task_id": task.task_id,
                "capability_id": manifest.capability_id,
                "risk": manifest.policy.risk,
                "network": manifest.policy.network,
                "requires_confirmation": manifest.policy.requires_confirmation,
                "dry_run": task.dry_run,
            }
        )
    return {
        "apiVersion": PACKAGE_API_VERSION,
        "kind": "WorkflowPolicyProfile",
        "workflow_id": graph.workflow_id,
        "generated_at": now_iso(),
        "summary": {
            "task_count": len(tasks),
            "risk_counts": dict(sorted(risk_counts.items())),
            "network_counts": dict(sorted(network_counts.items())),
            "requires_confirmation": requires_confirmation,
        },
        "tasks": tasks,
    }


def _write_artifact_schemas(
    graph: WorkflowGraph,
    registry: ManifestRegistry,
    schema_dir: Path,
) -> list[dict[str, Any]]:
    records = []
    for task in graph.topological_order():
        manifest = registry.require(task.uses)
        filename = f"{safe_package_name(task.task_id)}.output.schema.json"
        path = schema_dir / filename
        schema = _task_output_schema(task.task_id, manifest)
        _write_json(path, schema)
        records.append(
            {
                "task_id": task.task_id,
                "capability_id": manifest.capability_id,
                "parser_ref": manifest.output.parser_ref or "raw.text",
                "path": str(path),
            }
        )
    return records


def _task_output_schema(task_id: str, manifest: CapabilityManifest) -> dict[str, Any]:
    parser_ref = manifest.output.parser_ref or "raw.text"
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"cbn://artifact-schemas/{safe_package_name(task_id)}.output",
        "title": f"{task_id} BridgeMessage payload",
        "type": "object",
        "required": ["parser_ref", "ok", "data"],
        "properties": {
            "parser_ref": {"const": parser_ref},
            "ok": {"type": "boolean"},
            "data": {"type": "object"},
            "dry_run": {"type": "boolean"},
            "error": {"type": "string"},
        },
        "additionalProperties": True,
        "x-cbn": {
            "task_id": task_id,
            "capability_id": manifest.capability_id,
            "output_verified": manifest.output.verified,
        },
    }


def _validate_task_payload(schema: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    return [
        *_required_payload_errors(schema, payload),
        *_parser_ref_payload_errors(schema, payload),
        *_typed_payload_errors(payload),
    ]


def _required_payload_errors(schema: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    return [f"payload.{key} is required" for key in schema.get("required", []) if key not in payload]


def _parser_ref_payload_errors(schema: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    parser_ref = ((schema.get("properties") or {}).get("parser_ref") or {}).get("const")
    dry_run_raw = payload.get("dry_run") is True and payload.get("parser_ref") == "raw.text"
    if parser_ref is not None and payload.get("parser_ref") != parser_ref and not dry_run_raw:
        return [f"payload.parser_ref expected {parser_ref!r}, got {payload.get('parser_ref')!r}"]
    return []


def _typed_payload_errors(payload: dict[str, Any]) -> list[str]:
    checks = (
        ("ok", bool, "boolean"),
        ("data", dict, "object"),
        ("dry_run", bool, "boolean"),
        ("error", str, "string"),
    )
    return [
        f"payload.{field} must be a {label}"
        for field, expected_type, label in checks
        if field in payload and not isinstance(payload.get(field), expected_type)
    ]


def _schema_validation_ok(schema_validation: list[dict[str, Any]]) -> bool:
    return all(item.get("valid") is True for item in schema_validation)


def _task_state(
    run_task: dict[str, Any] | None,
    schema_validation: dict[str, Any] | None,
    run_started: bool,
    dependency_completed: bool,
) -> str:
    if run_task is None:
        if not run_started:
            return "not_started"
        return "skipped" if not dependency_completed else "skipped"
    result = run_task.get("result") or {}
    if not result.get("allowed"):
        return "blocked"
    if not result.get("ok"):
        return "failed"
    if schema_validation and not schema_validation.get("valid"):
        return "failed"
    return "completed"


def _compile_warnings(contract: dict[str, Any], bindings: dict[str, Any]) -> list[str]:
    warnings = []
    if not contract.get("ok"):
        warnings.append("workflow BridgeMessage contract is not ready")
    for binding in bindings.get("bindings", []):
        if not binding.get("output", {}).get("verified"):
            warnings.append(f"task {binding['task_id']} output parser is not verified")
        if binding.get("source_path") and "\\runtime\\manifests\\" in str(binding["source_path"]).casefold():
            warnings.append(f"task {binding['task_id']} uses a runtime-local manifest overlay")
    return warnings


def _artifact_kinds(artifacts: list[dict[str, Any]]) -> list[str]:
    return [str(artifact.get("kind")) for artifact in artifacts if isinstance(artifact, dict)]


def _compact_compile_report(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if report is None:
        return None
    return {
        "workflow_id": report.get("workflow_id"),
        "title": report.get("title"),
        "compiled_at": report.get("compiled_at"),
        "task_count": report.get("task_count"),
        "artifact_schema_count": report.get("artifact_schema_count"),
        "tool_binding_count": report.get("tool_binding_count"),
        "warnings": report.get("warnings", []),
    }


def _golden_run_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "path": str(path), "event_count": 0, "first_event": None, "last_event": None}
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return {
        "exists": True,
        "path": str(path),
        "event_count": len(events),
        "first_event": events[0] if events else None,
        "last_event": events[-1] if events else None,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return _read_json(path)


def _write_json_subset_yaml(path: Path, payload: dict[str, Any]) -> None:
    _write_json(path, payload)


def _read_json_subset_yaml(path: Path) -> dict[str, Any]:
    return _read_json(path)


def _digest(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
