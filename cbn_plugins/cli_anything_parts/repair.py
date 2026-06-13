"""Entrypoint repair helpers for CLI-Anything harnesses."""

from __future__ import annotations

from dataclasses import dataclass
import importlib.metadata as importlib_metadata
import importlib.util as importlib_util
import json
import os
import re
import shutil
import sys
import sysconfig
from pathlib import Path
from typing import Any, Callable

from cbn_core.manifest import validate_manifest_dict
from cbn_plugins.cli_anything_parts.lifecycle import max_risk
from cbn_plugins.cli_anything_parts.manifest_factory import infer_market_policy, sanitize_harness_name
from cbn_plugins.cli_anything_parts.verification import (
    known_parser_refs,
    mark_repaired_manifest_verified_from_fixtures,
    policy_requires_confirmation,
)
from cbn_plugins.manager import PluginPlan


PLUGIN_ID = "cli-anything"


@dataclass(frozen=True)
class RepairEntrypointRequest:
    harness_name: str
    from_market: bool
    module: str | None
    write: bool
    confirmed: bool
    require_smoke: bool
    smoke_args: tuple[str, ...]
    smoke_timeout_seconds: int


@dataclass(frozen=True)
class RepairEntrypointContext:
    plan: dict[str, Any]
    strategy: dict[str, Any]
    smoke_gate: dict[str, Any]
    smoke_report: dict[str, Any] | None
    wrapper_path: Path
    repair_manifest_path: Path
    manifest: dict[str, Any]
    parser_fixture_gate: dict[str, Any]
    validation: dict[str, Any]
    execution: dict[str, Any]


@dataclass(frozen=True)
class RepairEntrypointManifestState:
    wrapper_path: Path
    repair_manifest_path: Path
    manifest: dict[str, Any]
    validation_context: dict[str, Any]


@dataclass(frozen=True)
class RepairEntrypointExecutionRequest:
    hub: Any
    harness_name: str
    write: bool
    confirmed: bool
    strategy: dict[str, Any]
    smoke_gate: dict[str, Any]
    validation: dict[str, Any]
    wrapper_path: Path
    repair_manifest_path: Path
    manifest: dict[str, Any]


@dataclass(frozen=True)
class EntrypointRepairPlanContext:
    evaluation: dict[str, Any]
    entry_point: str | None
    entrypoint_path: str | None
    package_candidates: list[str]
    script_candidates: list[str]
    distribution_reports: list[dict[str, Any]]
    module_reports: list[dict[str, Any]]
    diagnosis: dict[str, Any]


@dataclass(frozen=True)
class EntrypointDiagnosisContext:
    gates: dict[str, Any]
    installed_dists: list[dict[str, Any]]
    matching_scripts: list[dict[str, Any]]
    existing_script_files: list[dict[str, Any]]
    runnable_modules: list[dict[str, Any]]


_REPAIR_ENTRYPOINT_OPTION_NAMES = (
    "from_market",
    "module",
    "write",
    "confirmed",
    "require_smoke",
    "smoke_args",
    "smoke_timeout_seconds",
    "smoke_gate_fn",
)


def entrypoint_repair_plan(
    hub: Any,
    harness_name: str,
    from_market: bool = True,
) -> dict[str, Any]:
    context = entrypoint_repair_plan_context(hub, harness_name, from_market)
    return entrypoint_repair_plan_payload(harness_name, from_market, context)


def entrypoint_repair_plan_context(
    hub: Any,
    harness_name: str,
    from_market: bool,
) -> EntrypointRepairPlanContext:
    evaluation = hub.evaluate_harness(harness_name, from_market=from_market)
    status = evaluation.get("status") if isinstance(evaluation.get("status"), dict) else {}
    market_record = status.get("market_record") if isinstance(status.get("market_record"), dict) else None
    entry_point = status.get("entry_point")
    if not isinstance(entry_point, str) or not entry_point:
        entry_point = None
    entrypoint_path = shutil.which(entry_point) if entry_point else None
    package_candidates = entrypoint_package_candidates(harness_name, market_record, status)
    script_candidates = script_path_candidates(entry_point)
    distribution_reports = [distribution_report(package) for package in package_candidates]
    module_reports = [module_report(package) for package in package_candidates]
    diagnosis = entrypoint_diagnosis(
        entry_point=entry_point,
        entrypoint_path=entrypoint_path,
        script_candidates=script_candidates,
        distribution_reports=distribution_reports,
        module_reports=module_reports,
        evaluation=evaluation,
    )
    return EntrypointRepairPlanContext(
        evaluation=evaluation,
        entry_point=entry_point,
        entrypoint_path=entrypoint_path,
        package_candidates=package_candidates,
        script_candidates=script_candidates,
        distribution_reports=distribution_reports,
        module_reports=module_reports,
        diagnosis=diagnosis,
    )


def entrypoint_repair_plan_payload(
    harness_name: str,
    from_market: bool,
    context: EntrypointRepairPlanContext,
) -> dict[str, Any]:
    return {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "kind": "CliAnythingEntrypointRepairPlan",
        "harness_name": harness_name,
        "from_market": from_market,
        "capability_id": context.evaluation.get("capability_id"),
        "entry_point": context.entry_point,
        "entrypoint_path": context.entrypoint_path,
        "entrypoint_available": bool(context.entrypoint_path),
        "package_candidates": context.package_candidates,
        "script_candidates": context.script_candidates,
        "distributions": context.distribution_reports,
        "modules": context.module_reports,
        "diagnosis": context.diagnosis,
        "evaluation": context.evaluation,
        "commands": entrypoint_repair_plan_commands(harness_name, context),
    }


def entrypoint_repair_plan_commands(
    harness_name: str,
    context: EntrypointRepairPlanContext,
) -> dict[str, str | None]:
    return {
        "status": f"python -m cbn plugin harness cli-anything status {harness_name} --from-market",
        "evaluate": f"python -m cbn plugin evaluate-harness cli-anything {harness_name} --from-market",
        "blocked_plan": f"python -m cbn plugin blocked-plan cli-anything --harness {harness_name}",
        "where_entrypoint": f"where.exe {context.entry_point}" if context.entry_point else None,
        "pip_show": (
            f"python -m pip show {context.package_candidates[0]}"
            if context.package_candidates
            else None
        ),
        "cli_hub_launch_help": f"cli-hub launch {harness_name} -- --help",
    }


def repair_entrypoint(
    hub: Any,
    harness_name: str,
    *args: Any,
    **options: Any,
) -> dict[str, Any]:
    request, smoke_gate_fn = repair_entrypoint_request(harness_name, args, options)
    context = repair_entrypoint_context(
        hub,
        request=request,
        smoke_gate_fn=smoke_gate_fn or default_repair_smoke_gate,
    )
    return repair_entrypoint_report_for_request(request, context)


def repair_entrypoint_request(
    harness_name: str,
    args: tuple[Any, ...],
    options: dict[str, Any],
) -> tuple[RepairEntrypointRequest, Callable[[bool, dict[str, Any] | None], dict[str, Any]] | None]:
    values = repair_entrypoint_options(args, options)
    smoke_gate_fn = values.pop("smoke_gate_fn")
    return RepairEntrypointRequest(harness_name=harness_name, **values), smoke_gate_fn


def repair_entrypoint_options(args: tuple[Any, ...], options: dict[str, Any]) -> dict[str, Any]:
    if len(args) > len(_REPAIR_ENTRYPOINT_OPTION_NAMES):
        raise TypeError(f"repair_entrypoint expected at most {len(_REPAIR_ENTRYPOINT_OPTION_NAMES) + 2} arguments")
    values = {
        "from_market": True,
        "module": None,
        "write": False,
        "confirmed": False,
        "require_smoke": False,
        "smoke_args": ("--help",),
        "smoke_timeout_seconds": 10,
        "smoke_gate_fn": None,
    }
    for name, value in zip(_REPAIR_ENTRYPOINT_OPTION_NAMES, args):
        if name in options:
            raise TypeError(f"repair_entrypoint got multiple values for argument '{name}'")
        values[name] = value
    unknown = sorted(set(options) - set(_REPAIR_ENTRYPOINT_OPTION_NAMES))
    if unknown:
        raise TypeError(f"unknown repair entrypoint option(s): {', '.join(unknown)}")
    values.update(options)
    return values


def repair_entrypoint_context(
    hub: Any,
    *,
    request: RepairEntrypointRequest,
    smoke_gate_fn: Callable[[bool, dict[str, Any] | None], dict[str, Any]],
) -> RepairEntrypointContext:
    plan = hub.entrypoint_repair_plan(request.harness_name, from_market=request.from_market)
    strategy = entrypoint_repair_strategy(plan, module=request.module)
    smoke_report = repair_smoke_report_for_request(hub, request, strategy)
    smoke_gate = smoke_gate_fn(request.require_smoke, smoke_report)
    manifest_state = repair_entrypoint_manifest_state(hub, request, plan, strategy, smoke_report)
    execution = repair_entrypoint_execution(RepairEntrypointExecutionRequest(
        hub=hub,
        harness_name=request.harness_name,
        write=request.write,
        confirmed=request.confirmed,
        strategy=strategy,
        smoke_gate=smoke_gate,
        validation=manifest_state.validation_context["validation"],
        wrapper_path=manifest_state.wrapper_path,
        repair_manifest_path=manifest_state.repair_manifest_path,
        manifest=manifest_state.manifest,
    ))
    return RepairEntrypointContext(
        plan=plan,
        strategy=strategy,
        smoke_gate=smoke_gate,
        smoke_report=smoke_report,
        wrapper_path=manifest_state.wrapper_path,
        repair_manifest_path=manifest_state.repair_manifest_path,
        manifest=manifest_state.manifest,
        parser_fixture_gate=manifest_state.validation_context["parser_fixtures"],
        validation=manifest_state.validation_context["validation"],
        execution=execution,
    )


def repair_entrypoint_manifest_state(
    hub: Any,
    request: RepairEntrypointRequest,
    plan: dict[str, Any],
    strategy: dict[str, Any],
    smoke_report: dict[str, Any] | None,
) -> RepairEntrypointManifestState:
    wrapper_path = entrypoint_wrapper_path(hub.paths.external_plugins, request.harness_name)
    manifest = entrypoint_repair_manifest(plan, strategy, wrapper_path)
    repair_manifest_path = hub.paths.local_manifests / f"{plan['capability_id']}.json"
    annotate_repair_manifest_with_smoke(manifest, smoke_report)
    validation_context = repair_manifest_validation_context(
        hub,
        manifest=manifest,
        capability_id=str(plan["capability_id"]),
        repair_manifest_path=repair_manifest_path,
        smoke_report=smoke_report,
    )
    return RepairEntrypointManifestState(wrapper_path, repair_manifest_path, manifest, validation_context)


def repair_smoke_report_for_request(
    hub: Any,
    request: RepairEntrypointRequest,
    strategy: dict[str, Any],
) -> dict[str, Any] | None:
    return repair_smoke_report(hub, request, strategy)


def repair_entrypoint_execution(request: RepairEntrypointExecutionRequest) -> dict[str, Any]:
    execution: dict[str, Any] = repair_entrypoint_initial_execution(
        write=request.write,
        confirmed=request.confirmed,
    )
    blocker = repair_entrypoint_execution_blocker(request)
    if blocker:
        execution["status"] = blocker["status"]
        execution["blockers"] = blocker["blockers"]
    elif request.write and request.confirmed:
        repair_operation = execute_repair_entrypoint_write(
            request.hub,
            harness_name=request.harness_name,
            strategy=request.strategy,
            wrapper_path=request.wrapper_path,
            repair_manifest_path=request.repair_manifest_path,
            manifest=request.manifest,
        )
        apply_repair_operation_result(execution, repair_operation)
    return execution


def repair_entrypoint_execution_blocker(request: RepairEntrypointExecutionRequest) -> dict[str, Any] | None:
    if not request.write:
        return None
    if not request.confirmed:
        return {
            "status": "requires_confirmation",
            "blockers": ["entrypoint repair writes require --yes or confirmed=true"],
        }
    if not request.strategy["ready"]:
        return {"status": "blocked", "blockers": list(request.strategy["blockers"])}
    if not request.smoke_gate["ok"]:
        return {"status": "blocked", "blockers": list(request.smoke_gate["blockers"])}
    if not request.validation["valid"]:
        return {
            "status": "blocked",
            "blockers": [f"manifest validation error: {item}" for item in request.validation["errors"]],
        }
    return None


def repair_entrypoint_report_for_request(
    request: RepairEntrypointRequest,
    context: RepairEntrypointContext,
) -> dict[str, Any]:
    return repair_entrypoint_report(request, context)


def default_repair_smoke_gate(require_smoke: bool, smoke_report: dict[str, Any] | None) -> dict[str, Any]:
    from cbn_plugins.cli_anything_parts.adapter_targets import repair_entrypoint_smoke_gate

    return repair_entrypoint_smoke_gate(require_smoke, smoke_report)


def repair_smoke_report(
    hub: Any,
    request: RepairEntrypointRequest,
    strategy: dict[str, Any],
) -> dict[str, Any] | None:
    if not (request.require_smoke and strategy.get("ready") and strategy.get("module")):
        return None
    return hub.adapter_target_smoke(
        request.harness_name,
        module=strategy["module"],
        from_market=request.from_market,
        smoke_args=request.smoke_args,
        timeout_seconds=request.smoke_timeout_seconds,
        run=request.write,
        confirmed=request.confirmed,
    )


def annotate_repair_manifest_with_smoke(
    manifest: dict[str, Any],
    smoke_report: dict[str, Any] | None,
) -> None:
    if not (smoke_report and smoke_report.get("summary", {}).get("smoke_ok")):
        return
    annotations = manifest.setdefault("metadata", {}).setdefault("annotations", {})
    annotations["cbn.repair.smoke.module"] = str(smoke_report["module"])
    annotations["cbn.repair.smoke.args"] = json.dumps(smoke_report["smoke_args"], ensure_ascii=False)
    annotations["cbn.repair.smoke.exit_code"] = str(smoke_report["execution"].get("exit_code"))


def repair_manifest_validation_context(
    hub: Any,
    *,
    manifest: dict[str, Any],
    capability_id: str,
    repair_manifest_path: Path,
    smoke_report: dict[str, Any] | None,
) -> dict[str, Any]:
    parser_fixture_gate = mark_repaired_manifest_verified_from_fixtures(
        manifest=manifest,
        capability_id=capability_id,
        fixture_dir=hub.paths.root / "parser_fixtures",
        root=hub.paths.root,
        smoke_ok=bool(smoke_report and smoke_report.get("summary", {}).get("smoke_ok")),
    )
    return {
        "parser_fixtures": parser_fixture_gate,
        "validation": validate_manifest_dict(
            manifest,
            source_path=repair_manifest_path,
            known_parser_refs=known_parser_refs(),
        ),
    }


def repair_entrypoint_initial_execution(write: bool, confirmed: bool) -> dict[str, Any]:
    return {
        "requested": write,
        "confirmed": confirmed,
        "status": "not_requested",
        "blockers": [],
        "written": [],
    }


def execute_repair_entrypoint_write(
    hub: Any,
    *,
    harness_name: str,
    strategy: dict[str, Any],
    wrapper_path: Path,
    repair_manifest_path: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    return hub.operation_runner.execute_write(
        PluginPlan(
            plugin_id=PLUGIN_ID,
            action=f"repair-entrypoint-{sanitize_harness_name(harness_name)}",
            plugin_dir=str(hub.paths.external_plugins / PLUGIN_ID),
            commands=(),
            notes=(
                "Writes a CBN-owned CLI-Anything entrypoint wrapper and local manifest overlay.",
                f"Harness: {harness_name}",
                f"Module: {strategy['module']}",
            ),
        ),
        lambda operation_id: write_repair_entrypoint_files(
            operation_id=operation_id,
            root=hub.paths.root,
            wrapper_path=wrapper_path,
            module=strategy["module"],
            manifest_path=repair_manifest_path,
            manifest=manifest,
        ),
    )


def apply_repair_operation_result(execution: dict[str, Any], repair_operation: dict[str, Any]) -> None:
    write_result = repair_operation.get("write_result") or {}
    execution["status"] = repair_operation.get("status", "failed")
    execution["operation_id"] = repair_operation.get("operation_id")
    execution["operation_status"] = repair_operation.get("status")
    execution["artifact_ids"] = repair_operation.get("artifact_ids", [])
    execution["write_result"] = write_result
    execution["written"] = list(write_result.get("written", []))
    execution["backups"] = list(write_result.get("backups", []))
    if execution["status"] == "completed":
        return
    execution["blockers"] = list(repair_operation.get("blockers", []))
    if not execution["blockers"] and write_result.get("error"):
        execution["blockers"] = [str(write_result["error"])]


def repair_entrypoint_report(
    request: RepairEntrypointRequest,
    context: RepairEntrypointContext,
) -> dict[str, Any]:
    plan = context.plan
    harness_name = request.harness_name
    return {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "kind": "CliAnythingEntrypointRepair",
        "harness_name": harness_name,
        "from_market": request.from_market,
        "module": request.module,
        "write": request.write,
        "confirmed": request.confirmed,
        "require_smoke": request.require_smoke,
        "smoke_args": list(request.smoke_args),
        "smoke_timeout_seconds": request.smoke_timeout_seconds,
        "plan": plan,
        "strategy": context.strategy,
        "smoke_gate": context.smoke_gate,
        "smoke_report": context.smoke_report,
        "wrapper_path": str(context.wrapper_path),
        "manifest_path": str(context.repair_manifest_path),
        "manifest": context.manifest,
        "repair_provenance": entrypoint_repair_manifest_provenance(context.manifest),
        "parser_fixtures": context.parser_fixture_gate,
        "validation": context.validation,
        "execution": context.execution,
        "next_commands": repair_entrypoint_next_commands(harness_name, plan),
    }


def repair_entrypoint_next_commands(harness_name: str, plan: dict[str, Any]) -> list[str]:
    return [
        f"python -m cbn plugin repair-plan cli-anything {harness_name} --from-market",
        f"python -m cbn plugin repair-entrypoint cli-anything {harness_name} --from-market --module <module>",
        f"python -m cbn plugin adapter-smoke cli-anything {harness_name} --from-market --module <module> --run --yes",
        f"python -m cbn plugin repair-entrypoint cli-anything {harness_name} --from-market --module <module> --write --yes",
        f"python -m cbn plugin repair-entrypoint cli-anything {harness_name} --from-market --module <module> --require-smoke --write --yes",
        "python -m cbn registry validate runtime/manifests",
        f"python -m cbn call {plan.get('capability_id')} --dry-run",
    ]


def entrypoint_package_candidates(
    harness_name: str,
    market_record: dict[str, Any] | None,
    status: dict[str, Any],
) -> list[str]:
    candidates = [
        *market_package_candidates(market_record),
        *status_package_candidates(status),
        harness_name,
    ]
    return normalized_package_candidates(candidates)


def market_package_candidates(market_record: dict[str, Any] | None) -> list[str]:
    if not market_record:
        return []
    candidates = [
        value.strip()
        for key in ("name", "package", "pip_package", "npm_package")
        if isinstance((value := market_record.get(key)), str) and value.strip()
    ]
    install_cmd = market_record.get("install_cmd")
    if isinstance(install_cmd, str):
        candidates.extend(packages_from_install_command(install_cmd))
    return candidates


def status_package_candidates(status: dict[str, Any]) -> list[str]:
    fields = status.get("cli_hub_info", {}).get("fields", {})
    if not isinstance(fields, dict):
        return []
    install_cmd = fields.get("install_cmd")
    return packages_from_install_command(install_cmd) if isinstance(install_cmd, str) else []


def normalized_package_candidates(candidates: list[str]) -> list[str]:
    normalized: list[str] = []
    for candidate in candidates:
        cleaned = normalize_package_candidate(candidate)
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


def packages_from_install_command(command: str) -> list[str]:
    tokens = command.split()
    if "install" not in tokens:
        return []
    packages = []
    seen_install = False
    for token in tokens:
        if not seen_install:
            seen_install = token == "install"
            continue
        if token.startswith("-"):
            continue
        packages.append(token)
    return packages


def normalize_package_candidate(candidate: str) -> str | None:
    text = candidate.strip()
    if not text:
        return None
    if text.startswith(("git+", "http://", "https://")):
        return None
    text = text.split("[", 1)[0]
    text = re.split(r"[<>=!~]", text, maxsplit=1)[0]
    text = text.strip().strip("'\"")
    if not re.match(r"^[A-Za-z0-9_.-]+$", text):
        return None
    return text


def script_path_candidates(entry_point: str | None) -> list[dict[str, Any]]:
    if not entry_point:
        return []
    names = [entry_point]
    if os.name == "nt":
        names.extend([f"{entry_point}.exe", f"{entry_point}.bat", f"{entry_point}.cmd", f"{entry_point}-script.py"])
    dirs = []
    for value in (sysconfig.get_path("scripts"), str(Path(sys.executable).parent / "Scripts")):
        if value and value not in dirs:
            dirs.append(value)
    reports = []
    for directory in dirs:
        for name in names:
            path = Path(directory) / name
            reports.append(
                {
                    "path": str(path),
                    "exists": path.exists(),
                    "directory": directory,
                }
            )
    return reports


def distribution_report(package: str) -> dict[str, Any]:
    try:
        dist = importlib_metadata.distribution(package)
    except importlib_metadata.PackageNotFoundError:
        return {
            "package": package,
            "installed": False,
            "version": None,
            "location": None,
            "console_scripts": [],
        }
    console_scripts = [
        {"name": ep.name, "value": ep.value}
        for ep in dist.entry_points
        if ep.group == "console_scripts"
    ]
    return {
        "package": package,
        "installed": True,
        "version": dist.version,
        "location": str(Path(dist.locate_file(""))),
        "console_scripts": console_scripts,
    }


def module_report(package: str) -> dict[str, Any]:
    try:
        spec = importlib_util.find_spec(package)
    except Exception as exc:
        return {
            "package": package,
            "importable": False,
            "origin": None,
            "module_main": False,
            "error": str(exc),
        }
    if spec is None:
        return {
            "package": package,
            "importable": False,
            "origin": None,
            "module_main": False,
            "error": None,
        }
    module_main = False
    if spec.submodule_search_locations:
        for location in spec.submodule_search_locations:
            if (Path(location) / "__main__.py").exists():
                module_main = True
                break
    return {
        "package": package,
        "importable": True,
        "origin": spec.origin,
        "module_main": module_main,
        "error": None,
    }


def entrypoint_diagnosis(
    entry_point: str | None,
    entrypoint_path: str | None,
    script_candidates: list[dict[str, Any]],
    distribution_reports: list[dict[str, Any]],
    module_reports: list[dict[str, Any]],
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    if entrypoint_path:
        return entrypoint_available_diagnosis()
    context = entrypoint_diagnosis_context(
        entry_point,
        script_candidates,
        distribution_reports,
        module_reports,
        evaluation,
    )
    state, action = entrypoint_diagnosis_state(
        gates=context.gates,
        installed_dists=context.installed_dists,
        matching_scripts=context.matching_scripts,
        existing_script_files=context.existing_script_files,
    )
    return entrypoint_repair_diagnosis_payload(state, action, entry_point, context)


def entrypoint_available_diagnosis() -> dict[str, Any]:
    return {
        "state": "entrypoint_available",
        "repair_required": False,
        "recommended_next_action": "verify_harness_runtime",
        "findings": ["entrypoint is available on PATH"],
    }


def entrypoint_repair_diagnosis_payload(
    state: str,
    action: str,
    entry_point: str | None,
    context: EntrypointDiagnosisContext,
) -> dict[str, Any]:
    return {
        "state": state,
        "repair_required": True,
        "recommended_next_action": action,
        "findings": entrypoint_diagnosis_findings(
            entry_point=entry_point,
            installed_dists=context.installed_dists,
            matching_scripts=context.matching_scripts,
            existing_script_files=context.existing_script_files,
            runnable_modules=context.runnable_modules,
        ),
    }


def entrypoint_diagnosis_context(
    entry_point: str | None,
    script_candidates: list[dict[str, Any]],
    distribution_reports: list[dict[str, Any]],
    module_reports: list[dict[str, Any]],
    evaluation: dict[str, Any],
) -> EntrypointDiagnosisContext:
    matching_scripts = [
        script
        for report in distribution_reports
        for script in report.get("console_scripts", [])
        if script.get("name") == entry_point
    ]
    gates = evaluation.get("gates") if isinstance(evaluation.get("gates"), dict) else {}
    return EntrypointDiagnosisContext(
        gates=gates,
        installed_dists=[report for report in distribution_reports if report.get("installed")],
        matching_scripts=matching_scripts,
        existing_script_files=[item for item in script_candidates if item.get("exists")],
        runnable_modules=[item for item in module_reports if item.get("module_main")],
    )


def entrypoint_diagnosis_findings(
    *,
    entry_point: str | None,
    installed_dists: list[dict[str, Any]],
    matching_scripts: list[dict[str, Any]],
    existing_script_files: list[dict[str, Any]],
    runnable_modules: list[dict[str, Any]],
) -> list[str]:
    findings = []
    if entry_point:
        findings.append(f"entrypoint is not on PATH: {entry_point}")
    findings.append(
        "python package distribution is installed"
        if installed_dists
        else "no matching python package distribution found"
    )
    if matching_scripts:
        findings.append("matching console_script exists in package metadata")
    elif installed_dists:
        findings.append("installed package has no matching console_script")
    if existing_script_files:
        findings.append("entrypoint file exists in a scripts directory but is not on PATH")
    if runnable_modules:
        findings.append("package exposes a python -m module entry")
    return findings


def entrypoint_diagnosis_state(
    *,
    gates: dict[str, Any],
    installed_dists: list[dict[str, Any]],
    matching_scripts: list[dict[str, Any]],
    existing_script_files: list[dict[str, Any]],
) -> tuple[str, str]:
    if gates.get("installed") and not gates.get("entrypoint_available"):
        return "installed_entrypoint_missing", "repair_market_metadata_or_create_entrypoint_wrapper"
    if installed_dists and not matching_scripts:
        return "package_without_declared_console_script", "repair_market_metadata_or_choose_module_adapter"
    if existing_script_files:
        return "script_exists_but_path_missing", "add_scripts_directory_to_path_or_use_absolute_entrypoint"
    return "entrypoint_unresolved", "inspect_package_and_market_metadata"


def entrypoint_repair_strategy(plan: dict[str, Any], module: str | None) -> dict[str, Any]:
    diagnosis = plan.get("diagnosis") if isinstance(plan.get("diagnosis"), dict) else {}
    if diagnosis.get("repair_required") is False:
        return repair_strategy_result(
            False,
            "repair_not_required",
            None,
            ["entrypoint is already available"],
            "verify_harness_runtime",
        )
    if not module:
        module = default_repair_module(plan)
    if not module:
        return repair_strategy_result(
            False,
            "adapter_target_required",
            None,
            ["no importable module with __main__.py was found; pass --module after inspecting the package API"],
            "choose_explicit_python_module_or_custom_adapter",
        )
    module_check = module_report(module)
    if not module_check["importable"]:
        return repair_strategy_result(
            False,
            "module_not_importable",
            module,
            [f"module is not importable: {module}"],
            "choose_importable_python_module",
            module_check,
        )
    return repair_strategy_result(
        True,
        "python_module_wrapper",
        module,
        [],
        "write_wrapper_and_repaired_manifest",
        module_check,
    )


def default_repair_module(plan: dict[str, Any]) -> str | None:
    for item in plan.get("modules", []):
        if item.get("importable") and item.get("module_main"):
            return str(item["package"])
    return None


def repair_strategy_result(
    ready: bool,
    state: str,
    module: str | None,
    blockers: list[str],
    next_action: str,
    module_report_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ready": ready,
        "state": state,
        "module": module,
        "blockers": blockers,
        "recommended_next_action": next_action,
    }
    if module_report_payload is not None:
        result["module_report"] = module_report_payload
    return result


def entrypoint_wrapper_path(
    external_plugins: Path,
    harness_name: str,
    safe_name: str | None = None,
) -> Path:
    safe_name = safe_name or sanitize_harness_name(harness_name)
    return external_plugins / PLUGIN_ID / "entrypoints" / f"{safe_name}.py"


def python_module_wrapper_content(module: str) -> str:
    return "\n".join(
        [
            "# Generated by CBN for a CLI-Anything harness whose declared entrypoint is missing.",
            "# This wrapper stays under external_plugins and does not modify global PATH.",
            "from __future__ import annotations",
            "",
            "from pathlib import Path",
            "import runpy",
            "import sys",
            "",
            f"MODULE = {module!r}",
            "",
            "",
            "if __name__ == \"__main__\":",
            "    wrapper_dir = str(Path(__file__).resolve().parent)",
            "    sys.path[:] = [entry for entry in sys.path if str(Path(entry or '.').resolve()) != wrapper_dir]",
            "    runpy.run_module(MODULE, run_name=\"__main__\", alter_sys=True)",
            "",
        ]
    )


def write_repair_entrypoint_files(
    *,
    operation_id: str,
    root: Path,
    wrapper_path: Path,
    module: str,
    manifest_path: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    backup_dir = root / "runtime" / "backups" / "cli-anything-repair" / operation_id
    written: list[str] = []
    backups: list[dict[str, Any]] = []
    for item in repair_entrypoint_write_items(wrapper_path, module, manifest_path, manifest):
        result = atomic_write_text_with_backup(
            path=item["path"],
            text=item["text"],
            backup_dir=backup_dir,
            operation_id=operation_id,
        )
        record_repair_entrypoint_write_result(item, result, written, backups)
    return {
        "status": "completed",
        "operation_id": operation_id,
        "written": written,
        "backups": backups,
        "atomic": True,
        "backup_dir": str(backup_dir),
    }


def repair_entrypoint_write_items(
    wrapper_path: Path,
    module: str,
    manifest_path: Path,
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        {"kind": "wrapper", "path": wrapper_path, "text": python_module_wrapper_content(module)},
        {
            "kind": "manifest",
            "path": manifest_path,
            "text": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        },
    ]


def record_repair_entrypoint_write_result(
    item: dict[str, Any],
    result: dict[str, Any],
    written: list[str],
    backups: list[dict[str, Any]],
) -> None:
    result["kind"] = item["kind"]
    written.append(result["path"])
    if not result["backup_path"]:
        return
    backups.append(
        {
            "kind": item["kind"],
            "path": result["path"],
            "backup_path": result["backup_path"],
            "backup_size_bytes": result["backup_size_bytes"],
        }
    )


def atomic_write_text_with_backup(
    *,
    path: Path,
    text: str,
    backup_dir: Path,
    operation_id: str,
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = None
    backup_size_bytes = 0
    if path.exists():
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{path.name}.bak"
        shutil.copy2(path, backup_path)
        backup_size_bytes = backup_path.stat().st_size
    temp_path = path.with_name(f".{path.name}.{operation_id}.tmp")
    temp_path.write_text(text, encoding="utf-8")
    os.replace(temp_path, path)
    return {
        "path": str(path),
        "size_bytes": len(text.encode("utf-8")),
        "backup_path": str(backup_path) if backup_path else None,
        "backup_size_bytes": backup_size_bytes,
        "temp_path": str(temp_path),
    }


def entrypoint_repair_manifest(
    plan: dict[str, Any],
    strategy: dict[str, Any],
    wrapper_path: Path,
) -> dict[str, Any]:
    manifest = json.loads(json.dumps(plan["evaluation"]["adaptation"]["manifest"]))
    annotations = manifest.setdefault("metadata", {}).setdefault("annotations", {})
    transport = manifest.setdefault("spec", {}).setdefault("transport", {})
    original_transport = json.loads(json.dumps(transport))
    module_provenance = entrypoint_repair_module_provenance(plan, strategy)
    policy_recheck = entrypoint_repair_policy_recheck(plan, manifest)
    apply_entrypoint_repair_annotations(
        annotations,
        strategy=strategy,
        wrapper_path=wrapper_path,
        original_transport=original_transport,
        module_provenance=module_provenance,
        policy_recheck=policy_recheck,
    )
    apply_entrypoint_repair_transport(transport, wrapper_path)
    annotations["cbn.repair.wrapper_transport"] = json.dumps(transport, ensure_ascii=False, sort_keys=True)
    manifest.setdefault("spec", {})["policy"] = manifest_policy_from_recheck(policy_recheck["effective_policy"])
    return manifest


def apply_entrypoint_repair_annotations(
    annotations: dict[str, Any],
    *,
    strategy: dict[str, Any],
    wrapper_path: Path,
    original_transport: dict[str, Any],
    module_provenance: dict[str, Any],
    policy_recheck: dict[str, Any],
) -> None:
    annotations["cbn.repair.kind"] = "cli-anything-entrypoint-wrapper"
    annotations["cbn.repair.original_transport"] = json.dumps(original_transport, ensure_ascii=False, sort_keys=True)
    annotations["cbn.repair.original_command"] = str(original_transport.get("command", ""))
    annotations["cbn.repair.original_argsTemplate"] = json.dumps(
        original_transport.get("argsTemplate", []),
        ensure_ascii=False,
    )
    annotations["cbn.repair.wrapper_path"] = str(wrapper_path)
    annotations["cbn.repair.strategy"] = str(strategy.get("state"))
    annotations["cbn.repair.python_executable"] = sys.executable
    annotations["cbn.repair.module_provenance"] = json.dumps(
        module_provenance,
        ensure_ascii=False,
        sort_keys=True,
    )
    annotations["cbn.repair.policy_recheck"] = json.dumps(
        policy_recheck,
        ensure_ascii=False,
        sort_keys=True,
    )
    if strategy.get("module"):
        annotations["cbn.repair.python_module"] = str(strategy["module"])
    if module_provenance.get("distribution"):
        annotations["cbn.repair.python_distribution"] = str(module_provenance["distribution"])
    if module_provenance.get("version"):
        annotations["cbn.repair.python_distribution_version"] = str(module_provenance["version"])


def apply_entrypoint_repair_transport(transport: dict[str, Any], wrapper_path: Path) -> None:
    transport["kind"] = "pty"
    transport["command"] = sys.executable
    transport["argsTemplate"] = [str(wrapper_path)]
    transport["cwdPolicy"] = transport.get("cwdPolicy", "workspace")


def entrypoint_repair_manifest_provenance(manifest: dict[str, Any]) -> dict[str, Any]:
    annotations = manifest.get("metadata", {}).get("annotations", {})
    if not isinstance(annotations, dict):
        return {}
    return {
        "kind": annotations.get("cbn.repair.kind"),
        "original_transport": _json_annotation(annotations.get("cbn.repair.original_transport")),
        "wrapper_transport": _json_annotation(annotations.get("cbn.repair.wrapper_transport")),
        "module_provenance": _json_annotation(annotations.get("cbn.repair.module_provenance")),
        "policy_recheck": _json_annotation(annotations.get("cbn.repair.policy_recheck")),
        "smoke": {
            "module": annotations.get("cbn.repair.smoke.module"),
            "args": _json_annotation(annotations.get("cbn.repair.smoke.args")),
            "exit_code": annotations.get("cbn.repair.smoke.exit_code"),
        },
    }


def entrypoint_repair_module_provenance(plan: dict[str, Any], strategy: dict[str, Any]) -> dict[str, Any]:
    module = strategy.get("module")
    module_check = strategy.get("module_report") if isinstance(strategy.get("module_report"), dict) else {}
    distributions = plan.get("distributions") if isinstance(plan.get("distributions"), list) else []
    distribution = distribution_for_module(str(module) if module else "", distributions)
    return {
        "module": module,
        "module_importable": module_check.get("importable"),
        "module_origin": module_check.get("origin"),
        "module_main": module_check.get("module_main"),
        "distribution": distribution.get("package") if distribution else None,
        "version": distribution.get("version") if distribution else None,
        "location": distribution.get("location") if distribution else None,
    }


def distribution_for_module(module: str, distributions: list[Any]) -> dict[str, Any] | None:
    if not module:
        return None
    matched = installed_distribution_for_module(module, distributions)
    if matched:
        return matched
    return metadata_distribution_for_module(module)


def installed_distribution_for_module(module: str, distributions: list[Any]) -> dict[str, Any] | None:
    normalized_module = module.replace("_", "-").lower()
    for item in distributions:
        if distribution_matches_module(item, module, normalized_module):
            return item
    return None


def distribution_matches_module(item: Any, module: str, normalized_module: str) -> bool:
    if not isinstance(item, dict) or not item.get("installed"):
        return False
    package = str(item.get("package") or "")
    normalized_package = package.replace("_", "-").lower()
    package_import = package.replace("-", "_")
    return normalized_module == normalized_package or module == package_import or module.startswith(package_import + ".")


def metadata_distribution_for_module(module: str) -> dict[str, Any] | None:
    try:
        dist = importlib_metadata.distribution(module.split(".", 1)[0])
    except importlib_metadata.PackageNotFoundError:
        return None
    return {
        "package": dist.metadata.get("Name") or module.split(".", 1)[0],
        "installed": True,
        "version": dist.version,
        "location": str(Path(dist.locate_file(""))),
    }


def entrypoint_repair_policy_recheck(plan: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    original = manifest.get("spec", {}).get("policy", {}) if isinstance(manifest.get("spec"), dict) else {}
    original_policy = {
        "risk": str(original.get("risk") or "read"),
        "requires_confirmation": policy_requires_confirmation(original),
        "network": str(original.get("network") or "deny"),
    }
    status = plan.get("evaluation", {}).get("status", {}) if isinstance(plan.get("evaluation"), dict) else {}
    market_record = status.get("market_record") if isinstance(status, dict) and isinstance(status.get("market_record"), dict) else None
    inferred = infer_market_policy(market_record, requested_risk=original_policy["risk"])
    effective = {
        "risk": max_risk(original_policy["risk"], inferred["risk"]),
        "requires_confirmation": bool(original_policy["requires_confirmation"] or inferred["requires_confirmation"]),
        "network": repair_policy_network(original_policy["network"], inferred["network"]),
        "reasons": list(inferred.get("reasons", [])),
    }
    return {
        "original_policy": original_policy,
        "market_record_present": market_record is not None,
        "inferred_policy": inferred,
        "effective_policy": effective,
        "changed": (
            original_policy["risk"] != effective["risk"]
            or original_policy["requires_confirmation"] != effective["requires_confirmation"]
            or original_policy["network"] != effective["network"]
        ),
    }


def _json_annotation(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def repair_policy_network(original_network: str, inferred_network: str) -> str:
    if original_network == "requires-confirmation" or inferred_network == "requires-confirmation":
        return "requires-confirmation"
    if original_network == "localhost" or inferred_network == "localhost":
        return "localhost"
    return original_network or inferred_network or "deny"


def manifest_policy_from_recheck(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "risk": policy["risk"],
        "requiresConfirmation": bool(policy["requires_confirmation"]),
        "network": policy["network"],
    }
