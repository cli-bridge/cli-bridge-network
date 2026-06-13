"""Controlled capability executor."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adapters.base import ToolCall, ToolResult
from adapters.pty import PtyAdapter
from adapters.stdio import StdioAdapter
from cbn_audit.log import AuditLog
from cbn_approval.store import ApprovalStore
from cbn_artifacts.store import ArtifactStore
from cbn_core.manifest import CapabilityManifest, ManifestRegistry
from cbn_events.bus import EventBus
from cbn_parsers.registry import ParserRegistry
from cbn_policy.engine import PolicyEngine
from cbn_core.message import BridgeMessage
from protocol import EventType


@dataclass(frozen=True)
class CompletedEventPayloadInput:
    call_id: str
    manifest: CapabilityManifest
    result: ToolResult
    parsed: dict[str, Any]
    artifacts: list[dict[str, Any]]
    authorization: dict[str, Any]
    approval_id: str | None
    ok: bool
    dry_run: bool


@dataclass(frozen=True)
class BlockedEventPayloadInput:
    call_id: str
    manifest: CapabilityManifest
    decision: Any
    approval: dict[str, Any] | None
    authorization: dict[str, Any]
    approval_id: str | None
    dry_run: bool


@dataclass(frozen=True)
class CapabilityExecutorDeps:
    policy: PolicyEngine | None = None
    approval_store: ApprovalStore | None = None
    event_bus: EventBus | None = None
    artifact_store: ArtifactStore | None = None
    parser_registry: ParserRegistry | None = None


class CapabilityExecutor:
    def __init__(
        self,
        registry: ManifestRegistry,
        audit_log: AuditLog,
        deps: CapabilityExecutorDeps | PolicyEngine | None = None,
        **overrides: Any,
    ) -> None:
        resolved = _executor_deps(deps, overrides)
        self.registry = registry
        self.audit_log = audit_log
        self.policy = resolved.policy or PolicyEngine()
        self.approval_store = resolved.approval_store
        self.event_bus = resolved.event_bus
        self.artifact_store = resolved.artifact_store
        self.parser_registry = resolved.parser_registry or ParserRegistry.builtins()
        self.stdio = StdioAdapter()
        self.pty = PtyAdapter()
        self.session_env: dict[str, str] = {}

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

        authorization = self._authorize(manifest, request, confirmed, approval_id)
        if not authorization["decision"].allowed:
            return self._blocked_response(
                call_id,
                manifest,
                request,
                authorization,
                approval_id,
                dry_run,
            )

        self._record_started(
            call_id,
            manifest,
            request,
            authorization["approval_confirmed"],
            approval_id,
            dry_run,
        )
        result = self._dispatch(manifest, request)
        return self._completed_response(
            call_id,
            manifest,
            result,
            authorization,
            approval_id,
            dry_run,
        )

    def _authorize(
        self,
        manifest: CapabilityManifest,
        request: ToolCall,
        confirmed: bool,
        approval_id: str | None,
    ) -> dict[str, Any]:
        approval_scope = _approval_scope(manifest, request)
        approval_confirmed = False
        approval_error = None
        decision = self.policy.evaluate(manifest, confirmed=confirmed)
        if not decision.allowed and approval_id and self.approval_store:
            try:
                self.approval_store.use(
                    approval_id,
                    manifest.capability_id,
                    scope_hash=approval_scope["scope_hash"],
                )
                approval_confirmed = True
                decision = self.policy.evaluate(manifest, confirmed=True)
            except (KeyError, ValueError) as exc:
                approval_error = str(exc)
        return {
            "decision": decision,
            "approval_confirmed": approval_confirmed,
            "approval_error": approval_error,
            "approval_scope": approval_scope,
        }

    def _blocked_response(
        self,
        call_id: str,
        manifest: CapabilityManifest,
        request: ToolCall,
        authorization: dict[str, Any],
        approval_id: str | None,
        dry_run: bool,
    ) -> dict[str, Any]:
        decision = authorization["decision"]
        approval_scope = authorization["approval_scope"]
        approval = self._request_approval(call_id, manifest, request, decision, approval_scope, dry_run)
        blocked = BlockedEventPayloadInput(
            call_id=call_id,
            manifest=manifest,
            decision=decision,
            approval=approval,
            authorization=authorization,
            approval_id=approval_id,
            dry_run=dry_run,
        )
        event = self.audit_log.append(_blocked_audit_record(blocked, approval_scope))
        if approval:
            self._publish_approval_requested(blocked)
        self._publish_blocked(blocked)
        return _blocked_call_result(blocked, event)

    def _request_approval(
        self,
        call_id: str,
        manifest: CapabilityManifest,
        request: ToolCall,
        decision: Any,
        approval_scope: dict[str, Any],
        dry_run: bool,
    ) -> dict[str, Any] | None:
        if not decision.requires_confirmation or self.approval_store is None:
            return None
        return self.approval_store.request(
            call_id=call_id,
            capability_id=manifest.capability_id,
            argv=request.argv,
            cwd=request.cwd,
            risk=decision.risk,
            reason=decision.reason,
            dry_run=dry_run,
            scope_hash=approval_scope["scope_hash"],
            scope=approval_scope["scope"],
        )

    def _publish_blocked(self, payload: BlockedEventPayloadInput) -> None:
        self._publish(
            EventType.TOOL_CALL_BLOCKED,
            payload.manifest.capability_id,
            {
                "decision": payload.decision.as_dict(),
                "approval_id": payload.approval["approval_id"] if payload.approval else None,
                "requested_approval_id": payload.approval_id,
                "approval_error": payload.authorization["approval_error"],
                "dry_run": payload.dry_run,
            },
            payload.call_id,
        )

    def _publish_approval_requested(self, payload: BlockedEventPayloadInput) -> None:
        if payload.approval is None:
            return
        self._publish(
            EventType.APPROVAL_REQUESTED,
            payload.manifest.capability_id,
            {"approval": payload.approval},
            payload.call_id,
        )

    def _record_started(
        self,
        call_id: str,
        manifest: CapabilityManifest,
        request: ToolCall,
        approval_confirmed: bool,
        approval_id: str | None,
        dry_run: bool,
    ) -> None:
        approval_scope = _approval_scope(manifest, request) if approval_confirmed else None
        self.audit_log.append(
            {
                "type": "tool_call.started",
                "call_id": call_id,
                "capability_id": manifest.capability_id,
                "approval_id": approval_id if approval_confirmed else None,
                "approval_scope_hash": approval_scope["scope_hash"] if approval_scope else None,
                "argv": list(request.argv),
                "cwd": request.cwd,
                "dry_run": dry_run,
            }
        )
        self._publish(
            EventType.TOOL_CALL_STARTED,
            manifest.capability_id,
            {"argv": list(request.argv), "cwd": request.cwd, "dry_run": dry_run},
            call_id,
        )

    def _completed_response(
        self,
        call_id: str,
        manifest: CapabilityManifest,
        result: ToolResult,
        authorization: dict[str, Any],
        approval_id: str | None,
        dry_run: bool,
    ) -> dict[str, Any]:
        completion = self._completed_call(call_id, manifest, result)
        self._publish_bridge_message(call_id, manifest, completion["message"])
        event = self._record_completed_audit(call_id, manifest, result, completion, authorization, dry_run)
        self._publish_completed(CompletedEventPayloadInput(
            call_id=call_id,
            manifest=manifest,
            result=result,
            parsed=completion["parsed_record"],
            artifacts=completion["artifacts"],
            authorization=authorization,
            approval_id=approval_id,
            ok=completion["ok"],
            dry_run=dry_run,
        ))
        return _completed_response_payload(
            call_id,
            manifest,
            result,
            completion,
            authorization,
            approval_id,
            event["event_id"],
        )

    def _completed_call(
        self,
        call_id: str,
        manifest: CapabilityManifest,
        result: ToolResult,
    ) -> dict[str, Any]:
        artifacts = self._record_artifacts(manifest.capability_id, call_id, result)
        parsed = self._parse_result(manifest, call_id, result, artifacts)
        if parsed["artifact"] is not None:
            artifacts.append(parsed["artifact"])
        ok = _tool_call_ok(result, parsed["payload"])
        return {
            "ok": ok,
            "parsed": parsed["payload"],
            "parsed_record": parsed,
            "artifacts": artifacts,
            "message": _capability_output_message(call_id, manifest, parsed["payload"], artifacts),
        }

    def _record_completed_audit(
        self,
        call_id: str,
        manifest: CapabilityManifest,
        result: ToolResult,
        completion: dict[str, Any],
        authorization: dict[str, Any],
        dry_run: bool,
    ) -> dict[str, Any]:
        return self.audit_log.append(
            {
                "type": "tool_call.completed",
                "call_id": call_id,
                "capability_id": manifest.capability_id,
                "allowed": result.allowed,
                "ok": completion["ok"],
                "exit_code": result.exit_code,
                "reason": result.reason,
                "stdout_summary": result.stdout[:500],
                "stderr_summary": result.stderr[:500],
                "parser_ref": completion["parsed"]["parser_ref"],
                "parser_ok": completion["parsed"].get("ok"),
                "artifact_ids": _artifact_ids(completion["artifacts"]),
                "dry_run": dry_run,
                "approval_scope_hash": _confirmed_scope_hash(authorization),
            }
        )

    def _publish_bridge_message(
        self,
        call_id: str,
        manifest: CapabilityManifest,
        message: dict[str, Any],
    ) -> None:
        self._publish(
            EventType.BRIDGE_MESSAGE_CREATED,
            manifest.capability_id,
            {"message": message},
            call_id,
        )

    def _publish_completed(self, data: CompletedEventPayloadInput) -> None:
        self._publish(
            EventType.TOOL_CALL_COMPLETED,
            data.manifest.capability_id,
            {
                "allowed": data.result.allowed,
                "ok": data.ok,
                "exit_code": data.result.exit_code,
                "reason": data.result.reason,
                "approval_id": data.approval_id if data.authorization["approval_confirmed"] else None,
                "parser_ref": data.parsed["payload"]["parser_ref"],
                "parser_ok": data.parsed["payload"].get("ok"),
                "artifact_ids": _artifact_ids(data.artifacts),
                "dry_run": data.dry_run,
                "approval_scope_hash": _confirmed_scope_hash(data.authorization),
            },
            data.call_id,
        )

    def _request_from_manifest(
        self,
        manifest: CapabilityManifest,
        extra_args: tuple[str, ...],
        cwd: Path | None,
        dry_run: bool,
    ) -> ToolCall:
        env = dict(self.session_env)
        if self.artifact_store is not None:
            env["CBN_ARTIFACT_ROOT"] = str(self.artifact_store.root)
        return ToolCall(
            capability_id=manifest.capability_id,
            argv=manifest.transport.argv(extra_args),
            cwd=str(cwd) if cwd else None,
            dry_run=dry_run,
            timeout_seconds=manifest.transport.timeout_seconds,
            env=env or None,
        )

    def _dispatch(self, manifest: CapabilityManifest, request: ToolCall) -> ToolResult:
        if manifest.transport.kind == "stdio":
            return self.stdio.call(request)
        if manifest.transport.kind == "pty":
            return self.pty.call(request)
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


def _executor_deps(
    deps: CapabilityExecutorDeps | PolicyEngine | None,
    overrides: dict[str, Any],
) -> CapabilityExecutorDeps:
    if deps is not None and not isinstance(deps, CapabilityExecutorDeps):
        if "policy" in overrides:
            raise TypeError("CapabilityExecutor got policy both positionally and by keyword")
        overrides = {**overrides, "policy": deps}
        deps = None
    unknown = sorted(set(overrides) - set(CapabilityExecutorDeps.__dataclass_fields__))
    if unknown:
        raise TypeError(f"unknown CapabilityExecutor dependency option(s): {', '.join(unknown)}")
    values = {
        name: getattr(deps, name) if deps is not None else None
        for name in CapabilityExecutorDeps.__dataclass_fields__
    }
    values.update(overrides)
    return CapabilityExecutorDeps(**values)


def _blocked_audit_record(
    payload: BlockedEventPayloadInput,
    approval_scope: dict[str, Any],
) -> dict[str, Any]:
    return {
        "type": "tool_call.blocked",
        "call_id": payload.call_id,
        "capability_id": payload.manifest.capability_id,
        "decision": payload.decision.as_dict(),
        "approval_id": payload.approval["approval_id"] if payload.approval else None,
        "requested_approval_id": payload.approval_id,
        "approval_error": payload.authorization["approval_error"],
        "dry_run": payload.dry_run,
        "approval_scope_hash": approval_scope["scope_hash"],
    }


def _blocked_call_result(
    payload: BlockedEventPayloadInput,
    event: dict[str, Any],
) -> dict[str, Any]:
    return {
        "call_id": payload.call_id,
        "capability_id": payload.manifest.capability_id,
        "ok": False,
        "allowed": False,
        "decision": payload.decision.as_dict(),
        "approval": payload.approval,
        "approval_error": payload.authorization["approval_error"],
        "audit_event_id": event["event_id"],
    }


def _tool_call_ok(result: ToolResult, parsed: dict[str, Any]) -> bool:
    return bool(result.allowed) and result.exit_code in (0, None) and parsed.get("ok") is True


def _capability_output_message(
    call_id: str,
    manifest: CapabilityManifest,
    parsed_payload: dict[str, Any],
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    return BridgeMessage(
        producer=manifest.capability_id,
        channel="capability.output",
        correlation_id=call_id,
        payload=parsed_payload,
        artifacts=tuple(artifacts),
    ).as_dict()


def _completed_response_payload(
    call_id: str,
    manifest: CapabilityManifest,
    result: ToolResult,
    completion: dict[str, Any],
    authorization: dict[str, Any],
    approval_id: str | None,
    audit_event_id: str,
) -> dict[str, Any]:
    return {
        "call_id": call_id,
        "capability_id": manifest.capability_id,
        "ok": completion["ok"],
        "allowed": result.allowed,
        "exit_code": result.exit_code,
        "reason": result.reason,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "approval_id": approval_id if authorization["approval_confirmed"] else None,
        "parsed": completion["parsed"],
        "message": completion["message"],
        "artifacts": completion["artifacts"],
        "audit_event_id": audit_event_id,
    }


def _artifact_ids(artifacts: list[dict[str, Any]]) -> list[str]:
    return [artifact["artifact_id"] for artifact in artifacts]


def _confirmed_scope_hash(authorization: dict[str, Any]) -> str | None:
    if not authorization["approval_confirmed"]:
        return None
    return authorization["approval_scope"]["scope_hash"]


def _approval_scope(manifest: CapabilityManifest, request: ToolCall) -> dict[str, Any]:
    manifest_digest = _digest(_manifest_scope_payload(manifest))
    policy_digest = _digest(_policy_scope_payload(manifest))
    scope = {
        "capability_id": manifest.capability_id,
        "argv": list(request.argv),
        "cwd": request.cwd,
        "dry_run": request.dry_run,
        "manifest_digest": manifest_digest,
        "policy_digest": policy_digest,
        "actor": "local-user",
    }
    return {
        "scope_hash": _digest(scope),
        "scope": scope,
    }


def _manifest_scope_payload(manifest: CapabilityManifest) -> dict[str, Any]:
    return {
        "capability_id": manifest.capability_id,
        "title": manifest.title,
        "transport": {
            "kind": manifest.transport.kind,
            "command": manifest.transport.command,
            "argsTemplate": list(manifest.transport.args_template),
            "cwdPolicy": manifest.transport.cwd_policy,
            "timeoutSeconds": manifest.transport.timeout_seconds,
        },
        "policy": _policy_scope_payload(manifest),
        "output": {
            "parserRef": manifest.output.parser_ref,
            "verified": manifest.output.verified,
        },
        "labels": manifest.labels,
        "annotations": manifest.annotations,
    }


def _policy_scope_payload(manifest: CapabilityManifest) -> dict[str, Any]:
    return {
        "risk": manifest.policy.risk,
        "requiresConfirmation": manifest.policy.requires_confirmation,
        "network": manifest.policy.network,
    }


def _digest(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
