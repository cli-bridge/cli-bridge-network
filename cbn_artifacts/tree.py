"""Group artifact records into a UE-Content-style tree.

The ArtifactStore is already a single shared root (all capabilities write under one
``CBN_ARTIFACT_ROOT``). This helper organizes the flat record list by producer
(capability_id) then by kind, so the产物 panel reads like a game-engine Content
browser instead of a flat log.
"""

from __future__ import annotations

from typing import Any


def build_artifact_tree(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    producers: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for record in records:
        producer = str(record.get("capability_id") or "unknown")
        kind = str(record.get("kind") or "artifact")
        producers.setdefault(producer, {}).setdefault(kind, []).append(record)

    tree: list[dict[str, Any]] = []
    for producer, kinds in producers.items():
        kind_nodes = []
        for kind, items in kinds.items():
            kind_nodes.append({"kind": kind, "count": len(items), "items": items})
        kind_nodes.sort(key=lambda node: node["count"], reverse=True)
        tree.append(
            {
                "producer": producer,
                "count": sum(node["count"] for node in kind_nodes),
                "kinds": kind_nodes,
            }
        )
    tree.sort(key=lambda group: group["count"], reverse=True)
    return tree
