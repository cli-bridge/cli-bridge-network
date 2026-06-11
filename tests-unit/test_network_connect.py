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
        internal = payload["contracts"]["internal"]
        self.assertEqual(internal["protocol"], "CBN BridgeMessage CLI-to-CLI Protocol")
        self.assertEqual(internal["api_version"], "bridge.dev/v1alpha1")
        self.assertEqual(
            internal["contract_sections"],
            ["artifact", "bridge_message", "tool_manifest", "workflow_selector"],
        )
        self.assertEqual(internal["contracts"]["tool_manifest"]["kind"], "ToolManifest")
        self.assertEqual(internal["contracts"]["bridge_message"]["kind"], "BridgeMessage")
        self.assertEqual(internal["contracts"]["artifact"]["kind"], "ArtifactRecord")
        self.assertEqual(internal["contracts"]["workflow_selector"]["kind"], "WorkflowSelector")
        self.assertEqual(
            internal["bridge_contract"]["contract"]["contracts"]["bridge_message"]["kind"],
            "BridgeMessage",
        )
        self.assertGreaterEqual(payload["summary"]["bridge_route_count"], 1)
        self.assertTrue(payload["summary"]["agent_workflow_request_ready"])
        self.assertTrue(payload["summary"]["demo_ready"])
        self.assertEqual(payload["summary"]["demo_stage_count"], 7)
        self.assertEqual(payload["protocols"]["mcp"]["workflow_tool_count"], 1)
        self.assertEqual(payload["protocols"]["a2a"]["skill_count"], 1)
        self.assertEqual(payload["protocols"]["acp"]["workflow_count"], 1)
        demo = payload["demo_readiness"]
        self.assertEqual(demo["kind"], "KillerDemoReadiness")
        self.assertEqual(demo["status"], "ready")
        self.assertEqual(demo["workflow_path"], "workflows/cli-anything-macrocli-mermaid-routing.example.json")
        self.assertEqual(demo["stage_count"], 7)
        self.assertIn("BridgeMessage", demo["evidence_contracts"])
        self.assertEqual(set(demo["protocol_targets"]), {"a2a", "acp", "mcp"})
        self.assertEqual(demo["demo_endpoint"]["path"], "/demo/killer")
        self.assertIn("inspect_agent_nodes", demo["acceptance_request_ids"])
        self.assertIn("python -m cbn demo killer", demo["next_commands"][0])
        self.assertEqual(payload["agent_workflow_request"]["kind"], "AdapterAgentWorkflowRequestPlan")
        self.assertEqual(payload["agent_workflow_request"]["reusable_harness"]["kind"], "NaturalLanguageWorkflowHarness")
        self.assertEqual(payload["agent_workflow_request"]["bridge_message_channel"], "agent.workflow.request.plan")
        agent_bundle = payload["agent_node_bundle"]
        self.assertEqual(agent_bundle["kind"], "AdapterAgentNodeBundle")
        self.assertEqual(agent_bundle["session"]["kind"], "AgentSession")
        self.assertEqual(agent_bundle["session"]["agent_id"], "orchestration-coordinator-agent")
        self.assertEqual(agent_bundle["cards"][0]["kind"], "AgentCard")
        self.assertTrue(any(card["id"] == "orchestration-coordinator-agent" for card in agent_bundle["cards"]))
        self.assertEqual(agent_bundle["harnesses"][0]["kind"], "AgentHarness")
        self.assertIn("BridgeMessage", agent_bundle["harnesses"][0]["accepts"])
        self.assertEqual(agent_bundle["tasks"][0]["kind"], "AgentTask")
        self.assertEqual(agent_bundle["bridge_message"]["kind"], "BridgeMessage")
        self.assertEqual(agent_bundle["bridge_message"]["channel"], "agent.adapter.node_bundle")
        self.assertEqual(payload["workflow_studio"]["kind"], "WorkflowStudioDemoLink")
        self.assertTrue(payload["workflow_studio"]["session_token_included"])
        self.assertEqual(payload["workflow_studio"]["dashboard_url"], "http://127.0.0.1:5173")
        self.assertIn("daemonUrl=http%3A%2F%2F127.0.0.1%3A8787", payload["workflow_studio"]["url"])
        self.assertIn("dashboardUrl=http%3A%2F%2F127.0.0.1%3A5173", payload["workflow_studio"]["url"])
        self.assertIn("sessionToken=test-token", payload["workflow_studio"]["url"])
        self.assertEqual(payload["acceptance"]["kind"], "NetworkConnectionAcceptance")
        self.assertEqual(payload["acceptance"]["check_count"], 10)
        self.assertIn("inspect_agent_nodes", payload["acceptance"]["required_request_ids"])
        self.assertIn("export_protocols", payload["acceptance"]["required_request_ids"])
        self.assertIn("run_workflow", payload["acceptance"]["required_request_ids"])
        self.assertEqual(payload["acceptance"]["checks"][3]["request_id"], "inspect_agent_nodes")
        self.assertEqual(payload["acceptance"]["checks"][3]["expect"]["json.kind"], "AdapterAgentNodeBundle")
        self.assertEqual(payload["acceptance"]["checks"][4]["request_id"], "export_protocols")
        self.assertEqual(payload["acceptance"]["checks"][4]["expect"]["json.exports.mcp.protocol"], "mcp")
        self.assertEqual(payload["acceptance"]["checks"][5]["request_id"], "plan_agent_request")
        self.assertEqual(
            payload["acceptance"]["checks"][5]["expect"]["json.reusable_harness.kind"],
            "NaturalLanguageWorkflowHarness",
        )
        self.assertEqual(payload["acceptance"]["checks"][7]["request_id"], "events")
        self.assertEqual(payload["acceptance"]["checks"][7]["expect"]["json.count_min"], 1)
        self.assertEqual(payload["acceptance"]["checks"][8]["request_id"], "audit")
        self.assertEqual(payload["acceptance"]["checks"][8]["expect"]["json.count_min"], 1)
        self.assertEqual(payload["acceptance"]["checks"][9]["request_id"], "artifacts")
        self.assertEqual(payload["acceptance"]["checks"][9]["expect"]["json.count_min"], 1)
        quickstart = payload["consumer_quickstart"]
        self.assertEqual(quickstart["kind"], "NetworkConnectQuickstart")
        self.assertEqual(quickstart["status"], "ready")
        self.assertEqual(quickstart["acceptance"], payload["acceptance"])
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
        requests_by_id = {request["id"]: request for request in quickstart["requests"]}
        self.assertEqual(requests_by_id["health"]["method"], "GET")
        self.assertEqual(requests_by_id["health"]["headers"]["X-CBN-Session"], "test-token")
        self.assertIn("curl -X GET", requests_by_id["health"]["curl"])
        self.assertIn("-H 'X-CBN-Session: test-token'", requests_by_id["health"]["curl"])
        self.assertEqual(requests_by_id["inspect_agent_nodes"]["method"], "GET")
        self.assertIn("/adapter-agent/node-bundle?", requests_by_id["inspect_agent_nodes"]["url"])
        self.assertEqual(requests_by_id["export_protocols"]["method"], "GET")
        self.assertIn("/protocols/workflows?", requests_by_id["export_protocols"]["url"])
        self.assertEqual(requests_by_id["plan_agent_request"]["method"], "POST")
        self.assertEqual(
            requests_by_id["plan_agent_request"]["json"]["workflow_path"],
            "workflows/cli-anything-macrocli-mermaid-routing.example.json",
        )
        self.assertIn("--data", requests_by_id["plan_agent_request"]["curl"])
        self.assertEqual(requests_by_id["run_workflow"]["url"], "http://127.0.0.1:8787/workflows/run")
        self.assertEqual(len(quickstart["requests"]), 10)
        self.assertTrue(quickstart["curl_script"].startswith("set -e\ncurl -X GET"))
        self.assertIn("curl -X GET 'http://127.0.0.1:8787/protocols/workflows?", quickstart["curl_script"])
        self.assertIn("curl -X POST 'http://127.0.0.1:8787/workflows/run'", quickstart["curl_script"])
        self.assertTrue(quickstart["powershell_script"].startswith("$ErrorActionPreference = 'Stop'"))
        self.assertIn("'X-CBN-Session' = 'test-token'", quickstart["powershell_script"])
        self.assertIn("Invoke-RestMethod -Method 'POST'", quickstart["powershell_script"])
        endpoint_paths = {endpoint["path"] for endpoint in payload["daemon_endpoints"]}
        self.assertIn("/network/quickstart", endpoint_paths)
        self.assertIn("/network/verify", endpoint_paths)
        self.assertIn("/adapter-agent/workflow-request-plan", endpoint_paths)
        self.assertTrue(any(endpoint["url"].startswith("http://127.0.0.1:8787/") for endpoint in payload["daemon_endpoints"]))

    def test_workflow_studio_demo_link_encodes_query_parameters(self):
        payload = workflow_studio_demo_link(
            workflow_path="workflows/demo.json",
            daemon_url="http://127.0.0.1:8788/",
            studio_url="http://127.0.0.1:5177/",
            dashboard_url="http://127.0.0.1:5173/",
            session_token="secret-token",
            agent_message="Run CLI-CLI flow",
        )

        self.assertEqual(payload["kind"], "WorkflowStudioDemoLink")
        self.assertEqual(payload["studio_url"], "http://127.0.0.1:5177")
        self.assertEqual(payload["dashboard_url"], "http://127.0.0.1:5173")
        self.assertEqual(payload["daemon_url"], "http://127.0.0.1:8788")
        self.assertTrue(payload["session_token_included"])
        self.assertIn("workflowPath=workflows%2Fdemo.json", payload["url"])
        self.assertIn("daemonUrl=http%3A%2F%2F127.0.0.1%3A8788", payload["url"])
        self.assertIn("dashboardUrl=http%3A%2F%2F127.0.0.1%3A5173", payload["url"])
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
        self.assertEqual(payload["contracts"]["internal"]["contracts"]["artifact"]["kind"], "ArtifactRecord")
        self.assertEqual(payload["agent_workflow_request"]["run"]["http"]["url"], "http://127.0.0.1:8787/workflows/run")
        self.assertEqual(payload["workflow_studio"]["daemon_url"], "http://127.0.0.1:8787")
        self.assertEqual(payload["workflow_studio"]["dashboard_url"], "http://127.0.0.1:5173")
        self.assertIn("dashboardUrl=http%3A%2F%2F127.0.0.1%3A5173", payload["workflow_studio"]["url"])
        self.assertEqual(payload["agent_node_bundle"]["cards"][0]["kind"], "AgentCard")
        self.assertEqual(payload["agent_node_bundle"]["harnesses"][0]["kind"], "AgentHarness")
        self.assertEqual(payload["consumer_quickstart"]["entrypoints"]["run_workflow"]["url"], "http://127.0.0.1:8787/workflows/run")
        self.assertEqual(payload["demo_readiness"]["status"], "ready")

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
                "--dashboard-url",
                "http://127.0.0.1:5199",
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
        self.assertIn("/adapter-agent/node-bundle?", payload["entrypoints"]["inspect_agent_nodes"])
        self.assertIn("/protocols/workflows?", payload["entrypoints"]["export_protocols"])
        self.assertEqual(payload["entrypoints"]["run_workflow"]["url"], "http://127.0.0.1:8787/workflows/run")
        self.assertEqual(payload["requests"][0]["id"], "health")
        self.assertEqual(payload["requests"][3]["id"], "inspect_agent_nodes")
        self.assertEqual(payload["requests"][4]["id"], "export_protocols")
        self.assertEqual(payload["requests"][6]["id"], "run_workflow")
        self.assertEqual(payload["requests"][6]["headers"]["X-CBN-Session"], "test-token")
        self.assertIn("curl -X POST", payload["requests"][6]["curl"])
        self.assertEqual(payload["acceptance"]["kind"], "NetworkConnectionAcceptance")
        self.assertEqual(payload["acceptance"]["check_count"], 10)
        self.assertEqual(payload["acceptance"]["checks"][6]["request_id"], "run_workflow")
        self.assertIn("curl -X GET 'http://127.0.0.1:8787/health'", payload["curl_script"])
        self.assertIn("$Body_run_workflow", payload["powershell_script"])
        self.assertEqual(
            payload["entrypoints"]["run_workflow"]["json"]["path"],
            "workflows/cli-anything-macrocli-mermaid-routing.example.json",
        )
        self.assertNotIn("contracts", payload)

    def test_network_quickstart_cli_outputs_acceptance_checklist(self):
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
                "--output",
                "acceptance",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["kind"], "NetworkConnectionAcceptance")
        self.assertEqual(payload["check_count"], 10)
        self.assertEqual(payload["checks"][0]["request_id"], "health")
        self.assertEqual(payload["checks"][3]["request_id"], "inspect_agent_nodes")
        self.assertEqual(payload["checks"][3]["expect"]["json.kind"], "AdapterAgentNodeBundle")
        self.assertEqual(payload["checks"][4]["request_id"], "export_protocols")
        self.assertEqual(payload["checks"][4]["expect"]["json.exports.acp.protocol"], "acp")
        self.assertEqual(payload["checks"][5]["expect"]["json.kind"], "AdapterAgentWorkflowRequestPlan")
        self.assertNotIn("curl_script", payload)

    def test_network_quickstart_cli_outputs_shell_scripts(self):
        base_args = [
            sys.executable,
            "-m",
            "cbn",
            "network",
            "quickstart",
            "--workflow-path",
            "workflows/cli-anything-macrocli-mermaid-routing.example.json",
            "--base-url",
            "http://127.0.0.1:8787",
            "--session-token",
            "test-token",
        ]
        curl_proc = subprocess.run(
            [*base_args, "--output", "curl"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        self.assertTrue(curl_proc.stdout.startswith("set -e\ncurl -X GET"))
        self.assertIn("curl -X POST 'http://127.0.0.1:8787/workflows/run'", curl_proc.stdout)
        self.assertIn("'X-CBN-Session: test-token'", curl_proc.stdout)
        self.assertNotIn('"kind"', curl_proc.stdout)

        powershell_proc = subprocess.run(
            [*base_args, "--output", "powershell"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        self.assertTrue(powershell_proc.stdout.startswith("$ErrorActionPreference = 'Stop'"))
        self.assertIn("$Body_run_workflow", powershell_proc.stdout)
        self.assertIn("Invoke-RestMethod -Method 'POST'", powershell_proc.stdout)
        self.assertIn("'X-CBN-Session' = 'test-token'", powershell_proc.stdout)
        self.assertNotIn('"kind"', powershell_proc.stdout)

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
                "--dashboard-url",
                "http://127.0.0.1:5199",
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
        self.assertEqual(payload["dashboard_url"], "http://127.0.0.1:5199")
        self.assertIn("dashboardUrl=http%3A%2F%2F127.0.0.1%3A5199", payload["url"])
        self.assertIn("sessionToken=test-token", payload["url"])


if __name__ == "__main__":
    unittest.main()
