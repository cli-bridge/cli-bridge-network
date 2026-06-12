"""Entrypoint repair helpers for CLI-Anything harnesses."""

from __future__ import annotations

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


def entrypoint_repair_plan(
    hub: Any,
    harness_name: str,
    from_market: bool = True,
) -> dict[str, Any]:
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
    return {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "kind": "CliAnythingEntrypointRepairPlan",
        "harness_name": harness_name,
        "from_market": from_market,
        "capability_id": evaluation.get("capability_id"),
        "entry_point": entry_point,
        "entrypoint_path": entrypoint_path,
        "entrypoint_available": bool(entrypoint_path),
        "package_candidates": package_candidates,
        "script_candidates": script_candidates,
        "distributions": distribution_reports,
        "modules": module_reports,
        "diagnosis": diagnosis,
        "evaluation": evaluation,
        "commands": {
            "status": f"python -m cbn plugin harness cli-anything status {harness_name} --from-market",
            "evaluate": f"python -m cbn plugin evaluate-harness cli-anything {harness_name} --from-market",
            "blocked_plan": f"python -m cbn plugin blocked-plan cli-anything --harness {harness_name}",
            "where_entrypoint": f"where.exe {entry_point}" if entry_point else None,
            "pip_show": f"python -m pip show {package_candidates[0]}" if package_candidates else None,
            "cli_hub_launch_help": f"cli-hub launch {harness_name} -- --help",
        },
    }


def repair_entrypoint(
    hub: Any,
    harness_name: str,
    from_market: bool = True,
    module: str | None = None,
    write: bool = False,
    confirmed: bool = False,
    require_smoke: bool = False,
    smoke_args: tuple[str, ...] = ("--help",),
    smoke_timeout_seconds: int = 10,
    smoke_gate_fn: Callable[[bool, dict[str, Any] | None], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if smoke_gate_fn is None:
        from cbn_plugins.cli_anything_parts.adapter_targets import repair_entrypoint_smoke_gate

        smoke_gate_fn = repair_entrypoint_smoke_gate

    plan = hub.entrypoint_repair_plan(harness_name, from_market=from_market)
    strategy = entrypoint_repair_strategy(plan, module=module)
    execution: dict[str, Any] = {
        "requested": write,
        "confirmed": confirmed,
        "status": "not_requested",
        "blockers": [],
        "written": [],
    }
    wrapper_path = entrypoint_wrapper_path(hub.paths.external_plugins, harness_name)
    smoke_report = None
    if require_smoke and strategy.get("ready") and strategy.get("module"):
        smoke_report = hub.adapter_target_smoke(
            harness_name,
            module=strategy["module"],
            from_market=from_market,
            smoke_args=smoke_args,
            timeout_seconds=smoke_timeout_seconds,
            run=write,
            confirmed=confirmed,
        )
    smoke_gate = smoke_gate_fn(require_smoke, smoke_report)
    manifest = entrypoint_repair_manifest(plan, strategy, wrapper_path)
    repair_manifest_path = hub.paths.local_manifests / f"{plan['capability_id']}.json"
    if smoke_report and smoke_report.get("summary", {}).get("smoke_ok"):
        annotations = manifest.setdefault("metadata", {}).setdefault("annotations", {})
        annotations["cbn.repair.smoke.module"] = str(smoke_report["module"])
        annotations["cbn.repair.smoke.args"] = json.dumps(smoke_report["smoke_args"], ensure_ascii=False)
        annotations["cbn.repair.smoke.exit_code"] = str(smoke_report["execution"].get("exit_code"))
    parser_fixture_gate = mark_repaired_manifest_verified_from_fixtures(
        manifest=manifest,
        capability_id=str(plan["capability_id"]),
        fixture_dir=hub.paths.root / "parser_fixtures",
        root=hub.paths.root,
        smoke_ok=bool(smoke_report and smoke_report.get("summary", {}).get("smoke_ok")),
    )
    validation = validate_manifest_dict(
        manifest,
        source_path=repair_manifest_path,
        known_parser_refs=known_parser_refs(),
    )
    if write and not confirmed:
        execution["status"] = "requires_confirmation"
        execution["blockers"] = ["entrypoint repair writes require --yes or confirmed=true"]
    elif write and confirmed and not strategy["ready"]:
        execution["status"] = "blocked"
        execution["blockers"] = list(strategy["blockers"])
    elif write and confirmed and not smoke_gate["ok"]:
        execution["status"] = "blocked"
        execution["blockers"] = list(smoke_gate["blockers"])
    elif write and confirmed and not validation["valid"]:
        execution["status"] = "blocked"
        execution["blockers"] = [f"manifest validation error: {item}" for item in validation["errors"]]
    elif write and confirmed:
        repair_operation = hub.operation_runner.execute_write(
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
        write_result = repair_operation.get("write_result") or {}
        execution["status"] = repair_operation.get("status", "failed")
        execution["operation_id"] = repair_operation.get("operation_id")
        execution["operation_status"] = repair_operation.get("status")
        execution["artifact_ids"] = repair_operation.get("artifact_ids", [])
        execution["write_result"] = write_result
        execution["written"] = list(write_result.get("written", []))
        execution["backups"] = list(write_result.get("backups", []))
        if execution["status"] != "completed":
            execution["blockers"] = list(repair_operation.get("blockers", []))
            if not execution["blockers"] and write_result.get("error"):
                execution["blockers"] = [str(write_result["error"])]
    return {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "kind": "CliAnythingEntrypointRepair",
        "harness_name": harness_name,
        "from_market": from_market,
        "module": module,
        "write": write,
        "confirmed": confirmed,
        "require_smoke": require_smoke,
        "smoke_args": list(smoke_args),
        "smoke_timeout_seconds": smoke_timeout_seconds,
        "plan": plan,
        "strategy": strategy,
        "smoke_gate": smoke_gate,
        "smoke_report": smoke_report,
        "wrapper_path": str(wrapper_path),
        "manifest_path": str(repair_manifest_path),
        "manifest": manifest,
        "repair_provenance": entrypoint_repair_manifest_provenance(manifest),
        "parser_fixtures": parser_fixture_gate,
        "validation": validation,
        "execution": execution,
        "next_commands": [
            f"python -m cbn plugin repair-plan cli-anything {harness_name} --from-market",
            f"python -m cbn plugin repair-entrypoint cli-anything {harness_name} --from-market --module <module>",
            f"python -m cbn plugin adapter-smoke cli-anything {harness_name} --from-market --module <module> --run --yes",
            f"python -m cbn plugin repair-entrypoint cli-anything {harness_name} --from-market --module <module> --write --yes",
            f"python -m cbn plugin repair-entrypoint cli-anything {harness_name} --from-market --module <module> --require-smoke --write --yes",
            "python -m cbn registry validate runtime/manifests",
            f"python -m cbn call {plan.get('capability_id')} --dry-run",
        ],
    }


def entrypoint_package_candidates(
    harness_name: str,
    market_record: dict[str, Any] | None,
    status: dict[str, Any],
) -> list[str]:
    candidates: list[str] = []
    if market_record:
        for key in ("name", "package", "pip_package", "npm_package"):
            value = market_record.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())
        install_cmd = market_record.get("install_cmd")
        if isinstance(install_cmd, str):
            candidates.extend(packages_from_install_command(install_cmd))
    fields = status.get("cli_hub_info", {}).get("fields", {})
    if isinstance(fields, dict):
        install_cmd = fields.get("install_cmd")
        if isinstance(install_cmd, str):
            candidates.extend(packages_from_install_command(install_cmd))
    candidates.append(harness_name)
    normalized = []
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
        return {
            "state": "entrypoint_available",
            "repair_required": False,
            "recommended_next_action": "verify_harness_runtime",
            "findings": ["entrypoint is available on PATH"],
        }
    findings = []
    if entry_point:
        findings.append(f"entrypoint is not on PATH: {entry_point}")
    installed_dists = [report for report in distribution_reports if report.get("installed")]
    if installed_dists:
        findings.append("python package distribution is installed")
    else:
        findings.append("no matching python package distribution found")
    matching_scripts = [
        script
        for report in distribution_reports
        for script in report.get("console_scripts", [])
        if script.get("name") == entry_point
    ]
    if matching_scripts:
        findings.append("matching console_script exists in package metadata")
    elif installed_dists:
        findings.append("installed package has no matching console_script")
    existing_script_files = [item for item in script_candidates if item.get("exists")]
    if existing_script_files:
        findings.append("entrypoint file exists in a scripts directory but is not on PATH")
    runnable_modules = [item for item in module_reports if item.get("module_main")]
    if runnable_modules:
        findings.append("package exposes a python -m module entry")
    gates = evaluation.get("gates") if isinstance(evaluation.get("gates"), dict) else {}
    if gates.get("installed") and not gates.get("entrypoint_available"):
        state = "installed_entrypoint_missing"
        action = "repair_market_metadata_or_create_entrypoint_wrapper"
    elif installed_dists and not matching_scripts:
        state = "package_without_declared_console_script"
        action = "repair_market_metadata_or_choose_module_adapter"
    elif existing_script_files:
        state = "script_exists_but_path_missing"
        action = "add_scripts_directory_to_path_or_use_absolute_entrypoint"
    else:
        state = "entrypoint_unresolved"
        action = "inspect_package_and_market_metadata"
    return {
        "state": state,
        "repair_required": True,
        "recommended_next_action": action,
        "findings": findings,
    }


def entrypoint_repair_strategy(plan: dict[str, Any], module: str | None) -> dict[str, Any]:
    diagnosis = plan.get("diagnosis") if isinstance(plan.get("diagnosis"), dict) else {}
    if diagnosis.get("repair_required") is False:
        return {
            "ready": False,
            "state": "repair_not_required",
            "module": None,
            "blockers": ["entrypoint is already available"],
            "recommended_next_action": "verify_harness_runtime",
        }
    if not module:
        runnable_modules = [
            item
            for item in plan.get("modules", [])
            if item.get("importable") and item.get("module_main")
        ]
        if runnable_modules:
            module = str(runnable_modules[0]["package"])
        else:
            return {
                "ready": False,
                "state": "adapter_target_required",
                "module": None,
                "blockers": [
                    "no importable module with __main__.py was found; pass --module after inspecting the package API"
                ],
                "recommended_next_action": "choose_explicit_python_module_or_custom_adapter",
            }
    module_check = module_report(module)
    if not module_check["importable"]:
        return {
            "ready": False,
            "state": "module_not_importable",
            "module": module,
            "module_report": module_check,
            "blockers": [f"module is not importable: {module}"],
            "recommended_next_action": "choose_importable_python_module",
        }
    return {
        "ready": True,
        "state": "python_module_wrapper",
        "module": module,
        "module_report": module_check,
        "blockers": [],
        "recommended_next_action": "write_wrapper_and_repaired_manifest",
    }


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
    writes = [
        {
            "kind": "wrapper",
            "path": wrapper_path,
            "text": python_module_wrapper_content(module),
        },
        {
            "kind": "manifest",
            "path": manifest_path,
            "text": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        },
    ]
    written: list[str] = []
    backups: list[dict[str, Any]] = []
    for item in writes:
        result = atomic_write_text_with_backup(
            path=item["path"],
            text=item["text"],
            backup_dir=backup_dir,
            operation_id=operation_id,
        )
        result["kind"] = item["kind"]
        written.append(result["path"])
        if result["backup_path"]:
            backups.append(
                {
                    "kind": item["kind"],
                    "path": result["path"],
                    "backup_path": result["backup_path"],
                    "backup_size_bytes": result["backup_size_bytes"],
                }
            )
    return {
        "status": "completed",
        "operation_id": operation_id,
        "written": written,
        "backups": backups,
        "atomic": True,
        "backup_dir": str(backup_dir),
    }


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
    annotations["cbn.repair.kind"] = "cli-anything-entrypoint-wrapper"
    annotations["cbn.repair.original_transport"] = json.dumps(original_transport, ensure_ascii=False, sort_keys=True)
    annotations["cbn.repair.original_command"] = str(transport.get("command", ""))
    annotations["cbn.repair.original_argsTemplate"] = json.dumps(
        transport.get("argsTemplate", []),
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
    transport["kind"] = "pty"
    transport["command"] = sys.executable
    transport["argsTemplate"] = [str(wrapper_path)]
    transport["cwdPolicy"] = transport.get("cwdPolicy", "workspace")
    annotations["cbn.repair.wrapper_transport"] = json.dumps(transport, ensure_ascii=False, sort_keys=True)
    manifest.setdefault("spec", {})["policy"] = manifest_policy_from_recheck(policy_recheck["effective_policy"])
    return manifest


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
    normalized_module = module.replace("_", "-").lower()
    for item in distributions:
        if not isinstance(item, dict) or not item.get("installed"):
            continue
        package = str(item.get("package") or "")
        normalized_package = package.replace("_", "-").lower()
        package_import = package.replace("-", "_")
        if (
            normalized_module == normalized_package
            or module == package_import
            or module.startswith(package_import + ".")
        ):
            return item
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
