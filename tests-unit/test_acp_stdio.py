import json
import subprocess
import sys
import unittest
from pathlib import Path

from cbn_protocol.acp_stdio import AcpStdioAgent, smoke_acp_stdio


class AcpStdioTests(unittest.TestCase):
    def test_initialize_and_new_session_shape(self):
        agent = AcpStdioAgent()
        init = agent.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": 1},
                }
            )
        )
        self.assertEqual(init["jsonrpc"], "2.0")
        self.assertEqual(init["result"]["protocolVersion"], 1)
        self.assertEqual(init["result"]["agentInfo"]["name"], "CLI Bridge Network")
        self.assertIn("promptCapabilities", init["result"]["agentCapabilities"])

        session = agent.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "session/new",
                    "params": {"cwd": str(Path.cwd()), "mcpServers": []},
                }
            )
        )
        self.assertIsInstance(session["result"]["sessionId"], str)
        self.assertEqual(session["result"]["_meta"]["cbn"]["cwd"], str(Path.cwd()))

    def test_session_prompt_routes_through_executor(self):
        agent = AcpStdioAgent()
        session = agent.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "session/new",
                    "params": {"cwd": str(Path.cwd()), "mcpServers": []},
                }
            )
        )["result"]["sessionId"]
        response = agent.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "session/prompt",
                    "params": {
                        "sessionId": session,
                        "prompt": [{"type": "text", "text": "version"}],
                        "_meta": {"cbn": {"capability_id": "git.version"}},
                    },
                }
            )
        )
        result = response["result"]
        self.assertEqual(result["stopReason"], "end_turn")
        cbn = result["_meta"]["cbn"]
        self.assertEqual(cbn["capability_id"], "git.version")
        self.assertEqual(cbn["exit_code"], 0)
        self.assertTrue(cbn["artifacts"])

    def test_smoke_runs_real_stdio_agent(self):
        payload = smoke_acp_stdio("git.version")
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["responses"][0]["result"]["agentInfo"]["name"], "CLI Bridge Network")
        self.assertEqual(payload["responses"][2]["result"]["stopReason"], "end_turn")

    def test_cli_acp_smoke(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn", "acp", "smoke", "--capability-id", "git.version"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["capability_id"], "git.version")


if __name__ == "__main__":
    unittest.main()
