"""Adapter target discovery and smoke helpers for CLI-Anything harnesses."""

from __future__ import annotations

import ast
import importlib.metadata as importlib_metadata
import importlib.util as importlib_util
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from cbn_plugins.cli_anything_parts.manifest_factory import sanitize_harness_name
from cbn_plugins.manager import PluginCommand, PluginPlan


PLUGIN_ID = "cli-anything"


def adapter_target_package_report(package: str, limit: int = 20) -> dict[str, Any]:
    try:
        dist = importlib_metadata.distribution(package)
    except importlib_metadata.PackageNotFoundError:
        return {
            "package": package,
            "installed": False,
            "version": None,
            "targets": [],
            "blockers": [f"python package distribution is not installed: {package}"],
        }
    top_levels = distribution_top_levels(dist, package)
    targets: list[dict[str, Any]] = []
    scanned_files = 0
    for top_level in top_levels:
        spec = importlib_util.find_spec(top_level)
        if spec is None:
            continue
        locations = list(spec.submodule_search_locations or [])
        if not locations and spec.origin:
            locations = [str(Path(spec.origin).parent)]
        for location in locations:
            root = Path(location)
            if not root.exists():
                continue
            for path in sorted(root.rglob("*.py")):
                if "__pycache__" in path.parts:
                    continue
                scanned_files += 1
                target = module_adapter_target(path, root, top_level)
                if target is not None:
                    targets.append(target)
                if scanned_files >= 500:
                    break
            if scanned_files >= 500:
                break
        if scanned_files >= 500:
            break
    targets.sort(key=lambda item: (-int(item["score"]), item["module"]))
    bounded_limit = max(0, min(limit, 100))
    return {
        "package": package,
        "installed": True,
        "version": dist.version,
        "location": str(Path(dist.locate_file(""))),
        "top_levels": top_levels,
        "scanned_files": scanned_files,
        "targets": targets[:bounded_limit],
        "truncated": len(targets) > bounded_limit,
        "blockers": [] if targets else ["no CLI-like python module targets found"],
    }


def distribution_top_levels(dist: importlib_metadata.Distribution, package: str) -> list[str]:
    raw = dist.read_text("top_level.txt") or ""
    names = [line.strip() for line in raw.splitlines() if line.strip()]
    fallback = package.replace("-", "_").split(".", 1)[0]
    if fallback in names:
        return [fallback]
    if fallback and fallback not in names:
        names.append(fallback)
    return [name for name in names if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name)]


def module_adapter_target(path: Path, root: Path, top_level: str) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(text)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None
    rel = path.relative_to(root)
    module_parts = [top_level]
    if rel.name == "__init__.py":
        module_parts.extend(rel.parent.parts)
    elif rel.name == "__main__.py":
        module_parts.extend(rel.parent.parts)
    else:
        module_parts.extend(rel.with_suffix("").parts)
    module = ".".join(part for part in module_parts if part)
    evidence: list[str] = []
    score = 0
    if rel.name == "__main__.py":
        score += 90
        evidence.append("__main__.py module")
    if has_name_main_guard(tree):
        score += 70
        evidence.append("if __name__ == '__main__'")
    imports = imported_root_names(tree)
    for name, points in (("click", 35), ("typer", 35), ("argparse", 25), ("fire", 25)):
        if name in imports:
            score += points
            evidence.append(f"imports {name}")
    functions = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if "main" in functions:
        score += 25
        evidence.append("defines main()")
    if "cli" in functions:
        score += 15
        evidence.append("defines cli()")
    if not evidence:
        return None
    kind = "python-module-main" if rel.name == "__main__.py" else "python-module"
    if any(item.startswith("imports ") for item in evidence):
        kind = "python-cli-framework"
    return {
        "module": module,
        "kind": kind,
        "score": score,
        "path": str(path),
        "evidence": evidence,
        "command_preview": f"{sys.executable} -m {module}",
    }


def imported_root_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".", 1)[0])
    return names


def has_name_main_guard(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if is_name_main_compare(node.test):
            return True
    return False


def is_name_main_compare(node: ast.AST) -> bool:
    if not isinstance(node, ast.Compare) or len(node.ops) != 1 or not isinstance(node.ops[0], ast.Eq):
        return False
    if len(node.comparators) != 1:
        return False
    left = node.left
    right = node.comparators[0]
    return (
        isinstance(left, ast.Name)
        and left.id == "__name__"
        and isinstance(right, ast.Constant)
        and right.value == "__main__"
    )


def adapter_target_smoke_execution(
    argv: tuple[str, ...],
    cwd: Path,
    timeout_seconds: int,
    run: bool,
    confirmed: bool,
    operation_runner: Any,
    plugin_dir: Path,
    harness_name: str,
    module: str,
) -> dict[str, Any]:
    bounded_timeout = max(1, min(int(timeout_seconds), 120))
    if not run:
        return {
            "status": "not_run",
            "requires_confirmation": True,
            "confirmed": confirmed,
            "exit_code": None,
            "reason": "adapter target smoke is a plan until --run is provided",
            "cwd": str(cwd),
            "stdout_summary": "",
            "stderr_summary": "",
        }
    if not confirmed:
        return {
            "status": "requires_confirmation",
            "requires_confirmation": True,
            "confirmed": False,
            "exit_code": None,
            "reason": "adapter target smoke execution requires --yes or confirmed=true",
            "cwd": str(cwd),
            "stdout_summary": "",
            "stderr_summary": "",
        }
    smoke_root = cwd / "runtime" / "adapter-smoke"
    smoke_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="run-", dir=smoke_root) as smoke_cwd:
        plan = PluginPlan(
            plugin_id=PLUGIN_ID,
            action=f"adapter-smoke-{sanitize_harness_name(harness_name)}",
            plugin_dir=str(plugin_dir),
            commands=(
                PluginCommand(
                    label=f"Adapter smoke: {harness_name} -> {module}",
                    argv=argv,
                    cwd=smoke_cwd,
                    timeout_seconds=bounded_timeout,
                    env={"CBN_ADAPTER_SMOKE": "1"},
                ),
            ),
            notes=(
                "Executable adapter smoke runs through the plugin operation boundary.",
                f"Harness: {harness_name}",
                f"Module: {module}",
            ),
        )
        operation = operation_runner.execute(plan)
        smoke_cwd_value = smoke_cwd
    command = operation["results"][0] if operation.get("results") else {}
    exit_code = command.get("exit_code")
    if operation.get("status") == "blocked":
        status = "blocked"
        reason = "; ".join(operation.get("blockers", [])) or "plugin operation blocked"
    elif command.get("timed_out"):
        status = "timeout"
        reason = f"command timed out after {bounded_timeout} seconds"
    elif exit_code == 127:
        status = "spawn_failed"
        reason = command.get("stderr") or "command failed to start"
    else:
        status = "completed" if exit_code == 0 else "failed"
        reason = "completed" if exit_code == 0 else "nonzero_exit"
    return {
        "status": status,
        "requires_confirmation": True,
        "confirmed": True,
        "exit_code": exit_code,
        "reason": reason,
        "cwd": smoke_cwd_value,
        "stdout_summary": clip_text(str(command.get("stdout") or ""), 2000),
        "stderr_summary": clip_text(str(command.get("stderr") or ""), 2000),
        "operation_id": operation.get("operation_id"),
        "operation_status": operation.get("status"),
        "command_id": command.get("command_id"),
        "artifact_ids": command.get("artifact_ids", []),
        "operation": operation,
    }


def adapter_target_smoke_next_action(
    selected: dict[str, Any] | None,
    module_report: dict[str, Any],
    execution: dict[str, Any],
) -> str:
    if not module_report.get("importable"):
        return "choose_importable_module"
    if selected is None:
        return "inspect_module_before_repair"
    if execution["status"] == "not_run":
        return "run_adapter_smoke_with_confirmation"
    if execution["status"] == "requires_confirmation":
        return "confirm_adapter_smoke_execution"
    if execution.get("exit_code") == 0:
        return "repair_entrypoint_with_smoked_module"
    return "inspect_smoke_failure_or_choose_another_target"


def repair_entrypoint_smoke_gate(
    require_smoke: bool,
    smoke_report: dict[str, Any] | None,
) -> dict[str, Any]:
    if not require_smoke:
        return {
            "required": False,
            "ok": True,
            "status": "not_required",
            "blockers": [],
        }
    if smoke_report is None:
        return {
            "required": True,
            "ok": False,
            "status": "blocked",
            "blockers": ["smoke gate requires a ready module strategy"],
        }
    execution = smoke_report.get("execution", {})
    if execution.get("status") == "not_run":
        return {
            "required": True,
            "ok": False,
            "status": "not_run",
            "blockers": ["smoke gate has not run; use --write --yes or run adapter-smoke first"],
        }
    if execution.get("status") == "requires_confirmation":
        return {
            "required": True,
            "ok": False,
            "status": "requires_confirmation",
            "blockers": ["smoke gate execution requires confirmation"],
        }
    if smoke_report.get("summary", {}).get("smoke_ok"):
        return {
            "required": True,
            "ok": True,
            "status": "passed",
            "blockers": [],
        }
    return {
        "required": True,
        "ok": False,
        "status": "failed",
        "blockers": [
            f"adapter target smoke failed: {execution.get('reason', 'unknown')}",
        ],
    }


def clip_text(value: str | None, limit: int) -> str:
    text = value or ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...<truncated>"
