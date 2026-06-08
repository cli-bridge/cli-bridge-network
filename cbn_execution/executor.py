"""Controlled capability executor."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from adapters.base import ToolCall, ToolResult
from adapters.stdio import StdioAdapter
from cbn_audit.log import AuditLog
from cbn_core.manifest import CapabilityManifest, ManifestRegistry
from cbn_policy.engine import PolicyEngine


class CapabilityExecutor:
    def __init__(
        self,
        registry: ManifestRegistry,
        audit_log: AuditLog,
        policy: PolicyEngine | None = None,
    ) -> None:
        self.registry = registry
        self.audit_log = audit_log
        self.policy = policy or PolicyEngine()
        self.stdio = StdioAdapter()

    def call(
        self,
        capability_id: str,
        extra_args: tuple[str, ...] = (),
        cwd: Path | None = None,
        dry_run: bool = False,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        manifest = self.registry.require(capability_id)
        decision = self.policy.evaluate(manifest, confirmed=confirmed)
        if not decision.allowed:
            event = self.audit_log.append(
                {
                    "type": "tool_call.blocked",
                    "capability_id": capability_id,
                    "decision": decision.as_dict(),
                    "dry_run": dry_run,
                }
            )
            return {
                "capability_id": capability_id,
                "allowed": False,
                "decision": decision.as_dict(),
                "audit_event_id": event["event_id"],
            }

        request = self._request_from_manifest(manifest, extra_args, cwd, dry_run)
        self.audit_log.append(
            {
                "type": "tool_call.started",
                "capability_id": capability_id,
                "argv": list(request.argv),
                "cwd": request.cwd,
                "dry_run": dry_run,
            }
        )
        result = self._dispatch(manifest, request)
        event = self.audit_log.append(
            {
                "type": "tool_call.completed",
                "capability_id": capability_id,
                "allowed": result.allowed,
                "exit_code": result.exit_code,
                "reason": result.reason,
                "stdout_summary": result.stdout[:500],
                "stderr_summary": result.stderr[:500],
                "dry_run": dry_run,
            }
        )
        return {
            "capability_id": capability_id,
            "allowed": result.allowed,
            "exit_code": result.exit_code,
            "reason": result.reason,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "audit_event_id": event["event_id"],
        }

    def _request_from_manifest(
        self,
        manifest: CapabilityManifest,
        extra_args: tuple[str, ...],
        cwd: Path | None,
        dry_run: bool,
    ) -> ToolCall:
        return ToolCall(
            capability_id=manifest.capability_id,
            argv=manifest.transport.argv(extra_args),
            cwd=str(cwd) if cwd else None,
            dry_run=dry_run,
        )

    def _dispatch(self, manifest: CapabilityManifest, request: ToolCall) -> ToolResult:
        if manifest.transport.kind == "stdio":
            return self.stdio.call(request)
        return ToolResult(
            capability_id=manifest.capability_id,
            allowed=False,
            exit_code=None,
            reason=f"unsupported transport={manifest.transport.kind}",
        )

