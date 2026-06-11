"""Argument parsing for the CBN CLI."""

from __future__ import annotations

import argparse

from cbn_demo.network_connect import DEFAULT_AGENT_CONNECT_MESSAGE


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
    parser_fixtures = parser_subcommands.add_parser("fixtures", help="Run parser output fixtures.")
    parser_fixtures.add_argument("path", nargs="?", default="parser_fixtures", help="Fixture file or directory.")
    parser_fixtures.add_argument("--parser-ref", help="Only run fixtures for one parser ref.")

    record_parser_fixture = subcommands.add_parser(
        "record-parser-fixture",
        help="Record observed stdout/stderr as a reusable parser fixture.",
    )
    record_parser_fixture.add_argument("parser_ref", help="Parser ref to validate, for example raw.text.")
    record_parser_fixture.add_argument("case_id", help="Stable fixture case id.")
    record_parser_fixture.add_argument("--stdout", default="", help="Observed stdout text.")
    record_parser_fixture.add_argument("--stderr", default="", help="Observed stderr text.")
    record_parser_fixture.add_argument("--stdout-file", help="Read stdout text from a UTF-8 file.")
    record_parser_fixture.add_argument("--stderr-file", help="Read stderr text from a UTF-8 file.")
    record_parser_fixture.add_argument("--title", help="Fixture title.")
    record_parser_fixture.add_argument("--fixture-id", help="Fixture metadata id.")
    record_parser_fixture.add_argument(
        "--verified-capability",
        action="append",
        default=[],
        help="Capability verified by this fixture; repeatable.",
    )
    record_parser_fixture.add_argument("--expect-failure", action="store_true")
    record_parser_fixture.add_argument("--error-contains", help="Expected parser error substring.")
    record_parser_fixture.add_argument("--output", help="Output fixture path. Defaults to parser_fixtures/<parser>.<case>.json.")
    record_parser_fixture.add_argument("--write", action="store_true", help="Write the fixture after validation.")

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
    protocol_check.add_argument("--workflow-path", help="Check workflow descriptor compatibility for one workflow.")
    protocol_matrix = protocol_subcommands.add_parser(
        "matrix",
        help="Summarize protocol compatibility checks for all capabilities.",
    )
    protocol_matrix.add_argument(
        "--include-workflows",
        action="store_true",
        help="Include workflow descriptor compatibility rows.",
    )
    protocol_readiness = protocol_subcommands.add_parser(
        "readiness",
        help="Report CLI-to-CLI BridgeMessage routing and external protocol readiness.",
    )
    protocol_readiness.add_argument("--workflow-path", help="Optional workflow JSON path to inspect.")
    protocol_readiness.add_argument(
        "--include-workflows",
        action="store_true",
        default=True,
        help="Include workflow routing contract evidence.",
    )
    protocol_readiness.add_argument(
        "--no-workflows",
        action="store_false",
        dest="include_workflows",
        help="Skip workflow routing contract evidence.",
    )
    protocol_conformance = protocol_subcommands.add_parser(
        "conformance-plan",
        help="Return the conservative MCP/A2A/ACP wire conformance plan.",
    )
    protocol_conformance.add_argument("target", choices=["mcp", "a2a", "acp", "all"], nargs="?", default="all")
    protocol_conformance.add_argument("--capability-id")
    protocol_conformance.add_argument("--workflow-path", help="Plan conformance around one workflow descriptor.")
    protocol_lifecycle = protocol_subcommands.add_parser(
        "lifecycle-suite",
        help="Run MVP protocol lifecycle and error-boundary checks for MCP/A2A/ACP facades.",
    )
    protocol_lifecycle.add_argument("--capability-id", default="git.version")
    protocol_lifecycle.add_argument("--workflow-path", default="workflows/example.json")
    protocol_wire = protocol_subcommands.add_parser(
        "wire-conformance",
        help="Run local official-shape MCP/A2A/ACP wire conformance checks.",
    )
    protocol_wire.add_argument("target", choices=["mcp", "a2a", "acp", "all"], nargs="?", default="all")
    protocol_wire.add_argument("--capability-id", default="git.version")
    protocol_smoke_suite = protocol_subcommands.add_parser(
        "smoke-suite",
        help="Run the MVP MCP/A2A/ACP smoke suite for selected capabilities and workflows.",
    )
    protocol_smoke_suite.add_argument(
        "--capability-id",
        action="append",
        default=[],
        help="Capability to smoke through MCP/A2A/ACP; repeatable. Defaults to git.version.",
    )
    protocol_smoke_suite.add_argument(
        "--workflow-path",
        action="append",
        default=[],
        help="Workflow to smoke through MCP/A2A/ACP; repeatable. Defaults to workflows/example.json.",
    )
    protocol_smoke_suite.add_argument(
        "--extra-arg",
        action="append",
        default=[],
        help="Extra capability arg passed to every selected capability smoke; repeatable.",
    )
    protocol_smoke_suite.add_argument("--dry-run", action="store_true", help="Dry-run capability calls.")
    protocol_smoke_suite.add_argument("--workflow-dry-run", action="store_true", help="Dry-run workflow calls.")
    protocol_smoke_suite.add_argument("--yes", action="store_true", help="Confirm workflow tasks when needed.")
    protocol_smoke_suite.add_argument(
        "--include-payloads",
        action="store_true",
        help="Include raw per-protocol smoke payloads in the JSON report.",
    )
    protocol_accept_workflow = protocol_subcommands.add_parser(
        "accept-workflow",
        help="Accept one CLI-to-CLI workflow BridgeMessage routing contract.",
    )
    protocol_accept_workflow.add_argument("workflow_path", help="Workflow JSON path to accept.")
    protocol_accept_workflow.add_argument(
        "--run",
        action="store_true",
        help="Execute the workflow and attach runtime route evidence.",
    )
    protocol_accept_workflow.add_argument("--dry-run", action="store_true", help="Dry-run workflow execution.")
    protocol_accept_workflow.add_argument("--yes", action="store_true", help="Confirm workflow tasks when needed.")
    protocol_accept_workflow.add_argument(
        "--include-payloads",
        action="store_true",
        help="Include task messages and raw run result payloads.",
    )
    protocol_acceptance_queue = protocol_subcommands.add_parser(
        "acceptance-queue",
        help="Accept multiple CLI-to-CLI workflow BridgeMessage routing contracts.",
    )
    protocol_acceptance_queue.add_argument(
        "--workflow-path",
        action="append",
        default=[],
        help="Workflow JSON path to accept; repeatable. Defaults to the workflow catalog.",
    )
    protocol_acceptance_queue.add_argument(
        "--max-workflows",
        type=int,
        default=50,
        help="Maximum catalog workflows to inspect when no --workflow-path is provided.",
    )
    protocol_acceptance_queue.add_argument(
        "--run",
        action="store_true",
        help="Execute selected workflows and attach runtime route evidence.",
    )
    protocol_acceptance_queue.add_argument("--dry-run", action="store_true", help="Dry-run workflow execution.")
    protocol_acceptance_queue.add_argument("--yes", action="store_true", help="Confirm workflow tasks when needed.")
    protocol_acceptance_queue.add_argument(
        "--include-payloads",
        action="store_true",
        help="Include task messages and raw run result payloads.",
    )
    protocol_bridge_lab = protocol_subcommands.add_parser(
        "bridge-lab",
        help="Build a BridgeMessage CLI-to-CLI protocol research baseline.",
    )
    protocol_bridge_lab.add_argument(
        "--workflow-path",
        action="append",
        default=[],
        help="Workflow JSON path to include; repeatable. Defaults to the workflow catalog.",
    )
    protocol_bridge_lab.add_argument("--max-workflows", type=int, default=10)
    protocol_bridge_lab.add_argument("--run", action="store_true", help="Execute selected workflows for route evidence.")
    protocol_bridge_lab.add_argument("--dry-run", action="store_true", help="Dry-run workflow execution.")
    protocol_bridge_lab.add_argument("--yes", action="store_true", help="Confirm workflow tasks when needed.")
    protocol_bridge_lab.add_argument("--include-payloads", action="store_true")
    protocol_bridge_lab.add_argument(
        "--smoke-suite",
        action="store_true",
        help="Run protocol facade smoke checks as part of the lab report.",
    )

    demo_parser = subcommands.add_parser("demo", help="Run product demo evidence bundles.")
    demo_subcommands = demo_parser.add_subparsers(dest="demo_command")
    killer_demo = demo_subcommands.add_parser(
        "killer",
        help="Run the CLI-Anything macrocli -> mermaid killer demo report.",
    )
    killer_demo.add_argument(
        "--workflow-path",
        default="workflows/cli-anything-macrocli-mermaid-routing.example.json",
        help="Workflow JSON path to use for the killer demo.",
    )
    killer_demo.add_argument("--run", action="store_true", help="Execute the workflow and attach runtime evidence.")
    killer_demo.add_argument("--dry-run", action="store_true", help="Dry-run workflow execution.")
    killer_demo.add_argument("--yes", action="store_true", help="Confirm workflow tasks when needed.")
    killer_demo.add_argument("--include-payloads", action="store_true")
    killer_demo.add_argument(
        "--smoke-suite",
        action="store_true",
        help="Run MCP/A2A/ACP smoke checks as part of the demo report.",
    )

    network_parser = subcommands.add_parser("network", help="Inspect external CBN network connection packages.")
    network_subcommands = network_parser.add_subparsers(dest="network_command")
    network_connect = network_subcommands.add_parser(
        "connect-package",
        help="Print the one-shot package another program needs to connect to CBN.",
    )
    network_connect.add_argument(
        "--workflow-path",
        default="workflows/cli-anything-macrocli-mermaid-routing.example.json",
        help="Workflow JSON path to expose in the connect package.",
    )
    network_connect.add_argument("--base-url", help="Daemon base URL to embed in endpoint URLs.")
    network_connect.add_argument(
        "--studio-url",
        default="http://127.0.0.1:5177",
        help="Workflow Studio base URL to embed as a preconfigured demo link.",
    )
    network_connect.add_argument(
        "--dashboard-url",
        default="http://127.0.0.1:5173",
        help="Maintainer dashboard URL to embed in the Workflow Studio demo link.",
    )
    network_connect.add_argument(
        "--session-token",
        help="Optional daemon session token to include in the Workflow Studio demo link.",
    )
    network_connect.add_argument(
        "--message",
        default=DEFAULT_AGENT_CONNECT_MESSAGE,
        help="Agent prompt used to shape the Adapter Agent node bundle.",
    )
    network_quickstart = network_subcommands.add_parser(
        "quickstart",
        help="Print only the machine-readable first-call quickstart for external CBN consumers.",
    )
    network_quickstart.add_argument(
        "--workflow-path",
        default="workflows/cli-anything-macrocli-mermaid-routing.example.json",
        help="Workflow JSON path to expose in the quickstart.",
    )
    network_quickstart.add_argument("--base-url", help="Daemon base URL to embed in endpoint URLs.")
    network_quickstart.add_argument(
        "--studio-url",
        default="http://127.0.0.1:5177",
        help="Workflow Studio base URL to embed as a preconfigured demo link.",
    )
    network_quickstart.add_argument(
        "--dashboard-url",
        default="http://127.0.0.1:5173",
        help="Maintainer dashboard URL to embed in the Workflow Studio demo link.",
    )
    network_quickstart.add_argument(
        "--session-token",
        help="Optional daemon session token to include in required headers and the Studio demo link.",
    )
    network_quickstart.add_argument(
        "--message",
        default=DEFAULT_AGENT_CONNECT_MESSAGE,
        help="Agent prompt used to shape the reusable workflow request.",
    )
    network_quickstart.add_argument(
        "--output",
        choices=["json", "curl", "powershell", "acceptance", "readiness"],
        default="json",
        help="Output JSON quickstart, a cURL script, a PowerShell script, the acceptance checklist, or MVP readiness.",
    )
    network_verify = network_subcommands.add_parser(
        "verify",
        help="Run the quickstart acceptance checklist against a live CBN daemon.",
    )
    network_verify.add_argument(
        "--workflow-path",
        default="workflows/cli-anything-macrocli-mermaid-routing.example.json",
        help="Workflow JSON path to verify through the daemon.",
    )
    network_verify.add_argument(
        "--base-url",
        default="http://127.0.0.1:8787",
        help="Daemon base URL to call during verification.",
    )
    network_verify.add_argument(
        "--studio-url",
        default="http://127.0.0.1:5177",
        help="Workflow Studio base URL to embed in the generated connect package.",
    )
    network_verify.add_argument(
        "--dashboard-url",
        default="http://127.0.0.1:5173",
        help="Maintainer dashboard URL to embed in generated Workflow Studio links.",
    )
    network_verify.add_argument(
        "--session-token",
        help="Optional daemon session token to include in verification requests.",
    )
    network_verify.add_argument(
        "--message",
        default=DEFAULT_AGENT_CONNECT_MESSAGE,
        help="Agent prompt used to shape the reusable workflow request.",
    )
    network_verify.add_argument("--timeout-seconds", type=float, default=8.0)
    network_studio_link = network_subcommands.add_parser(
        "studio-link",
        help="Print a preconfigured Workflow Studio URL for a CBN workflow.",
    )
    network_studio_link.add_argument(
        "--workflow-path",
        default="workflows/cli-anything-macrocli-mermaid-routing.example.json",
        help="Workflow JSON path to open in Workflow Studio.",
    )
    network_studio_link.add_argument(
        "--daemon-url",
        default="http://127.0.0.1:8787",
        help="Daemon base URL to prefill in Workflow Studio.",
    )
    network_studio_link.add_argument(
        "--studio-url",
        default="http://127.0.0.1:5177",
        help="Workflow Studio base URL.",
    )
    network_studio_link.add_argument(
        "--dashboard-url",
        default="http://127.0.0.1:5173",
        help="Maintainer dashboard URL to prefill in Workflow Studio.",
    )
    network_studio_link.add_argument("--session-token", help="Optional daemon session token to include.")
    network_studio_link.add_argument("--dry-run", action="store_true", default=True)
    network_studio_link.add_argument("--no-dry-run", action="store_false", dest="dry_run")
    network_studio_link.add_argument("--confirmed", action="store_true")
    network_studio_link.add_argument(
        "--message",
        default="Run this workflow as a reusable CLI-CLI harness agent and surface setup gates.",
        help="Agent prompt to prefill in Workflow Studio.",
    )

    import_parser = subcommands.add_parser("import", help="Create CBN manifests from external tools.")
    import_subcommands = import_parser.add_subparsers(dest="import_command")
    import_subcommands.add_parser(
        "catalog",
        help="Print the dry-run-first importer catalog.",
    )
    import_command = import_subcommands.add_parser(
        "command",
        help="Generate a ToolManifest for a plain CLI command.",
    )
    import_command.add_argument("capability_id", help="Stable CBN capability id, for example local.echo.")
    import_command.add_argument(
        "--command",
        dest="executable",
        required=True,
        help="Executable command or absolute path.",
    )
    import_command.add_argument(
        "--arg",
        action="append",
        default=[],
        help="Argument to include in the manifest argsTemplate; repeatable.",
    )
    import_command.add_argument("--title", help="Human-readable capability title.")
    import_command.add_argument("--transport", choices=["stdio", "pty"], default="stdio")
    import_command.add_argument("--parser-ref", default="raw.text")
    import_command.add_argument("--verified", action="store_true", help="Mark parser/output contract verified.")
    import_command.add_argument(
        "--risk",
        choices=["read", "write-workspace", "privileged", "external-network"],
        default="read",
    )
    import_command.add_argument("--requires-confirmation", action="store_true")
    import_command.add_argument(
        "--network",
        choices=["deny", "localhost", "requires-confirmation", "allow"],
        default="deny",
    )
    import_command.add_argument("--cwd-policy", default="workspace")
    import_command.add_argument("--timeout-seconds", type=int, default=30)
    import_command.add_argument("--label", action="append", default=[], help="Manifest label as KEY=VALUE; repeatable.")
    import_command.add_argument(
        "--annotation",
        action="append",
        default=[],
        help="Manifest annotation as KEY=VALUE; repeatable.",
    )
    import_command.add_argument("--output", help="Output manifest path. Defaults to runtime/manifests/<id>.json.")
    import_command.add_argument("--write", action="store_true", help="Write the manifest after validation.")
    import_cli_anything = import_subcommands.add_parser(
        "cli-anything",
        help="Import or onboard a CLI-Anything harness as a CBN capability.",
    )
    import_cli_anything.add_argument("harness_name", help="Harness name in CLI-Anything CLI-Hub.")
    import_cli_anything.add_argument("--title", help="Override generated manifest title.")
    import_cli_anything.add_argument("--from-market", action="store_true", default=True)
    import_cli_anything.add_argument(
        "--offline",
        action="store_false",
        dest="from_market",
        help="Do not require CLI-Hub market metadata.",
    )
    import_cli_anything.add_argument("--write", action="store_true", help="Write manifest after gates pass.")
    import_cli_anything.add_argument("--install", action="store_true", help="Install the harness through plugin operations.")
    import_cli_anything.add_argument("--yes", action="store_true", help="Confirm write/install side effects.")
    import_cli_anything.add_argument(
        "--allow-blocked",
        action="store_true",
        help="Allow confirmed write/install despite onboarding blockers.",
    )
    import_cli_anything.add_argument(
        "--no-workflows",
        action="store_false",
        dest="include_workflows",
        help="Skip workflow reference lookup.",
    )
    import_cli_anything.add_argument(
        "--smoke-suite",
        action="store_true",
        help="Run protocol smoke suite after onboarding checks.",
    )
    import_cli_anything.add_argument(
        "--smoke-extra-arg",
        action="append",
        default=[],
        help="Extra arg passed to protocol smoke capability calls; repeatable.",
    )
    import_agent_cli_card = import_subcommands.add_parser(
        "agent-cli-card",
        help="Generate ToolManifest drafts from an AgentCliCard descriptor.",
    )
    import_agent_cli_card.add_argument(
        "--card-file",
        required=True,
        help="UTF-8 AgentCliCard JSON file.",
    )
    import_agent_cli_card.add_argument(
        "--output-dir",
        help="Directory for generated manifests. Defaults to runtime/manifests.",
    )
    import_agent_cli_card.add_argument(
        "--write",
        action="store_true",
        help="Write generated manifests after validation.",
    )
    import_mcp = import_subcommands.add_parser(
        "mcp",
        help="Generate a ToolManifest draft from an external MCP tool descriptor.",
    )
    import_mcp.add_argument("--tool-file", required=True, help="UTF-8 JSON MCP tool descriptor or tools/list payload.")
    import_mcp.add_argument("--tool-name", help="Tool name to select when --tool-file contains a tools array.")
    import_mcp.add_argument("--server-id", required=True, help="Stable MCP server id.")
    import_mcp.add_argument("--adapter-command", required=True, help="Local adapter executable that calls the MCP tool.")
    import_mcp.add_argument(
        "--adapter-arg",
        action="append",
        default=[],
        help="Static adapter argument. Supports {server_id}, {tool_name}, {capability_id}; repeatable.",
    )
    import_mcp.add_argument("--capability-id", help="Override generated capability id.")
    import_mcp.add_argument("--title", help="Override manifest title.")
    import_mcp.add_argument("--parser-ref", default="raw.text")
    import_mcp.add_argument("--verified", action="store_true")
    import_mcp.add_argument(
        "--risk",
        choices=["read", "write-workspace", "privileged", "external-network"],
        default="read",
    )
    import_mcp.add_argument("--requires-confirmation", action="store_true")
    import_mcp.add_argument(
        "--network",
        choices=["deny", "localhost", "requires-confirmation", "allow"],
        default="localhost",
    )
    import_mcp.add_argument("--timeout-seconds", type=int, default=60)
    import_mcp.add_argument("--output", help="Output manifest path. Defaults to runtime/manifests/<id>.json.")
    import_mcp.add_argument("--write", action="store_true", help="Write the manifest after validation.")
    import_skill = import_subcommands.add_parser(
        "skill",
        help="Generate a ToolManifest draft from a local skill descriptor.",
    )
    import_skill.add_argument("skill_file", help="UTF-8 JSON or Markdown skill descriptor.")
    import_skill.add_argument("--command", dest="executable", required=True, help="Local skill runner command.")
    import_skill.add_argument(
        "--arg",
        action="append",
        default=[],
        help="Argument to include in argsTemplate. Supports the runner's own conventions; repeatable.",
    )
    import_skill.add_argument("--capability-id", help="Override generated capability id.")
    import_skill.add_argument("--title", help="Override manifest title.")
    import_skill.add_argument("--parser-ref", default="raw.text")
    import_skill.add_argument("--verified", action="store_true")
    import_skill.add_argument(
        "--risk",
        choices=["read", "write-workspace", "privileged", "external-network"],
        default="read",
    )
    import_skill.add_argument("--requires-confirmation", action="store_true")
    import_skill.add_argument(
        "--network",
        choices=["deny", "localhost", "requires-confirmation", "allow"],
        default="deny",
    )
    import_skill.add_argument("--timeout-seconds", type=int, default=60)
    import_skill.add_argument("--output", help="Output manifest path. Defaults to runtime/manifests/<id>.json.")
    import_skill.add_argument("--write", action="store_true", help="Write the manifest after validation.")

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
    message_contract = message_subcommands.add_parser(
        "contract",
        help="Report the BridgeMessage and workflow CLI-to-CLI routing contract.",
    )
    message_contract.add_argument("--workflow-path", help="Optional workflow JSON path to inspect.")

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

    workflow_parser = subcommands.add_parser("workflow", help="Validate, plan, package, or run workflows.")
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
    workflow_compile = workflow_subcommands.add_parser(
        "compile",
        help="Compile a workflow into an executable workflow package.",
    )
    workflow_compile.add_argument("path", help="Workflow JSON path.")
    workflow_compile.add_argument(
        "--out",
        help="Output package directory. Defaults to runtime/workflow-packages/<workflow_id>.",
    )
    workflow_run_package = workflow_subcommands.add_parser(
        "run-package",
        help="Run a compiled workflow package.",
    )
    workflow_run_package.add_argument("package_dir", help="Compiled workflow package directory.")
    workflow_run_package.add_argument("--dry-run", action="store_true")
    workflow_run_package.add_argument("--yes", action="store_true", help="Confirm high-risk workflow tasks.")
    workflow_run_package.add_argument(
        "--write-golden",
        action="store_true",
        help="Write normalized golden_run.jsonl after the run.",
    )
    workflow_inspect_package = workflow_subcommands.add_parser(
        "inspect-package",
        help="Inspect a compiled workflow package and its run state.",
    )
    workflow_inspect_package.add_argument("package_dir", help="Compiled workflow package directory.")
    workflow_golden = workflow_subcommands.add_parser(
        "golden",
        help="Run a workflow package and regenerate golden_run.jsonl.",
    )
    workflow_golden.add_argument("package_dir", help="Compiled workflow package directory.")
    workflow_golden.add_argument("--dry-run", action="store_true")
    workflow_golden.add_argument("--yes", action="store_true", help="Confirm high-risk workflow tasks.")

    runtime_parser = subcommands.add_parser("runtime", help="Inspect or prepare local runtime dependencies.")
    runtime_subcommands = runtime_parser.add_subparsers(dest="runtime_command")
    runtime_transport = runtime_subcommands.add_parser(
        "transport",
        help="Inspect or install an optional runtime transport backend.",
    )
    runtime_transport.add_argument("kind", choices=["pty"], help="Runtime transport kind.")
    runtime_transport.add_argument("--plan", action="store_true", help="Render the install plan without executing.")
    runtime_transport.add_argument("--install", action="store_true", help="Install the missing backend.")
    runtime_transport.add_argument("--yes", action="store_true", help="Confirm runtime dependency installation.")

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

    plugin_operations = plugin_subcommands.add_parser(
        "operations",
        help="List provider operation descriptors for WebUI/API dispatch.",
    )
    plugin_operations.add_argument("plugin_id", nargs="?", help="Plugin id, for example cli-anything.")

    plugin_validate_operations = plugin_subcommands.add_parser(
        "validate-operations",
        help="Validate provider operation descriptors and side-effect gates.",
    )
    plugin_validate_operations.add_argument("plugin_id", nargs="?", help="Plugin id, for example cli-anything.")

    plugin_operation_plan = plugin_subcommands.add_parser(
        "operation-plan",
        help="Resolve one provider operation descriptor into a dispatch-ready plan.",
    )
    plugin_operation_plan.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_operation_plan.add_argument("operation_id", help="Operation id from plugin operations.")
    plugin_operation_plan.add_argument(
        "--input",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Input value used to resolve descriptor placeholders; repeatable.",
    )
    plugin_operation_plan.add_argument("--yes", action="store_true", help="Confirm side-effecting operation dispatch.")

    plugin_verify_plan = plugin_subcommands.add_parser(
        "verify-plan",
        help="Preview or run a plugin plan's post-operation verification commands.",
    )
    plugin_verify_plan.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_verify_plan.add_argument(
        "--action",
        choices=["install", "update"],
        default="install",
        help="Plugin plan action whose verification commands should be checked.",
    )
    plugin_verify_plan.add_argument(
        "--with-codex-skill",
        action="store_true",
        help="Include optional Codex skill install steps when deriving the plugin plan.",
    )
    plugin_verify_plan.add_argument("--run", action="store_true", help="Run safe read-only verification commands.")
    plugin_verify_plan.add_argument("--timeout-seconds", type=int, default=60)

    plugin_preflight = plugin_subcommands.add_parser("preflight", help="Run install readiness checks.")
    plugin_preflight.add_argument("plugin_id", help="Plugin id, for example cli-anything.")

    plugin_provenance = plugin_subcommands.add_parser(
        "provenance",
        help="Show installed plugin source, package, and entrypoint provenance.",
    )
    plugin_provenance.add_argument("plugin_id", help="Plugin id, for example cli-anything.")

    plugin_check_update = plugin_subcommands.add_parser(
        "check-update",
        help="Check local and optional remote update state without executing update.",
    )
    plugin_check_update.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_check_update.add_argument(
        "--remote",
        action="store_true",
        help="Query the source repository remote HEAD with git ls-remote.",
    )

    plugin_gate = plugin_subcommands.add_parser(
        "gate",
        help="Preview install/update preflight and provenance gates without executing.",
    )
    plugin_gate.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_gate.add_argument(
        "--action",
        choices=["install", "update"],
        default="install",
        help="Operation to check.",
    )

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

    plugin_probe = plugin_subcommands.add_parser(
        "probe-harness",
        help="Read-only probe of CLI-Anything harness dependencies before install.",
    )
    plugin_probe.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_probe.add_argument("harness_name", help="Harness name in CLI-Hub.")
    plugin_probe.add_argument("--title", help="Override generated manifest title.")
    plugin_probe.add_argument("--from-market", action="store_true", default=True)

    plugin_verify = plugin_subcommands.add_parser(
        "verify-harness",
        help="Return the read-only adaptation verification plan for a CLI-Anything harness.",
    )
    plugin_verify.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_verify.add_argument("harness_name", help="Harness name in CLI-Hub.")
    plugin_verify.add_argument("--title", help="Override generated manifest title.")
    plugin_verify.add_argument("--from-market", action="store_true", default=True)
    plugin_verify.add_argument(
        "--offline",
        action="store_false",
        dest="from_market",
        help="Verify without requiring market metadata.",
    )
    plugin_verify.add_argument(
        "--no-workflows",
        action="store_false",
        dest="include_workflows",
        help="Skip workflow reference lookup.",
    )
    plugin_verify.add_argument(
        "--smoke-suite",
        action="store_true",
        help="Run the protocol smoke suite for this harness capability.",
    )
    plugin_verify.add_argument(
        "--smoke-extra-arg",
        action="append",
        default=[],
        help="Extra arg passed to the harness capability when --smoke-suite is used; repeatable.",
    )

    plugin_verify_harness_plan = plugin_subcommands.add_parser(
        "verify-harness-plan",
        help="Preview or run a CLI-Anything harness plan's post-operation verification commands.",
    )
    plugin_verify_harness_plan.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_verify_harness_plan.add_argument(
        "harness_action",
        choices=["install", "update", "uninstall", "launch"],
        help="Harness lifecycle action whose verification commands should be checked.",
    )
    plugin_verify_harness_plan.add_argument("harness_name", help="Harness name in CLI-Hub.")
    plugin_verify_harness_plan.add_argument("extra_args", nargs="*", help="Extra args passed to launch verification planning.")
    plugin_verify_harness_plan.add_argument("--run", action="store_true", help="Run safe read-only verification commands.")
    plugin_verify_harness_plan.add_argument("--timeout-seconds", type=int, default=60)

    plugin_onboard = plugin_subcommands.add_parser(
        "onboard-harness",
        help="Run the CLI-Anything harness discovery, adaptation, install gate, and verification onboarding report.",
    )
    plugin_onboard.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_onboard.add_argument("harness_name", help="Harness name in CLI-Hub.")
    plugin_onboard.add_argument("--title", help="Override generated manifest title.")
    plugin_onboard.add_argument("--from-market", action="store_true", default=True)
    plugin_onboard.add_argument(
        "--offline",
        action="store_false",
        dest="from_market",
        help="Onboard without requiring market metadata.",
    )
    plugin_onboard.add_argument("--write", action="store_true", help="Write the generated harness manifest.")
    plugin_onboard.add_argument("--yes", action="store_true", help="Confirm manifest write when --write is set.")
    plugin_onboard.add_argument(
        "--install",
        action="store_true",
        help="Execute the gated harness install operation when paired with --yes.",
    )
    plugin_onboard.add_argument(
        "--allow-blocked",
        action="store_true",
        help="Execute install even when harness evaluation reports blockers.",
    )
    plugin_onboard.add_argument(
        "--no-workflows",
        action="store_false",
        dest="include_workflows",
        help="Skip workflow reference lookup.",
    )
    plugin_onboard.add_argument(
        "--smoke-suite",
        action="store_true",
        help="Run the protocol smoke suite for this harness capability.",
    )
    plugin_onboard.add_argument(
        "--smoke-extra-arg",
        action="append",
        default=[],
        help="Extra arg passed to the harness capability when --smoke-suite is used; repeatable.",
    )

    plugin_live = plugin_subcommands.add_parser(
        "live-verification",
        help="Return a read-only CLI-Anything live verification snapshot.",
    )
    plugin_live.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_live.add_argument(
        "--harness",
        action="append",
        default=[],
        help="Harness to include; repeatable. Defaults to mermaid and macrocli.",
    )
    plugin_live.add_argument("--candidate-query", default="image", help="Market query used for blocker sampling.")
    plugin_live.add_argument("--candidate-limit", type=int, default=10, help="Maximum market candidates to rank.")
    plugin_live.add_argument(
        "--no-candidates",
        action="store_false",
        dest="include_candidates",
        help="Skip market candidate sampling.",
    )
    plugin_live.add_argument(
        "--no-workflows",
        action="store_false",
        dest="include_workflows",
        help="Skip workflow protocol readiness.",
    )
    plugin_live.add_argument(
        "--smoke-suite",
        action="store_true",
        help="Run protocol smoke suite for every selected harness.",
    )
    plugin_live.add_argument(
        "--smoke-extra-arg",
        action="append",
        default=[],
        help="Extra arg passed to harness capabilities when --smoke-suite is used; repeatable.",
    )

    plugin_mvp_plan = plugin_subcommands.add_parser(
        "mvp-plan",
        help="Return the read-only CLI-Anything install, adaptation, and protocol MVP plan.",
    )
    plugin_mvp_plan.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_mvp_plan.add_argument("--query", default="file", help="Market query used for the install queue.")
    plugin_mvp_plan.add_argument("--limit", type=int, default=20, help="Maximum market records to rank.")
    plugin_mvp_plan.add_argument("--max-harnesses", type=int, default=5, help="Maximum harnesses to gate.")
    plugin_mvp_plan.add_argument("--no-blocked", action="store_false", dest="include_blocked")
    plugin_mvp_plan.set_defaults(include_blocked=True)
    plugin_mvp_plan.add_argument(
        "--workflow-path",
        action="append",
        default=[],
        help="Workflow JSON path to include in the acceptance queue; repeatable.",
    )
    plugin_mvp_plan.add_argument("--max-workflows", type=int, default=10)

    plugin_bootstrap_plan = plugin_subcommands.add_parser(
        "bootstrap-plan",
        help="Return the read-only CLI-Anything plugin bootstrap runbook before first download/install.",
    )
    plugin_bootstrap_plan.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_bootstrap_plan.add_argument("--harness", default="mermaid", help="First harness to prepare after bootstrap.")
    plugin_bootstrap_plan.add_argument("--query", default="file", help="Market query used after cli-hub is installed.")
    plugin_bootstrap_plan.add_argument(
        "--workflow-path",
        default="workflows/cli-anything-macrocli-mermaid-routing.example.json",
        help="Workflow used by the protocol lifecycle runbook stage.",
    )
    plugin_bootstrap_plan.add_argument(
        "--no-workflows",
        action="store_false",
        dest="include_workflows",
        help="Skip workflow readiness from the first harness onboarding preview.",
    )
    plugin_bootstrap_plan.set_defaults(include_workflows=True)

    plugin_candidates = plugin_subcommands.add_parser(
        "candidates",
        help="Rank CLI-Anything market harnesses as install candidates without installing them.",
    )
    plugin_candidates.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_candidates.add_argument("--query", help="Optional CLI-Hub search query; omit to inspect list output.")
    plugin_candidates.add_argument("--limit", type=int, default=50, help="Maximum market records to rank.")
    plugin_candidates.add_argument(
        "--with-probes",
        action="store_true",
        help="Attach read-only local dependency probe summaries to each candidate.",
    )
    plugin_candidates.add_argument(
        "--compact",
        action="store_true",
        help="Omit raw CLI-Hub market stdout and include a concise candidate summary for WebUI/API use.",
    )

    plugin_install_queue = plugin_subcommands.add_parser(
        "install-queue",
        help="Build a read-only CLI-Anything market harness install queue from probed candidates.",
    )
    plugin_install_queue.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_install_queue.add_argument("--query", help="Optional CLI-Hub search query; omit to inspect list output.")
    plugin_install_queue.add_argument("--limit", type=int, default=50, help="Maximum market records to rank.")
    plugin_install_queue.add_argument(
        "--max-installs",
        type=int,
        default=10,
        help="Maximum install-ready harnesses to place in the queue.",
    )
    plugin_install_queue.add_argument(
        "--no-blocked",
        action="store_false",
        dest="include_blocked",
        help="Omit blocked candidates from the queue report.",
    )

    plugin_blocked_plan = plugin_subcommands.add_parser(
        "blocked-plan",
        help="Build a read-only decision report for blocked CLI-Anything market harnesses.",
    )
    plugin_blocked_plan.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_blocked_plan.add_argument(
        "--harness",
        action="append",
        default=[],
        help="Specific harness to inspect; repeatable. Defaults to blocked market install queue entries.",
    )
    plugin_blocked_plan.add_argument("--query", help="Optional CLI-Hub search query when no --harness is provided.")
    plugin_blocked_plan.add_argument("--limit", type=int, default=50, help="Maximum market records to inspect.")

    plugin_repair_plan = plugin_subcommands.add_parser(
        "repair-plan",
        help="Build a read-only repair plan for a CLI-Anything harness entrypoint problem.",
    )
    plugin_repair_plan.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_repair_plan.add_argument("harness_name", help="Harness name from the plugin market.")
    plugin_repair_plan.add_argument("--from-market", action="store_true", default=True)
    plugin_repair_plan.add_argument(
        "--offline",
        action="store_false",
        dest="from_market",
        help="Build repair diagnostics without requiring market metadata.",
    )

    plugin_repair_entrypoint = plugin_subcommands.add_parser(
        "repair-entrypoint",
        help="Plan or confirm a CBN-owned wrapper repair for a missing CLI-Anything entrypoint.",
    )
    plugin_repair_entrypoint.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_repair_entrypoint.add_argument("harness_name", help="Harness name from the plugin market.")
    plugin_repair_entrypoint.add_argument("--from-market", action="store_true", default=True)
    plugin_repair_entrypoint.add_argument(
        "--offline",
        action="store_false",
        dest="from_market",
        help="Repair from current local status without requiring market metadata.",
    )
    plugin_repair_entrypoint.add_argument(
        "--module",
        help="Explicit Python module to run from the project-local wrapper.",
    )
    plugin_repair_entrypoint.add_argument("--write", action="store_true", help="Write wrapper and repaired manifest.")
    plugin_repair_entrypoint.add_argument("--yes", action="store_true", help="Confirm writing repair artifacts.")
    plugin_repair_entrypoint.add_argument(
        "--require-smoke",
        action="store_true",
        help="Require adapter-smoke to pass before confirmed repair writes.",
    )
    plugin_repair_entrypoint.add_argument(
        "--smoke-arg",
        action="append",
        default=[],
        help="Argument passed to adapter smoke; defaults to --help when omitted.",
    )
    plugin_repair_entrypoint.add_argument("--smoke-timeout", type=int, default=10)

    plugin_promotion_gate = plugin_subcommands.add_parser(
        "promotion-gate",
        help="Check whether a repaired CLI-Anything runtime overlay can be promoted to portable manifests.",
    )
    plugin_promotion_gate.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_promotion_gate.add_argument("harness_name", help="Harness name from the plugin market.")
    plugin_promotion_gate.add_argument("--from-market", action="store_true", default=True)
    plugin_promotion_gate.add_argument(
        "--offline",
        action="store_false",
        dest="from_market",
        help="Gate local overlay promotion without requiring market metadata.",
    )
    plugin_promotion_gate.add_argument("--title", help="Optional title override for generated preview manifests.")
    plugin_promotion_gate.add_argument("--no-workflows", action="store_false", dest="include_workflows")
    plugin_promotion_gate.set_defaults(include_workflows=True)
    plugin_promotion_gate.add_argument(
        "--smoke-suite",
        action="store_true",
        help="Run protocol smoke-suite evidence as part of the promotion gate.",
    )
    plugin_promotion_gate.add_argument(
        "--smoke-extra-arg",
        action="append",
        default=[],
        help="Extra arg passed to the capability during protocol smoke-suite.",
    )

    plugin_adapter_targets = plugin_subcommands.add_parser(
        "adapter-targets",
        help="Inspect installed Python packages for CLI-like modules that can back a CLI-Anything adapter.",
    )
    plugin_adapter_targets.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_adapter_targets.add_argument("harness_name", help="Harness name from the plugin market.")
    plugin_adapter_targets.add_argument("--from-market", action="store_true", default=True)
    plugin_adapter_targets.add_argument(
        "--offline",
        action="store_false",
        dest="from_market",
        help="Inspect local packages without requiring market metadata.",
    )
    plugin_adapter_targets.add_argument("--package", help="Inspect one explicit Python distribution name.")
    plugin_adapter_targets.add_argument("--limit", type=int, default=20, help="Maximum adapter targets to return.")

    plugin_adapter_smoke = plugin_subcommands.add_parser(
        "adapter-smoke",
        help="Plan or run a confirmed smoke test for a CLI-Anything adapter target module.",
    )
    plugin_adapter_smoke.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_adapter_smoke.add_argument("harness_name", help="Harness name from the plugin market.")
    plugin_adapter_smoke.add_argument("--from-market", action="store_true", default=True)
    plugin_adapter_smoke.add_argument(
        "--offline",
        action="store_false",
        dest="from_market",
        help="Smoke a module without requiring market metadata.",
    )
    plugin_adapter_smoke.add_argument("--module", required=True, help="Python module candidate to smoke.")
    plugin_adapter_smoke.add_argument(
        "--smoke-arg",
        action="append",
        default=[],
        help="Argument passed to python -m <module>; defaults to --help when omitted.",
    )
    plugin_adapter_smoke.add_argument("--timeout", type=int, default=10, help="Smoke command timeout in seconds.")
    plugin_adapter_smoke.add_argument("--run", action="store_true", help="Execute the smoke command.")
    plugin_adapter_smoke.add_argument("--yes", action="store_true", help="Confirm smoke execution.")

    plugin_adaptation_gate = plugin_subcommands.add_parser(
        "adaptation-gate",
        help="Summarize native launch, repair, adapter target, and smoke readiness for one CLI-Anything harness.",
    )
    plugin_adaptation_gate.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_adaptation_gate.add_argument("harness_name", help="Harness name from the plugin market.")
    plugin_adaptation_gate.add_argument("--from-market", action="store_true", default=True)
    plugin_adaptation_gate.add_argument(
        "--offline",
        action="store_false",
        dest="from_market",
        help="Build the gate without requiring market metadata.",
    )
    plugin_adaptation_gate.add_argument("--module", help="Explicit adapter module to evaluate.")
    plugin_adaptation_gate.add_argument("--no-require-smoke", action="store_false", dest="require_smoke")
    plugin_adaptation_gate.set_defaults(require_smoke=True)
    plugin_adaptation_gate.add_argument(
        "--smoke-arg",
        action="append",
        default=[],
        help="Argument passed to adapter smoke; defaults to --help when omitted.",
    )
    plugin_adaptation_gate.add_argument("--smoke-timeout", type=int, default=10)
    plugin_adaptation_gate.add_argument("--run-smoke", action="store_true", help="Execute adapter smoke.")
    plugin_adaptation_gate.add_argument("--yes", action="store_true", help="Confirm smoke execution.")

    plugin_adaptation_queue = plugin_subcommands.add_parser(
        "adaptation-queue",
        help="Build a read-only adaptation gate queue for multiple CLI-Anything harnesses.",
    )
    plugin_adaptation_queue.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_adaptation_queue.add_argument(
        "--harness",
        action="append",
        default=[],
        help="Specific harness to gate; repeatable. Defaults to market install queue entries.",
    )
    plugin_adaptation_queue.add_argument("--query", help="Optional CLI-Hub search query when no --harness is provided.")
    plugin_adaptation_queue.add_argument("--limit", type=int, default=20)
    plugin_adaptation_queue.add_argument("--max-harnesses", type=int, default=5)
    plugin_adaptation_queue.add_argument("--no-blocked", action="store_false", dest="include_blocked")
    plugin_adaptation_queue.add_argument("--no-require-smoke", action="store_false", dest="require_smoke")
    plugin_adaptation_queue.set_defaults(include_blocked=True, require_smoke=True)
    plugin_adaptation_queue.add_argument(
        "--smoke-arg",
        action="append",
        default=[],
        help="Argument passed to adapter smoke; defaults to --help when omitted.",
    )
    plugin_adaptation_queue.add_argument("--smoke-timeout", type=int, default=10)
    plugin_adaptation_queue.add_argument("--run-smoke", action="store_true", help="Execute adapter smoke for selected gates.")
    plugin_adaptation_queue.add_argument("--yes", action="store_true", help="Confirm smoke execution.")

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
        "--allow-failed-preflight",
        action="store_true",
        help="Execute even when plugin preflight/provenance gates report blockers.",
    )
    plugin_install.add_argument(
        "--with-codex-skill",
        action="store_true",
        help="Also install the optional Codex skill when supported.",
    )

    plugin_update = plugin_subcommands.add_parser("update", help="Update an external plugin.")
    plugin_update.add_argument("plugin_id", help="Plugin id, for example cli-anything.")
    plugin_update.add_argument("--yes", action="store_true", help="Execute the update plan.")
    plugin_update.add_argument(
        "--allow-failed-preflight",
        action="store_true",
        help="Execute even when plugin preflight/provenance gates report blockers.",
    )
    plugin_update.add_argument(
        "--with-codex-skill",
        action="store_true",
        help="Also run the optional Codex skill installer when supported.",
    )
    return parser
