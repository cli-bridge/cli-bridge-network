"""CBN command-line interface."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from api_server.routes.health import health_payload
from cbn.cli_args import build_parser
from cbn.paths import resolve_project_paths
from cbn.version import __version__
from cbn_core.manifest import validate_manifest_path
from cbn_execution.graph import WorkflowGraph
from cbn_parsers.fixtures import run_parser_fixtures
from cbn_parsers.registry import ParserRegistry
from cbn_plugins.cli_anything import CliAnythingHub
from cbn_plugins.manager import PluginManager
from cbn_protocol.acceptance import cli_to_cli_acceptance_report
from cbn_protocol.bridge_contract import workflow_bridge_contract_report
from cbn_protocol.a2a_http import agent_card, smoke_a2a_http
from cbn_protocol.a2a_http import smoke_a2a_workflow_http
from cbn_protocol.acp_stdio import serve_stdio as serve_acp_stdio
from cbn_protocol.acp_stdio import smoke_acp_stdio
from cbn_protocol.acp_stdio import smoke_acp_workflow_stdio
from cbn_protocol.envelope import bridge_args_from_selectors, select_bridge_value, validate_bridge_message
from cbn_protocol.compatibility import check_protocol, protocol_matrix
from cbn_protocol.exports import (
    export_all_protocols,
    export_all_workflow_protocols,
    export_protocol,
    export_workflow_protocol,
    list_protocol_exports,
)
from cbn_protocol.readiness import protocol_readiness_report
from cbn_protocol.mcp_stdio import serve_stdio, smoke_mcp_stdio
from cbn_protocol.mcp_stdio import smoke_mcp_workflow_stdio
from cbn_protocol.smoke_suite import protocol_smoke_suite
from cbn_runtime.context import build_runtime
from cbn_workflow.catalog import inspect_workflow, list_workflows
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


def _known_parser_refs() -> set[str]:
    return {item["parser_ref"] for item in ParserRegistry.builtins().list()}


def _operation_exit_code(result: dict) -> int:
    status = result.get("status")
    if status == "completed":
        return 0
    if status == "blocked":
        return 14
    return 15
