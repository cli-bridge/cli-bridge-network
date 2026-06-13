"""Status lookup helpers for CLI-Anything harnesses."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cbn_plugins.cli_anything_parts.manifest_factory import sanitize_harness_name
from cbn_plugins.cli_anything_parts.market import (
    is_installed_status,
    matches_sanitized_name,
    parse_info_fields,
)


PLUGIN_ID = "cli-anything"


@dataclass(frozen=True)
class HarnessStatusPayloadInput:
    harness_name: str
    market_name: str
    safe_name: str
    capability_id: str
    manifest_path: Path
    info_result: Any
    info_fields: dict[str, str]
    status_text: str | None
    market_record: dict[str, Any] | None
    entry_point: str | None
    entrypoint_path: str | None
    installed: bool


def harness_status(hub: Any, harness_name: str, from_market: bool = False) -> dict[str, Any]:
    market_record = hub.market_record_for_harness(harness_name) if from_market else None
    market_name = str((market_record or {}).get("name") or harness_name)
    safe_name = sanitize_harness_name(market_name)
    capability_id = f"cli-anything.{safe_name}.launch"
    manifest_path = hub.paths.manifests / f"{capability_id}.json"
    info_result = hub.info(harness_name)
    info_fields = parse_info_fields(info_result.stdout)
    entry_point = _entry_point(info_fields, market_record)
    status_text = info_fields.get("status")
    installed = is_installed_status(status_text)
    entrypoint_path = shutil.which(entry_point) if entry_point else None
    return _harness_status_payload(HarnessStatusPayloadInput(
        harness_name=harness_name,
        market_name=market_name,
        safe_name=safe_name,
        capability_id=capability_id,
        manifest_path=manifest_path,
        info_result=info_result,
        info_fields=info_fields,
        status_text=status_text,
        market_record=market_record,
        entry_point=entry_point,
        entrypoint_path=entrypoint_path,
        installed=installed,
    ))


def _entry_point(info_fields: dict[str, str], market_record: dict[str, Any] | None) -> str | None:
    return info_fields.get("entry_point") or str((market_record or {}).get("entry_point") or "") or None


def _harness_status_payload(data: HarnessStatusPayloadInput) -> dict[str, Any]:
    return {
        "plugin_id": PLUGIN_ID,
        "harness_name": data.harness_name,
        "market_name": data.market_name,
        "safe_name": data.safe_name,
        "capability_id": data.capability_id,
        "manifest_path": str(data.manifest_path),
        "manifest_imported": data.manifest_path.exists(),
        "cli_hub_available": data.info_result.exit_code != 127,
        "cli_hub_info": {
            "argv": list(data.info_result.argv),
            "exit_code": data.info_result.exit_code,
            "status": data.status_text,
            "fields": data.info_fields,
        },
        "market_record_available": data.market_record is not None,
        "market_record": data.market_record,
        "entry_point": data.entry_point,
        "entrypoint_path": data.entrypoint_path,
        "entrypoint_available": data.entrypoint_path is not None,
        "installed": data.installed,
        "launch_ready": bool(data.installed and data.entrypoint_path),
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
