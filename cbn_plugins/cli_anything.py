"""CLI-Anything / CLI-Hub integration helpers.

This module intentionally treats CLI-Anything as an external plugin. It never
vendors upstream code; it only detects `cli-hub`, calls it when available, and
generates CBN manifests for installed or planned harnesses.
"""

from __future__ import annotations

import ast
import json
import importlib.metadata as importlib_metadata
import importlib.util as importlib_util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adapters.pty import pty_backend_status
from cbn.paths import resolve_project_paths
from cbn_audit.log import AuditLog
from cbn_artifacts.store import ArtifactStore
from cbn_core.manifest import CapabilityManifest, ManifestRegistry, validate_manifest_dict
from cbn_events.bus import EventBus
from cbn_parsers.fixtures import run_parser_fixtures
from cbn_parsers.registry import ParserRegistry
from cbn_plugins.manager import (
    PluginCommand,
    PluginManager,
    PluginPlan,
    verification_report_for_plan,
)
from cbn_plugins.operations import PluginOperationRunner
from cbn_plugins.cli_anything_parts.manifest_factory import (
    build_harness_manifest,
    has_external_network_signal as _manifest_factory_has_external_network_signal,
    has_local_network_signal as _manifest_factory_has_local_network_signal,
    has_write_workspace_signal as _manifest_factory_has_write_workspace_signal,
    infer_market_policy as _manifest_factory_infer_market_policy,
    market_annotations as _manifest_factory_market_annotations,
    market_labels as _manifest_factory_market_labels,
    market_runtime_text as _manifest_factory_market_runtime_text,
    max_risk as _manifest_factory_max_risk,
    preserve_existing_parser_contract as _manifest_factory_preserve_existing_parser_contract,
    sanitize_harness_name as _manifest_factory_sanitize_harness_name,
)
from cbn_plugins.cli_anything_parts.market import (
    mark_candidate_collisions as _market_parts_mark_candidate_collisions,
    mark_capability_collisions as _market_parts_mark_capability_collisions,
    market_record_identity as _market_parts_market_record_identity,
    market_records_from_result as _market_parts_market_records_from_result,
)
from cbn_plugins.cli_anything_parts.onboarding import (
    onboarding_next_commands as _onboarding_parts_next_commands,
    onboarding_stage_results as _onboarding_parts_stage_results,
    onboarding_summary as _onboarding_parts_summary,
    probe_blocked_onboarding_report as _onboarding_parts_probe_blocked_report,
)
from cbn_plugins.cli_anything_parts.probe import (
    declared_requires as _probe_parts_declared_requires,
    dependency_probes as _probe_parts_dependency_probes,
    external_app_requirement_signals as _probe_parts_external_app_requirement_signals,
    localhost_port_available as _probe_parts_localhost_port_available,
    managed_requirement_signals as _probe_parts_managed_requirement_signals,
    platform_assessment as _probe_parts_platform_assessment,
    readiness_blocker_probes as _probe_parts_readiness_blocker_probes,
    readiness_summary as _probe_parts_readiness_summary,
    requirement_assessment as _probe_parts_requirement_assessment,
    requirement_commands as _probe_parts_requirement_commands,
    requirement_env_vars as _probe_parts_requirement_env_vars,
    requirement_localhost_ports as _probe_parts_requirement_localhost_ports,
    requires_manual_account_or_key as _probe_parts_requires_manual_account_or_key,
)
from cbn_plugins.cli_anything_parts.repair import (
    entrypoint_diagnosis as _repair_parts_entrypoint_diagnosis,
    entrypoint_package_candidates as _repair_parts_entrypoint_package_candidates,
    entrypoint_wrapper_path as _repair_parts_entrypoint_wrapper_path,
    manifest_policy_from_recheck as _repair_parts_manifest_policy_from_recheck,
    normalize_package_candidate as _repair_parts_normalize_package_candidate,
    packages_from_install_command as _repair_parts_packages_from_install_command,
    python_module_wrapper_content as _repair_parts_python_module_wrapper_content,
    repair_policy_network as _repair_parts_repair_policy_network,
    script_path_candidates as _repair_parts_script_path_candidates,
)
from cbn_plugins.cli_anything_parts.verification import (
    manifest_has_entrypoint_repair as _verification_parts_manifest_has_entrypoint_repair,
    matching_parser_fixture_paths as _verification_parts_matching_parser_fixture_paths,
    parser_contract_report as _verification_parts_parser_contract_report,
    parser_fixture_gate as _verification_parts_parser_fixture_gate,
    policy_requires_confirmation as _verification_parts_policy_requires_confirmation,
    protocol_smoke_suite_command as _verification_parts_protocol_smoke_suite_command,
    protocol_verification_summary as _verification_parts_protocol_verification_summary,
    registry_source_for_manifest as _verification_parts_registry_source_for_manifest,
    smoke_suite_stage_status as _verification_parts_smoke_suite_stage_status,
    verification_blockers as _verification_parts_verification_blockers,
    verification_stages as _verification_parts_verification_stages,
)
from cbn_protocol.acceptance_queue import cli_to_cli_acceptance_queue
from cbn_protocol.compatibility import check_all_protocols
from cbn_protocol.lifecycle_suite import protocol_lifecycle_suite
from cbn_protocol.readiness import protocol_readiness_report
from cbn_protocol.smoke_suite import protocol_smoke_suite
from cbn_workflow.catalog import list_workflows


PLUGIN_ID = "cli-anything"


@dataclass(frozen=True)
class CliHubCommandResult:
    argv: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    parsed_json: Any | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "argv": list(self.argv),
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "parsed_json": self.parsed_json,
        }


class CliAnythingHub:
    def __init__(
        self,
        root: Path | None = None,
        entrypoint: str = "cli-hub",
        operation_runner: PluginOperationRunner | None = None,
    ) -> None:
        self.paths = resolve_project_paths(root)
        self.entrypoint = entrypoint
        self.operation_runner = operation_runner or PluginOperationRunner(
            audit_log=AuditLog(self.paths.logs / "cbn-audit.jsonl"),
            event_bus=EventBus(self.paths.logs / "cbn-events.jsonl"),
            artifact_store=ArtifactStore(self.paths.artifacts),
        )

    def status(self) -> dict[str, Any]:
        executable = shutil.which(self.entrypoint)
        repo_dir = self.paths.external_plugins / PLUGIN_ID / "repo"
        version = None
        if executable:
            result = self._run(("--version",), parse_json=False)
            version = (result.stdout or result.stderr).strip() or None
        return {
            "plugin_id": PLUGIN_ID,
            "entrypoint": self.entrypoint,
            "entrypoint_path": executable,
            "entrypoint_available": executable is not None,
            "source_repo_dir": str(repo_dir),
            "source_repo_available": repo_dir.exists(),
            "version": version,
        }

    def list_market(self) -> CliHubCommandResult:
        return self._run(("list", "--json"), parse_json=True)

    def search_market(self, query: str) -> CliHubCommandResult:
        return self._run(("search", query, "--json"), parse_json=True)

    def info(self, harness_name: str) -> CliHubCommandResult:
        return self._run(("info", harness_name), parse_json=False)

    def harness_status(self, harness_name: str, from_market: bool = False) -> dict[str, Any]:
        market_record = self.market_record_for_harness(harness_name) if from_market else None
        market_name = str((market_record or {}).get("name") or harness_name)
        safe_name = sanitize_harness_name(market_name)
        capability_id = f"cli-anything.{safe_name}.launch"
        manifest_path = self.paths.manifests / f"{capability_id}.json"
        info_result = self.info(harness_name)
        info_fields = _parse_info_fields(info_result.stdout)
        entry_point = (
            info_fields.get("entry_point")
            or str((market_record or {}).get("entry_point") or "")
            or None
        )
        status_text = info_fields.get("status")
        installed = _is_installed_status(status_text)
        entrypoint_path = shutil.which(entry_point) if entry_point else None
        return {
            "plugin_id": PLUGIN_ID,
            "harness_name": harness_name,
            "market_name": market_name,
            "safe_name": safe_name,
            "capability_id": capability_id,
            "manifest_path": str(manifest_path),
            "manifest_imported": manifest_path.exists(),
            "cli_hub_available": info_result.exit_code != 127,
            "cli_hub_info": {
                "argv": list(info_result.argv),
                "exit_code": info_result.exit_code,
                "status": status_text,
                "fields": info_fields,
            },
            "market_record_available": market_record is not None,
            "market_record": market_record,
            "entry_point": entry_point,
            "entrypoint_path": entrypoint_path,
            "entrypoint_available": entrypoint_path is not None,
            "installed": installed,
            "launch_ready": bool(installed and entrypoint_path),
        }

    def market_record_for_harness(self, harness_name: str) -> dict[str, Any] | None:
        result = self.search_market(harness_name)
        if result.exit_code != 0 or not isinstance(result.parsed_json, list):
            return None
        safe_name = sanitize_harness_name(harness_name)
        candidates = [item for item in result.parsed_json if isinstance(item, dict)]
        for item in candidates:
            if _matches_sanitized_name(item.get("name"), safe_name):
                return item
        for item in candidates:
            if _matches_sanitized_name(item.get("display_name"), safe_name):
                return item
        return candidates[0] if candidates else None

    def harness_plan(
        self,
        action: str,
        harness_name: str,
        extra_args: tuple[str, ...] = (),
    ) -> PluginPlan:
        if action not in {"install", "update", "uninstall", "launch"}:
            raise ValueError(f"unsupported CLI-Anything harness action: {action}")
        safe_name = sanitize_harness_name(harness_name)
        if action == "launch":
            argv = (self.entrypoint, "launch", harness_name, *extra_args)
        else:
            argv = (self.entrypoint, action, harness_name)
        return PluginPlan(
            plugin_id=PLUGIN_ID,
            action=f"harness-{action}-{safe_name}",
            plugin_dir=str(self.paths.external_plugins / PLUGIN_ID),
            commands=(
                PluginCommand(
                    label=f"CLI-Anything harness {action}: {harness_name}",
                    argv=argv,
                ),
            ),
            notes=(
                f"Preflight install/update with: python -m cbn plugin evaluate-harness cli-anything {harness_name}",
            )
            if action in {"install", "update"}
            else (),
            verification_commands=(
                f"python -m cbn plugin harness cli-anything status {harness_name} --from-market",
                f"python -m cbn plugin verify-harness cli-anything {harness_name} --no-workflows",
                f"python -m cbn call cli-anything.{safe_name}.launch --dry-run",
            )
            if action in {"install", "update"}
            else (
                f"python -m cbn plugin harness cli-anything status {harness_name} --from-market",
            ),
        )

    def verify_harness_plan(
        self,
        action: str,
        harness_name: str,
        extra_args: tuple[str, ...] = (),
        run: bool = False,
        timeout_seconds: int = 60,
    ) -> dict[str, Any]:
        safe_name = sanitize_harness_name(harness_name)
        plan = self.harness_plan(action, harness_name, extra_args=extra_args)
        return verification_report_for_plan(
            plan,
            report_kind="CliAnythingHarnessPlanVerificationReport",
            run=run,
            timeout_seconds=timeout_seconds,
            next_commands=(
                (
                    f"python -m cbn plugin verify-harness-plan cli-anything {action} "
                    f"{harness_name}"
                ),
                (
                    f"python -m cbn plugin verify-harness-plan cli-anything {action} "
                    f"{harness_name} --run"
                ),
            ),
            extra={
                "harness_name": harness_name,
                "safe_name": safe_name,
                "capability_id": f"cli-anything.{safe_name}.launch",
            },
        )

    def harness_operation_gate(
        self,
        action: str,
        harness_name: str,
        from_market: bool = True,
    ) -> dict[str, Any]:
        if action not in {"install", "update"}:
            return {
                "ok": True,
                "plugin_id": PLUGIN_ID,
                "action": action,
                "harness_name": harness_name,
                "gated": False,
                "blockers": [],
            }
        evaluation = self.evaluate_harness(harness_name, from_market=from_market)
        if not evaluation["ok"]:
            return {
                "ok": False,
                "plugin_id": PLUGIN_ID,
                "action": action,
                "harness_name": harness_name,
                "gated": True,
                "blockers": [evaluation.get("error", "harness evaluation failed")],
                "evaluation": evaluation,
                "override_flag": "--allow-blocked",
            }
        gates = evaluation["gates"]
        blockers = list(evaluation["blockers"])
        readiness = _readiness_from_evaluation(evaluation)
        for probe in readiness["probes"]:
            if (
                probe["status"] in {"missing", "unavailable", "manual_required"}
                and probe["severity"] == "blocker"
            ):
                blockers.append(f"dependency probe failed: {probe['id']}")
        if action == "install" and not (evaluation["install_candidate"] or gates["installed"]):
            blockers.append("harness is not an install candidate")
        if action == "update" and not gates["installed"]:
            blockers.append("harness is not installed")
        ok = len(blockers) == 0
        return {
            "ok": ok,
            "plugin_id": PLUGIN_ID,
            "action": action,
            "harness_name": harness_name,
            "gated": True,
            "from_market": from_market,
            "blockers": blockers,
            "evaluation": evaluation,
            "readiness": readiness,
            "override_flag": "--allow-blocked",
        }

    def manifest_for_harness(
        self,
        harness_name: str,
        title: str | None = None,
        risk: str = "read",
        market_record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return build_harness_manifest(
            harness_name,
            entrypoint=self.entrypoint,
            title=title,
            risk=risk,
            market_record=market_record,
        )

    def write_harness_manifest(
        self,
        harness_name: str,
        title: str | None = None,
        market_record: dict[str, Any] | None = None,
    ) -> Path:
        manifest = self.manifest_for_harness(harness_name, title=title, market_record=market_record)
        path = self.paths.manifests / f"{manifest['metadata']['id']}.json"
        if path.exists():
            manifest = _manifest_factory_preserve_existing_parser_contract(
                existing=_manifest_dict_from_path(path, {}),
                generated=manifest,
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def adapt_harness(
        self,
        harness_name: str,
        title: str | None = None,
        from_market: bool = False,
        write: bool = False,
    ) -> dict[str, Any]:
        market_record = self.market_record_for_harness(harness_name) if from_market else None
        if from_market and market_record is None:
            return {
                "ok": False,
                "error": "CLI-Anything market record not found",
                "plugin_id": PLUGIN_ID,
                "harness_name": harness_name,
                "from_market": True,
            }
        manifest = self.manifest_for_harness(harness_name, title=title, market_record=market_record)
        capability_id = manifest["metadata"]["id"]
        manifest_path = self.paths.manifests / f"{capability_id}.json"
        written = None
        if write:
            written = self.write_harness_manifest(harness_name, title=title, market_record=market_record)
            manifest_path = written
            manifest = _manifest_dict_from_path(manifest_path, manifest)
        return {
            "ok": True,
            "plugin_id": PLUGIN_ID,
            "harness_name": harness_name,
            "from_market": from_market,
            "market_record_available": market_record is not None,
            "write": write,
            "written": str(written) if written else None,
            "manifest_path": str(manifest_path),
            "manifest": manifest,
            "validation": validate_manifest_dict(
                manifest,
                source_path=manifest_path,
                known_parser_refs=_known_parser_refs(),
            ),
            "status": self.harness_status(harness_name, from_market=from_market),
            "next_commands": [
                f"python -m cbn plugin harness cli-anything status {harness_name} --from-market",
                f"python -m cbn plugin harness cli-anything install {harness_name} --yes",
                f"python -m cbn call {capability_id} --dry-run",
                f"python -m cbn protocol export all --capability-id {capability_id}",
            ],
        }

    def prepare_harness(
        self,
        harness_name: str,
        title: str | None = None,
        from_market: bool = False,
    ) -> dict[str, Any]:
        adaptation = self.adapt_harness(
            harness_name,
            title=title,
            from_market=from_market,
            write=False,
        )
        if not adaptation["ok"]:
            return {
                "ok": False,
                "plugin_id": PLUGIN_ID,
                "harness_name": harness_name,
                "from_market": from_market,
                "error": adaptation["error"],
                "adaptation": adaptation,
            }
        status = adaptation["status"]
        validation = adaptation["validation"]
        install_plan = self.harness_plan("install", harness_name).as_dict()
        update_plan = self.harness_plan("update", harness_name).as_dict()
        launch_plan = self.harness_plan("launch", harness_name).as_dict()
        gates = {
            "cli_hub_available": bool(status["cli_hub_available"]),
            "market_record_available": bool(adaptation["market_record_available"]),
            "market_required_satisfied": (not from_market) or bool(adaptation["market_record_available"]),
            "manifest_valid": bool(validation["valid"]),
            "manifest_imported": bool(status["manifest_imported"]),
            "installed": bool(status["installed"]),
            "entrypoint_available": bool(status["entrypoint_available"]),
            "launch_ready": bool(status["launch_ready"] and validation["valid"]),
        }
        return {
            "ok": gates["market_required_satisfied"] and gates["manifest_valid"],
            "plugin_id": PLUGIN_ID,
            "harness_name": harness_name,
            "from_market": from_market,
            "capability_id": adaptation["manifest"]["metadata"]["id"],
            "gates": gates,
            "status": status,
            "validation": validation,
            "adaptation": adaptation,
            "plans": {
                "install": install_plan,
                "update": update_plan,
                "launch": launch_plan,
            },
            "next_commands": [
                f"python -m cbn plugin harness cli-anything install {harness_name} --yes",
                f"python -m cbn plugin adapt-harness cli-anything {harness_name} --from-market --write",
                "python -m cbn registry validate manifests",
                f"python -m cbn call {adaptation['manifest']['metadata']['id']} --dry-run",
            ],
        }

    def evaluate_harness(
        self,
        harness_name: str,
        title: str | None = None,
        from_market: bool = True,
    ) -> dict[str, Any]:
        adaptation = self.adapt_harness(
            harness_name,
            title=title,
            from_market=from_market,
            write=False,
        )
        if not adaptation["ok"]:
            return {
                "ok": False,
                "plugin_id": PLUGIN_ID,
                "harness_name": harness_name,
                "from_market": from_market,
                "error": adaptation["error"],
                "adaptation": adaptation,
            }
        status = adaptation["status"]
        manifest = adaptation["manifest"]
        validation = adaptation["validation"]
        if status.get("manifest_imported"):
            manifest = _manifest_dict_from_path(Path(adaptation["manifest_path"]), manifest)
            validation = validate_manifest_dict(
                manifest,
                source_path=Path(adaptation["manifest_path"]),
                known_parser_refs=_known_parser_refs(),
            )
            adaptation = {
                **adaptation,
                "manifest": manifest,
                "validation": validation,
            }
        market_record = status.get("market_record") if isinstance(status.get("market_record"), dict) else None
        requires = _declared_requires(market_record, status)
        requirements = _requirement_assessment(requires)
        platform = _platform_assessment(market_record, requires)
        policy = manifest["spec"]["policy"]
        transport = _transport_assessment(manifest)
        low_policy_risk = policy["risk"] in {"read", "write-workspace"} and not policy["requiresConfirmation"]
        gates = {
            "cli_hub_available": bool(status["cli_hub_available"]),
            "market_record_available": bool(adaptation["market_record_available"]),
            "market_required_satisfied": (not from_market) or bool(adaptation["market_record_available"]),
            "manifest_valid": bool(validation["valid"]),
            "manifest_imported": bool(status["manifest_imported"]),
            "installed": bool(status["installed"]),
            "entrypoint_available": bool(status["entrypoint_available"]),
            "runtime_transport_ready": bool(transport["ready"]),
            "launch_ready": bool(status["launch_ready"] and validation["valid"] and transport["ready"]),
            "low_policy_risk": low_policy_risk,
            "external_dependency_free": requirements["external_dependency_free"],
            "platform_compatible": platform["compatible"],
        }
        blockers = []
        if not gates["cli_hub_available"]:
            blockers.append("cli-hub is not available")
        if not gates["market_required_satisfied"]:
            blockers.append("required market record is unavailable")
        if not gates["manifest_valid"]:
            blockers.append("generated manifest is invalid")
        if not gates["low_policy_risk"]:
            blockers.append("policy requires elevated confirmation")
        if not gates["external_dependency_free"]:
            blockers.append("declared requirements need external app, account, token, or service")
        if not gates["platform_compatible"]:
            blockers.append("declared platform does not match this host")
        if gates["installed"] and not gates["entrypoint_available"]:
            blockers.append("installed harness entrypoint is missing from PATH")
        install_candidate = (
            gates["cli_hub_available"]
            and gates["market_required_satisfied"]
            and gates["manifest_valid"]
            and gates["low_policy_risk"]
            and gates["external_dependency_free"]
            and gates["platform_compatible"]
            and not (gates["installed"] and not gates["entrypoint_available"])
        )
        if gates["launch_ready"]:
            recommended_next_action = "call_capability"
        elif gates["installed"] and not gates["entrypoint_available"]:
            recommended_next_action = "resolve_blockers"
        elif gates["installed"] and not gates["manifest_imported"]:
            recommended_next_action = "write_manifest"
        elif gates["installed"] and gates["manifest_imported"] and not gates["runtime_transport_ready"]:
            recommended_next_action = "install_runtime_transport"
        elif install_candidate and gates["manifest_imported"]:
            recommended_next_action = "install_harness"
        elif install_candidate:
            recommended_next_action = "write_manifest"
        else:
            recommended_next_action = "resolve_blockers"
        capability_id = manifest["metadata"]["id"]
        lifecycle = _lifecycle_report(
            harness_name=harness_name,
            capability_id=capability_id,
            recommended_next_action=recommended_next_action,
            gates=gates,
            blockers=blockers,
            install_candidate=install_candidate,
        )
        return {
            "ok": True,
            "plugin_id": PLUGIN_ID,
            "harness_name": harness_name,
            "from_market": from_market,
            "capability_id": capability_id,
            "install_candidate": install_candidate,
            "recommended_next_action": recommended_next_action,
            "blockers": blockers,
            "gates": gates,
            "requirements": requirements,
            "platform": platform,
            "transport": transport,
            "policy": policy,
            "lifecycle": lifecycle,
            "status": status,
            "validation": validation,
            "adaptation": adaptation,
            "plans": {
                "install": self.harness_plan("install", harness_name).as_dict(),
                "launch": self.harness_plan("launch", harness_name).as_dict(),
            },
            "next_commands": [
                f"python -m cbn plugin adapt-harness cli-anything {harness_name} --from-market --write",
                f"python -m cbn plugin harness cli-anything install {harness_name} --yes",
                "python -m cbn registry validate manifests",
                f"python -m cbn call {capability_id} --dry-run",
            ],
        }

    def probe_harness(
        self,
        harness_name: str,
        title: str | None = None,
        from_market: bool = True,
    ) -> dict[str, Any]:
        evaluation = self.evaluate_harness(
            harness_name,
            title=title,
            from_market=from_market,
        )
        if not evaluation["ok"]:
            return {
                "ok": False,
                "plugin_id": PLUGIN_ID,
                "harness_name": harness_name,
                "from_market": from_market,
                "error": evaluation["error"],
                "evaluation": evaluation,
                "probes": [],
            }
        status = evaluation["status"]
        market_record = status.get("market_record") if isinstance(status.get("market_record"), dict) else None
        requires = _declared_requires(market_record, status)
        readiness = _readiness_summary(
            probes=_dependency_probes(
                requires=requires,
                entry_point=status.get("entry_point"),
            ),
            install_candidate=evaluation["install_candidate"],
        )
        return {
            "ok": True,
            "plugin_id": PLUGIN_ID,
            "harness_name": harness_name,
            "from_market": from_market,
            "capability_id": evaluation["capability_id"],
            "ready": readiness["ready"],
            "probe_blocker_count": readiness["probe_blocker_count"],
            "probes": readiness["probes"],
            "evaluation": evaluation,
            "next_commands": [
                f"python -m cbn plugin probe-harness cli-anything {harness_name}",
                f"python -m cbn plugin evaluate-harness cli-anything {harness_name}",
                f"python -m cbn plugin adapt-harness cli-anything {harness_name} --from-market --write",
                f"python -m cbn plugin harness cli-anything install {harness_name} --yes",
            ],
        }

    def verify_harness(
        self,
        harness_name: str,
        title: str | None = None,
        from_market: bool = True,
        include_workflows: bool = True,
        run_smoke_suite: bool = False,
        smoke_extra_args: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        probe = self.probe_harness(
            harness_name,
            title=title,
            from_market=from_market,
        )
        if not probe["ok"]:
            return {
                "ok": False,
                "plugin_id": PLUGIN_ID,
                "harness_name": harness_name,
                "from_market": from_market,
                "include_workflows": include_workflows,
                "run_smoke_suite": run_smoke_suite,
                "error": probe["error"],
                "probe": probe,
            }

        evaluation = probe["evaluation"]
        adaptation = evaluation["adaptation"]
        manifest = adaptation["manifest"]
        capability_id = evaluation["capability_id"]
        registry = ManifestRegistry()
        registry.load_dir(self.paths.manifests)
        registry.load_dir(self.paths.local_manifests, replace=True)
        imported_manifest = registry.get(capability_id)
        effective_manifest = _effective_manifest_dict(imported_manifest, manifest)
        protocol_registry = registry if imported_manifest else ManifestRegistry()
        if imported_manifest is None:
            protocol_registry.register(
                CapabilityManifest.from_dict(
                    manifest,
                    source_path=Path(adaptation["manifest_path"]),
                )
            )
        protocol_checks = check_all_protocols(
            protocol_registry,
            capability_id=capability_id,
        )["checks"]
        readiness = {
            "ready": probe["ready"],
            "probe_blocker_count": probe["probe_blocker_count"],
            "probes": probe["probes"],
        }
        registry_status = {
            "manifest_imported": imported_manifest is not None,
            "manifest_path": str(imported_manifest.source_path) if imported_manifest else adaptation["manifest_path"],
            "protocol_check_source": _registry_source_for_manifest(
                imported_manifest,
                local_manifest_dir=self.paths.local_manifests,
            )
            if imported_manifest
            else "generated_preview",
            "entrypoint_repair_active": _manifest_has_entrypoint_repair(effective_manifest),
        }
        parser_contract = _parser_contract_report(effective_manifest)
        verification_blockers = _verification_blockers(evaluation, readiness, registry_status)
        workflow_matches = (
            _workflow_matches_for_capability(registry, capability_id)
            if include_workflows
            else []
        )
        smoke_suite = _harness_protocol_smoke_suite(
            registry=registry,
            capability_id=capability_id,
            include_workflows=include_workflows,
            extra_args=smoke_extra_args,
            run=run_smoke_suite,
        )
        if smoke_suite.get("run") and not smoke_suite.get("ok"):
            verification_blockers = sorted(
                set([*verification_blockers, "protocol smoke suite failed"])
            )
        return {
            "ok": True,
            "plugin_id": PLUGIN_ID,
            "harness_name": harness_name,
            "from_market": from_market,
            "include_workflows": include_workflows,
            "run_smoke_suite": run_smoke_suite,
            "capability_id": capability_id,
            "ready_for_manifest_write": bool(evaluation["gates"]["manifest_valid"] and not evaluation["blockers"]),
            "ready_for_runtime_verification": len(verification_blockers) == 0,
            "verification_blockers": verification_blockers,
            "readiness": readiness,
            "registry": registry_status,
            "parser_contract": parser_contract,
            "protocols": _protocol_verification_summary(protocol_checks),
            "protocol_smoke_suite": smoke_suite,
            "workflow_matches": workflow_matches,
            "verification_stages": _verification_stages(
                harness_name=harness_name,
                capability_id=capability_id,
                evaluation=evaluation,
                readiness=readiness,
                registry_status=registry_status,
                parser_contract=parser_contract,
                protocol_checks=protocol_checks,
                smoke_suite=smoke_suite,
            ),
            "probe": probe,
            "evaluation": evaluation,
            "next_commands": [
                f"python -m cbn plugin evaluate-harness cli-anything {harness_name}",
                f"python -m cbn plugin probe-harness cli-anything {harness_name}",
                f"python -m cbn plugin adapt-harness cli-anything {harness_name} --from-market --write",
                "python -m cbn registry validate manifests",
                f"python -m cbn plugin harness cli-anything install {harness_name} --yes",
                f"python -m cbn call {capability_id} --dry-run",
                f"python -m cbn protocol check all --capability-id {capability_id}",
                smoke_suite["command"],
                f"python -m cbn mcp smoke --capability-id {capability_id}",
                f"python -m cbn a2a smoke --capability-id {capability_id}",
                f"python -m cbn acp smoke --capability-id {capability_id}",
            ],
        }

    def promotion_gate(
        self,
        harness_name: str,
        title: str | None = None,
        from_market: bool = True,
        include_workflows: bool = True,
        run_smoke_suite: bool = False,
        smoke_extra_args: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        verification = self.verify_harness(
            harness_name,
            title=title,
            from_market=from_market,
            include_workflows=include_workflows,
            run_smoke_suite=run_smoke_suite,
            smoke_extra_args=smoke_extra_args,
        )
        if not verification.get("ok"):
            return {
                "ok": False,
                "plugin_id": PLUGIN_ID,
                "kind": "CliAnythingOverlayPromotionGate",
                "harness_name": harness_name,
                "from_market": from_market,
                "include_workflows": include_workflows,
                "run_smoke_suite": run_smoke_suite,
                "error": verification.get("error", "harness verification failed"),
                "verification": verification,
            }

        capability_id = str(verification["capability_id"])
        registry = ManifestRegistry()
        registry.load_dir(self.paths.manifests)
        registry.load_dir(self.paths.local_manifests, replace=True)
        imported_manifest = registry.get(capability_id)
        effective_manifest = _effective_manifest_dict(
            imported_manifest,
            verification.get("evaluation", {}).get("adaptation", {}).get("manifest", {}),
        )
        parser_contract = _parser_contract_report(effective_manifest)
        parser_fixture_report = run_parser_fixtures(
            parser_ref=parser_contract["parser_ref"],
            registry=ParserRegistry.builtins(),
        )
        parser_fixture_gate = _parser_fixture_gate(parser_fixture_report, capability_id)
        readiness = protocol_readiness_report(registry, include_workflows=include_workflows)
        registry_status = verification.get("registry") if isinstance(verification.get("registry"), dict) else {}
        smoke_suite = verification.get("protocol_smoke_suite") if isinstance(verification.get("protocol_smoke_suite"), dict) else {}
        source = registry_status.get("protocol_check_source")
        entrypoint_repair_active = bool(registry_status.get("entrypoint_repair_active"))
        blockers = _promotion_blockers(
            verification=verification,
            source=source,
            entrypoint_repair_active=entrypoint_repair_active,
            parser_contract=parser_contract,
            parser_fixture_gate=parser_fixture_gate,
            smoke_suite=smoke_suite,
            run_smoke_suite=run_smoke_suite,
            readiness=readiness,
        )
        if source == "current_registry":
            status = "already_portable"
        elif blockers:
            status = "blocked"
        else:
            status = "ready_for_promotion"
        return {
            "ok": True,
            "plugin_id": PLUGIN_ID,
            "kind": "CliAnythingOverlayPromotionGate",
            "harness_name": harness_name,
            "from_market": from_market,
            "include_workflows": include_workflows,
            "run_smoke_suite": run_smoke_suite,
            "capability_id": capability_id,
            "status": status,
            "ready_for_promotion": status == "ready_for_promotion",
            "promotion_blockers": blockers,
            "source": {
                "kind": source,
                "manifest_path": registry_status.get("manifest_path"),
                "entrypoint_repair_active": entrypoint_repair_active,
                "portable_manifest_path": str(self.paths.manifests / f"{capability_id}.json"),
                "runtime_overlay_path": str(self.paths.local_manifests / f"{capability_id}.json"),
            },
            "requirements": _promotion_requirements(
                source=source,
                entrypoint_repair_active=entrypoint_repair_active,
                parser_contract=parser_contract,
                parser_fixture_gate=parser_fixture_gate,
                smoke_suite=smoke_suite,
                run_smoke_suite=run_smoke_suite,
                readiness=readiness,
                verification=verification,
            ),
            "parser_contract": parser_contract,
            "parser_fixtures": parser_fixture_gate,
            "protocol_smoke_suite": smoke_suite,
            "protocol_readiness": {
                "ok": readiness.get("ok"),
                "summary": readiness.get("summary"),
                "readiness": readiness.get("readiness"),
                "manifest_sources": readiness.get("manifest_sources"),
                "protocol_gaps": readiness.get("protocol_gaps"),
            },
            "verification": verification,
            "next_commands": [
                f"python -m cbn plugin verify-harness cli-anything {harness_name} --from-market",
                f"python -m cbn parser fixtures --parser-ref {parser_contract['parser_ref']}",
                (
                    f"python -m cbn plugin promotion-gate cli-anything {harness_name} "
                    f"--from-market --smoke-suite --smoke-extra-arg=--help"
                ),
                "python -m cbn registry validate runtime/manifests",
                "python -m cbn registry validate manifests",
                f"python -m cbn protocol smoke-suite --capability-id {capability_id} --extra-arg=--help",
            ],
        }

    def onboard_harness(
        self,
        harness_name: str,
        title: str | None = None,
        from_market: bool = True,
        write: bool = False,
        confirmed: bool = False,
        install: bool = False,
        allow_blocked: bool = False,
        include_workflows: bool = True,
        run_smoke_suite: bool = False,
        smoke_extra_args: tuple[str, ...] = (),
        operation_runner: Any | None = None,
    ) -> dict[str, Any]:
        probe = self.probe_harness(
            harness_name,
            title=title,
            from_market=from_market,
        )
        if not probe["ok"]:
            return _onboarding_parts_probe_blocked_report(
                plugin_id=PLUGIN_ID,
                harness_name=harness_name,
                from_market=from_market,
                write=write,
                confirmed=confirmed,
                install=install,
                allow_blocked=allow_blocked,
                include_workflows=include_workflows,
                run_smoke_suite=run_smoke_suite,
                probe=probe,
            )

        evaluation = probe["evaluation"]
        capability_id = evaluation["capability_id"]
        adaptation = evaluation["adaptation"]
        write_requested_without_confirmation = bool(write and not confirmed)
        write_blocked_by_gate = bool(
            write
            and confirmed
            and not allow_blocked
            and not (
                evaluation["gates"]["manifest_valid"]
                and not evaluation["blockers"]
            )
        )
        install_requested_without_confirmation = bool(install and not confirmed)
        if write and confirmed and not write_blocked_by_gate:
            adaptation = self.adapt_harness(
                harness_name,
                title=title,
                from_market=from_market,
                write=True,
            )
        install_plan_obj = self.harness_plan("install", harness_name)
        install_plan = install_plan_obj.as_dict()
        install_gate = self.harness_operation_gate(
            "install",
            harness_name,
            from_market=from_market,
        )
        install_result = None
        install_execution_status = "not_requested"
        install_execution_blockers: list[str] = []
        if install and not confirmed:
            install_execution_status = "requires_confirmation"
        elif install and confirmed and not allow_blocked and not install_gate.get("ok"):
            install_execution_status = "blocked"
            install_execution_blockers = list(install_gate.get("blockers", []))
        elif install and confirmed and operation_runner is None:
            install_execution_status = "blocked"
            install_execution_blockers = ["operation runner is required for confirmed install"]
        elif install and confirmed:
            install_result = operation_runner.execute(install_plan_obj)
            install_execution_status = str(install_result.get("status", "unknown"))
            if install_execution_status != "completed":
                install_execution_blockers = list(install_result.get("blockers", [])) or [
                    f"harness install operation {install_execution_status}"
                ]
        verification = self.verify_harness(
            harness_name,
            title=title,
            from_market=from_market,
            include_workflows=include_workflows,
            run_smoke_suite=run_smoke_suite,
            smoke_extra_args=smoke_extra_args,
        )
        verification_blockers = (
            verification.get("verification_blockers", [])
            if verification.get("ok")
            else [verification.get("error", "verification failed")]
        )
        manifest_written = bool(adaptation.get("written"))
        ready_for_manifest_write = bool(
            verification.get("ready_for_manifest_write")
            if verification.get("ok")
            else evaluation["gates"]["manifest_valid"] and not evaluation["blockers"]
        )
        ready_for_install = bool(install_gate.get("ok"))
        ready_for_runtime_verification = bool(
            verification.get("ready_for_runtime_verification")
            if verification.get("ok")
            else False
        )
        effective_evaluation = verification.get("evaluation", evaluation) if verification.get("ok") else evaluation
        manifest_already_imported = bool(effective_evaluation["gates"].get("manifest_imported"))
        harness_already_installed = bool(effective_evaluation["gates"].get("installed"))
        smoke_suite = verification.get("protocol_smoke_suite", {}) if verification.get("ok") else {}
        stage_results = _onboarding_parts_stage_results(
            evaluation=evaluation,
            probe=probe,
            adaptation=adaptation,
            install_gate=install_gate,
            verification_blockers=verification_blockers,
            ready_for_manifest_write=ready_for_manifest_write,
            ready_for_install=ready_for_install,
            ready_for_runtime_verification=ready_for_runtime_verification,
            manifest_written=manifest_written,
            manifest_already_imported=manifest_already_imported,
            harness_already_installed=harness_already_installed,
            write=write,
            confirmed=confirmed,
            install=install,
            allow_blocked=allow_blocked,
            write_blocked_by_gate=write_blocked_by_gate,
            install_execution_status=install_execution_status,
            install_execution_blockers=install_execution_blockers,
            smoke_suite=smoke_suite,
        )
        next_commands = _onboarding_parts_next_commands(harness_name, capability_id)
        return {
            "ok": True,
            "plugin_id": PLUGIN_ID,
            "kind": "CliAnythingHarnessOnboarding",
            "harness_name": harness_name,
            "from_market": from_market,
            "write": write,
            "confirmed": confirmed,
            "install": install,
            "allow_blocked": allow_blocked,
            "include_workflows": include_workflows,
            "run_smoke_suite": run_smoke_suite,
            "capability_id": capability_id,
            "summary": _onboarding_parts_summary(
                ready_for_manifest_write=ready_for_manifest_write,
                manifest_written=manifest_written,
                write_blocked_by_gate=write_blocked_by_gate,
                write_requested_without_confirmation=write_requested_without_confirmation,
                ready_for_install=ready_for_install,
                install_requested_without_confirmation=install_requested_without_confirmation,
                install_execution_status=install_execution_status,
                ready_for_runtime_verification=ready_for_runtime_verification,
                smoke_suite=smoke_suite,
                recommended_next_action=evaluation["recommended_next_action"],
            ),
            "stage_results": stage_results,
            "reports": {
                "evaluation": evaluation,
                "probe": probe,
                "adaptation": adaptation,
                "install_plan": install_plan,
                "install_gate": install_gate,
                "install_result": install_result,
                "verification": verification,
            },
            "next_commands": next_commands,
        }

    def candidate_harnesses(
        self,
        query: str | None = None,
        limit: int = 50,
        with_probes: bool = False,
        compact: bool = False,
    ) -> dict[str, Any]:
        result = self.search_market(query) if query else self.list_market()
        records = _market_records_from_result(result.parsed_json)
        if result.exit_code != 0:
            return {
                "ok": False,
                "plugin_id": PLUGIN_ID,
                "query": query,
                "limit": max(0, min(limit, 500)),
                "with_probes": with_probes,
                "compact": compact,
                "error": "CLI-Anything market command failed",
                "market": _market_command_payload(result, compact=compact),
                "selected_count": 0,
                "install_candidate_count": 0,
                "blocked_count": 0,
                "candidates": [],
                "candidate_summary": [],
            }
        if records is None:
            return {
                "ok": False,
                "plugin_id": PLUGIN_ID,
                "query": query,
                "limit": max(0, min(limit, 500)),
                "with_probes": with_probes,
                "compact": compact,
                "error": "CLI-Anything market command did not return a supported JSON list shape",
                "market": _market_command_payload(result, compact=compact),
                "selected_count": 0,
                "install_candidate_count": 0,
                "blocked_count": 0,
                "candidates": [],
                "candidate_summary": [],
            }
        bounded_limit = max(0, min(limit, 500))
        candidates = [
            self._candidate_from_market_record(record, market_index=index)
            for index, record in enumerate(records)
        ]
        _mark_candidate_collisions(candidates)
        for item in candidates:
            _refresh_candidate_lifecycle(item)
            if with_probes:
                _attach_candidate_readiness(item)
        candidates.sort(
            key=lambda item: (
                not bool(item.get("install_candidate")),
                len(item.get("blockers", [])),
                item.get("harness_name") or "",
                item.get("market_index", 0),
            )
        )
        selected = candidates[:bounded_limit]
        for rank, item in enumerate(selected, start=1):
            item["rank"] = rank
        install_candidate_count = sum(1 for item in selected if item.get("install_candidate"))
        blocked_count = sum(1 for item in selected if not item.get("install_candidate"))
        probe_ready_count = sum(
            1
            for item in selected
            if isinstance(item.get("readiness"), dict) and item["readiness"].get("ready")
        )
        probe_blocked_count = sum(
            1
            for item in selected
            if isinstance(item.get("readiness"), dict) and item["readiness"].get("probe_blocker_count", 0) > 0
        )
        return {
            "ok": True,
            "plugin_id": PLUGIN_ID,
            "query": query,
            "limit": bounded_limit,
            "with_probes": with_probes,
            "compact": compact,
            "market_count": len(records),
            "evaluated_count": len(candidates),
            "selected_count": len(selected),
            "install_candidate_count": install_candidate_count,
            "blocked_count": blocked_count,
            "probe_ready_count": probe_ready_count if with_probes else None,
            "probe_blocked_count": probe_blocked_count if with_probes else None,
            "market": _market_command_payload(result, compact=compact),
            "candidates": selected,
            "candidate_summary": _candidate_summary(selected),
            "next_commands": [
                "python -m cbn plugin candidates cli-anything --query <query> --limit 20 --compact",
                "python -m cbn plugin candidates cli-anything --query <query> --limit 20 --with-probes --compact",
                "python -m cbn plugin evaluate-harness cli-anything <harness>",
                "python -m cbn plugin adapt-harness cli-anything <harness> --from-market --write",
                "python -m cbn plugin harness cli-anything install <harness> --yes",
            ],
        }

    def market_install_queue(
        self,
        query: str | None = None,
        limit: int = 50,
        max_installs: int = 10,
        include_blocked: bool = True,
    ) -> dict[str, Any]:
        candidate_scan = self.candidate_harnesses(
            query=query,
            limit=limit,
            with_probes=True,
            compact=True,
        )
        bounded_max_installs = max(0, min(max_installs, 100))
        if not candidate_scan.get("ok"):
            return {
                "ok": False,
                "plugin_id": PLUGIN_ID,
                "kind": "CliAnythingMarketInstallQueue",
                "query": query,
                "limit": max(0, min(limit, 500)),
                "max_installs": bounded_max_installs,
                "include_blocked": include_blocked,
                "error": candidate_scan.get("error", "CLI-Anything candidate scan failed"),
                "summary": {
                    "candidate_count": 0,
                    "queued_count": 0,
                    "blocked_count": 0,
                    "skipped_count": 0,
                },
                "queue": [],
                "blocked": [],
                "skipped": [],
                "candidate_scan": candidate_scan,
            }

        queue = []
        blocked = []
        skipped = []
        candidates = candidate_scan.get("candidates", [])
        if not isinstance(candidates, list):
            candidates = []

        for item in candidates:
            if not isinstance(item, dict):
                continue
            harness_name = item.get("harness_name")
            if not isinstance(harness_name, str) or not harness_name:
                blocked.append(_install_queue_blocked_entry(item, "market record is missing harness_name"))
                continue
            gates = item.get("gates") if isinstance(item.get("gates"), dict) else {}
            if bool(item.get("install_candidate")) and not bool(gates.get("launch_ready")):
                evaluation = self.evaluate_harness(harness_name, from_market=True)
                if not evaluation.get("ok"):
                    blocked.append(
                        _install_queue_blocked_entry(
                            item,
                            "harness evaluation failed before queueing",
                            evaluation=evaluation,
                        )
                    )
                    continue
                eval_gates = evaluation.get("gates") if isinstance(evaluation.get("gates"), dict) else {}
                if bool(eval_gates.get("launch_ready")):
                    skipped.append(
                        _install_queue_skipped_entry(
                            item,
                            "harness is already launch-ready",
                            evaluation=evaluation,
                        )
                    )
                    continue
                if not bool(evaluation.get("install_candidate")):
                    blocked.append(
                        _install_queue_blocked_entry(
                            item,
                            "harness evaluation blockers must be resolved first",
                            evaluation=evaluation,
                        )
                    )
                    continue
                if len(queue) >= bounded_max_installs:
                    skipped.append(
                        _install_queue_skipped_entry(
                            item,
                            "max_installs limit reached",
                            evaluation=evaluation,
                        )
                    )
                    continue
                queue.append(
                    _install_queue_entry(
                        item,
                        install_plan=self.harness_plan("install", harness_name).as_dict(),
                        evaluation=evaluation,
                    )
                )
            elif bool(item.get("install_candidate")) and bool(gates.get("launch_ready")):
                skipped.append(_install_queue_skipped_entry(item, "harness is already launch-ready"))
            elif include_blocked:
                blocked.append(_install_queue_blocked_entry(item, "candidate blockers must be resolved first"))

        return {
            "ok": True,
            "plugin_id": PLUGIN_ID,
            "kind": "CliAnythingMarketInstallQueue",
            "query": query,
            "limit": candidate_scan.get("limit"),
            "max_installs": bounded_max_installs,
            "include_blocked": include_blocked,
            "summary": {
                "candidate_count": len(candidates),
                "install_candidate_count": candidate_scan.get("install_candidate_count"),
                "probe_ready_count": candidate_scan.get("probe_ready_count"),
                "probe_blocked_count": candidate_scan.get("probe_blocked_count"),
                "queued_count": len(queue),
                "blocked_count": len(blocked),
                "skipped_count": len(skipped),
            },
            "queue": queue,
            "blocked": blocked,
            "skipped": skipped,
            "candidate_summary": candidate_scan.get("candidate_summary", []),
            "candidate_scan": candidate_scan,
            "next_commands": [
                "python -m cbn plugin install-queue cli-anything --query <query> --limit 20",
                "python -m cbn plugin onboard-harness cli-anything <harness> --from-market --write --install --yes --smoke-suite --smoke-extra-arg=--help --no-workflows",
                "python -m cbn plugin harness cli-anything install <harness> --yes",
            ],
        }

    def blocked_harness_plan(
        self,
        harnesses: tuple[str, ...] = (),
        query: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        bounded_limit = max(0, min(limit, 500))
        source = "explicit_harnesses" if harnesses else "market_install_queue"
        source_report: dict[str, Any] | None = None
        blocked_entries: list[dict[str, Any]] = []

        if harnesses:
            for harness_name in harnesses:
                evaluation = self.evaluate_harness(harness_name, from_market=True)
                blocked_entries.append(_blocked_entry_from_evaluation(harness_name, evaluation))
        else:
            source_report = self.market_install_queue(
                query=query,
                limit=bounded_limit,
                max_installs=100,
                include_blocked=True,
            )
            if not source_report.get("ok"):
                return {
                    "ok": False,
                    "plugin_id": PLUGIN_ID,
                    "kind": "CliAnythingBlockedHarnessPlan",
                    "source": source,
                    "query": query,
                    "limit": bounded_limit,
                    "error": source_report.get("error", "CLI-Anything install queue failed"),
                    "summary": {
                        "blocked_count": 0,
                        "override_candidate_count": 0,
                        "manual_resolution_count": 0,
                        "unresolved_count": 0,
                    },
                    "blocked": [],
                    "source_report": source_report,
                }
            blocked_raw = source_report.get("blocked", [])
            if isinstance(blocked_raw, list):
                blocked_entries = [item for item in blocked_raw if isinstance(item, dict)]

        decisions = [_blocked_harness_decision(item) for item in blocked_entries]
        category_counts: dict[str, int] = {}
        for decision in decisions:
            for category in decision.get("categories", []):
                category_counts[category] = category_counts.get(category, 0) + 1
        override_candidate_count = sum(1 for item in decisions if item.get("override", {}).get("available"))
        manual_resolution_count = sum(1 for item in decisions if item.get("manual_resolution_required"))
        unresolved_count = sum(1 for item in decisions if not item.get("decision_ready"))
        return {
            "ok": True,
            "plugin_id": PLUGIN_ID,
            "kind": "CliAnythingBlockedHarnessPlan",
            "source": source,
            "query": query,
            "limit": bounded_limit,
            "harnesses": list(harnesses),
            "summary": {
                "blocked_count": len(decisions),
                "override_candidate_count": override_candidate_count,
                "manual_resolution_count": manual_resolution_count,
                "unresolved_count": unresolved_count,
                "category_counts": category_counts,
            },
            "blocked": decisions,
            "source_report": source_report,
            "next_commands": [
                "python -m cbn plugin blocked-plan cli-anything --harness <harness>",
                "python -m cbn plugin evaluate-harness cli-anything <harness> --from-market",
                "python -m cbn plugin probe-harness cli-anything <harness> --from-market",
                "python -m cbn plugin onboard-harness cli-anything <harness> --from-market --write --install --yes --allow-blocked --smoke-suite --smoke-extra-arg=--help --no-workflows",
            ],
        }

    def entrypoint_repair_plan(
        self,
        harness_name: str,
        from_market: bool = True,
    ) -> dict[str, Any]:
        evaluation = self.evaluate_harness(harness_name, from_market=from_market)
        status = evaluation.get("status") if isinstance(evaluation.get("status"), dict) else {}
        market_record = status.get("market_record") if isinstance(status.get("market_record"), dict) else None
        entry_point = status.get("entry_point")
        if not isinstance(entry_point, str) or not entry_point:
            entry_point = None
        entrypoint_path = shutil.which(entry_point) if entry_point else None
        package_candidates = _entrypoint_package_candidates(harness_name, market_record, status)
        script_candidates = _script_path_candidates(entry_point)
        distribution_reports = [_distribution_report(package) for package in package_candidates]
        module_reports = [_module_report(package) for package in package_candidates]
        diagnosis = _entrypoint_diagnosis(
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
        self,
        harness_name: str,
        from_market: bool = True,
        module: str | None = None,
        write: bool = False,
        confirmed: bool = False,
        require_smoke: bool = False,
        smoke_args: tuple[str, ...] = ("--help",),
        smoke_timeout_seconds: int = 10,
    ) -> dict[str, Any]:
        plan = self.entrypoint_repair_plan(harness_name, from_market=from_market)
        strategy = _entrypoint_repair_strategy(plan, module=module)
        execution: dict[str, Any] = {
            "requested": write,
            "confirmed": confirmed,
            "status": "not_requested",
            "blockers": [],
            "written": [],
        }
        wrapper_path = _entrypoint_wrapper_path(self.paths.external_plugins, harness_name)
        smoke_report = None
        if require_smoke and strategy.get("ready") and strategy.get("module"):
            smoke_report = self.adapter_target_smoke(
                harness_name,
                module=strategy["module"],
                from_market=from_market,
                smoke_args=smoke_args,
                timeout_seconds=smoke_timeout_seconds,
                run=write,
                confirmed=confirmed,
            )
        smoke_gate = _repair_entrypoint_smoke_gate(require_smoke, smoke_report)
        manifest = _entrypoint_repair_manifest(plan, strategy, wrapper_path)
        repair_manifest_path = self.paths.local_manifests / f"{plan['capability_id']}.json"
        if smoke_report and smoke_report.get("summary", {}).get("smoke_ok"):
            annotations = manifest.setdefault("metadata", {}).setdefault("annotations", {})
            annotations["cbn.repair.smoke.module"] = str(smoke_report["module"])
            annotations["cbn.repair.smoke.args"] = json.dumps(smoke_report["smoke_args"], ensure_ascii=False)
            annotations["cbn.repair.smoke.exit_code"] = str(smoke_report["execution"].get("exit_code"))
        parser_fixture_gate = _mark_repaired_manifest_verified_from_fixtures(
            manifest=manifest,
            capability_id=str(plan["capability_id"]),
            fixture_dir=self.paths.root / "parser_fixtures",
            root=self.paths.root,
            smoke_ok=bool(smoke_report and smoke_report.get("summary", {}).get("smoke_ok")),
        )
        validation = validate_manifest_dict(
            manifest,
            source_path=repair_manifest_path,
            known_parser_refs=_known_parser_refs(),
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
            repair_operation = self.operation_runner.execute_write(
                PluginPlan(
                    plugin_id=PLUGIN_ID,
                    action=f"repair-entrypoint-{sanitize_harness_name(harness_name)}",
                    plugin_dir=str(self.paths.external_plugins / PLUGIN_ID),
                    commands=(),
                    notes=(
                        "Writes a CBN-owned CLI-Anything entrypoint wrapper and local manifest overlay.",
                        f"Harness: {harness_name}",
                        f"Module: {strategy['module']}",
                    ),
                ),
                lambda operation_id: _write_repair_entrypoint_files(
                    operation_id=operation_id,
                    root=self.paths.root,
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
            "repair_provenance": _entrypoint_repair_manifest_provenance(manifest),
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

    def adapter_targets(
        self,
        harness_name: str,
        from_market: bool = True,
        package: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        plan = self.entrypoint_repair_plan(harness_name, from_market=from_market)
        package_candidates = [package] if package else list(plan.get("package_candidates", []))
        package_reports = [
            _adapter_target_package_report(candidate, limit=limit)
            for candidate in package_candidates
        ]
        targets = [
            {
                **target,
                "package": report["package"],
                "repair_command": (
                    f"python -m cbn plugin repair-entrypoint cli-anything {harness_name} "
                    f"--from-market --module {target['module']}"
                ),
            }
            for report in package_reports
            for target in report.get("targets", [])
        ]
        targets.sort(key=lambda item: (-int(item["score"]), item["module"]))
        targets = targets[: max(0, min(limit, 100))]
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
            "summary": {
                "package_count": len(package_reports),
                "target_count": len(targets),
                "recommended_module": recommended["module"] if recommended else None,
                "recommended_score": recommended["score"] if recommended else None,
                "recommended_next_action": (
                    "inspect_top_target_then_repair_entrypoint"
                    if recommended
                    else "write_custom_adapter_or_choose_package_api"
                ),
            },
            "next_commands": [
                f"python -m cbn plugin repair-plan cli-anything {harness_name} --from-market",
                f"python -m cbn plugin adapter-targets cli-anything {harness_name} --from-market",
                (
                    f"python -m cbn plugin repair-entrypoint cli-anything {harness_name} "
                    f"--from-market --module {recommended['module']}"
                    if recommended
                    else None
                ),
            ],
        }

    def adapter_target_smoke(
        self,
        harness_name: str,
        module: str,
        from_market: bool = True,
        smoke_args: tuple[str, ...] = ("--help",),
        timeout_seconds: int = 10,
        run: bool = False,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        targets_report = self.adapter_targets(harness_name, from_market=from_market, limit=50)
        selected = next(
            (target for target in targets_report.get("targets", []) if target.get("module") == module),
            None,
        )
        module_report = _module_report(module)
        argv = (sys.executable, "-m", module, *smoke_args)
        execution = _adapter_target_smoke_execution(
            argv=argv,
            cwd=self.paths.root,
            timeout_seconds=timeout_seconds,
            run=run,
            confirmed=confirmed,
            operation_runner=self.operation_runner,
            plugin_dir=self.paths.external_plugins / PLUGIN_ID,
            harness_name=harness_name,
            module=module,
        )
        return {
            "ok": True,
            "plugin_id": PLUGIN_ID,
            "kind": "CliAnythingAdapterTargetSmoke",
            "harness_name": harness_name,
            "from_market": from_market,
            "module": module,
            "smoke_args": list(smoke_args),
            "timeout_seconds": timeout_seconds,
            "run": run,
            "confirmed": confirmed,
            "command": list(argv),
            "selected_target": selected,
            "module_report": module_report,
            "targets_summary": targets_report["summary"],
            "execution": execution,
            "summary": {
                "candidate_known": selected is not None,
                "module_importable": bool(module_report.get("importable")),
                "executed": execution["status"] in {"completed", "failed", "timeout", "spawn_failed"},
                "smoke_ok": execution.get("exit_code") == 0,
                "recommended_next_action": _adapter_target_smoke_next_action(selected, module_report, execution),
            },
            "next_commands": [
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
            ],
        }

    def adaptation_gate(
        self,
        harness_name: str,
        from_market: bool = True,
        module: str | None = None,
        require_smoke: bool = True,
        run_smoke: bool = False,
        confirmed: bool = False,
        smoke_args: tuple[str, ...] = ("--help",),
        smoke_timeout_seconds: int = 10,
    ) -> dict[str, Any]:
        evaluation = self.evaluate_harness(harness_name, from_market=from_market)
        gates = evaluation.get("gates") if isinstance(evaluation.get("gates"), dict) else {}
        native_launch_ready = bool(gates.get("launch_ready"))
        repair_plan = None
        adapter_targets = None
        selected_target = None
        selected_module = module
        smoke_report = None
        repair_scan = _adaptation_gate_repair_scan_decision(evaluation, native_launch_ready, module)
        if repair_scan["scan"]:
            repair_plan = self.entrypoint_repair_plan(harness_name, from_market=from_market)
            diagnosis = repair_plan.get("diagnosis") if isinstance(repair_plan.get("diagnosis"), dict) else {}
            if diagnosis.get("repair_required"):
                adapter_targets = self.adapter_targets(harness_name, from_market=from_market, limit=20)
                targets = adapter_targets.get("targets", [])
                selected_target = next(
                    (target for target in targets if target.get("module") == module),
                    None,
                )
                if selected_target is None and module is None and targets:
                    selected_target = targets[0]
                    selected_module = str(selected_target.get("module"))
                if selected_module:
                    smoke_report = self.adapter_target_smoke(
                        harness_name,
                        module=selected_module,
                        from_market=from_market,
                        smoke_args=smoke_args,
                        timeout_seconds=smoke_timeout_seconds,
                        run=run_smoke,
                        confirmed=confirmed,
                    )
        smoke_gate = _repair_entrypoint_smoke_gate(require_smoke, smoke_report)
        summary = _adaptation_gate_summary(
            evaluation=evaluation,
            native_launch_ready=native_launch_ready,
            repair_plan=repair_plan,
            selected_module=selected_module,
            smoke_gate=smoke_gate,
            smoke_report=smoke_report,
            require_smoke=require_smoke,
            repair_scan=repair_scan,
        )
        return {
            "ok": True,
            "plugin_id": PLUGIN_ID,
            "kind": "CliAnythingHarnessAdaptationGate",
            "harness_name": harness_name,
            "from_market": from_market,
            "module": module,
            "selected_module": selected_module,
            "require_smoke": require_smoke,
            "run_smoke": run_smoke,
            "confirmed": confirmed,
            "smoke_args": list(smoke_args),
            "smoke_timeout_seconds": smoke_timeout_seconds,
            "summary": summary,
            "repair_scan": repair_scan,
            "stages": _adaptation_gate_stages(
                evaluation=evaluation,
                repair_plan=repair_plan,
                adapter_targets=adapter_targets,
                selected_module=selected_module,
                smoke_gate=smoke_gate,
                smoke_report=smoke_report,
                summary=summary,
                repair_scan=repair_scan,
            ),
            "evaluation": evaluation,
            "repair_plan": repair_plan,
            "adapter_targets": adapter_targets,
            "selected_target": selected_target,
            "smoke_report": smoke_report,
            "next_commands": [
                f"python -m cbn plugin adaptation-gate cli-anything {harness_name} --from-market",
                f"python -m cbn plugin adapter-targets cli-anything {harness_name} --from-market --limit 10",
                (
                    f"python -m cbn plugin adapter-smoke cli-anything {harness_name} "
                    f"--from-market --module {selected_module} --run --yes"
                    if selected_module
                    else None
                ),
                (
                    f"python -m cbn plugin repair-entrypoint cli-anything {harness_name} "
                    f"--from-market --module {selected_module} --require-smoke --write --yes"
                    if selected_module
                    else None
                ),
            ],
        }

    def adaptation_queue(
        self,
        harnesses: tuple[str, ...] = (),
        query: str | None = None,
        limit: int = 20,
        max_harnesses: int = 5,
        include_blocked: bool = True,
        require_smoke: bool = True,
        run_smoke: bool = False,
        confirmed: bool = False,
        smoke_args: tuple[str, ...] = ("--help",),
        smoke_timeout_seconds: int = 10,
    ) -> dict[str, Any]:
        bounded_limit = max(0, min(limit, 500))
        bounded_max = max(0, min(max_harnesses, 50))
        source_report = None
        source = "explicit_harnesses"
        selected_harnesses = _unique_harnesses(harnesses)
        if not selected_harnesses:
            source = "market_install_queue"
            source_report = self.market_install_queue(
                query=query,
                limit=bounded_limit,
                max_installs=bounded_max,
                include_blocked=include_blocked,
            )
            selected_harnesses = _harnesses_from_install_queue(source_report, include_blocked=include_blocked)
        selected_harnesses = selected_harnesses[:bounded_max]
        gates = [
            self.adaptation_gate(
                harness,
                from_market=True,
                require_smoke=require_smoke,
                run_smoke=run_smoke,
                confirmed=confirmed,
                smoke_args=smoke_args,
                smoke_timeout_seconds=smoke_timeout_seconds,
            )
            for harness in selected_harnesses
        ]
        summary = _adaptation_queue_summary(gates)
        return {
            "ok": True,
            "plugin_id": PLUGIN_ID,
            "kind": "CliAnythingHarnessAdaptationQueue",
            "source": source,
            "query": query,
            "limit": bounded_limit,
            "max_harnesses": bounded_max,
            "include_blocked": include_blocked,
            "harnesses": selected_harnesses,
            "require_smoke": require_smoke,
            "run_smoke": run_smoke,
            "confirmed": confirmed,
            "smoke_args": list(smoke_args),
            "smoke_timeout_seconds": smoke_timeout_seconds,
            "summary": summary,
            "gates": gates,
            "source_report": source_report,
            "next_commands": [
                "python -m cbn plugin adaptation-queue cli-anything --query file --limit 20 --max-harnesses 5",
                "python -m cbn plugin adaptation-queue cli-anything --harness py4csr --harness 3mf",
                "python -m cbn plugin adaptation-gate cli-anything <harness> --from-market",
                "python -m cbn plugin adaptation-gate cli-anything <harness> --from-market --run-smoke --yes",
            ],
        }

    def live_verification(
        self,
        harnesses: tuple[str, ...] = ("mermaid", "macrocli"),
        candidate_query: str | None = "image",
        candidate_limit: int = 10,
        include_candidates: bool = True,
        include_workflows: bool = True,
        run_smoke_suite: bool = False,
        smoke_extra_args: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Return a repeatable read-only verification snapshot for CLI-Anything."""

        status = self.status()
        environment = self._environment_verification()
        harness_reports = [
            self.verify_harness(
                harness,
                from_market=True,
                include_workflows=include_workflows,
                run_smoke_suite=run_smoke_suite,
                smoke_extra_args=smoke_extra_args,
            )
            for harness in harnesses
        ]
        harness_summary = [_harness_live_summary(report) for report in harness_reports]
        candidates = (
            self.candidate_harnesses(
                query=candidate_query,
                limit=candidate_limit,
                with_probes=True,
                compact=True,
            )
            if include_candidates
            else None
        )
        workflow_readiness = (
            self._workflow_readiness("workflows/cli-anything-macrocli-mermaid-routing.example.json")
            if include_workflows
            else None
        )
        summary = _live_verification_summary(
            status=status,
            environment=environment,
            harness_summary=harness_summary,
            candidates=candidates,
            workflow_readiness=workflow_readiness,
        )
        return {
            "ok": summary["entrypoint_available"]
            and summary["verified_harness_count"] == len(harness_summary)
            and summary["workflow_internal_bridge_ready"] is not False,
            "plugin_id": PLUGIN_ID,
            "kind": "CliAnythingLiveVerification",
            "run_smoke_suite": run_smoke_suite,
            "status": status,
            "environment": environment,
            "harnesses": harness_summary,
            "candidate_scan": _candidate_live_summary(candidates) if candidates else None,
            "workflow_readiness": _workflow_live_summary(workflow_readiness) if workflow_readiness else None,
            "summary": summary,
            "reports": {
                "harness_verifications": harness_reports,
                "candidates": candidates,
                "workflow_readiness": workflow_readiness,
            },
            "next_commands": [
                "python -m cbn plugin live-verification cli-anything",
                "python -m cbn plugin candidates cli-anything --query image --limit 10 --with-probes --compact",
                "python -m cbn plugin verify-harness cli-anything mermaid",
                "python -m cbn plugin verify-harness cli-anything macrocli",
                "python -m cbn plugin verify-harness cli-anything 3mf --smoke-suite --smoke-extra-arg=--help --no-workflows",
                "python -m cbn call cli-anything.macrocli.backends",
                "python -m cbn workflow run workflows/cli-anything-macrocli-mermaid-routing.example.json",
                "python -m cbn protocol readiness --workflow-path workflows/cli-anything-macrocli-mermaid-routing.example.json",
            ],
        }

    def mvp_plan(
        self,
        query: str | None = "file",
        limit: int = 20,
        max_harnesses: int = 5,
        include_blocked: bool = True,
        workflow_paths: tuple[str, ...] = (),
        max_workflows: int = 10,
        registry: ManifestRegistry | None = None,
        workflow_runner: Any | None = None,
    ) -> dict[str, Any]:
        """Return the read-only MVP control plan for the next CLI-Anything work."""

        bounded_limit = max(0, min(limit, 500))
        bounded_max_harnesses = max(0, min(max_harnesses, 50))
        bounded_max_workflows = max(1, min(max_workflows, 50))
        environment = self._environment_verification()
        install_gate = _safe_plugin_report(lambda: PluginManager(root=self.paths.root).operation_gate(PLUGIN_ID, "install"))
        install_queue = self.market_install_queue(
            query=query,
            limit=bounded_limit,
            max_installs=bounded_max_harnesses,
            include_blocked=include_blocked,
        )
        adaptation_queue = self.adaptation_queue(
            query=query,
            limit=bounded_limit,
            max_harnesses=bounded_max_harnesses,
            include_blocked=include_blocked,
            require_smoke=True,
            run_smoke=False,
            confirmed=False,
        )
        registry = registry or _load_manifest_registry(self.paths.manifests)
        protocol_readiness = protocol_readiness_report(registry, include_workflows=True)
        acceptance_queue = (
            cli_to_cli_acceptance_queue(
                registry,
                workflow_runner,
                workflow_paths=workflow_paths or None,
                max_workflows=bounded_max_workflows,
                run=False,
                dry_run=True,
                confirmed=False,
                include_payloads=False,
            )
            if workflow_runner is not None
            else {
                "ok": False,
                "kind": "CliToCliAcceptanceQueue",
                "skipped": True,
                "reason": "workflow_runner was not provided",
                "summary": {
                    "workflow_count": 0,
                    "accepted_workflow_count": 0,
                    "blocked_workflow_count": 0,
                    "route_count": 0,
                    "route_ready_count": 0,
                    "blocked_route_count": 0,
                },
                "rows": [],
                "failures": [],
                "next_steps": ["Call mvp-plan through the CLI or daemon runtime to include acceptance evidence."],
            }
        )
        summary = _mvp_plan_summary(
            environment=environment,
            install_gate=install_gate,
            install_queue=install_queue,
            adaptation_queue=adaptation_queue,
            protocol_readiness=protocol_readiness,
            acceptance_queue=acceptance_queue,
        )
        return {
            "ok": True,
            "plugin_id": PLUGIN_ID,
            "kind": "CliAnythingMvpPlan",
            "query": query,
            "limit": bounded_limit,
            "max_harnesses": bounded_max_harnesses,
            "include_blocked": include_blocked,
            "workflow_paths": list(workflow_paths),
            "max_workflows": bounded_max_workflows,
            "summary": summary,
            "stages": _mvp_plan_stages(summary),
            "reports": {
                "environment": environment,
                "install_gate": install_gate,
                "install_queue": install_queue,
                "adaptation_queue": adaptation_queue,
                "protocol_readiness": protocol_readiness,
                "acceptance_queue": acceptance_queue,
            },
            "next_commands": [
                "python -m cbn plugin preflight cli-anything",
                "python -m cbn plugin install cli-anything --yes",
                (
                    f"python -m cbn plugin install-queue cli-anything --query {query or '<query>'} "
                    f"--limit {bounded_limit} --max-installs {bounded_max_harnesses}"
                ),
                (
                    f"python -m cbn plugin adaptation-queue cli-anything --query {query or '<query>'} "
                    f"--limit {bounded_limit} --max-harnesses {bounded_max_harnesses}"
                ),
                "python -m cbn protocol acceptance-queue --run --dry-run",
                "python -m cbn protocol readiness --include-workflows",
                "python -m cbn protocol smoke-suite --workflow-dry-run",
            ],
        }

    def bootstrap_plan(
        self,
        harness_name: str = "mermaid",
        query: str | None = "file",
        include_workflows: bool = True,
        workflow_path: str = "workflows/cli-anything-macrocli-mermaid-routing.example.json",
    ) -> dict[str, Any]:
        """Return the read-only bootstrap runbook for installing CLI-Anything."""

        manager = PluginManager(root=self.paths.root)
        environment = self._environment_verification()
        install_plan = _safe_plugin_report(lambda: manager.plan(PLUGIN_ID, "install").as_dict())
        update_plan = _safe_plugin_report(lambda: manager.plan(PLUGIN_ID, "update").as_dict())
        install_gate = _safe_plugin_report(lambda: manager.operation_gate(PLUGIN_ID, "install"))
        update_gate = _safe_plugin_report(lambda: manager.operation_gate(PLUGIN_ID, "update"))
        entrypoint_available = bool(
            any(item.get("available") for item in environment.get("entrypoints", []) if isinstance(item, dict))
        )
        market_scan = (
            self.candidate_harnesses(query=query, limit=10, with_probes=True, compact=True)
            if entrypoint_available
            else {
                "ok": False,
                "skipped": True,
                "reason": "cli-hub entrypoint is not available yet",
                "query": query,
                "candidate_summary": [],
            }
        )
        onboarding = self.onboard_harness(
            harness_name,
            from_market=entrypoint_available,
            write=False,
            confirmed=False,
            install=False,
            include_workflows=include_workflows,
            run_smoke_suite=False,
        )
        lifecycle_suite = protocol_lifecycle_suite(
            capability_id="git.version",
            workflow_path=workflow_path,
        )
        source_downloaded = bool(environment.get("source_downloaded"))
        source_trusted = environment.get("source_trusted")
        summary = {
            "source_downloaded": source_downloaded,
            "source_trusted": source_trusted,
            "entrypoint_available": entrypoint_available,
            "install_gate_ok": bool(install_gate.get("ok")),
            "update_gate_ok": bool(update_gate.get("ok")),
            "market_scan_ok": bool(market_scan.get("ok")),
            "market_scan_skipped": bool(market_scan.get("skipped")),
            "onboarding_ok": bool(onboarding.get("ok")),
            "onboarding_stage_count": len(onboarding.get("stage_results", []))
            if isinstance(onboarding.get("stage_results"), list)
            else 0,
            "protocol_lifecycle_ok": bool(lifecycle_suite.get("ok")),
            "recommended_next_action": _bootstrap_next_action(
                source_downloaded=source_downloaded,
                source_trusted=source_trusted,
                entrypoint_available=entrypoint_available,
                install_gate_ok=bool(install_gate.get("ok")),
                market_scan_ok=bool(market_scan.get("ok")),
                onboarding_ok=bool(onboarding.get("ok")),
                protocol_lifecycle_ok=bool(lifecycle_suite.get("ok")),
            ),
        }
        return {
            "ok": True,
            "plugin_id": PLUGIN_ID,
            "kind": "CliAnythingBootstrapPlan",
            "harness_name": harness_name,
            "query": query,
            "include_workflows": include_workflows,
            "workflow_path": workflow_path,
            "summary": summary,
            "stages": _bootstrap_stages(summary, harness_name, query, workflow_path),
            "plans": {
                "install": install_plan,
                "update": update_plan,
            },
            "reports": {
                "environment": environment,
                "install_gate": install_gate,
                "update_gate": update_gate,
                "market_scan": market_scan,
                "onboarding": onboarding,
                "protocol_lifecycle_suite": lifecycle_suite,
            },
            "next_commands": [
                "python -m cbn plugin bootstrap-plan cli-anything",
                "python -m cbn plugin preflight cli-anything",
                "python -m cbn plugin install cli-anything --yes",
                "python -m cbn plugin provenance cli-anything",
                "python -m cbn plugin check-update cli-anything --remote",
                f"python -m cbn plugin candidates cli-anything --query {query or '<query>'} --limit 10 --with-probes --compact",
                f"python -m cbn plugin onboard-harness cli-anything {harness_name} --from-market",
                f"python -m cbn protocol lifecycle-suite --capability-id git.version --workflow-path {workflow_path}",
            ],
        }

    def _environment_verification(self) -> dict[str, Any]:
        manager = PluginManager(root=self.paths.root)
        report: dict[str, Any] = {
            "preflight": _safe_plugin_report(lambda: manager.preflight(PLUGIN_ID)),
            "provenance": _safe_plugin_report(lambda: manager.provenance(PLUGIN_ID)),
            "update_check": _safe_plugin_report(lambda: manager.update_check(PLUGIN_ID)),
        }
        preflight = report["preflight"]
        provenance = report["provenance"]
        update_check = report["update_check"]
        return {
            "ok": bool(
                preflight.get("ready")
                and provenance.get("source_trusted") is not False
                and not update_check.get("blockers")
            ),
            "preflight_ready": preflight.get("ready"),
            "source_downloaded": provenance.get("source_downloaded"),
            "source_trusted": provenance.get("source_trusted"),
            "ready_for_update": update_check.get("ready_for_update"),
            "repository": (provenance.get("repository") or {}),
            "entrypoints": provenance.get("entrypoints", []),
            "reports": report,
        }

    def _workflow_readiness(self, workflow_path: str) -> dict[str, Any] | None:
        path = self.paths.root / workflow_path
        if not path.exists():
            return None
        registry = ManifestRegistry()
        registry.load_dir(self.paths.manifests)
        return protocol_readiness_report(
            registry,
            workflow_path=workflow_path,
            include_workflows=True,
        )

    def _candidate_from_market_record(
        self,
        record: dict[str, Any],
        market_index: int,
    ) -> dict[str, Any]:
        harness_name = str(record.get("name") or record.get("display_name") or "").strip()
        if not harness_name:
            return {
                "ok": False,
                "market_index": market_index,
                "harness_name": None,
                "capability_id": None,
                "install_candidate": False,
                "recommended_next_action": "resolve_blockers",
                "blockers": ["market record is missing name/display_name"],
                "market_record": record,
            }
        try:
            manifest = self.manifest_for_harness(harness_name, market_record=record)
            capability_id = manifest["metadata"]["id"]
            manifest_path = self.paths.manifests / f"{capability_id}.json"
            if manifest_path.exists():
                manifest = _manifest_dict_from_path(manifest_path, manifest)
            validation = validate_manifest_dict(
                manifest,
                source_path=manifest_path,
                known_parser_refs=_known_parser_refs(),
            )
        except (TypeError, ValueError) as exc:
            manifest = None
            capability_id = None
            manifest_path = None
            validation = {"valid": False, "errors": [str(exc)], "warnings": []}
        requires = _declared_requires(record, {})
        requirements = _requirement_assessment(requires)
        platform = _platform_assessment(record, requires)
        policy = manifest["spec"]["policy"] if manifest else infer_market_policy(record)
        transport = _transport_assessment(manifest) if manifest else {"ready": False}
        entry_point = str(record.get("entry_point") or "") or None
        entrypoint_path = shutil.which(entry_point) if entry_point else None
        manifest_imported = bool(manifest_path and manifest_path.exists())
        installed = entrypoint_path is not None
        launch_ready = bool(installed and manifest_imported and validation["valid"] and transport.get("ready"))
        low_policy_risk = policy["risk"] in {"read", "write-workspace"} and not _policy_requires_confirmation(policy)
        gates = {
            "manifest_valid": bool(validation["valid"]),
            "manifest_imported": manifest_imported,
            "installed": installed,
            "entrypoint_available": installed,
            "runtime_transport_ready": bool(transport.get("ready")),
            "launch_ready": launch_ready,
            "low_policy_risk": low_policy_risk,
            "external_dependency_free": bool(requirements["external_dependency_free"]),
            "platform_compatible": bool(platform["compatible"]),
        }
        blockers = []
        if not gates["manifest_valid"]:
            blockers.append("generated manifest is invalid")
        if not gates["low_policy_risk"]:
            blockers.append("policy requires elevated confirmation")
        if not gates["external_dependency_free"]:
            blockers.append("declared requirements need external app, account, token, or service")
        if not gates["platform_compatible"]:
            blockers.append("declared platform does not match this host")
        if gates["installed"] and not gates["entrypoint_available"]:
            blockers.append("installed harness entrypoint is missing from PATH")
        install_candidate = len(blockers) == 0
        if gates["launch_ready"]:
            recommended_next_action = "call_capability"
        elif install_candidate and gates["installed"] and not gates["manifest_imported"]:
            recommended_next_action = "write_manifest"
        elif install_candidate and gates["manifest_imported"]:
            recommended_next_action = "install_harness"
        elif install_candidate:
            recommended_next_action = "write_manifest"
        else:
            recommended_next_action = "resolve_blockers"
        lifecycle = _lifecycle_report(
            harness_name=harness_name,
            capability_id=capability_id,
            recommended_next_action=recommended_next_action,
            gates=gates,
            blockers=blockers,
            install_candidate=install_candidate,
        )
        return {
            "ok": True,
            "market_index": market_index,
            "harness_name": harness_name,
            "display_name": str(record.get("display_name") or harness_name),
            "capability_id": capability_id,
            "manifest_path": str(manifest_path) if manifest_path else None,
            "install_candidate": install_candidate,
            "recommended_next_action": recommended_next_action,
            "blockers": blockers,
            "gates": gates,
            "local_status": {
                "manifest_imported": manifest_imported,
                "entry_point": entry_point,
                "entrypoint_path": entrypoint_path,
                "entrypoint_available": installed,
                "launch_ready": launch_ready,
            },
            "requirements": requirements,
            "platform": platform,
            "transport": transport,
            "policy": policy,
            "lifecycle": lifecycle,
            "validation": validation,
            "market_record": record,
            "next_commands": [
                f"python -m cbn plugin evaluate-harness cli-anything {harness_name}",
                f"python -m cbn plugin adapt-harness cli-anything {harness_name} --from-market --write",
                f"python -m cbn plugin harness cli-anything install {harness_name} --yes",
            ],
        }

    def sync_market(
        self,
        query: str | None = None,
        limit: int = 50,
        write: bool = False,
    ) -> dict[str, Any]:
        result = self.search_market(query) if query else self.list_market()
        records = _market_records_from_result(result.parsed_json)
        if result.exit_code != 0:
            return {
                "ok": False,
                "plugin_id": PLUGIN_ID,
                "query": query,
                "write": write,
                "error": "CLI-Anything market command failed",
                "market": result.as_dict(),
                "records": [],
                "manifests": [],
            }
        if records is None:
            return {
                "ok": False,
                "plugin_id": PLUGIN_ID,
                "query": query,
                "write": write,
                "error": "CLI-Anything market command did not return a supported JSON list shape",
                "market": result.as_dict(),
                "records": [],
                "manifests": [],
            }
        bounded_limit = max(0, min(limit, 500))
        selected = records[:bounded_limit]
        manifests = []
        for record in selected:
            harness_name = str(record.get("name") or record.get("display_name") or "").strip()
            if not harness_name:
                manifests.append(
                    {
                        "ok": False,
                        "error": "market record is missing name/display_name",
                        "market_record": record,
                    }
                )
                continue
            manifest = self.manifest_for_harness(harness_name, market_record=record)
            capability_id = manifest["metadata"]["id"]
            path = self.paths.manifests / f"{capability_id}.json"
            validation = validate_manifest_dict(
                manifest,
                source_path=path,
                known_parser_refs=_known_parser_refs(),
            )
            manifests.append(
                {
                    "ok": bool(validation["valid"]),
                    "error": None if validation["valid"] else "generated manifest is invalid",
                    "harness_name": harness_name,
                    "capability_id": capability_id,
                    "manifest_path": str(path),
                    "written": None,
                    "manifest": manifest,
                    "validation": validation,
                    "market_record": record,
                }
            )
        _mark_capability_collisions(manifests)
        writable = [item for item in manifests if item.get("ok")]
        if write:
            for item in writable:
                record = item["market_record"]
                harness_name = item["harness_name"]
                written = self.write_harness_manifest(harness_name, market_record=record)
                item["written"] = str(written)
                item["manifest_path"] = str(written)
                item["validation"] = validate_manifest_dict(
                    item["manifest"],
                    source_path=written,
                    known_parser_refs=_known_parser_refs(),
                )
        conflict_count = sum(
            1
            for item in manifests
            if item.get("error") == "duplicate capability_id generated from market records"
        )
        invalid_count = sum(1 for item in manifests if item.get("error") == "generated manifest is invalid")
        failed_count = sum(1 for item in manifests if not item.get("ok"))
        return {
            "ok": failed_count == 0,
            "plugin_id": PLUGIN_ID,
            "query": query,
            "write": write,
            "limit": bounded_limit,
            "market_count": len(records),
            "selected_count": len(selected),
            "importable_count": len(writable),
            "conflict_count": conflict_count,
            "invalid_count": invalid_count,
            "failed_count": failed_count,
            "market": result.as_dict(),
            "manifests": manifests,
            "next_commands": [
                "python -m cbn registry search cli-anything",
                "python -m cbn protocol export all --capability-id <capability_id>",
                "python -m cbn plugin harness cli-anything install <harness> --yes",
            ],
        }

    def _run(self, args: tuple[str, ...], parse_json: bool) -> CliHubCommandResult:
        executable = shutil.which(self.entrypoint)
        argv = (self.entrypoint, *args)
        if executable is None:
            return CliHubCommandResult(
                argv=argv,
                exit_code=127,
                stdout="",
                stderr=f"{self.entrypoint} is not installed or not on PATH",
            )
        proc = subprocess.run(
            [executable, *args],
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
        parsed = None
        if parse_json and proc.stdout.strip():
            try:
                parsed = json.loads(proc.stdout)
            except json.JSONDecodeError:
                parsed = None
        return CliHubCommandResult(
            argv=(executable, *args),
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            parsed_json=parsed,
        )


def sanitize_harness_name(name: str) -> str:
    return _manifest_factory_sanitize_harness_name(name)


def _matches_sanitized_name(value: Any, expected: str) -> bool:
    if value is None:
        return False
    try:
        return sanitize_harness_name(str(value)) == expected
    except ValueError:
        return False


def _parse_info_fields(stdout: str) -> dict[str, str]:
    fields = {}
    for line in stdout.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = re.sub(r"[^a-z0-9]+", "_", key.strip().casefold()).strip("_")
        value = value.strip()
        if key and value:
            fields[key] = value
    return fields


def _is_installed_status(status_text: str | None) -> bool:
    if not status_text:
        return False
    normalized = status_text.strip().casefold()
    return normalized == "installed" or normalized.startswith("installed ")


def _market_labels(market_record: dict[str, Any]) -> dict[str, str]:
    return _manifest_factory_market_labels(market_record)


def _market_annotations(market_record: dict[str, Any]) -> dict[str, str]:
    return _manifest_factory_market_annotations(market_record)


def infer_market_policy(
    market_record: dict[str, Any] | None,
    requested_risk: str = "read",
) -> dict[str, Any]:
    return _manifest_factory_infer_market_policy(market_record, requested_risk=requested_risk)


def _market_records_from_result(parsed_json: Any) -> list[dict[str, Any]] | None:
    return _market_parts_market_records_from_result(parsed_json)


def _mark_capability_collisions(manifests: list[dict[str, Any]]) -> None:
    _market_parts_mark_capability_collisions(manifests)


def _mark_candidate_collisions(candidates: list[dict[str, Any]]) -> None:
    _market_parts_mark_candidate_collisions(candidates)


def _refresh_candidate_lifecycle(item: dict[str, Any]) -> None:
    harness_name = item.get("harness_name")
    if not isinstance(harness_name, str) or not harness_name:
        return
    blockers = item.get("blockers")
    if not isinstance(blockers, list):
        blockers = []
    gates = item.get("gates")
    if not isinstance(gates, dict):
        gates = {}
    item["lifecycle"] = _lifecycle_report(
        harness_name=harness_name,
        capability_id=item.get("capability_id") if isinstance(item.get("capability_id"), str) else None,
        recommended_next_action=str(item.get("recommended_next_action") or "resolve_blockers"),
        gates=gates,
        blockers=blockers,
        install_candidate=bool(item.get("install_candidate")),
    )


def _attach_candidate_readiness(item: dict[str, Any]) -> None:
    record = item.get("market_record") if isinstance(item.get("market_record"), dict) else {}
    readiness = _readiness_summary(
        probes=_dependency_probes(
            requires=_declared_requires(record, {}),
            entry_point=record.get("entry_point"),
        ),
        install_candidate=bool(item.get("install_candidate")),
    )
    item["readiness"] = readiness
    blocker_probes = _readiness_blocker_probes(readiness)
    if blocker_probes:
        blockers = item.setdefault("blockers", [])
        if not isinstance(blockers, list):
            blockers = []
            item["blockers"] = blockers
        for probe in blocker_probes:
            probe_id = probe.get("id") or probe.get("kind") or "unknown"
            blocker = f"dependency probe failed: {probe_id}"
            if blocker not in blockers:
                blockers.append(blocker)
        gates = item.get("gates")
        if isinstance(gates, dict):
            gates["external_dependency_free"] = False
        item["install_candidate"] = False
        item["recommended_next_action"] = "resolve_blockers"
        _refresh_candidate_lifecycle(item)


def _readiness_from_evaluation(evaluation: dict[str, Any]) -> dict[str, Any]:
    status = evaluation.get("status") if isinstance(evaluation.get("status"), dict) else {}
    market_record = status.get("market_record") if isinstance(status.get("market_record"), dict) else None
    return _readiness_summary(
        probes=_dependency_probes(
            requires=_declared_requires(market_record, status),
            entry_point=status.get("entry_point"),
        ),
        install_candidate=bool(evaluation.get("install_candidate")),
    )


def _readiness_summary(probes: list[dict[str, Any]], install_candidate: bool) -> dict[str, Any]:
    return _probe_parts_readiness_summary(probes, install_candidate)


def _readiness_blocker_probes(readiness: dict[str, Any]) -> list[dict[str, Any]]:
    return _probe_parts_readiness_blocker_probes(readiness)


def _parser_contract_report(manifest: dict[str, Any]) -> dict[str, Any]:
    return _verification_parts_parser_contract_report(manifest, _known_parser_refs())


def _effective_manifest_dict(
    imported_manifest: CapabilityManifest | None,
    preview_manifest: dict[str, Any],
) -> dict[str, Any]:
    if imported_manifest is None or imported_manifest.source_path is None:
        return preview_manifest
    return _manifest_dict_from_path(imported_manifest.source_path, preview_manifest)


def _manifest_dict_from_path(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _preserve_existing_parser_contract(
    existing: dict[str, Any],
    generated: dict[str, Any],
) -> dict[str, Any]:
    return _manifest_factory_preserve_existing_parser_contract(existing, generated)


def _protocol_verification_summary(protocol_checks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return _verification_parts_protocol_verification_summary(protocol_checks)


def _workflow_matches_for_capability(
    registry: ManifestRegistry,
    capability_id: str,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for workflow in list_workflows(registry=registry):
        tasks = workflow.get("tasks") if isinstance(workflow.get("tasks"), list) else []
        matched_tasks = [
            {
                "id": task.get("id"),
                "uses": task.get("uses"),
                "capability": task.get("capability"),
            }
            for task in tasks
            if isinstance(task, dict) and task.get("uses") == capability_id
        ]
        if not matched_tasks:
            continue
        matches.append(
            {
                "workflow_id": workflow.get("workflow_id"),
                "title": workflow.get("title"),
                "path": workflow.get("path"),
                "valid": workflow.get("valid"),
                "matched_tasks": matched_tasks,
            }
        )
    return matches


def _verification_blockers(
    evaluation: dict[str, Any],
    readiness: dict[str, Any],
    registry_status: dict[str, Any],
) -> list[str]:
    return _verification_parts_verification_blockers(evaluation, readiness, registry_status)


def _manifest_has_entrypoint_repair(manifest: dict[str, Any]) -> bool:
    return _verification_parts_manifest_has_entrypoint_repair(manifest)


def _registry_source_for_manifest(
    manifest: CapabilityManifest | None,
    *,
    local_manifest_dir: Path,
) -> str:
    return _verification_parts_registry_source_for_manifest(
        manifest,
        local_manifest_dir=local_manifest_dir,
    )


def _verification_stages(
    harness_name: str,
    capability_id: str,
    evaluation: dict[str, Any],
    readiness: dict[str, Any],
    registry_status: dict[str, Any],
    parser_contract: dict[str, Any],
    protocol_checks: dict[str, dict[str, Any]],
    smoke_suite: dict[str, Any],
) -> list[dict[str, Any]]:
    return _verification_parts_verification_stages(
        harness_name,
        capability_id,
        evaluation,
        readiness,
        registry_status,
        parser_contract,
        protocol_checks,
        smoke_suite,
    )


def _parser_fixture_gate(report: dict[str, Any], capability_id: str) -> dict[str, Any]:
    return _verification_parts_parser_fixture_gate(report, capability_id)


def _mark_repaired_manifest_verified_from_fixtures(
    *,
    manifest: dict[str, Any],
    capability_id: str,
    fixture_dir: Path,
    root: Path,
    smoke_ok: bool,
) -> dict[str, Any]:
    output = manifest.setdefault("spec", {}).setdefault("output", {})
    if not isinstance(output, dict):
        return {
            "ok": False,
            "parser_ref": None,
            "capability_verified": False,
            "marked_verified": False,
            "error": "manifest spec.output is not an object",
        }
    parser_ref = str(output.get("parserRef") or "raw.text")
    try:
        fixture_report = run_parser_fixtures(
            path=fixture_dir,
            parser_ref=parser_ref,
            registry=ParserRegistry.builtins(),
        )
    except Exception as exc:
        return {
            "ok": False,
            "parser_ref": parser_ref,
            "capability_verified": False,
            "marked_verified": False,
            "error": str(exc),
        }
    gate = _parser_fixture_gate(fixture_report, capability_id)
    gate["marked_verified"] = False
    if smoke_ok and gate.get("ok") and gate.get("capability_verified"):
        output["verified"] = True
        annotations = manifest.setdefault("metadata", {}).setdefault("annotations", {})
        matching_paths = _matching_parser_fixture_paths(fixture_report, capability_id, root)
        if matching_paths:
            annotations["cbn.parser_fixture"] = matching_paths[0]
        annotations["cbn.parser_fixture_verified_capability"] = capability_id
        gate["marked_verified"] = True
    return gate


def _matching_parser_fixture_paths(
    fixture_report: dict[str, Any],
    capability_id: str,
    root: Path,
) -> list[str]:
    return _verification_parts_matching_parser_fixture_paths(fixture_report, capability_id, root)


def _promotion_blockers(
    verification: dict[str, Any],
    source: Any,
    entrypoint_repair_active: bool,
    parser_contract: dict[str, Any],
    parser_fixture_gate: dict[str, Any],
    smoke_suite: dict[str, Any],
    run_smoke_suite: bool,
    readiness: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if source == "current_registry":
        blockers.append("capability is already loaded from portable manifests/")
    elif source != "runtime_local_overlay":
        blockers.append("capability is not loaded from runtime/manifests overlay")
    if not entrypoint_repair_active:
        blockers.append("runtime overlay does not declare a CBN entrypoint repair")
    for blocker in verification.get("verification_blockers", []):
        if blocker not in blockers:
            blockers.append(str(blocker))
    if not parser_contract.get("known"):
        blockers.append("parser is not known to the local parser registry")
    if not parser_contract.get("verified"):
        blockers.append("parser output contract is not verified in the manifest")
    if not parser_fixture_gate.get("ok"):
        blockers.append("parser fixtures are missing or failing")
    if not parser_fixture_gate.get("capability_verified"):
        blockers.append("parser fixtures do not list this capability as verified")
    if not run_smoke_suite:
        blockers.append("protocol smoke suite was not run for promotion")
    elif not smoke_suite.get("ok"):
        blockers.append("protocol smoke suite failed")
    readiness_gates = readiness.get("readiness") if isinstance(readiness.get("readiness"), dict) else {}
    if not readiness_gates.get("internal_bridge_ready"):
        blockers.append("protocol readiness does not mark internal BridgeMessage routing ready")
    return sorted(set(blockers))


def _promotion_requirements(
    source: Any,
    entrypoint_repair_active: bool,
    parser_contract: dict[str, Any],
    parser_fixture_gate: dict[str, Any],
    smoke_suite: dict[str, Any],
    run_smoke_suite: bool,
    readiness: dict[str, Any],
    verification: dict[str, Any],
) -> list[dict[str, Any]]:
    readiness_gates = readiness.get("readiness") if isinstance(readiness.get("readiness"), dict) else {}
    return [
        {
            "id": "runtime_overlay_source",
            "status": "passed" if source == "runtime_local_overlay" else "blocked",
            "evidence": source,
        },
        {
            "id": "entrypoint_repair_provenance",
            "status": "passed" if entrypoint_repair_active else "blocked",
            "evidence": verification.get("registry", {}).get("manifest_path"),
        },
        {
            "id": "runtime_verification",
            "status": "passed" if verification.get("ready_for_runtime_verification") else "blocked",
            "evidence": verification.get("verification_blockers", []),
        },
        {
            "id": "parser_contract_verified",
            "status": "passed" if parser_contract.get("known") and parser_contract.get("verified") else "blocked",
            "evidence": parser_contract,
        },
        {
            "id": "parser_fixture_capability_coverage",
            "status": "passed" if parser_fixture_gate.get("ok") and parser_fixture_gate.get("capability_verified") else "blocked",
            "evidence": {
                "fixture_count": parser_fixture_gate.get("fixture_count"),
                "case_count": parser_fixture_gate.get("case_count"),
                "failed_case_count": parser_fixture_gate.get("failed_case_count"),
                "matching_fixture_ids": parser_fixture_gate.get("matching_fixture_ids"),
            },
        },
        {
            "id": "protocol_smoke_suite",
            "status": "passed" if run_smoke_suite and smoke_suite.get("ok") else "blocked",
            "evidence": {
                "run": bool(smoke_suite.get("run")),
                "ok": smoke_suite.get("ok"),
                "summary": smoke_suite.get("summary"),
            },
        },
        {
            "id": "internal_bridge_readiness",
            "status": "passed" if readiness_gates.get("internal_bridge_ready") else "blocked",
            "evidence": readiness.get("summary"),
        },
    ]


def _harness_protocol_smoke_suite(
    registry: ManifestRegistry,
    capability_id: str,
    include_workflows: bool,
    extra_args: tuple[str, ...],
    run: bool,
) -> dict[str, Any]:
    workflow_paths: tuple[str, ...] = ("workflows/example.json",) if include_workflows else ()
    command = _protocol_smoke_suite_command(capability_id, extra_args, workflow_paths)
    payload: dict[str, Any] = {
        "run": run,
        "ok": None,
        "command": command,
        "capability_id": capability_id,
        "workflow_paths": list(workflow_paths),
        "extra_args": list(extra_args),
        "wire_compatible": False,
        "summary": None,
        "report": None,
        "error": None,
    }
    if not run:
        payload["status"] = "not_run"
        return payload
    try:
        report = protocol_smoke_suite(
            registry,
            capability_ids=(capability_id,),
            workflow_paths=workflow_paths,
            extra_args=extra_args,
            workflow_dry_run=True,
        )
    except Exception as exc:
        payload.update({"status": "failed", "ok": False, "error": str(exc)})
        return payload
    payload.update(
        {
            "status": "completed" if report.get("ok") else "failed",
            "ok": bool(report.get("ok")),
            "wire_compatible": bool(report.get("wire_compatible")),
            "summary": report.get("summary"),
            "readiness": report.get("readiness"),
            "bridge_contract": report.get("bridge_contract"),
            "failures": report.get("failures", []),
            "report": report,
        }
    )
    return payload


def _protocol_smoke_suite_command(
    capability_id: str,
    extra_args: tuple[str, ...],
    workflow_paths: tuple[str, ...],
) -> str:
    return _verification_parts_protocol_smoke_suite_command(capability_id, extra_args, workflow_paths)


def _smoke_suite_stage_status(smoke_suite: dict[str, Any], gates: dict[str, Any]) -> str:
    return _verification_parts_smoke_suite_stage_status(smoke_suite, gates)


def _policy_requires_confirmation(policy: dict[str, Any]) -> bool:
    return _verification_parts_policy_requires_confirmation(policy)


def _market_command_payload(result: CliHubCommandResult, compact: bool) -> dict[str, Any]:
    if not compact:
        return result.as_dict()
    parsed = result.parsed_json
    payload: dict[str, Any] = {
        "argv": list(result.argv),
        "exit_code": result.exit_code,
        "stdout_chars": len(result.stdout or ""),
        "stderr_chars": len(result.stderr or ""),
        "stdout_omitted": bool(result.stdout),
        "parsed_json_omitted": parsed is not None,
        "parsed_json_type": type(parsed).__name__ if parsed is not None else None,
    }
    if isinstance(parsed, list):
        payload["parsed_json_count"] = len(parsed)
    elif isinstance(parsed, dict):
        payload["parsed_json_keys"] = sorted(str(key) for key in parsed.keys())
    if result.stderr:
        payload["stderr_tail"] = result.stderr[-4000:]
    return payload


def _candidate_summary(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for item in candidates:
        readiness = item.get("readiness") if isinstance(item.get("readiness"), dict) else {}
        lifecycle = item.get("lifecycle") if isinstance(item.get("lifecycle"), dict) else {}
        local_status = item.get("local_status") if isinstance(item.get("local_status"), dict) else {}
        summary.append(
            {
                "rank": item.get("rank"),
                "harness_name": item.get("harness_name"),
                "display_name": item.get("display_name"),
                "capability_id": item.get("capability_id"),
                "install_candidate": bool(item.get("install_candidate")),
                "recommended_next_action": item.get("recommended_next_action"),
                "lifecycle_state": lifecycle.get("state"),
                "blocker_count": len(item.get("blockers", [])),
                "blockers": item.get("blockers", []),
                "launch_ready": bool(local_status.get("launch_ready")),
                "manifest_imported": bool(local_status.get("manifest_imported")),
                "entrypoint_available": bool(local_status.get("entrypoint_available")),
                "readiness_ready": readiness.get("ready"),
                "probe_blocker_count": readiness.get("probe_blocker_count"),
            }
        )
    return summary


def _install_queue_entry(
    item: dict[str, Any],
    install_plan: dict[str, Any],
    evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    harness_name = item.get("harness_name")
    capability_id = item.get("capability_id")
    return {
        "rank": item.get("rank"),
        "harness_name": harness_name,
        "display_name": item.get("display_name"),
        "capability_id": capability_id,
        "state": "queued",
        "ready_for_install": True,
        "requires_confirmation": True,
        "recommended_next_action": item.get("recommended_next_action"),
        "lifecycle": item.get("lifecycle"),
        "gates": item.get("gates"),
        "readiness": item.get("readiness"),
        "evaluation": evaluation,
        "plan": install_plan,
        "commands": {
            "evaluate": f"python -m cbn plugin evaluate-harness cli-anything {harness_name}",
            "adapt_preview": f"python -m cbn plugin adapt-harness cli-anything {harness_name} --from-market",
            "onboard_preview": f"python -m cbn plugin onboard-harness cli-anything {harness_name} --from-market --smoke-suite --smoke-extra-arg=--help --no-workflows",
            "onboard_install": f"python -m cbn plugin onboard-harness cli-anything {harness_name} --from-market --write --install --yes --smoke-suite --smoke-extra-arg=--help --no-workflows",
            "install": f"python -m cbn plugin harness cli-anything install {harness_name} --yes",
            "dry_run_call": f"python -m cbn call {capability_id} --dry-run" if capability_id else None,
        },
    }


def _install_queue_blocked_entry(
    item: dict[str, Any],
    reason: str,
    evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blockers = list(item.get("blockers", []))
    if evaluation and isinstance(evaluation.get("blockers"), list):
        for blocker in evaluation["blockers"]:
            if blocker not in blockers:
                blockers.append(blocker)
    return {
        "rank": item.get("rank"),
        "harness_name": item.get("harness_name"),
        "display_name": item.get("display_name"),
        "capability_id": item.get("capability_id"),
        "state": "blocked",
        "ready_for_install": False,
        "reason": reason,
        "blockers": blockers,
        "recommended_next_action": item.get("recommended_next_action"),
        "lifecycle": item.get("lifecycle"),
        "gates": item.get("gates"),
        "readiness": item.get("readiness"),
        "evaluation": evaluation,
        "commands": {
            "evaluate": f"python -m cbn plugin evaluate-harness cli-anything {item.get('harness_name')}",
            "probe": f"python -m cbn plugin probe-harness cli-anything {item.get('harness_name')}",
        },
    }


def _install_queue_skipped_entry(
    item: dict[str, Any],
    reason: str,
    evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "rank": item.get("rank"),
        "harness_name": item.get("harness_name"),
        "display_name": item.get("display_name"),
        "capability_id": item.get("capability_id"),
        "state": "skipped",
        "ready_for_install": False,
        "reason": reason,
        "recommended_next_action": item.get("recommended_next_action"),
        "lifecycle": item.get("lifecycle"),
        "gates": item.get("gates"),
        "readiness": item.get("readiness"),
        "evaluation": evaluation,
    }


def _blocked_entry_from_evaluation(harness_name: str, evaluation: dict[str, Any]) -> dict[str, Any]:
    capability_id = evaluation.get("capability_id")
    return {
        "rank": None,
        "harness_name": harness_name,
        "display_name": harness_name,
        "capability_id": capability_id,
        "state": "blocked" if not evaluation.get("install_candidate") else "review",
        "ready_for_install": bool(evaluation.get("install_candidate")),
        "reason": "harness evaluation blockers must be resolved first"
        if not evaluation.get("install_candidate")
        else "harness is not blocked by evaluation",
        "blockers": evaluation.get("blockers", []),
        "recommended_next_action": evaluation.get("recommended_next_action"),
        "lifecycle": evaluation.get("lifecycle"),
        "gates": evaluation.get("gates"),
        "readiness": None,
        "evaluation": evaluation,
    }


def _blocked_harness_decision(item: dict[str, Any]) -> dict[str, Any]:
    harness_name = item.get("harness_name")
    capability_id = item.get("capability_id")
    blockers = [str(blocker) for blocker in item.get("blockers", [])]
    categories = _blocker_categories(blockers)
    entrypoint_missing = "installed-entrypoint-missing" in categories
    manual_resolution_required = bool(
        {"manual-dependency", "installed-entrypoint-missing", "platform", "manifest"}
        & set(categories)
    )
    override_available = bool(categories) and not entrypoint_missing
    override_mode = (
        "repair_required"
        if entrypoint_missing
        else "explicit_risk_acceptance"
        if "external-network-or-risk" in categories
        else "manual_dependency_acknowledgement"
        if "manual-dependency" in categories
        else "explicit_override"
    )
    decision_ready = bool(categories)
    commands = {
        "evaluate": f"python -m cbn plugin evaluate-harness cli-anything {harness_name} --from-market",
        "probe": f"python -m cbn plugin probe-harness cli-anything {harness_name} --from-market",
        "onboard_preview": f"python -m cbn plugin onboard-harness cli-anything {harness_name} --from-market --smoke-suite --smoke-extra-arg=--help --no-workflows",
        "onboard_write": f"python -m cbn plugin onboard-harness cli-anything {harness_name} --from-market --write --yes",
        "onboard_install_override": (
            f"python -m cbn plugin onboard-harness cli-anything {harness_name} "
            "--from-market --write --install --yes --allow-blocked "
            "--smoke-suite --smoke-extra-arg=--help --no-workflows"
        ),
        "harness_install_override": f"python -m cbn plugin harness cli-anything install {harness_name} --yes --allow-blocked",
        "dry_run_call": f"python -m cbn call {capability_id} --dry-run" if capability_id else None,
    }
    return {
        "rank": item.get("rank"),
        "harness_name": harness_name,
        "display_name": item.get("display_name"),
        "capability_id": capability_id,
        "reason": item.get("reason"),
        "blockers": blockers,
        "categories": categories,
        "decision_ready": decision_ready,
        "manual_resolution_required": manual_resolution_required,
        "override": {
            "available": override_available,
            "mode": override_mode,
            "requires_confirmation": True,
            "recommended": False,
            "blocked_reason": "repair entrypoint before reinstalling" if entrypoint_missing else None,
        },
        "recommended_next_action": _blocked_recommended_next_action(categories),
        "commands": commands,
        "evidence": {
            "gates": item.get("gates"),
            "readiness": item.get("readiness"),
            "evaluation": item.get("evaluation"),
            "lifecycle": item.get("lifecycle"),
        },
    }


def _blocker_categories(blockers: list[str]) -> list[str]:
    categories = []
    text = "\n".join(blockers).casefold()
    mapping = (
        ("installed-entrypoint-missing", ("entrypoint is missing", "entrypoint missing", "not found on path")),
        ("external-network-or-risk", ("policy requires elevated confirmation", "external-network")),
        ("manual-dependency", ("declared requirements need external app", "dependency probe failed", "backend")),
        ("platform", ("platform",)),
        ("manifest", ("manifest", "duplicate capability_id")),
        ("tooling", ("cli-hub is not available", "market record")),
    )
    for category, markers in mapping:
        if any(marker in text for marker in markers):
            categories.append(category)
    if not categories and blockers:
        categories.append("unknown")
    return categories


def _blocked_recommended_next_action(categories: list[str]) -> str:
    if "installed-entrypoint-missing" in categories:
        return "repair_entrypoint_or_market_metadata"
    if "external-network-or-risk" in categories:
        return "review_and_accept_external_network_risk"
    if "manual-dependency" in categories:
        return "install_or_configure_manual_dependency"
    if "platform" in categories:
        return "use_compatible_platform"
    if "manifest" in categories:
        return "fix_manifest_or_market_metadata"
    return "inspect_blockers"


def _entrypoint_package_candidates(
    harness_name: str,
    market_record: dict[str, Any] | None,
    status: dict[str, Any],
) -> list[str]:
    return _repair_parts_entrypoint_package_candidates(harness_name, market_record, status)


def _packages_from_install_command(command: str) -> list[str]:
    return _repair_parts_packages_from_install_command(command)


def _normalize_package_candidate(candidate: str) -> str | None:
    return _repair_parts_normalize_package_candidate(candidate)


def _script_path_candidates(entry_point: str | None) -> list[dict[str, Any]]:
    return _repair_parts_script_path_candidates(entry_point)


def _distribution_report(package: str) -> dict[str, Any]:
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


def _module_report(package: str) -> dict[str, Any]:
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


def _entrypoint_diagnosis(
    entry_point: str | None,
    entrypoint_path: str | None,
    script_candidates: list[dict[str, Any]],
    distribution_reports: list[dict[str, Any]],
    module_reports: list[dict[str, Any]],
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    return _repair_parts_entrypoint_diagnosis(
        entry_point,
        entrypoint_path,
        script_candidates,
        distribution_reports,
        module_reports,
        evaluation,
    )


def _entrypoint_repair_strategy(plan: dict[str, Any], module: str | None) -> dict[str, Any]:
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
    module_report = _module_report(module)
    if not module_report["importable"]:
        return {
            "ready": False,
            "state": "module_not_importable",
            "module": module,
            "module_report": module_report,
            "blockers": [f"module is not importable: {module}"],
            "recommended_next_action": "choose_importable_python_module",
        }
    return {
        "ready": True,
        "state": "python_module_wrapper",
        "module": module,
        "module_report": module_report,
        "blockers": [],
        "recommended_next_action": "write_wrapper_and_repaired_manifest",
    }


def _entrypoint_wrapper_path(external_plugins: Path, harness_name: str) -> Path:
    return _repair_parts_entrypoint_wrapper_path(
        external_plugins,
        harness_name,
        safe_name=sanitize_harness_name(harness_name),
    )


def _python_module_wrapper_content(module: str) -> str:
    return _repair_parts_python_module_wrapper_content(module)


def _write_repair_entrypoint_files(
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
            "text": _python_module_wrapper_content(module),
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
        result = _atomic_write_text_with_backup(
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


def _atomic_write_text_with_backup(
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


def _entrypoint_repair_manifest(
    plan: dict[str, Any],
    strategy: dict[str, Any],
    wrapper_path: Path,
) -> dict[str, Any]:
    manifest = json.loads(json.dumps(plan["evaluation"]["adaptation"]["manifest"]))
    annotations = manifest.setdefault("metadata", {}).setdefault("annotations", {})
    transport = manifest.setdefault("spec", {}).setdefault("transport", {})
    original_transport = json.loads(json.dumps(transport))
    module_provenance = _entrypoint_repair_module_provenance(plan, strategy)
    policy_recheck = _entrypoint_repair_policy_recheck(plan, manifest)
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
    manifest.setdefault("spec", {})["policy"] = _manifest_policy_from_recheck(policy_recheck["effective_policy"])
    return manifest


def _entrypoint_repair_manifest_provenance(manifest: dict[str, Any]) -> dict[str, Any]:
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


def _json_annotation(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _entrypoint_repair_module_provenance(plan: dict[str, Any], strategy: dict[str, Any]) -> dict[str, Any]:
    module = strategy.get("module")
    module_report = strategy.get("module_report") if isinstance(strategy.get("module_report"), dict) else {}
    distributions = plan.get("distributions") if isinstance(plan.get("distributions"), list) else []
    distribution = _distribution_for_module(str(module) if module else "", distributions)
    return {
        "module": module,
        "module_importable": module_report.get("importable"),
        "module_origin": module_report.get("origin"),
        "module_main": module_report.get("module_main"),
        "distribution": distribution.get("package") if distribution else None,
        "version": distribution.get("version") if distribution else None,
        "location": distribution.get("location") if distribution else None,
    }


def _distribution_for_module(module: str, distributions: list[Any]) -> dict[str, Any] | None:
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


def _entrypoint_repair_policy_recheck(plan: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    original = manifest.get("spec", {}).get("policy", {}) if isinstance(manifest.get("spec"), dict) else {}
    original_policy = {
        "risk": str(original.get("risk") or "read"),
        "requires_confirmation": _policy_requires_confirmation(original),
        "network": str(original.get("network") or "deny"),
    }
    status = plan.get("evaluation", {}).get("status", {}) if isinstance(plan.get("evaluation"), dict) else {}
    market_record = status.get("market_record") if isinstance(status, dict) and isinstance(status.get("market_record"), dict) else None
    inferred = infer_market_policy(market_record, requested_risk=original_policy["risk"])
    effective = {
        "risk": _max_risk(original_policy["risk"], inferred["risk"]),
        "requires_confirmation": bool(original_policy["requires_confirmation"] or inferred["requires_confirmation"]),
        "network": _repair_policy_network(original_policy["network"], inferred["network"]),
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


def _repair_policy_network(original_network: str, inferred_network: str) -> str:
    return _repair_parts_repair_policy_network(original_network, inferred_network)


def _manifest_policy_from_recheck(policy: dict[str, Any]) -> dict[str, Any]:
    return _repair_parts_manifest_policy_from_recheck(policy)


def _adapter_target_package_report(package: str, limit: int = 20) -> dict[str, Any]:
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
    top_levels = _distribution_top_levels(dist, package)
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
                target = _module_adapter_target(path, root, top_level)
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


def _distribution_top_levels(dist: importlib_metadata.Distribution, package: str) -> list[str]:
    raw = dist.read_text("top_level.txt") or ""
    names = [line.strip() for line in raw.splitlines() if line.strip()]
    fallback = package.replace("-", "_").split(".", 1)[0]
    if fallback in names:
        return [fallback]
    if fallback and fallback not in names:
        names.append(fallback)
    return [name for name in names if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name)]


def _module_adapter_target(path: Path, root: Path, top_level: str) -> dict[str, Any] | None:
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
    if _has_name_main_guard(tree):
        score += 70
        evidence.append("if __name__ == '__main__'")
    imports = _imported_root_names(tree)
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


def _imported_root_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".", 1)[0])
    return names


def _has_name_main_guard(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if _is_name_main_compare(node.test):
            return True
    return False


def _is_name_main_compare(node: ast.AST) -> bool:
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


def _adapter_target_smoke_execution(
    argv: tuple[str, ...],
    cwd: Path,
    timeout_seconds: int,
    run: bool,
    confirmed: bool,
    operation_runner: PluginOperationRunner,
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
        "stdout_summary": _clip_text(str(command.get("stdout") or ""), 2000),
        "stderr_summary": _clip_text(str(command.get("stderr") or ""), 2000),
        "operation_id": operation.get("operation_id"),
        "operation_status": operation.get("status"),
        "command_id": command.get("command_id"),
        "artifact_ids": command.get("artifact_ids", []),
        "operation": operation,
    }


def _adapter_target_smoke_next_action(
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


def _repair_entrypoint_smoke_gate(
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


_REPAIRABLE_ENTRYPOINT_BLOCKER = "installed harness entrypoint is missing from PATH"


def _adaptation_gate_repair_scan_decision(
    evaluation: dict[str, Any],
    native_launch_ready: bool,
    module: str | None,
) -> dict[str, Any]:
    gates = evaluation.get("gates") if isinstance(evaluation.get("gates"), dict) else {}
    blockers = evaluation.get("blockers", []) if isinstance(evaluation.get("blockers"), list) else []
    blocker_texts = [str(item) for item in blockers if str(item)]
    if native_launch_ready:
        return {
            "scan": False,
            "status": "not_needed",
            "reason": "native launch is ready",
            "blockers": [],
        }
    if module:
        return {
            "scan": True,
            "status": "requested",
            "reason": "explicit adapter module requested",
            "blockers": [],
        }
    if not gates.get("installed"):
        return {
            "scan": False,
            "status": "skipped",
            "reason": "harness is not installed",
            "blockers": ["harness is not installed"],
        }
    non_repair_blockers = [
        blocker for blocker in blocker_texts if blocker != _REPAIRABLE_ENTRYPOINT_BLOCKER
    ]
    if non_repair_blockers:
        return {
            "scan": False,
            "status": "skipped",
            "reason": "candidate has blockers that entrypoint repair cannot resolve",
            "blockers": non_repair_blockers,
        }
    if _REPAIRABLE_ENTRYPOINT_BLOCKER in blocker_texts:
        return {
            "scan": True,
            "status": "allowed",
            "reason": "entrypoint repair may resolve the launch blocker",
            "blockers": [],
        }
    return {
        "scan": True,
        "status": "allowed",
        "reason": "no non-repair blockers were reported",
        "blockers": [],
    }


def _adaptation_gate_summary(
    evaluation: dict[str, Any],
    native_launch_ready: bool,
    repair_plan: dict[str, Any] | None,
    selected_module: str | None,
    smoke_gate: dict[str, Any],
    smoke_report: dict[str, Any] | None,
    require_smoke: bool,
    repair_scan: dict[str, Any],
) -> dict[str, Any]:
    gates = evaluation.get("gates") if isinstance(evaluation.get("gates"), dict) else {}
    diagnosis = repair_plan.get("diagnosis") if isinstance(repair_plan, dict) else {}
    repair_required = bool(diagnosis.get("repair_required")) if diagnosis else False
    smoke_passed = bool(smoke_report and smoke_report.get("summary", {}).get("smoke_ok"))
    ready_for_repair_write = bool(
        repair_required
        and selected_module
        and (not require_smoke or smoke_gate.get("ok"))
    )
    return {
        "manifest_valid": bool(gates.get("manifest_valid")),
        "installed": bool(gates.get("installed")),
        "native_launch_ready": native_launch_ready,
        "repair_required": repair_required,
        "repair_scan_status": repair_scan["status"],
        "repair_scan_skipped": not bool(repair_scan["scan"]),
        "repair_scan_reason": repair_scan["reason"],
        "repair_scan_blockers": repair_scan["blockers"],
        "selected_module": selected_module,
        "smoke_required": require_smoke,
        "smoke_passed": smoke_passed,
        "smoke_gate_status": smoke_gate["status"],
        "ready_for_call": native_launch_ready,
        "ready_for_repair_write": ready_for_repair_write,
        "recommended_next_action": _adaptation_gate_next_action(
            native_launch_ready=native_launch_ready,
            repair_required=repair_required,
            selected_module=selected_module,
            smoke_gate=smoke_gate,
            ready_for_repair_write=ready_for_repair_write,
        ),
    }


def _adaptation_gate_next_action(
    native_launch_ready: bool,
    repair_required: bool,
    selected_module: str | None,
    smoke_gate: dict[str, Any],
    ready_for_repair_write: bool,
) -> str:
    if native_launch_ready:
        return "verify_harness_and_protocol_facades"
    if not repair_required:
        return "inspect_harness_blockers"
    if not selected_module:
        return "inspect_adapter_targets"
    if ready_for_repair_write:
        return "write_smoke_gated_repaired_manifest"
    if smoke_gate["status"] == "not_run":
        return "run_adapter_smoke"
    if smoke_gate["status"] == "requires_confirmation":
        return "confirm_adapter_smoke"
    return "choose_another_adapter_target_or_fix_dependencies"


def _adaptation_gate_stages(
    evaluation: dict[str, Any],
    repair_plan: dict[str, Any] | None,
    adapter_targets: dict[str, Any] | None,
    selected_module: str | None,
    smoke_gate: dict[str, Any],
    smoke_report: dict[str, Any] | None,
    summary: dict[str, Any],
    repair_scan: dict[str, Any],
) -> list[dict[str, Any]]:
    gates = evaluation.get("gates") if isinstance(evaluation.get("gates"), dict) else {}
    blockers = evaluation.get("blockers", []) if isinstance(evaluation.get("blockers"), list) else []
    target_count = (
        int(adapter_targets.get("summary", {}).get("target_count", 0))
        if isinstance(adapter_targets, dict)
        else 0
    )
    return [
        {
            "id": "evaluate",
            "status": "completed" if evaluation.get("ok") else "blocked",
            "blockers": [] if evaluation.get("ok") else blockers,
        },
        {
            "id": "installed",
            "status": "completed" if gates.get("installed") else "blocked",
            "blockers": [] if gates.get("installed") else ["harness is not installed"],
        },
        {
            "id": "native_launch",
            "status": "completed" if summary["native_launch_ready"] else "blocked",
            "blockers": [] if summary["native_launch_ready"] else blockers,
        },
        {
            "id": "repair_plan",
            "status": (
                "completed"
                if repair_plan and summary["repair_required"]
                else "skipped"
                if summary["native_launch_ready"] or not repair_scan["scan"]
                else "blocked"
            ),
            "repair_scan_status": repair_scan["status"],
            "blockers": (
                []
                if repair_plan or summary["native_launch_ready"]
                else repair_scan["blockers"]
                if not repair_scan["scan"]
                else ["repair plan is unavailable"]
            ),
        },
        {
            "id": "adapter_target",
            "status": (
                "completed"
                if selected_module
                else "skipped"
                if summary["native_launch_ready"] or not summary["repair_required"]
                else "blocked"
            ),
            "target_count": target_count,
            "selected_module": selected_module,
            "blockers": (
                []
                if selected_module or summary["native_launch_ready"] or not summary["repair_required"]
                else ["no adapter target selected"]
            ),
        },
        {
            "id": "adapter_smoke",
            "status": (
                "completed"
                if smoke_gate["status"] == "passed"
                else "skipped"
                if not smoke_gate["required"] or not summary["repair_required"]
                else "ready"
                if smoke_gate["status"] == "not_run"
                else "blocked"
            ),
            "smoke_status": smoke_gate["status"],
            "exit_code": (
                smoke_report.get("execution", {}).get("exit_code")
                if isinstance(smoke_report, dict)
                else None
            ),
            "blockers": smoke_gate["blockers"],
        },
        {
            "id": "repair_write",
            "status": (
                "ready"
                if summary["ready_for_repair_write"]
                else "skipped"
                if summary["native_launch_ready"] or not summary["repair_required"]
                else "blocked"
            ),
            "blockers": (
                []
                if summary["ready_for_repair_write"]
                or summary["native_launch_ready"]
                or not summary["repair_required"]
                else smoke_gate["blockers"]
            ),
        },
    ]


def _unique_harnesses(harnesses: tuple[str, ...]) -> list[str]:
    selected: list[str] = []
    for harness in harnesses:
        value = str(harness).strip()
        if value and value not in selected:
            selected.append(value)
    return selected


def _harnesses_from_install_queue(report: dict[str, Any], include_blocked: bool = True) -> list[str]:
    selected: list[str] = []
    for section in ("queue", "blocked" if include_blocked else "", "skipped"):
        if not section:
            continue
        entries = report.get(section, [])
        if not isinstance(entries, list):
            continue
        for item in entries:
            if not isinstance(item, dict):
                continue
            harness = item.get("harness_name")
            if not isinstance(harness, str) or not harness:
                candidate = item.get("candidate") if isinstance(item.get("candidate"), dict) else {}
                harness = candidate.get("harness_name")
            if isinstance(harness, str) and harness and harness not in selected:
                selected.append(harness)
    return selected


def _adaptation_queue_summary(gates: list[dict[str, Any]]) -> dict[str, Any]:
    action_counts: dict[str, int] = {}
    for gate in gates:
        action = str(gate.get("summary", {}).get("recommended_next_action", "unknown"))
        action_counts[action] = action_counts.get(action, 0) + 1
    return {
        "harness_count": len(gates),
        "native_ready_count": sum(1 for item in gates if item.get("summary", {}).get("native_launch_ready")),
        "ready_for_repair_write_count": sum(
            1 for item in gates if item.get("summary", {}).get("ready_for_repair_write")
        ),
        "smoke_ready_count": sum(
            1 for item in gates if item.get("summary", {}).get("recommended_next_action") == "run_adapter_smoke"
        ),
        "blocked_count": sum(
            1
            for item in gates
            if item.get("summary", {}).get("recommended_next_action")
            in {
                "inspect_harness_blockers",
                "inspect_adapter_targets",
                "choose_another_adapter_target_or_fix_dependencies",
            }
        ),
        "action_counts": action_counts,
    }


def _mvp_plan_summary(
    environment: dict[str, Any],
    install_gate: dict[str, Any],
    install_queue: dict[str, Any],
    adaptation_queue: dict[str, Any],
    protocol_readiness: dict[str, Any],
    acceptance_queue: dict[str, Any],
) -> dict[str, Any]:
    install_summary = install_queue.get("summary") if isinstance(install_queue.get("summary"), dict) else {}
    adaptation_summary = (
        adaptation_queue.get("summary") if isinstance(adaptation_queue.get("summary"), dict) else {}
    )
    protocol_gates = (
        protocol_readiness.get("readiness") if isinstance(protocol_readiness.get("readiness"), dict) else {}
    )
    acceptance_summary = (
        acceptance_queue.get("summary") if isinstance(acceptance_queue.get("summary"), dict) else {}
    )
    source_downloaded = bool(environment.get("source_downloaded"))
    entrypoint_available = bool(
        any(item.get("available") for item in environment.get("entrypoints", []) if isinstance(item, dict))
    )
    plugin_install_ready = bool(install_gate.get("ok") or source_downloaded)
    queued_count = int(install_summary.get("queued_count", 0))
    blocked_install_count = int(install_summary.get("blocked_count", 0))
    native_ready_count = int(adaptation_summary.get("native_ready_count", 0))
    ready_for_repair_write_count = int(adaptation_summary.get("ready_for_repair_write_count", 0))
    smoke_ready_count = int(adaptation_summary.get("smoke_ready_count", 0))
    adaptation_blocked_count = int(adaptation_summary.get("blocked_count", 0))
    internal_bridge_ready = bool(protocol_gates.get("internal_bridge_ready"))
    acceptance_skipped = bool(acceptance_queue.get("skipped"))
    accepted_workflow_count = int(acceptance_summary.get("accepted_workflow_count", 0))
    blocked_workflow_count = int(acceptance_summary.get("blocked_workflow_count", 0))
    return {
        "source_downloaded": source_downloaded,
        "source_trusted": environment.get("source_trusted"),
        "entrypoint_available": entrypoint_available,
        "plugin_install_gate_ok": bool(install_gate.get("ok")),
        "plugin_install_ready": plugin_install_ready,
        "install_queue_ok": bool(install_queue.get("ok")),
        "queued_harness_count": queued_count,
        "blocked_install_count": blocked_install_count,
        "adaptation_harness_count": int(adaptation_summary.get("harness_count", 0)),
        "native_ready_count": native_ready_count,
        "ready_for_repair_write_count": ready_for_repair_write_count,
        "smoke_ready_count": smoke_ready_count,
        "adaptation_blocked_count": adaptation_blocked_count,
        "protocol_internal_bridge_ready": internal_bridge_ready,
        "external_protocol_wire_compatible": bool(protocol_gates.get("external_protocol_wire_compatible")),
        "accepted_workflow_count": accepted_workflow_count,
        "blocked_workflow_count": blocked_workflow_count,
        "acceptance_queue_skipped": acceptance_skipped,
        "ready_for_next_market_download": bool(plugin_install_ready and queued_count > 0),
        "ready_for_harness_adaptation": bool(
            native_ready_count > 0 or ready_for_repair_write_count > 0 or smoke_ready_count > 0
        ),
        "ready_for_cli_to_cli_protocol_study": bool(
            internal_bridge_ready and not acceptance_skipped and blocked_workflow_count == 0
        ),
        "recommended_next_action": _mvp_plan_next_action(
            source_downloaded=source_downloaded,
            plugin_install_ready=plugin_install_ready,
            queued_count=queued_count,
            ready_for_repair_write_count=ready_for_repair_write_count,
            smoke_ready_count=smoke_ready_count,
            adaptation_blocked_count=adaptation_blocked_count,
            internal_bridge_ready=internal_bridge_ready,
            blocked_workflow_count=blocked_workflow_count,
        ),
    }


def _mvp_plan_next_action(
    source_downloaded: bool,
    plugin_install_ready: bool,
    queued_count: int,
    ready_for_repair_write_count: int,
    smoke_ready_count: int,
    adaptation_blocked_count: int,
    internal_bridge_ready: bool,
    blocked_workflow_count: int,
) -> str:
    if not source_downloaded:
        return "install_cli_anything_external_plugin"
    if not plugin_install_ready:
        return "fix_cli_anything_install_gate"
    if queued_count > 0:
        return "install_next_market_harness"
    if smoke_ready_count > 0:
        return "run_adapter_smoke"
    if ready_for_repair_write_count > 0:
        return "repair_entrypoint_with_smoke_evidence"
    if adaptation_blocked_count > 0:
        return "inspect_adaptation_blockers"
    if not internal_bridge_ready or blocked_workflow_count > 0:
        return "fix_cli_to_cli_acceptance"
    return "start_external_protocol_conformance_research"


def _mvp_plan_stages(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": "download_cli_anything",
            "title": "Download CLI-Anything",
            "status": "ready" if summary["source_downloaded"] else "next",
            "ready": bool(summary["plugin_install_ready"]),
            "recommended_next_action": (
                "verify_or_update_cli_anything"
                if summary["source_downloaded"]
                else "install_cli_anything_external_plugin"
            ),
        },
        {
            "id": "install_market_harnesses",
            "title": "Install Market Harnesses",
            "status": (
                "next"
                if summary["ready_for_next_market_download"]
                else "complete"
                if summary["queued_harness_count"] == 0
                and summary["blocked_install_count"] == 0
                and summary["adaptation_harness_count"] > 0
                else "blocked"
            ),
            "ready": bool(summary["ready_for_next_market_download"]),
            "queued_count": summary["queued_harness_count"],
            "blocked_count": summary["blocked_install_count"],
            "recommended_next_action": (
                "install_next_market_harness"
                if summary["ready_for_next_market_download"]
                else "inspect_market_install_queue"
            ),
        },
        {
            "id": "adapt_harnesses",
            "title": "Adapt Harnesses",
            "status": "ready" if summary["ready_for_harness_adaptation"] else "blocked",
            "ready": bool(summary["ready_for_harness_adaptation"]),
            "native_ready_count": summary["native_ready_count"],
            "smoke_ready_count": summary["smoke_ready_count"],
            "ready_for_repair_write_count": summary["ready_for_repair_write_count"],
            "blocked_count": summary["adaptation_blocked_count"],
            "recommended_next_action": (
                "run_adapter_smoke_or_repair_entrypoint"
                if summary["ready_for_harness_adaptation"]
                else "inspect_adaptation_queue"
            ),
        },
        {
            "id": "accept_cli_to_cli_routes",
            "title": "Accept CLI-to-CLI Routes",
            "status": "ready" if summary["ready_for_cli_to_cli_protocol_study"] else "blocked",
            "ready": bool(summary["ready_for_cli_to_cli_protocol_study"]),
            "accepted_workflow_count": summary["accepted_workflow_count"],
            "blocked_workflow_count": summary["blocked_workflow_count"],
            "recommended_next_action": (
                "use_acceptance_rows_as_bridge_fixtures"
                if summary["ready_for_cli_to_cli_protocol_study"]
                else "fix_cli_to_cli_acceptance"
            ),
        },
        {
            "id": "external_protocol_facades",
            "title": "External Protocol Facades",
            "status": "partial",
            "ready": bool(summary["protocol_internal_bridge_ready"]),
            "wire_compatible": bool(summary["external_protocol_wire_compatible"]),
            "recommended_next_action": "run_protocol_smoke_then_add_conformance_coverage",
        },
    ]


def _bootstrap_next_action(
    source_downloaded: bool,
    source_trusted: Any,
    entrypoint_available: bool,
    install_gate_ok: bool,
    market_scan_ok: bool,
    onboarding_ok: bool,
    protocol_lifecycle_ok: bool,
) -> str:
    if not source_downloaded:
        return "install_cli_anything_external_plugin"
    if source_trusted is False:
        return "fix_cli_anything_source_provenance"
    if not entrypoint_available:
        return "repair_or_reinstall_cli_hub_entrypoint"
    if not install_gate_ok:
        return "fix_cli_anything_install_gate"
    if not market_scan_ok:
        return "inspect_cli_hub_market"
    if not onboarding_ok:
        return "inspect_harness_onboarding"
    if not protocol_lifecycle_ok:
        return "fix_protocol_lifecycle_suite"
    return "onboard_first_market_harness"


def _bootstrap_stages(
    summary: dict[str, Any],
    harness_name: str,
    query: str | None,
    workflow_path: str,
) -> list[dict[str, Any]]:
    query_arg = query or "<query>"
    return [
        {
            "id": "preflight",
            "title": "Preflight CLI-Anything Plugin",
            "status": "complete" if summary["install_gate_ok"] else "blocked",
            "ready": bool(summary["install_gate_ok"]),
            "command": "python -m cbn plugin preflight cli-anything",
        },
        {
            "id": "download_plugin",
            "title": "Download External Plugin Source",
            "status": "complete" if summary["source_downloaded"] else "next",
            "ready": bool(summary["install_gate_ok"]),
            "command": "python -m cbn plugin install cli-anything --yes",
        },
        {
            "id": "verify_provenance",
            "title": "Verify Source And Entrypoint Provenance",
            "status": (
                "complete"
                if summary["source_trusted"] is not False and summary["entrypoint_available"]
                else "blocked"
                if summary["source_trusted"] is False
                else "pending"
            ),
            "ready": bool(summary["source_downloaded"]),
            "command": "python -m cbn plugin provenance cli-anything",
        },
        {
            "id": "check_updates",
            "title": "Check External Plugin Updates",
            "status": "ready" if summary["source_downloaded"] else "pending",
            "ready": bool(summary["source_downloaded"]),
            "command": "python -m cbn plugin check-update cli-anything --remote",
        },
        {
            "id": "sync_market",
            "title": "Inspect CLI-Anything Market",
            "status": (
                "complete"
                if summary["market_scan_ok"]
                else "pending"
                if summary["market_scan_skipped"]
                else "blocked"
            ),
            "ready": bool(summary["entrypoint_available"]),
            "command": f"python -m cbn plugin candidates cli-anything --query {query_arg} --limit 10 --with-probes --compact",
        },
        {
            "id": "onboard_harness",
            "title": "Onboard First Market Harness",
            "status": "ready" if summary["onboarding_ok"] else "blocked",
            "ready": bool(summary["entrypoint_available"] and summary["market_scan_ok"]),
            "command": f"python -m cbn plugin onboard-harness cli-anything {harness_name} --from-market",
        },
        {
            "id": "protocol_lifecycle",
            "title": "Run Local Protocol Lifecycle Gate",
            "status": "complete" if summary["protocol_lifecycle_ok"] else "blocked",
            "ready": True,
            "command": f"python -m cbn protocol lifecycle-suite --capability-id git.version --workflow-path {workflow_path}",
        },
    ]


def _load_manifest_registry(path: Path) -> ManifestRegistry:
    registry = ManifestRegistry()
    registry.load_dir(path)
    return registry


def _clip_text(value: str | None, limit: int) -> str:
    text = value or ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...<truncated>"


def _safe_plugin_report(builder: Any) -> dict[str, Any]:
    try:
        return builder()
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
        }


def _harness_live_summary(report: dict[str, Any]) -> dict[str, Any]:
    evaluation = report.get("evaluation") if isinstance(report.get("evaluation"), dict) else {}
    gates = evaluation.get("gates") if isinstance(evaluation.get("gates"), dict) else {}
    parser_contract = report.get("parser_contract") if isinstance(report.get("parser_contract"), dict) else {}
    smoke_suite = report.get("protocol_smoke_suite") if isinstance(report.get("protocol_smoke_suite"), dict) else {}
    return {
        "harness_name": report.get("harness_name"),
        "capability_id": report.get("capability_id"),
        "ok": bool(report.get("ok")),
        "ready_for_manifest_write": bool(report.get("ready_for_manifest_write")),
        "ready_for_runtime_verification": bool(report.get("ready_for_runtime_verification")),
        "verification_blockers": report.get("verification_blockers", []),
        "readiness_ready": bool((report.get("readiness") or {}).get("ready")),
        "manifest_imported": bool(gates.get("manifest_imported")),
        "installed": bool(gates.get("installed")),
        "entrypoint_available": bool((evaluation.get("status") or {}).get("entrypoint_available")),
        "launch_ready": bool(gates.get("launch_ready")),
        "parser_ref": parser_contract.get("parser_ref"),
        "parser_verified": bool(parser_contract.get("verified")),
        "protocol_smoke_suite_run": bool(smoke_suite.get("run")),
        "protocol_smoke_suite_ok": smoke_suite.get("ok"),
        "protocol_wire_compatible": any(
            protocol.get("wire_compatible")
            for protocol in (report.get("protocols") or {}).values()
            if isinstance(protocol, dict)
        ),
    }


def _candidate_live_summary(candidates: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": bool(candidates.get("ok")),
        "query": candidates.get("query"),
        "market_count": candidates.get("market_count"),
        "evaluated_count": candidates.get("evaluated_count"),
        "selected_count": candidates.get("selected_count"),
        "install_candidate_count": candidates.get("install_candidate_count"),
        "blocked_count": candidates.get("blocked_count"),
        "probe_ready_count": candidates.get("probe_ready_count"),
        "probe_blocked_count": candidates.get("probe_blocked_count"),
        "candidate_summary": candidates.get("candidate_summary", []),
        "market": candidates.get("market"),
    }


def _workflow_live_summary(workflow_readiness: dict[str, Any]) -> dict[str, Any]:
    readiness = workflow_readiness.get("readiness") if isinstance(workflow_readiness.get("readiness"), dict) else {}
    summary = workflow_readiness.get("summary") if isinstance(workflow_readiness.get("summary"), dict) else {}
    return {
        "ok": bool(workflow_readiness.get("ok")),
        "workflow_path": workflow_readiness.get("workflow_path"),
        "route_count": summary.get("route_count"),
        "routed_workflow_count": summary.get("routed_workflow_count"),
        "internal_bridge_ready": readiness.get("internal_bridge_ready"),
        "external_protocol_wire_compatible": readiness.get("external_protocol_wire_compatible"),
        "protocol_gaps": workflow_readiness.get("protocol_gaps", {}),
        "next_steps": workflow_readiness.get("next_steps", []),
    }


def _live_verification_summary(
    status: dict[str, Any],
    environment: dict[str, Any],
    harness_summary: list[dict[str, Any]],
    candidates: dict[str, Any] | None,
    workflow_readiness: dict[str, Any] | None,
) -> dict[str, Any]:
    workflow_gate = None
    if workflow_readiness is not None:
        readiness = workflow_readiness.get("readiness") if isinstance(workflow_readiness.get("readiness"), dict) else {}
        workflow_gate = readiness.get("internal_bridge_ready")
    return {
        "entrypoint_available": bool(status.get("entrypoint_available")),
        "source_trusted": environment.get("source_trusted"),
        "ready_for_update": environment.get("ready_for_update"),
        "harness_count": len(harness_summary),
        "verified_harness_count": sum(
            1
            for item in harness_summary
            if item["ok"] and item["ready_for_runtime_verification"]
        ),
        "launch_ready_harness_count": sum(1 for item in harness_summary if item["launch_ready"]),
        "unverified_parser_count": sum(1 for item in harness_summary if not item["parser_verified"]),
        "protocol_smoke_suite_run_count": sum(1 for item in harness_summary if item["protocol_smoke_suite_run"]),
        "protocol_smoke_suite_passed_count": sum(
            1
            for item in harness_summary
            if item["protocol_smoke_suite_run"] and item["protocol_smoke_suite_ok"]
        ),
        "candidate_query": candidates.get("query") if candidates else None,
        "candidate_market_count": candidates.get("market_count") if candidates else None,
        "candidate_blocked_count": candidates.get("blocked_count") if candidates else None,
        "candidate_install_candidate_count": candidates.get("install_candidate_count") if candidates else None,
        "workflow_internal_bridge_ready": workflow_gate,
        "external_protocol_wire_compatible": bool(
            workflow_readiness
            and (workflow_readiness.get("readiness") or {}).get("external_protocol_wire_compatible")
        ),
    }


def _market_record_identity(item: dict[str, Any]) -> dict[str, str | None]:
    return _market_parts_market_record_identity(item)


def _declared_requires(market_record: dict[str, Any] | None, status: dict[str, Any]) -> str | None:
    return _probe_parts_declared_requires(market_record, status)


def _requirement_assessment(requires: str | None) -> dict[str, Any]:
    return _probe_parts_requirement_assessment(requires)


def _managed_requirement_signals(requires: str) -> list[str]:
    return _probe_parts_managed_requirement_signals(requires)


def _external_app_requirement_signals(requires: str) -> list[str]:
    return _probe_parts_external_app_requirement_signals(requires)


def _platform_assessment(market_record: dict[str, Any] | None, requires: str | None) -> dict[str, Any]:
    return _probe_parts_platform_assessment(market_record, requires)


def _transport_assessment(manifest: dict[str, Any]) -> dict[str, Any]:
    transport = manifest.get("spec", {}).get("transport", {})
    if not isinstance(transport, dict):
        return {
            "kind": None,
            "ready": False,
            "reason": "manifest transport is not an object",
            "backend": None,
            "install_hint": None,
        }
    kind = transport.get("kind")
    if kind == "stdio":
        return {
            "kind": "stdio",
            "ready": True,
            "reason": "stdio transport is available",
            "backend": "subprocess",
            "install_hint": None,
        }
    if kind == "pty":
        status = pty_backend_status()
        ready = bool(status["available"])
        return {
            "kind": "pty",
            "ready": ready,
            "reason": "pty transport is available" if ready else "pty transport backend is missing",
            "backend": status.get("backend"),
            "platform": status.get("platform"),
            "install_hint": status.get("install_hint"),
        }
    return {
        "kind": kind,
        "ready": False,
        "reason": f"unsupported transport kind: {kind}",
        "backend": None,
        "install_hint": None,
    }


def _market_runtime_text(market_record: dict[str, Any]) -> str:
    return _manifest_factory_market_runtime_text(market_record)


def _has_local_network_signal(text: str) -> bool:
    return _manifest_factory_has_local_network_signal(text)


def _has_external_network_signal(text: str) -> bool:
    return _manifest_factory_has_external_network_signal(text)


def _has_write_workspace_signal(text: str) -> bool:
    return _manifest_factory_has_write_workspace_signal(text)


def _max_risk(left: str, right: str) -> str:
    return _manifest_factory_max_risk(left, right)


def _lifecycle_report(
    harness_name: str,
    capability_id: str | None,
    recommended_next_action: str,
    gates: dict[str, Any],
    blockers: list[str],
    install_candidate: bool,
) -> dict[str, Any]:
    blocked = bool(blockers)
    manifest_imported = bool(gates.get("manifest_imported", False))
    installed = bool(gates.get("installed", False))
    launch_ready = bool(gates.get("launch_ready", False))
    runtime_transport_ready = bool(gates.get("runtime_transport_ready", True))
    ready_for_install = bool(install_candidate and not installed and not blocked)
    requires_override = blocked or not bool(gates.get("external_dependency_free", True))
    if launch_ready:
        state = "launch_ready"
    elif installed and manifest_imported and not runtime_transport_ready:
        state = "runtime_transport_missing"
    elif blocked:
        state = "blocked"
    elif installed and not manifest_imported:
        state = "installed_needs_manifest"
    elif installed:
        state = "installed"
    elif manifest_imported and ready_for_install:
        state = "manifest_ready"
    elif install_candidate:
        state = "market_candidate"
    else:
        state = "needs_review"

    stages = [
        {
            "id": "evaluate",
            "status": "completed",
            "command": f"python -m cbn plugin evaluate-harness cli-anything {harness_name}",
        },
        {
            "id": "write_manifest",
            "status": _stage_status(
                done=manifest_imported,
                ready=recommended_next_action == "write_manifest" and not blocked,
                blocked=blocked,
            ),
            "command": f"python -m cbn plugin adapt-harness cli-anything {harness_name} --from-market --write",
        },
        {
            "id": "install_harness",
            "status": _stage_status(
                done=installed,
                ready=recommended_next_action == "install_harness" and not blocked,
                blocked=blocked,
            ),
            "command": f"python -m cbn plugin harness cli-anything install {harness_name} --yes",
        },
        {
            "id": "dry_run_call",
            "status": _stage_status(
                done=False,
                ready=manifest_imported,
                blocked=blocked or not capability_id,
            ),
            "command": f"python -m cbn call {capability_id} --dry-run" if capability_id else None,
        },
    ]
    return {
        "state": state,
        "recommended_next_action": recommended_next_action,
        "blocked": blocked,
        "requires_override": requires_override,
        "ready_for_install": ready_for_install,
        "ready_for_call": launch_ready,
        "blockers": blockers,
        "stages": stages,
    }


def _stage_status(done: bool, ready: bool, blocked: bool) -> str:
    if done:
        return "completed"
    if blocked:
        return "blocked"
    if ready:
        return "ready"
    return "pending"


def _dependency_probes(requires: str | None, entry_point: Any) -> list[dict[str, Any]]:
    return _probe_parts_dependency_probes(requires, entry_point)


def _requirement_commands(requirement: str) -> list[str]:
    return _probe_parts_requirement_commands(requirement)


def _requirement_env_vars(requirement: str) -> list[str]:
    return _probe_parts_requirement_env_vars(requirement)


def _requirement_localhost_ports(requirement: str) -> list[tuple[str, int]]:
    return _probe_parts_requirement_localhost_ports(requirement)


def _localhost_port_available(host: str, port: int) -> bool:
    return _probe_parts_localhost_port_available(host, port)


def _requires_manual_account_or_key(requirement: str) -> bool:
    return _probe_parts_requires_manual_account_or_key(requirement)


def _known_parser_refs() -> set[str]:
    return {item["parser_ref"] for item in ParserRegistry.builtins().list()}
