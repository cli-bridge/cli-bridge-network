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
from cbn_demo.network_connect import network_acceptance_report, network_connect_package, workflow_studio_demo_link
from cbn_core.agent_cli_importer import agent_cli_card_import_report
from cbn_core.command_importer import command_import_report, parse_key_values
from cbn_core.import_catalog import cli_registration_surface
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
from cbn_core.bridge_contract import workflow_bridge_contract_report
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

    return _dispatch_command(args, parser)


def _dispatch_command(args, parser) -> int:
    handlers = {
        "health": lambda: _handle_health_command(),
        "paths": lambda: _handle_paths_command(),
        "nodes": lambda: _handle_nodes_command(),
        "registry": lambda: _handle_registry_command(args, parser),
        "call": lambda: _handle_call_command(args),
        "audit": lambda: _handle_audit_command(args, parser),
        "event": lambda: _handle_event_command(args, parser),
        "artifact": lambda: _handle_artifact_command(args, parser),
        "parser": lambda: _handle_parser_command(args, parser),
        "record-parser-fixture": lambda: _handle_record_parser_fixture_command(args),
        "protocol": lambda: _handle_protocol_command(args, parser),
        "demo": lambda: _handle_demo_command(args, parser),
        "import": lambda: _handle_import_command(args, parser),
        "mcp": lambda: _handle_mcp_command(args, parser),
        "a2a": lambda: _handle_a2a_command(args, parser),
        "acp": lambda: _handle_acp_command(args, parser),
        "message": lambda: _handle_message_command(args, parser),
        "approvals": lambda: _handle_approvals_command(args, parser),
        "workflow": lambda: _handle_workflow_command(args, parser),
        "network": lambda: _handle_network_command(args, parser),
        "runtime": lambda: _handle_runtime_command(args, parser),
        "daemon": lambda: _handle_daemon_command(args, parser),
        "plugin": lambda: _handle_plugin_command(args, parser),
    }
    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        return 0
    return handler()


def _handle_health_command() -> int:
    _print_json(health_payload())
    return 0


def _handle_paths_command() -> int:
    _print_json(resolve_project_paths().as_dict())
    return 0


def _handle_nodes_command() -> int:
    init_builtin_nodes()
    _print_json(
        {
            key: {
                "title": value.title,
                "category": value.category,
                "risk": value.risk,
            }
            for key, value in sorted(CAPABILITY_NODE_MAPPINGS.items())
        }
    )
    return 0


def _handle_registry_command(args, parser) -> int:
    if args.registry_command == "validate":
        result = validate_manifest_path(Path(args.path), known_parser_refs=_known_parser_refs())
        _print_json(result)
        return 0 if result["valid"] else 7
    if args.registry_command is None:
        parser.print_help()
        return 0

    runtime = build_runtime()
    if args.registry_command == "list":
        _print_json([manifest.as_record() for manifest in runtime.registry.list()])
        return 0
    if args.registry_command == "search":
        _print_json(runtime.registry.search(args.query, limit=args.limit))
        return 0
    if args.registry_command == "inspect":
        _print_json(runtime.registry.require(args.capability_id).as_record())
        return 0
    parser.print_help()
    return 0


def _handle_call_command(args) -> int:
    result = build_runtime().executor.call(
        args.capability_id,
        extra_args=tuple(args.extra_args),
        dry_run=args.dry_run,
        confirmed=args.yes,
        approval_id=args.approval_id,
    )
    _print_json(result)
    return 0 if result.get("ok") else 3


def _handle_audit_command(args, parser) -> int:
    if args.audit_command == "tail":
        _print_json(build_runtime().audit_log.tail(limit=args.limit))
        return 0
    parser.print_help()
    return 0


def _handle_event_command(args, parser) -> int:
    if args.event_command == "tail":
        _print_json(build_runtime().event_bus.tail(limit=args.limit))
        return 0
    parser.print_help()
    return 0


def _handle_artifact_command(args, parser) -> int:
    runtime = build_runtime()
    if args.artifact_command == "list":
        _print_json(runtime.artifact_store.list(limit=args.limit))
        return 0
    if args.artifact_command == "inspect":
        _print_json(runtime.artifact_store.inspect(args.artifact_id))
        return 0
    parser.print_help()
    return 0


def _handle_parser_command(args, parser) -> int:
    runtime = build_runtime()
    if args.parser_command == "list":
        _print_json(runtime.parser_registry.list())
        return 0
    if args.parser_command == "inspect":
        _print_json(runtime.parser_registry.inspect(args.parser_ref))
        return 0
    if args.parser_command == "fixtures":
        result = run_parser_fixtures(
            Path(args.path),
            parser_ref=args.parser_ref,
            registry=runtime.parser_registry,
        )
        _print_json(result)
        return 0 if result["ok"] else 7
    parser.print_help()
    return 0


def _handle_record_parser_fixture_command(args) -> int:
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
    _print_json(result)
    return 0 if result["ok"] else 12


def _handle_demo_command(args, parser) -> int:
    if args.demo_command != "killer":
        parser.print_help()
        return 0
    runtime = build_runtime()
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
    _print_json(payload)
    return 0 if payload["ok"] else 10


def _handle_runtime_command(args, parser) -> int:
    if args.runtime_command != "transport":
        parser.print_help()
        return 0
    manager = PluginManager()
    if args.install:
        return _install_runtime_transport(args, manager)
    if args.plan:
        _print_json(manager.runtime_transport_plan(args.kind).as_dict())
        return 0
    result = manager.runtime_transport_status(args.kind)
    _print_json(result)
    return 0 if result["ready"] else 5


def _install_runtime_transport(args, manager: PluginManager) -> int:
    gate = manager.runtime_transport_gate(args.kind)
    if not gate["ok"]:
        _print_json(gate)
        return 13
    plan = manager.runtime_transport_plan(args.kind)
    if not args.yes:
        _print_json(plan.as_dict())
        return 2
    result = build_runtime().plugin_runner.execute(plan)
    _print_json(result)
    return _operation_exit_code(result)


def _handle_daemon_command(args, parser) -> int:
    if args.daemon_command == "routes":
        _print_json(ROUTE_SUMMARY)
        return 0
    if args.daemon_command == "serve":
        if args.session_token and args.require_session_token is False:
            parser.error("daemon serve cannot combine --session-token with --no-session-token")
        serve(
            host=args.host,
            port=args.port,
            session_token=args.session_token,
            require_session_token=args.require_session_token,
        )
        return 0
    parser.print_help()
    return 0


def _handle_plugin_command(args, parser) -> int:
    if args.plugin_command is None:
        parser.print_help()
        return 0
    manager = PluginManager()
    if args.plugin_command in _PLUGIN_MANAGER_READ_COMMANDS:
        return _handle_plugin_manager_read(args, manager)
    if args.plugin_command in _PLUGIN_MANAGER_REPORT_COMMANDS:
        return _handle_plugin_manager_report(args, manager)
    if args.plugin_command in {"plan", "install", "update"}:
        return _handle_plugin_lifecycle_command(args, manager)
    if args.plugin_command in _CLI_ANYTHING_PLUGIN_COMMANDS:
        return _handle_cli_anything_plugin_command(args, parser)
    parser.print_help()
    return 0


_PLUGIN_MANAGER_READ_COMMANDS = {"list", "info", "operations", "provenance"}
_PLUGIN_MANAGER_REPORT_COMMANDS = {
    "validate-operations",
    "operation-plan",
    "verify-plan",
    "preflight",
    "check-update",
    "gate",
}
_CLI_ANYTHING_PLUGIN_COMMANDS = {
    "status",
    "market",
    "import-harness",
    "adapt-harness",
    "prepare-harness",
    "evaluate-harness",
    "probe-harness",
    "verify-harness",
    "verify-harness-plan",
    "onboard-harness",
    "live-verification",
    "mvp-plan",
    "bootstrap-plan",
    "candidates",
    "install-queue",
    "blocked-plan",
    "repair-plan",
    "repair-entrypoint",
    "promotion-gate",
    "adapter-targets",
    "adapter-smoke",
    "adaptation-gate",
    "adaptation-queue",
    "sync-market",
    "harness",
}


def _handle_plugin_manager_read(args, manager: PluginManager) -> int:
    if args.plugin_command == "list":
        _print_json(manager.list_plugins())
    elif args.plugin_command == "info":
        _print_json(manager.plugin_info(args.plugin_id))
    elif args.plugin_command == "operations":
        _print_json(manager.operation_catalog(args.plugin_id))
    else:
        _print_json(manager.provenance(args.plugin_id))
    return 0


def _handle_plugin_manager_report(args, manager: PluginManager) -> int:
    result = _plugin_manager_report(args, manager)
    _print_json(result)
    if args.plugin_command == "preflight":
        return 0 if result["ready"] else 5
    if args.plugin_command == "check-update":
        return 0 if result["ready_for_update"] else 13
    return 0 if result["ok"] else 13


def _plugin_manager_report(args, manager: PluginManager) -> dict:
    if args.plugin_command == "validate-operations":
        return manager.validate_operation_catalog(args.plugin_id)
    if args.plugin_command == "operation-plan":
        return manager.operation_plan(
            args.plugin_id,
            args.operation_id,
            inputs=_parse_operation_inputs(args.input),
            confirmed=args.yes,
        )
    if args.plugin_command == "verify-plan":
        return manager.verify_plan(
            args.plugin_id,
            action=args.action,
            include_codex_skill=args.with_codex_skill,
            run=args.run,
            timeout_seconds=args.timeout_seconds,
        )
    if args.plugin_command == "preflight":
        return manager.preflight(args.plugin_id)
    if args.plugin_command == "check-update":
        return manager.update_check(args.plugin_id, remote=args.remote)
    return manager.operation_gate(args.plugin_id, args.action)


def _handle_plugin_lifecycle_command(args, manager: PluginManager) -> int:
    action = args.action if args.plugin_command == "plan" else args.plugin_command
    plan = manager.plan(args.plugin_id, action=action, include_codex_skill=args.with_codex_skill)
    if args.plugin_command == "plan":
        _print_json(plan.as_dict())
        return 0
    if not args.yes:
        _print_json(plan.as_dict())
        return 2
    if not args.allow_failed_preflight:
        gate = manager.operation_gate(args.plugin_id, action)
        if not gate["ok"]:
            _print_json(gate)
            return 13
    result = build_runtime().plugin_runner.execute(plan)
    _print_json(result)
    return _operation_exit_code(result)


def _handle_cli_anything_plugin_command(args, parser) -> int:
    _require_cli_anything(args.plugin_id, args.plugin_command)
    if args.plugin_command == "status":
        _print_json(CliAnythingHub().status())
        return 0
    if args.plugin_command == "market":
        return _handle_cli_anything_market(args, parser)
    if args.plugin_command == "import-harness":
        return _handle_cli_anything_import_harness(args)
    if args.plugin_command == "harness":
        return _handle_cli_anything_harness_operation(args)
    result = _cli_anything_report(args)
    _print_json(result)
    return 0 if result["ok"] else 6


def _require_cli_anything(plugin_id: str, command: str) -> None:
    if plugin_id != "cli-anything":
        raise KeyError(f"{command} is not implemented for plugin: {plugin_id}")


def _handle_cli_anything_market(args, parser) -> int:
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
    _print_json(result.as_dict())
    return 0 if result.exit_code == 0 else result.exit_code


def _handle_cli_anything_import_harness(args) -> int:
    hub = CliAnythingHub()
    market_record = hub.market_record_for_harness(args.harness_name) if args.from_market else None
    if args.from_market and market_record is None:
        _print_json(
            {
                "error": "CLI-Anything market record not found",
                "plugin_id": args.plugin_id,
                "harness_name": args.harness_name,
            }
        )
        return 6
    if args.write:
        path = hub.write_harness_manifest(args.harness_name, title=args.title, market_record=market_record)
        _print_json({"written": str(path)})
        return 0
    _print_json(hub.manifest_for_harness(args.harness_name, title=args.title, market_record=market_record))
    return 0


def _handle_cli_anything_harness_operation(args) -> int:
    hub = CliAnythingHub()
    if args.harness_action == "status":
        _print_json(hub.harness_status(args.harness_name, from_market=args.from_market))
        return 0
    plan = hub.harness_plan(args.harness_action, args.harness_name, extra_args=tuple(args.extra_args))
    if not args.yes:
        _print_json(plan.as_dict())
        return 2
    if args.harness_action in {"install", "update"} and not args.allow_blocked:
        gate = hub.harness_operation_gate(args.harness_action, args.harness_name, from_market=not args.offline)
        if not gate["ok"]:
            _print_json(gate)
            return 12
    result = build_runtime().plugin_runner.execute(plan)
    _print_json(result)
    return _operation_exit_code(result)


def _cli_anything_report(args) -> dict:
    hub = CliAnythingHub()
    if args.plugin_command in {"adapt-harness", "prepare-harness", "evaluate-harness", "probe-harness"}:
        return _cli_anything_basic_harness_report(args, hub)
    if args.plugin_command in {"verify-harness", "verify-harness-plan", "onboard-harness", "live-verification"}:
        return _cli_anything_verification_report(args, hub)
    if args.plugin_command in {
        "mvp-plan",
        "bootstrap-plan",
        "candidates",
        "install-queue",
        "blocked-plan",
        "repair-plan",
        "promotion-gate",
    }:
        return _cli_anything_planning_report(args, hub)
    return _cli_anything_adapter_report(args, hub)


def _cli_anything_basic_harness_report(args, hub: CliAnythingHub) -> dict:
    common = {
        "adapt-harness": hub.adapt_harness,
        "prepare-harness": hub.prepare_harness,
        "evaluate-harness": hub.evaluate_harness,
        "probe-harness": hub.probe_harness,
    }
    kwargs = {
        "title": args.title,
        "from_market": args.from_market,
    }
    if args.plugin_command == "adapt-harness":
        kwargs["write"] = args.write
    return common[args.plugin_command](args.harness_name, **kwargs)


def _cli_anything_verification_report(args, hub: CliAnythingHub) -> dict:
    handlers = {
        "verify-harness": _cli_anything_verify_harness_report,
        "verify-harness-plan": _cli_anything_verify_harness_plan_report,
        "onboard-harness": _cli_anything_onboard_harness_report,
        "live-verification": _cli_anything_live_verification_report,
    }
    return handlers[args.plugin_command](args, hub)


def _cli_anything_verify_harness_report(args, hub: CliAnythingHub) -> dict:
    return hub.verify_harness(
        args.harness_name,
        title=args.title,
        from_market=args.from_market,
        include_workflows=args.include_workflows,
        run_smoke_suite=args.smoke_suite,
        smoke_extra_args=tuple(args.smoke_extra_arg),
    )


def _cli_anything_verify_harness_plan_report(args, hub: CliAnythingHub) -> dict:
    return hub.verify_harness_plan(
        args.harness_action,
        args.harness_name,
        extra_args=tuple(args.extra_args),
        run=args.run,
        timeout_seconds=args.timeout_seconds,
    )


def _cli_anything_onboard_harness_report(args, hub: CliAnythingHub) -> dict:
    runtime = build_runtime() if args.install and args.yes else None
    return hub.onboard_harness(
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


def _cli_anything_live_verification_report(args, hub: CliAnythingHub) -> dict:
    return hub.live_verification(
        harnesses=tuple(args.harness) if args.harness else ("mermaid", "macrocli"),
        candidate_query=args.candidate_query,
        candidate_limit=args.candidate_limit,
        include_candidates=args.include_candidates,
        include_workflows=args.include_workflows,
        run_smoke_suite=args.smoke_suite,
        smoke_extra_args=tuple(args.smoke_extra_arg),
    )


def _cli_anything_planning_report(args, hub: CliAnythingHub) -> dict:
    handlers = {
        "mvp-plan": _cli_anything_mvp_plan_report,
        "bootstrap-plan": _cli_anything_bootstrap_plan_report,
        "candidates": _cli_anything_candidates_report,
        "install-queue": _cli_anything_install_queue_report,
        "blocked-plan": _cli_anything_blocked_plan_report,
        "repair-plan": _cli_anything_repair_plan_report,
        "promotion-gate": _cli_anything_promotion_gate_report,
    }
    return handlers[args.plugin_command](args, hub)


def _cli_anything_mvp_plan_report(args, hub: CliAnythingHub) -> dict:
    runtime = build_runtime()
    return hub.mvp_plan(
        query=args.query,
        limit=args.limit,
        max_harnesses=args.max_harnesses,
        include_blocked=args.include_blocked,
        workflow_paths=tuple(args.workflow_path),
        max_workflows=args.max_workflows,
        registry=runtime.registry,
        workflow_runner=runtime.workflow_runner,
    )


def _cli_anything_bootstrap_plan_report(args, hub: CliAnythingHub) -> dict:
    return hub.bootstrap_plan(
        harness_name=args.harness,
        query=args.query,
        include_workflows=args.include_workflows,
        workflow_path=args.workflow_path,
    )


def _cli_anything_candidates_report(args, hub: CliAnythingHub) -> dict:
    return hub.candidate_harnesses(
        query=args.query,
        limit=args.limit,
        with_probes=args.with_probes,
        compact=args.compact,
    )


def _cli_anything_install_queue_report(args, hub: CliAnythingHub) -> dict:
    return hub.market_install_queue(
        query=args.query,
        limit=args.limit,
        max_installs=args.max_installs,
        include_blocked=args.include_blocked,
    )


def _cli_anything_blocked_plan_report(args, hub: CliAnythingHub) -> dict:
    return hub.blocked_harness_plan(harnesses=tuple(args.harness), query=args.query, limit=args.limit)


def _cli_anything_repair_plan_report(args, hub: CliAnythingHub) -> dict:
    return hub.entrypoint_repair_plan(args.harness_name, from_market=args.from_market)


def _cli_anything_promotion_gate_report(args, hub: CliAnythingHub) -> dict:
    return hub.promotion_gate(
        args.harness_name,
        title=args.title,
        from_market=args.from_market,
        include_workflows=args.include_workflows,
        run_smoke_suite=args.smoke_suite,
        smoke_extra_args=tuple(args.smoke_extra_arg),
    )


def _cli_anything_adapter_report(args, hub: CliAnythingHub) -> dict:
    if args.plugin_command == "repair-entrypoint":
        return _cli_anything_repair_entrypoint_report(args, hub)
    if args.plugin_command == "adapter-targets":
        return hub.adapter_targets(
            args.harness_name,
            from_market=args.from_market,
            package=args.package,
            limit=args.limit,
        )
    if args.plugin_command == "adapter-smoke":
        return _cli_anything_adapter_smoke_report(args, hub)
    if args.plugin_command == "adaptation-gate":
        return _cli_anything_adaptation_gate_report(args, hub)
    if args.plugin_command == "adaptation-queue":
        return _cli_anything_adaptation_queue_report(args, hub)
    return hub.sync_market(query=args.query, limit=args.limit, write=args.write)


def _confirmation_required(message: str) -> dict:
    return {"ok": False, "error_type": "confirmation_required", "error": message}


def _cli_anything_repair_entrypoint_report(args, hub: CliAnythingHub) -> dict:
    if args.write and not args.yes:
        return _confirmation_required("entrypoint repair writes require --yes")
    return hub.repair_entrypoint(
        args.harness_name,
        from_market=args.from_market,
        module=args.module,
        write=args.write,
        confirmed=args.yes,
        require_smoke=args.require_smoke,
        smoke_args=_smoke_args(args),
        smoke_timeout_seconds=args.smoke_timeout,
    )


def _cli_anything_adapter_smoke_report(args, hub: CliAnythingHub) -> dict:
    if args.run and not args.yes:
        return _confirmation_required("adapter smoke execution requires --yes")
    return hub.adapter_target_smoke(
        args.harness_name,
        module=args.module,
        from_market=args.from_market,
        smoke_args=_smoke_args(args),
        timeout_seconds=args.timeout,
        run=args.run,
        confirmed=args.yes,
    )


def _cli_anything_adaptation_gate_report(args, hub: CliAnythingHub) -> dict:
    if args.run_smoke and not args.yes:
        return _confirmation_required("adaptation gate smoke execution requires --yes")
    return hub.adaptation_gate(
        args.harness_name,
        from_market=args.from_market,
        module=args.module,
        require_smoke=args.require_smoke,
        run_smoke=args.run_smoke,
        confirmed=args.yes,
        smoke_args=_smoke_args(args),
        smoke_timeout_seconds=args.smoke_timeout,
    )


def _smoke_args(args) -> tuple[str, ...]:
    return tuple(args.smoke_arg) if args.smoke_arg else ("--help",)


def _cli_anything_adaptation_queue_report(args, hub: CliAnythingHub) -> dict:
    if args.run_smoke and not args.yes:
        return {"ok": False, "error_type": "confirmation_required", "error": "adaptation queue smoke execution requires --yes"}
    if args.run_smoke and not args.harness and args.include_blocked:
        return {
            "ok": False,
            "error_type": "blocked",
            "error": "adaptation queue smoke execution requires explicit --harness entries or --no-blocked",
        }
    return hub.adaptation_queue(
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


def _handle_mcp_command(args, parser) -> int:
    if args.mcp_command == "serve":
        if not args.stdio:
            parser.error("mcp serve currently requires --stdio")
        return serve_stdio()
    if args.mcp_command == "smoke":
        payload = smoke_mcp_stdio(args.capability_id, extra_args=args.extra_arg, dry_run=args.dry_run)
        _print_json(payload)
        return 0 if payload["ok"] else 9
    if args.mcp_command == "smoke-workflow":
        payload = smoke_mcp_workflow_stdio(args.path, dry_run=args.dry_run, confirmed=args.yes)
        _print_json(payload)
        return 0 if payload["ok"] else 9
    parser.print_help()
    return 0


def _handle_a2a_command(args, parser) -> int:
    if args.a2a_command == "agent-card":
        _print_json(agent_card(args.base_url))
        return 0
    if args.a2a_command == "smoke":
        payload = smoke_a2a_http(args.capability_id, extra_args=args.extra_arg)
        _print_json(payload)
        return 0 if payload["ok"] else 9
    if args.a2a_command == "smoke-workflow":
        payload = smoke_a2a_workflow_http(args.path, dry_run=args.dry_run, confirmed=args.yes)
        _print_json(payload)
        return 0 if payload["ok"] else 9
    parser.print_help()
    return 0


def _handle_acp_command(args, parser) -> int:
    if args.acp_command == "serve":
        if not args.stdio:
            parser.error("acp serve currently requires --stdio")
        return serve_acp_stdio()
    if args.acp_command == "smoke":
        payload = smoke_acp_stdio(args.capability_id, extra_args=args.extra_arg, dry_run=args.dry_run)
        _print_json(payload)
        return 0 if payload["ok"] else 9
    if args.acp_command == "smoke-workflow":
        payload = smoke_acp_workflow_stdio(args.path, dry_run=args.dry_run, confirmed=args.yes)
        _print_json(payload)
        return 0 if payload["ok"] else 9
    parser.print_help()
    return 0


def _handle_message_command(args, parser) -> int:
    if args.message_command == "contract":
        runtime = build_runtime()
        result = workflow_bridge_contract_report(runtime.registry, workflow_path=args.workflow_path)
        _print_json(result)
        return 0 if result["ok"] else 7
    if args.message_command is None:
        parser.print_help()
        return 0

    message = _read_json_arg(args.path)
    if args.message_command == "validate":
        result = validate_bridge_message(message)
        _print_json(result)
        return 0 if result["valid"] else 7
    if args.message_command == "select":
        return _print_message_selection(message, args.selector)
    if args.message_command == "args":
        return _print_message_args(message, list(args.selectors))
    parser.print_help()
    return 0


def _print_message_selection(message: dict, selector: str) -> int:
    try:
        _print_json(select_bridge_value(message, selector))
        return 0
    except (KeyError, IndexError, ValueError) as exc:
        _print_json({"error": str(exc), "selector": selector})
        return 8


def _print_message_args(message: dict, selectors: list[str]) -> int:
    try:
        result = bridge_args_from_selectors(message, selectors)
        _print_json(result)
        return 0 if result["valid"] else 7
    except (KeyError, IndexError, ValueError) as exc:
        _print_json({"error": str(exc), "selectors": selectors})
        return 8


def _handle_approvals_command(args, parser) -> int:
    if args.approvals_command is None:
        parser.print_help()
        return 0
    runtime = build_runtime()
    if args.approvals_command == "list":
        _print_json(runtime.approval_store.list(status=args.status, limit=args.limit))
        return 0
    if args.approvals_command == "show":
        _print_json(runtime.approval_store.inspect(args.approval_id))
        return 0
    if args.approvals_command in {"approve", "deny"}:
        approval = _decide_approval(runtime, args)
        _print_json(approval)
        return 0
    parser.print_help()
    return 0


def _decide_approval(runtime, args) -> dict:
    approval = runtime.approval_store.decide(
        args.approval_id,
        "approved" if args.approvals_command == "approve" else "denied",
        actor="cli",
        reason=args.reason,
    )
    runtime.event_bus.publish(
        "approval.decided",
        approval["capability_id"],
        {"approval": approval},
        correlation_id=approval["call_id"],
    )
    return approval


def _handle_workflow_command(args, parser) -> int:
    if args.workflow_command is None:
        parser.print_help()
        return 0
    runtime = build_runtime()
    if args.workflow_command == "list":
        _print_json(list_workflows(registry=runtime.registry))
        return 0
    if args.workflow_command in {"compile", "run-package", "inspect-package", "golden"}:
        return _handle_workflow_package_command(args, runtime)
    if args.workflow_command == "inspect":
        result = inspect_workflow(Path(args.path), registry=runtime.registry)
        _print_json(result)
        return 0 if result["valid"] else 7
    return _handle_workflow_graph_command(args, runtime, parser)


def _handle_workflow_package_command(args, runtime) -> int:
    if args.workflow_command == "compile":
        result = compile_workflow_package(
            Path(args.path),
            Path(args.out) if args.out else None,
            runtime.registry,
        )
        _print_json(result)
        return 0 if result["lock_status"]["ok"] else 7
    if args.workflow_command == "inspect-package":
        result = inspect_workflow_package(Path(args.package_dir), registry=runtime.registry)
        _print_json(result)
        return 0 if result["ok"] else 7

    result = run_workflow_package(
        Path(args.package_dir),
        runtime.registry,
        runtime.workflow_runner,
        dry_run=args.dry_run,
        confirmed=args.yes,
        write_golden=args.workflow_command == "golden" or args.write_golden,
    )
    _print_json(result)
    return 0 if result["ok"] else 4


def _handle_workflow_graph_command(args, runtime, parser) -> int:
    if args.workflow_command not in {"validate", "plan", "run"}:
        parser.print_help()
        return 0
    graph = WorkflowGraph.from_file(Path(args.path))
    if args.workflow_command == "validate":
        graph.validate()
        _print_json({"valid": True, "workflow_id": graph.workflow_id})
        return 0
    if args.workflow_command == "plan":
        _print_json(runtime.workflow_runner.plan(graph))
        return 0

    result = runtime.workflow_runner.run(graph, dry_run=args.dry_run, confirmed=args.yes)
    _print_json(result)
    return 0 if result["status"] == "completed" else 4


def _handle_protocol_command(args, parser) -> int:
    if args.protocol_command is None:
        parser.print_help()
        return 0
    if args.protocol_command == "list":
        _print_json(list_protocol_exports())
        return 0

    runtime = build_runtime()
    payload, failure_code = _protocol_payload(args, runtime)
    if payload is None:
        parser.print_help()
        return 0
    _print_json(payload)
    if failure_code is None:
        return 0
    return 0 if payload["ok"] else failure_code


def _protocol_payload(args, runtime) -> tuple[dict | list | None, int | None]:
    for builder in (
        _protocol_descriptor_payload,
        _protocol_readiness_payload,
        _protocol_suite_payload,
        _protocol_acceptance_payload,
    ):
        payload, failure_code = builder(args, runtime)
        if payload is not None:
            return payload, failure_code
    return None, None


def _protocol_descriptor_payload(args, runtime) -> tuple[dict | list | None, int | None]:
    if args.protocol_command == "export":
        if args.target == "all":
            return export_all_protocols(runtime.registry, capability_id=args.capability_id), None
        return export_protocol(runtime.registry, args.target, capability_id=args.capability_id), None
    if args.protocol_command == "export-workflows":
        if args.target == "all":
            return export_all_workflow_protocols(runtime.registry, workflow_path=args.path), None
        return export_workflow_protocol(runtime.registry, args.target, workflow_path=args.path), None
    if args.protocol_command == "check":
        return (
            check_protocol(
                runtime.registry,
                args.target,
                capability_id=args.capability_id,
                workflow_path=args.workflow_path,
            ),
            None,
        )
    if args.protocol_command == "matrix":
        return protocol_matrix(runtime.registry, include_workflows=args.include_workflows), None
    return None, None


def _protocol_readiness_payload(args, runtime) -> tuple[dict | None, int | None]:
    if args.protocol_command == "readiness":
        return (
            protocol_readiness_report(
                runtime.registry,
                workflow_path=args.workflow_path,
                include_workflows=args.include_workflows,
            ),
            7,
        )
    if args.protocol_command == "conformance-plan":
        return (
            protocol_conformance_plan(
                runtime.registry,
                target=args.target,
                capability_id=args.capability_id,
                workflow_path=args.workflow_path,
            ),
            7,
        )
    return None, None


def _protocol_suite_payload(args, runtime) -> tuple[dict | None, int | None]:
    if args.protocol_command == "lifecycle-suite":
        return protocol_lifecycle_suite(capability_id=args.capability_id, workflow_path=args.workflow_path), 9
    if args.protocol_command == "wire-conformance":
        return protocol_wire_conformance_suite(target=args.target, capability_id=args.capability_id), 9
    if args.protocol_command == "smoke-suite":
        return (
            protocol_smoke_suite(
                runtime.registry,
                capability_ids=tuple(args.capability_id) or None,
                workflow_paths=tuple(args.workflow_path) or None,
                extra_args=tuple(args.extra_arg),
                dry_run=args.dry_run,
                workflow_dry_run=args.workflow_dry_run,
                workflow_confirmed=args.yes,
                include_payloads=args.include_payloads,
            ),
            9,
        )
    return None, None


def _protocol_acceptance_payload(args, runtime) -> tuple[dict | None, int | None]:
    if args.protocol_command == "accept-workflow":
        return _accept_workflow_payload(args, runtime), 10
    if args.protocol_command == "acceptance-queue":
        return _acceptance_queue_payload(args, runtime), 10
    if args.protocol_command == "bridge-lab":
        return _bridge_lab_payload(args, runtime), 10
    return None, None


def _accept_workflow_payload(args, runtime) -> dict:
    return cli_to_cli_acceptance_report(
        runtime.registry,
        runtime.workflow_runner,
        args.workflow_path,
        run=args.run,
        dry_run=args.dry_run,
        confirmed=args.yes,
        include_payloads=args.include_payloads,
    )


def _acceptance_queue_payload(args, runtime) -> dict:
    return cli_to_cli_acceptance_queue(
        runtime.registry,
        runtime.workflow_runner,
        workflow_paths=tuple(args.workflow_path) or None,
        max_workflows=args.max_workflows,
        run=args.run,
        dry_run=args.dry_run,
        confirmed=args.yes,
        include_payloads=args.include_payloads,
    )


def _bridge_lab_payload(args, runtime) -> dict:
    return bridge_lab_report(
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


def _handle_import_command(args, parser) -> int:
    if args.import_command is None:
        parser.print_help()
        return 0
    if args.import_command == "catalog":
        _print_json(cli_registration_surface())
        return 0
    if args.import_command == "cli-anything":
        return _handle_cli_anything_import(args)

    builders = {
        "command": _command_import_payload,
        "agent-cli-card": _agent_cli_card_import_payload,
        "mcp": _mcp_import_payload,
        "skill": _skill_import_payload,
    }
    payload_builder = builders.get(args.import_command)
    if payload_builder is None:
        parser.print_help()
        return 0
    payload = payload_builder(args)
    _print_json(payload)
    return 0 if payload["ok"] else 11


def _command_import_payload(args) -> dict:
    return command_import_report(
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


def _agent_cli_card_import_payload(args) -> dict:
    return agent_cli_card_import_report(
        Path(args.card_file),
        write=args.write,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        known_parser_refs=_known_parser_refs(),
    )


def _mcp_import_payload(args) -> dict:
    return mcp_import_report(
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


def _skill_import_payload(args) -> dict:
    return skill_import_report(
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


def _handle_cli_anything_import(args) -> int:
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
    _print_json(_cli_anything_import_payload(args, payload))
    return 0 if payload["ok"] else 11


def _cli_anything_import_payload(args, payload: dict) -> dict:
    return {
        **payload,
        "entrypoint": "cbn import cli-anything",
        "compatibility": {
            "plugin_command": f"python -m cbn plugin onboard-harness cli-anything {args.harness_name}",
            "facade_for": "CliAnythingHub.onboard_harness",
        },
    }


def _handle_network_command(args, parser) -> int:
    if args.network_command is None:
        parser.print_help()
        return 0
    if args.network_command == "studio-link":
        return _print_network_studio_link(args)

    runtime = build_runtime()
    if args.network_command == "verify":
        return _print_network_verify(args, runtime)

    result = network_connect_package(runtime.registry, **_network_connect_kwargs(args))
    if args.network_command == "connect-package":
        return _print_network_result(result)
    if args.network_command == "quickstart":
        return _print_network_quickstart(result, args.output)
    if args.network_command == "acceptance":
        return _print_network_acceptance(result)
    if args.network_command in _NETWORK_PACKAGE_SLICES:
        return _print_network_package_slice(result, args.network_command)
    parser.print_help()
    return 0


def _print_network_studio_link(args) -> int:
    result = workflow_studio_demo_link(
        workflow_path=args.workflow_path,
        daemon_url=args.daemon_url,
        studio_url=args.studio_url,
        dashboard_url=args.dashboard_url,
        session_token=args.session_token,
        agent_message=args.message,
        dry_run=args.dry_run,
        confirmed=args.confirmed,
    )
    return _print_network_result(result)


def _print_network_verify(args, runtime) -> int:
    result = network_acceptance_report(
        runtime.registry,
        **_network_connect_kwargs(args),
        timeout_seconds=args.timeout_seconds,
    )
    _print_json(result)
    return 0 if result["ok"] else 8


def _print_network_result(result: dict) -> int:
    _print_json(result)
    return 0 if result["ok"] else 7


def _print_network_acceptance(result: dict) -> int:
    acceptance = _network_acceptance(result)
    _print_json(acceptance)
    return 0 if result["ok"] and acceptance.get("kind") == "NetworkConnectionAcceptance" else 7


def _print_network_package_slice(result: dict, command: str) -> int:
    key, expected_kind = _NETWORK_PACKAGE_SLICES[command]
    payload = result.get(key, {})
    _print_json(payload)
    return 0 if result["ok"] and payload.get("kind") == expected_kind else 7


_NETWORK_PACKAGE_SLICES = {
    "entry-profile": ("network_entry_profile", "NetworkEntryProfile"),
    "harness-agent": ("network_harness_agent", "NetworkHarnessAgent"),
    "sdk-bootstrap": ("consumer_sdk_bootstrap", "ConsumerSdkBootstrap"),
    "consumer-manifest": ("consumer_manifest", "NetworkConsumerManifest"),
}


def _network_connect_kwargs(args) -> dict:
    return {
        "workflow_path": args.workflow_path,
        "base_url": args.base_url,
        "studio_url": args.studio_url,
        "dashboard_url": args.dashboard_url,
        "session_token": args.session_token,
        "agent_message": args.message,
    }


def _print_network_quickstart(result: dict, output: str) -> int:
    quickstart = result.get("consumer_quickstart", {})
    output_payloads = {
        "acceptance": quickstart.get("acceptance", {}),
        "readiness": result.get("mvp_readiness", {}),
        "launch-contract": result.get("consumer_launch_contract", {}),
        "entry-profile": result.get("network_entry_profile", {}),
        "harness-agent": result.get("network_harness_agent", {}),
        "sdk-bootstrap": result.get("consumer_sdk_bootstrap", {}),
        "consumer-manifest": result.get("consumer_manifest", {}),
    }
    if output == "curl":
        print(quickstart.get("curl_script", ""))
    elif output == "powershell":
        print(quickstart.get("powershell_script", ""))
    elif output in output_payloads:
        _print_json(output_payloads[output])
    else:
        _print_json(quickstart)
    return 0 if result["ok"] and quickstart.get("kind") == "NetworkConnectQuickstart" else 7


def _network_acceptance(result: dict) -> dict:
    quickstart = result.get("consumer_quickstart", {})
    return quickstart.get("acceptance") if isinstance(quickstart, dict) else {}


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


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
