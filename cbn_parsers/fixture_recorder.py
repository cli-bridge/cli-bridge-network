"""Record parser fixture files from observed CLI stdout/stderr."""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cbn_parsers.fixtures import DEFAULT_FIXTURE_DIR, run_parser_fixture_file
from cbn_parsers.registry import ParserRegistry


@dataclass(frozen=True)
class ParserFixtureInput:
    parser_ref: str
    case_id: str
    stdout: str
    stderr: str
    title: str | None
    fixture_id: str | None
    verified_capabilities: tuple[str, ...]
    expect_failure: bool
    error_contains: str | None
    registry: ParserRegistry


_RECORD_OPTION_NAMES = (
    "title",
    "fixture_id",
    "verified_capabilities",
    "expect_failure",
    "error_contains",
    "output_path",
    "write",
    "registry",
)


def record_parser_fixture(
    parser_ref: str,
    case_id: str | None = None,
    stdout: str = "",
    stderr: str = "",
    *args: Any,
    **options: Any,
) -> dict[str, Any]:
    """Build and optionally write a parser fixture from observed command output."""

    if case_id is None:
        raise TypeError("case_id is required")
    options = _record_options(args, options)
    registry = options["registry"] or ParserRegistry.builtins()
    request = _parser_fixture_input(parser_ref, case_id, stdout, stderr, registry, options)
    fixture = build_parser_fixture(request)
    target = options["output_path"] or default_fixture_path(parser_ref, case_id)
    validation = _validate_fixture(fixture, registry)
    written = False
    if options["write"]:
        if not validation["ok"]:
            return _report(fixture, target, validation, written=False, error="fixture validation failed")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written = True
    return _report(fixture, target, validation, written=written)


def _record_options(args: tuple[Any, ...], options: dict[str, Any]) -> dict[str, Any]:
    if len(args) > len(_RECORD_OPTION_NAMES):
        raise TypeError(f"record_parser_fixture expected at most {len(_RECORD_OPTION_NAMES) + 4} arguments")
    resolved = _default_record_options()
    for name, value in zip(_RECORD_OPTION_NAMES, args):
        if name in options:
            raise TypeError(f"record_parser_fixture got multiple values for argument '{name}'")
        resolved[name] = value
    unknown = sorted(set(options) - set(_RECORD_OPTION_NAMES))
    if unknown:
        raise TypeError(f"unknown parser fixture option(s): {', '.join(unknown)}")
    resolved.update(options)
    return resolved


def _default_record_options() -> dict[str, Any]:
    return {
        "title": None,
        "fixture_id": None,
        "verified_capabilities": (),
        "expect_failure": False,
        "error_contains": None,
        "output_path": None,
        "write": False,
        "registry": None,
    }


def _parser_fixture_input(
    parser_ref: str,
    case_id: str,
    stdout: str,
    stderr: str,
    registry: ParserRegistry,
    options: dict[str, Any],
) -> ParserFixtureInput:
    return ParserFixtureInput(
        parser_ref=parser_ref,
        case_id=case_id,
        stdout=stdout,
        stderr=stderr,
        title=options["title"],
        fixture_id=options["fixture_id"],
        verified_capabilities=tuple(options["verified_capabilities"]),
        expect_failure=bool(options["expect_failure"]),
        error_contains=options["error_contains"],
        registry=registry,
    )


def build_parser_fixture(request: ParserFixtureInput) -> dict[str, Any]:
    expected = (
        _expected_failure(request.error_contains)
        if request.expect_failure
        else _expected_success(request.parser_ref, request.stdout, request.stderr, request.registry)
    )
    return {
        "apiVersion": "bridge.dev/v1alpha1",
        "kind": "ParserFixture",
        "metadata": {
            "id": request.fixture_id or f"{_safe_id(request.parser_ref)}.{_safe_id(request.case_id)}",
            "title": request.title or f"{request.parser_ref} {request.case_id}",
            "parserRef": request.parser_ref,
            "verifiedCapabilities": list(request.verified_capabilities),
        },
        "cases": [
            {
                "id": request.case_id,
                "stdout": request.stdout,
                "stderr": request.stderr,
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
