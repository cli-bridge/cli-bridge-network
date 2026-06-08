"""Controlled capability executor."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from adapters.base import ToolCall, ToolResult
from adapters.stdio import StdioAdapter
from cbn_audit.log import AuditLog
from cbn_approval.store import ApprovalStore
from cbn_artifacts.store import ArtifactStore
from cbn_core.manifest import CapabilityManifest, ManifestRegistry
from cbn_events.bus import EventBus
from cbn_parsers.registry import ParserRegistry
from cbn_policy.engine import PolicyEngine
from cbn_protocol.envelope import BridgeMessage
from protocol import EventType


class CapabilityExecutor:
    def __init__(
        self,
        registry: ManifestRegistry,
        audit_log: AuditLog,
        policy: PolicyEngine | None = None,
        approval_store: ApprovalStore | None = None,
        event_bus: EventBus | None = None,
        artifact_store: ArtifactStore | None = None,
        parser_registry: ParserRegistry | None = None,
    ) -> None:
        self.registry = registry
        self.audit_log = audit_log
        self.policy = policy or PolicyEngine()
        self.approval_store = approval_store
        self.event_bus = event_bus
        self.artifact_store = artifact_store
        self.parser_registry = parser_registry or ParserRegistry.builtins()
        self.stdio = StdioAdapter()

    def call(
        self,
        capability_id: str,
        extra_args: tuple[str, ...] = (),
        cwd: Path | None = None,
        dry_run: bool = False,
        confirmed: bool = False,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        call_id = str(uuid.uuid4())
        manifest = self.registry.require(capability_id)
        request = self._request_from_manifest(manifest, extra_args, cwd, dry_run)
        approval_confirmed = False
        if approval_id and self.approval_store:
            approval_confirmed = self.approval_store.is_approved(approval_id, capability_id)
        decision = self.policy.evaluate(manifest, confirmed=confirmed)
        if not decision.allowed and approval_confirmed:
            decision = self.policy.evaluate(manifest, confirmed=True)
        if not decision.allowed:
            approval = None
            if decision.requires_confirmation and self.approval_store is not None:
                approval = self.approval_store.request(
                    call_id=call_id,
                    capability_id=capability_id,
                    argv=request.argv,
                    cwd=request.cwd,
                    risk=decision.risk,
                    reason=decision.reason,
                    dry_run=dry_run,
                )
            event = self.audit_log.append(
                {
                    "type": "tool_call.blocked",
                    "call_id": call_id,
                    "capability_id": capability_id,
                    "decision": decision.as_dict(),
                    "approval_id": approval["approval_id"] if approval else None,
                    "dry_run": dry_run,
                }
            )
            if approval:
                self._publish(
                    EventType.APPROVAL_REQUESTED,
                    capability_id,
                    {"approval": approval},
                    call_id,
                )
            self._publish(
                EventType.TOOL_CALL_BLOCKED,
                capability_id,
                {
                    "decision": decision.as_dict(),
                    "approval_id": approval["approval_id"] if approval else None,
                    "dry_run": dry_run,
                },
                call_id,
            )
            return {
                "call_id": call_id,
                "capability_id": capability_id,
                "allowed": False,
                "decision": decision.as_dict(),
                "approval": approval,
                "audit_event_id": event["event_id"],
            }

        if approval_id and approval_confirmed and self.approval_store:
            self.approval_store.use(approval_id, capability_id)
        self.audit_log.append(
            {
                "type": "tool_call.started",
                "call_id": call_id,
                "capability_id": capability_id,
                "approval_id": approval_id if approval_confirmed else None,
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
        parsed = self._parse_result(manifest, call_id, result, artifacts)
        if parsed["artifact"] is not None:
            artifacts.append(parsed["artifact"])
        message = BridgeMessage(
            producer=capability_id,
            channel="capability.output",
            correlation_id=call_id,
            payload=parsed["payload"],
            artifacts=tuple(artifacts),
        ).as_dict()
        self._publish(
            EventType.BRIDGE_MESSAGE_CREATED,
            capability_id,
            {"message": message},
            call_id,
        )
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
                "parser_ref": parsed["payload"]["parser_ref"],
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
                "approval_id": approval_id if approval_confirmed else None,
                "parser_ref": parsed["payload"]["parser_ref"],
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
            "approval_id": approval_id if approval_confirmed else None,
            "parsed": parsed["payload"],
            "message": message,
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
        env = None
        if self.artifact_store is not None:
            env = {"CBN_ARTIFACT_ROOT": str(self.artifact_store.root)}
        return ToolCall(
            capability_id=manifest.capability_id,
            argv=manifest.transport.argv(extra_args),
            cwd=str(cwd) if cwd else None,
            dry_run=dry_run,
            timeout_seconds=manifest.transport.timeout_seconds,
            env=env,
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

    def _parse_result(
        self,
        manifest: CapabilityManifest,
        call_id: str,
        result: ToolResult,
        artifacts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        parser_ref = "raw.text" if result.reason == "dry-run" else manifest.output.parser_ref
        try:
            payload = self.parser_registry.parse(
                parser_ref,
                result.stdout,
                result.stderr,
            )
            if result.reason == "dry-run":
                payload["dry_run"] = True
        except Exception as exc:
            payload = {
                "parser_ref": parser_ref,
                "ok": False,
                "error": str(exc),
                "data": {"stdout": result.stdout, "stderr": result.stderr},
            }
        artifact = None
        if self.artifact_store is not None:
            record = self.artifact_store.create_json(
                capability_id=manifest.capability_id,
                call_id=call_id,
                kind="parsed",
                payload=payload,
            )
            artifact = record.as_dict()
            self._publish(
                EventType.OUTPUT_PARSED,
                manifest.capability_id,
                {"parsed": payload, "artifact": artifact},
                call_id,
            )
        return {"payload": payload, "artifact": artifact}

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
