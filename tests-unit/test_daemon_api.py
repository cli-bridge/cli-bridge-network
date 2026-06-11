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
        self.assertIn(("POST", "/plugins/cli-anything/verify-harness-plan"), routes)
        self.assertIn(("POST", "/plugins/cli-anything/promotion-gate"), routes)
        self.assertIn(("POST", "/plugins/cli-anything/live-verification"), routes)
        self.assertIn(("POST", "/plugins/cli-anything/mvp-plan"), routes)
        self.assertIn(("POST", "/plugins/cli-anything/bootstrap-plan"), routes)
        self.assertIn(("GET", "/plugins/cli-anything/provenance"), routes)
        self.assertIn(("GET", "/plugins/cli-anything/update-check"), routes)
        self.assertIn(("GET", "/plugins/operations"), routes)
        self.assertIn(("GET", "/plugins/operations/validate"), routes)
        self.assertIn(("POST", "/plugins/gate"), routes)
        self.assertIn(("POST", "/plugins/check-update"), routes)
        self.assertIn(("POST", "/plugins/operation-plan"), routes)
        self.assertIn(("POST", "/plugins/verify-plan"), routes)
        self.assertIn(("GET", "/protocols/check"), routes)
        self.assertIn(("GET", "/protocols/matrix"), routes)
        self.assertIn(("GET", "/protocols/readiness"), routes)
        self.assertIn(("GET", "/protocols/conformance-plan"), routes)
        self.assertIn(("GET", "/protocols/lifecycle-suite"), routes)
        self.assertIn(("GET", "/protocols/wire-conformance"), routes)
        self.assertIn(("GET", "/protocols/smoke-suite"), routes)
        self.assertIn(("GET", "/protocols/acceptance-queue"), routes)
        self.assertIn(("GET", "/protocols/bridge-lab"), routes)
        self.assertIn(("POST", "/protocols/acceptance-queue"), routes)
        self.assertIn(("POST", "/protocols/bridge-lab"), routes)
        self.assertIn(("GET", "/demo/killer"), routes)
        self.assertIn(("GET", "/network/connect-package"), routes)
        self.assertIn(("GET", "/network/quickstart"), routes)
        self.assertIn(("POST", "/demo/killer"), routes)
        self.assertIn(("GET", "/protocols/workflows"), routes)
        self.assertIn(("GET", "/.well-known/agent-card.json"), routes)
        self.assertIn(("POST", "/a2a"), routes)
        self.assertIn(("GET", "/workflows"), routes)
        self.assertIn(("GET", "/runtime/transports"), routes)
        self.assertIn(("GET", "/messages/contract"), routes)
        self.assertIn(("GET", "/parsers/fixtures"), routes)
        self.assertIn(("POST", "/adapter-agent/orchestrate"), routes)
        self.assertIn(("POST", "/adapter-agent/orchestrate-stream"), routes)
        self.assertIn(("GET", "/adapter-agent/node-bundle"), routes)
        self.assertIn(("POST", "/adapter-agent/workflow-request-plan"), routes)
        self.assertIn(("POST", "/adapter-agent/tool-call-plan"), routes)
        self.assertIn(("POST", "/adapter-agent/tool-use"), routes)
        self.assertIn(("POST", "/runtime/transports/gate"), routes)
        self.assertIn(("POST", "/runtime/transports/plan"), routes)
        self.assertIn(("POST", "/runtime/transports/install"), routes)

    def test_plugin_operations_route_returns_provider_catalog(self):
        with daemon_url() as base_url:
            with urllib.request.urlopen(
                f"{base_url}/plugins/operations?plugin_id=cli-anything",
                timeout=5,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))

            self.assertEqual(response.status, 200)
            self.assertEqual(payload["kind"], "PluginProviderOperationCatalog")
            self.assertEqual(payload["plugin_id"], "cli-anything")
            operation_ids = {operation["id"] for operation in payload["operations"]}
            self.assertIn("adaptation-queue", operation_ids)
            self.assertIn("repair-entrypoint", operation_ids)

    def test_plugin_operations_validate_route_returns_gate_report(self):
        with daemon_url() as base_url:
            with urllib.request.urlopen(
                f"{base_url}/plugins/operations/validate?plugin_id=cli-anything",
                timeout=5,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))

            self.assertEqual(response.status, 200)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["kind"], "PluginProviderOperationCatalogValidation")
            self.assertEqual(payload["summary"]["error_count"], 0)

    def test_killer_demo_route_returns_demo_report(self):
        with daemon_url() as base_url:
            request = urllib.request.Request(
                f"{base_url}/demo/killer",
                data=json.dumps({"run": True, "dry_run": True, "smoke_suite": False}).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(payload["kind"], "CbnKillerDemoReport")
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["summary"]["workflow_status"], "completed")
                self.assertEqual(payload["summary"]["route_count"], 2)

    def test_network_connect_package_route_returns_one_shot_contract(self):
        with daemon_url() as base_url:
            url = (
                f"{base_url}/network/connect-package"
                "?workflow_path=workflows/cli-anything-macrocli-mermaid-routing.example.json"
                "&studio_url=http://127.0.0.1:5177"
                "&session_token=demo-token"
            )
            with urllib.request.urlopen(url, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))

            self.assertEqual(response.status, 200)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["kind"], "NetworkConnectPackage")
            self.assertEqual(payload["contracts"]["external"]["protocol"], "agent-cli-contract")
            self.assertEqual(payload["contracts"]["external"]["accepted_kinds"], ["AgentCliCard", "RunReceipt"])
            self.assertEqual(payload["contracts"]["external"]["receipt_mapping"]["message_kind"], "BridgeMessage")
            self.assertGreaterEqual(payload["summary"]["bridge_route_count"], 1)
            self.assertIn("mcp", payload["protocols"]["targets"])
            self.assertEqual(payload["protocols"]["a2a"]["skill_count"], 1)
            self.assertEqual(payload["protocols"]["acp"]["workflow_count"], 1)
            self.assertEqual(payload["agent_node_bundle"]["bridge_message_channel"], "agent.adapter.node_bundle")
            self.assertEqual(payload["agent_workflow_request"]["bridge_message_channel"], "agent.workflow.request.plan")
            self.assertEqual(payload["agent_workflow_request"]["reusable_harness"]["kind"], "NaturalLanguageWorkflowHarness")
            self.assertEqual(payload["workflow_studio"]["kind"], "WorkflowStudioDemoLink")
            self.assertTrue(payload["workflow_studio"]["session_token_included"])
            self.assertIn("sessionToken=demo-token", payload["workflow_studio"]["url"])
            endpoint_paths = {endpoint["path"].split("?", 1)[0] for endpoint in payload["daemon_endpoints"]}
            self.assertIn("/workflows/run", endpoint_paths)
            self.assertIn("/adapter-agent/workflow-request-plan", endpoint_paths)
            self.assertIn("/demo/killer", endpoint_paths)

    def test_network_quickstart_route_returns_first_call_payload(self):
        with daemon_url() as base_url:
            url = (
                f"{base_url}/network/quickstart"
                "?workflow_path=workflows/cli-anything-macrocli-mermaid-routing.example.json"
                "&studio_url=http://127.0.0.1:5177"
            )
            request = urllib.request.Request(url, headers={"X-CBN-Session": "header-token"})
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))

            self.assertEqual(response.status, 200)
            self.assertEqual(payload["kind"], "NetworkConnectQuickstart")
            self.assertEqual(payload["required_headers"]["X-CBN-Session"], "header-token")
            self.assertEqual(payload["entrypoints"]["run_workflow"]["url"], f"{base_url}/workflows/run")
            self.assertEqual(payload["entrypoints"]["plan_agent_request"]["method"], "POST")
            self.assertEqual(payload["requests"][0]["id"], "health")
            self.assertEqual(payload["requests"][0]["headers"]["X-CBN-Session"], "header-token")
            self.assertIn("-H 'X-CBN-Session: header-token'", payload["requests"][0]["curl"])
            self.assertEqual(payload["requests"][4]["id"], "run_workflow")
            self.assertEqual(
                payload["requests"][4]["json"]["path"],
                "workflows/cli-anything-macrocli-mermaid-routing.example.json",
            )
            self.assertIn("--data", payload["requests"][4]["curl"])
            self.assertIn("curl -X POST", payload["curl_script"])
            self.assertIn("'X-CBN-Session' = 'header-token'", payload["powershell_script"])
            self.assertIn("Invoke-RestMethod -Method 'POST'", payload["powershell_script"])
            self.assertIn("sessionToken=header-token", payload["entrypoints"]["open_studio"])
            self.assertNotIn("contracts", payload)

    def test_adapter_agent_orchestrate_route_returns_auth_fallback(self):
        with daemon_url() as base_url:
            request = urllib.request.Request(
                f"{base_url}/adapter-agent/orchestrate",
                data=json.dumps(
                    {
                        "workflow_path": "workflows/auth-gated-first-run.example.json",
                        "message": "Initialize and guide login fallback.",
                        "use_glm": False,
                    }
                ).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))

            self.assertEqual(response.status, 200)
            self.assertEqual(payload["kind"], "AdapterAgentOrchestrationTurn")
            self.assertEqual(payload["status"], "requires_user_setup_and_inputs")
            setup_ids = {
                fallback["setup"]["setup_id"]
                for fallback in payload["auth_fallbacks"]
                if fallback.get("setup")
            }
            self.assertIn("jimeng-oauth-login", setup_ids)
            self.assertIn("obsidian-local-rest-api-key", setup_ids)
            self.assertTrue(any(route["task_id"] == "query-image-result" for route in payload["cli_routes"]))

    def test_adapter_agent_orchestrate_stream_returns_ndjson_plan_and_done(self):
        with daemon_url() as base_url:
            request = urllib.request.Request(
                f"{base_url}/adapter-agent/orchestrate-stream",
                data=json.dumps(
                    {
                        "workflow_path": "workflows/auth-gated-first-run.example.json",
                        "message": "Initialize and stream setup guidance.",
                        "use_glm": False,
                    }
                ).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                lines = [json.loads(line) for line in response.read().decode("utf-8").splitlines()]

            self.assertEqual(response.status, 200)
            self.assertEqual(lines[0]["type"], "plan")
            self.assertEqual(lines[0]["payload"]["kind"], "AdapterAgentOrchestrationTurn")
            self.assertTrue(any(event["type"] == "fallback" for event in lines))
            self.assertEqual(lines[-1]["type"], "done")

    def test_adapter_agent_tool_use_stores_session_secret_without_echo(self):
        with daemon_url() as base_url:
            request = urllib.request.Request(
                f"{base_url}/adapter-agent/tool-use",
                data=json.dumps(
                    {
                        "action": "store-secret",
                        "name": "OBSIDIAN_API_KEY",
                        "value": "test-only-secret",
                    }
                ).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                body = response.read().decode("utf-8")
                payload = json.loads(body)

            self.assertEqual(response.status, 200)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["stored"], "OBSIDIAN_API_KEY")
            self.assertNotIn("test-only-secret", body)

    def test_adapter_agent_tool_call_plan_route_returns_loop_contract(self):
        with daemon_url() as base_url:
            request = urllib.request.Request(
                f"{base_url}/adapter-agent/tool-call-plan",
                data=json.dumps(
                    {
                        "workflow_path": "workflows/auth-gated-first-run.example.json",
                        "message": "Initialize setup and plan tool calls.",
                    }
                ).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))

            self.assertEqual(response.status, 200)
            self.assertEqual(payload["kind"], "AdapterAgentToolCallPlan")
            self.assertEqual(payload["long_running_loop"]["kind"], "AdapterAgentLoopPlan")
            self.assertTrue(payload["execution_batches"])

    def test_adapter_agent_node_bundle_route_returns_agent_nodes(self):
        with daemon_url() as base_url:
            url = (
                f"{base_url}/adapter-agent/node-bundle"
                "?workflow_path=workflows/auth-gated-first-run.example.json"
                "&message=Initialize%20node%20bundle"
            )
            with urllib.request.urlopen(url, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))

            self.assertEqual(response.status, 200)
            self.assertEqual(payload["kind"], "AdapterAgentNodeBundle")
            self.assertEqual(payload["status"], "requires_user_setup_and_inputs")
            self.assertEqual(payload["session"]["kind"], "AgentSession")
            self.assertTrue(any(card["kind"] == "AgentCard" for card in payload["cards"]))
            self.assertTrue(any(node["agent"] == "orchestration-coordinator-agent" for node in payload["workflow_nodes"]))
            self.assertEqual(payload["bridge_message"]["kind"], "BridgeMessage")
            self.assertEqual(
                payload["bridge_message"]["metadata"]["channel"],
                "agent.adapter.node_bundle",
            )

    def test_adapter_agent_workflow_request_plan_route_returns_reusable_invocation(self):
        with daemon_url() as base_url:
            request = urllib.request.Request(
                f"{base_url}/adapter-agent/workflow-request-plan",
                data=json.dumps(
                    {
                        "workflow_path": "workflows/cli-anything-macrocli-mermaid-routing.example.json",
                        "message": "Run macrocli to mermaid as a reusable agent workflow.",
                        "dry_run": True,
                    }
                ).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))

            self.assertEqual(response.status, 200)
            self.assertEqual(payload["kind"], "AdapterAgentWorkflowRequestPlan")
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["summary"]["bridge_route_count"], 2)
            self.assertEqual(payload["run"]["http"]["url"], f"{base_url}/workflows/run")
            self.assertEqual(payload["reusable_harness"]["kind"], "NaturalLanguageWorkflowHarness")
            self.assertEqual(payload["bridge_message"]["metadata"]["channel"], "agent.workflow.request.plan")

    def test_plugin_operation_plan_route_resolves_descriptor(self):
        with daemon_url() as base_url:
            request = urllib.request.Request(
                f"{base_url}/plugins/operation-plan",
                data=json.dumps(
                    {
                        "plugin_id": "cli-anything",
                        "operation_id": "repair-entrypoint",
                        "inputs": {
                            "harness": "py4csr",
                            "module": "py4csr.tables.rtf_formatter",
                        },
                        "confirmed": True,
                    }
                ).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))

            self.assertEqual(response.status, 200)
            self.assertTrue(payload["dispatch_ready"])
            self.assertEqual(payload["required_inputs"], ["harness", "module"])
            self.assertEqual(payload["missing_inputs"], [])
            self.assertEqual(payload["api_request"]["path"], "/plugins/cli-anything/repair-entrypoint")
            self.assertTrue(payload["api_request"]["json"]["confirmed"])

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
                self.assertEqual(
                    response.headers["Access-Control-Allow-Headers"],
                    "Authorization, Content-Type, X-CBN-Session",
                )

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

    def test_post_requires_session_token_when_configured(self):
        with daemon_url(session_token="test-token") as base_url:
            request = urllib.request.Request(
                f"{base_url}/messages/validate",
                data=json.dumps({"message": _sample_message()}).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(request, timeout=5)

            self.assertEqual(raised.exception.code, 403)
            payload = json.loads(raised.exception.read().decode("utf-8"))
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["error_type"], "session_denied")

    def test_post_rejects_wrong_session_token_when_configured(self):
        with daemon_url(session_token="test-token") as base_url:
            request = urllib.request.Request(
                f"{base_url}/messages/validate",
                data=json.dumps({"message": _sample_message()}).encode("utf-8"),
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "X-CBN-Session": "wrong-token",
                },
            )
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(request, timeout=5)

            self.assertEqual(raised.exception.code, 403)
            payload = json.loads(raised.exception.read().decode("utf-8"))
            self.assertEqual(payload["error_type"], "session_denied")

    def test_post_accepts_x_cbn_session_token_when_configured(self):
        with daemon_url(session_token="test-token") as base_url:
            request = urllib.request.Request(
                f"{base_url}/messages/validate",
                data=json.dumps({"message": _sample_message()}).encode("utf-8"),
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "X-CBN-Session": "test-token",
                },
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertTrue(payload["valid"])

    def test_post_accepts_bearer_session_token_when_configured(self):
        with daemon_url(session_token="test-token") as base_url:
            request = urllib.request.Request(
                f"{base_url}/messages/validate",
                data=json.dumps({"message": _sample_message()}).encode("utf-8"),
                method="POST",
                headers={
                    "Authorization": "Bearer test-token",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertTrue(payload["valid"])

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
                self.assertTrue(payload["readiness"]["external_protocol_wire_compatible"])
                self.assertEqual(payload["summary"]["route_count"], 1)
                self.assertIn("mcp", payload["protocol_gaps"])

    def test_protocol_conformance_plan_route_returns_promotion_gates(self):
        with daemon_url() as base_url:
            with urllib.request.urlopen(
                f"{base_url}/protocols/conformance-plan?target=all&capability_id=git.version",
                timeout=5,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(payload["kind"], "ProtocolConformancePlan")
                self.assertFalse(payload["wire_compatible"])
                self.assertIn("mcp", payload["protocols"])
                self.assertGreater(payload["summary"]["missing_gate_count"], 0)

    def test_protocol_lifecycle_suite_route_returns_report(self):
        with daemon_url() as base_url:
            with urllib.request.urlopen(
                f"{base_url}/protocols/lifecycle-suite?capability_id=git.version&workflow_path=workflows/example.json",
                timeout=5,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(payload["kind"], "ProtocolLifecycleSuiteReport")
                self.assertTrue(payload["ok"])
                self.assertTrue(payload["wire_compatible"])
                self.assertEqual(payload["summary"]["failed_count"], 0)

    def test_protocol_wire_conformance_route_returns_report(self):
        with daemon_url() as base_url:
            with urllib.request.urlopen(
                f"{base_url}/protocols/wire-conformance?target=all&capability_id=git.version",
                timeout=5,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(payload["kind"], "ProtocolWireConformanceReport")
                self.assertTrue(payload["wire_compatible"])
                self.assertEqual(payload["summary"]["wire_compatible_protocol_count"], 3)

    def test_protocol_smoke_suite_route_returns_batch_gate(self):
        def fake_suite(
            registry,
            capability_ids=None,
            workflow_paths=None,
            extra_args=(),
            dry_run=False,
            workflow_dry_run=False,
            workflow_confirmed=False,
            include_payloads=False,
        ):
            return {
                "ok": True,
                "kind": "ProtocolSmokeSuiteReport",
                "capability_ids": list(capability_ids or []),
                "workflow_paths": list(workflow_paths or []),
                "dry_run": dry_run,
                "workflow_dry_run": workflow_dry_run,
                "workflow_confirmed": workflow_confirmed,
                "include_payloads": include_payloads,
                "extra_args": list(extra_args),
                "summary": {"check_count": 6, "failed_count": 0},
                "wire_compatible": True,
            }

        with patch("api_server.server.protocol_smoke_suite", fake_suite):
            with daemon_url() as base_url:
                with urllib.request.urlopen(
                    (
                        f"{base_url}/protocols/smoke-suite"
                        "?capability_id=git.version"
                        "&workflow_path=workflows/example.json"
                        "&workflow_dry_run=true"
                    ),
                    timeout=5,
                ) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(response.status, 200)
                    self.assertEqual(payload["kind"], "ProtocolSmokeSuiteReport")
                    self.assertEqual(payload["capability_ids"], ["git.version"])
                    self.assertEqual(payload["workflow_paths"], ["workflows/example.json"])
                    self.assertTrue(payload["workflow_dry_run"])
                    self.assertTrue(payload["wire_compatible"])

    def test_protocol_acceptance_queue_route_returns_matrix(self):
        with daemon_url() as base_url:
            request = urllib.request.Request(
                f"{base_url}/protocols/acceptance-queue",
                data=json.dumps(
                    {
                        "workflow_paths": ["workflows/message-routing.example.json"],
                        "run": True,
                        "dry_run": True,
                    }
                ).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(payload["kind"], "CliToCliAcceptanceQueue")
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["summary"]["workflow_count"], 1)
                self.assertEqual(payload["summary"]["runtime_route_failed_count"], 0)
                self.assertEqual(payload["rows"][0]["workflow_path"], "workflows/message-routing.example.json")

    def test_protocol_bridge_lab_route_returns_protocol_baseline(self):
        with daemon_url() as base_url:
            request = urllib.request.Request(
                f"{base_url}/protocols/bridge-lab",
                data=json.dumps(
                    {
                        "workflow_paths": ["workflows/message-routing.example.json"],
                        "run": True,
                        "dry_run": True,
                    }
                ).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(payload["kind"], "BridgeMessageProtocolLab")
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["summary"]["workflow_count"], 1)
                self.assertEqual(payload["summary"]["runtime_route_failed_count"], 0)
                self.assertTrue(payload["wire_compatible"])

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

    def test_cli_anything_install_queue_route_returns_read_only_queue(self):
        class FakeHub:
            def market_install_queue(self, query=None, limit=50, max_installs=10, include_blocked=True):
                return {
                    "ok": True,
                    "plugin_id": "cli-anything",
                    "kind": "CliAnythingMarketInstallQueue",
                    "query": query,
                    "limit": limit,
                    "max_installs": max_installs,
                    "include_blocked": include_blocked,
                    "summary": {"queued_count": 1, "blocked_count": 1},
                    "queue": [{"harness_name": "3mf"}],
                    "blocked": [{"harness_name": "blender"}],
                    "skipped": [],
                }

        with patch("api_server.server.CliAnythingHub", FakeHub):
            with daemon_url() as base_url:
                request = urllib.request.Request(
                    f"{base_url}/plugins/cli-anything/install-queue",
                    data=json.dumps(
                        {
                            "query": "file",
                            "limit": 20,
                            "max_installs": 3,
                            "include_blocked": False,
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(response.status, 200)
                    self.assertEqual(payload["query"], "file")
                    self.assertEqual(payload["limit"], 20)
                    self.assertEqual(payload["max_installs"], 3)
                    self.assertFalse(payload["include_blocked"])
                    self.assertEqual(payload["queue"][0]["harness_name"], "3mf")

    def test_cli_anything_blocked_plan_route_returns_decision_report(self):
        class FakeHub:
            def blocked_harness_plan(self, harnesses=(), query=None, limit=50):
                return {
                    "ok": True,
                    "plugin_id": "cli-anything",
                    "kind": "CliAnythingBlockedHarnessPlan",
                    "harnesses": list(harnesses),
                    "query": query,
                    "limit": limit,
                    "summary": {"blocked_count": 1},
                    "blocked": [{"harness_name": "n8n", "categories": ["external-network-or-risk"]}],
                }

        with patch("api_server.server.CliAnythingHub", FakeHub):
            with daemon_url() as base_url:
                request = urllib.request.Request(
                    f"{base_url}/plugins/cli-anything/blocked-plan",
                    data=json.dumps(
                        {
                            "harnesses": ["n8n"],
                            "query": "automation",
                            "limit": 20,
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(response.status, 200)
                    self.assertEqual(payload["harnesses"], ["n8n"])
                    self.assertEqual(payload["query"], "automation")
                    self.assertEqual(payload["limit"], 20)
                    self.assertEqual(payload["blocked"][0]["categories"], ["external-network-or-risk"])

    def test_cli_anything_repair_plan_route_returns_entrypoint_report(self):
        class FakeHub:
            def entrypoint_repair_plan(self, harness_name, from_market=True):
                return {
                    "ok": True,
                    "plugin_id": "cli-anything",
                    "kind": "CliAnythingEntrypointRepairPlan",
                    "harness_name": harness_name,
                    "from_market": from_market,
                    "diagnosis": {"state": "installed_entrypoint_missing"},
                }

        with patch("api_server.server.CliAnythingHub", FakeHub):
            with daemon_url() as base_url:
                request = urllib.request.Request(
                    f"{base_url}/plugins/cli-anything/repair-plan",
                    data=json.dumps(
                        {
                            "harness_name": "py4csr",
                            "from_market": True,
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(response.status, 200)
                    self.assertEqual(payload["harness_name"], "py4csr")
                    self.assertTrue(payload["from_market"])
                    self.assertEqual(payload["diagnosis"]["state"], "installed_entrypoint_missing")

    def test_cli_anything_repair_entrypoint_route_returns_execution_report(self):
        class FakeHub:
            def repair_entrypoint(
                self,
                harness_name,
                from_market=True,
                module=None,
                write=False,
                confirmed=False,
                require_smoke=False,
                smoke_args=("--help",),
                smoke_timeout_seconds=10,
            ):
                return {
                    "ok": True,
                    "plugin_id": "cli-anything",
                    "kind": "CliAnythingEntrypointRepair",
                    "harness_name": harness_name,
                    "from_market": from_market,
                    "module": module,
                    "write": write,
                    "confirmed": confirmed,
                    "require_smoke": require_smoke,
                    "smoke_args": list(smoke_args),
                    "smoke_timeout_seconds": smoke_timeout_seconds,
                    "strategy": {"state": "python_module_wrapper"},
                    "execution": {"status": "completed" if confirmed else "requires_confirmation"},
                }

        with patch("api_server.server.CliAnythingHub", FakeHub):
            with daemon_url() as base_url:
                request = urllib.request.Request(
                    f"{base_url}/plugins/cli-anything/repair-entrypoint",
                    data=json.dumps(
                        {
                            "harness_name": "py4csr",
                            "from_market": True,
                            "module": "pip",
                            "write": True,
                            "confirmed": True,
                            "require_smoke": True,
                            "smoke_args": ["--help"],
                            "smoke_timeout_seconds": 11,
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(response.status, 200)
                    self.assertEqual(payload["harness_name"], "py4csr")
                    self.assertEqual(payload["module"], "pip")
                    self.assertTrue(payload["write"])
                    self.assertTrue(payload["confirmed"])
                    self.assertTrue(payload["require_smoke"])
                    self.assertEqual(payload["smoke_args"], ["--help"])
                    self.assertEqual(payload["smoke_timeout_seconds"], 11)
                    self.assertEqual(payload["execution"]["status"], "completed")

    def test_cli_anything_repair_entrypoint_route_rejects_unconfirmed_write(self):
        class FakeHub:
            def repair_entrypoint(self, *args, **kwargs):
                raise AssertionError("repair_entrypoint should not run without confirmation")

        with patch("api_server.server.CliAnythingHub", FakeHub):
            with daemon_url() as base_url:
                request = urllib.request.Request(
                    f"{base_url}/plugins/cli-anything/repair-entrypoint",
                    data=json.dumps(
                        {
                            "harness_name": "py4csr",
                            "module": "pip",
                            "write": True,
                            "confirmed": False,
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request, timeout=5)
                self.assertEqual(raised.exception.code, 403)
                payload = json.loads(raised.exception.read().decode("utf-8"))
                self.assertEqual(payload["error_type"], "confirmation_required")

    def test_cli_anything_promotion_gate_route_returns_overlay_report(self):
        class FakeHub:
            def promotion_gate(
                self,
                harness_name,
                title=None,
                from_market=True,
                include_workflows=True,
                run_smoke_suite=False,
                smoke_extra_args=(),
            ):
                return {
                    "ok": True,
                    "plugin_id": "cli-anything",
                    "kind": "CliAnythingOverlayPromotionGate",
                    "harness_name": harness_name,
                    "title": title,
                    "from_market": from_market,
                    "include_workflows": include_workflows,
                    "run_smoke_suite": run_smoke_suite,
                    "smoke_extra_args": list(smoke_extra_args),
                    "ready_for_promotion": False,
                    "promotion_blockers": ["parser output contract is not verified in the manifest"],
                }

        with patch("api_server.server.CliAnythingHub", FakeHub):
            with daemon_url() as base_url:
                request = urllib.request.Request(
                    f"{base_url}/plugins/cli-anything/promotion-gate",
                    data=json.dumps(
                        {
                            "harness_name": "py4csr",
                            "title": "Py4CSR",
                            "from_market": True,
                            "include_workflows": False,
                            "run_smoke_suite": True,
                            "smoke_extra_args": ["--help"],
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(response.status, 200)
                    self.assertEqual(payload["harness_name"], "py4csr")
                    self.assertEqual(payload["title"], "Py4CSR")
                    self.assertFalse(payload["include_workflows"])
                    self.assertTrue(payload["run_smoke_suite"])
                    self.assertEqual(payload["smoke_extra_args"], ["--help"])
                    self.assertFalse(payload["ready_for_promotion"])

    def test_cli_anything_adapter_targets_route_returns_candidate_report(self):
        class FakeHub:
            def adapter_targets(self, harness_name, from_market=True, package=None, limit=20):
                return {
                    "ok": True,
                    "plugin_id": "cli-anything",
                    "kind": "CliAnythingAdapterTargets",
                    "harness_name": harness_name,
                    "from_market": from_market,
                    "package": package,
                    "limit": limit,
                    "summary": {"target_count": 1},
                    "targets": [{"module": "samplecli.runner"}],
                }

        with patch("api_server.server.CliAnythingHub", FakeHub):
            with daemon_url() as base_url:
                request = urllib.request.Request(
                    f"{base_url}/plugins/cli-anything/adapter-targets",
                    data=json.dumps(
                        {
                            "harness_name": "py4csr",
                            "from_market": True,
                            "package": "py4csr",
                            "limit": 10,
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(response.status, 200)
                    self.assertEqual(payload["harness_name"], "py4csr")
                    self.assertEqual(payload["package"], "py4csr")
                    self.assertEqual(payload["limit"], 10)
                    self.assertEqual(payload["targets"][0]["module"], "samplecli.runner")

    def test_cli_anything_adapter_smoke_route_returns_execution_report(self):
        class FakeHub:
            def adapter_target_smoke(
                self,
                harness_name,
                module,
                from_market=True,
                smoke_args=("--help",),
                timeout_seconds=10,
                run=False,
                confirmed=False,
            ):
                return {
                    "ok": True,
                    "plugin_id": "cli-anything",
                    "kind": "CliAnythingAdapterTargetSmoke",
                    "harness_name": harness_name,
                    "module": module,
                    "from_market": from_market,
                    "smoke_args": list(smoke_args),
                    "timeout_seconds": timeout_seconds,
                    "run": run,
                    "confirmed": confirmed,
                    "execution": {"status": "completed" if run and confirmed else "not_run"},
                }

        with patch("api_server.server.CliAnythingHub", FakeHub):
            with daemon_url() as base_url:
                request = urllib.request.Request(
                    f"{base_url}/plugins/cli-anything/adapter-smoke",
                    data=json.dumps(
                        {
                            "harness_name": "py4csr",
                            "from_market": True,
                            "module": "py4csr.plotting.sas_compatible_rtf_generator",
                            "smoke_args": ["--help"],
                            "timeout_seconds": 10,
                            "run": True,
                            "confirmed": True,
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(response.status, 200)
                    self.assertEqual(payload["harness_name"], "py4csr")
                    self.assertEqual(payload["module"], "py4csr.plotting.sas_compatible_rtf_generator")
                    self.assertEqual(payload["smoke_args"], ["--help"])
                    self.assertTrue(payload["run"])
                    self.assertTrue(payload["confirmed"])
                    self.assertEqual(payload["execution"]["status"], "completed")

    def test_cli_anything_adapter_smoke_route_rejects_unconfirmed_run(self):
        class FakeHub:
            def adapter_target_smoke(self, *args, **kwargs):
                raise AssertionError("adapter smoke should not run without confirmation")

        with patch("api_server.server.CliAnythingHub", FakeHub):
            with daemon_url() as base_url:
                request = urllib.request.Request(
                    f"{base_url}/plugins/cli-anything/adapter-smoke",
                    data=json.dumps(
                        {
                            "harness_name": "py4csr",
                            "module": "py4csr.plotting.sas_compatible_rtf_generator",
                            "run": True,
                            "confirmed": False,
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request, timeout=5)
                self.assertEqual(raised.exception.code, 403)
                payload = json.loads(raised.exception.read().decode("utf-8"))
                self.assertEqual(payload["error_type"], "confirmation_required")

    def test_cli_anything_adaptation_gate_route_returns_acceptance_report(self):
        class FakeHub:
            def adaptation_gate(
                self,
                harness_name,
                from_market=True,
                module=None,
                require_smoke=True,
                run_smoke=False,
                confirmed=False,
                smoke_args=("--help",),
                smoke_timeout_seconds=10,
            ):
                return {
                    "ok": True,
                    "plugin_id": "cli-anything",
                    "kind": "CliAnythingHarnessAdaptationGate",
                    "harness_name": harness_name,
                    "from_market": from_market,
                    "module": module,
                    "require_smoke": require_smoke,
                    "run_smoke": run_smoke,
                    "confirmed": confirmed,
                    "smoke_args": list(smoke_args),
                    "smoke_timeout_seconds": smoke_timeout_seconds,
                    "summary": {"ready_for_repair_write": False},
                    "stages": [{"id": "adapter_smoke", "status": "ready"}],
                }

        with patch("api_server.server.CliAnythingHub", FakeHub):
            with daemon_url() as base_url:
                request = urllib.request.Request(
                    f"{base_url}/plugins/cli-anything/adaptation-gate",
                    data=json.dumps(
                        {
                            "harness_name": "py4csr",
                            "from_market": True,
                            "module": "py4csr.tables.rtf_formatter",
                            "require_smoke": True,
                            "run_smoke": False,
                            "confirmed": False,
                            "smoke_args": ["--help"],
                            "smoke_timeout_seconds": 10,
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(response.status, 200)
                    self.assertEqual(payload["harness_name"], "py4csr")
                    self.assertEqual(payload["module"], "py4csr.tables.rtf_formatter")
                    self.assertTrue(payload["require_smoke"])
                    self.assertFalse(payload["run_smoke"])
                    self.assertEqual(payload["stages"][0]["id"], "adapter_smoke")

    def test_cli_anything_adaptation_gate_route_rejects_unconfirmed_smoke_run(self):
        class FakeHub:
            def adaptation_gate(self, *args, **kwargs):
                raise AssertionError("adaptation gate should not run smoke without confirmation")

        with patch("api_server.server.CliAnythingHub", FakeHub):
            with daemon_url() as base_url:
                request = urllib.request.Request(
                    f"{base_url}/plugins/cli-anything/adaptation-gate",
                    data=json.dumps(
                        {
                            "harness_name": "py4csr",
                            "module": "py4csr.tables.rtf_formatter",
                            "run_smoke": True,
                            "confirmed": False,
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request, timeout=5)
                self.assertEqual(raised.exception.code, 403)
                payload = json.loads(raised.exception.read().decode("utf-8"))
                self.assertEqual(payload["error_type"], "confirmation_required")

    def test_cli_anything_adaptation_gate_route_reports_missing_harness_as_bad_request(self):
        class FakeHub:
            def adaptation_gate(self, *args, **kwargs):
                raise AssertionError("adaptation gate should not run with invalid request body")

        with patch("api_server.server.CliAnythingHub", FakeHub):
            with daemon_url() as base_url:
                request = urllib.request.Request(
                    f"{base_url}/plugins/cli-anything/adaptation-gate",
                    data=json.dumps({"module": "py4csr.tables.rtf_formatter"}).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request, timeout=5)
                self.assertEqual(raised.exception.code, 400)
                payload = json.loads(raised.exception.read().decode("utf-8"))
                self.assertEqual(payload["error_type"], "bad_request")
                self.assertIn("harness_name", payload["error"])

    def test_cli_anything_adaptation_queue_route_returns_batch_report(self):
        class FakeHub:
            def adaptation_queue(
                self,
                harnesses=(),
                query=None,
                limit=20,
                max_harnesses=5,
                include_blocked=True,
                require_smoke=True,
                run_smoke=False,
                confirmed=False,
                smoke_args=("--help",),
                smoke_timeout_seconds=10,
            ):
                return {
                    "ok": True,
                    "plugin_id": "cli-anything",
                    "kind": "CliAnythingHarnessAdaptationQueue",
                    "harnesses": list(harnesses),
                    "query": query,
                    "limit": limit,
                    "max_harnesses": max_harnesses,
                    "include_blocked": include_blocked,
                    "require_smoke": require_smoke,
                    "run_smoke": run_smoke,
                    "confirmed": confirmed,
                    "smoke_args": list(smoke_args),
                    "smoke_timeout_seconds": smoke_timeout_seconds,
                    "summary": {"harness_count": len(harnesses)},
                    "gates": [],
                }

        with patch("api_server.server.CliAnythingHub", FakeHub):
            with daemon_url() as base_url:
                request = urllib.request.Request(
                    f"{base_url}/plugins/cli-anything/adaptation-queue",
                    data=json.dumps(
                        {
                            "harnesses": ["py4csr", "3mf"],
                            "query": "file",
                            "limit": 20,
                            "max_harnesses": 2,
                            "include_blocked": True,
                            "require_smoke": True,
                            "run_smoke": False,
                            "confirmed": False,
                            "smoke_args": ["--help"],
                            "smoke_timeout_seconds": 10,
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(response.status, 200)
                    self.assertEqual(payload["harnesses"], ["py4csr", "3mf"])
                    self.assertEqual(payload["query"], "file")
                    self.assertEqual(payload["max_harnesses"], 2)
                    self.assertEqual(payload["summary"]["harness_count"], 2)

    def test_cli_anything_adaptation_queue_route_rejects_unconfirmed_smoke_run(self):
        class FakeHub:
            def adaptation_queue(self, *args, **kwargs):
                raise AssertionError("adaptation queue should not run smoke without confirmation")

        with patch("api_server.server.CliAnythingHub", FakeHub):
            with daemon_url() as base_url:
                request = urllib.request.Request(
                    f"{base_url}/plugins/cli-anything/adaptation-queue",
                    data=json.dumps(
                        {
                            "harnesses": ["py4csr"],
                            "run_smoke": True,
                            "confirmed": False,
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request, timeout=5)
                self.assertEqual(raised.exception.code, 403)
                payload = json.loads(raised.exception.read().decode("utf-8"))
                self.assertEqual(payload["error_type"], "confirmation_required")

    def test_cli_anything_adaptation_queue_route_rejects_market_smoke_with_blocked_entries(self):
        class FakeHub:
            def adaptation_queue(self, *args, **kwargs):
                raise AssertionError("adaptation queue should not auto-run blocked market entries")

        with patch("api_server.server.CliAnythingHub", FakeHub):
            with daemon_url() as base_url:
                request = urllib.request.Request(
                    f"{base_url}/plugins/cli-anything/adaptation-queue",
                    data=json.dumps(
                        {
                            "query": "file",
                            "harnesses": [],
                            "include_blocked": True,
                            "run_smoke": True,
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
                self.assertEqual(payload["error_type"], "blocked")

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

    def test_protocol_accept_workflow_route_returns_runtime_evidence(self):
        with daemon_url() as base_url:
            request = urllib.request.Request(
                f"{base_url}/protocols/accept-workflow",
                data=json.dumps(
                    {
                        "workflow_path": "workflows/message-routing.example.json",
                        "run": True,
                        "dry_run": True,
                    }
                ).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(payload["kind"], "CliToCliWorkflowAcceptance")
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["summary"]["runtime_route_count"], 1)
                self.assertTrue(payload["runtime_routes"][0]["matched"])

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

    def test_plugin_verify_plan_route_returns_preview_report(self):
        with daemon_url() as base_url:
            request = urllib.request.Request(
                f"{base_url}/plugins/verify-plan",
                data=json.dumps({"plugin_id": "cli-anything", "action": "install"}).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))

            self.assertEqual(response.status, 200)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["kind"], "PluginPlanVerificationReport")
            self.assertFalse(payload["run"])
            self.assertTrue(payload["ready_to_run"])

    def test_cli_anything_verify_harness_plan_route_returns_preview_report(self):
        with daemon_url() as base_url:
            request = urllib.request.Request(
                f"{base_url}/plugins/cli-anything/verify-harness-plan",
                data=json.dumps(
                    {
                        "action": "install",
                        "harness_name": "mermaid",
                    }
                ).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))

            self.assertEqual(response.status, 200)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["kind"], "CliAnythingHarnessPlanVerificationReport")
            self.assertEqual(payload["harness_name"], "mermaid")
            self.assertFalse(payload["run"])
            self.assertTrue(payload["ready_to_run"])

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
                self.assertFalse(payload["protocol_smoke_suite"]["run"])

    def test_cli_anything_verify_harness_route_accepts_smoke_suite_payload(self):
        class FakeHub:
            def verify_harness(
                self,
                harness_name,
                title=None,
                from_market=True,
                include_workflows=True,
                run_smoke_suite=False,
                smoke_extra_args=(),
            ):
                return {
                    "ok": True,
                    "plugin_id": "cli-anything",
                    "harness_name": harness_name,
                    "from_market": from_market,
                    "include_workflows": include_workflows,
                    "run_smoke_suite": run_smoke_suite,
                    "smoke_extra_args": list(smoke_extra_args),
                    "protocol_smoke_suite": {
                        "run": run_smoke_suite,
                        "ok": True,
                        "command": "python -m cbn protocol smoke-suite",
                    },
                    "protocols": {},
                    "verification_stages": [],
                }

        with patch("api_server.server.CliAnythingHub", FakeHub):
            with daemon_url() as base_url:
                request = urllib.request.Request(
                    f"{base_url}/plugins/cli-anything/verify-harness",
                    data=json.dumps(
                        {
                            "harness_name": "3mf",
                            "include_workflows": False,
                            "run_smoke_suite": True,
                            "smoke_extra_args": ["--help"],
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(response.status, 200)
                    self.assertTrue(payload["run_smoke_suite"])
                    self.assertEqual(payload["smoke_extra_args"], ["--help"])
                    self.assertTrue(payload["protocol_smoke_suite"]["run"])

    def test_cli_anything_onboard_harness_route_returns_onboarding_report(self):
        class FakeHub:
            def onboard_harness(
                self,
                harness_name,
                title=None,
                from_market=True,
                write=False,
                confirmed=False,
                install=False,
                allow_blocked=False,
                include_workflows=True,
                run_smoke_suite=False,
                smoke_extra_args=(),
                operation_runner=None,
            ):
                return {
                    "ok": True,
                    "plugin_id": "cli-anything",
                    "kind": "CliAnythingHarnessOnboarding",
                    "harness_name": harness_name,
                    "title": title,
                    "from_market": from_market,
                    "write": write,
                    "confirmed": confirmed,
                    "install": install,
                    "allow_blocked": allow_blocked,
                    "runner_available": operation_runner is not None,
                    "include_workflows": include_workflows,
                    "run_smoke_suite": run_smoke_suite,
                    "smoke_extra_args": list(smoke_extra_args),
                    "summary": {"ready_for_manifest_write": True},
                    "stage_results": [{"id": "evaluate", "status": "completed"}],
                }

        with patch("api_server.server.CliAnythingHub", FakeHub):
            with daemon_url() as base_url:
                request = urllib.request.Request(
                    f"{base_url}/plugins/cli-anything/onboard-harness",
                    data=json.dumps(
                        {
                            "harness_name": "3mf",
                            "title": "3MF Harness",
                            "from_market": True,
                            "write": True,
                            "confirmed": True,
                            "install": True,
                            "allow_blocked": True,
                            "include_workflows": False,
                            "run_smoke_suite": True,
                            "smoke_extra_args": ["--help"],
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(response.status, 200)
                    self.assertEqual(payload["kind"], "CliAnythingHarnessOnboarding")
                    self.assertEqual(payload["harness_name"], "3mf")
                    self.assertTrue(payload["write"])
                    self.assertTrue(payload["confirmed"])
                    self.assertTrue(payload["install"])
                    self.assertTrue(payload["allow_blocked"])
                    self.assertTrue(payload["runner_available"])
                    self.assertFalse(payload["include_workflows"])
                    self.assertTrue(payload["run_smoke_suite"])
                    self.assertEqual(payload["smoke_extra_args"], ["--help"])

    def test_cli_anything_live_verification_route_returns_snapshot(self):
        class FakeHub:
            def live_verification(
                self,
                harnesses=("mermaid", "macrocli"),
                candidate_query="image",
                candidate_limit=10,
                include_candidates=True,
                include_workflows=True,
                run_smoke_suite=False,
                smoke_extra_args=(),
            ):
                return {
                    "ok": True,
                    "plugin_id": "cli-anything",
                    "kind": "CliAnythingLiveVerification",
                    "run_smoke_suite": run_smoke_suite,
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

    def test_cli_anything_mvp_plan_route_returns_control_plan(self):
        class FakeHub:
            def mvp_plan(
                self,
                query="file",
                limit=20,
                max_harnesses=5,
                include_blocked=True,
                workflow_paths=(),
                max_workflows=10,
                registry=None,
                workflow_runner=None,
            ):
                return {
                    "ok": True,
                    "plugin_id": "cli-anything",
                    "kind": "CliAnythingMvpPlan",
                    "query": query,
                    "limit": limit,
                    "max_harnesses": max_harnesses,
                    "include_blocked": include_blocked,
                    "workflow_paths": list(workflow_paths),
                    "max_workflows": max_workflows,
                    "summary": {"recommended_next_action": "install_next_market_harness"},
                    "stages": [{"id": "install_market_harnesses", "ready": True}],
                }

        with patch("api_server.server.CliAnythingHub", FakeHub):
            with daemon_url() as base_url:
                request = urllib.request.Request(
                    f"{base_url}/plugins/cli-anything/mvp-plan",
                    data=json.dumps(
                        {
                            "query": "file",
                            "limit": 12,
                            "max_harnesses": 3,
                            "include_blocked": False,
                            "workflow_paths": ["workflows/example.json"],
                            "max_workflows": 4,
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(response.status, 200)
                    self.assertEqual(payload["kind"], "CliAnythingMvpPlan")
                    self.assertEqual(payload["query"], "file")
                    self.assertEqual(payload["limit"], 12)
                    self.assertEqual(payload["max_harnesses"], 3)
                    self.assertFalse(payload["include_blocked"])
                    self.assertEqual(payload["workflow_paths"], ["workflows/example.json"])
                    self.assertEqual(payload["max_workflows"], 4)

    def test_cli_anything_bootstrap_plan_route_returns_runbook(self):
        class FakeHub:
            def bootstrap_plan(
                self,
                harness_name="mermaid",
                query="file",
                include_workflows=True,
                workflow_path="workflows/cli-anything-macrocli-mermaid-routing.example.json",
            ):
                return {
                    "ok": True,
                    "plugin_id": "cli-anything",
                    "kind": "CliAnythingBootstrapPlan",
                    "harness_name": harness_name,
                    "query": query,
                    "include_workflows": include_workflows,
                    "workflow_path": workflow_path,
                    "summary": {"recommended_next_action": "install_cli_anything_external_plugin"},
                    "stages": [{"id": "download_plugin", "status": "next"}],
                }

        with patch("api_server.server.CliAnythingHub", FakeHub):
            with daemon_url() as base_url:
                request = urllib.request.Request(
                    f"{base_url}/plugins/cli-anything/bootstrap-plan",
                    data=json.dumps(
                        {
                            "harness_name": "mermaid",
                            "query": "diagram",
                            "include_workflows": False,
                            "workflow_path": "workflows/example.json",
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(response.status, 200)
                    self.assertEqual(payload["kind"], "CliAnythingBootstrapPlan")
                    self.assertEqual(payload["harness_name"], "mermaid")
                    self.assertEqual(payload["query"], "diagram")
                    self.assertFalse(payload["include_workflows"])
                    self.assertEqual(payload["workflow_path"], "workflows/example.json")

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
                        "method": "SendMessage",
                        "params": {
                            "message": {
                                "messageId": "message-1",
                                "role": "ROLE_USER",
                                "parts": [{"text": "version"}],
                            },
                            "metadata": {"cbn": {"capability_id": "git.version"}},
                        },
                    }
                ).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json", "A2A-Version": "1.0.0"},
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                rpc = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(rpc["result"]["status"]["state"], "TASK_STATE_COMPLETED")
                self.assertEqual(rpc["result"]["metadata"]["cbn"]["capability_id"], "git.version")


def _sample_message():
    return {
        "apiVersion": "bridge.dev/v1alpha1",
        "kind": "BridgeMessage",
        "metadata": {
            "id": "message-1",
            "createdAt": "2026-06-10T00:00:00+0800",
            "producer": "test",
            "channel": "capability.output",
            "correlationId": "call-1",
        },
        "payload": {"parser_ref": "raw.text", "ok": True, "data": {"stdout": "ok"}},
        "artifacts": [],
    }


@contextmanager
def daemon_url(session_token=None):
    server = ThreadingHTTPServer(("127.0.0.1", 0), CbnRequestHandler)
    if session_token is not None:
        setattr(server, "session_token", session_token)
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
