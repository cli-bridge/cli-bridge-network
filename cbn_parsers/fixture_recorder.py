"""Record parser fixture files from observed CLI stdout/stderr."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

from cbn_parsers.fixtures import DEFAULT_FIXTURE_DIR, run_parser_fixture_file
from cbn_parsers.registry import ParserRegistry


def record_parser_fixture(
    parser_ref: str,
    case_id: str,
    stdout: str = "",
    stderr: str = "",
    title: str | None = None,
    fixture_id: str | None = None,
    verified_capabilities: tuple[str, ...] = (),
    expect_failure: bool = False,
    error_contains: str | None = None,
    output_path: Path | None = None,
    write: bool = False,
    registry: ParserRegistry | None = None,
) -> dict[str, Any]:
    """Build and optionally write a parser fixture from observed command output."""

    registry = registry or ParserRegistry.builtins()
    fixture = build_parser_fixture(
        parser_ref=parser_ref,
        case_id=case_id,
        stdout=stdout,
        stderr=stderr,
        title=title,
        fixture_id=fixture_id,
        verified_capabilities=verified_capabilities,
        expect_failure=expect_failure,
        error_contains=error_contains,
        registry=registry,
    )
    target = output_path or default_fixture_path(parser_ref, case_id)
    validation = _validate_fixture(fixture, registry)
    written = False
    if write:
        if not validation["ok"]:
            return _report(fixture, target, validation, written=False, error="fixture validation failed")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written = True
    return _report(fixture, target, validation, written=written)


def build_parser_fixture(
    parser_ref: str,
    case_id: str,
    stdout: str,
    stderr: str,
    title: str | None,
    fixture_id: str | None,
    verified_capabilities: tuple[str, ...],
    expect_failure: bool,
    error_contains: str | None,
    registry: ParserRegistry,
) -> dict[str, Any]:
    expected = _expected_failure(error_contains) if expect_failure else _expected_success(parser_ref, stdout, stderr, registry)
    return {
        "apiVersion": "bridge.dev/v1alpha1",
        "kind": "ParserFixture",
        "metadata": {
            "id": fixture_id or f"{_safe_id(parser_ref)}.{_safe_id(case_id)}",
            "title": title or f"{parser_ref} {case_id}",
            "parserRef": parser_ref,
            "verifiedCapabilities": list(verified_capabilities),
        },
        "cases": [
            {
                "id": case_id,
                "stdout": stdout,
                "stderr": stderr,
                "expect": expected,
            }
        ],
    }


def default_fixture_path(parser_ref: str, case_id: str) -> Path:
    return DEFAULT_FIXTURE_DIR / f"{_safe_id(parser_ref)}.{_safe_id(case_id)}.json"


def _expected_success(parser_ref: str, stdout: str, stderr: str, registry: ParserRegistry) -> dict[str, Any]:
    parsed = registry.parse(parser_ref, stdout, stderr)
    return {"ok": True, "data": _data_expectations(parsed.get("data", {}))}


def _expected_failure(error_contains: str | None) -> dict[str, Any]:
    expected: dict[str, Any] = {"ok": False}
    if error_contains:
        expected["errorContains"] = error_contains
    return expected


def _data_expectations(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    expectations: dict[str, Any] = {}
    for key, value in sorted(data.items()):
        if isinstance(value, str):
            expectations[key] = {"equals": value}
        elif isinstance(value, (int, float, bool)) or value is None:
            expectations[key] = value
    return expectations


def _validate_fixture(fixture: dict[str, Any], registry: ParserRegistry) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "fixture.json"
        path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return run_parser_fixture_file(path, registry=registry)


def _report(
    fixture: dict[str, Any],
    target: Path,
    validation: dict[str, Any],
    written: bool,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "ok": bool(validation["ok"]) and error is None,
        "kind": "ParserFixtureRecordReport",
        "apiVersion": "bridge.dev/v1alpha1",
        "parser_ref": fixture["metadata"]["parserRef"],
        "case_id": fixture["cases"][0]["id"],
        "target_path": str(target),
        "written": written,
        "error": error,
        "validation": validation,
        "fixture": fixture,
        "next_commands": [
            f"python -m cbn parser fixtures {target}",
            f"python -m cbn parser fixtures --parser-ref {fixture['metadata']['parserRef']}",
        ]
        if written
        else [
            (
                "python -m cbn record-parser-fixture "
                f"{fixture['metadata']['parserRef']} {fixture['cases'][0]['id']} --write"
            )
        ],
    }


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "fixture"
