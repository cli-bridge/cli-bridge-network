"""Config loader.

The first skeleton keeps config stdlib-only. JSON is supported immediately;
YAML parsing can be added once dependency policy is settled.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cbn_config.types import CbnConfig


def load_config(path: Path | None = None) -> CbnConfig:
    if path is None or not path.exists():
        return CbnConfig()
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return CbnConfig(
        project_name=raw.get("project_name", CbnConfig.project_name),
        command_name=raw.get("command_name", CbnConfig.command_name),
        default_transport=raw.get("default_transport", CbnConfig.default_transport),
        enabled_exports=tuple(raw.get("enabled_exports", CbnConfig.enabled_exports)),
        feature_flags=dict(raw.get("feature_flags", {})),
    )

