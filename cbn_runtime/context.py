"""Build shared MVP runtime context."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from cbn.paths import resolve_project_paths
from cbn_audit.log import AuditLog
from cbn_approval.store import ApprovalStore
from cbn_artifacts.store import ArtifactStore
from cbn_core.manifest import ManifestRegistry
from cbn_events.bus import EventBus
from cbn_execution.executor import CapabilityExecutor
from cbn_favorites.store import FavoriteStore
from cbn_parsers.registry import ParserRegistry
from cbn_plugins.operations import PluginOperationRunner
from cbn_threads.store import ThreadStore
from cbn_workflow.runner import WorkflowRunner


@dataclass
class RuntimeContext:
    registry: ManifestRegistry
    audit_log: AuditLog
    approval_store: ApprovalStore
    event_bus: EventBus
    artifact_store: ArtifactStore
    parser_registry: ParserRegistry
    executor: CapabilityExecutor
    workflow_runner: WorkflowRunner
    plugin_runner: PluginOperationRunner
    thread_store: ThreadStore
    favorite_store: FavoriteStore


_EXTERNAL_PATH_ADDED = False


def _ensure_external_plugin_path(paths: object) -> None:
    """One-time prepend of external plugin bin dirs (cli-anything hub-venv +
    npm-global) to PATH so bare commands like ``cli-hub`` / ``lark-cli`` resolve
    in capability subprocesses (which inherit os.environ via _subprocess_env)."""
    global _EXTERNAL_PATH_ADDED
    if _EXTERNAL_PATH_ADDED:
        return
    root = getattr(paths, "root", None)
    if root is None:
        _EXTERNAL_PATH_ADDED = True
        return
    candidates = [
        Path(root) / "external_plugins" / "cli-anything" / "hub-venv" / "Scripts",
        Path(root) / "external_plugins" / "cli-anything" / "npm-global",
    ]
    sep = os.pathsep
    parts = os.environ.get("PATH", "").split(sep)
    additions = [str(p) for p in candidates if p.exists() and str(p) not in parts]
    if additions:
        os.environ["PATH"] = sep.join([*additions, *parts])
    _EXTERNAL_PATH_ADDED = True


def build_runtime(root: Path | None = None) -> RuntimeContext:
    paths = resolve_project_paths(root)
    _ensure_external_plugin_path(paths)

    registry = ManifestRegistry()
    registry.load_dir(paths.manifests)
    registry.load_dir(paths.local_manifests, replace=True)
    audit_log = AuditLog(paths.logs / "cbn-audit.jsonl")
    approval_store = ApprovalStore(paths.approvals)
    event_bus = EventBus(paths.logs / "cbn-events.jsonl")
    artifact_store = ArtifactStore(paths.artifacts)
    parser_registry = ParserRegistry.builtins()
    executor = CapabilityExecutor(
        registry=registry,
        audit_log=audit_log,
        approval_store=approval_store,
        event_bus=event_bus,
        artifact_store=artifact_store,
        parser_registry=parser_registry,
    )
    thread_store = ThreadStore(paths.threads)
    favorite_store = FavoriteStore(paths.favorites)
    return RuntimeContext(
        registry=registry,
        audit_log=audit_log,
        approval_store=approval_store,
        event_bus=event_bus,
        artifact_store=artifact_store,
        parser_registry=parser_registry,
        executor=executor,
        workflow_runner=WorkflowRunner(executor, event_bus=event_bus, audit_log=audit_log),
        plugin_runner=PluginOperationRunner(
            audit_log=audit_log,
            event_bus=event_bus,
            artifact_store=artifact_store,
        ),
        thread_store=thread_store,
        favorite_store=favorite_store,
    )


# Run once at import so external plugin bins (cli-hub, lark-cli) are on PATH before
# ANY request handler runs — including the static cli-anything GET routes that are
# dispatched before build_runtime.
try:
    _ensure_external_plugin_path(resolve_project_paths())
except Exception:
    pass
