import json
import subprocess
import sys
import unittest
from pathlib import Path

from cbn_core.manifest import ManifestRegistry
from cbn_protocol.compatibility import check_protocol, protocol_matrix
from cbn_protocol.exports import (
    export_all_protocols,
    export_all_workflow_protocols,
    export_protocol,
    export_workflow_protocol,
    list_protocol_exports,
)
from cbn_protocol.readiness import protocol_readiness_report


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
            payload["exports"]["acp"]["workflows"][0]["cbn"]["runner"],
            "cbn.workflow.run",
        )

    def test_protocol_check_reports_descriptor_evidence_and_wire_gaps(self):
        payload = check_protocol(self.registry, "all", capability_id="cli-anything.mermaid.set-diagram")
        self.assertEqual(set(payload["checks"]), {"a2a", "acp", "mcp"})
        a2a = payload["checks"]["a2a"]
        self.assertFalse(a2a["wire_compatible"])
        self.assertTrue(
            any(
                item["requirement"] == "A2A AgentCard and message/send smoke"
                and item["status"] == "partial"
                for item in a2a["checks"]
            )
        )
        self.assertTrue(
            any(
                item["requirement"] == "A2A workflow message/send smoke"
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
        self.assertFalse(payload["wire_compatible"])
        self.assertTrue(payload["readiness"]["internal_bridge_ready"])
        self.assertFalse(payload["readiness"]["external_protocol_wire_compatible"])
        self.assertGreaterEqual(payload["summary"]["capability_count"], 1)
        self.assertGreaterEqual(payload["summary"]["route_count"], 1)
        self.assertGreaterEqual(payload["parser_coverage"]["verified_output_count"], 1)
        self.assertGreaterEqual(payload["parser_coverage"]["unverified_output_count"], 1)
        self.assertTrue(
            any(
                route["selector"] == "artifacts[0].artifact_id"
                for route in payload["routes"]
            )
        )
        self.assertEqual(set(payload["protocol_gaps"]), {"a2a", "acp", "mcp"})
        self.assertGreater(payload["protocol_gaps"]["mcp"]["missing_count"], 0)
        self.assertTrue(
            any("wire_compatible=false" in step for step in payload["next_steps"])
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
                item["requirement"] == "CBN workflow descriptor is preserved"
                and item["status"] == "present"
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
                item["requirement"] == "A2A workflow message/send smoke"
                and "artifact-id-routing.example.json" in item["evidence"]
                for item in a2a["checks"]
            )
        )
        acp = payload["checks"]["acp"]
        self.assertEqual(acp["scope"], "workflow")
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
        self.assertFalse(payload["wire_compatible"])


if __name__ == "__main__":
    unittest.main()
