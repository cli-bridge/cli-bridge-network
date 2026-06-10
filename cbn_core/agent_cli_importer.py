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
    entries = []
    errors = []
    for manifest in manifests:
        target = output_root / f"{_safe_filename(manifest['metadata']['id'])}.json"
        validation = validate_manifest_dict(manifest, source_path=target, known_parser_refs=validation_parser_refs)
        written = False
        error = None
        if write:
            if not validation["valid"]:
                error = "manifest validation failed"
                errors.append({"capability_id": manifest["metadata"]["id"], "error": error})
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                written = True
        entries.append(
            {
                "capability_id": manifest["metadata"]["id"],
                "target_path": str(target),
                "written": written,
                "error": error,
                "validation": validation,
                "manifest": manifest,
            }
        )
    valid_count = sum(1 for entry in entries if entry["validation"]["valid"])
    written_count = sum(1 for entry in entries if entry["written"])
    ok = bool(entries) and valid_count == len(entries) and not errors
    card_metadata = card.get("metadata") if isinstance(card.get("metadata"), dict) else {}
    return {
        "ok": ok,
        "kind": "AgentCliCardImportReport",
        "apiVersion": MANIFEST_API_VERSION,
        "card_id": card_metadata.get("id"),
        "card_path": str(card_path),
        "write": write,
        "write_requested": write,
        "written": written_count > 0,
        "manifest_count": len(entries),
        "output_dir": str(output_root),
        "summary": {
            "manifest_count": len(entries),
            "valid_count": valid_count,
            "written_count": written_count,
            "error_count": len(errors),
        },
        "errors": errors,
        "manifests": entries,
        "next_commands": _next_commands(entries, write=write, card_path=card_path, output_root=output_root),
    }


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
