"""CBN command-line interface."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from api_server.routes.health import health_payload
from cbn.cli_args import build_parser
from cbn.paths import resolve_project_paths
from cbn.version import __version__
from cbn_demo.killer import killer_demo_report
from cbn_demo.network_connect import network_connect_package, workflow_studio_demo_link
from cbn_core.agent_cli_importer import agent_cli_card_import_report
from cbn_core.command_importer import command_import_report, parse_key_values
from cbn_core.manifest import validate_manifest_path
from cbn_core.mcp_importer import load_mcp_tool_descriptor, mcp_import_report
from cbn_core.skill_importer import skill_import_report
from cbn_execution.graph import WorkflowGraph
from cbn_parsers.fixtures import run_parser_fixtures
from cbn_parsers.fixture_recorder import record_parser_fixture
from cbn_parsers.registry import ParserRegistry
from cbn_plugins.cli_anything import CliAnythingHub
from cbn_plugins.manager import PluginManager
from cbn_protocol.acceptance import cli_to_cli_acceptance_report
from cbn_protocol.acceptance_queue import cli_to_cli_acceptance_queue
from cbn_protocol.bridge_contract import workflow_bridge_contract_report
from cbn_protocol.bridge_lab import bridge_lab_report
from cbn_protocol.a2a_http import agent_card, smoke_a2a_http
from cbn_protocol.a2a_http import smoke_a2a_workflow_http
from cbn_protocol.acp_stdio import serve_stdio as serve_acp_stdio
from cbn_protocol.acp_stdio import smoke_acp_stdio
from cbn_protocol.acp_stdio import smoke_acp_workflow_stdio
from cbn_core.message import bridge_args_from_selectors, validate_bridge_message
from cbn_core.selector import select_bridge_value
from cbn_protocol.compatibility import check_protocol, protocol_matrix
from cbn_protocol.conformance import protocol_conformance_plan
from cbn_protocol.exports import (
    export_all_protocols,
    export_all_workflow_protocols,
    export_protocol,
    export_workflow_protocol,
    list_protocol_exports,
)
from cbn_protocol.lifecycle_suite import protocol_lifecycle_suite
from cbn_protocol.readiness import protocol_readiness_report
from cbn_protocol.mcp_stdio import serve_stdio, smoke_mcp_stdio
from cbn_protocol.mcp_stdio import smoke_mcp_workflow_stdio
from cbn_protocol.smoke_suite import protocol_smoke_suite
from cbn_protocol.wire_conformance import protocol_wire_conformance_suite
from cbn_runtime.context import build_runtime
from cbn_workflow.catalog import inspect_workflow, list_workflows
from cbn_workflow.package import compile_workflow_package, inspect_workflow_package, run_workflow_package
from api_server.server import ROUTE_SUMMARY, serve
from nodes import CAPABILITY_NODE_MAPPINGS, init_builtin_nodes


def main(argv: list[str] | None = None) -> int:
    _configure_stdio_utf8()
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

    if args.command == "registry":
        if args.registry_command == "validate":
            result = validate_manifest_path(Path(args.path), known_parser_refs=_known_parser_refs())
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["valid"] else 7
        runtime = build_runtime()
        if args.registry_command == "list":
            payload = [manifest.as_record() for manifest in runtime.registry.list()]
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        if args.registry_command == "search":
            print(json.dumps(runtime.registry.search(args.query, limit=args.limit), ensure_ascii=False, indent=2))
            return 0
        if args.registry_command == "inspect":
            manifest = runtime.registry.require(args.capability_id)
            print(json.dumps(manifest.as_record(), ensure_ascii=False, indent=2))
            return 0

    if args.command == "call":
        runtime = build_runtime()
        result = runtime.executor.call(
            args.capability_id,
            extra_args=tuple(args.extra_args),
            dry_run=args.dry_run,
            confirmed=args.yes,
            approval_id=args.approval_id,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 3

    if args.command == "audit":
        runtime = build_runtime()
        if args.audit_command == "tail":
            print(json.dumps(runtime.audit_log.tail(limit=args.limit), ensure_ascii=False, indent=2))
            return 0

    if args.command == "event":
        runtime = build_runtime()
        if args.event_command == "tail":
            print(json.dumps(runtime.event_bus.tail(limit=args.limit), ensure_ascii=False, indent=2))
            return 0

    if args.command == "artifact":
        runtime = build_runtime()
        if args.artifact_command == "list":
            print(json.dumps(runtime.artifact_store.list(limit=args.limit), ensure_ascii=False, indent=2))
            return 0
        if args.artifact_command == "inspect":
            print(
                json.dumps(
                    runtime.artifact_store.inspect(args.artifact_id),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

    if args.command == "parser":
        runtime = build_runtime()
        if args.parser_command == "list":
            print(json.dumps(runtime.parser_registry.list(), ensure_ascii=False, indent=2))
            return 0
        if args.parser_command == "inspect":
            print(
                json.dumps(
                    runtime.parser_registry.inspect(args.parser_ref),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.parser_command == "fixtures":
            result = run_parser_fixtures(
                Path(args.path),
                parser_ref=args.parser_ref,
                registry=runtime.parser_registry,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 7

    if args.command == "record-parser-fixture":
        result = record_parser_fixture(
            parser_ref=args.parser_ref,
            case_id=args.case_id,
            stdout=_read_text_option(args.stdout, args.stdout_file),
            stderr=_read_text_option(args.stderr, args.stderr_file),
            title=args.title,
            fixture_id=args.fixture_id,
            verified_capabilities=tuple(args.verified_capability),
            expect_failure=args.expect_failure,
            error_contains=args.error_contains,
            output_path=Path(args.output) if args.output else None,
            write=args.write,
            registry=ParserRegistry.builtins(),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 12

    if args.command == "protocol":
        runtime = build_runtime()
        if args.protocol_command == "list":
            print(json.dumps(list_protocol_exports(), ensure_ascii=False, indent=2))
            return 0
        if args.protocol_command == "export":
            if args.target == "all":
                payload = export_all_protocols(runtime.registry, capability_id=args.capability_id)
            else:
                payload = export_protocol(
                    runtime.registry,
                    args.target,
                    capability_id=args.capability_id,
                )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        if args.protocol_command == "export-workflows":
            if args.target == "all":
                payload = export_all_workflow_protocols(runtime.registry, workflow_path=args.path)
            else:
                payload = export_workflow_protocol(runtime.registry, args.target, workflow_path=args.path)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        if args.protocol_command == "check":
            payload = check_protocol(
                runtime.registry,
                args.target,
                capability_id=args.capability_id,
                workflow_path=args.workflow_path,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        if args.protocol_command == "matrix":
            payload = protocol_matrix(
                runtime.registry,
                include_workflows=args.include_workflows,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        if args.protocol_command == "readiness":
            payload = protocol_readiness_report(
                runtime.registry,
                workflow_path=args.workflow_path,
                include_workflows=args.include_workflows,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload["ok"] else 7
        if args.protocol_command == "conformance-plan":
            payload = protocol_conformance_plan(
                runtime.registry,
                target=args.target,
                capability_id=args.capability_id,
                workflow_path=args.workflow_path,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload["ok"] else 7
        if args.protocol_command == "lifecycle-suite":
            payload = protocol_lifecycle_suite(
                capability_id=args.capability_id,
                workflow_path=args.workflow_path,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload["ok"] else 9
        if args.protocol_command == "wire-conformance":
            payload = protocol_wire_conformance_suite(
                target=args.target,
                capability_id=args.capability_id,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload["ok"] else 9
        if args.protocol_command == "smoke-suite":
            payload = protocol_smoke_suite(
                runtime.registry,
                capability_ids=tuple(args.capability_id) or None,
                workflow_paths=tuple(args.workflow_path) or None,
                extra_args=tuple(args.extra_arg),
                dry_run=args.dry_run,
                workflow_dry_run=args.workflow_dry_run,
                workflow_confirmed=args.yes,
                include_payloads=args.include_payloads,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload["ok"] else 9
        if args.protocol_command == "accept-workflow":
            payload = cli_to_cli_acceptance_report(
                runtime.registry,
                runtime.workflow_runner,
                args.workflow_path,
                run=args.run,
                dry_run=args.dry_run,
                confirmed=args.yes,
                include_payloads=args.include_payloads,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload["ok"] else 10
        if args.protocol_command == "acceptance-queue":
            payload = cli_to_cli_acceptance_queue(
                runtime.registry,
                runtime.workflow_runner,
                workflow_paths=tuple(args.workflow_path) or None,
                max_workflows=args.max_workflows,
                run=args.run,
                dry_run=args.dry_run,
                confirmed=args.yes,
                include_payloads=args.include_payloads,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload["ok"] else 10
        if args.protocol_command == "bridge-lab":
            payload = bridge_lab_report(
                runtime.registry,
                runtime.workflow_runner,
                workflow_paths=tuple(args.workflow_path),
                max_workflows=args.max_workflows,
                run=args.run,
                dry_run=args.dry_run,
                confirmed=args.yes,
                include_payloads=args.include_payloads,
                run_smoke_suite=args.smoke_suite,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload["ok"] else 10

    if args.command == "demo":
        runtime = build_runtime()
        if args.demo_command == "killer":
            payload = killer_demo_report(
                runtime.registry,
                runtime.workflow_runner,
                workflow_path=args.workflow_path,
                run=args.run,
                dry_run=args.dry_run,
                confirmed=args.yes,
                include_payloads=args.include_payloads,
                run_smoke_suite=args.smoke_suite,
                event_tail=runtime.event_bus.tail(limit=30),
                audit_tail=runtime.audit_log.tail(limit=30),
                artifact_list=runtime.artifact_store.list(limit=30),
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload["ok"] else 10

    if args.command == "import":
        if args.import_command == "command":
            payload = command_import_report(
                capability_id=args.capability_id,
                command=args.executable,
                args_template=tuple(args.arg),
                title=args.title,
                transport=args.transport,
                parser_ref=args.parser_ref,
                verified=args.verified,
                risk=args.risk,
                requires_confirmation=args.requires_confirmation,
                network=args.network,
                cwd_policy=args.cwd_policy,
                timeout_seconds=args.timeout_seconds,
                labels=parse_key_values(args.label),
                annotations=parse_key_values(args.annotation),
                write=args.write,
                output_path=Path(args.output) if args.output else None,
                known_parser_refs=_known_parser_refs(),
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload["ok"] else 11
        if args.import_command == "cli-anything":
            if (args.write or args.install) and not args.yes:
                return _print_cli_error(
                    "confirmation_required",
                    "cli-anything import side effects require --yes",
                )
            runtime = build_runtime() if args.install and args.yes else None
            payload = CliAnythingHub().onboard_harness(
                args.harness_name,
                title=args.title,
                from_market=args.from_market,
                write=args.write,
                confirmed=args.yes,
                install=args.install,
                allow_blocked=args.allow_blocked,
                include_workflows=args.include_workflows,
                run_smoke_suite=args.smoke_suite,
                smoke_extra_args=tuple(args.smoke_extra_arg),
                operation_runner=runtime.plugin_runner if runtime else None,
            )
            payload = {
                **payload,
                "entrypoint": "cbn import cli-anything",
                "compatibility": {
                    "plugin_command": (
                        "python -m cbn plugin onboard-harness "
                        f"cli-anything {args.harness_name}"
                    ),
                    "facade_for": "CliAnythingHub.onboard_harness",
                },
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload["ok"] else 11
        if args.import_command == "agent-cli-card":
            payload = agent_cli_card_import_report(
                Path(args.card_file),
                write=args.write,
                output_dir=Path(args.output_dir) if args.output_dir else None,
                known_parser_refs=_known_parser_refs(),
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload["ok"] else 11
        if args.import_command == "mcp":
            payload = mcp_import_report(
                load_mcp_tool_descriptor(Path(args.tool_file), tool_name=args.tool_name),
                server_id=args.server_id,
                adapter_command=args.adapter_command,
                adapter_args=tuple(args.adapter_arg),
                capability_id=args.capability_id,
                title=args.title,
                parser_ref=args.parser_ref,
                verified=args.verified,
                risk=args.risk,
                requires_confirmation=args.requires_confirmation,
                network=args.network,
                timeout_seconds=args.timeout_seconds,
                write=args.write,
                output_path=Path(args.output) if args.output else None,
                known_parser_refs=_known_parser_refs(),
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload["ok"] else 11
        if args.import_command == "skill":
            payload = skill_import_report(
                Path(args.skill_file),
                command=args.executable,
                args_template=tuple(args.arg),
                capability_id=args.capability_id,
                title=args.title,
                parser_ref=args.parser_ref,
                verified=args.verified,
                risk=args.risk,
                requires_confirmation=args.requires_confirmation,
                network=args.network,
                timeout_seconds=args.timeout_seconds,
                write=args.write,
                output_path=Path(args.output) if args.output else None,
                known_parser_refs=_known_parser_refs(),
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload["ok"] else 11

    if args.command == "mcp":
        if args.mcp_command == "serve":
            if not args.stdio:
                parser.error("mcp serve currently requires --stdio")
            return serve_stdio()
        if args.mcp_command == "smoke":
            payload = smoke_mcp_stdio(
                args.capability_id,
                extra_args=args.extra_arg,
                dry_run=args.dry_run,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload["ok"] else 9
        if args.mcp_command == "smoke-workflow":
            payload = smoke_mcp_workflow_stdio(args.path, dry_run=args.dry_run, confirmed=args.yes)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload["ok"] else 9

    if args.command == "a2a":
        if args.a2a_command == "agent-card":
            print(json.dumps(agent_card(args.base_url), ensure_ascii=False, indent=2))
            return 0
        if args.a2a_command == "smoke":
            payload = smoke_a2a_http(args.capability_id, extra_args=args.extra_arg)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload["ok"] else 9
        if args.a2a_command == "smoke-workflow":
            payload = smoke_a2a_workflow_http(args.path, dry_run=args.dry_run, confirmed=args.yes)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload["ok"] else 9

    if args.command == "acp":
        if args.acp_command == "serve":
            if not args.stdio:
                parser.error("acp serve currently requires --stdio")
            return serve_acp_stdio()
        if args.acp_command == "smoke":
            payload = smoke_acp_stdio(
                args.capability_id,
                extra_args=args.extra_arg,
                dry_run=args.dry_run,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload["ok"] else 9
        if args.acp_command == "smoke-workflow":
            payload = smoke_acp_workflow_stdio(args.path, dry_run=args.dry_run, confirmed=args.yes)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload["ok"] else 9

    if args.command == "message":
        if args.message_command == "contract":
            runtime = build_runtime()
            result = workflow_bridge_contract_report(runtime.registry, workflow_path=args.workflow_path)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 7
        message = _read_json_arg(args.path)
        if args.message_command == "validate":
            result = validate_bridge_message(message)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["valid"] else 7
        if args.message_command == "select":
            try:
                print(json.dumps(select_bridge_value(message, args.selector), ensure_ascii=False, indent=2))
                return 0
            except (KeyError, IndexError, ValueError) as exc:
                print(json.dumps({"error": str(exc), "selector": args.selector}, ensure_ascii=False, indent=2))
                return 8
        if args.message_command == "args":
            try:
                result = bridge_args_from_selectors(message, list(args.selectors))
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0 if result["valid"] else 7
            except (KeyError, IndexError, ValueError) as exc:
                print(json.dumps({"error": str(exc), "selectors": args.selectors}, ensure_ascii=False, indent=2))
                return 8

    if args.command == "approvals":
        runtime = build_runtime()
        if args.approvals_command == "list":
            print(
                json.dumps(
                    runtime.approval_store.list(status=args.status, limit=args.limit),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.approvals_command == "show":
            print(
                json.dumps(
                    runtime.approval_store.inspect(args.approval_id),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.approvals_command == "approve":
            approval = runtime.approval_store.decide(
                args.approval_id,
                "approved",
                actor="cli",
                reason=args.reason,
            )
            runtime.event_bus.publish(
                "approval.decided",
                approval["capability_id"],
                {"approval": approval},
                correlation_id=approval["call_id"],
            )
            print(json.dumps(approval, ensure_ascii=False, indent=2))
            return 0
        if args.approvals_command == "deny":
            approval = runtime.approval_store.decide(
                args.approval_id,
                "denied",
                actor="cli",
                reason=args.reason,
            )
            runtime.event_bus.publish(
                "approval.decided",
                approval["capability_id"],
                {"approval": approval},
                correlation_id=approval["call_id"],
            )
            print(json.dumps(approval, ensure_ascii=False, indent=2))
            return 0

    if args.command == "workflow":
        runtime = build_runtime()
        if args.workflow_command == "list":
            print(json.dumps(list_workflows(registry=runtime.registry), ensure_ascii=False, indent=2))
            return 0
        if args.workflow_command == "inspect":
            result = inspect_workflow(Path(args.path), registry=runtime.registry)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["valid"] else 7
        if args.workflow_command == "compile":
            result = compile_workflow_package(
                Path(args.path),
                Path(args.out) if args.out else None,
                runtime.registry,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["lock_status"]["ok"] else 7
        if args.workflow_command == "run-package":
            result = run_workflow_package(
                Path(args.package_dir),
                runtime.registry,
                runtime.workflow_runner,
                dry_run=args.dry_run,
                confirmed=args.yes,
                write_golden=args.write_golden,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 4
        if args.workflow_command == "inspect-package":
            result = inspect_workflow_package(Path(args.package_dir), registry=runtime.registry)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 7
        if args.workflow_command == "golden":
            result = run_workflow_package(
                Path(args.package_dir),
                runtime.registry,
                runtime.workflow_runner,
                dry_run=args.dry_run,
                confirmed=args.yes,
                write_golden=True,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 4
        graph = WorkflowGraph.from_file(Path(args.path))
        if args.workflow_command == "validate":
            graph.validate()
            print(json.dumps({"valid": True, "workflow_id": graph.workflow_id}, ensure_ascii=False, indent=2))
            return 0
        if args.workflow_command == "plan":
            print(json.dumps(runtime.workflow_runner.plan(graph), ensure_ascii=False, indent=2))
            return 0
        if args.workflow_command == "run":
            result = runtime.workflow_runner.run(
                graph,
                dry_run=args.dry_run,
                confirmed=args.yes,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == "completed" else 4

    if args.command == "network":
        runtime = build_runtime()
        if args.network_command == "connect-package":
            result = network_connect_package(
                runtime.registry,
                workflow_path=args.workflow_path,
                base_url=args.base_url,
                studio_url=args.studio_url,
                session_token=args.session_token,
                agent_message=args.message,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 7
        if args.network_command == "quickstart":
            result = network_connect_package(
                runtime.registry,
                workflow_path=args.workflow_path,
                base_url=args.base_url,
                studio_url=args.studio_url,
                session_token=args.session_token,
                agent_message=args.message,
            )
            quickstart = result.get("consumer_quickstart", {})
            if args.output == "curl":
                print(quickstart.get("curl_script", ""))
            elif args.output == "powershell":
                print(quickstart.get("powershell_script", ""))
            elif args.output == "acceptance":
                print(json.dumps(quickstart.get("acceptance", {}), ensure_ascii=False, indent=2))
            else:
                print(json.dumps(quickstart, ensure_ascii=False, indent=2))
            return 0 if result["ok"] and quickstart.get("kind") == "NetworkConnectQuickstart" else 7
        if args.network_command == "studio-link":
            result = workflow_studio_demo_link(
                workflow_path=args.workflow_path,
                daemon_url=args.daemon_url,
                studio_url=args.studio_url,
                session_token=args.session_token,
                agent_message=args.message,
                dry_run=args.dry_run,
                confirmed=args.confirmed,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 7

    if args.command == "runtime":
        manager = PluginManager()
        if args.runtime_command == "transport":
            if args.install:
                gate = manager.runtime_transport_gate(args.kind)
                if not gate["ok"]:
                    print(json.dumps(gate, ensure_ascii=False, indent=2))
                    return 13
                plan = manager.runtime_transport_plan(args.kind)
                if not args.yes:
                    print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2))
                    return 2
                runtime = build_runtime()
                result = runtime.plugin_runner.execute(plan)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return _operation_exit_code(result)
            if args.plan:
                plan = manager.runtime_transport_plan(args.kind)
                print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2))
                return 0
            result = manager.runtime_transport_status(args.kind)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ready"] else 5

    if args.command == "daemon":
        if args.daemon_command == "routes":
            print(json.dumps(ROUTE_SUMMARY, ensure_ascii=False, indent=2))
            return 0
        if args.daemon_command == "serve":
            serve(host=args.host, port=args.port)
            return 0

    if args.command == "plugin":
        manager = PluginManager()
        if args.plugin_command == "list":
            print(json.dumps(manager.list_plugins(), ensure_ascii=False, indent=2))
            return 0
        if args.plugin_command == "info":
            print(json.dumps(manager.plugin_info(args.plugin_id), ensure_ascii=False, indent=2))
            return 0
        if args.plugin_command == "operations":
            print(json.dumps(manager.operation_catalog(args.plugin_id), ensure_ascii=False, indent=2))
            return 0
        if args.plugin_command == "validate-operations":
            result = manager.validate_operation_catalog(args.plugin_id)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 13
        if args.plugin_command == "operation-plan":
            result = manager.operation_plan(
                args.plugin_id,
                args.operation_id,
                inputs=_parse_operation_inputs(args.input),
                confirmed=args.yes,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 13
        if args.plugin_command == "verify-plan":
            result = manager.verify_plan(
                args.plugin_id,
                action=args.action,
                include_codex_skill=args.with_codex_skill,
                run=args.run,
                timeout_seconds=args.timeout_seconds,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 13
        if args.plugin_command == "preflight":
            result = manager.preflight(args.plugin_id)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ready"] else 5
        if args.plugin_command == "provenance":
            print(json.dumps(manager.provenance(args.plugin_id), ensure_ascii=False, indent=2))
            return 0
        if args.plugin_command == "check-update":
            result = manager.update_check(args.plugin_id, remote=args.remote)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ready_for_update"] else 13
        if args.plugin_command == "gate":
            result = manager.operation_gate(args.plugin_id, args.action)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 13
        if args.plugin_command == "status":
            if args.plugin_id != "cli-anything":
                raise KeyError(f"status is not implemented for plugin: {args.plugin_id}")
            print(json.dumps(CliAnythingHub().status(), ensure_ascii=False, indent=2))
            return 0
        if args.plugin_command == "market":
            if args.plugin_id != "cli-anything":
                raise KeyError(f"market is not implemented for plugin: {args.plugin_id}")
            hub = CliAnythingHub()
            if args.market_command == "list":
                result = hub.list_market()
            elif args.market_command == "search":
                if not args.query:
                    parser.error("plugin market search requires a query")
                result = hub.search_market(args.query)
            else:
                if not args.query:
                    parser.error("plugin market info requires a harness name")
                result = hub.info(args.query)
            print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
            return 0 if result.exit_code == 0 else result.exit_code
        if args.plugin_command == "import-harness":
            if args.plugin_id != "cli-anything":
                raise KeyError(f"import-harness is not implemented for plugin: {args.plugin_id}")
            hub = CliAnythingHub()
            market_record = None
            if args.from_market:
                market_record = hub.market_record_for_harness(args.harness_name)
                if market_record is None:
                    print(
                        json.dumps(
                            {
                                "error": "CLI-Anything market record not found",
                                "plugin_id": args.plugin_id,
                                "harness_name": args.harness_name,
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
                    return 6
            if args.write:
                path = hub.write_harness_manifest(args.harness_name, title=args.title, market_record=market_record)
                print(json.dumps({"written": str(path)}, ensure_ascii=False, indent=2))
            else:
                print(
                    json.dumps(
                        hub.manifest_for_harness(args.harness_name, title=args.title, market_record=market_record),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            return 0
        if args.plugin_command == "adapt-harness":
            if args.plugin_id != "cli-anything":
                raise KeyError(f"adapt-harness is not implemented for plugin: {args.plugin_id}")
            result = CliAnythingHub().adapt_harness(
                args.harness_name,
                title=args.title,
                from_market=args.from_market,
                write=args.write,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 6
        if args.plugin_command == "prepare-harness":
            if args.plugin_id != "cli-anything":
                raise KeyError(f"prepare-harness is not implemented for plugin: {args.plugin_id}")
            result = CliAnythingHub().prepare_harness(
                args.harness_name,
                title=args.title,
                from_market=args.from_market,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 6
        if args.plugin_command == "evaluate-harness":
            if args.plugin_id != "cli-anything":
                raise KeyError(f"evaluate-harness is not implemented for plugin: {args.plugin_id}")
            result = CliAnythingHub().evaluate_harness(
                args.harness_name,
                title=args.title,
                from_market=args.from_market,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 6
        if args.plugin_command == "probe-harness":
            if args.plugin_id != "cli-anything":
                raise KeyError(f"probe-harness is not implemented for plugin: {args.plugin_id}")
            result = CliAnythingHub().probe_harness(
                args.harness_name,
                title=args.title,
                from_market=args.from_market,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 6
        if args.plugin_command == "verify-harness":
            if args.plugin_id != "cli-anything":
                raise KeyError(f"verify-harness is not implemented for plugin: {args.plugin_id}")
            result = CliAnythingHub().verify_harness(
                args.harness_name,
                title=args.title,
                from_market=args.from_market,
                include_workflows=args.include_workflows,
                run_smoke_suite=args.smoke_suite,
                smoke_extra_args=tuple(args.smoke_extra_arg),
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 6
        if args.plugin_command == "verify-harness-plan":
            if args.plugin_id != "cli-anything":
                raise KeyError(f"verify-harness-plan is not implemented for plugin: {args.plugin_id}")
            result = CliAnythingHub().verify_harness_plan(
                args.harness_action,
                args.harness_name,
                extra_args=tuple(args.extra_args),
                run=args.run,
                timeout_seconds=args.timeout_seconds,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 6
        if args.plugin_command == "onboard-harness":
            if args.plugin_id != "cli-anything":
                raise KeyError(f"onboard-harness is not implemented for plugin: {args.plugin_id}")
            runtime = build_runtime() if args.install and args.yes else None
            result = CliAnythingHub().onboard_harness(
                args.harness_name,
                title=args.title,
                from_market=args.from_market,
                write=args.write,
                confirmed=args.yes,
                install=args.install,
                allow_blocked=args.allow_blocked,
                include_workflows=args.include_workflows,
                run_smoke_suite=args.smoke_suite,
                smoke_extra_args=tuple(args.smoke_extra_arg),
                operation_runner=runtime.plugin_runner if runtime else None,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 6
        if args.plugin_command == "live-verification":
            if args.plugin_id != "cli-anything":
                raise KeyError(f"live-verification is not implemented for plugin: {args.plugin_id}")
            harnesses = tuple(args.harness) if args.harness else ("mermaid", "macrocli")
            result = CliAnythingHub().live_verification(
                harnesses=harnesses,
                candidate_query=args.candidate_query,
                candidate_limit=args.candidate_limit,
                include_candidates=args.include_candidates,
                include_workflows=args.include_workflows,
                run_smoke_suite=args.smoke_suite,
                smoke_extra_args=tuple(args.smoke_extra_arg),
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 6
        if args.plugin_command == "mvp-plan":
            if args.plugin_id != "cli-anything":
                raise KeyError(f"mvp-plan is not implemented for plugin: {args.plugin_id}")
            runtime = build_runtime()
            result = CliAnythingHub().mvp_plan(
                query=args.query,
                limit=args.limit,
                max_harnesses=args.max_harnesses,
                include_blocked=args.include_blocked,
                workflow_paths=tuple(args.workflow_path),
                max_workflows=args.max_workflows,
                registry=runtime.registry,
                workflow_runner=runtime.workflow_runner,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 6
        if args.plugin_command == "bootstrap-plan":
            if args.plugin_id != "cli-anything":
                raise KeyError(f"bootstrap-plan is not implemented for plugin: {args.plugin_id}")
            result = CliAnythingHub().bootstrap_plan(
                harness_name=args.harness,
                query=args.query,
                include_workflows=args.include_workflows,
                workflow_path=args.workflow_path,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 6
        if args.plugin_command == "candidates":
            if args.plugin_id != "cli-anything":
                raise KeyError(f"candidates is not implemented for plugin: {args.plugin_id}")
            result = CliAnythingHub().candidate_harnesses(
                query=args.query,
                limit=args.limit,
                with_probes=args.with_probes,
                compact=args.compact,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 6
        if args.plugin_command == "install-queue":
            if args.plugin_id != "cli-anything":
                raise KeyError(f"install-queue is not implemented for plugin: {args.plugin_id}")
            result = CliAnythingHub().market_install_queue(
                query=args.query,
                limit=args.limit,
                max_installs=args.max_installs,
                include_blocked=args.include_blocked,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 6
        if args.plugin_command == "blocked-plan":
            if args.plugin_id != "cli-anything":
                raise KeyError(f"blocked-plan is not implemented for plugin: {args.plugin_id}")
            result = CliAnythingHub().blocked_harness_plan(
                harnesses=tuple(args.harness),
                query=args.query,
                limit=args.limit,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 6
        if args.plugin_command == "repair-plan":
            if args.plugin_id != "cli-anything":
                raise KeyError(f"repair-plan is not implemented for plugin: {args.plugin_id}")
            result = CliAnythingHub().entrypoint_repair_plan(
                args.harness_name,
                from_market=args.from_market,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 6
        if args.plugin_command == "repair-entrypoint":
            if args.plugin_id != "cli-anything":
                raise KeyError(f"repair-entrypoint is not implemented for plugin: {args.plugin_id}")
            if args.write and not args.yes:
                return _print_cli_error(
                    "confirmation_required",
                    "entrypoint repair writes require --yes",
                )
            result = CliAnythingHub().repair_entrypoint(
                args.harness_name,
                from_market=args.from_market,
                module=args.module,
                write=args.write,
                confirmed=args.yes,
                require_smoke=args.require_smoke,
                smoke_args=tuple(args.smoke_arg) if args.smoke_arg else ("--help",),
                smoke_timeout_seconds=args.smoke_timeout,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 6
        if args.plugin_command == "promotion-gate":
            if args.plugin_id != "cli-anything":
                raise KeyError(f"promotion-gate is not implemented for plugin: {args.plugin_id}")
            result = CliAnythingHub().promotion_gate(
                args.harness_name,
                title=args.title,
                from_market=args.from_market,
                include_workflows=args.include_workflows,
                run_smoke_suite=args.smoke_suite,
                smoke_extra_args=tuple(args.smoke_extra_arg),
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 6
        if args.plugin_command == "adapter-targets":
            if args.plugin_id != "cli-anything":
                raise KeyError(f"adapter-targets is not implemented for plugin: {args.plugin_id}")
            result = CliAnythingHub().adapter_targets(
                args.harness_name,
                from_market=args.from_market,
                package=args.package,
                limit=args.limit,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 6
        if args.plugin_command == "adapter-smoke":
            if args.plugin_id != "cli-anything":
                raise KeyError(f"adapter-smoke is not implemented for plugin: {args.plugin_id}")
            if args.run and not args.yes:
                return _print_cli_error(
                    "confirmation_required",
                    "adapter smoke execution requires --yes",
                )
            result = CliAnythingHub().adapter_target_smoke(
                args.harness_name,
                module=args.module,
                from_market=args.from_market,
                smoke_args=tuple(args.smoke_arg) if args.smoke_arg else ("--help",),
                timeout_seconds=args.timeout,
                run=args.run,
                confirmed=args.yes,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 6
        if args.plugin_command == "adaptation-gate":
            if args.plugin_id != "cli-anything":
                raise KeyError(f"adaptation-gate is not implemented for plugin: {args.plugin_id}")
            if args.run_smoke and not args.yes:
                return _print_cli_error(
                    "confirmation_required",
                    "adaptation gate smoke execution requires --yes",
                )
            result = CliAnythingHub().adaptation_gate(
                args.harness_name,
                from_market=args.from_market,
                module=args.module,
                require_smoke=args.require_smoke,
                run_smoke=args.run_smoke,
                confirmed=args.yes,
                smoke_args=tuple(args.smoke_arg) if args.smoke_arg else ("--help",),
                smoke_timeout_seconds=args.smoke_timeout,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 6
        if args.plugin_command == "adaptation-queue":
            if args.plugin_id != "cli-anything":
                raise KeyError(f"adaptation-queue is not implemented for plugin: {args.plugin_id}")
            if args.run_smoke and not args.yes:
                return _print_cli_error(
                    "confirmation_required",
                    "adaptation queue smoke execution requires --yes",
                )
            if args.run_smoke and not args.harness and args.include_blocked:
                return _print_cli_error(
                    "blocked",
                    "adaptation queue smoke execution requires explicit --harness entries or --no-blocked",
                )
            result = CliAnythingHub().adaptation_queue(
                harnesses=tuple(args.harness),
                query=args.query,
                limit=args.limit,
                max_harnesses=args.max_harnesses,
                include_blocked=args.include_blocked,
                require_smoke=args.require_smoke,
                run_smoke=args.run_smoke,
                confirmed=args.yes,
                smoke_args=tuple(args.smoke_arg) if args.smoke_arg else ("--help",),
                smoke_timeout_seconds=args.smoke_timeout,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 6
        if args.plugin_command == "sync-market":
            if args.plugin_id != "cli-anything":
                raise KeyError(f"sync-market is not implemented for plugin: {args.plugin_id}")
            result = CliAnythingHub().sync_market(
                query=args.query,
                limit=args.limit,
                write=args.write,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 6
        if args.plugin_command == "harness":
            if args.plugin_id != "cli-anything":
                raise KeyError(f"harness operations are not implemented for plugin: {args.plugin_id}")
            hub = CliAnythingHub()
            if args.harness_action == "status":
                print(
                    json.dumps(
                        hub.harness_status(args.harness_name, from_market=args.from_market),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0
            plan = hub.harness_plan(
                args.harness_action,
                args.harness_name,
                extra_args=tuple(args.extra_args),
            )
            if not args.yes:
                print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2))
                return 2
            if args.harness_action in {"install", "update"} and not args.allow_blocked:
                gate = hub.harness_operation_gate(
                    args.harness_action,
                    args.harness_name,
                    from_market=not args.offline,
                )
                if not gate["ok"]:
                    print(json.dumps(gate, ensure_ascii=False, indent=2))
                    return 12
            runtime = build_runtime()
            result = runtime.plugin_runner.execute(plan)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return _operation_exit_code(result)
        if args.plugin_command == "plan":
            plan = manager.plan(
                args.plugin_id,
                action=args.action,
                include_codex_skill=args.with_codex_skill,
            )
            print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2))
            return 0
        if args.plugin_command == "install":
            plan = manager.plan(
                args.plugin_id,
                action="install",
                include_codex_skill=args.with_codex_skill,
            )
            if not args.yes:
                print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2))
                return 2
            if not args.allow_failed_preflight:
                gate = manager.operation_gate(args.plugin_id, "install")
                if not gate["ok"]:
                    print(json.dumps(gate, ensure_ascii=False, indent=2))
                    return 13
            runtime = build_runtime()
            result = runtime.plugin_runner.execute(plan)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return _operation_exit_code(result)
        if args.plugin_command == "update":
            plan = manager.plan(
                args.plugin_id,
                action="update",
                include_codex_skill=args.with_codex_skill,
            )
            if not args.yes:
                print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2))
                return 2
            if not args.allow_failed_preflight:
                gate = manager.operation_gate(args.plugin_id, "update")
                if not gate["ok"]:
                    print(json.dumps(gate, ensure_ascii=False, indent=2))
                    return 13
            runtime = build_runtime()
            result = runtime.plugin_runner.execute(plan)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return _operation_exit_code(result)

    parser.print_help()
    return 0


def _configure_stdio_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def _read_json_arg(path: str) -> dict:
    if path == "-":
        return json.loads(sys.stdin.read())
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _read_text_option(value: str, path: str | None) -> str:
    if path is None:
        return value
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def _known_parser_refs() -> set[str]:
    return {item["parser_ref"] for item in ParserRegistry.builtins().list()}


def _parse_operation_inputs(values: list[str]) -> dict:
    parsed: dict[str, object] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"operation input must use KEY=VALUE: {value}")
        key, raw = value.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"operation input key is empty: {value}")
        try:
            parsed[key] = json.loads(raw)
        except json.JSONDecodeError:
            parsed[key] = raw
    return parsed


def _operation_exit_code(result: dict) -> int:
    status = result.get("status")
    if status == "completed":
        return 0
    if status == "blocked":
        return 14
    return 15


def _print_cli_error(error_type: str, message: str) -> int:
    print(
        json.dumps(
            {
                "ok": False,
                "error_type": error_type,
                "error": message,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 6
