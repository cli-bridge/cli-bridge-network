"""Import AgentCliCard descriptors into CBN ToolManifest drafts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from cbn.paths import resolve_project_paths
from cbn_core.agent_cli_contract import agent_cli_card_to_tool_manifests
from cbn_core.manifest import MANIFEST_API_VERSION, validate_manifest_dict


def agent_cli_card_import_report(
    card_path: Path,
    *,
    write: bool = False,
    output_dir: Path | None = None,
    known_parser_refs: set[str] | None = None,
) -> dict[str, Any]:
    """Return ToolManifest drafts for an external AgentCliCard and optionally write them."""

    card = json.loads(card_path.read_text(encoding="utf-8"))
    manifests = agent_cli_card_to_tool_manifests(card)
    validation_parser_refs = _validation_parser_refs(manifests, known_parser_refs)
    output_root = output_dir or resolve_project_paths().local_manifests
    entries, errors = _import_entries(
        manifests,
        output_root=output_root,
        write=write,
        known_parser_refs=validation_parser_refs,
    )
    summary = _summary(entries, errors)
    return {
        "ok": bool(entries) and summary["valid_count"] == len(entries) and not errors,
        "kind": "AgentCliCardImportReport",
        "apiVersion": MANIFEST_API_VERSION,
        "card_id": _card_id(card),
        "card_path": str(card_path),
        "write": write,
        "write_requested": write,
        "written": summary["written_count"] > 0,
        "manifest_count": len(entries),
        "output_dir": str(output_root),
        "summary": summary,
        "errors": errors,
        "manifests": entries,
        "next_commands": _next_commands(entries, write=write, card_path=card_path, output_root=output_root),
    }


def _import_entries(
    manifests: list[dict[str, Any]],
    *,
    output_root: Path,
    write: bool,
    known_parser_refs: set[str] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    entries = []
    errors = []
    for manifest in manifests:
        entry = _import_entry(manifest, output_root=output_root, write=write, known_parser_refs=known_parser_refs)
        if entry["error"]:
            errors.append({"capability_id": entry["capability_id"], "error": entry["error"]})
        entries.append(entry)
    return entries, errors


def _import_entry(
    manifest: dict[str, Any],
    *,
    output_root: Path,
    write: bool,
    known_parser_refs: set[str] | None,
) -> dict[str, Any]:
    capability_id = manifest["metadata"]["id"]
    target = output_root / f"{_safe_filename(capability_id)}.json"
    validation = validate_manifest_dict(manifest, source_path=target, known_parser_refs=known_parser_refs)
    written = _write_manifest_if_valid(manifest, target, write=write, valid=bool(validation["valid"]))
    error = "manifest validation failed" if write and not validation["valid"] else None
    return {
        "capability_id": capability_id,
        "target_path": str(target),
        "written": written,
        "error": error,
        "validation": validation,
        "manifest": manifest,
    }


def _write_manifest_if_valid(manifest: dict[str, Any], target: Path, *, write: bool, valid: bool) -> bool:
    if not write or not valid:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def _summary(entries: list[dict[str, Any]], errors: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "manifest_count": len(entries),
        "valid_count": sum(1 for entry in entries if entry["validation"]["valid"]),
        "written_count": sum(1 for entry in entries if entry["written"]),
        "error_count": len(errors),
    }


def _card_id(card: dict[str, Any]) -> str | None:
    metadata = card.get("metadata") if isinstance(card.get("metadata"), dict) else {}
    return metadata.get("id")


def _next_commands(entries: list[dict[str, Any]], *, write: bool, card_path: Path, output_root: Path) -> list[str]:
    if write:
        return [
            f"python -m cbn registry inspect {entry['capability_id']}"
            for entry in entries
            if entry.get("written")
        ]
    return [
        f"python -m cbn import agent-cli-card --card-file {card_path} --output-dir {output_root} --write",
    ]


def _safe_filename(capability_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", capability_id).strip("-") or "capability"


def _validation_parser_refs(
    manifests: list[dict[str, Any]],
    known_parser_refs: set[str] | None,
) -> set[str] | None:
    if known_parser_refs is None:
        return None
    refs = set(known_parser_refs)
    for manifest in manifests:
        output = manifest.get("spec", {}).get("output", {})
        if isinstance(output, dict) and isinstance(output.get("parserRef"), str):
            refs.add(output["parserRef"])
    return refs
