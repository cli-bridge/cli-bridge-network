"""CLI-Anything / CLI-Hub integration helpers.

This module intentionally treats CLI-Anything as an external plugin. It never
vendors upstream code; it only detects `cli-hub`, calls it when available, and
generates CBN manifests for installed or planned harnesses.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cbn.paths import resolve_project_paths
from cbn_audit.log import AuditLog
from cbn_artifacts.store import ArtifactStore
from cbn_core.manifest import ManifestRegistry, validate_manifest_dict
from cbn_events.bus import EventBus
from cbn_plugins.manager import (
    PluginCommand,
    PluginManager,
    PluginPlan,
    verification_report_for_plan,
)
from cbn_plugins.operations import PluginOperationRunner
from cbn_plugins.cli_anything_parts import module_split_report as _parts_module_split_report
from cbn_plugins.cli_anything_parts.adaptation import (
    adaptation_gate as _adaptation_parts_adaptation_gate,
    adaptation_queue as _adaptation_parts_adaptation_queue,
)
from cbn_plugins.cli_anything_parts.adapter_targets import (
    adapter_target_package_report as _adapter_target_package_report,
    adapter_target_smoke as _adapter_targets_parts_adapter_target_smoke,
    adapter_targets as _adapter_targets_parts_adapter_targets,
)
from cbn_plugins.cli_anything_parts.manifest_factory import (
    build_harness_manifest,
    infer_market_policy as _manifest_factory_infer_market_policy,
    preserve_existing_parser_contract as _preserve_existing_parser_contract,
    sanitize_harness_name as _manifest_factory_sanitize_harness_name,
)
from cbn_plugins.cli_anything_parts.market import (
    is_installed_status as _is_installed_status,
    matches_sanitized_name as _matches_sanitized_name,
    parse_info_fields as _parse_info_fields,
)
from cbn_plugins.cli_anything_parts.lifecycle import (
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
    requirement_assessment as _requirement_assessment,
    requirement_commands as _requirement_commands,
    requirement_env_vars as _requirement_env_vars,
    requirement_localhost_ports as _requirement_localhost_ports,
    requires_manual_account_or_key as _requires_manual_account_or_key,
    transport_assessment as _transport_assessment,
)
from cbn_plugins.cli_anything_parts.live import (
    live_verification as _live_parts_live_verification,
)
from cbn_plugins.cli_anything_parts.onboarding import (
    onboard_harness as _onboarding_parts_onboard_harness,
)
from cbn_plugins.cli_anything_parts.planning import (
    bootstrap_plan as _planning_bootstrap_plan,
    mvp_plan as _planning_mvp_plan,
)
from cbn_plugins.cli_anything_parts.queue import (
    blocked_harness_plan as _queue_parts_blocked_harness_plan,
    candidate_harnesses as _queue_parts_candidate_harnesses,
    market_install_queue as _queue_parts_market_install_queue,
)
from cbn_plugins.cli_anything_parts.promotion import (
    promotion_gate as _promotion_parts_promotion_gate,
)
from cbn_plugins.cli_anything_parts.repair import (
    module_report as _module_report,
    entrypoint_repair_plan as _repair_parts_entrypoint_repair_plan,
    repair_entrypoint as _repair_parts_repair_entrypoint,
)
from cbn_plugins.cli_anything_parts.sync import (
    candidate_from_market_record as _sync_candidate_from_market_record,
    environment_verification as _sync_environment_verification,
    sync_market as _sync_market,
    workflow_readiness as _sync_workflow_readiness,
)
from cbn_plugins.cli_anything_parts.verification import (
    known_parser_refs as _known_parser_refs,
    load_manifest_registry as _load_manifest_registry,
    manifest_dict_from_path as _manifest_dict_from_path,
    mark_repaired_manifest_verified_from_fixtures as _mark_repaired_manifest_verified_from_fixtures,
    verify_harness as _verification_parts_verify_harness,
)


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
        return _verification_parts_verify_harness(
            self,
            title=title,
            harness_name=harness_name,
            from_market=from_market,
            include_workflows=include_workflows,
            run_smoke_suite=run_smoke_suite,
            smoke_extra_args=smoke_extra_args,
        )

    def promotion_gate(
        self,
        harness_name: str,
        title: str | None = None,
        from_market: bool = True,
        include_workflows: bool = True,
        run_smoke_suite: bool = False,
        smoke_extra_args: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        return _promotion_parts_promotion_gate(
            self,
            harness_name=harness_name,
            title=title,
            from_market=from_market,
            include_workflows=include_workflows,
            run_smoke_suite=run_smoke_suite,
            smoke_extra_args=smoke_extra_args,
        )

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
        return _onboarding_parts_onboard_harness(
            self,
            title=title,
            harness_name=harness_name,
            from_market=from_market,
            include_workflows=include_workflows,
            run_smoke_suite=run_smoke_suite,
            smoke_extra_args=smoke_extra_args,
            write=write,
            confirmed=confirmed,
            install=install,
            allow_blocked=allow_blocked,
            operation_runner=operation_runner,
        )

    def candidate_harnesses(
        self,
        query: str | None = None,
        limit: int = 50,
        with_probes: bool = False,
        compact: bool = False,
    ) -> dict[str, Any]:
        return _queue_parts_candidate_harnesses(
            self,
            query=query,
            limit=limit,
            with_probes=with_probes,
            compact=compact,
        )

    def market_install_queue(
        self,
        query: str | None = None,
        limit: int = 50,
        max_installs: int = 10,
        include_blocked: bool = True,
    ) -> dict[str, Any]:
        return _queue_parts_market_install_queue(
            self,
            query=query,
            limit=limit,
            max_installs=max_installs,
            include_blocked=include_blocked,
        )

    def blocked_harness_plan(
        self,
        harnesses: tuple[str, ...] = (),
        query: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        return _queue_parts_blocked_harness_plan(
            self,
            harnesses=harnesses,
            query=query,
            limit=limit,
        )

    def entrypoint_repair_plan(
        self,
        harness_name: str,
        from_market: bool = True,
    ) -> dict[str, Any]:
        return _repair_parts_entrypoint_repair_plan(
            self,
            harness_name=harness_name,
            from_market=from_market,
        )

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
        return _repair_parts_repair_entrypoint(
            self,
            harness_name=harness_name,
            from_market=from_market,
            module=module,
            write=write,
            confirmed=confirmed,
            require_smoke=require_smoke,
            smoke_args=smoke_args,
            smoke_timeout_seconds=smoke_timeout_seconds,
        )

    def adapter_targets(
        self,
        harness_name: str,
        from_market: bool = True,
        package: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        return _adapter_targets_parts_adapter_targets(
            self,
            harness_name=harness_name,
            from_market=from_market,
            package=package,
            limit=limit,
        )

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
        return _adapter_targets_parts_adapter_target_smoke(
            self,
            harness_name=harness_name,
            module=module,
            from_market=from_market,
            smoke_args=smoke_args,
            timeout_seconds=timeout_seconds,
            run=run,
            confirmed=confirmed,
        )

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
        return _adaptation_parts_adaptation_gate(
            self,
            harness_name=harness_name,
            from_market=from_market,
            module=module,
            require_smoke=require_smoke,
            run_smoke=run_smoke,
            confirmed=confirmed,
            smoke_args=smoke_args,
            smoke_timeout_seconds=smoke_timeout_seconds,
        )

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
        return _adaptation_parts_adaptation_queue(
            self,
            harnesses=harnesses,
            query=query,
            limit=limit,
            max_harnesses=max_harnesses,
            include_blocked=include_blocked,
            require_smoke=require_smoke,
            run_smoke=run_smoke,
            confirmed=confirmed,
            smoke_args=smoke_args,
            smoke_timeout_seconds=smoke_timeout_seconds,
        )

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

        return _live_parts_live_verification(
            self,
            harnesses=harnesses,
            candidate_query=candidate_query,
            candidate_limit=candidate_limit,
            include_candidates=include_candidates,
            include_workflows=include_workflows,
            run_smoke_suite=run_smoke_suite,
            smoke_extra_args=smoke_extra_args,
        )

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
