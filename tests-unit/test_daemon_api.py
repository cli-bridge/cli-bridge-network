import json
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from api_server.server import CbnRequestHandler, ROUTE_SUMMARY


class DaemonApiTests(unittest.TestCase):
    def test_route_summary_exposes_cli_anything_evaluation(self):
        routes = {(route["method"], route["path"]) for route in ROUTE_SUMMARY}
        self.assertIn(("POST", "/plugins/cli-anything/evaluate-harness"), routes)
        self.assertIn(("POST", "/plugins/cli-anything/candidates"), routes)
        self.assertIn(("POST", "/plugins/cli-anything/probe-harness"), routes)
        self.assertIn(("POST", "/plugins/cli-anything/verify-harness"), routes)
        self.assertIn(("POST", "/plugins/cli-anything/live-verification"), routes)
        self.assertIn(("GET", "/plugins/cli-anything/provenance"), routes)
        self.assertIn(("GET", "/plugins/cli-anything/update-check"), routes)
        self.assertIn(("POST", "/plugins/gate"), routes)
        self.assertIn(("POST", "/plugins/check-update"), routes)
        self.assertIn(("GET", "/protocols/check"), routes)
        self.assertIn(("GET", "/protocols/matrix"), routes)
        self.assertIn(("GET", "/protocols/readiness"), routes)
        self.assertIn(("GET", "/protocols/workflows"), routes)
        self.assertIn(("GET", "/.well-known/agent-card.json"), routes)
        self.assertIn(("POST", "/a2a"), routes)
        self.assertIn(("GET", "/workflows"), routes)
        self.assertIn(("GET", "/runtime/transports"), routes)
        self.assertIn(("GET", "/messages/contract"), routes)
        self.assertIn(("GET", "/parsers/fixtures"), routes)
        self.assertIn(("POST", "/runtime/transports/gate"), routes)
        self.assertIn(("POST", "/runtime/transports/plan"), routes)
        self.assertIn(("POST", "/runtime/transports/install"), routes)

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

    def test_protocol_matrix_route_returns_capabilities_and_workflows(self):
        with daemon_url() as base_url:
            with urllib.request.urlopen(
                f"{base_url}/protocols/matrix?include_workflows=true",
                timeout=5,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertTrue(payload["ok"])
                self.assertTrue(payload["include_workflows"])
                self.assertGreaterEqual(payload["capability_count"], 1)
                self.assertGreaterEqual(payload["workflow_count"], 1)
                self.assertTrue(any(item["kind"] == "workflow" for item in payload["rows"]))

    def test_protocol_readiness_route_returns_bridge_and_protocol_gaps(self):
        with daemon_url() as base_url:
            with urllib.request.urlopen(
                f"{base_url}/protocols/readiness?workflow_path=workflows/artifact-id-routing.example.json",
                timeout=5,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(payload["kind"], "ProtocolReadinessReport")
                self.assertEqual(payload["scope"], "workflow")
                self.assertTrue(payload["readiness"]["internal_bridge_ready"])
                self.assertFalse(payload["readiness"]["external_protocol_wire_compatible"])
                self.assertEqual(payload["summary"]["route_count"], 1)
                self.assertIn("mcp", payload["protocol_gaps"])

    def test_message_contract_route_returns_workflow_routes(self):
        with daemon_url() as base_url:
            with urllib.request.urlopen(
                f"{base_url}/messages/contract?workflow_path=workflows/artifact-id-routing.example.json",
                timeout=5,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["summary"]["artifact_route_count"], 1)
                self.assertEqual(payload["workflows"][0]["routes"][0]["selector"], "artifacts[0].artifact_id")

    def test_parser_fixtures_route_returns_verified_contracts(self):
        with daemon_url() as base_url:
            with urllib.request.urlopen(
                f"{base_url}/parsers/fixtures?parser_ref=cli-anything.raw",
                timeout=5,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["parser_ref"], "cli-anything.raw")
                self.assertEqual(payload["failed_case_count"], 0)
                self.assertIn(
                    "cli-anything.macrocli.launch",
                    payload["reports"][0]["verified_capabilities"],
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

    def test_cli_anything_candidates_route_accepts_compact_payload(self):
        class FakeHub:
            def candidate_harnesses(self, query=None, limit=50, with_probes=False, compact=False):
                return {
                    "ok": True,
                    "plugin_id": "cli-anything",
                    "query": query,
                    "limit": limit,
                    "with_probes": with_probes,
                    "compact": compact,
                    "market": {"stdout_omitted": compact},
                    "candidates": [],
                    "candidate_summary": [],
                }

        with patch("api_server.server.CliAnythingHub", FakeHub):
            with daemon_url() as base_url:
                request = urllib.request.Request(
                    f"{base_url}/plugins/cli-anything/candidates",
                    data=json.dumps(
                        {
                            "query": "image",
                            "limit": 2,
                            "with_probes": True,
                            "compact": True,
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(response.status, 200)
                    self.assertEqual(payload["query"], "image")
                    self.assertEqual(payload["limit"], 2)
                    self.assertTrue(payload["with_probes"])
                    self.assertTrue(payload["compact"])
                    self.assertTrue(payload["market"]["stdout_omitted"])

    def test_runtime_transport_status_and_plan_routes(self):
        with daemon_url() as base_url:
            with urllib.request.urlopen(f"{base_url}/runtime/transports?kind=pty", timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(payload["kind"], "pty")
                self.assertIn("ready", payload)

            request = urllib.request.Request(
                f"{base_url}/runtime/transports/plan",
                data=json.dumps({"kind": "pty"}).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(payload["plugin_id"], "runtime.pty")
                self.assertTrue(payload["requires_confirmation"])

    def test_runtime_transport_install_requires_confirmation(self):
        with daemon_url() as base_url:
            request = urllib.request.Request(
                f"{base_url}/runtime/transports/install",
                data=json.dumps({"kind": "pty"}).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(request, timeout=5)

            self.assertEqual(raised.exception.code, 403)
            payload = json.loads(raised.exception.read().decode("utf-8"))
            self.assertIn("confirmed=true", payload["error"])

    def test_plugin_execute_route_rejects_failed_operation_gate(self):
        class FakeManager:
            def operation_gate(self, plugin_id, action):
                return {
                    "ok": False,
                    "plugin_id": plugin_id,
                    "action": action,
                    "gated": True,
                    "blockers": ["preflight failed: external_plugins.writable"],
                    "override_flag": "--allow-failed-preflight",
                }

            def plan(self, *args, **kwargs):
                raise AssertionError("plan should not be built when gate blocks")

        with patch("api_server.server.PluginManager", FakeManager):
            with daemon_url() as base_url:
                request = urllib.request.Request(
                    f"{base_url}/plugins/execute",
                    data=json.dumps(
                        {
                            "plugin_id": "cli-anything",
                            "action": "install",
                            "confirmed": True,
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request, timeout=5)

                self.assertEqual(raised.exception.code, 409)
                payload = json.loads(raised.exception.read().decode("utf-8"))
                self.assertFalse(payload["ok"])
                self.assertIn("preflight failed: external_plugins.writable", payload["blockers"])

    def test_plugin_gate_route_returns_read_only_gate_report(self):
        with daemon_url() as base_url:
            request = urllib.request.Request(
                f"{base_url}/plugins/gate",
                data=json.dumps(
                    {
                        "plugin_id": "cli-anything",
                        "action": "install",
                    }
                ).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(payload["plugin_id"], "cli-anything")
                self.assertEqual(payload["action"], "install")
                self.assertTrue(payload["gated"])
                self.assertIn("preflight", payload)
                self.assertIn("provenance", payload)

    def test_cli_anything_provenance_route_returns_source_report(self):
        with daemon_url() as base_url:
            with urllib.request.urlopen(f"{base_url}/plugins/cli-anything/provenance", timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(payload["plugin_id"], "cli-anything")
                self.assertIn("repository", payload)
                self.assertIn("pip_packages", payload)
                self.assertIn("entrypoints", payload)

    def test_plugin_update_check_route_returns_read_only_report(self):
        with daemon_url() as base_url:
            request = urllib.request.Request(
                f"{base_url}/plugins/check-update",
                data=json.dumps({"plugin_id": "cli-anything"}).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            try:
                response = urllib.request.urlopen(request, timeout=5)
            except urllib.error.HTTPError as exc:
                self.assertEqual(exc.code, 409)
                payload = json.loads(exc.read().decode("utf-8"))
            else:
                with response:
                    self.assertEqual(response.status, 200)
                    payload = json.loads(response.read().decode("utf-8"))

            self.assertEqual(payload["plugin_id"], "cli-anything")
            self.assertIn("ready_for_update", payload)
            self.assertIn("repository", payload)
            self.assertFalse(payload["repository"]["remote_probe"]["requested"])

    def test_cli_anything_verify_harness_route_returns_protocol_plan(self):
        with daemon_url() as base_url:
            request = urllib.request.Request(
                f"{base_url}/plugins/cli-anything/verify-harness",
                data=json.dumps(
                    {
                        "harness_name": "mermaid",
                        "from_market": False,
                        "include_workflows": False,
                    }
                ).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(payload["plugin_id"], "cli-anything")
                self.assertEqual(payload["harness_name"], "mermaid")
                self.assertFalse(payload["include_workflows"])
                self.assertIn("protocols", payload)
                self.assertIn("verification_stages", payload)

    def test_cli_anything_live_verification_route_returns_snapshot(self):
        class FakeHub:
            def live_verification(
                self,
                harnesses=("mermaid", "macrocli"),
                candidate_query="image",
                candidate_limit=10,
                include_candidates=True,
                include_workflows=True,
            ):
                return {
                    "ok": True,
                    "plugin_id": "cli-anything",
                    "kind": "CliAnythingLiveVerification",
                    "harnesses": [{"harness_name": harnesses[0], "launch_ready": True}],
                    "candidate_scan": {"query": candidate_query, "selected_count": candidate_limit},
                    "workflow_readiness": {"internal_bridge_ready": include_workflows},
                    "summary": {"verified_harness_count": 1},
                }

        with patch("api_server.server.CliAnythingHub", FakeHub):
            with daemon_url() as base_url:
                request = urllib.request.Request(
                    f"{base_url}/plugins/cli-anything/live-verification",
                    data=json.dumps(
                        {
                            "harnesses": ["mermaid"],
                            "candidate_query": "image",
                            "candidate_limit": 2,
                            "include_candidates": True,
                            "include_workflows": True,
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(response.status, 200)
                    self.assertEqual(payload["kind"], "CliAnythingLiveVerification")
                    self.assertEqual(payload["harnesses"][0]["harness_name"], "mermaid")
                    self.assertEqual(payload["candidate_scan"]["selected_count"], 2)

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
