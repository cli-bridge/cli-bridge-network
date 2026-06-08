import json
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import ThreadingHTTPServer

from api_server.server import CbnRequestHandler, ROUTE_SUMMARY


class DaemonApiTests(unittest.TestCase):
    def test_route_summary_exposes_cli_anything_evaluation(self):
        routes = {(route["method"], route["path"]) for route in ROUTE_SUMMARY}
        self.assertIn(("POST", "/plugins/cli-anything/evaluate-harness"), routes)
        self.assertIn(("GET", "/protocols/check"), routes)
        self.assertIn(("GET", "/protocols/workflows"), routes)
        self.assertIn(("GET", "/.well-known/agent-card.json"), routes)
        self.assertIn(("POST", "/a2a"), routes)
        self.assertIn(("GET", "/workflows"), routes)

    def test_post_bad_json_returns_structured_error(self):
        with daemon_url() as base_url:
            request = urllib.request.Request(
                f"{base_url}/call",
                data=b"{bad json",
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(request, timeout=5)

            self.assertEqual(raised.exception.code, 400)
            payload = json.loads(raised.exception.read().decode("utf-8"))
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["error_type"], "bad_request")
            self.assertEqual(payload["status"], 400)

    def test_options_returns_cors_headers(self):
        with daemon_url() as base_url:
            request = urllib.request.Request(
                f"{base_url}/call",
                method="OPTIONS",
                headers={"Origin": "http://127.0.0.1:5173"},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertTrue(payload["ok"])
                self.assertEqual(
                    response.headers["Access-Control-Allow-Origin"],
                    "http://127.0.0.1:5173",
                )
                self.assertEqual(response.headers["Access-Control-Allow-Methods"], "GET, POST, OPTIONS")
                self.assertEqual(response.headers["Access-Control-Allow-Headers"], "Content-Type")

    def test_disallowed_origin_is_rejected_before_route_handling(self):
        with daemon_url() as base_url:
            request = urllib.request.Request(
                f"{base_url}/call",
                data=b"{}",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Origin": "https://example.com",
                },
            )
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(request, timeout=5)

            self.assertEqual(raised.exception.code, 403)
            payload = json.loads(raised.exception.read().decode("utf-8"))
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["error_type"], "origin_denied")
            self.assertNotIn("Access-Control-Allow-Origin", raised.exception.headers)

    def test_localhost_origin_is_allowed(self):
        with daemon_url() as base_url:
            request = urllib.request.Request(
                f"{base_url}/health",
                method="GET",
                headers={"Origin": "http://localhost:3000"},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(payload["status"], "ok")
                self.assertEqual(
                    response.headers["Access-Control-Allow-Origin"],
                    "http://localhost:3000",
                )

    def test_protocol_check_route_returns_wire_gaps(self):
        with daemon_url() as base_url:
            with urllib.request.urlopen(
                f"{base_url}/protocols/check?target=mcp&capability_id=cli-anything.mermaid.set-diagram",
                timeout=5,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(payload["protocol"], "mcp")
                self.assertFalse(payload["wire_compatible"])
                self.assertTrue(
                    any(item["status"] == "missing" for item in payload["checks"])
                )

    def test_protocol_workflows_route_returns_descriptor_exports(self):
        with daemon_url() as base_url:
            with urllib.request.urlopen(
                f"{base_url}/protocols/workflows?target=mcp&path=workflows/cli-anything-macrocli-mermaid-routing.example.json",
                timeout=5,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(payload["protocol"], "mcp")
                self.assertEqual(payload["workflowTools"][0]["_meta"]["cbn"]["kind"], "WorkflowDescriptor")
                self.assertEqual(payload["workflowTools"][0]["_meta"]["cbn_workflow"]["task_count"], 3)

    def test_protocol_check_route_returns_workflow_evidence(self):
        with daemon_url() as base_url:
            with urllib.request.urlopen(
                f"{base_url}/protocols/check?target=all&path=workflows/artifact-id-routing.example.json",
                timeout=5,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                mcp = payload["checks"]["mcp"]
                self.assertEqual(mcp["scope"], "workflow")
                self.assertEqual(mcp["workflow_path"], "workflows/artifact-id-routing.example.json")
                self.assertTrue(
                    any("artifacts[0].artifact_id" in item["evidence"] for item in mcp["checks"])
                )

    def test_workflows_route_returns_catalog(self):
        with daemon_url() as base_url:
            with urllib.request.urlopen(f"{base_url}/workflows", timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertTrue(
                    any(
                        item["workflow_id"] == "example.cli-anything-macrocli-mermaid-routing"
                        and item["valid"]
                        for item in payload
                    )
                )

            with urllib.request.urlopen(
                f"{base_url}/workflows?path=workflows/cli-anything-macrocli-mermaid-routing.example.json",
                timeout=5,
            ) as response:
                descriptor = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(descriptor["task_count"], 3)
                self.assertEqual(descriptor["tasks"][0]["uses"], "cli-anything.macrocli.backends")

    def test_cli_anything_harness_route_returns_gated_install_plan(self):
        with daemon_url() as base_url:
            request = urllib.request.Request(
                f"{base_url}/plugins/cli-anything/harness",
                data=json.dumps({"action": "install", "harness_name": "gimp"}).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(payload["action"], "harness-install-gimp")
                self.assertIn("evaluate-harness", payload["notes"][0])

    def test_a2a_routes_return_agent_card_and_task(self):
        with daemon_url() as base_url:
            with urllib.request.urlopen(f"{base_url}/.well-known/agent-card.json", timeout=5) as response:
                card = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(card["supportedInterfaces"][0]["url"], f"{base_url}/a2a")

            request = urllib.request.Request(
                f"{base_url}/a2a",
                data=json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "daemon-a2a",
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
                ).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json", "A2A-Version": "0.3"},
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                rpc = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(rpc["result"]["status"]["state"], "completed")
                self.assertEqual(rpc["result"]["metadata"]["cbn"]["capability_id"], "git.version")


@contextmanager
def daemon_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), CbnRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
