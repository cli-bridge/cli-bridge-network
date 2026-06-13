"""Import a skill descriptor into a CBN ToolManifest draft."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cbn_core.command_importer import command_import_report


@dataclass(frozen=True)
class _SkillImportContext:
    descriptor: dict[str, Any]
    skill_file: Path
    skill_id: str
    capability_id: str
    title: str


@dataclass(frozen=True)
class _SkillImportOptions:
    command: str
    args_template: tuple[str, ...] = ()
    capability_id: str | None = None
    title: str | None = None
    parser_ref: str = "raw.text"
    verified: bool = False
    risk: str = "read"
    requires_confirmation: bool = False
    network: str = "deny"
    timeout_seconds: int = 60
    write: bool = False
    output_path: Path | None = None
    known_parser_refs: set[str] | None = None


def skill_import_report(skill_file: Path, **kwargs: Any) -> dict[str, Any]:
    """Return a manifest import report for a local skill descriptor."""

    options = _skill_import_options(**kwargs)
    context = _skill_import_context(skill_file, capability_id=options.capability_id, title=options.title)
    result = _command_import(context, options)
    return _skill_import_payload(result, context=context, skill_file=skill_file, command=options.command)


def _skill_import_options(**kwargs: Any) -> _SkillImportOptions:
    unknown = sorted(set(kwargs) - set(_SkillImportOptions.__dataclass_fields__))
    if unknown:
        raise TypeError(f"unknown skill import option(s): {', '.join(unknown)}")
    values = dict(kwargs)
    values["args_template"] = tuple(values.get("args_template", ()))
    return _SkillImportOptions(**values)


def _skill_import_context(skill_file: Path, *, capability_id: str | None, title: str | None) -> _SkillImportContext:
    descriptor = read_skill_descriptor(skill_file)
    skill_id = str(descriptor.get("id") or _safe_id(skill_file.stem))
    return _SkillImportContext(
        descriptor=descriptor,
        skill_file=skill_file,
        skill_id=skill_id,
        capability_id=capability_id or f"skill.{_safe_id(skill_id)}",
        title=title or str(descriptor.get("title") or descriptor.get("name") or skill_id),
    )


def _command_import(context: _SkillImportContext, options: _SkillImportOptions) -> dict[str, Any]:
    return command_import_report(
        capability_id=context.capability_id,
        command=options.command,
        args_template=options.args_template,
        title=context.title,
        parser_ref=options.parser_ref,
        verified=options.verified,
        risk=options.risk,
        requires_confirmation=options.requires_confirmation,
        network=options.network,
        timeout_seconds=options.timeout_seconds,
        labels=_skill_labels(context.skill_id),
        annotations=_skill_annotations(context),
        write=options.write,
        output_path=options.output_path,
        known_parser_refs=options.known_parser_refs,
    )


def _skill_import_payload(
    result: dict[str, Any],
    *,
    context: _SkillImportContext,
    skill_file: Path,
    command: str,
) -> dict[str, Any]:
    return {
        **result,
        "kind": "SkillImportReport",
        "skill": context.descriptor,
        "skill_file": str(skill_file),
        "entrypoint": "cbn import skill",
        "next_commands": _next_commands(
            capability_id=context.capability_id,
            skill_file=skill_file,
            command=command,
            written=bool(result["written"]),
        ),
    }


def _skill_annotations(context: _SkillImportContext) -> dict[str, str]:
    descriptor = context.descriptor
    annotations = {
        "cbn.import.kind": "skill",
        "cbn.skill.id": context.skill_id,
        "cbn.skill.source_path": str(context.skill_file),
        "cbn.skill.summary": str(descriptor.get("summary") or descriptor.get("description") or "")[:500],
    }
    if descriptor.get("version") is not None:
        annotations["cbn.skill.version"] = str(descriptor["version"])
    return annotations


def _skill_labels(skill_id: str) -> dict[str, str]:
    return {"source": "skill", "skill": _safe_id(skill_id)}


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
    frontmatter = _frontmatter(text)
    title, summary_lines = _markdown_title_and_summary(_markdown_body(text, frontmatter))
    descriptor: dict[str, Any] = {
        "id": str(frontmatter.get("id") or fallback_id),
        "title": str(frontmatter.get("title") or frontmatter.get("name") or title or fallback_id),
        "summary": str(frontmatter.get("summary") or " ".join(summary_lines)),
    }
    if "version" in frontmatter:
        descriptor["version"] = str(frontmatter["version"])
    return descriptor


def _markdown_body(text: str, frontmatter: dict[str, str]) -> str:
    if frontmatter:
        return text.split("---", 2)[2]
    return text


def _markdown_title_and_summary(body: str) -> tuple[str | None, list[str]]:
    title = None
    summary_lines: list[str] = []
    for line in body.splitlines():
        title, added = _read_markdown_summary_line(line, title, summary_lines)
        if added:
            summary_lines.append(added)
    return title, summary_lines


def _read_markdown_summary_line(
    line: str,
    title: str | None,
    summary_lines: list[str],
) -> tuple[str | None, str | None]:
    stripped = line.strip()
    if title is None and stripped.startswith("#"):
        return stripped.lstrip("#").strip(), None
    if stripped and not stripped.startswith("#") and len(summary_lines) < 3:
        return title, stripped
    return title, None


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
