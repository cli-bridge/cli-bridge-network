import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cbn_core.manifest import ManifestRegistry
from cbn_protocol.compatibility import check_protocol, protocol_matrix
from cbn_protocol.conformance import protocol_conformance_plan
from cbn_protocol.descriptor_roundtrip import workflow_descriptor_roundtrip
from cbn_protocol.exports import (
    export_all_protocols,
    export_all_workflow_protocols,
    export_protocol,
    export_workflow_protocol,
    list_protocol_exports,
)
from cbn_protocol.acceptance_queue import cli_to_cli_acceptance_queue
from cbn_protocol.bridge_lab import bridge_lab_report
from cbn_protocol.lifecycle_suite import protocol_lifecycle_suite
from cbn_protocol.mcp_stdio import McpStdioServer
from cbn_protocol.readiness import protocol_readiness_report
from cbn_protocol.smoke_suite import protocol_smoke_suite
from cbn_runtime.context import build_runtime


class ProtocolExportTests(unittest.TestCase):
    def setUp(self):
        self.registry = ManifestRegistry()
        self.registry.load_dir(Path("manifests"))

    def test_protocol_export_list_is_explicitly_descriptor_only(self):
        exports = list_protocol_exports()
        self.assertEqual({item["protocol"] for item in exports}, {"mcp", "a2a", "acp"})
        self.assertTrue(all(item["wire_compatible"] is False for item in exports))

    def test_mcp_export_maps_capability_to_tool(self):
        payload = export_protocol(self.registry, "mcp", capability_id="git.status")
        self.assertFalse(payload["wire_compatible"])
        self.assertEqual(payload["tools"][0]["name"], "git.status")
        cbn = payload["tools"][0]["_meta"]["cbn"]
        self.assertEqual(cbn["output"]["parser_ref"], "git.status.short")
        self.assertEqual(cbn["output"]["message_kind"], "BridgeMessage")
        self.assertEqual(cbn["policy"]["network"], "deny")
        self.assertEqual(cbn["transport"]["timeout_seconds"], 30)

    def test_a2a_and_acp_exports_include_git_status(self):
        payload = export_all_protocols(self.registry, capability_id="git.status")
        self.assertEqual(payload["exports"]["a2a"]["agentCard"]["skills"][0]["id"], "git.status")
        self.assertEqual(payload["exports"]["acp"]["tools"][0]["id"], "git.status")
        a2a_cbn = payload["exports"]["a2a"]["agentCard"]["skills"][0]["cbn"]
        acp_cbn = payload["exports"]["acp"]["tools"][0]["cbn"]
        self.assertEqual(a2a_cbn["capability_id"], "git.status")
        self.assertEqual(acp_cbn["capability_id"], "git.status")
        self.assertEqual(a2a_cbn["output"], acp_cbn["output"])
        self.assertEqual(a2a_cbn["transport"]["args_template"], ["status", "--short"])

    def test_protocol_exports_preserve_manifest_labels_and_source_path(self):
        payload = export_protocol(self.registry, "mcp", capability_id="ffprobe.inspect")
        cbn = payload["tools"][0]["_meta"]["cbn"]
        self.assertEqual(cbn["labels"], {})
        self.assertEqual(cbn["output"]["parser_ref"], "ffprobe.json")
        self.assertIn("manifests", cbn["source_path"])

    def test_workflow_protocol_exports_preserve_routing_descriptors(self):
        payload = export_workflow_protocol(
            self.registry,
            "mcp",
            workflow_path="workflows/cli-anything-macrocli-mermaid-routing.example.json",
        )
        self.assertFalse(payload["wire_compatible"])
        workflow_tool = payload["workflowTools"][0]
        self.assertEqual(workflow_tool["name"], "workflow:example.cli-anything-macrocli-mermaid-routing")
        schema = workflow_tool["inputSchema"]
        self.assertIn("workflow_id", schema["properties"])
        self.assertIn("workflow_path", schema["properties"])
        self.assertNotIn("workflow_path", schema.get("required", []))
        workflow = workflow_tool["_meta"]["cbn_workflow"]
        self.assertEqual(workflow["task_count"], 3)
        self.assertEqual(workflow["tasks"][0]["capability"]["parser_ref"], "cli-anything.macrocli.backends")
        self.assertEqual(workflow["tasks"][1]["argsFrom"][0]["selector"], "payload.data")
        self.assertEqual(workflow_tool["_meta"]["cbn"]["output"]["task_message_kind"], "BridgeMessage")

    def test_all_workflow_protocol_exports_cover_a2a_and_acp(self):
        payload = export_all_workflow_protocols(
            self.registry,
            workflow_path="workflows/cli-anything-macrocli-mermaid-routing.example.json",
        )
        self.assertEqual(set(payload["exports"]), {"a2a", "acp", "mcp"})
        self.assertEqual(
            payload["exports"]["a2a"]["agentCard"]["skills"][0]["id"],
            "workflow:example.cli-anything-macrocli-mermaid-routing",
        )
        self.assertEqual(
            payload["exports"]["a2a"]["agentCard"]["skills"][0]["metadata"]["cbn_input"]["metadata.cbn.workflow_id"],
            "example.cli-anything-macrocli-mermaid-routing",
        )
        self.assertEqual(
            payload["exports"]["acp"]["workflows"][0]["cbn"]["runner"],
            "cbn.workflow.run",
        )
        self.assertEqual(payload["exports"]["acp"]["workflows"][0]["input"]["workflow_id"], "string")

    def test_workflow_descriptor_roundtrip_uses_native_handles_without_paths(self):
        payload = export_all_workflow_protocols(
            self.registry,
            workflow_path="workflows/cli-anything-macrocli-mermaid-routing.example.json",
        )
        for protocol, descriptor in payload["exports"].items():
            with self.subTest(protocol=protocol):
                report = workflow_descriptor_roundtrip(self.registry, protocol, descriptor)
                self.assertTrue(report["ok"])
                self.assertFalse(report["uses_workflow_path"])
                self.assertTrue(report["input_declares_handle"])
                self.assertEqual(
                    report["resolved_path"],
                    "workflows/cli-anything-macrocli-mermaid-routing.example.json",
                )
                self.assertNotIn("workflow_path", json.dumps(report["generated_call"], ensure_ascii=False))

    def test_protocol_check_reports_descriptor_evidence_and_wire_gaps(self):
        payload = check_protocol(self.registry, "all", capability_id="cli-anything.mermaid.set-diagram")
        self.assertEqual(set(payload["checks"]), {"a2a", "acp", "mcp"})
        a2a = payload["checks"]["a2a"]
        self.assertFalse(a2a["wire_compatible"])
        self.assertTrue(
            any(
                item["requirement"] == "A2A AgentCard and SendMessage smoke"
                and item["status"] == "partial"
                for item in a2a["checks"]
            )
        )
        self.assertTrue(
            any(
                item["requirement"] == "A2A workflow SendMessage smoke"
                and item["status"] == "partial"
                for item in a2a["checks"]
            )
        )
        mcp = payload["checks"]["mcp"]
        self.assertFalse(mcp["wire_compatible"])
        self.assertGreaterEqual(mcp["status_counts"]["present"], 3)
        self.assertTrue(
            any(
                item["requirement"] == "MCP stdio initialize/tools/list/tools/call smoke"
                and item["status"] == "partial"
                for item in mcp["checks"]
            )
        )
        self.assertTrue(
            any(
                item["requirement"] == "MCP workflow tools/call smoke"
                and item["status"] == "partial"
                for item in mcp["checks"]
            )
        )
        self.assertTrue(any(item["requirement"] == "MCP full conformance" for item in mcp["checks"]))
        self.assertIn("modelcontextprotocol.io", mcp["source"]["url"])
        acp = payload["checks"]["acp"]
        self.assertFalse(acp["wire_compatible"])
        self.assertTrue(
            any(
                item["requirement"] == "ACP stdio initialize/session/new/session/prompt smoke"
                and item["status"] == "partial"
                for item in acp["checks"]
            )
        )
        self.assertTrue(
            any(
                item["requirement"] == "ACP workflow session/prompt smoke"
                and item["status"] == "partial"
                for item in acp["checks"]
            )
        )
        self.assertTrue(any(item["requirement"] == "ACP full session lifecycle and conformance" for item in acp["checks"]))
        self.assertIn("agentclientprotocol.com", acp["source"]["url"])

    def test_protocol_matrix_summarizes_capabilities_and_workflows(self):
        payload = protocol_matrix(self.registry, include_workflows=True)
        self.assertTrue(payload["ok"])
        self.assertEqual(set(payload["protocols"]), {"a2a", "acp", "mcp"})
        self.assertGreaterEqual(payload["capability_count"], 1)
        self.assertGreaterEqual(payload["workflow_count"], 1)
        capability = next(item for item in payload["rows"] if item["id"] == "git.status")
        self.assertEqual(capability["kind"], "capability")
        self.assertIn("mcp", capability["protocols"])
        workflow = next(item for item in payload["rows"] if item["kind"] == "workflow")
        self.assertIn("workflow", workflow["protocols"]["mcp"]["scope"])
        self.assertFalse(workflow["wire_compatible"])
        self.assertEqual(payload["summary"]["row_count"], len(payload["rows"]))

    def test_protocol_readiness_summarizes_bridge_routes_and_wire_gaps(self):
        payload = protocol_readiness_report(self.registry)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["kind"], "ProtocolReadinessReport")
        self.assertEqual(payload["scope"], "project")
        self.assertTrue(payload["wire_compatible"])
        self.assertTrue(payload["readiness"]["internal_bridge_ready"])
        self.assertTrue(payload["readiness"]["external_protocol_wire_compatible"])
        self.assertGreaterEqual(payload["summary"]["capability_count"], 1)
        self.assertEqual(
            payload["summary"]["portable_manifest_count"],
            payload["summary"]["capability_count"],
        )
        self.assertEqual(payload["summary"]["runtime_local_overlay_count"], 0)
        self.assertGreaterEqual(payload["summary"]["route_count"], 1)
        self.assertGreaterEqual(payload["parser_coverage"]["verified_output_count"], 1)
        unverified_capabilities = {
            item["capability_id"]
            for item in payload["parser_coverage"]["unverified_capabilities"]
        }
        self.assertTrue(unverified_capabilities <= {"jimeng.query_result"})
        self.assertEqual(
            payload["parser_coverage"]["unverified_output_count"],
            len(unverified_capabilities),
        )
        self.assertEqual(payload["manifest_sources"]["runtime_local_overlay_capabilities"], [])
        self.assertTrue(
            any(
                route["selector"] == "artifacts[0].artifact_id"
                for route in payload["routes"]
            )
        )
        self.assertEqual(set(payload["protocol_gaps"]), {"a2a", "acp", "mcp"})
        self.assertGreater(payload["protocol_gaps"]["mcp"]["missing_count"], 0)
        self.assertEqual(payload["wire_conformance"]["summary"]["wire_compatible_protocol_count"], 3)
        if unverified_capabilities:
            self.assertTrue(
                any("parser fixtures" in step for step in payload["next_steps"])
            )
        else:
            self.assertTrue(
                any("protocol smoke" in step for step in payload["next_steps"])
            )

    def test_protocol_readiness_separates_runtime_local_overlay_manifests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            portable_dir = root / "manifests"
            local_dir = root / "runtime" / "manifests"
            portable_dir.mkdir(parents=True)
            local_dir.mkdir(parents=True)
            (portable_dir / "portable.tool.json").write_text(
                json.dumps(_test_manifest("portable.tool", verified=True), ensure_ascii=False),
                encoding="utf-8",
            )
            (local_dir / "local.tool.json").write_text(
                json.dumps(_test_manifest("local.tool", verified=False), ensure_ascii=False),
                encoding="utf-8",
            )
            registry = ManifestRegistry()
            registry.load_dir(portable_dir)
            registry.load_dir(local_dir, replace=True)

            payload = protocol_readiness_report(registry, include_workflows=False)

        self.assertEqual(payload["summary"]["capability_count"], 2)
        self.assertEqual(payload["summary"]["portable_manifest_count"], 1)
        self.assertEqual(payload["summary"]["runtime_local_overlay_count"], 1)
        self.assertTrue(payload["readiness"]["portable_manifests_present"])
        self.assertTrue(payload["readiness"]["runtime_local_overlay_present"])
        self.assertEqual(
            payload["manifest_sources"]["by_source_kind"],
            {"portable_manifest": 1, "runtime_local_overlay": 1},
        )
        self.assertEqual(
            payload["manifest_sources"]["runtime_local_overlay_capabilities"][0]["capability_id"],
            "local.tool",
        )
        self.assertEqual(
            payload["parser_coverage"]["unverified_capabilities"][0]["source_kind"],
            "runtime_local_overlay",
        )
        self.assertTrue(
            any("runtime/manifests" in step for step in payload["next_steps"])
        )

    def test_protocol_readiness_can_focus_one_workflow(self):
        payload = protocol_readiness_report(
            self.registry,
            workflow_path="workflows/artifact-id-routing.example.json",
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["scope"], "workflow")
        self.assertEqual(payload["workflow_path"], "workflows/artifact-id-routing.example.json")
        self.assertEqual(payload["summary"]["workflow_count"], 1)
        self.assertEqual(payload["summary"]["route_count"], 1)
        self.assertIn("selected_workflow_protocols", payload)
        self.assertEqual(payload["selected_workflow_protocols"]["mcp"]["scope"], "workflow")
        self.assertIn("missing", payload["protocol_gaps"]["mcp"])

    def test_protocol_conformance_plan_keeps_wire_compatibility_false(self):
        payload = protocol_conformance_plan(self.registry, target="all", capability_id="git.version")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["kind"], "ProtocolConformancePlan")
        self.assertFalse(payload["wire_compatible"])
        self.assertEqual(set(payload["protocols"]), {"a2a", "acp", "mcp"})
        self.assertGreater(payload["summary"]["missing_gate_count"], 0)
        self.assertEqual(payload["summary"]["wire_compatible_protocol_count"], 0)
        self.assertEqual(payload["protocols"]["mcp"]["gates"][0]["id"], "descriptor_shape")
        self.assertTrue(
            any(gate["id"] == "sdk_conformance" and gate["status"] == "missing" for gate in payload["protocols"]["mcp"]["gates"])
        )
        self.assertTrue(
            any(gate["id"] == "task_lifecycle" and gate["status"] == "missing" for gate in payload["protocols"]["a2a"]["gates"])
        )
        self.assertTrue(
            any(gate["id"] == "session_lifecycle" and gate["status"] == "missing" for gate in payload["protocols"]["acp"]["gates"])
        )
        self.assertIn("modelcontextprotocol.io", payload["source_anchors"]["mcp"]["url"])

    def test_protocol_conformance_plan_can_focus_workflow(self):
        payload = protocol_conformance_plan(
            self.registry,
            target="mcp",
            workflow_path="workflows/artifact-id-routing.example.json",
        )
        self.assertEqual(payload["scope"], "workflow")
        self.assertEqual(payload["workflow_path"], "workflows/artifact-id-routing.example.json")
        self.assertEqual(set(payload["protocols"]), {"mcp"})
        self.assertEqual(payload["protocols"]["mcp"]["gates"][0]["status"], "present")
        self.assertFalse(payload["protocols"]["mcp"]["ready_to_claim_wire_compatibility"])

    def test_protocol_lifecycle_suite_runs_mvp_boundaries(self):
        payload = protocol_lifecycle_suite(
            capability_id="git.version",
            workflow_path="workflows/example.json",
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["kind"], "ProtocolLifecycleSuiteReport")
        self.assertTrue(payload["wire_compatible"])
        self.assertEqual(set(payload["protocols"]), {"a2a", "acp", "mcp"})
        self.assertEqual(payload["summary"]["failed_count"], 0)
        self.assertTrue(
            any(check["id"] == "mcp.ping" and check["ok"] for check in payload["protocols"]["mcp"]["checks"])
        )
        self.assertTrue(
            any(check["id"] == "a2a.get_task" and check["ok"] for check in payload["protocols"]["a2a"]["checks"])
        )
        self.assertTrue(
            any(check["id"] == "acp.session_cancel" and check["ok"] for check in payload["protocols"]["acp"]["checks"])
        )

    def test_mcp_stdio_ping_returns_empty_result(self):
        payload = McpStdioServer().handle_line('{"jsonrpc":"2.0","id":"ping-1","method":"ping"}')
        self.assertEqual(payload["result"], {})

    def test_cli_protocol_conformance_plan_outputs_report(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn", "protocol", "conformance-plan", "all", "--capability-id", "git.version"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["kind"], "ProtocolConformancePlan")
        self.assertFalse(payload["wire_compatible"])
        self.assertGreater(payload["summary"]["missing_gate_count"], 0)

    def test_cli_protocol_lifecycle_suite_outputs_report(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "protocol",
                "lifecycle-suite",
                "--capability-id",
                "git.version",
                "--workflow-path",
                "workflows/example.json",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["kind"], "ProtocolLifecycleSuiteReport")
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["wire_compatible"])

    def test_cli_protocol_wire_conformance_outputs_report(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn", "protocol", "wire-conformance", "all", "--capability-id", "git.version"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["kind"], "ProtocolWireConformanceReport")
        self.assertTrue(payload["wire_compatible"])
        self.assertEqual(payload["summary"]["wire_compatible_protocol_count"], 3)

    def test_protocol_smoke_suite_runs_all_mvp_facades(self):
        payload = protocol_smoke_suite(
            self.registry,
            capability_ids=("git.version",),
            workflow_paths=("workflows/example.json",),
            workflow_dry_run=True,
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["kind"], "ProtocolSmokeSuiteReport")
        self.assertTrue(payload["wire_compatible"])
        self.assertEqual(payload["summary"]["check_count"], 6)
        self.assertEqual(payload["summary"]["failed_count"], 0)
        self.assertEqual(set(payload["summary"]["by_protocol"]), {"a2a", "acp", "mcp"})
        self.assertTrue(payload["readiness"]["internal_bridge_ready"])
        self.assertTrue(payload["bridge_contract"]["ok"])
        self.assertEqual(payload["failures"], [])

    def test_protocol_smoke_suite_can_skip_workflows(self):
        payload = protocol_smoke_suite(
            self.registry,
            capability_ids=("git.version",),
            workflow_paths=(),
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["workflow_paths"], [])
        self.assertEqual(payload["summary"]["check_count"], 3)
        self.assertEqual(payload["summary"]["by_kind"]["workflow"]["passed"], 0)

    def test_cli_to_cli_acceptance_queue_summarizes_selected_workflows(self):
        runtime = build_runtime()
        payload = cli_to_cli_acceptance_queue(
            runtime.registry,
            runtime.workflow_runner,
            workflow_paths=(
                "workflows/message-routing.example.json",
                "workflows/artifact-id-routing.example.json",
            ),
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["kind"], "CliToCliAcceptanceQueue")
        self.assertEqual(payload["scope"], "selected")
        self.assertEqual(payload["summary"]["workflow_count"], 2)
        self.assertEqual(payload["summary"]["blocked_workflow_count"], 0)
        self.assertEqual(payload["summary"]["route_count"], 2)
        self.assertEqual(len(payload["rows"]), 2)
        self.assertFalse(payload["wire_compatible"])
        self.assertTrue(
            all(row["recommended_next_action"] == "run_acceptance_with_dry_run_or_protocol_smoke" for row in payload["rows"])
        )

    def test_cli_to_cli_acceptance_queue_can_attach_runtime_evidence(self):
        runtime = build_runtime()
        payload = cli_to_cli_acceptance_queue(
            runtime.registry,
            runtime.workflow_runner,
            workflow_paths=("workflows/message-routing.example.json",),
            run=True,
            dry_run=True,
        )
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["run"])
        self.assertEqual(payload["summary"]["runtime_route_count"], 1)
        self.assertEqual(payload["summary"]["runtime_route_failed_count"], 0)
        self.assertEqual(payload["rows"][0]["recommended_next_action"], "use_as_runtime_cli_to_cli_fixture")

    def test_bridge_lab_report_summarizes_cli_to_cli_protocol_baseline(self):
        runtime = build_runtime()
        payload = bridge_lab_report(
            runtime.registry,
            runtime.workflow_runner,
            workflow_paths=("workflows/cli-anything-macrocli-mermaid-routing.example.json",),
            run=True,
            dry_run=True,
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["kind"], "BridgeMessageProtocolLab")
        self.assertTrue(payload["wire_compatible"])
        self.assertEqual(payload["summary"]["route_count"], 2)
        self.assertEqual(payload["summary"]["runtime_route_failed_count"], 0)
        self.assertEqual(payload["summary"]["recommended_next_action"], "run_protocol_smoke_suite")
        self.assertEqual(len(payload["route_catalog"]), 2)
        self.assertIn("protocol_lifecycle_suite", payload["reports"])

    def test_cli_protocol_bridge_lab_outputs_report(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "protocol",
                "bridge-lab",
                "--workflow-path",
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
        self.assertEqual(payload["kind"], "BridgeMessageProtocolLab")
        self.assertEqual(payload["summary"]["runtime_route_failed_count"], 0)
        self.assertTrue(payload["reports"]["acceptance_queue"]["ok"])

    def test_cli_protocol_export(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn", "protocol", "export", "mcp", "--capability-id", "git.status"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["protocol"], "mcp")
        self.assertEqual(payload["tools"][0]["name"], "git.status")

    def test_cli_protocol_export_workflows(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "protocol",
                "export-workflows",
                "all",
                "--path",
                "workflows/cli-anything-macrocli-mermaid-routing.example.json",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(
            payload["exports"]["mcp"]["workflowTools"][0]["_meta"]["cbn"]["kind"],
            "WorkflowDescriptor",
        )

    def test_cli_protocol_check(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "protocol",
                "check",
                "mcp",
                "--capability-id",
                "cli-anything.mermaid.set-diagram",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["protocol"], "mcp")
        self.assertFalse(payload["wire_compatible"])
        self.assertEqual(payload["capability_id"], "cli-anything.mermaid.set-diagram")

    def test_protocol_check_reports_workflow_descriptor_evidence(self):
        payload = check_protocol(
            self.registry,
            "all",
            workflow_path="workflows/artifact-id-routing.example.json",
        )
        self.assertEqual(set(payload["checks"]), {"a2a", "acp", "mcp"})
        mcp = payload["checks"]["mcp"]
        self.assertEqual(mcp["scope"], "workflow")
        self.assertEqual(mcp["workflow_path"], "workflows/artifact-id-routing.example.json")
        self.assertIsNone(mcp["capability_id"])
        self.assertFalse(mcp["wire_compatible"])
        self.assertTrue(
            any(
                item["requirement"] == "MCP workflow handle is descriptor-native"
                and item["status"] == "present"
                for item in mcp["checks"]
            )
        )
        self.assertTrue(
            any(
                item["requirement"] == "CBN workflow descriptor is preserved"
                and item["status"] == "present"
                for item in mcp["checks"]
            )
        )
        self.assertTrue(
            any(
                item["requirement"] == "workflow descriptor call roundtrips through runtime resolver"
                and item["status"] == "present"
                and "without workflow_path" in item["evidence"]
                for item in mcp["checks"]
            )
        )
        routing = [
            item
            for item in mcp["checks"]
            if item["requirement"] == "workflow routing metadata is inspectable"
        ][0]
        self.assertEqual(routing["status"], "present")
        self.assertIn("artifacts[0].artifact_id", routing["evidence"])
        self.assertIn("artifact routing=true", routing["evidence"])
        a2a = payload["checks"]["a2a"]
        self.assertEqual(a2a["scope"], "workflow")
        self.assertTrue(
            any(
                item["requirement"] == "A2A workflow handle is descriptor-native"
                and item["status"] == "present"
                for item in a2a["checks"]
            )
        )
        self.assertTrue(
            any(
                item["requirement"] == "workflow descriptor call roundtrips through runtime resolver"
                and item["status"] == "present"
                for item in a2a["checks"]
            )
        )
        self.assertTrue(
            any(
                item["requirement"] == "A2A workflow SendMessage smoke"
                and "artifact-id-routing.example.json" in item["evidence"]
                for item in a2a["checks"]
            )
        )
        acp = payload["checks"]["acp"]
        self.assertEqual(acp["scope"], "workflow")
        self.assertTrue(
            any(
                item["requirement"] == "ACP workflow handle is descriptor-native"
                and item["status"] == "present"
                for item in acp["checks"]
            )
        )
        self.assertTrue(
            any(
                item["requirement"] == "workflow descriptor call roundtrips through runtime resolver"
                and item["status"] == "present"
                for item in acp["checks"]
            )
        )
        self.assertGreaterEqual(acp["status_counts"]["present"], 4)

    def test_protocol_check_rejects_mixed_capability_and_workflow_scope(self):
        with self.assertRaises(ValueError):
            check_protocol(
                self.registry,
                "mcp",
                capability_id="git.status",
                workflow_path="workflows/example.json",
            )

    def test_cli_protocol_check_workflow(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "protocol",
                "check",
                "mcp",
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
        self.assertEqual(payload["protocol"], "mcp")
        self.assertEqual(payload["scope"], "workflow")
        self.assertEqual(payload["workflow_path"], "workflows/artifact-id-routing.example.json")
        self.assertTrue(
            any("artifacts[0].artifact_id" in item["evidence"] for item in payload["checks"])
        )

    def test_cli_protocol_readiness(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "protocol",
                "readiness",
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
        self.assertEqual(payload["kind"], "ProtocolReadinessReport")
        self.assertEqual(payload["scope"], "workflow")
        self.assertEqual(payload["summary"]["route_count"], 1)
        self.assertTrue(payload["wire_compatible"])

    def test_cli_protocol_smoke_suite(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "protocol",
                "smoke-suite",
                "--capability-id",
                "git.version",
                "--workflow-path",
                "workflows/example.json",
                "--workflow-dry-run",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["summary"]["check_count"], 6)
        self.assertTrue(payload["wire_compatible"])

    def test_cli_protocol_acceptance_queue(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "protocol",
                "acceptance-queue",
                "--workflow-path",
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
        self.assertEqual(payload["kind"], "CliToCliAcceptanceQueue")
        self.assertEqual(payload["summary"]["runtime_route_failed_count"], 0)
        self.assertEqual(payload["rows"][0]["workflow_path"], "workflows/message-routing.example.json")

def _test_manifest(capability_id: str, verified: bool) -> dict:
    return {
        "apiVersion": "bridge.dev/v1alpha1",
        "kind": "ToolManifest",
        "metadata": {"id": capability_id, "title": capability_id},
        "spec": {
            "transport": {
                "kind": "stdio",
                "command": sys.executable,
                "argsTemplate": ["--version"],
                "cwdPolicy": "workspace",
            },
            "policy": {"risk": "read", "requiresConfirmation": False, "network": "deny"},
            "output": {"parserRef": "raw.text", "verified": verified},
        },
    }


if __name__ == "__main__":
    unittest.main()
