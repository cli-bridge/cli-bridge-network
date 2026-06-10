"""Import a skill descriptor into a CBN ToolManifest draft."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from cbn_core.command_importer import command_import_report


def skill_import_report(
    skill_file: Path,
    command: str,
    args_template: tuple[str, ...] = (),
    capability_id: str | None = None,
    title: str | None = None,
    parser_ref: str = "raw.text",
    verified: bool = False,
    risk: str = "read",
    requires_confirmation: bool = False,
    network: str = "deny",
    timeout_seconds: int = 60,
    write: bool = False,
    output_path: Path | None = None,
    known_parser_refs: set[str] | None = None,
) -> dict[str, Any]:
    """Return a manifest import report for a local skill descriptor."""

    descriptor = read_skill_descriptor(skill_file)
    skill_id = str(descriptor.get("id") or _safe_id(skill_file.stem))
    resolved_capability_id = capability_id or f"skill.{_safe_id(skill_id)}"
    resolved_title = title or str(descriptor.get("title") or descriptor.get("name") or skill_id)
    annotations = {
        "cbn.import.kind": "skill",
        "cbn.skill.id": skill_id,
        "cbn.skill.source_path": str(skill_file),
        "cbn.skill.summary": str(descriptor.get("summary") or descriptor.get("description") or "")[:500],
    }
    if descriptor.get("version") is not None:
        annotations["cbn.skill.version"] = str(descriptor["version"])
    labels = {"source": "skill", "skill": _safe_id(skill_id)}
    result = command_import_report(
        capability_id=resolved_capability_id,
        command=command,
        args_template=args_template,
        title=resolved_title,
        parser_ref=parser_ref,
        verified=verified,
        risk=risk,
        requires_confirmation=requires_confirmation,
        network=network,
        timeout_seconds=timeout_seconds,
        labels=labels,
        annotations=annotations,
        write=write,
        output_path=output_path,
        known_parser_refs=known_parser_refs,
    )
    return {
        **result,
        "kind": "SkillImportReport",
        "skill": descriptor,
        "skill_file": str(skill_file),
        "entrypoint": "cbn import skill",
        "next_commands": _next_commands(
            capability_id=resolved_capability_id,
            skill_file=skill_file,
            command=command,
            written=bool(result["written"]),
        ),
    }


def read_skill_descriptor(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.casefold()
    if suffix == ".json" or text.lstrip().startswith("{"):
        raw = json.loads(text)
        if not isinstance(raw, dict):
            raise ValueError("skill JSON descriptor must be an object")
        return _normalize_descriptor(raw, fallback_id=path.stem)
    return _descriptor_from_markdown(text, fallback_id=path.stem)


def _normalize_descriptor(raw: dict[str, Any], fallback_id: str) -> dict[str, Any]:
    descriptor = dict(raw)
    descriptor.setdefault("id", fallback_id)
    if "title" not in descriptor and "name" in descriptor:
        descriptor["title"] = descriptor["name"]
    return descriptor


def _descriptor_from_markdown(text: str, fallback_id: str) -> dict[str, Any]:
    title = None
    summary_lines: list[str] = []
    frontmatter = _frontmatter(text)
    body = text
    if frontmatter:
        body = text.split("---", 2)[2]
    for line in body.splitlines():
        stripped = line.strip()
        if title is None and stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            continue
        if stripped and not stripped.startswith("#") and len(summary_lines) < 3:
            summary_lines.append(stripped)
    descriptor: dict[str, Any] = {
        "id": str(frontmatter.get("id") or fallback_id),
        "title": str(frontmatter.get("title") or frontmatter.get("name") or title or fallback_id),
        "summary": str(frontmatter.get("summary") or " ".join(summary_lines)),
    }
    if "version" in frontmatter:
        descriptor["version"] = str(frontmatter["version"])
    return descriptor


def _frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    values: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key:
            values[key] = value.strip().strip('"').strip("'")
    return values


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-").casefold() or "skill"


def _next_commands(capability_id: str, skill_file: Path, command: str, written: bool) -> list[str]:
    if written:
        return [
            f"python -m cbn registry inspect {capability_id}",
            f"python -m cbn call {capability_id} --dry-run",
        ]
    return [
        f"python -m cbn import skill {skill_file} --command {command} --write",
        f"python -m cbn protocol export all --capability-id {capability_id}",
    ]
