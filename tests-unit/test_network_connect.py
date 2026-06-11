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
        boundary = payload["contracts"]["external"]["package_boundary"]
        self.assertEqual(boundary["kind"], "ExternalProtocolPackageBoundary")
        self.assertEqual(boundary["npm_name"], "@agent-cli/contract")
        self.assertEqual(boundary["python_name"], "agent-cli-contract")
        self.assertTrue(boundary["dependency_boundary"]["standalone"])
        self.assertIn("api_server", boundary["dependency_boundary"]["forbidden_cbn_modules"])
        self.assertTrue(boundary["schemas"]["AgentCliCard"].replace("\\", "/").endswith("schemas/agent-cli-card.schema.json"))
        self.assertTrue(boundary["schemas"]["RunReceipt"].replace("\\", "/").endswith("schemas/run-receipt.schema.json"))
        self.assertTrue(boundary["typescript_types"].replace("\\", "/").endswith("ts/index.ts"))
        self.assertTrue(boundary["python_validator"].replace("\\", "/").endswith("python/agent_cli_contract/validator.py"))
        self.assertIn("conformance_smoke.py", boundary["conformance_smoke"]["script"])
        self.assertIn("ToolManifest", boundary["cbn_mapping_responsibility"]["AgentCliCard"])
        health = payload["contracts"]["external"]["package_health"]
        self.assertEqual(health["kind"], "AgentCliContractPackageHealth")
        self.assertTrue(health["ok"])
        self.assertEqual(health["metadata"]["npm_name"], "@agent-cli/contract")
        self.assertEqual(health["metadata"]["python_name"], "agent-cli-contract")
        self.assertTrue(health["independence"]["ok"])
        self.assertEqual(payload["summary"]["cli_anything_split_status"], "ready")
        cli_anything = payload["plugins"]["cli_anything"]
        self.assertEqual(cli_anything["plugin_id"], "cli-anything")
        self.assertEqual(cli_anything["module_split"]["kind"], "CliAnythingModuleSplitReport")
        self.assertEqual(cli_anything["module_split"]["status"], "ready")
        self.assertEqual(cli_anything["module_split"]["present_part_count"], 6)
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
        self.assertEqual(payload["summary"]["setup_status"], "ready_to_run")
        self.assertFalse(payload["summary"]["setup_required"])
        self.assertEqual(payload["summary"]["setup_user_gate_count"], 0)
        self.assertEqual(payload["summary"]["setup_secret_count"], 0)
        self.assertEqual(payload["summary"]["registration_importer_count"], 6)
        self.assertEqual(payload["summary"]["consumer_snippet_count"], 2)
        self.assertTrue(payload["summary"]["demo_ready"])
        self.assertEqual(payload["summary"]["demo_stage_count"], 7)
        self.assertEqual(payload["summary"]["demo_playbook_step_count"], 6)
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
        self.assertIn("--base-url http://127.0.0.1:8787", demo["next_commands"][2])
        self.assertIn("--session-token test-token", demo["next_commands"][2])
        playbook = payload["demo_playbook"]
        self.assertEqual(playbook["kind"], "KillerMvpDemoPlaybook")
        self.assertEqual(playbook["status"], "ready")
        self.assertEqual(playbook["step_count"], 6)
        self.assertEqual(playbook["steps"][0]["id"], "open_workflow_studio")
        self.assertEqual(playbook["steps"][1]["target"], "Connect")
        self.assertEqual(playbook["steps"][2]["target"], "Demo")
        self.assertEqual(playbook["steps"][3]["target"], "Daemon Verify")
        self.assertIn("--base-url http://127.0.0.1:8787", playbook["steps"][3]["command"])
        self.assertIn("--session-token test-token", playbook["steps"][3]["command"])
        self.assertEqual(playbook["steps"][5]["id"], "register_next_cli")
        self.assertIn("Registration surface", " ".join(playbook["success_criteria"]))
        entry_profile = payload["network_entry_profile"]
        self.assertEqual(entry_profile["kind"], "NetworkEntryProfile")
        self.assertEqual(entry_profile["status"], "ready")
        self.assertEqual(entry_profile["profile_id"], "cbn.network.entry.cli-cli-harness.v1")
        self.assertEqual(entry_profile["integration_mode"], "one_shot_package")
        self.assertEqual(entry_profile["compatibility"]["external_protocol"], "agent-cli-contract")
        self.assertEqual(entry_profile["compatibility"]["internal_bus"], "CBN BridgeMessage")
        self.assertIn("consumer_quickstart", entry_profile["compatibility"]["stable_fields"])
        self.assertIn("consumer_launch_contract", entry_profile["compatibility"]["stable_fields"])
        self.assertTrue(entry_profile["auth"]["session_token_included"])
        self.assertEqual(entry_profile["auth"]["required_headers"]["X-CBN-Session"], "test-token")
        self.assertEqual(entry_profile["primary_entrypoints"]["run_workflow"]["url"], "http://127.0.0.1:8787/workflows/run")
        self.assertIn("--session-token test-token", entry_profile["primary_entrypoints"]["verify_network"])
        self.assertEqual(entry_profile["harness_agent"]["kind"], "NaturalLanguageWorkflowHarness")
        self.assertEqual(entry_profile["harness_agent"]["request_binding"], "selected_workflow_path")
        self.assertEqual(entry_profile["harness_agent"]["bridge_message_channel"], "agent.workflow.request.plan")
        self.assertEqual(entry_profile["harness_agent"]["bridge_route_count"], 2)
        self.assertEqual(entry_profile["evidence"]["acceptance_check_count"], 11)
        self.assertEqual(entry_profile["evidence"]["demo_stage_count"], 7)
        self.assertIn("events", entry_profile["evidence"]["evidence_endpoints"])
        self.assertEqual(entry_profile["registration"]["importer_count"], 6)
        self.assertIn("cli-anything", entry_profile["registration"]["importer_ids"])
        self.assertEqual(entry_profile["protocol_facades"]["export_count"], 3)
        mvp = payload["mvp_readiness"]
        self.assertEqual(mvp["kind"], "KillerMvpReadiness")
        self.assertEqual(mvp["status"], "ready")
        self.assertEqual(mvp["score"], "12/12")
        self.assertEqual(payload["summary"]["mvp_readiness_status"], "ready")
        self.assertEqual(payload["summary"]["mvp_readiness_score"], "12/12")
        checks = {check["id"]: check for check in mvp["checks"]}
        self.assertTrue(checks["external_agent_cli_contract"]["ready"])
        self.assertTrue(checks["internal_bridge_contract"]["ready"])
        self.assertTrue(checks["natural_language_harness_agent"]["ready"])
        self.assertTrue(checks["network_entry_profile"]["ready"])
        self.assertTrue(checks["cli_registration_surface"]["ready"])
        self.assertTrue(checks["cli_anything_split"]["ready"])
        self.assertTrue(checks["setup_guidance"]["ready"])
        self.assertEqual(checks["killer_demo_playbook"]["evidence"]["stage_count"], 7)
        self.assertTrue(mvp["product_goals"]["show_cli_cli_protocol"])
        self.assertTrue(mvp["product_goals"]["run_reusable_harness_agent"])
        self.assertTrue(mvp["product_goals"]["integrate_next_cli"])
        self.assertTrue(mvp["product_goals"]["one_shot_external_network_entry"])
        self.assertEqual(mvp["recommended_next_action"], "open_workflow_studio_demo")
        presenter = payload["mvp_presenter_brief"]
        self.assertEqual(presenter["kind"], "KillerMvpPresenterBrief")
        self.assertEqual(presenter["status"], "ready")
        self.assertEqual(payload["summary"]["mvp_presenter_brief_status"], "ready")
        self.assertIn("BridgeMessage handoffs", presenter["headline"])
        self.assertEqual(presenter["decision_gates"]["mvp_readiness_score"], "12/12")
        self.assertEqual(presenter["decision_gates"]["setup_status"], "ready_to_run")
        self.assertEqual(presenter["integration_handoff"]["run_workflow_url"], "http://127.0.0.1:8787/workflows/run")
        self.assertIn("/network/connect-package?", presenter["integration_handoff"]["connect_package_url"])
        self.assertIn("/network/readiness?", presenter["integration_handoff"]["readiness_url"])
        self.assertIn("--output readiness", presenter["integration_handoff"]["readiness_command"])
        self.assertIn("--session-token test-token", presenter["integration_handoff"]["verify_command"])
        proof_points = {point["id"]: point for point in presenter["proof_points"]}
        self.assertEqual(proof_points["protocol_boundary"]["value"], "AgentCliCard + RunReceipt")
        self.assertEqual(proof_points["bridge_message_bus"]["value"], "2 BridgeMessage routes")
        self.assertIn("mcp", proof_points["protocol_facades"]["value"])
        self.assertEqual(presenter["live_demo_flow"][0]["id"], "open_workflow_studio")
        self.assertEqual(presenter["live_demo_flow"][2]["target"], "Demo")
        launch = payload["consumer_launch_contract"]
        self.assertEqual(launch["kind"], "ConsumerLaunchContract")
        self.assertEqual(launch["status"], "ready")
        self.assertEqual(launch["contract_id"], "cbn.consumer.launch.cli-cli-harness.v1")
        self.assertEqual(launch["audience"], "external_program")
        self.assertEqual(launch["profile_id"], entry_profile["profile_id"])
        self.assertTrue(launch["auth"]["session_token_required"])
        self.assertTrue(launch["auth"]["session_token_included"])
        self.assertFalse(launch["auth"]["secret_values_echoed"])
        self.assertEqual(launch["harness_agent"]["kind"], "NaturalLanguageWorkflowHarness")
        self.assertEqual(launch["harness_agent"]["bridge_route_count"], 2)
        self.assertEqual(launch["harness_agent"]["run_endpoint"], "http://127.0.0.1:8787/workflows/run")
        self.assertEqual(launch["success_gates"]["mvp_readiness_score"], "12/12")
        self.assertEqual(launch["success_gates"]["acceptance_check_count"], 11)
        self.assertEqual([step["request_id"] for step in launch["launch_sequence"]], launch["required_request_ids"])
        self.assertIn("plan_agent_request", launch["required_request_ids"])
        self.assertIn("run_workflow", launch["required_request_ids"])
        self.assertIn("artifacts", launch["required_request_ids"])
        self.assertIn("run_workflow", launch["available_request_ids"])
        self.assertIn("--session-token REDACTED", launch["entrypoints"]["verify_network"])
        self.assertIn("sessionToken=REDACTED", launch["entrypoints"]["open_studio"])
        self.assertNotIn("test-token", json.dumps(launch, ensure_ascii=False))
        self.assertTrue(any("Do not persist" in rule for rule in launch["do_not"]))
        self.assertEqual(payload["agent_workflow_request"]["kind"], "AdapterAgentWorkflowRequestPlan")
        self.assertEqual(payload["agent_workflow_request"]["reusable_harness"]["kind"], "NaturalLanguageWorkflowHarness")
        self.assertEqual(payload["agent_workflow_request"]["bridge_message_channel"], "agent.workflow.request.plan")
        self.assertEqual(payload["agent_workflow_request"]["request"]["binding"], "selected_workflow_path")
        self.assertTrue(payload["agent_workflow_request"]["request"]["intent"]["mentions_run"])
        self.assertEqual(payload["agent_workflow_request"]["run"]["http"]["method"], "POST")
        self.assertEqual(payload["agent_workflow_request"]["run"]["http"]["url"], "http://127.0.0.1:8787/workflows/run")
        self.assertEqual(
            payload["agent_workflow_request"]["run"]["http"]["json"]["path"].replace("\\", "/"),
            "workflows/cli-anything-macrocli-mermaid-routing.example.json",
        )
        self.assertEqual(payload["agent_workflow_request"]["bridge_route_count"], 2)
        self.assertEqual(len(payload["agent_workflow_request"]["bridge_routes"]), 2)
        self.assertEqual(payload["agent_workflow_request"]["bridge_routes"][0]["communication"], "BridgeMessage argsFrom")
        self.assertEqual(payload["agent_workflow_request"]["bridge_message"]["kind"], "BridgeMessage")
        self.assertEqual(payload["agent_workflow_request"]["bridge_message"]["parser_ref"], "cbn.agent.bridge_message")
        self.assertEqual(
            payload["agent_workflow_request"]["bridge_message"]["data"]["run_payload"]["path"].replace("\\", "/"),
            "workflows/cli-anything-macrocli-mermaid-routing.example.json",
        )
        self.assertIn("python -m cbn workflow run", payload["agent_workflow_request"]["next_commands"][2])
        setup = payload["setup_guidance"]
        self.assertEqual(setup["kind"], "AdapterAgentSetupGuidance")
        self.assertEqual(setup["status"], "ready_to_run")
        self.assertFalse(setup["setup_required"])
        self.assertEqual(setup["workflow_capability_count"], 3)
        self.assertEqual(setup["requires_user_count"], 0)
        self.assertFalse(setup["safety"]["executes_tools"])
        self.assertFalse(setup["safety"]["secret_values_included"])
        self.assertTrue(any(call["kind"] == "workflow-capability" for call in setup["tool_calls"]))
        self.assertNotIn("argv", setup["tool_calls"][0])
        registration = payload["registration_surface"]
        self.assertEqual(registration["kind"], "CliRegistrationSurface")
        self.assertEqual(registration["status"], "ready")
        self.assertEqual(registration["importer_count"], 6)
        self.assertTrue(registration["default_policy"]["dry_run_by_default"])
        self.assertTrue(registration["default_policy"]["writes_require_explicit_flag"])
        importer_ids = {importer["id"] for importer in registration["importers"]}
        self.assertEqual(
            importer_ids,
            {"command", "cli-anything", "agent-cli-card", "mcp", "skill", "parser-fixture"},
        )
        self.assertTrue(all(importer["default_side_effects"] == "none" for importer in registration["importers"]))
        self.assertEqual(registration["next_commands"][0], "python -m cbn import catalog")
        self.assertIn("python -m cbn import cli-anything --help", registration["next_commands"])
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
        self.assertEqual(payload["acceptance"]["check_count"], 11)
        self.assertIn("inspect_agent_nodes", payload["acceptance"]["required_request_ids"])
        self.assertIn("export_protocols", payload["acceptance"]["required_request_ids"])
        self.assertIn("import_catalog", payload["acceptance"]["required_request_ids"])
        self.assertIn("run_workflow", payload["acceptance"]["required_request_ids"])
        self.assertEqual(payload["acceptance"]["checks"][1]["request_id"], "import_catalog")
        self.assertEqual(payload["acceptance"]["checks"][1]["expect"]["json.kind"], "CliRegistrationSurface")
        self.assertEqual(payload["acceptance"]["checks"][4]["request_id"], "inspect_agent_nodes")
        self.assertEqual(payload["acceptance"]["checks"][4]["expect"]["json.kind"], "AdapterAgentNodeBundle")
        self.assertEqual(payload["acceptance"]["checks"][5]["request_id"], "export_protocols")
        self.assertEqual(payload["acceptance"]["checks"][5]["expect"]["json.exports.mcp.protocol"], "mcp")
        self.assertEqual(payload["acceptance"]["checks"][6]["request_id"], "plan_agent_request")
        self.assertEqual(
            payload["acceptance"]["checks"][6]["expect"]["json.reusable_harness.kind"],
            "NaturalLanguageWorkflowHarness",
        )
        self.assertEqual(payload["acceptance"]["checks"][8]["request_id"], "events")
        self.assertEqual(payload["acceptance"]["checks"][8]["expect"]["json.count_min"], 1)
        self.assertEqual(payload["acceptance"]["checks"][9]["request_id"], "audit")
        self.assertEqual(payload["acceptance"]["checks"][9]["expect"]["json.count_min"], 1)
        self.assertEqual(payload["acceptance"]["checks"][10]["request_id"], "artifacts")
        self.assertEqual(payload["acceptance"]["checks"][10]["expect"]["json.count_min"], 1)
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
        self.assertIn("import_catalog", quickstart["sequence"])
        self.assertIn("run_workflow", quickstart["sequence"])
        self.assertEqual(quickstart["sequence_steps"][0]["id"], "open_studio")
        self.assertEqual(quickstart["sequence_steps"][1]["request_id"], "import_catalog")
        self.assertEqual(quickstart["sequence_steps"][1]["method"], "GET")
        self.assertEqual(quickstart["sequence_steps"][1]["url"], "http://127.0.0.1:8787/imports/catalog")
        self.assertEqual(quickstart["sequence_steps"][-1]["id"], "read_evidence")
        self.assertEqual(quickstart["sequence_steps"][-1]["request_ids"], ["events", "audit", "artifacts"])
        requests_by_id = {request["id"]: request for request in quickstart["requests"]}
        self.assertEqual(requests_by_id["health"]["method"], "GET")
        self.assertEqual(requests_by_id["health"]["headers"]["X-CBN-Session"], "test-token")
        self.assertIn("curl -X GET", requests_by_id["health"]["curl"])
        self.assertIn("-H 'X-CBN-Session: test-token'", requests_by_id["health"]["curl"])
        self.assertEqual(requests_by_id["import_catalog"]["method"], "GET")
        self.assertEqual(requests_by_id["import_catalog"]["url"], "http://127.0.0.1:8787/imports/catalog")
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
        self.assertEqual(len(quickstart["requests"]), 11)
        self.assertTrue(quickstart["curl_script"].startswith("set -e\ncurl -X GET"))
        self.assertIn("curl -X GET 'http://127.0.0.1:8787/imports/catalog'", quickstart["curl_script"])
        self.assertIn("curl -X GET 'http://127.0.0.1:8787/protocols/workflows?", quickstart["curl_script"])
        self.assertIn("curl -X POST 'http://127.0.0.1:8787/workflows/run'", quickstart["curl_script"])
        self.assertTrue(quickstart["powershell_script"].startswith("$ErrorActionPreference = 'Stop'"))
        self.assertIn("'X-CBN-Session' = 'test-token'", quickstart["powershell_script"])
        self.assertIn("Invoke-RestMethod -Method 'POST'", quickstart["powershell_script"])
        snippets = {snippet["id"]: snippet for snippet in quickstart["sdk_snippets"]}
        self.assertEqual(set(snippets), {"python-stdlib-consumer", "typescript-fetch-consumer"})
        self.assertEqual(snippets["python-stdlib-consumer"]["language"], "python")
        self.assertEqual(snippets["python-stdlib-consumer"]["entrypoint"], "run_workflow")
        self.assertFalse(snippets["python-stdlib-consumer"]["safety"]["confirmed"])
        self.assertIn("import_catalog", snippets["python-stdlib-consumer"]["uses_request_ids"])
        self.assertIn("'import_catalog'", snippets["python-stdlib-consumer"]["code"])
        self.assertIn("'run_workflow'", snippets["python-stdlib-consumer"]["code"])
        self.assertIn("urllib.request", snippets["python-stdlib-consumer"]["code"])
        self.assertNotIn("true", snippets["python-stdlib-consumer"]["code"])
        self.assertIn("const requests", snippets["typescript-fetch-consumer"]["code"])
        self.assertIn("await call('import_catalog')", snippets["typescript-fetch-consumer"]["code"])
        self.assertIn("await call('run_workflow')", snippets["typescript-fetch-consumer"]["code"])
        endpoint_paths = {endpoint["path"] for endpoint in payload["daemon_endpoints"]}
        self.assertIn("/imports/catalog", endpoint_paths)
        self.assertIn("/network/quickstart", endpoint_paths)
        self.assertIn("/network/launch-contract", endpoint_paths)
        self.assertIn("/network/readiness", endpoint_paths)
        self.assertIn("/network/verify", endpoint_paths)
        self.assertIn("/adapter-agent/workflow-request-plan", endpoint_paths)
        self.assertTrue(any(endpoint["url"].startswith("http://127.0.0.1:8787/") for endpoint in payload["daemon_endpoints"]))
        self.assertIn("--base-url http://127.0.0.1:8787", payload["next_commands"][0])
        self.assertIn("--session-token test-token", payload["next_commands"][0])

    def test_network_connect_package_surfaces_auth_setup_guidance_without_secret_values(self):
        runtime = build_runtime()
        payload = network_connect_package(
            runtime.registry,
            workflow_path="workflows/auth-gated-first-run.example.json",
            base_url="http://127.0.0.1:8787",
        )

        setup = payload["setup_guidance"]
        self.assertEqual(setup["kind"], "AdapterAgentSetupGuidance")
        self.assertEqual(setup["status"], "waiting_on_setup")
        self.assertTrue(setup["setup_required"])
        self.assertEqual(setup["next_action"], "complete_user_setup")
        self.assertEqual(setup["secret_count"], 1)
        self.assertEqual(setup["setup_command_count"], 5)
        self.assertEqual(setup["workflow_capability_count"], 3)
        self.assertGreaterEqual(setup["requires_user_count"], 1)
        self.assertFalse(setup["safety"]["executes_tools"])
        self.assertFalse(setup["safety"]["secret_values_included"])
        self.assertTrue(setup["safety"]["secrets_must_not_be_pasted_in_chat"])
        self.assertTrue(any(call["kind"] == "setup-secret" for call in setup["tool_calls"]))
        self.assertTrue(any(call["secret_name"] == "OBSIDIAN_API_KEY" for call in setup["tool_calls"]))
        self.assertTrue(any(call["action"] == "login" for call in setup["tool_calls"]))
        self.assertIn("setup-execution", {checkpoint["id"] for checkpoint in setup["checkpoints"]})
        serialized = json.dumps(setup, ensure_ascii=False)
        self.assertNotIn("argv", serialized)
        self.assertNotIn("test-secret", serialized)
        self.assertEqual(payload["summary"]["setup_status"], "waiting_on_setup")
        self.assertTrue(payload["summary"]["setup_required"])
        self.assertEqual(payload["summary"]["setup_secret_count"], 1)

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
        self.assertEqual(payload["contracts"]["external"]["package_boundary"]["package_name"], "agent-cli-contract")
        self.assertTrue(payload["contracts"]["external"]["package_health"]["ok"])
        self.assertIn(
            "RunReceipt schema",
            payload["contracts"]["external"]["package_boundary"]["dependency_boundary"]["allowed_scope"],
        )
        self.assertEqual(payload["contracts"]["internal"]["contracts"]["artifact"]["kind"], "ArtifactRecord")
        self.assertEqual(payload["agent_workflow_request"]["run"]["http"]["url"], "http://127.0.0.1:8787/workflows/run")
        self.assertEqual(payload["agent_workflow_request"]["request"]["binding"], "selected_workflow_path")
        self.assertTrue(payload["agent_workflow_request"]["request"]["intent"]["mentions_run"])
        self.assertTrue(payload["agent_workflow_request"]["request"]["intent"]["mentions_reuse"])
        self.assertEqual(payload["agent_workflow_request"]["bridge_message"]["channel"], "agent.workflow.request.plan")
        self.assertEqual(len(payload["agent_workflow_request"]["bridge_routes"]), 2)
        self.assertEqual(payload["registration_surface"]["importer_count"], 6)
        self.assertEqual(payload["plugins"]["cli_anything"]["module_split"]["status"], "ready")
        self.assertIn("cbn import agent-cli-card", payload["registration_surface"]["importers"][2]["entrypoint"])
        self.assertEqual(payload["demo_playbook"]["steps"][3]["command"], payload["demo_playbook"]["next_commands"][0])
        self.assertIn("python -m cbn import command --help", payload["demo_playbook"]["next_commands"])
        self.assertEqual(payload["workflow_studio"]["daemon_url"], "http://127.0.0.1:8787")
        self.assertEqual(payload["workflow_studio"]["dashboard_url"], "http://127.0.0.1:5173")
        self.assertIn("dashboardUrl=http%3A%2F%2F127.0.0.1%3A5173", payload["workflow_studio"]["url"])
        self.assertEqual(payload["network_entry_profile"]["status"], "ready")
        self.assertEqual(payload["mvp_readiness"]["score"], "12/12")
        self.assertEqual(payload["network_entry_profile"]["primary_entrypoints"]["run_workflow"]["url"], "http://127.0.0.1:8787/workflows/run")
        self.assertEqual(payload["agent_node_bundle"]["cards"][0]["kind"], "AgentCard")
        self.assertEqual(payload["agent_node_bundle"]["harnesses"][0]["kind"], "AgentHarness")
        self.assertEqual(payload["consumer_quickstart"]["entrypoints"]["run_workflow"]["url"], "http://127.0.0.1:8787/workflows/run")
        self.assertEqual(payload["consumer_quickstart"]["sdk_snippets"][1]["language"], "typescript")
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
        self.assertEqual(payload["requests"][1]["id"], "import_catalog")
        self.assertEqual(payload["sequence_steps"][1]["request_id"], "import_catalog")
        self.assertEqual(payload["sequence_steps"][7]["request_id"], "run_workflow")
        self.assertEqual(payload["sequence_steps"][-1]["request_ids"], ["events", "audit", "artifacts"])
        self.assertEqual(payload["requests"][4]["id"], "inspect_agent_nodes")
        self.assertEqual(payload["requests"][5]["id"], "export_protocols")
        self.assertEqual(payload["requests"][7]["id"], "run_workflow")
        self.assertEqual(payload["requests"][7]["headers"]["X-CBN-Session"], "test-token")
        self.assertIn("curl -X POST", payload["requests"][7]["curl"])
        self.assertEqual(payload["acceptance"]["kind"], "NetworkConnectionAcceptance")
        self.assertEqual(payload["acceptance"]["check_count"], 11)
        self.assertEqual(payload["acceptance"]["checks"][1]["request_id"], "import_catalog")
        self.assertEqual(payload["acceptance"]["checks"][7]["request_id"], "run_workflow")
        self.assertEqual(len(payload["sdk_snippets"]), 2)
        self.assertEqual(payload["sdk_snippets"][0]["uses_request_ids"][0], "health")
        self.assertIn("import_catalog", payload["sdk_snippets"][0]["uses_request_ids"])
        self.assertIn("plan_agent_request", payload["sdk_snippets"][0]["uses_request_ids"])
        self.assertIn("curl -X GET 'http://127.0.0.1:8787/health'", payload["curl_script"])
        self.assertIn("curl -X GET 'http://127.0.0.1:8787/imports/catalog'", payload["curl_script"])
        self.assertIn("$Body_run_workflow", payload["powershell_script"])
        self.assertEqual(
            payload["entrypoints"]["run_workflow"]["json"]["path"],
            "workflows/cli-anything-macrocli-mermaid-routing.example.json",
        )
        self.assertIn("reusable CLI-CLI harness agent", payload["entrypoints"]["plan_agent_request"]["json"]["message"])
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
        self.assertEqual(payload["check_count"], 11)
        self.assertEqual(payload["checks"][0]["request_id"], "health")
        self.assertEqual(payload["checks"][1]["request_id"], "import_catalog")
        self.assertEqual(payload["checks"][1]["expect"]["json.kind"], "CliRegistrationSurface")
        self.assertEqual(payload["checks"][4]["request_id"], "inspect_agent_nodes")
        self.assertEqual(payload["checks"][4]["expect"]["json.kind"], "AdapterAgentNodeBundle")
        self.assertEqual(payload["checks"][5]["request_id"], "export_protocols")
        self.assertEqual(payload["checks"][5]["expect"]["json.exports.acp.protocol"], "acp")
        self.assertEqual(payload["checks"][6]["expect"]["json.kind"], "AdapterAgentWorkflowRequestPlan")
        self.assertNotIn("curl_script", payload)

    def test_network_quickstart_cli_outputs_mvp_readiness(self):
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
                "readiness",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["kind"], "KillerMvpReadiness")
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["score"], "12/12")
        self.assertEqual(payload["recommended_next_action"], "open_workflow_studio_demo")

    def test_network_quickstart_cli_outputs_launch_contract(self):
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
                "--session-token",
                "test-token",
                "--output",
                "launch-contract",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["kind"], "ConsumerLaunchContract")
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["contract_id"], "cbn.consumer.launch.cli-cli-harness.v1")
        self.assertEqual(payload["harness_agent"]["run_endpoint"], "http://127.0.0.1:8787/workflows/run")
        self.assertIn("run_workflow", payload["required_request_ids"])
        self.assertIn("--session-token REDACTED", payload["entrypoints"]["verify_network"])
        self.assertIn("sessionToken=REDACTED", payload["entrypoints"]["open_studio"])
        self.assertNotIn("test-token", json.dumps(payload, ensure_ascii=False))
        self.assertNotIn("consumer_quickstart", payload)

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
