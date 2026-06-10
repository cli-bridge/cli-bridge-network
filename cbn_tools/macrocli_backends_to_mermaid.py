"""Convert MacroCLI backend status JSON into a Mermaid source file."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_PATH = Path("runtime/generated/macrocli-backends.mmd")


def build_mermaid_source(payload: dict[str, Any]) -> str:
    backends = _extract_backends(payload)
    lines = [
        "flowchart LR",
        f'  summary["MacroCLI Backends\\n{len(backends)} total"]',
    ]
    for backend in sorted(backends, key=lambda item: (-item["priority"], item["id"])):
        node_id = _node_id(backend["id"])
        state = "available" if backend["available"] else "unavailable"
        label = _label(f"{backend['name']}\\npriority {backend['priority']}\\n{state}")
        lines.append(f'  {node_id}["{label}"]:::{state}')
        lines.append(f"  summary --> {node_id}")
    lines.extend(
        [
            "  classDef available fill:#dcfce7,stroke:#16a34a,color:#052e16",
            "  classDef unavailable fill:#fee2e2,stroke:#dc2626,color:#450a0a",
        ]
    )
    return "\n".join(lines) + "\n"


def write_mermaid_source(payload: dict[str, Any], output_path: Path = DEFAULT_OUTPUT_PATH) -> Path:
    source = build_mermaid_source(payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(source, encoding="utf-8", newline="\n")
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("payload", help="MacroCLI parser payload JSON string or UTF-8 JSON file path.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="Output Mermaid .mmd path.")
    args = parser.parse_args(argv)

    payload = _load_payload(args.payload)
    path = write_mermaid_source(payload, Path(args.output))
    sys.stdout.write(path.as_posix())
    return 0


def _load_payload(value: str) -> dict[str, Any]:
    value = value.strip()
    if value.startswith(("{", "[")):
        payload = json.loads(value)
    else:
        payload = json.loads(Path(value).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        payload = {"backends": payload}
    if not isinstance(payload, dict):
        raise ValueError("MacroCLI payload must be a JSON object or backend array")
    return payload


def _extract_backends(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_backends = payload.get("backends", payload)
    if isinstance(raw_backends, dict):
        raw_backends = [
            {
                "id": key,
                "name": value.get("name", key),
                "priority": value.get("priority"),
                "available": value.get("available"),
            }
            for key, value in raw_backends.items()
            if isinstance(value, dict)
        ]
    if not isinstance(raw_backends, list):
        raise ValueError("MacroCLI payload must include a backends list")
    backends: list[dict[str, Any]] = []
    for item in raw_backends:
        if not isinstance(item, dict):
            raise ValueError("MacroCLI backend item must be an object")
        backend_id = item.get("id")
        name = item.get("name")
        priority = item.get("priority")
        available = item.get("available")
        if not isinstance(backend_id, str) or not backend_id:
            raise ValueError("MacroCLI backend id must be a non-empty string")
        if not isinstance(name, str) or not name:
            raise ValueError(f"MacroCLI backend {backend_id} name must be a non-empty string")
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise ValueError(f"MacroCLI backend {backend_id} priority must be an integer")
        if not isinstance(available, bool):
            raise ValueError(f"MacroCLI backend {backend_id} available must be a boolean")
        backends.append(
            {
                "id": backend_id,
                "name": name,
                "priority": priority,
                "available": available,
            }
        )
    return backends


def _node_id(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z_]+", "_", value).strip("_")
    if not normalized:
        normalized = "backend"
    if normalized[0].isdigit():
        normalized = f"backend_{normalized}"
    return normalized


def _label(value: str) -> str:
    return value.replace('"', '\\"')


if __name__ == "__main__":
    raise SystemExit(main())
