"""Status lookup helpers for CLI-Anything harnesses."""

from __future__ import annotations

import shutil
from typing import Any

from cbn_plugins.cli_anything_parts.manifest_factory import sanitize_harness_name
from cbn_plugins.cli_anything_parts.market import (
    is_installed_status,
    matches_sanitized_name,
    parse_info_fields,
)


PLUGIN_ID = "cli-anything"


def harness_status(hub: Any, harness_name: str, from_market: bool = False) -> dict[str, Any]:
    market_record = hub.market_record_for_harness(harness_name) if from_market else None
    market_name = str((market_record or {}).get("name") or harness_name)
    safe_name = sanitize_harness_name(market_name)
    capability_id = f"cli-anything.{safe_name}.launch"
    manifest_path = hub.paths.manifests / f"{capability_id}.json"
    info_result = hub.info(harness_name)
    info_fields = parse_info_fields(info_result.stdout)
    entry_point = (
        info_fields.get("entry_point")
        or str((market_record or {}).get("entry_point") or "")
        or None
    )
    status_text = info_fields.get("status")
    installed = is_installed_status(status_text)
    entrypoint_path = shutil.which(entry_point) if entry_point else None
    return {
        "plugin_id": PLUGIN_ID,
        "harness_name": harness_name,
        "market_name": market_name,
        "safe_name": safe_name,
        "capability_id": capability_id,
        "manifest_path": str(manifest_path),
        "manifest_imported": manifest_path.exists(),
        "cli_hub_available": info_result.exit_code != 127,
        "cli_hub_info": {
            "argv": list(info_result.argv),
            "exit_code": info_result.exit_code,
            "status": status_text,
            "fields": info_fields,
        },
        "market_record_available": market_record is not None,
        "market_record": market_record,
        "entry_point": entry_point,
        "entrypoint_path": entrypoint_path,
        "entrypoint_available": entrypoint_path is not None,
        "installed": installed,
        "launch_ready": bool(installed and entrypoint_path),
    }


def market_record_for_harness(hub: Any, harness_name: str) -> dict[str, Any] | None:
    result = hub.search_market(harness_name)
    if result.exit_code != 0 or not isinstance(result.parsed_json, list):
        return None
    safe_name = sanitize_harness_name(harness_name)
    candidates = [item for item in result.parsed_json if isinstance(item, dict)]
    for item in candidates:
        if matches_sanitized_name(item.get("name"), safe_name, sanitize_harness_name):
            return item
    for item in candidates:
        if matches_sanitized_name(item.get("display_name"), safe_name, sanitize_harness_name):
            return item
    return candidates[0] if candidates else None
