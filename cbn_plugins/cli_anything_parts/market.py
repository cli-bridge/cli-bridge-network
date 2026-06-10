"""Market parsing helpers for the CLI-Anything plugin facade."""

from __future__ import annotations

from typing import Any


CAPABILITY_COLLISION_ERROR = "duplicate capability_id generated from market records"


def market_records_from_result(parsed_json: Any) -> list[dict[str, Any]] | None:
    if isinstance(parsed_json, list):
        records = parsed_json
    elif isinstance(parsed_json, dict):
        records = None
        for key in ("items", "harnesses", "tools", "results", "data"):
            value = parsed_json.get(key)
            if isinstance(value, list):
                records = value
                break
        if records is None:
            return None
    else:
        return None
    return [item for item in records if isinstance(item, dict)]


def market_record_identity(item: dict[str, Any]) -> dict[str, str | None]:
    record = item.get("market_record")
    if not isinstance(record, dict):
        record = {}
    return {
        "name": str(record.get("name")) if record.get("name") is not None else None,
        "display_name": str(record.get("display_name")) if record.get("display_name") is not None else None,
        "entry_point": str(record.get("entry_point")) if record.get("entry_point") is not None else None,
        "source": str(record.get("_source")) if record.get("_source") is not None else None,
    }


def mark_capability_collisions(manifests: list[dict[str, Any]]) -> None:
    by_id = _items_by_capability_id(manifests)
    for capability_id, matches in by_id.items():
        if len(matches) < 2:
            continue
        sources = [market_record_identity(item) for item in matches]
        for item in matches:
            item["ok"] = False
            item["error"] = CAPABILITY_COLLISION_ERROR
            item["collision"] = {
                "capability_id": capability_id,
                "market_records": sources,
            }


def mark_candidate_collisions(candidates: list[dict[str, Any]]) -> None:
    by_id = _items_by_capability_id(candidates)
    for capability_id, matches in by_id.items():
        if len(matches) < 2:
            continue
        sources = [market_record_identity(item) for item in matches]
        for item in matches:
            item["install_candidate"] = False
            item["recommended_next_action"] = "resolve_blockers"
            item.setdefault("blockers", []).append(CAPABILITY_COLLISION_ERROR)
            item["collision"] = {
                "capability_id": capability_id,
                "market_records": sources,
            }


def _items_by_capability_id(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_id: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        capability_id = item.get("capability_id")
        if isinstance(capability_id, str) and capability_id:
            by_id.setdefault(capability_id, []).append(item)
    return by_id
