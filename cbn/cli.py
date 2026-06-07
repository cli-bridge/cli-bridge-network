"""CBN command-line interface."""

from __future__ import annotations

import json

from api_server.routes.health import health_payload
from cbn.cli_args import build_parser
from cbn.paths import resolve_project_paths
from cbn.version import __version__
from nodes import CAPABILITY_NODE_MAPPINGS, init_builtin_nodes


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(f"cbn {__version__}")
        return 0

    if args.command == "health":
        print(json.dumps(health_payload(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "paths":
        print(json.dumps(resolve_project_paths().as_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "nodes":
        init_builtin_nodes()
        payload = {
            key: {
                "title": value.title,
                "category": value.category,
                "risk": value.risk,
            }
            for key, value in sorted(CAPABILITY_NODE_MAPPINGS.items())
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    parser.print_help()
    return 0

