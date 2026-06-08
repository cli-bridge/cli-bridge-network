"""Build shared MVP runtime context."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cbn.paths import resolve_project_paths
from cbn_audit.log import AuditLog
from cbn_approval.store import ApprovalStore
from cbn_artifacts.store import ArtifactStore
from cbn_core.manifest import ManifestRegistry
from cbn_events.bus import EventBus
from cbn_execution.executor import CapabilityExecutor
from cbn_workflow.runner import WorkflowRunner


@dataclass
class RuntimeContext:
    registry: ManifestRegistry
    audit_log: AuditLog
    approval_store: ApprovalStore
    event_bus: EventBus
    artifact_store: ArtifactStore
    executor: CapabilityExecutor
    workflow_runner: WorkflowRunner


def build_runtime(root: Path | None = None) -> RuntimeContext:
    paths = resolve_project_paths(root)
    registry = ManifestRegistry()
    registry.load_dir(paths.manifests)
    audit_log = AuditLog(paths.logs / "cbn-audit.jsonl")
    approval_store = ApprovalStore(paths.approvals)
    event_bus = EventBus(paths.logs / "cbn-events.jsonl")
    artifact_store = ArtifactStore(paths.artifacts)
    executor = CapabilityExecutor(
        registry=registry,
        audit_log=audit_log,
        approval_store=approval_store,
        event_bus=event_bus,
        artifact_store=artifact_store,
    )
    return RuntimeContext(
        registry=registry,
        audit_log=audit_log,
        approval_store=approval_store,
        event_bus=event_bus,
        artifact_store=artifact_store,
        executor=executor,
        workflow_runner=WorkflowRunner(executor, event_bus=event_bus, audit_log=audit_log),
    )
