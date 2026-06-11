"""Command-line entrypoint for the standalone Agent CLI contract package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Callable

from agent_cli_contract.validator import validate_agent_cli_card, validate_run_receipt


Validator = Callable[[dict[str, Any]], dict[str, Any]]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "validate":
        validator: Validator = validate_agent_cli_card if args.target == "card" else validate_run_receipt
        report = validate_file(Path(args.file), validator=validator, target=args.target)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1
    parser.print_help()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-cli-contract",
        description="Validate AgentCliCard and RunReceipt JSON documents.",
    )
    subcommands = parser.add_subparsers(dest="command")
    validate = subcommands.add_parser("validate", help="Validate a contract JSON document.")
    validate_subcommands = validate.add_subparsers(dest="target", required=True)
    card = validate_subcommands.add_parser("card", help="Validate an AgentCliCard JSON file.")
    card.add_argument("file", help="Path to an AgentCliCard JSON document.")
    receipt = validate_subcommands.add_parser("receipt", help="Validate a RunReceipt JSON file.")
    receipt.add_argument("file", help="Path to a RunReceipt JSON document.")
    return parser


def validate_file(path: Path, *, validator: Validator, target: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _error_report(target, path, f"file not found: {path}")
    except json.JSONDecodeError as exc:
        return _error_report(target, path, f"invalid JSON: {exc}")
    if not isinstance(payload, dict):
        return _error_report(target, path, "document must be a JSON object")
    report = validator(payload)
    return {
        **report,
        "target": target,
        "file": str(path),
    }


def _error_report(target: str, path: Path, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "target": target,
        "file": str(path),
        "errors": [message],
    }


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
