"""CBN command-line interface."""

from __future__ import annotations

import json

from api_server.routes.health import health_payload
from cbn.cli_args import build_parser
from cbn.paths import resolve_project_paths
from cbn.version import __version__
from cbn_plugins.cli_anything import CliAnythingHub
from cbn_plugins.manager import PluginManager
from cbn_runtime.context import build_runtime
from api_server.server import ROUTE_SUMMARY, serve
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

    if args.command == "registry":
        runtime = build_runtime()
        if args.registry_command == "list":
            payload = [manifest.as_record() for manifest in runtime.registry.list()]
            print(json.dumps(payload, ensure_ascii=False, indent=2))
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
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("allowed") else 3

    if args.command == "audit":
        runtime = build_runtime()
        if args.audit_command == "tail":
            print(json.dumps(runtime.audit_log.tail(limit=args.limit), ensure_ascii=False, indent=2))
            return 0

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
            if args.write:
                path = hub.write_harness_manifest(args.harness_name, title=args.title)
                print(json.dumps({"written": str(path)}, ensure_ascii=False, indent=2))
            else:
                print(
                    json.dumps(
                        hub.manifest_for_harness(args.harness_name, title=args.title),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
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
            print(json.dumps(manager.execute_plan(plan), ensure_ascii=False, indent=2))
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
            print(json.dumps(manager.execute_plan(plan), ensure_ascii=False, indent=2))
            return 0

    parser.print_help()
    return 0
