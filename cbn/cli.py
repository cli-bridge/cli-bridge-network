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
from cbn_parsers.registry import ParserRegistry
from cbn_plugins.cli_anything import CliAnythingHub
from cbn_plugins.manager import PluginManager
from cbn_protocol.a2a_http import agent_card, smoke_a2a_http
from cbn_protocol.envelope import bridge_args_from_selectors, select_bridge_value, validate_bridge_message
from cbn_protocol.compatibility import check_protocol
from cbn_protocol.exports import export_all_protocols, export_protocol, list_protocol_exports
from cbn_protocol.mcp_stdio import serve_stdio, smoke_mcp_stdio
from cbn_runtime.context import build_runtime
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
        return 0 if result.get("allowed") else 3

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
        if args.protocol_command == "check":
            payload = check_protocol(runtime.registry, args.target, capability_id=args.capability_id)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0

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

    if args.command == "a2a":
        if args.a2a_command == "agent-card":
            print(json.dumps(agent_card(args.base_url), ensure_ascii=False, indent=2))
            return 0
        if args.a2a_command == "smoke":
            payload = smoke_a2a_http(args.capability_id, extra_args=args.extra_arg)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload["ok"] else 9

    if args.command == "message":
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
            runtime = build_runtime()
            print(json.dumps(runtime.plugin_runner.execute(plan), ensure_ascii=False, indent=2))
            return 0
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
            runtime = build_runtime()
            print(json.dumps(runtime.plugin_runner.execute(plan), ensure_ascii=False, indent=2))
            return 0
        if args.plugin_command == "update":
            plan = manager.plan(
                args.plugin_id,
                action="update",
                include_codex_skill=args.with_codex_skill,
            )
            if not args.yes:
                print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2))
                return 2
            runtime = build_runtime()
            print(json.dumps(runtime.plugin_runner.execute(plan), ensure_ascii=False, indent=2))
            return 0

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
