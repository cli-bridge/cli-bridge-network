import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cbn_parsers.registry import ParserRegistry
from cbn_core.manifest import CapabilityManifest, ManifestRegistry
from cbn_runtime.context import build_runtime
from cbn_protocol.acceptance import cli_to_cli_acceptance_report
from cbn_protocol.bridge_contract import workflow_bridge_contract_report
from cbn_protocol.envelope import (
    BridgeMessage,
    bridge_args_from_selectors,
    select_bridge_value,
    validate_bridge_message,
)


class ParserProtocolTests(unittest.TestCase):
    def test_git_status_parser_returns_entries(self):
        parsed = ParserRegistry.builtins().parse(
            "git.status.short",
            " M README.md\n?? tmp.txt\n",
            "",
        )
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["data"]["entries"][0]["worktree"], "M")
        self.assertEqual(parsed["data"]["entries"][1]["path"], "tmp.txt")

    def test_json_parser_returns_json_payload(self):
        parsed = ParserRegistry.builtins().parse("json.stdout", '{"ok": true}', "")
        self.assertEqual(parsed["data"]["json"], {"ok": True})

    def test_git_version_parser_returns_version(self):
        parsed = ParserRegistry.builtins().parse("git.version", "git version 2.49.0.windows.1\n", "")
        self.assertEqual(parsed["data"]["version"], "2.49.0.windows.1")
        self.assertEqual(parsed["data"]["raw"], "git version 2.49.0.windows.1")

    def test_cli_anything_mermaid_set_diagram_parser_returns_verified_shape(self):
        parsed = ParserRegistry.builtins().parse(
            "cli-anything.mermaid.set_diagram",
            '{"action":"set_diagram","line_count":2}',
            "",
        )
        self.assertEqual(parsed["data"], {"action": "set_diagram", "line_count": 2})

    def test_cli_anything_macrocli_backends_parser_returns_verified_shape(self):
        parsed = ParserRegistry.builtins().parse(
            "cli-anything.macrocli.backends",
            '{"native_api":{"name":"native_api","priority":100,"available":true},'
            '"semantic_ui":{"name":"semantic_ui","priority":50,"available":false}}',
            "",
        )
        self.assertEqual(parsed["data"]["backend_count"], 2)
        self.assertEqual(parsed["data"]["available_count"], 1)
        self.assertEqual(parsed["data"]["backends"][0]["id"], "native_api")

    def test_cli_anything_raw_parser_rejects_fatal_stderr(self):
        with self.assertRaisesRegex(ValueError, "NoConsoleScreenBufferError"):
            ParserRegistry.builtins().parse(
                "cli-anything.raw",
                "cli-anything-mermaid v1.0.0\n",
                "Traceback (most recent call last):\n"
                "prompt_toolkit.output.win32.NoConsoleScreenBufferError: No Windows console found.\n",
            )

    def test_cli_anything_raw_parser_fixtures_verify_launch_contract(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "parser",
                "fixtures",
                "--parser-ref",
                "cli-anything.raw",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["parser_ref"], "cli-anything.raw")
        self.assertEqual(payload["fixture_count"], 1)
        self.assertEqual(payload["failed_case_count"], 0)
        self.assertIn(
            "cli-anything.mermaid.launch",
            payload["reports"][0]["verified_capabilities"],
        )

    def test_bridge_message_envelope_shape(self):
        message = BridgeMessage(
            producer="git.status",
            channel="capability.output",
            correlation_id="call-1",
            payload={"parser_ref": "git.status.short", "ok": True, "data": {}},
        ).as_dict()
        self.assertEqual(message["apiVersion"], "bridge.dev/v1alpha1")
        self.assertEqual(message["kind"], "BridgeMessage")
        self.assertEqual(message["metadata"]["producer"], "git.status")
        self.assertEqual(message["metadata"]["correlationId"], "call-1")

    def test_bridge_message_validation_and_selectors(self):
        message = BridgeMessage(
            producer="git.status",
            channel="capability.output",
            correlation_id="call-1",
            payload={"parser_ref": "raw.text", "ok": True, "data": {"stdout": "git status --short"}},
            artifacts=({"artifact_id": "artifact-1", "kind": "stdout"},),
        ).as_dict()
        validation = validate_bridge_message(message)
        self.assertTrue(validation["valid"])
        self.assertEqual(validation["payload_parser_ref"], "raw.text")
        self.assertTrue(validation["payload_ok"])
        self.assertEqual(validation["artifact_count"], 1)
        self.assertEqual(select_bridge_value(message, "payload.data.stdout")["value"], "git status --short")
        self.assertEqual(select_bridge_value(message, "artifacts[0].artifact_id")["value"], "artifact-1")

    def test_bridge_message_args_from_selectors(self):
        message = BridgeMessage(
            producer="json.tool",
            channel="capability.output",
            correlation_id="call-1",
            payload={
                "parser_ref": "json.stdout",
                "ok": True,
                "data": {
                    "name": "gimp",
                    "enabled": True,
                    "options": {"mode": "batch", "scale": 2},
                    "empty": None,
                },
            },
        ).as_dict()
        routed = bridge_args_from_selectors(
            message,
            [
                "payload.data.name",
                "payload.data.enabled",
                "payload.data.options",
                "payload.data.empty",
            ],
        )
        self.assertTrue(routed["valid"])
        self.assertEqual(
            routed["args"],
            ["gimp", "True", '{"mode": "batch", "scale": 2}', ""],
        )
        self.assertEqual(routed["mappings"][2]["selector"], "payload.data.options")

    def test_bridge_contract_report_summarizes_workflow_routes(self):
        registry = ManifestRegistry()
        registry.load_dir(Path("manifests"))
        report = workflow_bridge_contract_report(
            registry,
            workflow_path="workflows/cli-anything-macrocli-mermaid-routing.example.json",
        )
        self.assertTrue(report["ok"])
        self.assertEqual(report["apiVersion"], "bridge.dev/v1alpha1")
        self.assertEqual(report["summary"]["workflow_count"], 1)
        self.assertEqual(report["summary"]["route_count"], 2)
        self.assertEqual(report["summary"]["payload_route_count"], 2)
        workflow = report["workflows"][0]
        self.assertEqual(workflow["workflow_id"], "example.cli-anything-macrocli-mermaid-routing")
        self.assertEqual(workflow["routes"][0]["route_kind"], "payload")
        self.assertEqual(workflow["routes"][0]["source_parser_ref"], "cli-anything.macrocli.backends")
        self.assertTrue(workflow["routes"][0]["selector_valid"])
        self.assertTrue(workflow["routes"][0]["ready"])
        self.assertEqual(workflow["routes"][0]["blockers"], [])
        self.assertTrue(workflow["routes"][0]["argv_mapping"]["ready"])
        self.assertEqual(report["summary"]["route_ready_count"], 2)
        self.assertEqual(report["summary"]["blocked_route_count"], 0)
        self.assertEqual(report["summary"]["argv_mapping_ready_count"], 2)

    def test_cli_to_cli_acceptance_static_and_runtime_evidence(self):
        runtime = build_runtime()
        report = cli_to_cli_acceptance_report(
            runtime.registry,
            runtime.workflow_runner,
            "workflows/message-routing.example.json",
            run=True,
            dry_run=True,
        )
        self.assertTrue(report["ok"])
        self.assertEqual(report["kind"], "CliToCliWorkflowAcceptance")
        self.assertTrue(report["gates"]["workflow_contract_ready"])
        self.assertTrue(report["gates"]["runtime_execution_completed"])
        self.assertEqual(report["summary"]["runtime_route_count"], 1)
        self.assertEqual(report["summary"]["runtime_route_failed_count"], 0)
        self.assertEqual(report["runtime_routes"][0]["selector"], "payload.data.stdout")
        self.assertTrue(report["runtime_routes"][0]["matched"])

    def test_bridge_contract_blocks_unverified_payload_source(self):
        registry = ManifestRegistry()
        registry.register(
            CapabilityManifest.from_dict(
                _manifest("sample.source", parser_ref="raw.text", verified=False)
            )
        )
        registry.register(
            CapabilityManifest.from_dict(
                _manifest("sample.consumer", parser_ref="raw.text", verified=True)
            )
        )
        workflow = {
            "apiVersion": "bridge.dev/v1alpha1",
            "kind": "Workflow",
            "metadata": {"id": "sample.unverified-route"},
            "spec": {
                "tasks": [
                    {"id": "source", "uses": "sample.source"},
                    {
                        "id": "consumer",
                        "uses": "sample.consumer",
                        "needs": ["source"],
                        "argsFrom": [{"task": "source", "selector": "payload.data.stdout"}],
                    },
                ]
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "workflow.json"
            path.write_text(json.dumps(workflow, ensure_ascii=False), encoding="utf-8")
            report = workflow_bridge_contract_report(registry, workflow_path=str(path))

        self.assertFalse(report["ok"])
        self.assertEqual(report["summary"]["blocked_route_count"], 1)
        route = report["workflows"][0]["routes"][0]
        self.assertFalse(route["ready"])
        self.assertIn("payload route source output is not verified", route["blockers"])
        self.assertTrue(route["argv_mapping"]["ready"])

    def test_invalid_bridge_message_reports_errors(self):
        result = validate_bridge_message({"kind": "BridgeMessage", "payload": []})
        self.assertFalse(result["valid"])
        self.assertIn("metadata must be an object", result["errors"])
        self.assertIn("payload must be an object", result["errors"])

    def test_invalid_bridge_message_reports_payload_and_artifact_errors(self):
        result = validate_bridge_message(
            {
                "apiVersion": "bridge.dev/v1alpha1",
                "kind": "BridgeMessage",
                "metadata": {
                    "id": "message-1",
                    "createdAt": "2026-06-09T12:00:00+0800",
                    "producer": "git.version",
                    "channel": "capability.output",
                    "correlationId": "call-1",
                },
                "payload": {"parser_ref": "", "data": []},
                "artifacts": [{"artifact_id": "artifact-1"}, "bad-artifact"],
            }
        )
        self.assertFalse(result["valid"])
        self.assertIn("payload.parser_ref is required", result["errors"])
        self.assertIn("payload.ok must be a boolean", result["errors"])
        self.assertIn("payload.data must be an object when present", result["errors"])
        self.assertIn("artifacts[0].kind is required", result["errors"])
        self.assertIn("artifacts[1] must be an object", result["errors"])

    def test_cli_parser_list_and_call_message(self):
        parsers = subprocess.run(
            [sys.executable, "-m", "cbn", "parser", "list"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        parser_refs = {item["parser_ref"] for item in json.loads(parsers.stdout)}
        self.assertIn("git.status.short", parser_refs)
        self.assertIn("git.version", parser_refs)
        self.assertIn("direct-cli.typed", parser_refs)
        self.assertIn("cli-anything.mermaid.set_diagram", parser_refs)
        self.assertIn("cli-anything.macrocli.backends", parser_refs)

        call = subprocess.run(
            [sys.executable, "-m", "cbn", "call", "git.version", "--dry-run"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(call.stdout)
        self.assertEqual(payload["parsed"]["parser_ref"], "raw.text")
        self.assertEqual(payload["message"]["kind"], "BridgeMessage")
        self.assertEqual(payload["message"]["metadata"]["producer"], "git.version")

    def test_git_version_call_uses_verified_parser(self):
        call = subprocess.run(
            [sys.executable, "-m", "cbn", "call", "git.version"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(call.stdout)
        self.assertEqual(payload["parsed"]["parser_ref"], "git.version")
        self.assertTrue(payload["parsed"]["ok"])
        self.assertIn("version", payload["parsed"]["data"])

    def test_cli_message_validate_and_select(self):
        message = BridgeMessage(
            producer="git.version",
            channel="capability.output",
            correlation_id="call-1",
            payload={"parser_ref": "raw.text", "ok": True, "data": {"stdout": "git --version"}},
        ).as_dict()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "message.json"
            path.write_text(json.dumps(message, ensure_ascii=False), encoding="utf-8")
            validated = subprocess.run(
                [sys.executable, "-m", "cbn", "message", "validate", str(path)],
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            self.assertTrue(json.loads(validated.stdout)["valid"])

            selected = subprocess.run(
                [sys.executable, "-m", "cbn", "message", "select", str(path), "payload.data.stdout"],
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            self.assertEqual(json.loads(selected.stdout)["value"], "git --version")

            args = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "cbn",
                    "message",
                    "args",
                    str(path),
                    "payload.data.stdout",
                    "metadata.producer",
                ],
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            payload = json.loads(args.stdout)
            self.assertEqual(payload["args"], ["git --version", "git.version"])
            self.assertEqual(payload["mappings"][0]["selector"], "payload.data.stdout")

    def test_cli_message_contract_outputs_workflow_report(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "message",
                "contract",
                "--workflow-path",
                "workflows/artifact-id-routing.example.json",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["summary"]["artifact_route_count"], 1)
        self.assertEqual(payload["workflows"][0]["routes"][0]["selector"], "artifacts[0].artifact_id")

    def test_cli_protocol_accept_workflow_outputs_acceptance_report(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "protocol",
                "accept-workflow",
                "workflows/message-routing.example.json",
                "--run",
                "--dry-run",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["kind"], "CliToCliWorkflowAcceptance")
        self.assertEqual(payload["summary"]["runtime_route_ready_count"], 1)
        self.assertTrue(payload["runtime_routes"][0]["matched"])

    def test_dry_run_uses_raw_parser_even_for_structured_capability(self):
        call = subprocess.run(
            [sys.executable, "-m", "cbn", "call", "git.status", "--dry-run"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(call.stdout)
        self.assertEqual(payload["reason"], "dry-run")
        self.assertEqual(payload["parsed"]["parser_ref"], "raw.text")
        self.assertTrue(payload["parsed"]["dry_run"])
        self.assertIn("git status --short", payload["parsed"]["data"]["stdout"])


def _manifest(capability_id: str, parser_ref: str, verified: bool) -> dict[str, object]:
    return {
        "apiVersion": "bridge.dev/v1alpha1",
        "kind": "ToolManifest",
        "metadata": {"id": capability_id, "title": capability_id},
        "spec": {
            "transport": {
                "kind": "stdio",
                "command": "python",
                "argsTemplate": ["-c", "print('ok')"],
            },
            "policy": {
                "risk": "read",
                "requiresConfirmation": False,
                "network": "deny",
            },
            "output": {
                "parserRef": parser_ref,
                "verified": verified,
            },
        },
    }


if __name__ == "__main__":
    unittest.main()
