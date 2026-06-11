"""Stable network connection specs shared by CBN demo package builders."""

from __future__ import annotations

CONNECT_API_VERSION = "bridge.dev/v1alpha1"
DEFAULT_AGENT_CONNECT_MESSAGE = "Run this workflow as a reusable CLI-CLI harness agent and connect an external program to CBN."

QUICKSTART_GET_REQUEST_IDS = (
    "health",
    "launch_contract",
    "entry_profile",
    "harness_agent",
    "sdk_bootstrap",
    "consumer_manifest",
    "import_catalog",
    "direct_cli_readiness",
    "inspect_workflow",
    "inspect_bridge_contract",
    "inspect_agent_nodes",
    "export_protocols",
)
QUICKSTART_EVIDENCE_REQUEST_IDS = ("events", "audit", "artifacts")
QUICKSTART_REQUEST_IDS = (
    *QUICKSTART_GET_REQUEST_IDS,
    "plan_agent_request",
    "run_workflow",
    *QUICKSTART_EVIDENCE_REQUEST_IDS,
)
QUICKSTART_SDK_REQUEST_IDS = (
    "health",
    "launch_contract",
    "entry_profile",
    "harness_agent",
    "sdk_bootstrap",
    "consumer_manifest",
    "import_catalog",
    "direct_cli_readiness",
    "plan_agent_request",
    "run_workflow",
    *QUICKSTART_EVIDENCE_REQUEST_IDS,
)
CONSUMER_SDK_REQUIRED_SEQUENCE = (
    "health",
    "launch_contract",
    "entry_profile",
    "harness_agent",
    "sdk_bootstrap",
    "plan_agent_request",
    "run_workflow",
    *QUICKSTART_EVIDENCE_REQUEST_IDS,
)
QUICKSTART_SEQUENCE = (
    "open_studio",
    "launch_contract",
    "entry_profile",
    "harness_agent",
    "sdk_bootstrap",
    "consumer_manifest",
    "import_catalog",
    "direct_cli_readiness",
    "inspect_workflow",
    "inspect_bridge_contract",
    "inspect_agent_nodes",
    "export_protocols",
    "plan_agent_request",
    "run_workflow",
    "read_events_audit_artifacts",
)

NETWORK_ACCEPTANCE_CHECK_SPECS: tuple[tuple[str, str, str, dict[str, object]], ...] = (
    (
        "daemon_reachable",
        "health",
        "CBN daemon answers authenticated first-call requests.",
        {"http_status": 200, "json.status": "ok"},
    ),
    (
        "launch_contract_readable",
        "launch_contract",
        "External consumers can fetch the redacted minimum launch contract without reading the full package.",
        {
            "http_status": 200,
            "json.kind": "ConsumerLaunchContract",
            "json.status": "ready",
            "json.auth.secret_values_echoed": False,
            "json.harness_agent.kind": "NaturalLanguageWorkflowHarness",
        },
    ),
    (
        "entry_profile_readable",
        "entry_profile",
        "External consumers can fetch the redacted stable entry profile before reading optional surfaces.",
        {
            "http_status": 200,
            "json.kind": "NetworkEntryProfile",
            "json.status": "ready",
            "json.auth.secret_values_echoed": False,
            "json.compatibility.internal_bus": "CBN BridgeMessage",
        },
    ),
    (
        "harness_agent_readable",
        "harness_agent",
        "External consumers can fetch the focused natural-language harness agent contract.",
        {
            "http_status": 200,
            "json.kind": "NetworkHarnessAgent",
            "json.status": "ready",
            "json.auth.secret_values_echoed": False,
            "json.harness.kind": "NaturalLanguageWorkflowHarness",
            "json.bridge.route_count_min": 1,
        },
    ),
    (
        "sdk_bootstrap_readable",
        "sdk_bootstrap",
        "External SDKs can fetch the stable bootstrap contract before choosing a larger package.",
        {
            "http_status": 200,
            "json.kind": "ConsumerSdkBootstrap",
            "json.status": "ready",
            "json.auth.secret_values_echoed": False,
            "json.typed_responses.run_workflow": "WorkflowRunReceipt",
            "json.harness.bridge_route_count_min": 1,
        },
    ),
    (
        "consumer_manifest_readable",
        "consumer_manifest",
        "External programs can fetch the redacted persistable manifest used to enter the CBN network.",
        {
            "http_status": 200,
            "json.kind": "NetworkConsumerManifest",
            "json.status": "ready",
            "json.auth.secret_values_echoed": False,
            "json.safety.secret_values_included": False,
            "json.typed_responses.run_workflow": "WorkflowRunReceipt",
        },
    ),
    (
        "import_catalog_readable",
        "import_catalog",
        "External consumers can discover CLI registration importers before choosing a harness.",
        {
            "http_status": 200,
            "json.kind": "CliRegistrationSurface",
            "json.status": "ready",
            "json.importer_count_min": 1,
        },
    ),
    (
        "direct_cli_readiness_readable",
        "direct_cli_readiness",
        "External consumers can inspect direct CLI typed parser coverage and first-run recovery gates.",
        {
            "http_status": 200,
            "json.kind": "DirectCliReadinessReport",
            "json.ok": True,
            "json.summary.profile_count_min": 1,
            "json.summary.capability_count_min": 1,
            "json.summary.recovery_type_count_min": 1,
        },
    ),
    (
        "workflow_dag_loads",
        "inspect_workflow",
        "The selected CLI-CLI workflow DAG can be inspected before execution.",
        {"http_status": 200, "json.valid": True, "json.task_count_min": 1},
    ),
    (
        "bridge_contract_routes",
        "inspect_bridge_contract",
        "BridgeMessage selector routes are available for CLI-CLI handoff inspection.",
        {"http_status": 200, "json.ok": True, "json.summary.route_count_min": 1},
    ),
    (
        "agent_nodes_readable",
        "inspect_agent_nodes",
        "Reusable harness agent nodes can be inspected before execution.",
        {
            "http_status": 200,
            "json.kind": "AdapterAgentNodeBundle",
            "json.ok": True,
            "json.cards_count_min": 1,
            "json.harnesses_count_min": 1,
            "json.bridge_message.kind": "BridgeMessage",
        },
    ),
    (
        "protocol_exports_readable",
        "export_protocols",
        "MCP/A2A/ACP workflow descriptors can be exported for external protocol facades.",
        {
            "http_status": 200,
            "json.exports.mcp.protocol": "mcp",
            "json.exports.a2a.protocol": "a2a",
            "json.exports.acp.protocol": "acp",
        },
    ),
    (
        "natural_language_harness_plan",
        "plan_agent_request",
        "A reusable harness agent can bind natural language to the workflow run contract.",
        {
            "http_status": 200,
            "json.kind": "AdapterAgentWorkflowRequestPlan",
            "json.ok": True,
            "json.reusable_harness.kind": "NaturalLanguageWorkflowHarness",
        },
    ),
    (
        "workflow_run_receipt",
        "run_workflow",
        "The daemon can produce a workflow run receipt for the CLI-CLI chain.",
        {"http_status": 200, "json.status": "completed", "json.workflow_id_type": "string"},
    ),
    (
        "runtime_events_readable",
        "events",
        "Runtime events include evidence after the workflow call.",
        {"http_status": 200, "json.type": "array", "json.count_min": 1},
    ),
    (
        "audit_evidence_readable",
        "audit",
        "Audit evidence includes records for demo and integration review.",
        {"http_status": 200, "json.type": "array", "json.count_min": 1},
    ),
    (
        "artifacts_readable",
        "artifacts",
        "Produced artifacts can be listed by the consumer after workflow execution.",
        {"http_status": 200, "json.type": "array", "json.count_min": 1},
    ),
)

NETWORK_ACCEPTANCE_SUCCESS_SIGNALS = (
    "health.status == ok",
    "consumer_launch_contract.status == ready",
    "network_entry_profile.status == ready",
    "network_harness_agent.status == ready",
    "consumer_sdk_bootstrap.status == ready",
    "network_consumer_manifest.status == ready",
    "import_catalog.importer_count >= 1",
    "direct_cli_readiness.ok == true",
    "workflow.valid == true",
    "bridge_contract.summary.route_count >= 1",
    "agent_node_bundle.kind == AdapterAgentNodeBundle",
    "protocol_exports include mcp, a2a, acp",
    "agent_workflow_request.reusable_harness.kind == NaturalLanguageWorkflowHarness",
    "workflow_run.status == completed",
    "events/audit/artifacts endpoints return non-empty JSON arrays after run",
)

NETWORK_ACCEPTANCE_FAILURE_RECOVERY = (
    "If health fails, verify daemon URL and X-CBN-Session.",
    "If launch_contract fails, verify the daemon exposes /network/launch-contract from the current CBN build.",
    "If entry_profile fails, verify the daemon exposes /network/entry-profile and redacts session tokens.",
    "If harness_agent fails, verify the daemon exposes /network/harness-agent and the workflow request plan is ready.",
    "If sdk_bootstrap fails, verify the daemon exposes /network/sdk-bootstrap and the bootstrap contract is redacted.",
    "If consumer_manifest fails, verify the daemon exposes /network/consumer-manifest and redacts session tokens.",
    "If import_catalog fails, verify the daemon exposes /imports/catalog from the current CBN build.",
    "If direct_cli_readiness fails, verify the daemon exposes /direct-cli/readiness and parser fixtures are available.",
    "If workflow inspection fails, verify workflow_path and required manifests.",
    "If run_workflow fails, rerun plan_agent_request and inspect bridge routes before retrying.",
)
