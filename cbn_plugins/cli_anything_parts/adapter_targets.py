"""Adapter target discovery and smoke helpers for CLI-Anything harnesses."""

from __future__ import annotations

import ast
import importlib.metadata as importlib_metadata
import importlib.util as importlib_util
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cbn_plugins.cli_anything_parts.manifest_factory import sanitize_harness_name
from cbn_plugins.cli_anything_parts.repair import module_report
from cbn_plugins.manager import PluginCommand, PluginPlan


PLUGIN_ID = "cli-anything"
_ADAPTER_SMOKE_OPTION_NAMES = (
    "from_market",
    "smoke_args",
    "timeout_seconds",
    "run",
    "confirmed",
)


@dataclass(frozen=True)
class AdapterTargetSmokeReportInput:
    harness_name: str
    from_market: bool
    module: str
    smoke_args: tuple[str, ...]
    timeout_seconds: int
    run: bool
    confirmed: bool
    argv: tuple[str, ...]
    selected: dict[str, Any] | None
    module_report_payload: dict[str, Any]
    targets_report: dict[str, Any]
    execution: dict[str, Any]


@dataclass(frozen=True)
class AdapterTargetSmokeRequest:
    harness_name: str
    module: str
    from_market: bool
    smoke_args: tuple[str, ...]
    timeout_seconds: int
    run: bool
    confirmed: bool


@dataclass(frozen=True)
class AdapterSmokeExecutionInput:
    argv: tuple[str, ...]
    cwd: Path
    timeout_seconds: int
    run: bool
    confirmed: bool
    operation_runner: Any
    plugin_dir: Path
    harness_name: str
    module: str


def adapter_targets(
    hub: Any,
    harness_name: str,
    from_market: bool = True,
    package: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    plan = hub.entrypoint_repair_plan(harness_name, from_market=from_market)
    package_candidates = [package] if package else list(plan.get("package_candidates", []))
    package_reports = adapter_target_package_reports(package_candidates, limit)
    targets = sorted_adapter_targets(package_reports, harness_name, limit)
    recommended = targets[0] if targets else None
    return {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "kind": "CliAnythingAdapterTargets",
        "harness_name": harness_name,
        "from_market": from_market,
        "package": package,
        "limit": limit,
        "plan": plan,
        "packages": package_reports,
        "targets": targets,
        "summary": adapter_targets_summary(package_reports, targets, recommended),
        "next_commands": adapter_targets_next_commands(harness_name, recommended),
    }


def adapter_target_package_reports(
    package_candidates: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    return [
        adapter_target_package_report(candidate, limit=limit)
        for candidate in package_candidates
    ]


def sorted_adapter_targets(
    package_reports: list[dict[str, Any]],
    harness_name: str,
    limit: int,
) -> list[dict[str, Any]]:
    targets = [
        adapter_target_entry(harness_name, report, target)
        for report in package_reports
        for target in report.get("targets", [])
    ]
    targets.sort(key=lambda item: (-int(item["score"]), item["module"]))
    return targets[: max(0, min(limit, 100))]


def adapter_target_entry(
    harness_name: str,
    report: dict[str, Any],
    target: dict[str, Any],
) -> dict[str, Any]:
    return {
        **target,
        "package": report["package"],
        "repair_command": (
            f"python -m cbn plugin repair-entrypoint cli-anything {harness_name} "
            f"--from-market --module {target['module']}"
        ),
    }


def adapter_targets_summary(
    package_reports: list[dict[str, Any]],
    targets: list[dict[str, Any]],
    recommended: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "package_count": len(package_reports),
        "target_count": len(targets),
        "recommended_module": recommended["module"] if recommended else None,
        "recommended_score": recommended["score"] if recommended else None,
        "recommended_next_action": (
            "inspect_top_target_then_repair_entrypoint"
            if recommended
            else "write_custom_adapter_or_choose_package_api"
        ),
    }


def adapter_targets_next_commands(
    harness_name: str,
    recommended: dict[str, Any] | None,
) -> list[str | None]:
    return [
        f"python -m cbn plugin repair-plan cli-anything {harness_name} --from-market",
        f"python -m cbn plugin adapter-targets cli-anything {harness_name} --from-market",
        (
            f"python -m cbn plugin repair-entrypoint cli-anything {harness_name} "
            f"--from-market --module {recommended['module']}"
            if recommended
            else None
        ),
    ]


def adapter_target_smoke(
    hub: Any,
    harness_name: str,
    module: str,
    *args: Any,
    **options: Any,
) -> dict[str, Any]:
    request = adapter_target_smoke_request(harness_name, module, args, options)
    targets_report = hub.adapter_targets(request.harness_name, from_market=request.from_market, limit=50)
    selected = selected_adapter_target(targets_report, request.module)
    report = module_report(request.module)
    argv = (sys.executable, "-m", request.module, *request.smoke_args)
    execution = adapter_target_smoke_execution(AdapterSmokeExecutionInput(
        argv=argv,
        cwd=hub.paths.root,
        timeout_seconds=request.timeout_seconds,
        run=request.run,
        confirmed=request.confirmed,
        operation_runner=hub.operation_runner,
        plugin_dir=hub.paths.external_plugins / PLUGIN_ID,
        harness_name=request.harness_name,
        module=request.module,
    ))
    return adapter_target_smoke_report(
        AdapterTargetSmokeReportInput(
            harness_name=request.harness_name,
            from_market=request.from_market,
            module=request.module,
            smoke_args=request.smoke_args,
            timeout_seconds=request.timeout_seconds,
            run=request.run,
            confirmed=request.confirmed,
            argv=argv,
            selected=selected,
            module_report_payload=report,
            targets_report=targets_report,
            execution=execution,
        )
    )


def adapter_target_smoke_request(
    harness_name: str,
    module: str,
    args: tuple[Any, ...],
    options: dict[str, Any],
) -> AdapterTargetSmokeRequest:
    if len(args) > len(_ADAPTER_SMOKE_OPTION_NAMES):
        raise TypeError(f"adapter_target_smoke expected at most {len(_ADAPTER_SMOKE_OPTION_NAMES) + 3} arguments")
    values = {
        "from_market": True,
        "smoke_args": ("--help",),
        "timeout_seconds": 10,
        "run": False,
        "confirmed": False,
    }
    for name, value in zip(_ADAPTER_SMOKE_OPTION_NAMES, args):
        if name in options:
            raise TypeError(f"adapter_target_smoke got multiple values for argument '{name}'")
        values[name] = value
    unknown = sorted(set(options) - set(_ADAPTER_SMOKE_OPTION_NAMES))
    if unknown:
        raise TypeError(f"unknown adapter target smoke option(s): {', '.join(unknown)}")
    values.update(options)
    values["smoke_args"] = tuple(values["smoke_args"])
    return AdapterTargetSmokeRequest(harness_name=harness_name, module=module, **values)


def selected_adapter_target(
    targets_report: dict[str, Any],
    module: str,
) -> dict[str, Any] | None:
    return next(
        (target for target in targets_report.get("targets", []) if target.get("module") == module),
        None,
    )


def adapter_target_smoke_report(report: AdapterTargetSmokeReportInput) -> dict[str, Any]:
    return {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "kind": "CliAnythingAdapterTargetSmoke",
        "harness_name": report.harness_name,
        "from_market": report.from_market,
        "module": report.module,
        "smoke_args": list(report.smoke_args),
        "timeout_seconds": report.timeout_seconds,
        "run": report.run,
        "confirmed": report.confirmed,
        "command": list(report.argv),
        "selected_target": report.selected,
        "module_report": report.module_report_payload,
        "targets_summary": report.targets_report["summary"],
        "execution": report.execution,
        "summary": adapter_target_smoke_summary(report.selected, report.module_report_payload, report.execution),
        "next_commands": adapter_target_smoke_next_commands(report.harness_name, report.module),
    }


def adapter_target_smoke_summary(
    selected: dict[str, Any] | None,
    module_report_payload: dict[str, Any],
    execution: dict[str, Any],
) -> dict[str, Any]:
    return {
        "candidate_known": selected is not None,
        "module_importable": bool(module_report_payload.get("importable")),
        "executed": execution["status"] in {"completed", "failed", "timeout", "spawn_failed"},
        "smoke_ok": execution.get("exit_code") == 0,
        "recommended_next_action": adapter_target_smoke_next_action(
            selected,
            module_report_payload,
            execution,
        ),
    }


def adapter_target_smoke_next_commands(harness_name: str, module: str) -> list[str]:
    return [
        f"python -m cbn plugin adapter-targets cli-anything {harness_name} --from-market --limit 10",
        (
            f"python -m cbn plugin adapter-smoke cli-anything {harness_name} "
            f"--from-market --module {module}"
        ),
        (
            f"python -m cbn plugin adapter-smoke cli-anything {harness_name} "
            f"--from-market --module {module} --run --yes"
        ),
        (
            f"python -m cbn plugin repair-entrypoint cli-anything {harness_name} "
            f"--from-market --module {module} --write --yes"
        ),
    ]


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
    targets, scanned_files = scan_adapter_package_targets(top_levels)
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


def scan_adapter_package_targets(top_levels: list[str]) -> tuple[list[dict[str, Any]], int]:
    targets: list[dict[str, Any]] = []
    scanned_files = 0
    for top_level in top_levels:
        for root in adapter_target_roots(top_level):
            scanned_files = scan_adapter_target_root(root, top_level, targets, scanned_files)
            if scanned_files >= 500:
                return targets, scanned_files
    return targets, scanned_files


def adapter_target_roots(top_level: str) -> list[Path]:
    spec = importlib_util.find_spec(top_level)
    if spec is None:
        return []
    locations = list(spec.submodule_search_locations or [])
    if not locations and spec.origin:
        locations = [str(Path(spec.origin).parent)]
    return [Path(location) for location in locations if Path(location).exists()]


def scan_adapter_target_root(
    root: Path,
    top_level: str,
    targets: list[dict[str, Any]],
    scanned_files: int,
) -> int:
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        scanned_files += 1
        target = module_adapter_target(path, root, top_level)
        if target is not None:
            targets.append(target)
        if scanned_files >= 500:
            break
    return scanned_files


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
    module = module_name_from_path(rel, top_level)
    score, evidence = module_target_score(tree, rel)
    if not evidence:
        return None
    return {
        "module": module,
        "kind": module_target_kind(rel, evidence),
        "score": score,
        "path": str(path),
        "evidence": evidence,
        "command_preview": f"{sys.executable} -m {module}",
    }


def module_name_from_path(rel: Path, top_level: str) -> str:
    module_parts = [top_level]
    if rel.name in {"__init__.py", "__main__.py"}:
        module_parts.extend(rel.parent.parts)
    else:
        module_parts.extend(rel.with_suffix("").parts)
    return ".".join(part for part in module_parts if part)


def module_target_score(tree: ast.AST, rel: Path) -> tuple[int, list[str]]:
    score = 0
    evidence: list[str] = []
    if rel.name == "__main__.py":
        score += 90
        evidence.append("__main__.py module")
    if has_name_main_guard(tree):
        score += 70
        evidence.append("if __name__ == '__main__'")
    score += cli_framework_score(tree, evidence)
    score += cli_function_score(tree, evidence)
    return score, evidence


def cli_framework_score(tree: ast.AST, evidence: list[str]) -> int:
    score = 0
    imports = imported_root_names(tree)
    for name, points in (("click", 35), ("typer", 35), ("argparse", 25), ("fire", 25)):
        if name in imports:
            score += points
            evidence.append(f"imports {name}")
    return score


def cli_function_score(tree: ast.AST, evidence: list[str]) -> int:
    score = 0
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
    return score


def module_target_kind(rel: Path, evidence: list[str]) -> str:
    if any(item.startswith("imports ") for item in evidence):
        return "python-cli-framework"
    if rel.name == "__main__.py":
        return "python-module-main"
    return "python-module"


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


def adapter_target_smoke_execution(request: AdapterSmokeExecutionInput) -> dict[str, Any]:
    bounded_timeout = bounded_smoke_timeout(request.timeout_seconds)
    if not request.run:
        return planned_adapter_smoke_execution(request.cwd, request.confirmed)
    if not request.confirmed:
        return unconfirmed_adapter_smoke_execution(request.cwd)
    operation, smoke_cwd_value = run_adapter_smoke_operation(
        argv=request.argv,
        cwd=request.cwd,
        timeout_seconds=bounded_timeout,
        operation_runner=request.operation_runner,
        plugin_dir=request.plugin_dir,
        harness_name=request.harness_name,
        module=request.module,
    )
    command = operation["results"][0] if operation.get("results") else {}
    status, reason = adapter_smoke_status_reason(operation, command, bounded_timeout)
    return adapter_smoke_execution_report(
        status=status,
        reason=reason,
        operation=operation,
        command=command,
        smoke_cwd=smoke_cwd_value,
    )


def bounded_smoke_timeout(timeout_seconds: int) -> int:
    return max(1, min(int(timeout_seconds), 120))


def planned_adapter_smoke_execution(cwd: Path, confirmed: bool) -> dict[str, Any]:
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


def unconfirmed_adapter_smoke_execution(cwd: Path) -> dict[str, Any]:
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


def run_adapter_smoke_operation(
    *,
    argv: tuple[str, ...],
    cwd: Path,
    timeout_seconds: int,
    operation_runner: Any,
    plugin_dir: Path,
    harness_name: str,
    module: str,
) -> tuple[dict[str, Any], str]:
    smoke_root = cwd / "runtime" / "adapter-smoke"
    smoke_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="run-", dir=smoke_root) as smoke_cwd:
        plan = adapter_smoke_plugin_plan(
            argv=argv,
            timeout_seconds=timeout_seconds,
            plugin_dir=plugin_dir,
            harness_name=harness_name,
            module=module,
            smoke_cwd=smoke_cwd,
        )
        return operation_runner.execute(plan), smoke_cwd


def adapter_smoke_plugin_plan(
    *,
    argv: tuple[str, ...],
    timeout_seconds: int,
    plugin_dir: Path,
    harness_name: str,
    module: str,
    smoke_cwd: str,
) -> PluginPlan:
    return PluginPlan(
        plugin_id=PLUGIN_ID,
        action=f"adapter-smoke-{sanitize_harness_name(harness_name)}",
        plugin_dir=str(plugin_dir),
        commands=(
            PluginCommand(
                label=f"Adapter smoke: {harness_name} -> {module}",
                argv=argv,
                cwd=smoke_cwd,
                timeout_seconds=timeout_seconds,
                env={"CBN_ADAPTER_SMOKE": "1"},
            ),
        ),
        notes=(
            "Executable adapter smoke runs through the plugin operation boundary.",
            f"Harness: {harness_name}",
            f"Module: {module}",
        ),
    )


def adapter_smoke_status_reason(
    operation: dict[str, Any],
    command: dict[str, Any],
    timeout_seconds: int,
) -> tuple[str, str]:
    exit_code = command.get("exit_code")
    if operation.get("status") == "blocked":
        return "blocked", "; ".join(operation.get("blockers", [])) or "plugin operation blocked"
    if command.get("timed_out"):
        return "timeout", f"command timed out after {timeout_seconds} seconds"
    if exit_code == 127:
        return "spawn_failed", command.get("stderr") or "command failed to start"
    if exit_code == 0:
        return "completed", "completed"
    return "failed", "nonzero_exit"


def adapter_smoke_execution_report(
    *,
    status: str,
    reason: str,
    operation: dict[str, Any],
    command: dict[str, Any],
    smoke_cwd: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "requires_confirmation": True,
        "confirmed": True,
        "exit_code": command.get("exit_code"),
        "reason": reason,
        "cwd": smoke_cwd,
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
        return smoke_gate_result(False, True, "not_required")
    if smoke_report is None:
        return smoke_gate_result(True, False, "blocked", "smoke gate requires a ready module strategy")
    execution = smoke_report.get("execution", {})
    if execution.get("status") == "not_run":
        return smoke_gate_result(
            True,
            False,
            "not_run",
            "smoke gate has not run; use --write --yes or run adapter-smoke first",
        )
    if execution.get("status") == "requires_confirmation":
        return smoke_gate_result(True, False, "requires_confirmation", "smoke gate execution requires confirmation")
    if smoke_report.get("summary", {}).get("smoke_ok"):
        return smoke_gate_result(True, True, "passed")
    return smoke_gate_result(
        True,
        False,
        "failed",
        f"adapter target smoke failed: {execution.get('reason', 'unknown')}",
    )


def smoke_gate_result(
    required: bool,
    ok: bool,
    status: str,
    blocker: str | None = None,
) -> dict[str, Any]:
    return {
        "required": required,
        "ok": ok,
        "status": status,
        "blockers": [blocker] if blocker else [],
    }


def clip_text(value: str | None, limit: int) -> str:
    text = value or ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...<truncated>"
