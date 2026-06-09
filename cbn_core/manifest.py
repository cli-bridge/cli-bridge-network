"""Versioned Manifest IR for CBN capabilities."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MANIFEST_API_VERSION = "bridge.dev/v1alpha1"
VALID_MANIFEST_RISKS = {"read", "write-workspace", "privileged", "external-network"}
VALID_NETWORK_POLICIES = {"deny", "localhost", "requires-confirmation", "allow"}
KNOWN_TRANSPORT_KINDS = {"stdio", "pty"}
CURRENT_EXECUTOR_TRANSPORTS = {"stdio", "pty"}


@dataclass(frozen=True)
class TransportSpec:
    kind: str
    command: str
    args_template: tuple[str, ...]
    cwd_policy: str = "workspace"
    timeout_seconds: int = 30

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TransportSpec":
        return cls(
            kind=raw["kind"],
            command=raw["command"],
            args_template=tuple(raw.get("argsTemplate", [])),
            cwd_policy=raw.get("cwdPolicy", "workspace"),
            timeout_seconds=_parse_timeout_seconds(raw.get("timeoutSeconds", 30)),
        )

    def argv(self, extra_args: tuple[str, ...] = ()) -> tuple[str, ...]:
        return (self.command, *self.args_template, *extra_args)


@dataclass(frozen=True)
class PolicySpec:
    risk: str
    requires_confirmation: bool
    network: str = "deny"

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PolicySpec":
        return cls(
            risk=raw["risk"],
            requires_confirmation=bool(raw.get("requiresConfirmation", False)),
            network=raw.get("network", "deny"),
        )


@dataclass(frozen=True)
class OutputSpec:
    parser_ref: str | None = None
    verified: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "OutputSpec":
        return cls(parser_ref=raw.get("parserRef"), verified=bool(raw.get("verified", False)))


@dataclass(frozen=True)
class CapabilityManifest:
    capability_id: str
    title: str
    transport: TransportSpec
    policy: PolicySpec
    output: OutputSpec
    labels: dict[str, str]
    annotations: dict[str, str]
    source_path: Path | None = None

    @classmethod
    def from_dict(
        cls,
        raw: dict[str, Any],
        source_path: Path | None = None,
    ) -> "CapabilityManifest":
        if raw.get("apiVersion") != MANIFEST_API_VERSION:
            raise ValueError(f"unsupported manifest apiVersion: {raw.get('apiVersion')}")
        if raw.get("kind") != "ToolManifest":
            raise ValueError(f"unsupported manifest kind: {raw.get('kind')}")
        metadata = raw["metadata"]
        spec = raw["spec"]
        return cls(
            capability_id=metadata["id"],
            title=metadata.get("title", metadata["id"]),
            transport=TransportSpec.from_dict(spec["transport"]),
            policy=PolicySpec.from_dict(spec["policy"]),
            output=OutputSpec.from_dict(spec.get("output", {})),
            labels={str(key): str(value) for key, value in metadata.get("labels", {}).items()},
            annotations={str(key): str(value) for key, value in metadata.get("annotations", {}).items()},
            source_path=source_path,
        )

    @classmethod
    def from_file(cls, path: Path) -> "CapabilityManifest":
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(raw, source_path=path)

    def as_record(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "title": self.title,
            "transport": self.transport.kind,
            "timeout_seconds": self.transport.timeout_seconds,
            "risk": self.policy.risk,
            "requires_confirmation": self.policy.requires_confirmation,
            "parser_ref": self.output.parser_ref,
            "verified": self.output.verified,
            "labels": self.labels,
            "annotations": self.annotations,
            "source_path": str(self.source_path) if self.source_path else None,
        }

    def search_text(self) -> dict[str, str]:
        return {
            "capability_id": self.capability_id,
            "title": self.title,
            "transport": self.transport.kind,
            "command": " ".join(self.transport.argv()),
            "risk": self.policy.risk,
            "parser_ref": self.output.parser_ref or "",
            "labels": " ".join(f"{key}:{value}" for key, value in sorted(self.labels.items())),
            "annotations": " ".join(f"{key}:{value}" for key, value in sorted(self.annotations.items())),
            "source_path": str(self.source_path) if self.source_path else "",
        }


class ManifestRegistry:
    def __init__(self) -> None:
        self._manifests: dict[str, CapabilityManifest] = {}

    def register(self, manifest: CapabilityManifest, *, replace: bool = False) -> None:
        if manifest.capability_id in self._manifests and not replace:
            raise ValueError(f"duplicate capability manifest: {manifest.capability_id}")
        self._manifests[manifest.capability_id] = manifest

    def load_dir(self, manifest_dir: Path, *, replace: bool = False) -> None:
        if not manifest_dir.exists():
            return
        for path in sorted(manifest_dir.glob("*.json")):
            self.register(CapabilityManifest.from_file(path), replace=replace)

    def list(self) -> list[CapabilityManifest]:
        return [self._manifests[key] for key in sorted(self._manifests)]

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(0, min(limit, 100))
        tokens = [token for token in query.casefold().split() if token]
        if not tokens:
            return [
                {"manifest": manifest.as_record(), "match": {"score": 0, "fields": []}}
                for manifest in self.list()[:limit]
            ]
        matches = []
        for manifest in self.list():
            fields = manifest.search_text()
            haystack = {field: value.casefold() for field, value in fields.items()}
            if not all(any(token in value for value in haystack.values()) for token in tokens):
                continue
            matched_fields = sorted(
                field
                for field, value in haystack.items()
                if any(token in value for token in tokens)
            )
            score = sum(
                3 if value.startswith(token) else value.count(token)
                for value in haystack.values()
                for token in tokens
            )
            matches.append(
                {
                    "manifest": manifest.as_record(),
                    "match": {
                        "score": score,
                        "fields": matched_fields,
                    },
                }
            )
        matches.sort(
            key=lambda item: (
                -item["match"]["score"],
                item["manifest"]["capability_id"],
            )
        )
        return matches[:limit]

    def get(self, capability_id: str) -> CapabilityManifest | None:
        return self._manifests.get(capability_id)

    def require(self, capability_id: str) -> CapabilityManifest:
        manifest = self.get(capability_id)
        if manifest is None:
            raise KeyError(f"unknown capability: {capability_id}")
        return manifest


def validate_manifest_path(
    path: Path,
    known_parser_refs: set[str] | None = None,
) -> dict[str, Any]:
    if path.is_dir():
        reports = [validate_manifest_file(item, known_parser_refs=known_parser_refs) for item in sorted(path.glob("*.json"))]
        _mark_duplicate_capability_ids(reports)
    else:
        reports = [validate_manifest_file(path, known_parser_refs=known_parser_refs)]
    error_count = sum(len(report["errors"]) for report in reports)
    warning_count = sum(len(report["warnings"]) for report in reports)
    return {
        "valid": error_count == 0,
        "path": str(path),
        "checked_count": len(reports),
        "error_count": error_count,
        "warning_count": warning_count,
        "reports": reports,
    }


def validate_manifest_file(
    path: Path,
    known_parser_refs: set[str] | None = None,
) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return _manifest_report(path, None, [f"cannot read manifest: {exc}"], [])
    except json.JSONDecodeError as exc:
        return _manifest_report(path, None, [f"invalid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}"], [])
    return validate_manifest_dict(raw, source_path=path, known_parser_refs=known_parser_refs)


def validate_manifest_dict(
    raw: dict[str, Any],
    source_path: Path | None = None,
    known_parser_refs: set[str] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    capability_id = None
    if not isinstance(raw, dict):
        return _manifest_report(source_path, None, ["manifest root must be an object"], [])
    if raw.get("apiVersion") != MANIFEST_API_VERSION:
        errors.append(f"unsupported apiVersion: {raw.get('apiVersion')}")
    if raw.get("kind") != "ToolManifest":
        errors.append(f"unsupported kind: {raw.get('kind')}")

    metadata = raw.get("metadata")
    if not isinstance(metadata, dict):
        errors.append("metadata must be an object")
        metadata = {}
    capability_id = metadata.get("id")
    if not isinstance(capability_id, str) or not capability_id.strip():
        errors.append("metadata.id is required")
        capability_id = None
    if "title" in metadata and not isinstance(metadata.get("title"), str):
        errors.append("metadata.title must be a string when present")
    for field in ("labels", "annotations"):
        value = metadata.get(field, {})
        if not isinstance(value, dict):
            errors.append(f"metadata.{field} must be an object when present")

    spec = raw.get("spec")
    if not isinstance(spec, dict):
        errors.append("spec must be an object")
        spec = {}
    _validate_transport(spec.get("transport"), errors, warnings)
    _validate_policy(spec.get("policy"), errors)
    _validate_output(spec.get("output", {}), errors, warnings, known_parser_refs)

    if not errors:
        try:
            CapabilityManifest.from_dict(raw, source_path=source_path)
        except Exception as exc:
            errors.append(f"manifest cannot be parsed: {exc}")
    return _manifest_report(source_path, capability_id, errors, warnings)


def _validate_transport(raw: Any, errors: list[str], warnings: list[str]) -> None:
    if not isinstance(raw, dict):
        errors.append("spec.transport must be an object")
        return
    kind = raw.get("kind")
    if not isinstance(kind, str) or not kind:
        errors.append("spec.transport.kind is required")
    elif kind not in KNOWN_TRANSPORT_KINDS:
        errors.append(f"unsupported spec.transport.kind: {kind}")
    elif kind not in CURRENT_EXECUTOR_TRANSPORTS:
        warnings.append(f"transport kind is recognized but not executable in current MVP: {kind}")
    command = raw.get("command")
    if not isinstance(command, str) or not command.strip():
        errors.append("spec.transport.command is required")
    args_template = raw.get("argsTemplate", [])
    if not isinstance(args_template, list) or not all(isinstance(item, str) for item in args_template):
        errors.append("spec.transport.argsTemplate must be a list of strings when present")
    cwd_policy = raw.get("cwdPolicy", "workspace")
    if not isinstance(cwd_policy, str) or not cwd_policy:
        errors.append("spec.transport.cwdPolicy must be a string when present")
    timeout = raw.get("timeoutSeconds", 30)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        errors.append("spec.transport.timeoutSeconds must be a positive integer when present")


def _parse_timeout_seconds(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError("spec.transport.timeoutSeconds must be a positive integer")
    return value


def _validate_policy(raw: Any, errors: list[str]) -> None:
    if not isinstance(raw, dict):
        errors.append("spec.policy must be an object")
        return
    risk = raw.get("risk")
    if risk not in VALID_MANIFEST_RISKS:
        errors.append(f"unknown spec.policy.risk: {risk}")
    if "requiresConfirmation" in raw and not isinstance(raw.get("requiresConfirmation"), bool):
        errors.append("spec.policy.requiresConfirmation must be a boolean when present")
    network = raw.get("network", "deny")
    if network not in VALID_NETWORK_POLICIES:
        errors.append(f"unknown spec.policy.network: {network}")
    if risk == "external-network" and network != "requires-confirmation":
        errors.append("external-network risk must use network=requires-confirmation")


def _validate_output(
    raw: Any,
    errors: list[str],
    warnings: list[str],
    known_parser_refs: set[str] | None,
) -> None:
    if not isinstance(raw, dict):
        errors.append("spec.output must be an object when present")
        return
    parser_ref = raw.get("parserRef")
    if parser_ref is not None and not isinstance(parser_ref, str):
        errors.append("spec.output.parserRef must be a string when present")
    if isinstance(parser_ref, str) and known_parser_refs is not None and parser_ref not in known_parser_refs:
        errors.append(f"unknown spec.output.parserRef: {parser_ref}")
    if parser_ref is None:
        warnings.append("spec.output.parserRef is missing; raw.text parser will be used")
    if "verified" in raw and not isinstance(raw.get("verified"), bool):
        errors.append("spec.output.verified must be a boolean when present")
    if raw.get("verified") is False:
        warnings.append("spec.output.verified=false; parser/output contract is not verified")


def _mark_duplicate_capability_ids(reports: list[dict[str, Any]]) -> None:
    by_id: dict[str, list[dict[str, Any]]] = {}
    for report in reports:
        capability_id = report.get("capability_id")
        if isinstance(capability_id, str) and capability_id:
            by_id.setdefault(capability_id, []).append(report)
    for capability_id, matches in by_id.items():
        if len(matches) < 2:
            continue
        for report in matches:
            report["errors"].append(f"duplicate capability_id in validation set: {capability_id}")
            report["valid"] = False


def _manifest_report(
    source_path: Path | None,
    capability_id: Any,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "valid": not errors,
        "source_path": str(source_path) if source_path else None,
        "capability_id": capability_id,
        "errors": errors,
        "warnings": warnings,
    }
