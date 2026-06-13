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
from cbn_core.manifest import ManifestRegistry
from cbn_events.bus import EventBus
from cbn_plugins.manager import (
    PluginManager,
    PluginPlan,
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
from cbn_plugins.cli_anything_parts.evaluation import (
    adapt_harness as _evaluation_parts_adapt_harness,
    evaluate_harness as _evaluation_parts_evaluate_harness,
    harness_operation_gate as _evaluation_parts_harness_operation_gate,
    prepare_harness as _evaluation_parts_prepare_harness,
    probe_harness as _evaluation_parts_probe_harness,
)
from cbn_plugins.cli_anything_parts.manifest_factory import (
    build_harness_manifest,
    infer_market_policy as _manifest_factory_infer_market_policy,
    preserve_existing_parser_contract as _preserve_existing_parser_contract,
    sanitize_harness_name as _manifest_factory_sanitize_harness_name,
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
from cbn_plugins.cli_anything_parts.plans import (
    harness_plan as _plans_parts_harness_plan,
    verify_harness_plan as _plans_parts_verify_harness_plan,
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
from cbn_plugins.cli_anything_parts.status import (
    harness_status as _status_parts_harness_status,
    market_record_for_harness as _status_parts_market_record_for_harness,
)
from cbn_plugins.cli_anything_parts.verification import (
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
        return _status_parts_harness_status(self, harness_name, from_market=from_market)

    def market_record_for_harness(self, harness_name: str) -> dict[str, Any] | None:
        return _status_parts_market_record_for_harness(self, harness_name)

    def harness_plan(
        self,
        action: str,
        harness_name: str,
        extra_args: tuple[str, ...] = (),
    ) -> PluginPlan:
        return _plans_parts_harness_plan(
            self,
            action=action,
            harness_name=harness_name,
            extra_args=extra_args,
        )

    def verify_harness_plan(
        self,
        action: str,
        harness_name: str,
        extra_args: tuple[str, ...] = (),
        run: bool = False,
        timeout_seconds: int = 60,
    ) -> dict[str, Any]:
        return _plans_parts_verify_harness_plan(
            self,
            action=action,
            harness_name=harness_name,
            extra_args=extra_args,
            run=run,
            timeout_seconds=timeout_seconds,
        )

    def harness_operation_gate(
        self,
        action: str,
        harness_name: str,
        from_market: bool = True,
    ) -> dict[str, Any]:
        return _evaluation_parts_harness_operation_gate(
            self,
            action=action,
            harness_name=harness_name,
            from_market=from_market,
        )

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
        return _evaluation_parts_adapt_harness(
            self,
            harness_name=harness_name,
            title=title,
            from_market=from_market,
            write=write,
        )

    def prepare_harness(
        self,
        harness_name: str,
        title: str | None = None,
        from_market: bool = False,
    ) -> dict[str, Any]:
        return _evaluation_parts_prepare_harness(
            self,
            harness_name=harness_name,
            title=title,
            from_market=from_market,
        )

    def evaluate_harness(
        self,
        harness_name: str,
        title: str | None = None,
        from_market: bool = True,
    ) -> dict[str, Any]:
        return _evaluation_parts_evaluate_harness(
            self,
            harness_name=harness_name,
            title=title,
            from_market=from_market,
        )

    def probe_harness(
        self,
        harness_name: str,
        title: str | None = None,
        from_market: bool = True,
    ) -> dict[str, Any]:
        return _evaluation_parts_probe_harness(
            self,
            harness_name=harness_name,
            title=title,
            from_market=from_market,
        )

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
        **options: Any,
    ) -> dict[str, Any]:
        return _onboarding_parts_onboard_harness(
            self,
            harness_name=harness_name,
            **options,
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
        **options: Any,
    ) -> dict[str, Any]:
        return _repair_parts_repair_entrypoint(
            self,
            harness_name=harness_name,
            **options,
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
        **options: Any,
    ) -> dict[str, Any]:
        return _adapter_targets_parts_adapter_target_smoke(
            self,
            harness_name=harness_name,
            module=module,
            **options,
        )

    def adaptation_gate(
        self,
        harness_name: str,
        **options: Any,
    ) -> dict[str, Any]:
        return _adaptation_parts_adaptation_gate(
            self,
            harness_name=harness_name,
            **options,
        )

    def adaptation_queue(
        self,
        harnesses: tuple[str, ...] = (),
        **options: Any,
    ) -> dict[str, Any]:
        return _adaptation_parts_adaptation_queue(
            self,
            harnesses=harnesses,
            **options,
        )

    def live_verification(
        self,
        **options: Any,
    ) -> dict[str, Any]:
        """Return a repeatable read-only verification snapshot for CLI-Anything."""

        return _live_parts_live_verification(
            self,
            **options,
        )

    def mvp_plan(
        self,
        **options: Any,
    ) -> dict[str, Any]:
        """Return the read-only MVP control plan for the next CLI-Anything work."""

        return _planning_mvp_plan(
            self,
            **options,
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
