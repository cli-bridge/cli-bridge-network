"""Argument parsing for the CBN CLI."""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cbn", description="CLI Bridge Network")
    parser.add_argument("--version", action="store_true", help="Print the CBN version and exit.")

    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("health", help="Print local runtime health.")
    subcommands.add_parser("paths", help="Print resolved project paths.")
    subcommands.add_parser("nodes", help="List built-in capability nodes.")

    registry_parser = subcommands.add_parser("registry", help="Inspect capability registry.")
    registry_subcommands = registry_parser.add_subparsers(dest="registry_command")
    registry_subcommands.add_parser("list", help="List loaded capability manifests.")
    registry_inspect = registry_subcommands.add_parser("inspect", help="Inspect one capability.")
    registry_inspect.add_argument("capability_id")

    call_parser = subcommands.add_parser("call", help="Call a capability through policy/audit.")
    call_parser.add_argument("capability_id")
    call_parser.add_argument("extra_args", nargs="*", help="Extra arguments appended to the manifest template.")
    call_parser.add_argument("--dry-run", action="store_true", help="Return the command without executing it.")
    call_parser.add_argument("--yes", action="store_true", help="Confirm high-risk calls.")

    audit_parser = subcommands.add_parser("audit", help="Inspect local audit log.")
    audit_subcommands = audit_parser.add_subparsers(dest="audit_command")
    audit_tail = audit_subcommands.add_parser("tail", help="Print recent audit events.")
    audit_tail.add_argument("--limit", type=int, default=20)

    daemon_parser = subcommands.add_parser("daemon", help="Run or inspect the local daemon API.")
    daemon_subcommands = daemon_parser.add_subparsers(dest="daemon_command")
    daemon_subcommands.add_parser("routes", help="List MVP daemon routes.")
    daemon_serve = daemon_subcommands.add_parser("serve", help="Serve the MVP daemon API.")
    daemon_serve.add_argument("--host", default="127.0.0.1")
    daemon_serve.add_argument("--port", type=int, default=8787)

    plugin_parser = subcommands.add_parser("plugin", help="Manage external CBN plugins.")
    plugin_subcommands = plugin_parser.add_subparsers(dest="plugin_command")
    plugin_subcommands.add_parser("list", help="List known external plugins.")

    plugin_info = plugin_subcommands.add_parser("info", help="Show plugin metadata.")
    plugin_info.add_argument("plugin_id", help="Plugin id, for example cli-anything.")

    plugin_plan = plugin_subcommands.add_parser("plan", help="Print install/update plan.")
    plugin_plan.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_plan.add_argument(
        "--action",
        choices=["install", "update"],
        default="install",
        help="Plan action to render.",
    )
    plugin_plan.add_argument(
        "--with-codex-skill",
        action="store_true",
        help="Include the optional Codex skill install command in the plan.",
    )

    plugin_install = plugin_subcommands.add_parser("install", help="Install an external plugin.")
    plugin_install.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_install.add_argument("--yes", action="store_true", help="Execute the install plan.")
    plugin_install.add_argument(
        "--with-codex-skill",
        action="store_true",
        help="Also install the optional Codex skill when supported.",
    )

    plugin_update = plugin_subcommands.add_parser("update", help="Update an external plugin.")
    plugin_update.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_update.add_argument("--yes", action="store_true", help="Execute the update plan.")
    plugin_update.add_argument(
        "--with-codex-skill",
        action="store_true",
        help="Also run the optional Codex skill installer when supported.",
    )
    return parser
