"""Durable append-only approval queue."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_DENIED = "denied"
APPROVAL_USED = "used"
APPROVAL_STATUSES = {
    APPROVAL_PENDING,
    APPROVAL_APPROVED,
    APPROVAL_DENIED,
    APPROVAL_USED,
}
_MISSING = object()
_REQUEST_OPTION_NAMES = ("cwd", "risk", "reason", "dry_run", "scope_hash", "scope")


@dataclass(frozen=True)
class ApprovalRequestInput:
    call_id: str
    capability_id: str
    argv: tuple[str, ...]
    cwd: str | None
    risk: str
    reason: str
    dry_run: bool
    scope_hash: str | None
    scope: dict[str, Any] | None


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _approval_request_input(
    call_id: str,
    capability_id: str,
    argv: tuple[str, ...],
    args: tuple[Any, ...],
    options: dict[str, Any],
) -> ApprovalRequestInput:
    values = _approval_request_options(args, options)
    return ApprovalRequestInput(call_id=call_id, capability_id=capability_id, argv=argv, **values)


def _approval_request_options(args: tuple[Any, ...], options: dict[str, Any]) -> dict[str, Any]:
    if len(args) > len(_REQUEST_OPTION_NAMES):
        raise TypeError(f"request expected at most {len(_REQUEST_OPTION_NAMES) + 4} arguments")
    values = _default_request_options()
    for name, value in zip(_REQUEST_OPTION_NAMES, args):
        if name in options:
            raise TypeError(f"request got multiple values for argument '{name}'")
        values[name] = value
    unknown = sorted(set(options) - set(_REQUEST_OPTION_NAMES))
    if unknown:
        raise TypeError(f"unknown approval request option(s): {', '.join(unknown)}")
    values.update(options)
    missing = [name for name in ("risk", "reason", "dry_run") if values[name] is _MISSING]
    if missing:
        raise TypeError(f"missing approval request option(s): {', '.join(missing)}")
    return values


def _default_request_options() -> dict[str, Any]:
    return {
        "cwd": None,
        "risk": _MISSING,
        "reason": _MISSING,
        "dry_run": _MISSING,
        "scope_hash": None,
        "scope": None,
    }


class ApprovalStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def request(
        self,
        call_id: str,
        capability_id: str,
        argv: tuple[str, ...],
        *args: Any,
        **options: Any,
    ) -> dict[str, Any]:
        request = _approval_request_input(call_id, capability_id, argv, args, options)
        approval_id = str(uuid.uuid4())
        record = {
            "approval_id": approval_id,
            "status": APPROVAL_PENDING,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "call_id": request.call_id,
            "capability_id": request.capability_id,
            "argv": list(request.argv),
            "cwd": request.cwd,
            "risk": request.risk,
            "reason": request.reason,
            "dry_run": request.dry_run,
            "scope_hash": request.scope_hash,
            "scope": request.scope,
            "history": [
                {
                    "ts": now_iso(),
                    "action": "requested",
                    "actor": "system",
                    "reason": request.reason,
                }
            ],
        }
        self._append({"type": "approval.requested", **record})
        return record

    def list(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        records = list(self._latest().values())
        if status:
            records = [record for record in records if record["status"] == status]
        records.sort(key=lambda record: record["updated_at"])
        return records[-limit:]

    def inspect(self, approval_id: str) -> dict[str, Any]:
        record = self._latest().get(approval_id)
        if record is None:
            raise KeyError(f"unknown approval: {approval_id}")
        return record

    def decide(
        self,
        approval_id: str,
        decision: str,
        actor: str = "user",
        reason: str = "",
    ) -> dict[str, Any]:
        if decision not in {APPROVAL_APPROVED, APPROVAL_DENIED}:
            raise ValueError(f"unsupported approval decision: {decision}")
        record = self.inspect(approval_id)
        if record["status"] != APPROVAL_PENDING:
            raise ValueError(f"approval {approval_id} is not pending")
        return self._transition(approval_id, decision, actor=actor, reason=reason)

    def use(
        self,
        approval_id: str,
        capability_id: str,
        scope_hash: str | None = None,
    ) -> dict[str, Any]:
        record = self.inspect(approval_id)
        if record["capability_id"] != capability_id:
            raise ValueError(
                f"approval {approval_id} is for {record['capability_id']}, not {capability_id}"
            )
        if scope_hash is not None and record.get("scope_hash") != scope_hash:
            raise ValueError(f"approval {approval_id} scope does not match current request")
        if record["status"] != APPROVAL_APPROVED:
            raise ValueError(f"approval {approval_id} is not approved")
        return self._transition(approval_id, APPROVAL_USED, actor="system", reason="consumed")

    def is_approved(
        self,
        approval_id: str,
        capability_id: str,
        scope_hash: str | None = None,
    ) -> bool:
        try:
            record = self.inspect(approval_id)
        except KeyError:
            return False
        if record["status"] != APPROVAL_APPROVED or record["capability_id"] != capability_id:
            return False
        if scope_hash is not None and record.get("scope_hash") != scope_hash:
            return False
        return True

    def _transition(
        self,
        approval_id: str,
        status: str,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        if status not in APPROVAL_STATUSES:
            raise ValueError(f"unsupported approval status: {status}")
        record = dict(self.inspect(approval_id))
        history = list(record.get("history", []))
        history.append(
            {
                "ts": now_iso(),
                "action": status,
                "actor": actor,
                "reason": reason,
            }
        )
        record["status"] = status
        record["updated_at"] = now_iso()
        record["history"] = history
        self._append({"type": f"approval.{status}", **record})
        return record

    def _latest(self) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        if not self.path.exists():
            return latest
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            approval_id = event.get("approval_id")
            if approval_id:
                record = dict(event)
                record.pop("type", None)
                latest[approval_id] = record
        return latest

    def _append(self, event: dict[str, Any]) -> None:
        payload = {"event_id": str(uuid.uuid4()), "ts": now_iso(), **event}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
