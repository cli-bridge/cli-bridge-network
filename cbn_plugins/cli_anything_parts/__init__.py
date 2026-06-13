"""Extracted implementation parts for the CLI-Anything plugin facade."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


EXPECTED_PART_MODULES = (
    "market",
    "probe",
    "manifest_factory",
    "repair",
    "verification",
    "onboarding",
    "lifecycle",
    "adaptation",
    "planning",
    "adapter_targets",
    "live",
    "queue",
    "promotion",
    "sync",
)


def module_split_report(*, facade_path: Path | None = None) -> dict[str, Any]:
    """Return a machine-readable report for the CLI-Anything facade split."""

    parts = [_part_module_status(module_name) for module_name in EXPECTED_PART_MODULES]
    facade_lines = _line_count(facade_path) if facade_path else None
    present_count = sum(1 for part in parts if part["present"])
    return _module_split_payload(facade_path, facade_lines, parts, present_count)


def _part_module_status(module_name: str) -> dict[str, Any]:
    qualified_name = f"{__name__}.{module_name}"
    spec = importlib.util.find_spec(qualified_name)
    path = Path(spec.origin) if spec and spec.origin else None
    return {
        "id": module_name,
        "module": qualified_name,
        "present": path is not None and path.exists(),
        "path": str(path) if path else None,
    }


def _module_split_payload(
    facade_path: Path | None,
    facade_lines: int | None,
    parts: list[dict[str, Any]],
    present_count: int,
) -> dict[str, Any]:
    return {
        "kind": "CliAnythingModuleSplitReport",
        "status": "ready" if present_count == len(EXPECTED_PART_MODULES) else "incomplete",
        "facade_module": "cbn_plugins.cli_anything",
        "facade_path": str(facade_path) if facade_path else None,
        "facade_line_count": facade_lines,
        "expected_part_count": len(EXPECTED_PART_MODULES),
        "present_part_count": present_count,
        "parts": parts,
        "strategy": "keep cbn_plugins.cli_anything as compatibility facade while moving implementation to parts modules",
        "next_targets": [
            "route remaining pure helper functions behind existing parts modules",
            "reduce facade to public API orchestration only",
            "preserve CliAnythingHub import compatibility until downstream callers migrate",
        ],
    }


def _line_count(path: Path | None) -> int | None:
    if path is None or not path.exists():
        return None
    return len(path.read_text(encoding="utf-8").splitlines())
