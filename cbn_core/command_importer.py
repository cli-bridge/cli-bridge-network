"""Helpers for turning a plain CLI command into a ToolManifest."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from cbn.paths import resolve_project_paths
from cbn_core.manifest import MANIFEST_API_VERSION, validate_manifest_dict


def build_command_manifest(
    capability_id: str,
    command: str,
    args_template: tuple[str, ...] = (),
    title: str | None = None,
    transport: str = "stdio",
    parser_ref: str = "raw.text",
    verified: bool = False,
    risk: str = "read",
    requires_confirmation: bool = False,
    network: str = "deny",
    cwd_policy: str = "workspace",
    timeout_seconds: int = 30,
    labels: dict[str, str] | None = None,
    annotations: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a ToolManifest dict for the lowest-friction CLI onboarding path."""

    metadata: dict[str, Any] = {
        "id": capability_id,
        "title": title or _title_from_id(capability_id),
    }
    if labels:
        metadata["labels"] = dict(sorted(labels.items()))
    if annotations:
        metadata["annotations"] = dict(sorted(annotations.items()))
    return {
        "apiVersion": MANIFEST_API_VERSION,
        "kind": "ToolManifest",
        "metadata": metadata,
        "spec": {
            "transport": {
                "kind": transport,
                "command": command,
                "argsTemplate": list(args_template),
                "cwdPolicy": cwd_policy,
                "timeoutSeconds": timeout_seconds,
            },
            "policy": {
                "risk": risk,
                "requiresConfirmation": requires_confirmation,
                "network": network,
            },
            "output": {
                "parserRef": parser_ref,
                "verified": verified,
            },
        },
    }


def command_import_report(
    capability_id: str,
    command: str,
    args_template: tuple[str, ...] = (),
    title: str | None = None,
    transport: str = "stdio",
    parser_ref: str = "raw.text",
    verified: bool = False,
    risk: str = "read",
    requires_confirmation: bool = False,
    network: str = "deny",
    cwd_policy: str = "workspace",
    timeout_seconds: int = 30,
    labels: dict[str, str] | None = None,
    annotations: dict[str, str] | None = None,
    write: bool = False,
    output_path: Path | None = None,
    known_parser_refs: set[str] | None = None,
) -> dict[str, Any]:
    """Return a validation report and optionally write the generated manifest."""

    manifest = build_command_manifest(
        capability_id=capability_id,
        command=command,
        args_template=args_template,
        title=title,
        transport=transport,
        parser_ref=parser_ref,
        verified=verified,
        risk=risk,
        requires_confirmation=requires_confirmation,
        network=network,
        cwd_policy=cwd_policy,
        timeout_seconds=timeout_seconds,
        labels=labels,
        annotations=annotations,
    )
    target = output_path or _default_manifest_path(capability_id)
    validation = validate_manifest_dict(manifest, source_path=target, known_parser_refs=known_parser_refs)
    written = False
    if write:
        if not validation["valid"]:
            return _report(manifest, validation, target, written=False, error="manifest validation failed")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        written = True
    return _report(manifest, validation, target, written=written)


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
