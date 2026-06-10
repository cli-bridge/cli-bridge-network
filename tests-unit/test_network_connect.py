import json
import subprocess
import sys
import unittest

from cbn_demo.network_connect import network_connect_package, workflow_studio_demo_link
from cbn_runtime.context import build_runtime


class NetworkConnectPackageTests(unittest.TestCase):
    def test_network_connect_package_collects_external_and_internal_contracts(self):
        runtime = build_runtime()
        payload = network_connect_package(
            runtime.registry,
            workflow_path="workflows/cli-anything-macrocli-mermaid-routing.example.json",
            base_url="http://127.0.0.1:8787",
            studio_url="http://127.0.0.1:5177",
            session_token="test-token",
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["kind"], "NetworkConnectPackage")
        self.assertEqual(payload["contracts"]["external"]["protocol"], "agent-cli-contract")
        self.assertEqual(payload["contracts"]["external"]["accepted_kinds"], ["AgentCliCard", "RunReceipt"])
        self.assertEqual(payload["contracts"]["external"]["receipt_mapping"]["message_channel"], "agent-cli.run.receipt")
        self.assertGreaterEqual(payload["summary"]["bridge_route_count"], 1)
        self.assertTrue(payload["summary"]["agent_workflow_request_ready"])
        self.assertEqual(payload["protocols"]["mcp"]["workflow_tool_count"], 1)
        self.assertEqual(payload["protocols"]["a2a"]["skill_count"], 1)
        self.assertEqual(payload["protocols"]["acp"]["workflow_count"], 1)
        self.assertEqual(payload["agent_workflow_request"]["kind"], "AdapterAgentWorkflowRequestPlan")
        self.assertEqual(payload["agent_workflow_request"]["reusable_harness"]["kind"], "NaturalLanguageWorkflowHarness")
        self.assertEqual(payload["agent_workflow_request"]["bridge_message_channel"], "agent.workflow.request.plan")
        self.assertEqual(payload["workflow_studio"]["kind"], "WorkflowStudioDemoLink")
        self.assertTrue(payload["workflow_studio"]["session_token_included"])
        self.assertIn("daemonUrl=http%3A%2F%2F127.0.0.1%3A8787", payload["workflow_studio"]["url"])
        self.assertIn("sessionToken=test-token", payload["workflow_studio"]["url"])
        quickstart = payload["consumer_quickstart"]
        self.assertEqual(quickstart["kind"], "NetworkConnectQuickstart")
        self.assertEqual(quickstart["status"], "ready")
        self.assertEqual(quickstart["required_headers"]["X-CBN-Session"], "test-token")
        self.assertEqual(quickstart["entrypoints"]["open_studio"], payload["workflow_studio"]["url"])
        self.assertEqual(
            quickstart["entrypoints"]["plan_agent_request"]["url"],
            "http://127.0.0.1:8787/adapter-agent/workflow-request-plan",
        )
        self.assertEqual(
            quickstart["entrypoints"]["run_workflow"]["url"],
            "http://127.0.0.1:8787/workflows/run",
        )
        self.assertEqual(
            quickstart["entrypoints"]["run_workflow"]["json"]["path"],
            "workflows/cli-anything-macrocli-mermaid-routing.example.json",
        )
        self.assertEqual(quickstart["sequence"][0], "open_studio")
        self.assertIn("run_workflow", quickstart["sequence"])
        endpoint_paths = {endpoint["path"] for endpoint in payload["daemon_endpoints"]}
        self.assertIn("/adapter-agent/workflow-request-plan", endpoint_paths)
        self.assertTrue(any(endpoint["url"].startswith("http://127.0.0.1:8787/") for endpoint in payload["daemon_endpoints"]))

    def test_workflow_studio_demo_link_encodes_query_parameters(self):
        payload = workflow_studio_demo_link(
            workflow_path="workflows/demo.json",
            daemon_url="http://127.0.0.1:8788/",
            studio_url="http://127.0.0.1:5177/",
            session_token="secret-token",
            agent_message="Run CLI-CLI flow",
        )

        self.assertEqual(payload["kind"], "WorkflowStudioDemoLink")
        self.assertEqual(payload["studio_url"], "http://127.0.0.1:5177")
        self.assertEqual(payload["daemon_url"], "http://127.0.0.1:8788")
        self.assertTrue(payload["session_token_included"])
        self.assertIn("workflowPath=workflows%2Fdemo.json", payload["url"])
        self.assertIn("daemonUrl=http%3A%2F%2F127.0.0.1%3A8788", payload["url"])
        self.assertIn("dryRun=true", payload["url"])
        self.assertIn("confirmed=false", payload["url"])

    def test_network_connect_package_cli_outputs_json(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "network",
                "connect-package",
                "--workflow-path",
                "workflows/cli-anything-macrocli-mermaid-routing.example.json",
                "--base-url",
                "http://127.0.0.1:8787",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["kind"], "NetworkConnectPackage")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["summary"]["recommended_next_action"], "call_daemon_endpoints")
        self.assertEqual(payload["contracts"]["external"]["generated_capability_ids"], ["example.macrocli.backends"])
        self.assertEqual(payload["agent_workflow_request"]["run"]["http"]["url"], "http://127.0.0.1:8787/workflows/run")
        self.assertEqual(payload["workflow_studio"]["daemon_url"], "http://127.0.0.1:8787")
        self.assertEqual(payload["consumer_quickstart"]["entrypoints"]["run_workflow"]["url"], "http://127.0.0.1:8787/workflows/run")

    def test_network_quickstart_cli_outputs_first_call_package(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "network",
                "quickstart",
                "--workflow-path",
                "workflows/cli-anything-macrocli-mermaid-routing.example.json",
                "--base-url",
                "http://127.0.0.1:8787",
                "--studio-url",
                "http://127.0.0.1:5177",
                "--session-token",
                "test-token",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["kind"], "NetworkConnectQuickstart")
        self.assertEqual(payload["required_headers"]["X-CBN-Session"], "test-token")
        self.assertIn("sessionToken=test-token", payload["entrypoints"]["open_studio"])
        self.assertEqual(payload["entrypoints"]["plan_agent_request"]["method"], "POST")
        self.assertEqual(payload["entrypoints"]["run_workflow"]["url"], "http://127.0.0.1:8787/workflows/run")
        self.assertEqual(
            payload["entrypoints"]["run_workflow"]["json"]["path"],
            "workflows/cli-anything-macrocli-mermaid-routing.example.json",
        )
        self.assertNotIn("contracts", payload)

    def test_network_studio_link_cli_outputs_json(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "network",
                "studio-link",
                "--workflow-path",
                "workflows/cli-anything-macrocli-mermaid-routing.example.json",
                "--daemon-url",
                "http://127.0.0.1:8788",
                "--studio-url",
                "http://127.0.0.1:5177",
                "--session-token",
                "test-token",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["kind"], "WorkflowStudioDemoLink")
        self.assertIn("sessionToken=test-token", payload["url"])


if __name__ == "__main__":
    unittest.main()
