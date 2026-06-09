"""CLI-Anything / CLI-Hub integration helpers.

This module intentionally treats CLI-Anything as an external plugin. It never
vendors upstream code; it only detects `cli-hub`, calls it when available, and
generates CBN manifests for installed or planned harnesses.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adapters.pty import pty_backend_status
from cbn.paths import resolve_project_paths
from cbn_core.manifest import CapabilityManifest, ManifestRegistry, validate_manifest_dict
from cbn_parsers.registry import ParserRegistry
from cbn_plugins.manager import PluginCommand, PluginManager, PluginPlan
from cbn_protocol.compatibility import check_all_protocols
from cbn_protocol.readiness import protocol_readiness_report
from cbn_protocol.smoke_suite import protocol_smoke_suite
from cbn_workflow.catalog import list_workflows


PLUGIN_ID = "cli-anything"
MARKET_LABEL_KEYS = ("category", "_source", "package_manager", "platform")
MARKET_ANNOTATION_KEYS = (
    "display_name",
    "version",
    "description",
    "requires",
    "homepage",
    "docs_url",
    "source_url",
    "install_cmd",
    "update_cmd",
    "uninstall_cmd",
    "entry_point",
    "skill_md",
    "npm_package",
    "npx_cmd",
    "contributors",
)
RISK_ORDER = ("read", "write-workspace", "external-network", "privileged")
RUNTIME_TEXT_KEYS = ("description", "requires")
LOCAL_NETWORK_MARKERS = (
    "localhost",
    "127.0.0.1",
    "::1",
)
EXTERNAL_NETWORK_MARKERS = (
    "api key",
    "apikey",
    "access token",
    "auth token",
    "bearer token",
    "google_cloud_project",
    "gemini_api_key",
    "openai_api_key",
    "anthropic_api_key",
    "vertex ai",
    "gemini",
    "openai",
    "anthropic",
    "replicate",
    "huggingface",
    "cloud",
)
WRITE_WORKSPACE_MARKERS = (
    "generate",
    "generation",
    "export",
    "convert",
    "transcode",
    "render",
    "edit",
    "image",
    "video",
    "svg",
    "raster",
    "painting",
)


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
    def __init__(self, root: Path | None = None, entrypoint: str = "cli-hub") -> None:
        self.paths = resolve_project_paths(root)
        self.entrypoint = entrypoint

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
        market_record = market_record or {}
        market_name = str(market_record.get("name") or harness_name)
        display_name = str(market_record.get("display_name") or market_name)
        safe_name = sanitize_harness_name(market_name)
        capability_id = f"cli-anything.{safe_name}.launch"
        labels = {
            "plugin": PLUGIN_ID,
            "harness": market_name,
        }
        labels.update(_market_labels(market_record))
        annotations = _market_annotations(market_record)
        policy = infer_market_policy(market_record, requested_risk=risk)
        if policy["reasons"]:
            annotations["cli-anything.policy_inference"] = json.dumps(
                policy["reasons"],
                ensure_ascii=False,
                sort_keys=True,
            )
        return {
            "apiVersion": "bridge.dev/v1alpha1",
            "kind": "ToolManifest",
            "metadata": {
                "id": capability_id,
                "title": title or f"CLI-Anything {display_name}",
                "labels": labels,
                "annotations": annotations,
            },
            "spec": {
                "transport": {
                    "kind": "pty",
                    "command": self.entrypoint,
                    "argsTemplate": ["launch", market_name, "--"],
                    "cwdPolicy": "workspace",
                    "timeoutSeconds": 600,
                },
                "policy": {
                    "risk": policy["risk"],
                    "requiresConfirmation": policy["requires_confirmation"],
                    "network": policy["network"],
                },
                "output": {
                    "parserRef": "cli-anything.raw",
                    "verified": False,
                },
            },
        }

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
        install_candidate = (
            gates["cli_hub_available"]
            and gates["market_required_satisfied"]
            and gates["manifest_valid"]
            and gates["low_policy_risk"]
            and gates["external_dependency_free"]
            and gates["platform_compatible"]
        )
        if gates["launch_ready"]:
            recommended_next_action = "call_capability"
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
            "manifest_path": adaptation["manifest_path"],
            "protocol_check_source": "current_registry" if imported_manifest else "generated_preview",
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
            return {
                "ok": False,
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
                "error": probe["error"],
                "stage_results": [
                    {
                        "id": "probe",
                        "status": "blocked",
                        "blockers": [probe["error"]],
                    }
                ],
                "reports": {"probe": probe},
                "next_commands": [
                    f"python -m cbn plugin market cli-anything info {harness_name}",
                    f"python -m cbn plugin onboard-harness cli-anything {harness_name} --offline",
                ],
            }

        evaluation = probe["evaluation"]
        capability_id = evaluation["capability_id"]
        adaptation = evaluation["adaptation"]
        write_requested_without_confirmation = bool(write and not confirmed)
        install_requested_without_confirmation = bool(install and not confirmed)
        if write and confirmed:
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
        stage_results = [
            {
                "id": "evaluate",
                "status": "completed",
                "blockers": evaluation["blockers"],
                "recommended_next_action": evaluation["recommended_next_action"],
            },
            {
                "id": "probe_dependencies",
                "status": "completed" if probe["ready"] else "blocked",
                "blockers": [
                    item["id"]
                    for item in probe["probes"]
                    if item.get("severity") == "blocker" and item.get("status") != "available"
                ],
            },
            {
                "id": "adapt_manifest",
                "status": (
                    "completed"
                    if manifest_written or manifest_already_imported
                    else "ready"
                    if ready_for_manifest_write
                    else "blocked"
                ),
                "write_requested": write,
                "write_confirmed": confirmed,
                "written": adaptation.get("written"),
                "blockers": [] if ready_for_manifest_write else evaluation["blockers"],
            },
            {
                "id": "install_harness",
                "status": (
                    "completed"
                    if harness_already_installed or install_execution_status == "completed"
                    else "blocked"
                    if install_execution_status == "blocked"
                    else "ready"
                    if ready_for_install
                    else "blocked"
                ),
                "execution": install_execution_status,
                "install_requested": install,
                "allow_blocked": allow_blocked,
                "blockers": install_execution_blockers or install_gate.get("blockers", []),
            },
            {
                "id": "verify_runtime",
                "status": "completed" if ready_for_runtime_verification else "blocked",
                "blockers": verification_blockers,
            },
            {
                "id": "smoke_protocol_facades",
                "status": (
                    "completed"
                    if smoke_suite.get("run") and smoke_suite.get("ok")
                    else "blocked"
                    if smoke_suite.get("run")
                    else "pending"
                ),
                "run": bool(smoke_suite.get("run")),
                "blockers": [] if smoke_suite.get("ok") or not smoke_suite.get("run") else ["protocol smoke suite failed"],
            },
        ]
        next_commands = [
            f"python -m cbn plugin onboard-harness cli-anything {harness_name} --from-market",
            f"python -m cbn plugin onboard-harness cli-anything {harness_name} --from-market --write --yes",
            f"python -m cbn plugin harness cli-anything install {harness_name} --yes",
            "python -m cbn registry validate manifests",
            f"python -m cbn plugin verify-harness cli-anything {harness_name} --smoke-suite --smoke-extra-arg=--help --no-workflows",
            f"python -m cbn call {capability_id} --dry-run",
        ]
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
            "summary": {
                "ready_for_manifest_write": ready_for_manifest_write,
                "manifest_written": manifest_written,
                "write_requires_confirmation": write_requested_without_confirmation,
                "ready_for_install": ready_for_install,
                "install_requires_confirmation": install_requested_without_confirmation,
                "install_executed": install_execution_status == "completed",
                "install_execution_status": install_execution_status,
                "ready_for_runtime_verification": ready_for_runtime_verification,
                "smoke_suite_ready": bool(smoke_suite.get("ok")) if smoke_suite.get("run") else None,
                "recommended_next_action": evaluation["recommended_next_action"],
            },
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
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", name.strip()).strip("-._")
    if not normalized:
        raise ValueError("harness name cannot be empty")
    return normalized.lower()


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
    labels = {}
    for key in MARKET_LABEL_KEYS:
        value = market_record.get(key)
        if value is None or value == "":
            continue
        labels[key.strip("_")] = str(value)
    return labels


def _market_annotations(market_record: dict[str, Any]) -> dict[str, str]:
    annotations = {}
    for key in MARKET_ANNOTATION_KEYS:
        value = market_record.get(key)
        if value is None or value == "":
            continue
        annotation_key = f"cli-anything.{key}"
        if isinstance(value, (dict, list)):
            annotations[annotation_key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
        else:
            annotations[annotation_key] = str(value)
    return annotations


def infer_market_policy(
    market_record: dict[str, Any] | None,
    requested_risk: str = "read",
) -> dict[str, Any]:
    risk = requested_risk
    network = "deny"
    reasons: list[str] = []
    if market_record:
        runtime_text = _market_runtime_text(market_record)
        if _has_local_network_signal(runtime_text):
            network = "localhost"
            reasons.append("runtime mentions local service or localhost dependency")
        if _has_external_network_signal(runtime_text):
            risk = _max_risk(risk, "external-network")
            network = "requires-confirmation"
            reasons.append("runtime mentions external API, cloud service, token, or API key")
        if _has_write_workspace_signal(runtime_text):
            risk = _max_risk(risk, "write-workspace")
            reasons.append("runtime appears to generate, edit, render, convert, or export artifacts")
    requires_confirmation = risk in {"privileged", "external-network"}
    if risk in {"privileged", "external-network"}:
        network = "requires-confirmation" if risk == "external-network" else network
    return {
        "risk": risk,
        "requires_confirmation": requires_confirmation,
        "network": network,
        "reasons": reasons,
    }


def _market_records_from_result(parsed_json: Any) -> list[dict[str, Any]] | None:
    if isinstance(parsed_json, list):
        records = parsed_json
    elif isinstance(parsed_json, dict):
        records = None
        for key in ("items", "harnesses", "tools", "results", "data"):
            value = parsed_json.get(key)
            if isinstance(value, list):
                records = value
                break
        if records is None:
            return None
    else:
        return None
    return [item for item in records if isinstance(item, dict)]


def _mark_capability_collisions(manifests: list[dict[str, Any]]) -> None:
    by_id: dict[str, list[dict[str, Any]]] = {}
    for item in manifests:
        capability_id = item.get("capability_id")
        if isinstance(capability_id, str) and capability_id:
            by_id.setdefault(capability_id, []).append(item)
    for capability_id, matches in by_id.items():
        if len(matches) < 2:
            continue
        sources = [_market_record_identity(item) for item in matches]
        for item in matches:
            item["ok"] = False
            item["error"] = "duplicate capability_id generated from market records"
            item["collision"] = {
                "capability_id": capability_id,
                "market_records": sources,
            }


def _mark_candidate_collisions(candidates: list[dict[str, Any]]) -> None:
    by_id: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        capability_id = item.get("capability_id")
        if isinstance(capability_id, str) and capability_id:
            by_id.setdefault(capability_id, []).append(item)
    for capability_id, matches in by_id.items():
        if len(matches) < 2:
            continue
        sources = [_market_record_identity(item) for item in matches]
        for item in matches:
            item["install_candidate"] = False
            item["recommended_next_action"] = "resolve_blockers"
            item.setdefault("blockers", []).append("duplicate capability_id generated from market records")
            item["collision"] = {
                "capability_id": capability_id,
                "market_records": sources,
            }


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
    item["readiness"] = _readiness_summary(
        probes=_dependency_probes(
            requires=_declared_requires(record, {}),
            entry_point=record.get("entry_point"),
        ),
        install_candidate=bool(item.get("install_candidate")),
    )


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
    blockers = [
        probe
        for probe in probes
        if probe["status"] in {"missing", "unavailable", "manual_required"}
        and probe["severity"] == "blocker"
    ]
    return {
        "ready": bool(install_candidate) and len(blockers) == 0,
        "probe_blocker_count": len(blockers),
        "probes": probes,
    }


def _parser_contract_report(manifest: dict[str, Any]) -> dict[str, Any]:
    output = manifest.get("spec", {}).get("output", {})
    if not isinstance(output, dict):
        output = {}
    parser_ref = output.get("parserRef") or "raw.text"
    known = parser_ref in _known_parser_refs()
    verified = bool(output.get("verified", False))
    if verified and known:
        status = "verified"
    elif known:
        status = "known_unverified"
    else:
        status = "unknown_parser"
    return {
        "parser_ref": parser_ref,
        "known": known,
        "verified": verified,
        "status": status,
        "next_step": (
            "Add harness-specific parser fixtures and set spec.output.verified=true."
            if not verified
            else "Keep parser fixtures in the release gate."
        ),
    }


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
    existing_output = ((existing.get("spec") or {}).get("output") or {})
    generated_output = ((generated.get("spec") or {}).get("output") or {})
    if (
        existing_output.get("verified") is True
        and existing_output.get("parserRef") == generated_output.get("parserRef")
    ):
        generated_output["verified"] = True
        generated_annotations = generated.setdefault("metadata", {}).setdefault("annotations", {})
        existing_annotations = (existing.get("metadata") or {}).get("annotations") or {}
        for key, value in existing_annotations.items():
            if str(key).startswith("cbn.parser"):
                generated_annotations.setdefault(key, value)
    return generated


def _protocol_verification_summary(protocol_checks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        protocol: {
            "scope": report["scope"],
            "wire_compatible": report["wire_compatible"],
            "status_counts": report["status_counts"],
            "missing": [
                item["requirement"]
                for item in report["checks"]
                if item["status"] == "missing"
            ],
            "partial": [
                item["requirement"]
                for item in report["checks"]
                if item["status"] == "partial"
            ],
            "next_steps": report["next_steps"],
        }
        for protocol, report in protocol_checks.items()
    }


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
    blockers = list(evaluation.get("blockers", []))
    if readiness.get("probe_blocker_count", 0) > 0:
        blockers.append("dependency probes have blocker-level failures")
    if not registry_status.get("manifest_imported"):
        blockers.append("manifest is not imported into manifests/")
    gates = evaluation.get("gates", {})
    if not gates.get("installed"):
        blockers.append("harness is not installed")
    if not gates.get("runtime_transport_ready", True):
        blockers.append("runtime transport is not ready")
    if not gates.get("launch_ready"):
        blockers.append("harness launch is not ready")
    return sorted(set(blockers))


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
    gates = evaluation.get("gates", {})
    dry_run_ready = bool(registry_status.get("manifest_imported"))
    return [
        {
            "id": "evaluate_market_and_policy",
            "status": "completed" if evaluation.get("ok") else "blocked",
            "command": f"python -m cbn plugin evaluate-harness cli-anything {harness_name}",
        },
        {
            "id": "probe_dependencies",
            "status": "completed" if readiness.get("probe_blocker_count") == 0 else "blocked",
            "command": f"python -m cbn plugin probe-harness cli-anything {harness_name}",
        },
        {
            "id": "write_manifest",
            "status": "completed" if registry_status.get("manifest_imported") else "ready",
            "command": f"python -m cbn plugin adapt-harness cli-anything {harness_name} --from-market --write",
        },
        {
            "id": "validate_registry",
            "status": "completed" if gates.get("manifest_valid") else "blocked",
            "command": "python -m cbn registry validate manifests",
        },
        {
            "id": "install_harness",
            "status": "completed" if gates.get("installed") else "pending",
            "command": f"python -m cbn plugin harness cli-anything install {harness_name} --yes",
        },
        {
            "id": "dry_run_call",
            "status": "ready" if dry_run_ready else "blocked",
            "command": f"python -m cbn call {capability_id} --dry-run",
        },
        {
            "id": "verify_parser_contract",
            "status": "completed" if parser_contract.get("verified") else "pending",
            "command": f"python -m cbn parser fixtures --parser-ref {parser_contract.get('parser_ref')}",
        },
        {
            "id": "check_protocol_exports",
            "status": "completed",
            "command": f"python -m cbn protocol check all --capability-id {capability_id}",
            "source": registry_status.get("protocol_check_source"),
            "protocol_status_counts": {
                protocol: report.get("status_counts", {})
                for protocol, report in protocol_checks.items()
            },
        },
        {
            "id": "smoke_protocol_facades",
            "status": _smoke_suite_stage_status(smoke_suite, gates),
            "command": smoke_suite.get("command"),
            "run": bool(smoke_suite.get("run")),
            "ok": smoke_suite.get("ok"),
            "summary": smoke_suite.get("summary"),
            "commands": [
                f"python -m cbn mcp smoke --capability-id {capability_id}",
                f"python -m cbn a2a smoke --capability-id {capability_id}",
                f"python -m cbn acp smoke --capability-id {capability_id}",
            ],
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
    parts = [
        "python",
        "-m",
        "cbn",
        "protocol",
        "smoke-suite",
        "--capability-id",
        capability_id,
    ]
    for extra_arg in extra_args:
        parts.append(f"--extra-arg={extra_arg}")
    for workflow_path in workflow_paths:
        parts.extend(["--workflow-path", workflow_path, "--workflow-dry-run"])
    return " ".join(parts)


def _smoke_suite_stage_status(smoke_suite: dict[str, Any], gates: dict[str, Any]) -> str:
    if smoke_suite.get("run"):
        return "completed" if smoke_suite.get("ok") else "failed"
    return "ready" if gates.get("launch_ready") else "blocked"


def _policy_requires_confirmation(policy: dict[str, Any]) -> bool:
    return bool(policy.get("requiresConfirmation", policy.get("requires_confirmation", False)))


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
    record = item.get("market_record")
    if not isinstance(record, dict):
        record = {}
    return {
        "name": str(record.get("name")) if record.get("name") is not None else None,
        "display_name": str(record.get("display_name")) if record.get("display_name") is not None else None,
        "entry_point": str(record.get("entry_point")) if record.get("entry_point") is not None else None,
        "source": str(record.get("_source")) if record.get("_source") is not None else None,
    }


def _declared_requires(market_record: dict[str, Any] | None, status: dict[str, Any]) -> str | None:
    if market_record and market_record.get("requires") not in {None, ""}:
        return str(market_record["requires"])
    fields = status.get("cli_hub_info", {}).get("fields", {})
    if isinstance(fields, dict) and fields.get("requires") not in {None, ""}:
        return str(fields["requires"])
    return None


def _requirement_assessment(requires: str | None) -> dict[str, Any]:
    if not requires or requires.strip().casefold() in {"none", "nothing", "null", "n/a"}:
        return {
            "declared": requires,
            "external_dependency_free": True,
            "dependency_class": "none",
            "managed_dependency_only": False,
            "manual_dependency_required": False,
            "signals": [],
        }
    text = requires.casefold()
    blocking_markers = (
        "api key",
        "apikey",
        "token",
        "secret",
        "credential",
        "account",
        "auth",
        "desktop app",
        "running",
        "server",
        "instance",
        "localhost",
        "127.0.0.1",
        "licensed",
        "license",
        "installation",
        "apt ",
        "brew ",
        "choco ",
        "winget ",
        "set ",
        "env ",
        "environment variable",
        "extension",
        "login",
    )
    signals = [marker.strip() for marker in blocking_markers if marker in text]
    managed_signals = _managed_requirement_signals(requires)
    if not signals and managed_signals:
        return {
            "declared": requires,
            "external_dependency_free": True,
            "dependency_class": "managed-package",
            "managed_dependency_only": True,
            "manual_dependency_required": False,
            "signals": managed_signals,
        }
    if not signals:
        signals = ["declared requirement"]
    return {
        "declared": requires,
        "external_dependency_free": False,
        "dependency_class": "manual-or-external",
        "managed_dependency_only": False,
        "manual_dependency_required": True,
        "signals": signals,
    }


def _managed_requirement_signals(requires: str) -> list[str]:
    text = requires.casefold().strip()
    if not text:
        return []
    signals: list[str] = []
    if re.search(r"\bpython\s*[0-9><=~.+-]*", text):
        signals.append("python-runtime")
    if re.search(r"\b(node|npm|npx|pnpm|yarn)\b", text):
        signals.append("node-runtime")
    if re.search(r"\b(pip|uv|poetry|pdm)\b", text):
        signals.append("python-package-manager")
    cleaned = re.sub(r"\bpython\s*[0-9><=~.+-]*", "", text)
    cleaned = re.sub(r"\b(node|npm|npx|pnpm|yarn|pip|uv|poetry|pdm)\b", "", cleaned)
    cleaned = re.sub(r"\b(version|package|packages|dependency|dependencies|requires|required)\b", "", cleaned)
    cleaned = re.sub(r"[><=~!^]+", "", cleaned)
    tokens = [
        token.strip()
        for token in re.split(r"[,;\s]+", cleaned)
        if token.strip()
    ]
    package_tokens = [
        token
        for token in tokens
        if re.match(r"^@?[a-z0-9][a-z0-9_.-]*(/[a-z0-9][a-z0-9_.-]*)?$", token)
        and not re.fullmatch(r"\d+(\.\d+)*\+?", token)
    ]
    leftovers = [
        token
        for token in tokens
        if token not in package_tokens and not re.fullmatch(r"\d+(\.\d+)*\+?", token)
    ]
    if package_tokens:
        signals.append("managed-packages")
    if signals and not leftovers:
        return sorted(set(signals))
    return []


def _platform_assessment(market_record: dict[str, Any] | None, requires: str | None) -> dict[str, Any]:
    host_platform = sys.platform
    text = "\n".join(
        str(value)
        for value in (
            (market_record or {}).get("platform"),
            requires,
        )
        if value
    ).casefold()
    incompatible = False
    if "macos" in text or "darwin" in text:
        incompatible = not host_platform.startswith("darwin")
    if "linux" in text and not host_platform.startswith("linux"):
        incompatible = True
    if "windows" in text and not host_platform.startswith("win"):
        incompatible = True
    return {
        "host": host_platform,
        "compatible": not incompatible,
        "signals": text.splitlines(),
    }


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
    values = []
    for key in RUNTIME_TEXT_KEYS:
        value = market_record.get(key)
        if value:
            values.append(str(value))
    return "\n".join(values).casefold()


def _has_local_network_signal(text: str) -> bool:
    return any(marker in text for marker in LOCAL_NETWORK_MARKERS)


def _has_external_network_signal(text: str) -> bool:
    if any(marker in text for marker in EXTERNAL_NETWORK_MARKERS):
        return True
    for match in re.findall(r"https?://[^\s)]+", text):
        if not any(local in match for local in LOCAL_NETWORK_MARKERS):
            return True
    return False


def _has_write_workspace_signal(text: str) -> bool:
    return any(marker in text for marker in WRITE_WORKSPACE_MARKERS)


def _max_risk(left: str, right: str) -> str:
    try:
        left_rank = RISK_ORDER.index(left)
        right_rank = RISK_ORDER.index(right)
    except ValueError as exc:
        raise ValueError(f"unknown risk level for CLI-Anything policy inference: {exc}") from exc
    return left if left_rank >= right_rank else right


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
    probes: list[dict[str, Any]] = []
    requirement = (requires or "").strip()
    assessment = _requirement_assessment(requirement)
    if assessment["external_dependency_free"]:
        probes.append(
            {
                "id": "declared-requirements",
                "kind": "requirements",
                "status": "satisfied",
                "severity": "info",
                "detail": requirement or "no declared requirements",
                "dependency_class": assessment["dependency_class"],
                "signals": assessment["signals"],
            }
        )
    else:
        probes.append(
            {
                "id": "declared-requirements",
                "kind": "requirements",
                "status": "declared",
                "severity": "blocker",
                "detail": requirement,
                "dependency_class": assessment["dependency_class"],
                "signals": assessment["signals"],
            }
        )

    for command in _requirement_commands(requirement):
        path = shutil.which(command)
        probes.append(
            {
                "id": f"command:{command}",
                "kind": "command",
                "name": command,
                "status": "available" if path else "missing",
                "severity": "info" if path else "blocker",
                "path": path,
            }
        )

    if isinstance(entry_point, str) and entry_point:
        path = shutil.which(entry_point)
        probes.append(
            {
                "id": f"entrypoint:{entry_point}",
                "kind": "entrypoint",
                "name": entry_point,
                "status": "available" if path else "missing",
                "severity": "info" if path else "warning",
                "path": path,
            }
        )

    for env_name in _requirement_env_vars(requirement):
        present = bool(os.environ.get(env_name))
        probes.append(
            {
                "id": f"env:{env_name}",
                "kind": "env",
                "name": env_name,
                "status": "available" if present else "missing",
                "severity": "info" if present else "blocker",
            }
        )

    for host, port in _requirement_localhost_ports(requirement):
        available = _localhost_port_available(host, port)
        probes.append(
            {
                "id": f"localhost:{host}:{port}",
                "kind": "localhost",
                "host": host,
                "port": port,
                "status": "available" if available else "unavailable",
                "severity": "info" if available else "blocker",
            }
        )

    if _requires_manual_account_or_key(requirement):
        probes.append(
            {
                "id": "manual-account-or-api-key",
                "kind": "manual",
                "status": "manual_required",
                "severity": "blocker",
                "detail": "declared requirement mentions account, login, token, or API key",
            }
        )
    return probes


def _requirement_commands(requirement: str) -> list[str]:
    commands: list[str] = []
    text = requirement.strip()
    if not text:
        return commands
    package_match = re.match(r"^\s*([a-zA-Z][a-zA-Z0-9_.-]+)\s*\(", text)
    if package_match:
        commands.append(package_match.group(1))
    for marker in ("apt install", "brew install", "choco install", "winget install"):
        if marker in text.casefold():
            before_marker = text[: text.casefold().find(marker)].strip()
            if before_marker and re.match(r"^[a-zA-Z][a-zA-Z0-9_.-]+$", before_marker.split()[0]):
                commands.append(before_marker.split()[0])
    if re.search(r"\buv\b", text.casefold()):
        commands.append("uv")
    return sorted(set(commands))


def _requirement_env_vars(requirement: str) -> list[str]:
    if not requirement:
        return []
    env_vars = re.findall(r"\b[A-Z][A-Z0-9_]{2,}\b", requirement)
    return sorted(set(env_vars))


def _requirement_localhost_ports(requirement: str) -> list[tuple[str, int]]:
    ports: list[tuple[str, int]] = []
    for match in re.finditer(r"(localhost|127\.0\.0\.1|\[?::1\]?):(\d{2,5})", requirement, flags=re.IGNORECASE):
        host = match.group(1).strip("[]")
        port = int(match.group(2))
        if 0 < port < 65536:
            ports.append((host, port))
    return sorted(set(ports))


def _localhost_port_available(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


def _requires_manual_account_or_key(requirement: str) -> bool:
    text = requirement.casefold()
    return any(marker in text for marker in ("account", "login", "api key", "token", "secret"))


def _known_parser_refs() -> set[str]:
    return {item["parser_ref"] for item in ParserRegistry.builtins().list()}
