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
)


def module_split_report(*, facade_path: Path | None = None) -> dict[str, Any]:
    """Return a machine-readable report for the CLI-Anything facade split."""

    package_name = __name__
    parts: list[dict[str, Any]] = []
    for module_name in EXPECTED_PART_MODULES:
        spec = importlib.util.find_spec(f"{package_name}.{module_name}")
        path = Path(spec.origin) if spec and spec.origin else None
        parts.append(
            {
                "id": module_name,
                "module": f"{package_name}.{module_name}",
                "present": path is not None and path.exists(),
                "path": str(path) if path else None,
            }
        )

    facade_lines = _line_count(facade_path) if facade_path else None
    present_count = sum(1 for part in parts if part["present"])
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
