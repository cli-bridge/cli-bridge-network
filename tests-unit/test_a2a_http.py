import json
import subprocess
import sys
import unittest

from cbn_protocol.a2a_http import agent_card, handle_a2a_jsonrpc_request, smoke_a2a_http


class A2AHttpTests(unittest.TestCase):
    def test_agent_card_contains_supported_interface_and_skills(self):
        card = agent_card("http://127.0.0.1:8787")
        self.assertEqual(card["protocolVersion"], "0.3")
        self.assertEqual(card["supportedInterfaces"][0]["protocolBinding"], "JSONRPC")
        self.assertEqual(card["supportedInterfaces"][0]["url"], "http://127.0.0.1:8787/a2a")
        self.assertFalse(card["capabilities"]["streaming"])
        skill_ids = {skill["id"] for skill in card["skills"]}
        self.assertIn("git.version", skill_ids)

    def test_message_send_routes_to_capability_and_returns_task(self):
        response = handle_a2a_jsonrpc_request(
            {
                "jsonrpc": "2.0",
                "id": "test-1",
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": "message-1",
                        "role": "user",
                        "parts": [{"text": "version"}],
                    },
                    "metadata": {"cbn": {"capability_id": "git.version"}},
                },
            }
        )
        task = response["result"]
        self.assertEqual(response["jsonrpc"], "2.0")
        self.assertEqual(task["status"]["state"], "completed")
        self.assertEqual(task["metadata"]["cbn"]["capability_id"], "git.version")
        self.assertEqual(task["metadata"]["cbn"]["exit_code"], 0)
        self.assertTrue(task["artifacts"])

    def test_smoke_runs_real_daemon_routes(self):
        payload = smoke_a2a_http("git.version")
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["response"]["result"]["status"]["state"], "completed")

    def test_cli_a2a_smoke(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn", "a2a", "smoke", "--capability-id", "git.version"],
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
