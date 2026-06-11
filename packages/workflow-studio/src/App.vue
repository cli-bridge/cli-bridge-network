<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from "vue";
import {
  Activity,
  Bot,
  Boxes,
  Braces,
  ClipboardList,
  Copy,
  ExternalLink,
  FileJson,
  Gauge,
  History,
  Network,
  Play,
  RefreshCw,
  Rocket,
  ShieldCheck,
  Wrench,
} from "lucide-vue-next";
import { StudioApi } from "./api";
import { mountWorkflowGraph, type StudioGraph } from "./graph";
import type {
  AcceptanceExecutionResult,
  AcceptanceRunSummary,
  AgentCliContractPackageHealth,
  AdapterAgentNodeBundle,
  AdapterAgentToolCallPlan,
  AgentWorkflowRequestPlan,
  BridgeContractReport,
  BridgeContractSection,
  BridgeContractSummary,
  CliRegistrationSurface,
  ConnectDemoStage,
  ConnectionAcceptanceCheck,
  ConnectSummary,
  ConsumerLaunchContract,
  ConsumerSdkBootstrap,
  DirectCliReadinessReport,
  DockState,
  EvidenceSummary,
  KillerDemoReport,
  KillerMvpReadiness,
  NetworkConnectionAcceptance,
  NetworkEntryProfile,
  NetworkHarnessAgent,
  NetworkConnectionAcceptanceReport,
  NetworkConnectPackage,
  NetworkConnectQuickstart,
  ProtocolSummary,
  ProtocolWireConformanceReport,
  QuickstartSdkSnippet,
  QuickstartRequest,
  QuickstartSequenceStep,
  StudioConfig,
  WorkflowInspect,
  WorkflowRequestSummary,
  WorkflowTask,
} from "./types";

const urlConfig = new URLSearchParams(window.location.search);

const config = reactive<StudioConfig>({
  daemonUrl: urlConfig.get("daemonUrl") || "http://127.0.0.1:8787",
  sessionToken: urlConfig.get("sessionToken") || "",
  workflowPath: urlConfig.get("workflowPath") || "workflows/cli-anything-macrocli-mermaid-routing.example.json",
  agentMessage:
    urlConfig.get("agentMessage") ||
    "Run this workflow as a reusable CLI-CLI harness agent and surface setup gates.",
  dryRun: urlConfig.get("dryRun") !== "false",
  confirmed: urlConfig.get("confirmed") === "true",
});
const dashboardUrl = computed(() => urlConfig.get("dashboardUrl") || "http://127.0.0.1:5173");

const canvasRef = ref<HTMLCanvasElement | null>(null);
const graphRef = ref<StudioGraph | null>(null);
const workflow = ref<WorkflowInspect | null>(null);
const workflowList = ref<unknown>(null);
const contract = ref<BridgeContractReport | null>(null);
const runResult = ref<unknown>(null);
const demoReport = ref<KillerDemoReport | null>(null);
const agentBundle = ref<AdapterAgentNodeBundle | null>(null);
const workflowRequestPlan = ref<AgentWorkflowRequestPlan | null>(null);
const toolCallPlan = ref<AdapterAgentToolCallPlan | null>(null);
const connectPackage = ref<NetworkConnectPackage | null>(null);
const directQuickstart = ref<NetworkConnectQuickstart | null>(null);
const launchContract = ref<ConsumerLaunchContract | null>(null);
const entryProfile = ref<NetworkEntryProfile | null>(null);
const networkHarnessAgent = ref<NetworkHarnessAgent | null>(null);
const sdkBootstrap = ref<ConsumerSdkBootstrap | null>(null);
const directAcceptance = ref<NetworkConnectionAcceptance | null>(null);
const directReadiness = ref<KillerMvpReadiness | null>(null);
const importCatalog = ref<CliRegistrationSurface | null>(null);
const directCliReadiness = ref<DirectCliReadinessReport | null>(null);
const protocolWireReport = ref<ProtocolWireConformanceReport | null>(null);
const networkVerifyReport = ref<NetworkConnectionAcceptanceReport | null>(null);
const health = ref<unknown>(null);
const selectedTaskId = ref("");
const loading = ref("");
const error = ref("");
const copiedScript = ref("");
const acceptanceResults = ref<AcceptanceExecutionResult[]>([]);
const dock = reactive<DockState>({ events: [], audit: [], artifacts: [] });

const api = computed(() => new StudioApi(config));
const healthAuth = computed(() => healthAuthSummary(health.value, config.sessionToken));
const tasks = computed<WorkflowTask[]>(() => (Array.isArray(workflow.value?.tasks) ? workflow.value.tasks : []));
const selectedTask = computed(() => tasks.value.find((task) => task.id === selectedTaskId.value) ?? tasks.value[0]);
const selectedRoutes = computed(() => selectedTask.value?.argsFrom ?? []);
const agentCards = computed(() => (Array.isArray(agentBundle.value?.cards) ? agentBundle.value.cards : []));
const agentTasks = computed(() => (Array.isArray(agentBundle.value?.tasks) ? agentBundle.value.tasks : []));
const agentHandoffs = computed(() => agentBundle.value?.source_coordination_plan?.handoffs ?? []);
const evidenceSummary = computed<EvidenceSummary>(() => summarizeEvidence(demoReport.value, dock));
const demoCommunicationHandoffs = computed(() =>
  Array.isArray(demoReport.value?.communication_trace?.handoffs) ? demoReport.value.communication_trace.handoffs : [],
);
const protocolSummary = computed<ProtocolSummary>(() => summarizeProtocols(demoReport.value));
const protocolWireSummary = computed(() => summarizeProtocolWireConformance(protocolWireReport.value));
const bridgeContractSummary = computed<BridgeContractSummary>(() => summarizeBridgeContract(contract.value));
const workflowRequestSummary = computed<WorkflowRequestSummary>(() => summarizeWorkflowRequestPlan(workflowRequestPlan.value));
const setupToolCalls = computed(() => (Array.isArray(toolCallPlan.value?.tool_calls) ? toolCallPlan.value.tool_calls : []));
const setupBatches = computed(() => (Array.isArray(toolCallPlan.value?.execution_batches) ? toolCallPlan.value.execution_batches : []));
const setupCheckpoints = computed(() =>
  Array.isArray(toolCallPlan.value?.long_running_loop?.checkpoints) ? toolCallPlan.value.long_running_loop.checkpoints : [],
);
const connectSummary = computed<ConnectSummary>(() => summarizeConnectPackage(connectPackage.value));
const connectQuickstart = computed<NetworkConnectQuickstart>(() => connectPackage.value?.consumer_quickstart ?? {});
const directQuickstartContract = computed<NetworkConnectQuickstart>(() => directQuickstart.value ?? {});
const directQuickstartRequests = computed<QuickstartRequest[]>(() =>
  Array.isArray(directQuickstartContract.value.requests) ? directQuickstartContract.value.requests : [],
);
const quickstartParity = computed(() => summarizeQuickstartParity(connectQuickstart.value, directQuickstartContract.value));
const connectEntryProfile = computed<NetworkEntryProfile>(() => connectPackage.value?.network_entry_profile ?? {});
const connectNetworkHarnessAgent = computed<NetworkHarnessAgent>(() => connectPackage.value?.network_harness_agent ?? {});
const directEntryProfile = computed<NetworkEntryProfile>(() => entryProfile.value ?? {});
const directNetworkHarnessAgent = computed<NetworkHarnessAgent>(() => networkHarnessAgent.value ?? {});
const entryProfileParity = computed(() => summarizeEntryProfileParity(connectEntryProfile.value, directEntryProfile.value));
const networkHarnessParity = computed(() =>
  summarizeNetworkHarnessParity(connectNetworkHarnessAgent.value, directNetworkHarnessAgent.value),
);
const connectMvpReadiness = computed<KillerMvpReadiness>(() => connectPackage.value?.mvp_readiness ?? {});
const directMvpReadiness = computed<KillerMvpReadiness>(() => directReadiness.value ?? {});
const readinessParity = computed(() => summarizeReadinessParity(connectMvpReadiness.value, directMvpReadiness.value));
const connectMvpChecks = computed(() =>
  Array.isArray(connectMvpReadiness.value.checks) ? connectMvpReadiness.value.checks : [],
);
const directMvpChecks = computed(() =>
  Array.isArray(directMvpReadiness.value.checks) ? directMvpReadiness.value.checks : [],
);
const connectPresenterBrief = computed(() => connectPackage.value?.mvp_presenter_brief ?? {});
const connectPresenterProofPoints = computed(() =>
  Array.isArray(connectPresenterBrief.value.proof_points) ? connectPresenterBrief.value.proof_points : [],
);
const connectPresenterFlow = computed(() =>
  Array.isArray(connectPresenterBrief.value.live_demo_flow) ? connectPresenterBrief.value.live_demo_flow : [],
);
const connectLaunchContract = computed<ConsumerLaunchContract>(() => connectPackage.value?.consumer_launch_contract ?? {});
const directLaunchContract = computed<ConsumerLaunchContract>(() => launchContract.value ?? {});
const launchContractParity = computed(() => summarizeLaunchContractParity(connectLaunchContract.value, directLaunchContract.value));
const connectSdkBootstrap = computed<ConsumerSdkBootstrap>(() => connectPackage.value?.consumer_sdk_bootstrap ?? {});
const directSdkBootstrap = computed<ConsumerSdkBootstrap>(() => sdkBootstrap.value ?? {});
const sdkBootstrapParity = computed(() => summarizeSdkBootstrapParity(connectSdkBootstrap.value, directSdkBootstrap.value));
const connectAcceptance = computed<NetworkConnectionAcceptance>(
  () => connectPackage.value?.acceptance ?? connectPackage.value?.consumer_quickstart?.acceptance ?? {},
);
const directAcceptanceContract = computed<NetworkConnectionAcceptance>(() => directAcceptance.value ?? {});
const directAcceptanceChecks = computed<ConnectionAcceptanceCheck[]>(() =>
  Array.isArray(directAcceptanceContract.value.checks) ? directAcceptanceContract.value.checks : [],
);
const acceptanceParity = computed(() => summarizeAcceptanceParity(connectAcceptance.value, directAcceptanceContract.value));
const connectLaunchSequence = computed(() =>
  Array.isArray(connectLaunchContract.value.launch_sequence) ? connectLaunchContract.value.launch_sequence : [],
);
const directLaunchSequence = computed(() =>
  Array.isArray(directLaunchContract.value.launch_sequence) ? directLaunchContract.value.launch_sequence : [],
);
const connectContractSummary = computed<BridgeContractSummary>(() => summarizeConnectContracts(connectPackage.value));
const connectExternalPackageHealth = computed<AgentCliContractPackageHealth>(() => connectPackage.value?.contracts?.external?.package_health ?? {});
const connectExternalPackageFiles = computed(() =>
  Array.isArray(connectExternalPackageHealth.value.files) ? connectExternalPackageHealth.value.files : [],
);
const connectExternalPackageOffenders = computed(() =>
  Array.isArray(connectExternalPackageHealth.value.independence?.offenders)
    ? connectExternalPackageHealth.value.independence.offenders
    : [],
);
const connectCliAnythingHealth = computed(() => connectPackage.value?.plugins?.cli_anything ?? {});
const connectCliAnythingSplit = computed(() => connectCliAnythingHealth.value.module_split ?? {});
const connectCliAnythingSplitParts = computed(() =>
  Array.isArray(connectCliAnythingSplit.value.parts) ? connectCliAnythingSplit.value.parts : [],
);
const connectAgentBundle = computed(() => connectPackage.value?.agent_node_bundle ?? {});
const connectAgentCards = computed(() => (Array.isArray(connectAgentBundle.value.cards) ? connectAgentBundle.value.cards : []));
const connectAgentHarnesses = computed(() => (Array.isArray(connectAgentBundle.value.harnesses) ? connectAgentBundle.value.harnesses : []));
const connectAgentTasks = computed(() => (Array.isArray(connectAgentBundle.value.tasks) ? connectAgentBundle.value.tasks : []));
const connectEndpoints = computed(() => (Array.isArray(connectPackage.value?.daemon_endpoints) ? connectPackage.value.daemon_endpoints : []));
const connectDemoStages = computed<ConnectDemoStage[]>(() =>
  Array.isArray(connectPackage.value?.demo_readiness?.stages) ? connectPackage.value.demo_readiness.stages : [],
);
const connectDemoPlaybookSteps = computed(() =>
  Array.isArray(connectPackage.value?.demo_playbook?.steps) ? connectPackage.value.demo_playbook.steps : [],
);
const connectSetupGuidance = computed(() => connectPackage.value?.setup_guidance ?? {});
const connectSetupCalls = computed(() =>
  Array.isArray(connectPackage.value?.setup_guidance?.tool_calls) ? connectPackage.value.setup_guidance.tool_calls : [],
);
const connectHarnessRoutes = computed<Array<Record<string, unknown>>>(() =>
  Array.isArray(connectPackage.value?.agent_workflow_request?.bridge_routes)
    ? connectPackage.value.agent_workflow_request.bridge_routes
    : [],
);
const connectRegistrationImporters = computed(() =>
  Array.isArray(connectPackage.value?.registration_surface?.importers) ? connectPackage.value.registration_surface.importers : [],
);
const directImportCatalogImporters = computed(() =>
  Array.isArray(importCatalog.value?.importers) ? importCatalog.value.importers : [],
);
const importCatalogNextCommands = computed<string[]>(() =>
  Array.isArray(importCatalog.value?.next_commands) ? importCatalog.value.next_commands : [],
);
const connectDirectCliReadiness = computed<DirectCliReadinessReport>(() => connectPackage.value?.direct_cli_readiness ?? {});
const directCliSummary = computed(() => summarizeDirectCliReadiness(directCliReadiness.value ?? connectDirectCliReadiness.value ?? null));
const directCliParity = computed(() => summarizeDirectCliParity(connectDirectCliReadiness.value, directCliReadiness.value ?? {}));
const importCatalogParity = computed(() => {
  if (!importCatalog.value || !connectPackage.value?.registration_surface) return "not compared";
  return importCatalog.value.importer_count === connectPackage.value.registration_surface.importer_count
    ? "catalog parity"
    : "catalog drift";
});
const connectNextCommands = computed<string[]>(() => {
  const commands = [
    ...(Array.isArray(connectPackage.value?.next_commands) ? connectPackage.value.next_commands : []),
    ...(Array.isArray(connectPackage.value?.demo_readiness?.next_commands) ? connectPackage.value.demo_readiness.next_commands : []),
    ...(Array.isArray(connectPackage.value?.demo_playbook?.next_commands) ? connectPackage.value.demo_playbook.next_commands : []),
    ...(Array.isArray(connectPackage.value?.mvp_presenter_brief?.next_commands) ? connectPackage.value.mvp_presenter_brief.next_commands : []),
    ...(Array.isArray(connectPackage.value?.registration_surface?.next_commands) ? connectPackage.value.registration_surface.next_commands : []),
  ].filter((command): command is string => typeof command === "string" && command.trim().length > 0);
  return Array.from(new Set(commands));
});
const quickstartRequests = computed<QuickstartRequest[]>(() =>
  Array.isArray(connectQuickstart.value.requests) ? connectQuickstart.value.requests : [],
);
const quickstartSdkSnippets = computed<QuickstartSdkSnippet[]>(() =>
  Array.isArray(connectQuickstart.value.sdk_snippets) ? connectQuickstart.value.sdk_snippets : [],
);
const quickstartSequenceSteps = computed<QuickstartSequenceStep[]>(() => {
  const steps = connectQuickstart.value.sequence_steps;
  if (Array.isArray(steps) && steps.length) return steps;
  return quickstartRequests.value.map((request, index) => ({
    order: index + 1,
    id: request.id || `request-${index + 1}`,
    kind: "http",
    title: request.id || "Quickstart request",
    intent: "Replay this request as part of the consumer first-call sequence.",
    request_id: request.id,
    method: request.method || "GET",
    url: request.url,
    success_signal: "Request returns the expected JSON payload.",
  }));
});
const acceptanceChecks = computed<ConnectionAcceptanceCheck[]>(() => {
  return Array.isArray(connectAcceptance.value.checks) ? connectAcceptance.value.checks : [];
});
const acceptanceRunSummary = computed<AcceptanceRunSummary>(() => summarizeAcceptanceResults(acceptanceResults.value, acceptanceChecks.value.length));
const acceptanceResultByCheck = computed<Record<string, AcceptanceExecutionResult>>(() =>
  Object.fromEntries(acceptanceResults.value.map((result) => [result.check_id, result])),
);

async function call(label: string, fn: () => Promise<unknown>): Promise<unknown | null> {
  loading.value = label;
  error.value = "";
  try {
    return await fn();
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
    return null;
  } finally {
    loading.value = "";
  }
}

async function loadHealth() {
  health.value = await call("health", () => api.value.health());
}

async function loadWorkflows() {
  workflowList.value = await call("workflows", () => api.value.workflows());
}

async function inspectWorkflow() {
  const payload = await call("workflow", () => api.value.workflow(config.workflowPath));
  workflow.value = payload as WorkflowInspect;
  selectedTaskId.value = tasks.value[0]?.id ?? "";
  await nextTick();
  graphRef.value?.render(workflow.value, agentBundle.value);
}

async function inspectContract() {
  contract.value = (await call("contract", () => api.value.contract(config.workflowPath))) as BridgeContractReport;
}

async function inspectAgentBundle() {
  agentBundle.value = (await call("agent", () => api.value.adapterAgentNodeBundle())) as AdapterAgentNodeBundle;
  await nextTick();
  graphRef.value?.render(workflow.value, agentBundle.value);
}

async function inspectWorkflowRequestPlan() {
  workflowRequestPlan.value = (await call("plan", () => api.value.workflowRequestPlan())) as AgentWorkflowRequestPlan;
}

async function inspectSetupPlan() {
  toolCallPlan.value = (await call("setup plan", () => api.value.toolCallPlan())) as AdapterAgentToolCallPlan;
}

async function inspectConnectPackage() {
  connectPackage.value = (await call("connect", () => api.value.networkConnectPackage())) as NetworkConnectPackage;
}

async function inspectQuickstart() {
  directQuickstart.value = (await call("quickstart", () => api.value.networkQuickstart())) as NetworkConnectQuickstart;
}

async function inspectLaunchContract() {
  launchContract.value = (await call("launch", () => api.value.networkLaunchContract())) as ConsumerLaunchContract;
}

async function inspectEntryProfile() {
  entryProfile.value = (await call("profile", () => api.value.networkEntryProfile())) as NetworkEntryProfile;
}

async function inspectNetworkHarnessAgent() {
  networkHarnessAgent.value = (await call("harness", () => api.value.networkHarnessAgent())) as NetworkHarnessAgent;
}

async function inspectSdkBootstrap() {
  sdkBootstrap.value = (await call("sdk bootstrap", () => api.value.networkSdkBootstrap())) as ConsumerSdkBootstrap;
}

async function inspectAcceptance() {
  directAcceptance.value = (await call("acceptance", () => api.value.networkAcceptance())) as NetworkConnectionAcceptance;
}

async function inspectReadiness() {
  directReadiness.value = (await call("readiness", () => api.value.networkReadiness())) as KillerMvpReadiness;
}

async function inspectImportCatalog() {
  importCatalog.value = (await call("imports", () => api.value.importCatalog())) as CliRegistrationSurface;
}

async function inspectDirectCliReadiness() {
  directCliReadiness.value = (await call("direct CLI", () => api.value.directCliReadiness())) as DirectCliReadinessReport;
}

async function inspectProtocolWireConformance() {
  protocolWireReport.value = (await call("wire conformance", () => api.value.protocolWireConformance())) as ProtocolWireConformanceReport;
}

function openStudioLink() {
  const url = connectSummary.value.studioLink;
  if (url) {
    window.open(url, "_blank", "noopener,noreferrer");
  }
}

function openDashboardConsole() {
  window.open(dashboardUrl.value, "_blank", "noopener,noreferrer");
}

async function copyText(label: string, text: string) {
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    copiedScript.value = label;
    window.setTimeout(() => {
      if (copiedScript.value === label) copiedScript.value = "";
    }, 1600);
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  }
}

async function verifyConnectAcceptance() {
  if (!connectPackage.value) {
    await inspectConnectPackage();
  }
  const checks = acceptanceChecks.value;
  const requests = quickstartRequests.value;
  acceptanceResults.value = [];
  loading.value = "acceptance";
  error.value = "";
  try {
    for (const check of checks) {
      const result = await runAcceptanceCheck(check, requests);
      acceptanceResults.value = [...acceptanceResults.value, result];
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    loading.value = "";
  }
  await refreshEvidence();
}

async function verifyDaemonAcceptance() {
  if (!connectPackage.value) {
    await inspectConnectPackage();
  }
  networkVerifyReport.value = (await call("network verify", () => api.value.networkVerify())) as NetworkConnectionAcceptanceReport;
  acceptanceResults.value = Array.isArray(networkVerifyReport.value?.results)
    ? networkVerifyReport.value.results
    : [];
  await refreshEvidence();
}

async function runAcceptanceCheck(
  check: ConnectionAcceptanceCheck,
  requests: QuickstartRequest[],
): Promise<AcceptanceExecutionResult> {
  const checkId = check.id || check.request_id || "acceptance_check";
  const requestId = check.request_id || "";
  const request = requests.find((candidate) => candidate.id === requestId);
  if (!request) {
    return {
      check_id: checkId,
      request_id: requestId || "unknown",
      status: "skipped",
      proves: check.proves,
      expect: check.expect,
      error: "matching quickstart request not found",
    };
  }
  try {
    const response = await api.value.quickstartRequest(request);
    const evaluation = evaluateAcceptanceExpectation(check.expect ?? {}, response.payload, response.http_status);
    return {
      check_id: checkId,
      request_id: requestId,
      status: evaluation.passed ? "passed" : "failed",
      http_status: response.http_status,
      proves: check.proves,
      expect: check.expect,
      evidence: evaluation.evidence,
      error: evaluation.error,
    };
  } catch (err) {
    return {
      check_id: checkId,
      request_id: requestId,
      status: "failed",
      proves: check.proves,
      expect: check.expect,
      error: err instanceof Error ? err.message : String(err),
    };
  }
}

async function runWorkflow() {
  runResult.value = await call("run", () => api.value.runWorkflow());
  await refreshEvidence();
}

async function runKillerDemo() {
  demoReport.value = (await call("demo", () => api.value.killerDemo())) as KillerDemoReport;
  runResult.value = demoReport.value?.summary ? demoReport.value : runResult.value;
  await refreshEvidence();
}

async function refreshEvidence() {
  const [events, audit, artifacts] = await Promise.all([
    call("events", () => api.value.events()),
    call("audit", () => api.value.audit()),
    call("artifacts", () => api.value.artifacts()),
  ]);
  dock.events = Array.isArray(events) ? events : [];
  dock.audit = Array.isArray(audit) ? audit : [];
  dock.artifacts = Array.isArray(artifacts) ? artifacts : [];
}

async function loadAll() {
  await Promise.all([
    loadHealth(),
    loadWorkflows(),
    inspectWorkflow(),
    inspectContract(),
    inspectAgentBundle(),
    inspectWorkflowRequestPlan(),
    inspectConnectPackage(),
    inspectQuickstart(),
    inspectLaunchContract(),
    inspectEntryProfile(),
    inspectNetworkHarnessAgent(),
    inspectSdkBootstrap(),
    inspectAcceptance(),
    inspectReadiness(),
    inspectImportCatalog(),
    inspectDirectCliReadiness(),
    inspectProtocolWireConformance(),
    refreshEvidence(),
  ]);
}

function pretty(payload: unknown): string {
  return JSON.stringify(payload ?? null, null, 2);
}

function healthAuthSummary(payload: unknown, configuredToken: string): { status: string; required: boolean; supplied: boolean; detail: string } {
  const hasConfiguredToken = configuredToken.trim().length > 0;
  if (!(payload && typeof payload === "object" && "auth" in payload)) {
    return {
      status: "checking token",
      required: !hasConfiguredToken,
      supplied: hasConfiguredToken,
      detail: "Waiting for daemon /health auth metadata.",
    };
  }
  const auth =
    typeof (payload as { auth?: unknown }).auth === "object"
      ? ((payload as { auth?: Record<string, unknown> }).auth ?? {})
      : {};
  const required = auth.session_token_required === true;
  const supplied = auth.session_token_supplied === true || hasConfiguredToken;
  if (!required) {
    return { status: "open daemon", required, supplied, detail: "POST calls do not require a daemon session token." };
  }
  if (supplied) {
    return { status: "token ready", required, supplied, detail: "X-CBN-Session will be sent with POST calls." };
  }
  return {
    status: "token required",
    required,
    supplied,
    detail: "Paste the daemon session token printed by `python -m cbn daemon serve`.",
  };
}

function summarizeEvidence(report: KillerDemoReport | null, evidenceDock: DockState): EvidenceSummary {
  const summary = report?.summary ?? {};
  const evidence = report?.evidence ?? {};
  const trace = report?.communication_trace ?? {};
  const stageStatuses = Array.isArray(report?.stages) ? report.stages : [];
  const completedStages = numberValue(summary.completed_stage_count) ?? stageStatuses.filter((stage) => stage.status === "completed").length;
  const blockedStages = numberValue(summary.blocked_stage_count) ?? stageStatuses.filter((stage) => !["completed", "not_run"].includes(stage.status)).length;
  const taskArtifacts = Array.isArray(evidence.task_artifacts) ? evidence.task_artifacts : [];
  const artifactIds = taskArtifacts
    .map((artifact) => artifact.artifact_id)
    .filter((artifactId): artifactId is string => Boolean(artifactId))
    .slice(0, 6);
  return {
    status: report?.ok ? "ready" : report ? "needs attention" : "not run",
    workflowStatus: stringValue(summary.workflow_status) ?? "not run",
    completedStages,
    blockedStages,
    routeCount: numberValue(summary.route_count) ?? 0,
    communicationTraceStatus: stringValue(trace.status) ?? stringValue(summary.communication_trace_status) ?? "not run",
    communicationHandoffs: numberValue(trace.handoff_count) ?? numberValue(summary.communication_handoff_count) ?? 0,
    communicationValid: `${numberValue(trace.message_valid_count) ?? 0}/${numberValue(trace.handoff_count) ?? 0}`,
    taskArtifactCount: numberValue(summary.artifact_count) ?? numberValue(evidence.task_artifact_count) ?? 0,
    eventCount: numberValue(evidence.event_count) ?? evidenceDock.events.length,
    auditCount: numberValue(evidence.audit_count) ?? evidenceDock.audit.length,
    smokeOk: statusText(summary.smoke_ok),
    bridgeLabOk: statusText(summary.bridge_lab_ok),
    artifactIds,
  };
}

function summarizeProtocols(report: KillerDemoReport | null): ProtocolSummary {
  const exports = report?.protocol_exports?.exports ?? {};
  const smokeByProtocol = report?.protocol_smoke_suite?.summary?.by_protocol ?? {};
  return {
    mcpWorkflowTools: Array.isArray(exports.mcp?.workflowTools) ? exports.mcp.workflowTools.length : 0,
    a2aSkills: Array.isArray(exports.a2a?.agentCard?.skills) ? exports.a2a.agentCard.skills.length : 0,
    acpWorkflows: Array.isArray(exports.acp?.workflows) ? exports.acp.workflows.length : 0,
    mcpSmoke: smokeText(smokeByProtocol.mcp),
    a2aSmoke: smokeText(smokeByProtocol.a2a),
    acpSmoke: smokeText(smokeByProtocol.acp),
    smokeChecks: numberValue(report?.protocol_smoke_suite?.summary?.check_count) ?? 0,
    smokeFailures: numberValue(report?.protocol_smoke_suite?.summary?.failed_count) ?? 0,
    wireCompatible: {
      mcp: wireText(exports.mcp?.wire_compatible),
      a2a: wireText(exports.a2a?.wire_compatible),
      acp: wireText(exports.acp?.wire_compatible),
    },
  };
}

function summarizeProtocolWireConformance(report: ProtocolWireConformanceReport | null): {
  status: string;
  detail: string;
  wireCount: string;
  checks: string;
  failures: number;
  protocols: Array<{ id: string; status: string; checks: string }>;
} {
  const summary = report?.summary ?? {};
  const protocolEntries = Object.entries(report?.protocols ?? {});
  const protocolCount = numberValue(summary.protocol_count) ?? protocolEntries.length;
  const wireCount = numberValue(summary.wire_compatible_protocol_count) ?? 0;
  const checkCount = numberValue(summary.check_count) ?? 0;
  const passedCount = numberValue(summary.passed_count) ?? 0;
  return {
    status: report?.wire_compatible ? "wire compatible" : report ? "wire gaps" : "not loaded",
    detail: report?.external_protocol_boundary ?? "Direct /protocols/wire-conformance has not been fetched.",
    wireCount: `${wireCount}/${protocolCount}`,
    checks: `${passedCount}/${checkCount}`,
    failures: numberValue(summary.failed_count) ?? 0,
    protocols: protocolEntries.map(([id, value]) => ({
      id: id.toUpperCase(),
      status: value?.wire_compatible ? "wire compatible" : "wire gaps",
      checks: `${numberValue(value?.summary?.passed_count) ?? 0}/${numberValue(value?.summary?.check_count) ?? 0}`,
    })),
  };
}

function summarizeDirectCliReadiness(report: DirectCliReadinessReport | null): {
  status: string;
  profiles: string;
  capabilities: string;
  parser: string;
  fixtures: string;
  recovery: string;
  gated: number;
  rows: Array<{ profile: string; status: string; capabilities: string; setup: number; gated: number }>;
  recoveryRows: Array<{ errorType: string; status: string; cases: string; nextAction: string }>;
} {
  const summary = report?.summary ?? {};
  const parser = report?.parser_contract ?? {};
  const profiles = Array.isArray(report?.profiles) ? report.profiles : [];
  const recovery = Array.isArray(report?.error_recovery) ? report.error_recovery : [];
  return {
    status: report?.ok ? "ready" : report ? "needs attention" : "not loaded",
    profiles: `${numberValue(summary.profile_count) ?? profiles.length}/${numberValue(summary.action_count) ?? 0}`,
    capabilities: `${numberValue(summary.verified_output_count) ?? 0}/${numberValue(summary.capability_count) ?? 0}`,
    parser: parser.present ? parser.parser_ref || report?.parser_ref || "direct-cli.typed" : "not loaded",
    fixtures: `${numberValue(summary.fixture_case_count) ?? numberValue(parser.case_count) ?? 0}/${numberValue(summary.fixture_failed_case_count) ?? numberValue(parser.failed_case_count) ?? 0} failed`,
    recovery: `${recovery.filter((item) => item.covered).length}/${numberValue(summary.recovery_type_count) ?? recovery.length}`,
    gated: numberValue(summary.gated_capability_count) ?? 0,
    rows: profiles.map((profile) => ({
      profile: profile.profile || "profile",
      status: profile.status || "unknown",
      capabilities: `${numberValue(profile.verified_capability_count) ?? 0}/${numberValue(profile.capability_count) ?? 0}`,
      setup: numberValue(profile.setup_action_count) ?? 0,
      gated: numberValue(profile.gated_capability_count) ?? 0,
    })),
    recoveryRows: recovery.map((item) => ({
      errorType: item.error_type || "error",
      status: item.covered ? "covered" : "missing",
      cases: (item.fixture_case_ids || []).join(", ") || "no fixture",
      nextAction: item.next_action || "inspect setup guide",
    })),
  };
}

function summarizeDirectCliParity(nested: DirectCliReadinessReport, direct: DirectCliReadinessReport): { status: string; detail: string } {
  if (!direct.kind) {
    return { status: "direct CLI one-shot", detail: "Using the direct CLI readiness copy embedded in the one-shot package." };
  }
  if (!nested.kind) {
    return { status: "direct CLI direct only", detail: "Direct endpoint is loaded; connect package is not loaded yet." };
  }
  const nestedSummary = nested.summary ?? {};
  const directSummary = direct.summary ?? {};
  const matched =
    nested.ok === direct.ok &&
    nestedSummary.profile_count === directSummary.profile_count &&
    nestedSummary.capability_count === directSummary.capability_count &&
    nestedSummary.verified_output_count === directSummary.verified_output_count &&
    nestedSummary.recovery_type_count === directSummary.recovery_type_count &&
    nestedSummary.fixture_failed_case_count === directSummary.fixture_failed_case_count;
  return {
    status: matched ? "direct CLI parity" : "direct CLI drift",
    detail: matched
      ? "Direct CLI readiness endpoint matches the one-shot package copy."
      : "Direct CLI readiness endpoint differs from the one-shot package copy.",
  };
}

function summarizeBridgeContract(payload: BridgeContractReport | null): BridgeContractSummary {
  const contracts = payload?.contract?.contracts ?? {};
  const summary = payload?.summary ?? {};
  const routeCount = numberValue(summary.route_count) ?? 0;
  const readyCount = numberValue(summary.route_ready_count) ?? 0;
  return {
    status: payload?.ok ? "ready" : payload ? "blocked" : "not loaded",
    protocolName: payload?.contract?.protocol_name ?? "CBN Bridge Contract",
    routeReady: `${readyCount}/${routeCount}`,
    blockedRoutes: numberValue(summary.blocked_route_count) ?? 0,
    sections: [
      contractSectionSummary("tool_manifest", "ToolManifest", contracts.tool_manifest),
      contractSectionSummary("bridge_message", "BridgeMessage", contracts.bridge_message),
      contractSectionSummary("artifact", "Artifact", contracts.artifact),
      contractSectionSummary("workflow_selector", "Workflow Selector", contracts.workflow_selector),
    ],
  };
}

function contractSectionSummary(
  id: string,
  title: string,
  section: BridgeContractSection | undefined,
): BridgeContractSummary["sections"][number] {
  const required = section?.required_spec ?? section?.required_metadata ?? section?.required_payload ?? section?.required_fields ?? section?.valid_roots ?? [];
  return {
    id,
    title,
    kind: section?.kind ?? "not loaded",
    owner: section?.owner ?? "not loaded",
    scope: section?.scope ?? "not loaded",
    required: required.length ? required.join(", ") : "not loaded",
  };
}

function summarizeWorkflowRequestPlan(payload: AgentWorkflowRequestPlan | null): WorkflowRequestSummary {
  const apiError = apiErrorPayload(payload);
  if (apiError) {
    const errorType = stringValue(apiError.error_type) ?? "api_error";
    const errorDetail = stringValue(apiError.error) ?? `HTTP ${numberValue(payload?.status) ?? "error"}`;
    const sessionDenied = errorType === "session_denied";
    return {
      status: sessionDenied ? "session token required" : "blocked",
      workflowId: "unknown",
      tasks: 0,
      routes: 0,
      agents: 0,
      nextAction: sessionDenied ? "paste_daemon_session_token" : "inspect_api_error",
      harnessKind: "not loaded",
      runCli: sessionDenied
        ? "Paste the daemon session token printed by `python -m cbn daemon serve`, or open a Studio URL containing sessionToken=..."
        : "",
      errorType,
      errorDetail,
    };
  }
  const summary = payload?.summary ?? {};
  return {
    status: payload?.ok ? "ready" : payload ? "needs attention" : "not loaded",
    workflowId: stringValue(summary.workflow_id) ?? "unknown",
    tasks: numberValue(summary.task_count) ?? 0,
    routes: numberValue(summary.bridge_route_count) ?? 0,
    agents: numberValue(summary.agent_card_count) ?? 0,
    nextAction: stringValue(summary.recommended_next_action) ?? "load_request_plan",
    harnessKind: payload?.reusable_harness?.kind ?? "unknown",
    runCli: payload?.run?.cli ?? "",
    errorType: "",
    errorDetail: "",
  };
}

function apiErrorPayload(payload: AgentWorkflowRequestPlan | null): { error_type?: unknown; error?: unknown } | null {
  if (!payload || payload.ok !== false) return null;
  const nested = payload.payload;
  if (nested?.error_type || nested?.error) return nested;
  if (nested?.payload?.error_type || nested?.payload?.error) return nested.payload;
  return null;
}

function summarizeConnectPackage(payload: NetworkConnectPackage | null): ConnectSummary {
  const external = payload?.contracts?.external ?? {};
  const packageHealth = external.package_health ?? {};
  const packageMetadata = packageHealth.metadata ?? {};
  const packageIndependence = packageHealth.independence ?? {};
  const summary = payload?.summary ?? {};
  const studio = payload?.workflow_studio ?? {};
  const demo = payload?.demo_readiness ?? {};
  const playbook = payload?.demo_playbook ?? {};
  const quickstart = payload?.consumer_quickstart ?? {};
  const entryProfile = payload?.network_entry_profile ?? {};
  const networkHarnessAgent = payload?.network_harness_agent ?? {};
  const mvp = payload?.mvp_readiness ?? {};
  const presenter = payload?.mvp_presenter_brief ?? {};
  const presenterHandoff = presenter.integration_handoff ?? {};
  const launchContract = payload?.consumer_launch_contract ?? {};
  const sdkBootstrap = payload?.consumer_sdk_bootstrap ?? {};
  const acceptance = payload?.acceptance ?? quickstart.acceptance ?? {};
  const setup = payload?.setup_guidance ?? {};
  const harness = payload?.agent_workflow_request ?? {};
  const registration = payload?.registration_surface ?? {};
  const cliAnything = payload?.plugins?.cli_anything ?? {};
  const cliAnythingSplit = cliAnything.module_split ?? {};
  const harnessBridge =
    harness.bridge_message && typeof harness.bridge_message === "object"
      ? (harness.bridge_message as { metadata?: { channel?: unknown }; channel?: unknown })
      : {};
  const headers = quickstart.required_headers ?? {};
  return {
    status: payload?.ok ? "ready" : payload ? "needs attention" : "not loaded",
    entryProfileStatus: stringValue(entryProfile.status) ?? "not loaded",
    entryProfileMode: stringValue(entryProfile.integration_mode) ?? "not loaded",
    entryProfileId: stringValue(entryProfile.profile_id) ?? "not loaded",
    entryProfileStableFields: Array.isArray(entryProfile.compatibility?.stable_fields)
      ? entryProfile.compatibility.stable_fields.join(", ")
      : "not loaded",
    entryProfileAuth: entryProfile.auth?.session_token_included
      ? "session token included"
      : entryProfile.auth?.session_token_required
        ? "session token required"
        : "no session header",
    entryProfileEvidence: `${numberValue(entryProfile.evidence?.acceptance_check_count) ?? 0} checks · ${numberValue(entryProfile.evidence?.demo_stage_count) ?? 0} stages`,
    networkHarnessStatus: stringValue(networkHarnessAgent.status) ?? "not loaded",
    networkHarnessId: stringValue(networkHarnessAgent.contract_id) ?? "not loaded",
    networkHarnessRouteCount: numberValue(networkHarnessAgent.bridge?.route_count) ?? 0,
    networkHarnessRunEndpoint: stringValue(networkHarnessAgent.run?.endpoint) ?? "not loaded",
    mvpReadinessStatus: stringValue(mvp.status) ?? stringValue(summary.mvp_readiness_status) ?? "not loaded",
    mvpReadinessScore: stringValue(mvp.score) ?? stringValue(summary.mvp_readiness_score) ?? "0/0",
    mvpReadinessGoals: Object.entries(mvp.product_goals ?? {}).filter(([, ready]) => ready).length + "/" + Object.keys(mvp.product_goals ?? {}).length,
    presenterStatus: stringValue(presenter.status) ?? stringValue(summary.mvp_presenter_brief_status) ?? "not loaded",
    presenterHeadline: stringValue(presenter.headline) ?? "Presenter brief not loaded",
    presenterProofPoints: Array.isArray(presenter.proof_points) ? presenter.proof_points.length : 0,
    presenterFlowSteps: Array.isArray(presenter.live_demo_flow) ? presenter.live_demo_flow.length : 0,
    presenterConnectPackageUrl: stringValue(presenterHandoff.connect_package_url) ?? "not loaded",
    presenterConnectPackageCommand: stringValue(presenterHandoff.connect_package_command) ?? "not loaded",
    presenterSdkBootstrapUrl: stringValue(presenterHandoff.sdk_bootstrap_url) ?? "not loaded",
    presenterSdkBootstrapCommand: stringValue(presenterHandoff.sdk_bootstrap_command) ?? "not loaded",
    launchContractStatus: stringValue(launchContract.status) ?? "not loaded",
    launchContractId: stringValue(launchContract.contract_id) ?? "not loaded",
    launchSequenceSteps: Array.isArray(launchContract.launch_sequence) ? launchContract.launch_sequence.length : 0,
    launchRequiredRequests: Array.isArray(launchContract.required_request_ids) ? launchContract.required_request_ids.length : 0,
    launchSecretPolicy: launchContract.auth?.secret_values_echoed === false ? "no secret echo" : "check secret policy",
    sdkBootstrapStatus: stringValue(sdkBootstrap.status) ?? stringValue(summary.consumer_sdk_bootstrap_status) ?? "not loaded",
    sdkBootstrapId: stringValue(sdkBootstrap.bootstrap_id) ?? "not loaded",
    sdkBootstrapRequests: numberValue(sdkBootstrap.request_count) ?? numberValue(summary.consumer_sdk_bootstrap_request_count) ?? 0,
    sdkBootstrapRequiredSequence: Array.isArray(sdkBootstrap.required_sequence) ? sdkBootstrap.required_sequence.length : 0,
    sdkBootstrapSecretPolicy: sdkBootstrap.auth?.secret_values_echoed === false ? "no secret echo" : "check secret policy",
    sdkBootstrapRunEndpoint: stringValue(sdkBootstrap.harness?.run_endpoint) ?? "not loaded",
    externalProtocol: external.protocol ?? "unknown",
    acceptedKinds: Array.isArray(external.accepted_kinds) ? external.accepted_kinds.join(" + ") : "unknown",
    externalPackageStatus: packageHealth.ok ? "package clean" : packageHealth.kind ? "package attention" : "package not loaded",
    externalPackageFiles: numberValue(packageHealth.file_count) ?? (Array.isArray(packageHealth.files) ? packageHealth.files.length : 0),
    externalPackageSourceFiles: numberValue(packageIndependence.source_file_count) ?? 0,
    externalPackageNpm: stringValue(packageMetadata.npm_name) ?? stringValue(external.package_boundary?.npm_name) ?? "npm not loaded",
    externalPackagePython: stringValue(packageMetadata.python_name) ?? stringValue(external.package_boundary?.python_name) ?? "python not loaded",
    generatedCapabilities: Array.isArray(external.generated_capability_ids) ? external.generated_capability_ids.slice(0, 4) : [],
    bridgeRoutes: numberValue(summary.bridge_route_count) ?? 0,
    endpointCount: Array.isArray(payload?.daemon_endpoints) ? payload.daemon_endpoints.length : 0,
    protocolExports: numberValue(summary.protocol_export_count) ?? 0,
    agentCards: numberValue(summary.agent_card_count) ?? 0,
    registrationImporters: numberValue(registration.importer_count) ?? numberValue(summary.registration_importer_count) ?? 0,
    consumerSnippets: numberValue(summary.consumer_snippet_count) ?? quickstartSdkSnippets.value.length,
    registrationPolicy: registration.default_policy?.dry_run_by_default ? "dry-run imports" : "check import policy",
    cliAnythingSplitStatus: stringValue(cliAnythingSplit.status) ?? stringValue(summary.cli_anything_split_status) ?? "not loaded",
    cliAnythingSplitParts: `${numberValue(cliAnythingSplit.present_part_count) ?? 0}/${numberValue(cliAnythingSplit.expected_part_count) ?? 0}`,
    cliAnythingFacadeLines: numberValue(cliAnythingSplit.facade_line_count) ?? 0,
    cliAnythingEntrypoint: cliAnything.entrypoint_available ? "cli-hub available" : "cli-hub not found",
    demoReadinessStatus: stringValue(demo.status) ?? "not loaded",
    demoStageCount: numberValue(demo.stage_count) ?? 0,
    demoPlaybookStatus: stringValue(playbook.status) ?? "not loaded",
    demoPlaybookSteps: numberValue(playbook.step_count) ?? numberValue(summary.demo_playbook_step_count) ?? 0,
    setupStatus: stringValue(setup.status) ?? stringValue(summary.setup_status) ?? "not loaded",
    setupRequired: setup.setup_required || summary.setup_required ? "setup required" : "ready",
    setupUserGates: numberValue(setup.requires_user_count) ?? numberValue(summary.setup_user_gate_count) ?? 0,
    setupSecrets: numberValue(setup.secret_count) ?? numberValue(summary.setup_secret_count) ?? 0,
    setupCommands: numberValue(setup.setup_command_count) ?? 0,
    setupSafety: setup.safety?.secret_values_included === false ? "no secret values" : "unknown safety",
    harnessKind: stringValue(harness.reusable_harness?.kind) ?? "not loaded",
    harnessBinding: stringValue(harness.request?.binding) ?? "not loaded",
    harnessRouteCount: numberValue(harness.bridge_route_count) ?? (Array.isArray(harness.bridge_routes) ? harness.bridge_routes.length : 0),
    harnessRunEndpoint: stringValue(harness.run?.http?.url) ?? "",
    harnessBridgeChannel: stringValue(harnessBridge.metadata?.channel) ?? stringValue(harnessBridge.channel) ?? stringValue(harness.bridge_message_channel) ?? "",
    demoEndpoint: stringValue(demo.demo_endpoint?.url) ?? stringValue(demo.demo_endpoint?.path) ?? "",
    nextAction: stringValue(summary.recommended_next_action) ?? "load_connect_package",
    studioLink: stringValue(studio.url) ?? "",
    studioToken: studio.session_token_included ? "token included" : "token not included",
    studioMode: studio.dry_run === false ? "live run" : "dry-run",
    quickstartStatus: quickstart.status ?? "not loaded",
    authHeaderStatus: headers["X-CBN-Session"] ? "X-CBN-Session ready" : "no session header",
    runEndpoint: stringValue(quickstart.entrypoints?.run_workflow?.url) ?? "",
    planEndpoint: stringValue(quickstart.entrypoints?.plan_agent_request?.url) ?? "",
    agentNodesEndpoint: stringValue(quickstart.entrypoints?.inspect_agent_nodes) ?? "",
    protocolExportsEndpoint: stringValue(quickstart.entrypoints?.export_protocols) ?? "",
    quickstartRequestCount: Array.isArray(quickstart.requests) ? quickstart.requests.length : 0,
    acceptanceStatus: stringValue(acceptance.status) ?? "not loaded",
    acceptanceCheckCount: numberValue(acceptance.check_count) ?? (Array.isArray(acceptance.checks) ? acceptance.checks.length : 0),
    curlScript: stringValue(quickstart.curl_script) ?? "",
    powershellScript: stringValue(quickstart.powershell_script) ?? "",
  };
}

function summarizeLaunchContractParity(nested: ConsumerLaunchContract, direct: ConsumerLaunchContract): { status: string; detail: string } {
  if (!direct.kind) {
    return { status: "launch not loaded", detail: "Direct /network/launch-contract has not been fetched." };
  }
  if (!nested.kind) {
    return { status: "launch direct only", detail: "Direct endpoint is loaded; connect package is not loaded yet." };
  }
  const sameContract = nested.contract_id === direct.contract_id;
  const sameStatus = nested.status === direct.status;
  const nestedRun = nested.harness_agent?.run_endpoint ?? nested.entrypoints?.run_workflow?.url;
  const directRun = direct.harness_agent?.run_endpoint ?? direct.entrypoints?.run_workflow?.url;
  const sameRunEndpoint = nestedRun === directRun;
  const nestedRequired = Array.isArray(nested.required_request_ids) ? nested.required_request_ids.join("|") : "";
  const directRequired = Array.isArray(direct.required_request_ids) ? direct.required_request_ids.join("|") : "";
  const sameRequired = nestedRequired === directRequired;
  const matched = sameContract && sameStatus && sameRunEndpoint && sameRequired;
  return {
    status: matched ? "launch parity" : "launch drift",
    detail: matched
      ? "Direct launch contract matches the one-shot package copy."
      : "Direct launch contract differs from the one-shot package copy.",
  };
}

function summarizeSdkBootstrapParity(nested: ConsumerSdkBootstrap, direct: ConsumerSdkBootstrap): { status: string; detail: string } {
  if (!direct.kind) {
    return { status: "sdk not loaded", detail: "Direct /network/sdk-bootstrap has not been fetched." };
  }
  if (!nested.kind) {
    return { status: "sdk direct only", detail: "Direct SDK bootstrap is loaded; connect package is not loaded yet." };
  }
  const sameBootstrap = nested.bootstrap_id === direct.bootstrap_id;
  const sameStatus = nested.status === direct.status;
  const sameRequests = (nested.request_count ?? nested.requests?.length ?? 0) === (direct.request_count ?? direct.requests?.length ?? 0);
  const sameSequence = (nested.required_sequence ?? []).join("|") === (direct.required_sequence ?? []).join("|");
  const sameRunEndpoint = nested.harness?.run_endpoint === direct.harness?.run_endpoint;
  const sameSecretPolicy = nested.auth?.secret_values_echoed === direct.auth?.secret_values_echoed;
  const matched = sameBootstrap && sameStatus && sameRequests && sameSequence && sameRunEndpoint && sameSecretPolicy;
  return {
    status: matched ? "sdk parity" : "sdk drift",
    detail: matched
      ? "Direct SDK bootstrap matches the one-shot package copy."
      : "Direct SDK bootstrap differs from the one-shot package copy.",
  };
}

function summarizeQuickstartParity(nested: NetworkConnectQuickstart, direct: NetworkConnectQuickstart): { status: string; detail: string } {
  if (!direct.kind) {
    return { status: "quickstart not loaded", detail: "Direct /network/quickstart has not been fetched." };
  }
  if (!nested.kind) {
    return { status: "quickstart direct only", detail: "Direct quickstart is loaded; connect package quickstart is not loaded yet." };
  }
  const sameStatus = nested.status === direct.status;
  const nestedRequests = Array.isArray(nested.requests) ? nested.requests.map((request) => request.id || "").join("|") : "";
  const directRequests = Array.isArray(direct.requests) ? direct.requests.map((request) => request.id || "").join("|") : "";
  const sameRequests = nestedRequests === directRequests;
  const nestedSequence = Array.isArray(nested.sequence_steps) ? nested.sequence_steps.map((step) => step.request_id || step.id || "").join("|") : "";
  const directSequence = Array.isArray(direct.sequence_steps) ? direct.sequence_steps.map((step) => step.request_id || step.id || "").join("|") : "";
  const sameSequence = nestedSequence === directSequence;
  const sameSdkCount = (nested.sdk_snippets?.length ?? 0) === (direct.sdk_snippets?.length ?? 0);
  const nestedEntrypoints = nested.entrypoints ?? {};
  const directEntrypoints = direct.entrypoints ?? {};
  const sameRunEndpoint = nestedEntrypoints.run_workflow?.url === directEntrypoints.run_workflow?.url;
  const samePlanEndpoint = nestedEntrypoints.plan_agent_request?.url === directEntrypoints.plan_agent_request?.url;
  const sameAcceptanceEndpoint = nestedEntrypoints.acceptance === directEntrypoints.acceptance;
  const matched = sameStatus && sameRequests && sameSequence && sameSdkCount && sameRunEndpoint && samePlanEndpoint && sameAcceptanceEndpoint;
  return {
    status: matched ? "quickstart parity" : "quickstart drift",
    detail: matched
      ? "Direct first-call quickstart matches the one-shot package copy."
      : "Direct first-call quickstart differs from the one-shot package copy.",
  };
}

function summarizeAcceptanceParity(nested: NetworkConnectionAcceptance, direct: NetworkConnectionAcceptance): { status: string; detail: string } {
  if (!direct.kind) {
    return { status: "acceptance not loaded", detail: "Direct /network/acceptance has not been fetched." };
  }
  if (!nested.kind) {
    return { status: "acceptance direct only", detail: "Direct checklist is loaded; connect package checklist is not loaded yet." };
  }
  const sameStatus = nested.status === direct.status;
  const sameCheckCount = nested.check_count === direct.check_count;
  const nestedRequired = Array.isArray(nested.required_request_ids) ? nested.required_request_ids.join("|") : "";
  const directRequired = Array.isArray(direct.required_request_ids) ? direct.required_request_ids.join("|") : "";
  const sameRequired = nestedRequired === directRequired;
  const nestedChecks = Array.isArray(nested.checks)
    ? nested.checks.map((check) => `${check.id || ""}:${check.request_id || ""}`).join("|")
    : "";
  const directChecks = Array.isArray(direct.checks)
    ? direct.checks.map((check) => `${check.id || ""}:${check.request_id || ""}`).join("|")
    : "";
  const sameChecks = nestedChecks === directChecks;
  const matched = sameStatus && sameCheckCount && sameRequired && sameChecks;
  return {
    status: matched ? "acceptance parity" : "acceptance drift",
    detail: matched
      ? "Direct acceptance checklist matches the one-shot package copy."
      : "Direct acceptance checklist differs from the one-shot package copy.",
  };
}

function summarizeReadinessParity(nested: KillerMvpReadiness, direct: KillerMvpReadiness): { status: string; detail: string } {
  if (!direct.kind) {
    return { status: "readiness not loaded", detail: "Direct /network/readiness has not been fetched." };
  }
  if (!nested.kind) {
    return { status: "readiness direct only", detail: "Direct readiness matrix is loaded; connect package readiness is not loaded yet." };
  }
  const sameStatus = nested.status === direct.status;
  const sameScore = nested.score === direct.score;
  const sameCheckCount = nested.check_count === direct.check_count;
  const nestedChecks = Array.isArray(nested.checks)
    ? nested.checks.map((check) => `${check.id || ""}:${check.ready ? "ready" : "todo"}`).join("|")
    : "";
  const directChecks = Array.isArray(direct.checks)
    ? direct.checks.map((check) => `${check.id || ""}:${check.ready ? "ready" : "todo"}`).join("|")
    : "";
  const sameChecks = nestedChecks === directChecks;
  const nestedGoals = nested.product_goals ? Object.entries(nested.product_goals).sort().map(([key, ready]) => `${key}:${ready}`).join("|") : "";
  const directGoals = direct.product_goals ? Object.entries(direct.product_goals).sort().map(([key, ready]) => `${key}:${ready}`).join("|") : "";
  const sameGoals = nestedGoals === directGoals;
  const matched = sameStatus && sameScore && sameCheckCount && sameChecks && sameGoals;
  return {
    status: matched ? "readiness parity" : "readiness drift",
    detail: matched
      ? "Direct MVP readiness matrix matches the one-shot package copy."
      : "Direct MVP readiness matrix differs from the one-shot package copy.",
  };
}

function summarizeEntryProfileParity(nested: NetworkEntryProfile, direct: NetworkEntryProfile): { status: string; detail: string } {
  if (!direct.kind) {
    return { status: "profile not loaded", detail: "Direct /network/entry-profile has not been fetched." };
  }
  if (!nested.kind) {
    return { status: "profile direct only", detail: "Direct endpoint is loaded; connect package is not loaded yet." };
  }
  const sameProfile = nested.profile_id === direct.profile_id;
  const sameStatus = nested.status === direct.status;
  const sameMode = nested.integration_mode === direct.integration_mode;
  const nestedRun = nested.harness_agent?.run_endpoint ?? nested.primary_entrypoints?.run_workflow?.url;
  const directRun = direct.harness_agent?.run_endpoint ?? direct.primary_entrypoints?.run_workflow?.url;
  const sameRunEndpoint = nestedRun === directRun;
  const nestedStable = Array.isArray(nested.compatibility?.stable_fields) ? nested.compatibility.stable_fields.join("|") : "";
  const directStable = Array.isArray(direct.compatibility?.stable_fields) ? direct.compatibility.stable_fields.join("|") : "";
  const sameStableFields = nestedStable === directStable;
  const matched = sameProfile && sameStatus && sameMode && sameRunEndpoint && sameStableFields;
  return {
    status: matched ? "profile parity" : "profile drift",
    detail: matched
      ? "Direct entry profile matches the one-shot package copy."
      : "Direct entry profile differs from the one-shot package copy.",
  };
}

function summarizeNetworkHarnessParity(nested: NetworkHarnessAgent, direct: NetworkHarnessAgent): { status: string; detail: string } {
  if (!direct.kind) {
    return { status: "harness not loaded", detail: "Direct /network/harness-agent has not been fetched." };
  }
  if (!nested.kind) {
    return { status: "harness direct only", detail: "Direct harness contract is loaded; connect package is not loaded yet." };
  }
  const sameContract = nested.contract_id === direct.contract_id;
  const sameStatus = nested.status === direct.status;
  const sameRunEndpoint = nested.run?.endpoint === direct.run?.endpoint;
  const sameRouteCount = nested.bridge?.route_count === direct.bridge?.route_count;
  const sameSecretPolicy = nested.auth?.secret_values_echoed === direct.auth?.secret_values_echoed;
  const matched = sameContract && sameStatus && sameRunEndpoint && sameRouteCount && sameSecretPolicy;
  return {
    status: matched ? "harness parity" : "harness drift",
    detail: matched
      ? "Direct harness contract matches the one-shot package copy."
      : "Direct harness contract differs from the one-shot package copy.",
  };
}

function summarizeConnectContracts(payload: NetworkConnectPackage | null): BridgeContractSummary {
  const internal = payload?.contracts?.internal ?? {};
  const contracts = internal.contracts ?? {};
  const bridgeSummary = internal.bridge_contract?.summary ?? {};
  const routeCount = numberValue(bridgeSummary.route_count) ?? numberValue(payload?.summary?.bridge_route_count) ?? 0;
  const readyCount = numberValue(bridgeSummary.route_ready_count) ?? routeCount;
  return {
    status: payload?.ok ? "ready" : payload ? "needs attention" : "not loaded",
    protocolName: internal.protocol ?? "CBN Bridge Contract",
    routeReady: `${readyCount}/${routeCount}`,
    blockedRoutes: numberValue(bridgeSummary.blocked_route_count) ?? 0,
    sections: [
      contractSectionSummary("tool_manifest", "ToolManifest", contracts.tool_manifest),
      contractSectionSummary("bridge_message", "BridgeMessage", contracts.bridge_message),
      contractSectionSummary("artifact", "Artifact", contracts.artifact),
      contractSectionSummary("workflow_selector", "Workflow Selector", contracts.workflow_selector),
    ],
  };
}

function summarizeAcceptanceResults(results: AcceptanceExecutionResult[], expectedTotal: number): AcceptanceRunSummary {
  const passed = results.filter((result) => result.status === "passed").length;
  const failed = results.filter((result) => result.status === "failed").length;
  const skipped = results.filter((result) => result.status === "skipped").length;
  const total = expectedTotal || results.length;
  const status = results.length === 0 ? "not run" : failed > 0 ? "failed" : skipped > 0 ? "partial" : results.length === total ? "passed" : "running";
  return { status, passed, failed, skipped, total };
}

function demoStageDetail(stage: ConnectDemoStage): string {
  if (Array.isArray(stage.capability_ids) && stage.capability_ids.length) {
    return stage.capability_ids.slice(0, 3).join(", ");
  }
  if (stage.endpoint?.path || stage.endpoint?.url) {
    return `${stage.endpoint.method || "GET"} ${stage.endpoint.path || stage.endpoint.url}`;
  }
  if (Array.isArray(stage.endpoints) && stage.endpoints.length) {
    return stage.endpoints
      .slice(0, 3)
      .map((endpoint) => endpoint.path || endpoint.url || endpoint.method || "endpoint")
      .join(", ");
  }
  if (typeof stage.bridge_route_count === "number") {
    return `${stage.bridge_route_count} bridge routes`;
  }
  return stage.id || "stage";
}

function acceptanceResult(check: ConnectionAcceptanceCheck): AcceptanceExecutionResult | undefined {
  const key = check.id || check.request_id || "";
  return acceptanceResultByCheck.value[key];
}

function evaluateAcceptanceExpectation(
  expect: Record<string, unknown>,
  payload: unknown,
  httpStatus: number,
): { passed: boolean; evidence: Record<string, unknown>; error?: string } {
  const evidence: Record<string, unknown> = {};
  const failures: string[] = [];
  for (const [key, expected] of Object.entries(expect)) {
    const actual = acceptanceActualValue(key, payload, httpStatus);
    const ok = acceptanceValueMatches(key, actual, expected);
    evidence[key] = { expected, actual, ok };
    if (!ok) {
      failures.push(`${key} expected ${String(expected)} but got ${String(actual)}`);
    }
  }
  return {
    passed: failures.length === 0,
    evidence,
    error: failures.length ? failures.join("; ") : undefined,
  };
}

function acceptanceActualValue(key: string, payload: unknown, httpStatus: number): unknown {
  if (key === "http_status") {
    return httpStatus;
  }
  if (!key.startsWith("json.")) {
    return undefined;
  }
  const jsonKey = key.slice("json.".length);
  if (jsonKey === "type") {
    return Array.isArray(payload) ? "array" : typeof payload;
  }
  if (jsonKey === "count_min" || jsonKey === "length_min") {
    return collectionLength(payload);
  }
  if (jsonKey.endsWith("_count_min")) {
    const value = jsonPath(payload, jsonKey.slice(0, -"_count_min".length));
    const length = collectionLength(value);
    if (typeof length === "number") return length;
  }
  if (jsonKey.endsWith("_min")) {
    return jsonPath(payload, jsonKey.slice(0, -"_min".length));
  }
  if (jsonKey.endsWith("_type")) {
    return typeof jsonPath(payload, jsonKey.slice(0, -"_type".length));
  }
  return jsonPath(payload, jsonKey);
}

function collectionLength(value: unknown): number | undefined {
  if (Array.isArray(value) || typeof value === "string") {
    return value.length;
  }
  if (value && typeof value === "object") {
    return Object.keys(value).length;
  }
  return undefined;
}

function acceptanceValueMatches(key: string, actual: unknown, expected: unknown): boolean {
  if (key.endsWith("_min") && typeof actual === "number" && typeof expected === "number") {
    return actual >= expected;
  }
  return actual === expected;
}

function jsonPath(payload: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((current, part) => {
    if (current && typeof current === "object" && part in current) {
      return (current as Record<string, unknown>)[part];
    }
    return undefined;
  }, payload);
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function statusText(value: unknown): string {
  if (value === true) return "pass";
  if (value === false) return "fail";
  if (value === null) return "not run";
  return "unknown";
}

function smokeText(value: { passed?: number; failed?: number } | undefined): string {
  if (!value) return "not run";
  return `${value.passed ?? 0}/${(value.passed ?? 0) + (value.failed ?? 0)}`;
}

function wireText(value: unknown): string {
  if (value === true) return "compatible";
  if (value === false) return "partial";
  return "unknown";
}

watch(
  () => config.workflowPath,
  () => {
    void inspectWorkflow();
    void inspectContract();
    void inspectAgentBundle();
    void inspectWorkflowRequestPlan();
    void inspectConnectPackage();
  },
);

onMounted(async () => {
  if (canvasRef.value) {
    graphRef.value = mountWorkflowGraph(canvasRef.value);
  }
  await loadAll();
});
</script>

<template>
  <main class="studio-shell">
    <aside class="left-rail">
      <header class="brand-block">
        <Network :size="22" />
        <div>
          <h1>CBN Workflow Studio</h1>
          <p>CLI-CLI workflow runtime</p>
        </div>
      </header>

      <label>
        Daemon URL
        <input v-model="config.daemonUrl" spellcheck="false" />
      </label>
      <label>
        Session token
        <input v-model="config.sessionToken" type="password" spellcheck="false" />
      </label>
      <label>
        Workflow path
        <textarea v-model="config.workflowPath" spellcheck="false" rows="3" />
      </label>
      <label>
        Agent prompt
        <textarea v-model="config.agentMessage" spellcheck="false" rows="3" />
      </label>

      <div class="switch-row">
        <label class="check"><input v-model="config.dryRun" type="checkbox" /> dry-run</label>
        <label class="check"><input v-model="config.confirmed" type="checkbox" /> confirmed</label>
      </div>

      <div class="command-grid">
        <button title="Load health, workflow, contract, evidence" @click="loadAll">
          <RefreshCw :size="16" /> Refresh
        </button>
        <button title="Run selected workflow through daemon" @click="runWorkflow">
          <Play :size="16" /> Run
        </button>
        <button title="Run the CLI-Anything macrocli to mermaid killer demo" @click="runKillerDemo">
          <Rocket :size="16" /> Demo
        </button>
        <button title="Inspect workflow contract" @click="inspectContract">
          <ShieldCheck :size="16" /> Contract
        </button>
        <button title="Load Adapter Agent node bundle" @click="inspectAgentBundle">
          <Bot :size="16" /> Agent
        </button>
        <button title="Plan natural-language agent workflow invocation" @click="inspectWorkflowRequestPlan">
          <ClipboardList :size="16" /> Plan
        </button>
        <button title="Plan setup, secret, and login tool calls without executing them" @click="inspectSetupPlan">
          <ShieldCheck :size="16" /> Setup
        </button>
        <button title="Load one-shot network connection package" @click="inspectConnectPackage">
          <Network :size="16" /> Connect
        </button>
        <button title="Load direct first-call quickstart package" @click="inspectQuickstart">
          <Play :size="16" /> Quick
        </button>
        <button title="Load direct network entry profile" @click="inspectEntryProfile">
          <Braces :size="16" /> Profile
        </button>
        <button title="Load direct reusable network harness agent contract" @click="inspectNetworkHarnessAgent">
          <Bot :size="16" /> Harness
        </button>
        <button title="Load direct consumer SDK bootstrap contract" @click="inspectSdkBootstrap">
          <Boxes :size="16" /> SDK
        </button>
        <button title="Load direct consumer launch contract" @click="inspectLaunchContract">
          <ClipboardList :size="16" /> Launch
        </button>
        <button title="Load direct network acceptance checklist" @click="inspectAcceptance">
          <ShieldCheck :size="16" /> Accept
        </button>
        <button title="Load direct MVP readiness matrix" @click="inspectReadiness">
          <Gauge :size="16" /> Ready
        </button>
        <button title="Load direct CLI import catalog from daemon" @click="inspectImportCatalog">
          <FileJson :size="16" /> Imports
        </button>
        <button title="Load direct CLI profile parser and recovery readiness" @click="inspectDirectCliReadiness">
          <Braces :size="16" /> Direct
        </button>
        <button title="Load direct MCP/A2A/ACP wire conformance report" @click="inspectProtocolWireConformance">
          <Network :size="16" /> Wire
        </button>
        <button title="Open maintainer console" @click="openDashboardConsole">
          <Wrench :size="16" /> Console
        </button>
      </div>

      <section class="status-panel">
        <div class="section-title"><Gauge :size="15" /> Health</div>
        <div class="evidence-row">
          <span :class="['pill-inline', healthAuth.required && !healthAuth.supplied ? 'blocked' : 'ok']">{{ healthAuth.status }}</span>
          <span class="pill-inline">{{ healthAuth.detail }}</span>
        </div>
        <pre>{{ pretty(health) }}</pre>
      </section>
    </aside>

    <section class="graph-pane">
      <div class="toolbar">
        <div>
          <strong>{{ workflow?.workflow_id || "workflow" }}</strong>
          <span>{{ tasks.length }} tasks</span>
        </div>
        <span v-if="loading" class="pill">loading {{ loading }}</span>
        <span v-if="error" class="pill danger">{{ error }}</span>
      </div>
      <canvas ref="canvasRef" width="1100" height="640" />
    </section>

    <aside class="right-rail">
      <section>
        <div class="section-title"><Boxes :size="15" /> Task</div>
        <select v-model="selectedTaskId">
          <option v-for="task in tasks" :key="task.id" :value="task.id">{{ task.id }}</option>
        </select>
        <pre>{{ pretty(selectedTask) }}</pre>
      </section>
      <section>
        <div class="section-title"><Braces :size="15" /> Selectors</div>
        <pre>{{ pretty(selectedRoutes) }}</pre>
      </section>
      <section>
        <div class="section-title"><ShieldCheck :size="15" /> Bridge Contract</div>
        <div class="contract-status-grid">
          <div>
            <span>Status</span>
            <strong>{{ bridgeContractSummary.status }}</strong>
          </div>
          <div>
            <span>Routes</span>
            <strong>{{ bridgeContractSummary.routeReady }}</strong>
          </div>
          <div>
            <span>Blocked</span>
            <strong>{{ bridgeContractSummary.blockedRoutes }}</strong>
          </div>
        </div>
        <div class="contract-section-list">
          <div v-for="section in bridgeContractSummary.sections" :key="section.id">
            <strong>{{ section.title }}</strong>
            <span>{{ section.kind }}</span>
            <code>{{ section.owner }}</code>
            <small>{{ section.scope }}</small>
            <em>{{ section.required }}</em>
          </div>
        </div>
        <pre>{{ pretty({ protocol: bridgeContractSummary.protocolName, summary: contract?.summary, contracts: contract?.contract?.contracts }) }}</pre>
      </section>
      <section>
        <div class="section-title"><FileJson :size="15" /> Run result</div>
        <pre>{{ pretty(runResult) }}</pre>
      </section>
      <section>
        <div class="section-title"><Bot :size="15" /> Agent Bundle</div>
        <div class="agent-summary">
          <span :class="['pill-inline', agentBundle?.ok ? 'ok' : 'blocked']">{{ agentBundle?.status || "not loaded" }}</span>
          <span>{{ agentCards.length }} agents</span>
          <span>{{ agentTasks.length }} tasks</span>
        </div>
        <div class="agent-card-list">
          <div v-for="card in agentCards" :key="card.metadata.id" class="agent-card">
            <strong>{{ card.metadata.title || card.metadata.id }}</strong>
            <span>{{ card.metadata.status || card.spec.policy?.risk || "unknown" }}</span>
            <code>{{ card.metadata.role || card.metadata.id }}</code>
          </div>
        </div>
        <pre>{{ pretty({ handoffs: agentHandoffs, bridge_message: agentBundle?.bridge_message }) }}</pre>
      </section>
      <section>
        <div class="section-title"><ClipboardList :size="15" /> Agent Workflow Plan</div>
        <div class="request-summary">
          <div>
            <span>Status</span>
            <strong>{{ workflowRequestSummary.status }}</strong>
          </div>
          <div>
            <span>Workflow</span>
            <strong>{{ workflowRequestSummary.workflowId }}</strong>
          </div>
          <div>
            <span>Tasks</span>
            <strong>{{ workflowRequestSummary.tasks }}</strong>
          </div>
          <div>
            <span>Routes</span>
            <strong>{{ workflowRequestSummary.routes }}</strong>
          </div>
          <div>
            <span>Agents</span>
            <strong>{{ workflowRequestSummary.agents }}</strong>
          </div>
          <div>
            <span>Harness</span>
            <strong>{{ workflowRequestSummary.harnessKind }}</strong>
          </div>
        </div>
        <div class="evidence-row">
          <span :class="['pill-inline', workflowRequestPlan?.ok ? 'ok' : 'blocked']">{{ workflowRequestSummary.nextAction }}</span>
          <span v-if="workflowRequestSummary.errorType" class="pill-inline blocked">{{ workflowRequestSummary.errorType }}</span>
          <span v-if="workflowRequestSummary.errorDetail" class="pill-inline">{{ workflowRequestSummary.errorDetail }}</span>
        </div>
        <div class="artifact-strip">
          <code v-if="workflowRequestSummary.runCli">{{ workflowRequestSummary.runCli }}</code>
          <span v-else>No workflow request plan loaded</span>
        </div>
        <pre>{{ pretty({ request: workflowRequestPlan?.request, run: workflowRequestPlan?.run, bridge_routes: workflowRequestPlan?.bridge_routes, bridge_message: workflowRequestPlan?.bridge_message, api_error: workflowRequestPlan?.payload }) }}</pre>
      </section>
      <section>
        <div class="section-title"><ShieldCheck :size="15" /> Agent Setup Plan</div>
        <div class="request-summary">
          <div>
            <span>Loop</span>
            <strong>{{ toolCallPlan?.long_running_loop?.status || "not loaded" }}</strong>
          </div>
          <div>
            <span>Calls</span>
            <strong>{{ toolCallPlan?.summary?.tool_call_count ?? 0 }}</strong>
          </div>
          <div>
            <span>User gates</span>
            <strong>{{ toolCallPlan?.summary?.requires_user_count ?? 0 }}</strong>
          </div>
          <div>
            <span>Batches</span>
            <strong>{{ toolCallPlan?.summary?.batch_count ?? 0 }}</strong>
          </div>
          <div>
            <span>Secrets</span>
            <strong>{{ toolCallPlan?.summary?.by_kind?.["setup-secret"] ?? 0 }}</strong>
          </div>
          <div>
            <span>Commands</span>
            <strong>{{ toolCallPlan?.summary?.by_kind?.["setup-command"] ?? 0 }}</strong>
          </div>
        </div>
        <div class="agent-card-list">
          <div v-for="call in setupToolCalls.slice(0, 6)" :key="call.call_id || call.tool_use_id" class="agent-card">
            <strong>{{ call.action || call.kind || "tool call" }}</strong>
            <span>{{ call.initial_status || "queued" }}</span>
            <code>{{ call.agent_role || "agent" }} · {{ call.source?.setup_id || call.source?.secret_name || call.tool || "setup" }}</code>
          </div>
          <span v-if="!setupToolCalls.length">No setup tool calls loaded</span>
        </div>
        <div class="endpoint-list">
          <div v-for="batch in setupBatches.slice(0, 4)" :key="batch.batch_id">
            <code>{{ batch.mode || "batch" }}</code>
            <span>{{ batch.batch_id || "batch" }} · {{ batch.reason || "execution order" }}</span>
          </div>
        </div>
        <pre>{{ pretty({ checkpoints: setupCheckpoints, by_initial_status: toolCallPlan?.summary?.by_initial_status, batches: setupBatches.slice(0, 4) }) }}</pre>
      </section>
      <section>
        <div class="section-title"><Network :size="15" /> Connect Package</div>
        <div class="connect-summary">
          <div>
            <span>Status</span>
            <strong>{{ connectSummary.status }}</strong>
          </div>
          <div>
            <span>Entry</span>
            <strong>{{ connectSummary.entryProfileStatus }}</strong>
          </div>
          <div>
            <span>MVP</span>
            <strong>{{ connectSummary.mvpReadinessScore }}</strong>
          </div>
          <div>
            <span>External</span>
            <strong>{{ connectSummary.externalProtocol }}</strong>
          </div>
          <div>
            <span>Package</span>
            <strong>{{ connectSummary.externalPackageFiles }}</strong>
          </div>
          <div>
            <span>Endpoints</span>
            <strong>{{ connectSummary.endpointCount }}</strong>
          </div>
          <div>
            <span>Routes</span>
            <strong>{{ connectSummary.bridgeRoutes }}</strong>
          </div>
          <div>
            <span>Protocols</span>
            <strong>{{ connectSummary.protocolExports }}</strong>
          </div>
          <div>
            <span>Agents</span>
            <strong>{{ connectSummary.agentCards }}</strong>
          </div>
          <div>
            <span>Imports</span>
            <strong>{{ connectSummary.registrationImporters }}</strong>
          </div>
          <div>
            <span>Split</span>
            <strong>{{ connectSummary.cliAnythingSplitParts }}</strong>
          </div>
          <div>
            <span>Snippets</span>
            <strong>{{ connectSummary.consumerSnippets }}</strong>
          </div>
          <div>
            <span>Demo</span>
            <strong>{{ connectSummary.demoStageCount }}</strong>
          </div>
          <div>
            <span>Playbook</span>
            <strong>{{ connectSummary.demoPlaybookSteps }}</strong>
          </div>
          <div>
            <span>Setup</span>
            <strong>{{ connectSummary.setupStatus }}</strong>
          </div>
          <div>
            <span>Harness</span>
            <strong>{{ connectSummary.harnessRouteCount }}</strong>
          </div>
        </div>
        <div class="evidence-row">
          <span :class="['pill-inline', connectPackage?.ok ? 'ok' : 'blocked']">{{ connectSummary.acceptedKinds }}</span>
          <span :class="['pill-inline', connectExternalPackageHealth.ok ? 'ok' : 'blocked']">{{ connectSummary.externalPackageStatus }}</span>
          <span class="pill-inline">{{ connectSummary.nextAction }}</span>
          <span class="pill-inline">{{ connectSummary.studioToken }}</span>
          <span class="pill-inline">{{ connectSummary.studioMode }}</span>
          <span class="pill-inline">{{ connectSummary.quickstartStatus }}</span>
          <span :class="['pill-inline', quickstartParity.status === 'quickstart parity' ? 'ok' : quickstartParity.status === 'quickstart drift' ? 'blocked' : '']">
            {{ quickstartParity.status }}
          </span>
          <span class="pill-inline">{{ connectSummary.authHeaderStatus }}</span>
          <span class="pill-inline">{{ connectSummary.registrationPolicy }}</span>
          <span :class="['pill-inline', connectSummary.cliAnythingSplitStatus === 'ready' ? 'ok' : connectSummary.cliAnythingSplitStatus === 'incomplete' ? 'blocked' : '']">
            split {{ connectSummary.cliAnythingSplitStatus }}
          </span>
          <span class="pill-inline">{{ connectSummary.cliAnythingEntrypoint }}</span>
          <span :class="['pill-inline', importCatalogParity === 'catalog parity' ? 'ok' : importCatalogParity === 'catalog drift' ? 'blocked' : '']">
            {{ importCatalogParity }}
          </span>
          <span class="pill-inline">{{ connectSummary.quickstartRequestCount }} requests</span>
          <span class="pill-inline">{{ connectSummary.acceptanceStatus }}</span>
          <span class="pill-inline">{{ connectSummary.acceptanceCheckCount }} checks</span>
          <span :class="['pill-inline', acceptanceParity.status === 'acceptance parity' ? 'ok' : acceptanceParity.status === 'acceptance drift' ? 'blocked' : '']">
            {{ acceptanceParity.status }}
          </span>
          <span :class="['pill-inline', readinessParity.status === 'readiness parity' ? 'ok' : readinessParity.status === 'readiness drift' ? 'blocked' : '']">
            {{ readinessParity.status }}
          </span>
          <span class="pill-inline">{{ connectSummary.demoReadinessStatus }}</span>
          <span class="pill-inline">{{ connectSummary.demoPlaybookStatus }}</span>
          <span :class="['pill-inline', connectSummary.entryProfileStatus === 'ready' ? 'ok' : 'blocked']">
            entry {{ connectSummary.entryProfileStatus }}
          </span>
          <span :class="['pill-inline', connectSummary.networkHarnessStatus === 'ready' ? 'ok' : 'blocked']">
            harness contract {{ connectSummary.networkHarnessStatus }}
          </span>
          <span :class="['pill-inline', networkHarnessParity.status === 'harness parity' ? 'ok' : networkHarnessParity.status === 'harness drift' ? 'blocked' : '']">
            {{ networkHarnessParity.status }}
          </span>
          <span :class="['pill-inline', sdkBootstrapParity.status === 'sdk parity' ? 'ok' : sdkBootstrapParity.status === 'sdk drift' ? 'blocked' : '']">
            {{ sdkBootstrapParity.status }}
          </span>
          <span :class="['pill-inline', connectSummary.mvpReadinessStatus === 'ready' ? 'ok' : 'blocked']">
            mvp {{ connectSummary.mvpReadinessStatus }}
          </span>
          <span class="pill-inline">goals {{ connectSummary.mvpReadinessGoals }}</span>
          <span class="pill-inline">{{ connectSummary.entryProfileMode }}</span>
          <span :class="['pill-inline', connectSetupGuidance.setup_required ? 'blocked' : 'ok']">{{ connectSummary.setupRequired }}</span>
          <span class="pill-inline">{{ connectSummary.setupUserGates }} user gates</span>
          <span class="pill-inline">{{ connectSummary.setupSecrets }} secrets</span>
          <span class="pill-inline">{{ connectSummary.setupSafety }}</span>
          <span class="pill-inline">{{ connectSummary.harnessKind }}</span>
          <span class="pill-inline">{{ connectSummary.harnessBinding }}</span>
          <span :class="['pill-inline', acceptanceRunSummary.status === 'passed' ? 'ok' : acceptanceRunSummary.status === 'failed' ? 'blocked' : '']">
            {{ acceptanceRunSummary.status }}
          </span>
        </div>
        <div class="contract-status-grid">
          <div>
            <span>Network entry</span>
            <strong>{{ connectEntryProfile.display_name || connectSummary.entryProfileId }}</strong>
          </div>
          <div>
            <span>Direct profile</span>
            <strong>{{ directEntryProfile.status || "not loaded" }}</strong>
          </div>
          <div>
            <span>Parity</span>
            <strong>{{ entryProfileParity.status }}</strong>
          </div>
        </div>
        <div class="quickstart-grid">
          <div>
            <span>Profile ID</span>
            <code>{{ connectSummary.entryProfileId }}</code>
          </div>
          <div>
            <span>Compatibility</span>
            <code>{{ connectEntryProfile.compatibility?.external_protocol || connectSummary.externalProtocol }} -> {{ connectEntryProfile.compatibility?.internal_bus || "CBN BridgeMessage" }}</code>
          </div>
          <div>
            <span>Stable fields</span>
            <code>{{ connectSummary.entryProfileStableFields }}</code>
          </div>
          <div>
            <span>Verify</span>
            <code>{{ connectEntryProfile.primary_entrypoints?.verify_network || "not loaded" }}</code>
          </div>
        </div>
        <div class="quickstart-grid">
          <div>
            <span>Direct ID</span>
            <code>{{ directEntryProfile.profile_id || "not loaded" }}</code>
          </div>
          <div>
            <span>Direct run</span>
            <code>{{ directEntryProfile.harness_agent?.run_endpoint || directEntryProfile.primary_entrypoints?.run_workflow?.url || "not loaded" }}</code>
          </div>
          <div>
            <span>Auth</span>
            <code>{{ directEntryProfile.auth?.session_token_included ? "session token included" : directEntryProfile.auth?.session_token_required ? "session token required" : connectSummary.entryProfileAuth }}</code>
          </div>
          <div>
            <span>Parity detail</span>
            <code>{{ entryProfileParity.detail }}</code>
          </div>
        </div>
        <div class="quickstart-grid">
          <div>
            <span>Harness contract</span>
            <code>{{ connectSummary.networkHarnessId }}</code>
          </div>
          <div>
            <span>Harness status</span>
            <code>{{ connectSummary.networkHarnessStatus }}</code>
          </div>
          <div>
            <span>Harness routes</span>
            <code>{{ connectSummary.networkHarnessRouteCount }} BridgeMessage routes</code>
          </div>
          <div>
            <span>Harness run</span>
            <code>{{ connectSummary.networkHarnessRunEndpoint }}</code>
          </div>
        </div>
        <div class="quickstart-grid">
          <div>
            <span>Direct harness</span>
            <code>{{ directNetworkHarnessAgent.status || "not loaded" }}</code>
          </div>
          <div>
            <span>Direct routes</span>
            <code>{{ directNetworkHarnessAgent.bridge?.route_count ?? 0 }} BridgeMessage routes</code>
          </div>
          <div>
            <span>Direct run</span>
            <code>{{ directNetworkHarnessAgent.run?.endpoint || "not loaded" }}</code>
          </div>
          <div>
            <span>Harness parity</span>
            <code>{{ networkHarnessParity.detail }}</code>
          </div>
        </div>
        <div class="contract-status-grid">
          <div>
            <span>SDK bootstrap</span>
            <strong>{{ connectSummary.sdkBootstrapStatus }}</strong>
          </div>
          <div>
            <span>Direct SDK</span>
            <strong>{{ directSdkBootstrap.status || "not loaded" }}</strong>
          </div>
          <div>
            <span>Parity</span>
            <strong>{{ sdkBootstrapParity.status }}</strong>
          </div>
          <div>
            <span>Secret policy</span>
            <strong>{{ connectSummary.sdkBootstrapSecretPolicy }}</strong>
          </div>
        </div>
        <div class="quickstart-grid">
          <div>
            <span>Bootstrap ID</span>
            <code>{{ connectSummary.sdkBootstrapId }}</code>
          </div>
          <div>
            <span>SDK requests</span>
            <code>{{ connectSummary.sdkBootstrapRequests }} requests</code>
          </div>
          <div>
            <span>Required sequence</span>
            <code>{{ connectSummary.sdkBootstrapRequiredSequence }} calls</code>
          </div>
          <div>
            <span>SDK run</span>
            <code>{{ directSdkBootstrap.harness?.run_endpoint || connectSummary.sdkBootstrapRunEndpoint }}</code>
          </div>
        </div>
        <div class="contract-status-grid">
          <div>
            <span>Launch contract</span>
            <strong>{{ connectSummary.launchContractStatus }}</strong>
          </div>
          <div>
            <span>Direct launch</span>
            <strong>{{ directLaunchContract.status || "not loaded" }}</strong>
          </div>
          <div>
            <span>Parity</span>
            <strong>{{ launchContractParity.status }}</strong>
          </div>
          <div>
            <span>Secret policy</span>
            <strong>{{ connectSummary.launchSecretPolicy }}</strong>
          </div>
        </div>
        <div class="quickstart-grid">
          <div>
            <span>Contract ID</span>
            <code>{{ connectSummary.launchContractId }}</code>
          </div>
          <div>
            <span>Run endpoint</span>
            <code>{{ connectLaunchContract.harness_agent?.run_endpoint || connectSummary.runEndpoint || "not loaded" }}</code>
          </div>
          <div>
            <span>Verify</span>
            <code>{{ connectLaunchContract.entrypoints?.verify_network || "not loaded" }}</code>
          </div>
          <div>
            <span>Required requests</span>
            <code>{{ connectSummary.launchRequiredRequests }}</code>
          </div>
        </div>
        <div class="quickstart-grid">
          <div>
            <span>Direct ID</span>
            <code>{{ directLaunchContract.contract_id || "not loaded" }}</code>
          </div>
          <div>
            <span>Direct run</span>
            <code>{{ directLaunchContract.harness_agent?.run_endpoint || "not loaded" }}</code>
          </div>
          <div>
            <span>Direct verify</span>
            <code>{{ directLaunchContract.entrypoints?.verify_network || "not loaded" }}</code>
          </div>
          <div>
            <span>Parity detail</span>
            <code>{{ launchContractParity.detail }}</code>
          </div>
        </div>
        <div class="request-sequence">
          <div v-for="step in connectLaunchSequence" :key="step.id || step.request_id || step.order" class="passed">
            <code>{{ step.request_id || step.id || "launch" }}</code>
            <span>{{ step.intent || "Launch sequence step" }}</span>
            <small>{{ step.success_signal || "success signal not loaded" }}</small>
          </div>
          <span v-if="!connectLaunchSequence.length">No launch contract loaded</span>
        </div>
        <div class="request-sequence">
          <div v-for="step in directLaunchSequence" :key="`direct-${step.id || step.request_id || step.order}`" class="passed">
            <code>{{ step.request_id || step.id || "direct" }}</code>
            <span>{{ step.intent || "Direct launch sequence step" }}</span>
            <small>{{ step.success_signal || "success signal not loaded" }}</small>
          </div>
          <span v-if="!directLaunchSequence.length">No direct launch contract loaded</span>
        </div>
        <div class="contract-status-grid">
          <div>
            <span>Killer MVP</span>
            <strong>{{ connectSummary.mvpReadinessScore }}</strong>
          </div>
          <div>
            <span>Goals</span>
            <strong>{{ connectSummary.mvpReadinessGoals }}</strong>
          </div>
          <div>
            <span>Next</span>
            <strong>{{ connectMvpReadiness.recommended_next_action || "not loaded" }}</strong>
          </div>
          <div>
            <span>Direct MVP</span>
            <strong>{{ directMvpReadiness.score || directMvpReadiness.status || "not loaded" }}</strong>
          </div>
          <div>
            <span>Direct checks</span>
            <strong>{{ directMvpReadiness.check_count ?? directMvpChecks.length }}</strong>
          </div>
          <div>
            <span>Parity</span>
            <strong>{{ readinessParity.status }}</strong>
          </div>
        </div>
        <div class="quickstart-grid">
          <div>
            <span>Readiness URL</span>
            <code>{{ connectPresenterBrief.integration_handoff?.readiness_url || "not loaded" }}</code>
          </div>
          <div>
            <span>Direct action</span>
            <code>{{ directMvpReadiness.recommended_next_action || "not loaded" }}</code>
          </div>
          <div>
            <span>Product goals</span>
            <code>{{ Object.entries(directMvpReadiness.product_goals || connectMvpReadiness.product_goals || {}).filter(([, ready]) => ready).length }}/{{ Object.keys(directMvpReadiness.product_goals || connectMvpReadiness.product_goals || {}).length }}</code>
          </div>
          <div>
            <span>Parity detail</span>
            <code>{{ readinessParity.detail }}</code>
          </div>
        </div>
        <div class="request-sequence">
          <div v-for="check in connectMvpChecks" :key="check.id || check.title" :class="check.ready ? 'passed' : 'failed'">
            <code>{{ check.ready ? "ready" : "todo" }}</code>
            <span>{{ check.title || check.id || "MVP check" }}</span>
            <small>{{ check.proves || "readiness evidence" }}</small>
            <em>{{ pretty(check.evidence || { next_action: check.next_action }) }}</em>
          </div>
          <span v-if="!connectMvpChecks.length">No MVP readiness checks loaded</span>
        </div>
        <div class="contract-status-grid">
          <div>
            <span>Presenter</span>
            <strong>{{ connectSummary.presenterStatus }}</strong>
          </div>
          <div>
            <span>Proof</span>
            <strong>{{ connectSummary.presenterProofPoints }}</strong>
          </div>
          <div>
            <span>Flow</span>
            <strong>{{ connectSummary.presenterFlowSteps }}</strong>
          </div>
        </div>
        <div class="quickstart-grid">
          <div>
            <span>Headline</span>
            <code>{{ connectSummary.presenterHeadline }}</code>
          </div>
          <div>
            <span>Studio</span>
            <code>{{ connectPresenterBrief.integration_handoff?.studio_url || connectSummary.studioLink || "not loaded" }}</code>
          </div>
          <div>
            <span>Connect package</span>
            <code>{{ connectSummary.presenterConnectPackageUrl }}</code>
          </div>
          <div>
            <span>Readiness</span>
            <code>{{ connectPresenterBrief.integration_handoff?.readiness_url || "not loaded" }}</code>
          </div>
          <div>
            <span>Connect command</span>
            <code>{{ connectSummary.presenterConnectPackageCommand }}</code>
          </div>
          <div>
            <span>SDK bootstrap</span>
            <code>{{ connectSummary.presenterSdkBootstrapUrl }}</code>
          </div>
          <div>
            <span>Verify command</span>
            <code>{{ connectPresenterBrief.integration_handoff?.verify_command || "not loaded" }}</code>
          </div>
          <div>
            <span>SDK command</span>
            <code>{{ connectSummary.presenterSdkBootstrapCommand }}</code>
          </div>
        </div>
        <div class="request-sequence">
          <div v-for="point in connectPresenterProofPoints" :key="point.id || point.title" class="passed">
            <code>{{ point.metric || "proof" }}</code>
            <span>{{ point.title || point.id || "Proof point" }}</span>
            <small>{{ point.evidence_source || "presenter brief" }}</small>
            <em>{{ point.value ?? "not loaded" }}</em>
          </div>
          <span v-if="!connectPresenterProofPoints.length">No presenter proof points loaded</span>
        </div>
        <div class="endpoint-list">
          <div v-for="step in connectPresenterFlow" :key="step.id || step.title">
            <code>{{ step.id || "flow" }}</code>
            <span>{{ step.title || "Presenter flow" }} · {{ step.success_signal || "success signal" }}</span>
          </div>
          <span v-if="!connectPresenterFlow.length">No presenter flow loaded</span>
        </div>
        <div class="agent-card-list">
          <div v-for="call in connectSetupCalls.slice(0, 6)" :key="call.call_id || call.tool_use_id" class="agent-card">
            <strong>{{ call.action || call.kind || "setup" }}</strong>
            <span>{{ call.initial_status || "queued" }}</span>
            <code>{{ call.setup_id || call.capability_id || call.secret_name || call.agent_role || "setup guidance" }}</code>
          </div>
          <span v-if="!connectSetupCalls.length">No setup guidance loaded</span>
        </div>
        <div class="studio-link-row">
          <button title="Open preconfigured Workflow Studio demo link" :disabled="!connectSummary.studioLink" @click="openStudioLink">
            <ExternalLink :size="15" /> Open Studio
          </button>
          <button title="Run quickstart acceptance checks against the daemon" :disabled="!acceptanceChecks.length || loading === 'acceptance'" @click="verifyConnectAcceptance">
            <ShieldCheck :size="15" /> Verify
          </button>
          <button title="Ask the daemon to run the full network acceptance report" :disabled="loading === 'network verify'" @click="verifyDaemonAcceptance">
            <Network :size="15" /> Daemon Verify
          </button>
          <button title="Copy one-shot connect package command" :disabled="!connectSummary.presenterConnectPackageCommand || connectSummary.presenterConnectPackageCommand === 'not loaded'" @click="copyText('connect-package-command', connectSummary.presenterConnectPackageCommand)">
            <Copy :size="14" /> {{ copiedScript === "connect-package-command" ? "Copied" : "Copy Package" }}
          </button>
          <button title="Copy SDK bootstrap command" :disabled="!connectSummary.presenterSdkBootstrapCommand || connectSummary.presenterSdkBootstrapCommand === 'not loaded'" @click="copyText('sdk-bootstrap-command', connectSummary.presenterSdkBootstrapCommand)">
            <Copy :size="14" /> {{ copiedScript === "sdk-bootstrap-command" ? "Copied" : "Copy SDK" }}
          </button>
          <code v-if="connectSummary.studioLink">{{ connectSummary.studioLink }}</code>
          <span v-else>No Workflow Studio link loaded</span>
        </div>
        <div class="contract-status-grid">
          <div>
            <span>Direct quickstart</span>
            <strong>{{ directQuickstartContract.status || "not loaded" }}</strong>
          </div>
          <div>
            <span>Direct requests</span>
            <strong>{{ directQuickstartRequests.length }}</strong>
          </div>
          <div>
            <span>SDK snippets</span>
            <strong>{{ directQuickstartContract.sdk_snippets?.length ?? 0 }}</strong>
          </div>
          <div>
            <span>Parity</span>
            <strong>{{ quickstartParity.status }}</strong>
          </div>
        </div>
        <div class="quickstart-grid">
          <div>
            <span>Direct run</span>
            <code>{{ directQuickstartContract.entrypoints?.run_workflow?.url || "not loaded" }}</code>
          </div>
          <div>
            <span>Direct plan</span>
            <code>{{ directQuickstartContract.entrypoints?.plan_agent_request?.url || "not loaded" }}</code>
          </div>
          <div>
            <span>Direct acceptance</span>
            <code>{{ directQuickstartContract.entrypoints?.acceptance || "not loaded" }}</code>
          </div>
          <div>
            <span>Parity detail</span>
            <code>{{ quickstartParity.detail }}</code>
          </div>
        </div>
        <div class="contract-status-grid">
          <div>
            <span>Import catalog</span>
            <strong>{{ importCatalog?.status || "not loaded" }}</strong>
          </div>
          <div>
            <span>Direct imports</span>
            <strong>{{ importCatalog?.importer_count ?? directImportCatalogImporters.length }}</strong>
          </div>
          <div>
            <span>Policy</span>
            <strong>{{ importCatalog?.default_policy?.dry_run_by_default ? "dry-run" : "not loaded" }}</strong>
          </div>
        </div>
        <div class="endpoint-list">
          <div v-for="importer in directImportCatalogImporters.slice(0, 6)" :key="`direct-${importer.id || importer.entrypoint}`">
            <code>{{ importer.entrypoint || importer.id || "cbn import" }}</code>
            <span>{{ importer.title || "Direct import catalog" }} · {{ importer.write_gate || importer.default_side_effects || "no writes" }}</span>
          </div>
          <span v-if="!directImportCatalogImporters.length">No direct import catalog loaded</span>
        </div>
        <div class="next-command-list">
          <div v-for="(command, index) in importCatalogNextCommands.slice(0, 4)" :key="`import-${command}`">
            <span>{{ index === 0 ? "Catalog" : `Import ${index + 1}` }}</span>
            <code>{{ command }}</code>
            <button title="Copy import catalog command" @click="copyText(`import-catalog-${index}`, command)">
              <Copy :size="14" /> {{ copiedScript === `import-catalog-${index}` ? "Copied" : "Copy" }}
            </button>
          </div>
          <span v-if="!importCatalogNextCommands.length">No import catalog commands loaded</span>
        </div>
        <div class="acceptance-summary">
          <div>
            <span>Direct</span>
            <strong>{{ directAcceptanceContract.status || "not loaded" }}</strong>
          </div>
          <div>
            <span>Direct checks</span>
            <strong>{{ directAcceptanceContract.check_count ?? directAcceptanceChecks.length }}</strong>
          </div>
          <div>
            <span>Parity</span>
            <strong>{{ acceptanceParity.status }}</strong>
          </div>
          <div>
            <span>Signal</span>
            <strong>{{ directAcceptanceContract.success_signals?.length ?? 0 }}</strong>
          </div>
          <div>
            <span>Pass</span>
            <strong>{{ acceptanceRunSummary.passed }}</strong>
          </div>
          <div>
            <span>Fail</span>
            <strong>{{ acceptanceRunSummary.failed }}</strong>
          </div>
          <div>
            <span>Skip</span>
            <strong>{{ acceptanceRunSummary.skipped }}</strong>
          </div>
          <div>
            <span>Total</span>
            <strong>{{ acceptanceRunSummary.total }}</strong>
          </div>
        </div>
        <div class="quickstart-grid">
          <div>
            <span>Acceptance endpoint</span>
            <code>{{ connectPackage?.consumer_quickstart?.entrypoints?.acceptance || "not loaded" }}</code>
          </div>
          <div>
            <span>Required IDs</span>
            <code>{{ (directAcceptanceContract.required_request_ids || connectAcceptance.required_request_ids || []).join(", ") || "not loaded" }}</code>
          </div>
          <div>
            <span>Parity detail</span>
            <code>{{ acceptanceParity.detail }}</code>
          </div>
          <div>
            <span>Recovery</span>
            <code>{{ (directAcceptanceContract.failure_recovery || []).slice(0, 2).join(" · ") || "not loaded" }}</code>
          </div>
        </div>
        <div class="daemon-verify-summary">
          <div>
            <span>Daemon report</span>
            <strong>{{ networkVerifyReport?.status || "not run" }}</strong>
          </div>
          <div>
            <span>Requests</span>
            <strong>{{ networkVerifyReport?.summary?.request_count ?? 0 }}</strong>
          </div>
          <div>
            <span>Checks</span>
            <strong>{{ networkVerifyReport?.summary?.check_count ?? 0 }}</strong>
          </div>
          <div>
            <span>Base URL</span>
            <strong>{{ networkVerifyReport?.base_url || "daemon" }}</strong>
          </div>
        </div>
        <div class="contract-status-grid">
          <div>
            <span>External package</span>
            <strong>{{ connectSummary.externalPackageNpm }}</strong>
          </div>
          <div>
            <span>Python package</span>
            <strong>{{ connectSummary.externalPackagePython }}</strong>
          </div>
          <div>
            <span>Source scan</span>
            <strong>{{ connectSummary.externalPackageSourceFiles }}</strong>
          </div>
        </div>
        <div class="contract-status-grid">
          <div>
            <span>CLI-Anything split</span>
            <strong>{{ connectSummary.cliAnythingSplitStatus }}</strong>
          </div>
          <div>
            <span>Parts</span>
            <strong>{{ connectSummary.cliAnythingSplitParts }}</strong>
          </div>
          <div>
            <span>Facade lines</span>
            <strong>{{ connectSummary.cliAnythingFacadeLines }}</strong>
          </div>
        </div>
        <div class="package-health-list">
          <div v-for="part in connectCliAnythingSplitParts" :key="part.id || part.module" :class="part.present ? 'ok' : 'blocked'">
            <strong>{{ part.id || "part" }}</strong>
            <span>{{ part.present ? "present" : "missing" }}</span>
            <small>{{ part.module || "module not loaded" }}</small>
            <code>{{ part.path || "path not loaded" }}</code>
          </div>
          <span v-if="!connectCliAnythingSplitParts.length">No CLI-Anything split health loaded</span>
        </div>
        <div class="package-health-list">
          <div v-for="file in connectExternalPackageFiles.slice(0, 6)" :key="file.id || file.relative_path" :class="file.exists ? 'ok' : 'blocked'">
            <strong>{{ file.id || "contract file" }}</strong>
            <span>{{ file.exists ? "present" : "missing" }}</span>
            <small>{{ file.role || "package boundary" }}</small>
            <code>{{ file.relative_path || file.path || "path not loaded" }}</code>
          </div>
          <div v-for="offender in connectExternalPackageOffenders.slice(0, 3)" :key="`${offender.path}:${offender.module}`" class="blocked">
            <strong>{{ offender.module || "forbidden module" }}</strong>
            <span>offender</span>
            <small>external package must not import CBN runtime</small>
            <code>{{ offender.path || "path not loaded" }}</code>
          </div>
          <span v-if="!connectExternalPackageFiles.length && !connectExternalPackageOffenders.length">No external package health loaded</span>
        </div>
        <div class="contract-status-grid">
          <div>
            <span>Internal contract</span>
            <strong>{{ connectContractSummary.protocolName }}</strong>
          </div>
          <div>
            <span>Route ready</span>
            <strong>{{ connectContractSummary.routeReady }}</strong>
          </div>
          <div>
            <span>Blocked</span>
            <strong>{{ connectContractSummary.blockedRoutes }}</strong>
          </div>
        </div>
        <div class="contract-section-list">
          <div v-for="section in connectContractSummary.sections" :key="`connect-${section.id}`">
            <strong>{{ section.title }}</strong>
            <span>{{ section.kind }}</span>
            <small>{{ section.owner }}</small>
            <code>{{ section.scope }}</code>
            <em>{{ section.required }}</em>
          </div>
        </div>
        <div class="agent-summary">
          <span :class="['pill-inline', connectAgentBundle.ok ? 'ok' : 'blocked']">{{ connectAgentBundle.status || "agent nodes not loaded" }}</span>
          <span>{{ connectAgentCards.length }} cards</span>
          <span>{{ connectAgentHarnesses.length }} harnesses</span>
          <span>{{ connectAgentTasks.length }} tasks</span>
        </div>
        <div class="section-title"><Braces :size="15" /> Direct CLI Readiness</div>
        <div class="contract-status-grid">
          <div>
            <span>Status</span>
            <strong>{{ directCliSummary.status }}</strong>
          </div>
          <div>
            <span>Profiles/actions</span>
            <strong>{{ directCliSummary.profiles }}</strong>
          </div>
          <div>
            <span>Capabilities</span>
            <strong>{{ directCliSummary.capabilities }}</strong>
          </div>
          <div>
            <span>Parser</span>
            <strong>{{ directCliSummary.parser }}</strong>
          </div>
          <div>
            <span>Fixture cases</span>
            <strong>{{ directCliSummary.fixtures }}</strong>
          </div>
          <div>
            <span>Recovery</span>
            <strong>{{ directCliSummary.recovery }}</strong>
          </div>
          <div>
            <span>Live gates</span>
            <strong>{{ directCliSummary.gated }}</strong>
          </div>
        </div>
        <div class="protocol-grid">
          <div v-for="profile in directCliSummary.rows" :key="`direct-${profile.profile}`">
            <strong>{{ profile.profile }}</strong>
            <span>{{ profile.status }}</span>
            <code>{{ profile.capabilities }} verified</code>
            <small>{{ profile.setup }} setup · {{ profile.gated }} gated</small>
          </div>
          <span v-if="!directCliSummary.rows.length">No direct CLI readiness loaded</span>
        </div>
        <div class="evidence-row">
          <span :class="['pill-inline', directCliParity.status.includes('parity') || directCliParity.status.includes('one-shot') ? 'ok' : 'blocked']">
            {{ directCliParity.status }}
          </span>
          <span>{{ directCliParity.detail }}</span>
        </div>
        <div class="request-sequence">
          <div v-for="item in directCliSummary.recoveryRows" :key="item.errorType">
            <code>{{ item.status }}</code>
            <span>{{ item.errorType }}</span>
            <small>{{ item.cases }}</small>
            <em>{{ item.nextAction }}</em>
          </div>
          <span v-if="!directCliSummary.recoveryRows.length">No direct CLI recovery matrix loaded</span>
        </div>
        <div class="quickstart-grid">
          <div>
            <span>Agent session</span>
            <code>{{ connectAgentBundle.session?.agent_id || "not loaded" }}</code>
          </div>
          <div>
            <span>Agent bridge</span>
            <code>{{ connectAgentBundle.bridge_message?.channel || connectAgentBundle.bridge_message_channel || "not loaded" }}</code>
          </div>
          <div>
            <span>Harness run</span>
            <code>{{ connectSummary.harnessRunEndpoint || "not loaded" }}</code>
          </div>
          <div>
            <span>Harness bridge</span>
            <code>{{ connectSummary.harnessBridgeChannel || "not loaded" }}</code>
          </div>
        </div>
        <div class="endpoint-list">
          <div v-for="route in connectHarnessRoutes.slice(0, 4)" :key="String(route.task_id || route.uses || route.communication)">
            <code>{{ route.task_id || "route" }}</code>
            <span>{{ route.uses || "workflow task" }} · {{ route.communication || "BridgeMessage" }}</span>
          </div>
          <span v-if="!connectHarnessRoutes.length">No harness routes loaded</span>
        </div>
        <div class="agent-card-list">
          <div v-for="card in connectAgentCards.slice(0, 4)" :key="card.id || card.title" class="agent-card">
            <strong>{{ card.title || card.id || "AgentCard" }}</strong>
            <span>{{ card.status || card.risk || "unknown" }}</span>
            <code>{{ card.role || card.id || "agent" }} · {{ (card.capabilities || []).slice(0, 3).join(", ") || "BridgeMessage" }}</code>
          </div>
          <span v-if="!connectAgentCards.length">No agent cards loaded</span>
        </div>
        <div class="agent-card-list">
          <div v-for="harness in connectAgentHarnesses.slice(0, 4)" :key="harness.id || harness.agent_id" class="agent-card">
            <strong>{{ harness.id || "AgentHarness" }}</strong>
            <span>{{ harness.kind || "AgentHarness" }}</span>
            <code>{{ (harness.accepts || []).join(", ") || "BridgeMessage" }} -> {{ (harness.emits || []).join(", ") || "BridgeMessage" }}</code>
          </div>
          <span v-if="!connectAgentHarnesses.length">No agent harnesses loaded</span>
        </div>
        <div class="artifact-strip">
          <code v-for="capabilityId in connectSummary.generatedCapabilities" :key="capabilityId">{{ capabilityId }}</code>
          <span v-if="!connectSummary.generatedCapabilities.length">No external capabilities loaded</span>
        </div>
        <div class="endpoint-list">
          <div v-for="importer in connectRegistrationImporters.slice(0, 6)" :key="importer.id || importer.entrypoint">
            <code>{{ importer.entrypoint || importer.id || "cbn import" }}</code>
            <span>{{ importer.title || "CLI registration" }} · {{ importer.default_side_effects || "none" }}</span>
          </div>
          <span v-if="!connectRegistrationImporters.length">No registration importers loaded</span>
        </div>
        <div class="demo-stage-list">
          <div v-for="step in connectDemoPlaybookSteps.slice(0, 6)" :key="step.id || step.title">
            <strong>{{ step.title || step.id || "Demo step" }}</strong>
            <span>{{ step.action || "action" }}</span>
            <small>{{ step.intent || "demo flow" }}</small>
            <code>{{ step.command || step.success_signal || step.target || "ready" }}</code>
          </div>
          <span v-if="!connectDemoPlaybookSteps.length">No demo playbook loaded</span>
        </div>
        <div class="demo-stage-list">
          <div v-for="stage in connectDemoStages" :key="stage.id || stage.title">
            <strong>{{ stage.title || stage.id || "Demo stage" }}</strong>
            <span>{{ stage.id || "stage" }}</span>
            <small>{{ stage.proves || "demo evidence not loaded" }}</small>
            <code>{{ demoStageDetail(stage) }}</code>
          </div>
          <span v-if="!connectDemoStages.length">No demo readiness stages loaded</span>
        </div>
        <div class="quickstart-grid">
          <div>
            <span>Killer demo</span>
            <code>{{ connectSummary.demoEndpoint || "not loaded" }}</code>
          </div>
          <div>
            <span>Agent nodes</span>
            <code>{{ connectSummary.agentNodesEndpoint || "not loaded" }}</code>
          </div>
          <div>
            <span>Protocol exports</span>
            <code>{{ connectSummary.protocolExportsEndpoint || "not loaded" }}</code>
          </div>
          <div>
            <span>Plan request</span>
            <code>{{ connectSummary.planEndpoint || "not loaded" }}</code>
          </div>
          <div>
            <span>Run workflow</span>
            <code>{{ connectSummary.runEndpoint || "not loaded" }}</code>
          </div>
        </div>
        <div class="section-title"><ClipboardList :size="15" /> First-Call Sequence</div>
        <div class="request-sequence">
          <div v-for="step in quickstartSequenceSteps.slice(0, 10)" :key="step.id || step.request_id || step.order">
            <code>{{ step.order ?? "step" }}</code>
            <span>{{ step.title || step.id || step.request_id || "First call" }}</span>
            <small>{{ step.intent || step.success_signal || "consumer handoff" }}</small>
            <em>{{ step.method || step.kind || "step" }} {{ step.url || step.target || (step.request_ids || []).join(", ") || "not loaded" }}</em>
          </div>
          <span v-if="!quickstartSequenceSteps.length">No first-call sequence loaded</span>
        </div>
        <div class="section-title"><FileJson :size="15" /> Raw Quickstart Requests</div>
        <div class="request-sequence">
          <div v-for="request in quickstartRequests.slice(0, 13)" :key="request.id || request.url">
            <code>{{ request.method || "GET" }}</code>
            <span>{{ request.id || "request" }}</span>
            <small>{{ request.url || "not loaded" }}</small>
            <em>{{ request.curl || "curl not loaded" }}</em>
          </div>
          <span v-if="!quickstartRequests.length">No quickstart requests loaded</span>
        </div>
        <div class="snippet-list">
          <div v-for="snippet in quickstartSdkSnippets.slice(0, 4)" :key="snippet.id || snippet.language">
            <header>
              <strong>{{ snippet.title || snippet.id || "Consumer snippet" }}</strong>
              <span>{{ snippet.language || "code" }} · {{ snippet.runtime || "runtime" }}</span>
              <button title="Copy consumer snippet" @click="copyText(`snippet-${snippet.id || snippet.language}`, snippet.code || '')">
                <Copy :size="14" /> {{ copiedScript === `snippet-${snippet.id || snippet.language}` ? "Copied" : "Copy" }}
              </button>
            </header>
            <small>{{ snippet.entrypoint || "run_workflow" }} · {{ (snippet.uses_request_ids || []).join(" -> ") || "quickstart" }}</small>
            <code>{{ snippet.code || "snippet not loaded" }}</code>
          </div>
          <span v-if="!quickstartSdkSnippets.length">No consumer snippets loaded</span>
        </div>
        <div class="acceptance-list">
          <div v-for="check in acceptanceChecks.slice(0, 13)" :key="check.id || check.request_id" :class="acceptanceResult(check)?.status || 'pending'">
            <code>{{ check.request_id || "request" }}</code>
            <span>{{ check.id || "check" }}</span>
            <small>{{ check.proves || "acceptance evidence not loaded" }}</small>
            <b>{{ acceptanceResult(check)?.status || "pending" }}</b>
            <em>{{ pretty(acceptanceResult(check)?.evidence || check.expect) }}</em>
            <strong v-if="acceptanceResult(check)?.error">{{ acceptanceResult(check)?.error }}</strong>
          </div>
          <span v-if="!acceptanceChecks.length">No acceptance checklist loaded</span>
        </div>
        <div class="curl-script-preview">
          <div>
            <span>cURL script</span>
            <button title="Copy cURL script" :disabled="!connectSummary.curlScript" @click="copyText('curl', connectSummary.curlScript)">
              <Copy :size="14" /> {{ copiedScript === "curl" ? "Copied" : "Copy" }}
            </button>
          </div>
          <code>{{ connectSummary.curlScript || "not loaded" }}</code>
        </div>
        <div class="curl-script-preview">
          <div>
            <span>PowerShell script</span>
            <button title="Copy PowerShell script" :disabled="!connectSummary.powershellScript" @click="copyText('powershell', connectSummary.powershellScript)">
              <Copy :size="14" /> {{ copiedScript === "powershell" ? "Copied" : "Copy" }}
            </button>
          </div>
          <code>{{ connectSummary.powershellScript || "not loaded" }}</code>
        </div>
        <div class="next-command-list">
          <div v-for="(command, index) in connectNextCommands.slice(0, 8)" :key="command">
            <span>{{ index === 0 ? "Recommended" : `Next ${index + 1}` }}</span>
            <code>{{ command }}</code>
            <button title="Copy next command" @click="copyText(`next-${index}`, command)">
              <Copy :size="14" /> {{ copiedScript === `next-${index}` ? "Copied" : "Copy" }}
            </button>
          </div>
          <span v-if="!connectNextCommands.length">No next commands loaded</span>
        </div>
        <div class="endpoint-list">
          <div v-for="endpoint in connectEndpoints.slice(0, 6)" :key="`${endpoint.method}:${endpoint.path}`">
            <code>{{ endpoint.method }}</code>
            <span>{{ endpoint.path }}</span>
          </div>
        </div>
        <pre>{{ pretty({ daemon_verify: networkVerifyReport, import_catalog: importCatalog, direct_cli_readiness: directCliReadiness, one_shot_direct_cli_readiness: connectPackage?.direct_cli_readiness, direct_cli_parity: directCliParity, direct_quickstart: directQuickstart, quickstart_parity: quickstartParity, direct_entry_profile: entryProfile, entry_profile_parity: entryProfileParity, direct_network_harness_agent: directNetworkHarnessAgent, network_harness_parity: networkHarnessParity, direct_sdk_bootstrap: directSdkBootstrap, sdk_bootstrap_parity: sdkBootstrapParity, direct_launch_contract: launchContract, launch_contract_parity: launchContractParity, direct_acceptance: directAcceptance, acceptance_parity: acceptanceParity, direct_readiness: directReadiness, readiness_parity: readinessParity, network_entry_profile: connectPackage?.network_entry_profile, network_harness_agent: connectNetworkHarnessAgent, consumer_sdk_bootstrap: connectPackage?.consumer_sdk_bootstrap, consumer_launch_contract: connectPackage?.consumer_launch_contract, mvp_readiness: connectPackage?.mvp_readiness, mvp_presenter_brief: connectPackage?.mvp_presenter_brief, workflow_studio: connectPackage?.workflow_studio, demo_readiness: connectPackage?.demo_readiness, demo_playbook: connectPackage?.demo_playbook, setup_guidance: connectPackage?.setup_guidance, registration_surface: connectPackage?.registration_surface, agent_workflow_request: connectPackage?.agent_workflow_request, agent_node_bundle: connectPackage?.agent_node_bundle, consumer_quickstart: connectPackage?.consumer_quickstart, acceptance: connectPackage?.acceptance, protocols: connectPackage?.protocols, plugins: connectPackage?.plugins, contracts: connectPackage?.contracts, next_commands: connectPackage?.next_commands }) }}</pre>
      </section>
      <section>
        <div class="section-title"><Rocket :size="15" /> Killer Demo</div>
        <div class="evidence-summary">
          <div>
            <span>Status</span>
            <strong>{{ evidenceSummary.status }}</strong>
          </div>
          <div>
            <span>Workflow</span>
            <strong>{{ evidenceSummary.workflowStatus }}</strong>
          </div>
          <div>
            <span>Stages</span>
            <strong>{{ evidenceSummary.completedStages }}/{{ demoReport?.stages?.length || 0 }}</strong>
          </div>
          <div>
            <span>Blocked</span>
            <strong>{{ evidenceSummary.blockedStages }}</strong>
          </div>
          <div>
            <span>Routes</span>
            <strong>{{ evidenceSummary.routeCount }}</strong>
          </div>
          <div>
            <span>Handoffs</span>
            <strong>{{ evidenceSummary.communicationHandoffs }}</strong>
          </div>
          <div>
            <span>Messages</span>
            <strong>{{ evidenceSummary.communicationValid }}</strong>
          </div>
          <div>
            <span>Artifacts</span>
            <strong>{{ evidenceSummary.taskArtifactCount }}</strong>
          </div>
          <div>
            <span>Events</span>
            <strong>{{ evidenceSummary.eventCount }}</strong>
          </div>
          <div>
            <span>Audit</span>
            <strong>{{ evidenceSummary.auditCount }}</strong>
          </div>
        </div>
        <div class="evidence-row">
          <span :class="['pill-inline', evidenceSummary.smokeOk === 'pass' ? 'ok' : 'blocked']">smoke {{ evidenceSummary.smokeOk }}</span>
          <span :class="['pill-inline', evidenceSummary.bridgeLabOk === 'pass' ? 'ok' : 'blocked']">bridge lab {{ evidenceSummary.bridgeLabOk }}</span>
          <span :class="['pill-inline', evidenceSummary.communicationTraceStatus === 'ready' ? 'ok' : 'blocked']">trace {{ evidenceSummary.communicationTraceStatus }}</span>
        </div>
        <div class="section-title"><Braces :size="15" /> CLI-CLI Trace</div>
        <div class="request-sequence">
          <div v-for="handoff in demoCommunicationHandoffs" :key="`${handoff.producer_task}:${handoff.consumer_task}:${handoff.selector}`">
            <code>{{ handoff.index ?? "route" }}</code>
            <span>{{ handoff.producer_task || "producer" }} -> {{ handoff.consumer_task || "consumer" }}</span>
            <small>{{ handoff.communication || "BridgeMessage argsFrom" }} · {{ handoff.message_valid ? "valid" : "invalid" }} · {{ handoff.selected_type || "value" }}</small>
            <em>{{ handoff.selector || "selector" }} => {{ handoff.selected_preview || handoff.resolved_arg_preview || "not loaded" }}</em>
          </div>
          <span v-if="!demoCommunicationHandoffs.length">No CLI-CLI trace loaded</span>
        </div>
        <div class="artifact-strip">
          <code v-for="artifactId in evidenceSummary.artifactIds" :key="artifactId">{{ artifactId }}</code>
          <span v-if="!evidenceSummary.artifactIds.length">No demo artifacts yet</span>
        </div>
        <div class="section-title"><Network :size="15" /> Protocol Export</div>
        <div class="protocol-grid">
          <div>
            <strong>MCP</strong>
            <span>{{ protocolSummary.mcpWorkflowTools }} workflow tools</span>
            <code>smoke {{ protocolSummary.mcpSmoke }}</code>
            <small>wire {{ protocolSummary.wireCompatible.mcp }}</small>
          </div>
          <div>
            <strong>A2A</strong>
            <span>{{ protocolSummary.a2aSkills }} skills</span>
            <code>smoke {{ protocolSummary.a2aSmoke }}</code>
            <small>wire {{ protocolSummary.wireCompatible.a2a }}</small>
          </div>
          <div>
            <strong>ACP</strong>
            <span>{{ protocolSummary.acpWorkflows }} workflows</span>
            <code>smoke {{ protocolSummary.acpSmoke }}</code>
            <small>wire {{ protocolSummary.wireCompatible.acp }}</small>
          </div>
        </div>
        <div class="evidence-row">
          <span :class="['pill-inline', protocolSummary.smokeFailures === 0 && protocolSummary.smokeChecks > 0 ? 'ok' : 'blocked']">
            protocol smoke {{ protocolSummary.smokeChecks - protocolSummary.smokeFailures }}/{{ protocolSummary.smokeChecks }}
          </span>
        </div>
        <div class="contract-status-grid">
          <div>
            <span>Direct wire</span>
            <strong>{{ protocolWireSummary.status }}</strong>
          </div>
          <div>
            <span>Wire protocols</span>
            <strong>{{ protocolWireSummary.wireCount }}</strong>
          </div>
          <div>
            <span>Wire checks</span>
            <strong>{{ protocolWireSummary.checks }}</strong>
          </div>
          <div>
            <span>Wire failures</span>
            <strong>{{ protocolWireSummary.failures }}</strong>
          </div>
        </div>
        <div class="protocol-grid">
          <div v-for="protocol in protocolWireSummary.protocols" :key="`wire-${protocol.id}`">
            <strong>{{ protocol.id }}</strong>
            <span>{{ protocol.status }}</span>
            <code>{{ protocol.checks }} checks</code>
          </div>
          <span v-if="!protocolWireSummary.protocols.length">No direct wire conformance report loaded</span>
        </div>
        <div class="quickstart-grid">
          <div>
            <span>Boundary</span>
            <code>{{ protocolWireSummary.detail }}</code>
          </div>
          <div>
            <span>Target</span>
            <code>{{ protocolWireReport?.target || "not loaded" }}</code>
          </div>
          <div>
            <span>Capability</span>
            <code>{{ protocolWireReport?.capability_id || "not loaded" }}</code>
          </div>
          <div>
            <span>Next</span>
            <code>{{ (protocolWireReport?.next_steps || []).slice(0, 1).join(" ") || "not loaded" }}</code>
          </div>
        </div>
        <div class="stage-list">
          <div v-for="stage in demoReport?.stages || []" :key="stage.id" class="stage-row">
            <span :class="['dot', stage.status]"></span>
            <span>{{ stage.title }}</span>
            <code>{{ stage.status }}</code>
          </div>
        </div>
        <pre>{{ pretty({ demo_summary: demoReport?.summary || demoReport, direct_wire_conformance: protocolWireReport }) }}</pre>
      </section>
    </aside>

    <footer class="evidence-dock">
      <section>
        <div class="section-title"><Activity :size="15" /> Events</div>
        <pre>{{ pretty(dock.events) }}</pre>
      </section>
      <section>
        <div class="section-title"><History :size="15" /> Audit</div>
        <pre>{{ pretty(dock.audit) }}</pre>
      </section>
      <section>
        <div class="section-title"><FileJson :size="15" /> Artifacts</div>
        <pre>{{ pretty(dock.artifacts) }}</pre>
      </section>
    </footer>
  </main>
</template>
