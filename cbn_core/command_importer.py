"""Helpers for turning a plain CLI command into a ToolManifest."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cbn.paths import resolve_project_paths
from cbn_core.manifest import MANIFEST_API_VERSION, validate_manifest_dict


@dataclass(frozen=True)
class CommandManifestSpec:
    capability_id: str
    command: str
    args_template: tuple[str, ...] = ()
    title: str | None = None
    transport: str = "stdio"
    parser_ref: str = "raw.text"
    verified: bool = False
    risk: str = "read"
    requires_confirmation: bool = False
    network: str = "deny"
    cwd_policy: str = "workspace"
    timeout_seconds: int = 30
    labels: dict[str, str] | None = None
    annotations: dict[str, str] | None = None


@dataclass(frozen=True)
class CommandImportRequest:
    manifest: CommandManifestSpec
    write: bool = False
    output_path: Path | None = None
    known_parser_refs: set[str] | None = None


def build_command_manifest(spec: CommandManifestSpec) -> dict[str, Any]:
    """Build a ToolManifest dict for the lowest-friction CLI onboarding path."""

    return {
        "apiVersion": MANIFEST_API_VERSION,
        "kind": "ToolManifest",
        "metadata": _command_metadata(spec),
        "spec": {
            "transport": _command_transport(spec),
            "policy": _command_policy(spec),
            "output": _command_output(spec),
        },
    }


def command_import_report(**kwargs: Any) -> dict[str, Any]:
    """Return a validation report and optionally write the generated manifest."""

    request = command_import_request(**kwargs)
    manifest = build_command_manifest(request.manifest)
    target = request.output_path or _default_manifest_path(request.manifest.capability_id)
    validation = validate_manifest_dict(manifest, source_path=target, known_parser_refs=request.known_parser_refs)
    return _write_or_report(manifest, validation, target, write=request.write)


def command_import_request(**kwargs: Any) -> CommandImportRequest:
    manifest_keys = set(CommandManifestSpec.__dataclass_fields__)
    request_keys = {"write", "output_path", "known_parser_refs"}
    unknown = sorted(set(kwargs) - manifest_keys - request_keys)
    if unknown:
        raise TypeError(f"unknown command import option(s): {', '.join(unknown)}")
    manifest_values = {key: kwargs[key] for key in manifest_keys if key in kwargs}
    manifest_values["args_template"] = tuple(manifest_values.get("args_template", ()))
    return CommandImportRequest(
        manifest=CommandManifestSpec(**manifest_values),
        write=bool(kwargs.get("write", False)),
        output_path=kwargs.get("output_path"),
        known_parser_refs=kwargs.get("known_parser_refs"),
    )


def _command_metadata(spec: CommandManifestSpec) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "id": spec.capability_id,
        "title": spec.title or _title_from_id(spec.capability_id),
    }
    if spec.labels:
        metadata["labels"] = dict(sorted(spec.labels.items()))
    if spec.annotations:
        metadata["annotations"] = dict(sorted(spec.annotations.items()))
    return metadata


def _command_transport(spec: CommandManifestSpec) -> dict[str, Any]:
    return {
        "kind": spec.transport,
        "command": spec.command,
        "argsTemplate": list(spec.args_template),
        "cwdPolicy": spec.cwd_policy,
        "timeoutSeconds": spec.timeout_seconds,
    }


def _command_policy(spec: CommandManifestSpec) -> dict[str, Any]:
    return {
        "risk": spec.risk,
        "requiresConfirmation": spec.requires_confirmation,
        "network": spec.network,
    }


def _command_output(spec: CommandManifestSpec) -> dict[str, Any]:
    return {
        "parserRef": spec.parser_ref,
        "verified": spec.verified,
    }


def parse_key_values(values: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"expected KEY=VALUE: {value}")
        key, raw = value.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"empty key in KEY=VALUE value: {value}")
        parsed[key] = raw
    return parsed


def _write_or_report(
    manifest: dict[str, Any],
    validation: dict[str, Any],
    target: Path,
    *,
    write: bool,
) -> dict[str, Any]:
    if not write:
        return _report(manifest, validation, target, written=False)
    if not validation["valid"]:
        return _report(manifest, validation, target, written=False, error="manifest validation failed")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return _report(manifest, validation, target, written=True)


def _report(
    manifest: dict[str, Any],
    validation: dict[str, Any],
    target: Path,
    written: bool,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "ok": bool(validation["valid"]) and error is None,
        "kind": "CommandImportReport",
        "apiVersion": MANIFEST_API_VERSION,
        "capability_id": manifest["metadata"]["id"],
        "target_path": str(target),
        "written": written,
        "error": error,
        "validation": validation,
        "manifest": manifest,
        "next_commands": [
            f"python -m cbn registry inspect {manifest['metadata']['id']}",
            f"python -m cbn call {manifest['metadata']['id']} --dry-run",
        ]
        if written
        else [
            f"python -m cbn import command {manifest['metadata']['id']} --command {manifest['spec']['transport']['command']} --write",
        ],
    }


def _default_manifest_path(capability_id: str) -> Path:
    paths = resolve_project_paths()
    return paths.local_manifests / f"{_safe_filename(capability_id)}.json"


def _safe_filename(capability_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", capability_id).strip("-") or "capability"


def _title_from_id(capability_id: str) -> str:
    return capability_id.replace(".", " ").replace("-", " ").replace("_", " ").title()
