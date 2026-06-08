"""Build shared MVP runtime context."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cbn.paths import resolve_project_paths
from cbn_audit.log import AuditLog
from cbn_core.manifest import ManifestRegistry
from cbn_execution.executor import CapabilityExecutor


@dataclass
class RuntimeContext:
    registry: ManifestRegistry
    audit_log: AuditLog
    executor: CapabilityExecutor


def build_runtime(root: Path | None = None) -> RuntimeContext:
    paths = resolve_project_paths(root)
    registry = ManifestRegistry()
    registry.load_dir(paths.manifests)
    audit_log = AuditLog(paths.logs / "cbn-audit.jsonl")
    return RuntimeContext(
        registry=registry,
        audit_log=audit_log,
        executor=CapabilityExecutor(registry=registry, audit_log=audit_log),
    )

