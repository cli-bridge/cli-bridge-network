"""Controlled capability executor."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from adapters.base import ToolCall, ToolResult
from adapters.stdio import StdioAdapter
from cbn_audit.log import AuditLog
from cbn_artifacts.store import ArtifactStore
from cbn_core.manifest import CapabilityManifest, ManifestRegistry
from cbn_events.bus import EventBus
from cbn_policy.engine import PolicyEngine
from protocol import EventType


class CapabilityExecutor:
    def __init__(
        self,
        registry: ManifestRegistry,
        audit_log: AuditLog,
        policy: PolicyEngine | None = None,
        event_bus: EventBus | None = None,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self.registry = registry
        self.audit_log = audit_log
        self.policy = policy or PolicyEngine()
        self.event_bus = event_bus
        self.artifact_store = artifact_store
        self.stdio = StdioAdapter()

    def call(
        self,
        capability_id: str,
        extra_args: tuple[str, ...] = (),
        cwd: Path | None = None,
        dry_run: bool = False,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        call_id = str(uuid.uuid4())
        manifest = self.registry.require(capability_id)
        decision = self.policy.evaluate(manifest, confirmed=confirmed)
        if not decision.allowed:
            event = self.audit_log.append(
                {
                    "type": "tool_call.blocked",
                    "call_id": call_id,
                    "capability_id": capability_id,
                    "decision": decision.as_dict(),
                    "dry_run": dry_run,
                }
            )
            self._publish(
                EventType.TOOL_CALL_BLOCKED,
                capability_id,
                {"decision": decision.as_dict(), "dry_run": dry_run},
                call_id,
            )
            return {
                "call_id": call_id,
                "capability_id": capability_id,
                "allowed": False,
                "decision": decision.as_dict(),
                "audit_event_id": event["event_id"],
            }

        request = self._request_from_manifest(manifest, extra_args, cwd, dry_run)
        self.audit_log.append(
            {
                "type": "tool_call.started",
                "call_id": call_id,
                "capability_id": capability_id,
                "argv": list(request.argv),
                "cwd": request.cwd,
                "dry_run": dry_run,
            }
        )
        self._publish(
            EventType.TOOL_CALL_STARTED,
            capability_id,
            {"argv": list(request.argv), "cwd": request.cwd, "dry_run": dry_run},
            call_id,
        )
        result = self._dispatch(manifest, request)
        artifacts = self._record_artifacts(capability_id, call_id, result)
        event = self.audit_log.append(
            {
                "type": "tool_call.completed",
                "call_id": call_id,
                "capability_id": capability_id,
                "allowed": result.allowed,
                "exit_code": result.exit_code,
                "reason": result.reason,
                "stdout_summary": result.stdout[:500],
                "stderr_summary": result.stderr[:500],
                "artifact_ids": [artifact["artifact_id"] for artifact in artifacts],
                "dry_run": dry_run,
            }
        )
        self._publish(
            EventType.TOOL_CALL_COMPLETED,
            capability_id,
            {
                "allowed": result.allowed,
                "exit_code": result.exit_code,
                "reason": result.reason,
                "artifact_ids": [artifact["artifact_id"] for artifact in artifacts],
                "dry_run": dry_run,
            },
            call_id,
        )
        return {
            "call_id": call_id,
            "capability_id": capability_id,
            "allowed": result.allowed,
            "exit_code": result.exit_code,
            "reason": result.reason,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "artifacts": artifacts,
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

    def _record_artifacts(
        self,
        capability_id: str,
        call_id: str,
        result: ToolResult,
    ) -> list[dict[str, Any]]:
        if self.artifact_store is None:
            return []
        records = []
        for kind, text in (("stdout", result.stdout), ("stderr", result.stderr)):
            record = self.artifact_store.create_text(
                capability_id=capability_id,
                call_id=call_id,
                kind=kind,
                text=text,
            )
            if record is not None:
                artifact = record.as_dict()
                records.append(artifact)
                self._publish(
                    EventType.ARTIFACT_CREATED,
                    capability_id,
                    {"artifact": artifact},
                    call_id,
                )
        return records

    def _publish(
        self,
        event_type: EventType,
        subject: str,
        payload: dict[str, Any],
        call_id: str,
    ) -> None:
        if self.event_bus is None:
            return
        self.event_bus.publish(
            str(event_type),
            subject=subject,
            payload=payload,
            correlation_id=call_id,
        )
