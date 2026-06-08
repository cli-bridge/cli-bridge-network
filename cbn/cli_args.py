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
    registry_search = registry_subcommands.add_parser("search", help="Search loaded capability manifests.")
    registry_search.add_argument("query")
    registry_search.add_argument("--limit", type=int, default=20)
    registry_inspect = registry_subcommands.add_parser("inspect", help="Inspect one capability.")
    registry_inspect.add_argument("capability_id")
    registry_validate = registry_subcommands.add_parser("validate", help="Validate manifest JSON files.")
    registry_validate.add_argument("path", nargs="?", default="manifests", help="Manifest file or directory path.")

    call_parser = subcommands.add_parser("call", help="Call a capability through policy/audit.")
    call_parser.add_argument("capability_id")
    call_parser.add_argument("extra_args", nargs="*", help="Extra arguments appended to the manifest template.")
    call_parser.add_argument("--dry-run", action="store_true", help="Return the command without executing it.")
    call_parser.add_argument("--yes", action="store_true", help="Confirm high-risk calls.")
    call_parser.add_argument("--approval-id", help="Use a previously approved approval request.")

    audit_parser = subcommands.add_parser("audit", help="Inspect local audit log.")
    audit_subcommands = audit_parser.add_subparsers(dest="audit_command")
    audit_tail = audit_subcommands.add_parser("tail", help="Print recent audit events.")
    audit_tail.add_argument("--limit", type=int, default=20)

    event_parser = subcommands.add_parser("event", help="Inspect the local runtime event bus.")
    event_subcommands = event_parser.add_subparsers(dest="event_command")
    event_tail = event_subcommands.add_parser("tail", help="Print recent runtime events.")
    event_tail.add_argument("--limit", type=int, default=20)

    artifact_parser = subcommands.add_parser("artifact", help="Inspect local runtime artifacts.")
    artifact_subcommands = artifact_parser.add_subparsers(dest="artifact_command")
    artifact_list = artifact_subcommands.add_parser("list", help="List recent artifacts.")
    artifact_list.add_argument("--limit", type=int, default=20)
    artifact_inspect = artifact_subcommands.add_parser("inspect", help="Inspect one artifact.")
    artifact_inspect.add_argument("artifact_id")

    parser_parser = subcommands.add_parser("parser", help="Inspect output parsers.")
    parser_subcommands = parser_parser.add_subparsers(dest="parser_command")
    parser_subcommands.add_parser("list", help="List built-in parsers.")
    parser_inspect = parser_subcommands.add_parser("inspect", help="Inspect one parser.")
    parser_inspect.add_argument("parser_ref")

    protocol_parser = subcommands.add_parser("protocol", help="Inspect protocol export descriptors.")
    protocol_subcommands = protocol_parser.add_subparsers(dest="protocol_command")
    protocol_subcommands.add_parser("list", help="List supported descriptor exports.")
    protocol_export = protocol_subcommands.add_parser("export", help="Export capability descriptors.")
    protocol_export.add_argument("target", choices=["mcp", "a2a", "acp", "all"])
    protocol_export.add_argument("--capability-id")
    protocol_export_workflows = protocol_subcommands.add_parser(
        "export-workflows",
        help="Export workflow descriptors for protocol adapter design.",
    )
    protocol_export_workflows.add_argument("target", choices=["mcp", "a2a", "acp", "all"])
    protocol_export_workflows.add_argument("--path", help="Optional workflow JSON path.")
    protocol_check = protocol_subcommands.add_parser(
        "check",
        help="Report descriptor evidence and remaining wire-compatibility gaps.",
    )
    protocol_check.add_argument("target", choices=["mcp", "a2a", "acp", "all"])
    protocol_check.add_argument("--capability-id")

    mcp_parser = subcommands.add_parser("mcp", help="Run or test the MCP stdio facade.")
    mcp_subcommands = mcp_parser.add_subparsers(dest="mcp_command")
    mcp_serve = mcp_subcommands.add_parser("serve", help="Serve MCP over stdio.")
    mcp_serve.add_argument("--stdio", action="store_true", help="Use newline-delimited stdio JSON-RPC.")
    mcp_smoke = mcp_subcommands.add_parser("smoke", help="Run a local MCP stdio smoke test.")
    mcp_smoke.add_argument("--capability-id", default="git.version")
    mcp_smoke.add_argument("--extra-arg", action="append", default=[])
    mcp_smoke.add_argument("--dry-run", action="store_true")
    mcp_workflow_smoke = mcp_subcommands.add_parser("smoke-workflow", help="Run a local MCP stdio workflow smoke test.")
    mcp_workflow_smoke.add_argument("--path", required=True, help="Workflow JSON path.")
    mcp_workflow_smoke.add_argument("--dry-run", action="store_true")
    mcp_workflow_smoke.add_argument("--yes", action="store_true", help="Confirm workflow tasks.")

    a2a_parser = subcommands.add_parser("a2a", help="Inspect or test the A2A HTTP facade.")
    a2a_subcommands = a2a_parser.add_subparsers(dest="a2a_command")
    a2a_card = a2a_subcommands.add_parser("agent-card", help="Print the local A2A AgentCard.")
    a2a_card.add_argument("--base-url", default="http://127.0.0.1:8787")
    a2a_smoke = a2a_subcommands.add_parser("smoke", help="Run a local A2A HTTP smoke test.")
    a2a_smoke.add_argument("--capability-id", default="git.version")
    a2a_smoke.add_argument("--extra-arg", action="append", default=[])
    a2a_workflow_smoke = a2a_subcommands.add_parser("smoke-workflow", help="Run a local A2A HTTP workflow smoke test.")
    a2a_workflow_smoke.add_argument("--path", required=True, help="Workflow JSON path.")
    a2a_workflow_smoke.add_argument("--dry-run", action="store_true")
    a2a_workflow_smoke.add_argument("--yes", action="store_true", help="Confirm workflow tasks.")

    acp_parser = subcommands.add_parser("acp", help="Run or test the ACP stdio facade.")
    acp_subcommands = acp_parser.add_subparsers(dest="acp_command")
    acp_serve = acp_subcommands.add_parser("serve", help="Serve ACP over stdio.")
    acp_serve.add_argument("--stdio", action="store_true", help="Use newline-delimited stdio JSON-RPC.")
    acp_smoke = acp_subcommands.add_parser("smoke", help="Run a local ACP stdio smoke test.")
    acp_smoke.add_argument("--capability-id", default="git.version")
    acp_smoke.add_argument("--extra-arg", action="append", default=[])
    acp_smoke.add_argument("--dry-run", action="store_true")
    acp_workflow_smoke = acp_subcommands.add_parser("smoke-workflow", help="Run a local ACP stdio workflow smoke test.")
    acp_workflow_smoke.add_argument("--path", required=True, help="Workflow JSON path.")
    acp_workflow_smoke.add_argument("--dry-run", action="store_true")
    acp_workflow_smoke.add_argument("--yes", action="store_true", help="Confirm workflow tasks.")

    message_parser = subcommands.add_parser("message", help="Validate and inspect BridgeMessage envelopes.")
    message_subcommands = message_parser.add_subparsers(dest="message_command")
    message_validate = message_subcommands.add_parser("validate", help="Validate one BridgeMessage JSON file.")
    message_validate.add_argument("path", help="BridgeMessage JSON path, or '-' for stdin.")
    message_select = message_subcommands.add_parser("select", help="Select a value from one BridgeMessage.")
    message_select.add_argument("path", help="BridgeMessage JSON path, or '-' for stdin.")
    message_select.add_argument("selector", help="Selector such as payload.data.stdout or artifacts[0].artifact_id.")
    message_args = message_subcommands.add_parser("args", help="Convert BridgeMessage selectors into CLI argv strings.")
    message_args.add_argument("path", help="BridgeMessage JSON path, or '-' for stdin.")
    message_args.add_argument("selectors", nargs="+", help="Selectors to map into argv strings.")

    approvals_parser = subcommands.add_parser("approvals", help="Manage the approval queue.")
    approvals_subcommands = approvals_parser.add_subparsers(dest="approvals_command")
    approvals_list = approvals_subcommands.add_parser("list", help="List approval requests.")
    approvals_list.add_argument("--status", choices=["pending", "approved", "denied", "used"])
    approvals_list.add_argument("--limit", type=int, default=20)
    approvals_show = approvals_subcommands.add_parser("show", help="Show one approval request.")
    approvals_show.add_argument("approval_id")
    approvals_approve = approvals_subcommands.add_parser("approve", help="Approve one request.")
    approvals_approve.add_argument("approval_id")
    approvals_approve.add_argument("--reason", default="")
    approvals_deny = approvals_subcommands.add_parser("deny", help="Deny one request.")
    approvals_deny.add_argument("approval_id")
    approvals_deny.add_argument("--reason", default="")

    workflow_parser = subcommands.add_parser("workflow", help="Validate, plan, or run workflows.")
    workflow_subcommands = workflow_parser.add_subparsers(dest="workflow_command")
    workflow_subcommands.add_parser("list", help="List workflow descriptors.")
    workflow_inspect = workflow_subcommands.add_parser("inspect", help="Inspect one workflow descriptor.")
    workflow_inspect.add_argument("path")
    workflow_validate = workflow_subcommands.add_parser("validate", help="Validate a workflow JSON file.")
    workflow_validate.add_argument("path")
    workflow_plan = workflow_subcommands.add_parser("plan", help="Print workflow execution plan.")
    workflow_plan.add_argument("path")
    workflow_run = workflow_subcommands.add_parser("run", help="Run a workflow.")
    workflow_run.add_argument("path")
    workflow_run.add_argument("--dry-run", action="store_true")
    workflow_run.add_argument("--yes", action="store_true", help="Confirm high-risk workflow tasks.")

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

    plugin_preflight = plugin_subcommands.add_parser("preflight", help="Run install readiness checks.")
    plugin_preflight.add_argument("plugin_id", help="Plugin id, for example cli-anything.")

    plugin_status = plugin_subcommands.add_parser("status", help="Show external plugin runtime status.")
    plugin_status.add_argument("plugin_id", help="Plugin id, for example cli-anything.")

    plugin_market = plugin_subcommands.add_parser("market", help="Inspect an external plugin market.")
    plugin_market.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_market.add_argument("market_command", choices=["list", "search", "info"])
    plugin_market.add_argument("query", nargs="?", help="Search query or harness name.")

    plugin_import = plugin_subcommands.add_parser(
        "import-harness",
        help="Generate or write a CBN manifest for an external harness.",
    )
    plugin_import.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_import.add_argument("harness_name", help="Harness name from the plugin market.")
    plugin_import.add_argument("--title", help="Optional manifest title.")
    plugin_import.add_argument(
        "--from-market",
        action="store_true",
        help="Require a CLI-Hub market record and include its metadata in the manifest.",
    )
    plugin_import.add_argument("--write", action="store_true", help="Write manifest into manifests/.")

    plugin_adapt = plugin_subcommands.add_parser(
        "adapt-harness",
        help="Preview or write the full CBN adaptation report for an external harness.",
    )
    plugin_adapt.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_adapt.add_argument("harness_name", help="Harness name from the plugin market.")
    plugin_adapt.add_argument("--title", help="Optional manifest title.")
    plugin_adapt.add_argument(
        "--from-market",
        action="store_true",
        help="Require a CLI-Hub market record and include its metadata in the adaptation.",
    )
    plugin_adapt.add_argument("--write", action="store_true", help="Write manifest into manifests/.")

    plugin_prepare = plugin_subcommands.add_parser(
        "prepare-harness",
        help="Return status, manifest validation, and lifecycle plans for an external harness.",
    )
    plugin_prepare.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_prepare.add_argument("harness_name", help="Harness name from the plugin market.")
    plugin_prepare.add_argument("--title", help="Optional manifest title.")
    plugin_prepare.add_argument(
        "--from-market",
        action="store_true",
        help="Require a CLI-Hub market record and include its metadata in the preparation report.",
    )

    plugin_evaluate = plugin_subcommands.add_parser(
        "evaluate-harness",
        help="Evaluate an external harness as a candidate for install and CBN adaptation.",
    )
    plugin_evaluate.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_evaluate.add_argument("harness_name", help="Harness name from the plugin market.")
    plugin_evaluate.add_argument("--title", help="Optional manifest title.")
    plugin_evaluate.add_argument(
        "--from-market",
        action="store_true",
        default=True,
        help="Require a CLI-Hub market record and include its metadata in the evaluation.",
    )
    plugin_evaluate.add_argument(
        "--offline",
        action="store_false",
        dest="from_market",
        help="Evaluate without requiring market metadata.",
    )

    plugin_sync = plugin_subcommands.add_parser(
        "sync-market",
        help="Preview or write CBN manifests for CLI-Anything market records.",
    )
    plugin_sync.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_sync.add_argument("--query", help="Optional CLI-Hub search query; omit to sync list output.")
    plugin_sync.add_argument("--limit", type=int, default=50, help="Maximum market records to convert.")
    plugin_sync.add_argument("--write", action="store_true", help="Write generated manifests into manifests/.")

    plugin_harness = plugin_subcommands.add_parser("harness", help="Plan or execute external harness operations.")
    plugin_harness.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_harness.add_argument("harness_action", choices=["status", "install", "update", "uninstall", "launch"])
    plugin_harness.add_argument("harness_name", help="Harness name from the plugin market.")
    plugin_harness.add_argument("extra_args", nargs="*", help="Extra args passed to harness launch.")
    plugin_harness.add_argument(
        "--from-market",
        action="store_true",
        help="Include CLI-Hub market metadata when checking harness status.",
    )
    plugin_harness.add_argument(
        "--offline",
        action="store_true",
        help="Skip market metadata during install/update gating.",
    )
    plugin_harness.add_argument("--yes", action="store_true", help="Execute the harness operation.")
    plugin_harness.add_argument(
        "--allow-blocked",
        action="store_true",
        help="Execute install/update even when harness evaluation reports blockers.",
    )

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
