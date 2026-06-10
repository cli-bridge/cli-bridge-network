import json
import subprocess
import sys
import unittest

from cbn_demo.network_connect import network_connect_package
from cbn_runtime.context import build_runtime


class NetworkConnectPackageTests(unittest.TestCase):
    def test_network_connect_package_collects_external_and_internal_contracts(self):
        runtime = build_runtime()
        payload = network_connect_package(
            runtime.registry,
            workflow_path="workflows/cli-anything-macrocli-mermaid-routing.example.json",
            base_url="http://127.0.0.1:8787",
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["kind"], "NetworkConnectPackage")
        self.assertEqual(payload["contracts"]["external"]["protocol"], "agent-cli-contract")
        self.assertEqual(payload["contracts"]["external"]["accepted_kinds"], ["AgentCliCard", "RunReceipt"])
        self.assertEqual(payload["contracts"]["external"]["receipt_mapping"]["message_channel"], "agent-cli.run.receipt")
        self.assertGreaterEqual(payload["summary"]["bridge_route_count"], 1)
        self.assertEqual(payload["protocols"]["mcp"]["workflow_tool_count"], 1)
        self.assertEqual(payload["protocols"]["a2a"]["skill_count"], 1)
        self.assertEqual(payload["protocols"]["acp"]["workflow_count"], 1)
        self.assertTrue(any(endpoint["url"].startswith("http://127.0.0.1:8787/") for endpoint in payload["daemon_endpoints"]))

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


if __name__ == "__main__":
    unittest.main()
