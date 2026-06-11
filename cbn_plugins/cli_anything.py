"""CLI-Anything / CLI-Hub integration helpers.

This module intentionally treats CLI-Anything as an external plugin. It never
vendors upstream code; it only detects `cli-hub`, calls it when available, and
generates CBN manifests for installed or planned harnesses.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
from cbn_plugins.cli_anything_parts import module_split_report as _parts_module_split_report
from cbn_plugins.cli_anything_parts.adaptation import (
    adaptation_gate_repair_scan_decision as _adaptation_gate_repair_scan_decision,
    adaptation_gate_stages as _adaptation_gate_stages,
    adaptation_gate_summary as _adaptation_gate_summary,
    adaptation_queue_summary as _adaptation_queue_summary,
    harnesses_from_install_queue as _harnesses_from_install_queue,
    unique_harnesses as _unique_harnesses,
)
from cbn_plugins.cli_anything_parts.adapter_targets import (
    adapter_target_package_report as _adapter_target_package_report,
    adapter_target_smoke_execution as _adapter_target_smoke_execution,
    adapter_target_smoke_next_action as _adapter_target_smoke_next_action,
    repair_entrypoint_smoke_gate as _repair_entrypoint_smoke_gate,
)
from cbn_plugins.cli_anything_parts.manifest_factory import (
    build_harness_manifest,
    infer_market_policy as _manifest_factory_infer_market_policy,
    preserve_existing_parser_contract as _preserve_existing_parser_contract,
    sanitize_harness_name as _manifest_factory_sanitize_harness_name,
)
from cbn_plugins.cli_anything_parts.market import (
    is_installed_status as _is_installed_status,
    mark_candidate_collisions as _mark_candidate_collisions,
    market_records_from_result as _market_records_from_result,
    matches_sanitized_name as _matches_sanitized_name,
    parse_info_fields as _parse_info_fields,
)
from cbn_plugins.cli_anything_parts.lifecycle import (
    attach_candidate_readiness as _attach_candidate_readiness,
    declared_requires as _declared_requires,
    dependency_probes as _dependency_probes,
    external_app_requirement_signals as _external_app_requirement_signals,
    has_external_network_signal as _has_external_network_signal,
    has_local_network_signal as _has_local_network_signal,
    has_write_workspace_signal as _has_write_workspace_signal,
    lifecycle_report as _lifecycle_report,
    localhost_port_available as _localhost_port_available,
    managed_requirement_signals as _managed_requirement_signals,
    market_record_identity as _market_record_identity,
    market_runtime_text as _market_runtime_text,
    platform_assessment as _platform_assessment,
    readiness_from_evaluation as _readiness_from_evaluation,
    readiness_summary as _readiness_summary,
    refresh_candidate_lifecycle as _refresh_candidate_lifecycle,
    requirement_assessment as _requirement_assessment,
    requirement_commands as _requirement_commands,
    requirement_env_vars as _requirement_env_vars,
    requirement_localhost_ports as _requirement_localhost_ports,
    requires_manual_account_or_key as _requires_manual_account_or_key,
    transport_assessment as _transport_assessment,
)
from cbn_plugins.cli_anything_parts.live import (
    candidate_live_summary as _candidate_live_summary,
    harness_live_summary as _harness_live_summary,
    live_verification_summary as _live_verification_summary,
    workflow_live_summary as _workflow_live_summary,
)
from cbn_plugins.cli_anything_parts.onboarding import (
    onboarding_next_commands as _onboarding_parts_next_commands,
    onboarding_stage_results as _onboarding_parts_stage_results,
    onboarding_summary as _onboarding_parts_summary,
    probe_blocked_onboarding_report as _onboarding_parts_probe_blocked_report,
)
from cbn_plugins.cli_anything_parts.planning import (
    bootstrap_plan as _planning_bootstrap_plan,
    mvp_plan as _planning_mvp_plan,
)
from cbn_plugins.cli_anything_parts.queue import (
    blocked_entry_from_evaluation as _blocked_entry_from_evaluation,
    blocked_harness_decision as _blocked_harness_decision,
    candidate_summary as _candidate_summary,
    install_queue_blocked_entry as _install_queue_blocked_entry,
    install_queue_entry as _install_queue_entry,
    install_queue_skipped_entry as _install_queue_skipped_entry,
    market_command_payload as _market_command_payload,
)
from cbn_plugins.cli_anything_parts.promotion import (
    promotion_blockers as _promotion_blockers,
    promotion_requirements as _promotion_requirements,
)
from cbn_plugins.cli_anything_parts.repair import (
    distribution_report as _distribution_report,
    entrypoint_diagnosis as _entrypoint_diagnosis,
    entrypoint_package_candidates as _entrypoint_package_candidates,
    entrypoint_repair_manifest as _entrypoint_repair_manifest,
    entrypoint_repair_manifest_provenance as _entrypoint_repair_manifest_provenance,
    entrypoint_repair_strategy as _entrypoint_repair_strategy,
    entrypoint_wrapper_path as _entrypoint_wrapper_path,
    module_report as _module_report,
    script_path_candidates as _script_path_candidates,
    write_repair_entrypoint_files as _write_repair_entrypoint_files,
)
from cbn_plugins.cli_anything_parts.sync import (
    candidate_from_market_record as _sync_candidate_from_market_record,
    environment_verification as _sync_environment_verification,
    sync_market as _sync_market,
    workflow_readiness as _sync_workflow_readiness,
)
from cbn_plugins.cli_anything_parts.verification import (
    effective_manifest_dict as _effective_manifest_dict,
    harness_protocol_smoke_suite as _harness_protocol_smoke_suite,
    known_parser_refs as _known_parser_refs,
    load_manifest_registry as _load_manifest_registry,
    manifest_has_entrypoint_repair as _manifest_has_entrypoint_repair,
    manifest_dict_from_path as _manifest_dict_from_path,
    mark_repaired_manifest_verified_from_fixtures as _mark_repaired_manifest_verified_from_fixtures,
    parser_contract_report_from_registry as _parser_contract_report,
    parser_fixture_gate as _parser_fixture_gate,
    protocol_verification_summary as _protocol_verification_summary,
    registry_source_for_manifest as _registry_source_for_manifest,
    verification_blockers as _verification_blockers,
    verification_stages as _verification_stages,
    workflow_matches_for_capability as _workflow_matches_for_capability,
)
from cbn_protocol.compatibility import check_all_protocols
from cbn_protocol.readiness import protocol_readiness_report


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
            "module_split": _parts_module_split_report(facade_path=Path(__file__)),
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
            if _matches_sanitized_name(item.get("name"), safe_name, sanitize_harness_name):
                return item
        for item in candidates:
            if _matches_sanitized_name(item.get("display_name"), safe_name, sanitize_harness_name):
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
            manifest = _preserve_existing_parser_contract(
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

        return _planning_mvp_plan(
            self,
            query=query,
            limit=limit,
            max_harnesses=max_harnesses,
            include_blocked=include_blocked,
            workflow_paths=workflow_paths,
            max_workflows=max_workflows,
            registry=registry,
            workflow_runner=workflow_runner,
        )

    def bootstrap_plan(
        self,
        harness_name: str = "mermaid",
        query: str | None = "file",
        include_workflows: bool = True,
        workflow_path: str = "workflows/cli-anything-macrocli-mermaid-routing.example.json",
    ) -> dict[str, Any]:
        """Return the read-only bootstrap runbook for installing CLI-Anything."""

        return _planning_bootstrap_plan(
            self,
            harness_name=harness_name,
            query=query,
            include_workflows=include_workflows,
            workflow_path=workflow_path,
        )

    def _environment_verification(self) -> dict[str, Any]:
        return _sync_environment_verification(self.paths.root)

    def _workflow_readiness(self, workflow_path: str) -> dict[str, Any] | None:
        return _sync_workflow_readiness(self.paths, workflow_path)

    def _candidate_from_market_record(
        self,
        record: dict[str, Any],
        market_index: int,
    ) -> dict[str, Any]:
        return _sync_candidate_from_market_record(self, record, market_index)

    def sync_market(
        self,
        query: str | None = None,
        limit: int = 50,
        write: bool = False,
    ) -> dict[str, Any]:
        return _sync_market(self, query=query, limit=limit, write=write)

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


def infer_market_policy(
    market_record: dict[str, Any] | None,
    requested_risk: str = "read",
) -> dict[str, Any]:
    return _manifest_factory_infer_market_policy(market_record, requested_risk=requested_risk)
