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
from typing import Any


PLUGIN_ID = "cli-anything"


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


def entrypoint_wrapper_path(external_plugins: Path, harness_name: str, safe_name: str) -> Path:
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
