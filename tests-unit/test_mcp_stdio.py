import json
import subprocess
import sys
import unittest

from cbn_protocol.mcp_stdio import McpStdioServer, smoke_mcp_stdio, smoke_mcp_workflow_stdio


class McpStdioTests(unittest.TestCase):
    def test_initialize_and_tools_list_jsonrpc_shape(self):
        server = McpStdioServer()
        init = server.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-11-25"},
                }
            )
        )
        self.assertEqual(init["jsonrpc"], "2.0")
        self.assertEqual(init["result"]["serverInfo"]["name"], "CLI Bridge Network")
        self.assertIn("tools", init["result"]["capabilities"])

        tools = server.handle_line(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}))
        tool_names = {item["name"] for item in tools["result"]["tools"]}
        self.assertIn("git.version", tool_names)
        self.assertIn("workflow:example.git-check", tool_names)

    def test_tools_call_routes_through_executor(self):
        server = McpStdioServer()
        response = server.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "git.version", "arguments": {}},
                }
            )
        )
        result = response["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["capability_id"], "git.version")
        self.assertEqual(result["structuredContent"]["exit_code"], 0)
        self.assertIn("git version", result["content"][0]["text"])

    def test_tools_call_can_run_workflow(self):
        server = McpStdioServer()
        response = server.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "workflow:example.git-check",
                        "arguments": {"dry_run": True},
                    },
                }
            )
        )
        result = response["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["workflow_id"], "example.git-check")
        self.assertEqual(result["structuredContent"]["workflow_path"], "workflows/example.json")
        self.assertEqual(result["structuredContent"]["run"]["status"], "completed")

    def test_smoke_runs_real_stdio_server(self):
        payload = smoke_mcp_stdio("git.version")
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["responses"][0]["result"]["serverInfo"]["name"], "CLI Bridge Network")
        self.assertFalse(payload["responses"][2]["result"]["isError"])

    def test_cli_mcp_smoke(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn", "mcp", "smoke", "--capability-id", "git.version"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["capability_id"], "git.version")

    def test_cli_mcp_smoke_workflow(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "mcp",
                "smoke-workflow",
                "--path",
                "workflows/example.json",
                "--dry-run",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["tool_name"], "workflow:example.git-check")

    def test_smoke_workflow_runs_real_stdio_server(self):
        payload = smoke_mcp_workflow_stdio("workflows/example.json", dry_run=True)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["tool_name"], "workflow:example.git-check")


if __name__ == "__main__":
    unittest.main()
