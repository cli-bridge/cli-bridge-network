"""Parser fixture runner for verified output contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cbn_parsers.registry import ParserRegistry


DEFAULT_FIXTURE_DIR = Path("parser_fixtures")


def run_parser_fixtures(
    path: Path = DEFAULT_FIXTURE_DIR,
    parser_ref: str | None = None,
    registry: ParserRegistry | None = None,
) -> dict[str, Any]:
    registry = registry or ParserRegistry.builtins()
    fixture_paths = _fixture_paths(path)
    reports = [
        run_parser_fixture_file(item, registry=registry)
        for item in fixture_paths
        if parser_ref is None or _fixture_parser_ref(item) == parser_ref
    ]
    case_count = sum(report["case_count"] for report in reports)
    failed_case_count = sum(report["failed_case_count"] for report in reports)
    return {
        "ok": failed_case_count == 0,
        "path": str(path),
        "parser_ref": parser_ref,
        "fixture_count": len(reports),
        "case_count": case_count,
        "passed_case_count": case_count - failed_case_count,
        "failed_case_count": failed_case_count,
        "reports": reports,
    }


def run_parser_fixture_file(path: Path, registry: ParserRegistry | None = None) -> dict[str, Any]:
    registry = registry or ParserRegistry.builtins()
    raw = json.loads(path.read_text(encoding="utf-8"))
    parser_ref = _raw_parser_ref(raw, source_path=path)
    cases = raw.get("cases", [])
    if not isinstance(cases, list):
        raise ValueError(f"{path}: cases must be a list")
    case_reports = [_run_case(registry, parser_ref, case) for case in cases]
    failed_case_count = sum(1 for report in case_reports if not report["ok"])
    return {
        "ok": failed_case_count == 0,
        "fixture_id": (raw.get("metadata") or {}).get("id"),
        "parser_ref": parser_ref,
        "source_path": str(path),
        "verified_capabilities": (raw.get("metadata") or {}).get("verifiedCapabilities", []),
        "case_count": len(case_reports),
        "failed_case_count": failed_case_count,
        "cases": case_reports,
    }


def _fixture_paths(path: Path) -> list[Path]:
    if path.is_dir():
        return sorted(path.glob("*.json"))
    return [path]


def _fixture_parser_ref(path: Path) -> str:
    return _raw_parser_ref(json.loads(path.read_text(encoding="utf-8")), source_path=path)


def _raw_parser_ref(raw: dict[str, Any], source_path: Path | None = None) -> str:
    if not isinstance(raw, dict):
        raise ValueError(f"{source_path}: parser fixture root must be an object")
    if raw.get("apiVersion") != "bridge.dev/v1alpha1":
        raise ValueError(f"{source_path}: unsupported fixture apiVersion: {raw.get('apiVersion')}")
    if raw.get("kind") != "ParserFixture":
        raise ValueError(f"{source_path}: unsupported fixture kind: {raw.get('kind')}")
    metadata = raw.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError(f"{source_path}: metadata must be an object")
    parser_ref = metadata.get("parserRef")
    if not isinstance(parser_ref, str) or not parser_ref:
        raise ValueError(f"{source_path}: metadata.parserRef is required")
    return parser_ref


def _run_case(registry: ParserRegistry, parser_ref: str, case: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(case, dict):
        return {"ok": False, "case_id": None, "errors": ["case must be an object"]}
    case_id = case.get("id")
    stdout = case.get("stdout", "")
    stderr = case.get("stderr", "")
    expected = case.get("expect", {})
    if not isinstance(stdout, str) or not isinstance(stderr, str):
        return {"ok": False, "case_id": case_id, "errors": ["stdout and stderr must be strings"]}
    if not isinstance(expected, dict):
        return {"ok": False, "case_id": case_id, "errors": ["expect must be an object"]}
    expect_ok = bool(expected.get("ok", True))
    try:
        parsed = registry.parse(parser_ref, stdout, stderr)
    except Exception as exc:
        if expect_ok:
            return {"ok": False, "case_id": case_id, "errors": [str(exc)]}
        errors = _check_error_expectations(str(exc), expected)
        return {
            "ok": not errors,
            "case_id": case_id,
            "expected_failure": True,
            "error": str(exc),
            "errors": errors,
        }
    if not expect_ok:
        return {
            "ok": False,
            "case_id": case_id,
            "errors": ["parser succeeded but fixture expected failure"],
        }
    errors = _check_data_expectations(parsed.get("data", {}), expected.get("data", {}))
    return {
        "ok": not errors,
        "case_id": case_id,
        "parser_ref": parsed.get("parser_ref"),
        "errors": errors,
    }


def _check_error_expectations(error: str, expected: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    contains = expected.get("errorContains")
    if isinstance(contains, str) and contains not in error:
        errors.append(f"error does not contain {contains!r}")
    return errors


def _check_data_expectations(data: dict[str, Any], expected: Any) -> list[str]:
    if not isinstance(expected, dict):
        return ["expect.data must be an object when present"]
    errors: list[str] = []
    for field, expectation in expected.items():
        value = data.get(field)
        if isinstance(expectation, dict):
            errors.extend(_check_string_expectations(field, value, expectation))
        elif value != expectation:
            errors.append(f"data.{field} expected {expectation!r}, got {value!r}")
    return errors


def _check_string_expectations(field: str, value: Any, expectation: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, str):
        return [f"data.{field} must be a string"]
    if "equals" in expectation and value != expectation["equals"]:
        errors.append(f"data.{field} expected exact value {expectation['equals']!r}")
    contains = expectation.get("contains", [])
    if isinstance(contains, str):
        contains = [contains]
    if not isinstance(contains, list) or not all(isinstance(item, str) for item in contains):
        errors.append(f"data.{field}.contains must be a string or list of strings")
    else:
        for needle in contains:
            if needle not in value:
                errors.append(f"data.{field} does not contain {needle!r}")
    return errors
