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
  AdapterAgentNodeBundle,
  AgentWorkflowRequestPlan,
  BridgeContractReport,
  BridgeContractSection,
  BridgeContractSummary,
  ConnectionAcceptanceCheck,
  ConnectSummary,
  DockState,
  EvidenceSummary,
  KillerDemoReport,
  NetworkConnectionAcceptanceReport,
  NetworkConnectPackage,
  ProtocolSummary,
  QuickstartRequest,
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
const connectPackage = ref<NetworkConnectPackage | null>(null);
const networkVerifyReport = ref<NetworkConnectionAcceptanceReport | null>(null);
const health = ref<unknown>(null);
const selectedTaskId = ref("");
const loading = ref("");
const error = ref("");
const copiedScript = ref("");
const acceptanceResults = ref<AcceptanceExecutionResult[]>([]);
const dock = reactive<DockState>({ events: [], audit: [], artifacts: [] });

const api = computed(() => new StudioApi(config));
const tasks = computed<WorkflowTask[]>(() => (Array.isArray(workflow.value?.tasks) ? workflow.value.tasks : []));
const selectedTask = computed(() => tasks.value.find((task) => task.id === selectedTaskId.value) ?? tasks.value[0]);
const selectedRoutes = computed(() => selectedTask.value?.argsFrom ?? []);
const agentCards = computed(() => (Array.isArray(agentBundle.value?.cards) ? agentBundle.value.cards : []));
const agentTasks = computed(() => (Array.isArray(agentBundle.value?.tasks) ? agentBundle.value.tasks : []));
const agentHandoffs = computed(() => agentBundle.value?.source_coordination_plan?.handoffs ?? []);
const evidenceSummary = computed<EvidenceSummary>(() => summarizeEvidence(demoReport.value, dock));
const protocolSummary = computed<ProtocolSummary>(() => summarizeProtocols(demoReport.value));
const bridgeContractSummary = computed<BridgeContractSummary>(() => summarizeBridgeContract(contract.value));
const workflowRequestSummary = computed<WorkflowRequestSummary>(() => summarizeWorkflowRequestPlan(workflowRequestPlan.value));
const connectSummary = computed<ConnectSummary>(() => summarizeConnectPackage(connectPackage.value));
const connectContractSummary = computed<BridgeContractSummary>(() => summarizeConnectContracts(connectPackage.value));
const connectAgentBundle = computed(() => connectPackage.value?.agent_node_bundle ?? {});
const connectAgentCards = computed(() => (Array.isArray(connectAgentBundle.value.cards) ? connectAgentBundle.value.cards : []));
const connectAgentHarnesses = computed(() => (Array.isArray(connectAgentBundle.value.harnesses) ? connectAgentBundle.value.harnesses : []));
const connectAgentTasks = computed(() => (Array.isArray(connectAgentBundle.value.tasks) ? connectAgentBundle.value.tasks : []));
const connectEndpoints = computed(() => (Array.isArray(connectPackage.value?.daemon_endpoints) ? connectPackage.value.daemon_endpoints : []));
const quickstartRequests = computed<QuickstartRequest[]>(() =>
  Array.isArray(connectPackage.value?.consumer_quickstart?.requests)
    ? connectPackage.value.consumer_quickstart.requests
    : [],
);
const acceptanceChecks = computed<ConnectionAcceptanceCheck[]>(() => {
  const acceptance = connectPackage.value?.acceptance ?? connectPackage.value?.consumer_quickstart?.acceptance;
  return Array.isArray(acceptance?.checks) ? acceptance.checks : [];
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

async function inspectConnectPackage() {
  connectPackage.value = (await call("connect", () => api.value.networkConnectPackage())) as NetworkConnectPackage;
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
    refreshEvidence(),
  ]);
}

function pretty(payload: unknown): string {
  return JSON.stringify(payload ?? null, null, 2);
}

function summarizeEvidence(report: KillerDemoReport | null, evidenceDock: DockState): EvidenceSummary {
  const summary = report?.summary ?? {};
  const evidence = report?.evidence ?? {};
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
  };
}

function summarizeConnectPackage(payload: NetworkConnectPackage | null): ConnectSummary {
  const external = payload?.contracts?.external ?? {};
  const summary = payload?.summary ?? {};
  const studio = payload?.workflow_studio ?? {};
  const demo = payload?.demo_readiness ?? {};
  const quickstart = payload?.consumer_quickstart ?? {};
  const acceptance = payload?.acceptance ?? quickstart.acceptance ?? {};
  const headers = quickstart.required_headers ?? {};
  return {
    status: payload?.ok ? "ready" : payload ? "needs attention" : "not loaded",
    externalProtocol: external.protocol ?? "unknown",
    acceptedKinds: Array.isArray(external.accepted_kinds) ? external.accepted_kinds.join(" + ") : "unknown",
    generatedCapabilities: Array.isArray(external.generated_capability_ids) ? external.generated_capability_ids.slice(0, 4) : [],
    bridgeRoutes: numberValue(summary.bridge_route_count) ?? 0,
    endpointCount: Array.isArray(payload?.daemon_endpoints) ? payload.daemon_endpoints.length : 0,
    protocolExports: numberValue(summary.protocol_export_count) ?? 0,
    agentCards: numberValue(summary.agent_card_count) ?? 0,
    demoReadinessStatus: stringValue(demo.status) ?? "not loaded",
    demoStageCount: numberValue(demo.stage_count) ?? 0,
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
        <button title="Load one-shot network connection package" @click="inspectConnectPackage">
          <Network :size="16" /> Connect
        </button>
        <button title="Open maintainer console" @click="openDashboardConsole">
          <Wrench :size="16" /> Console
        </button>
      </div>

      <section class="status-panel">
        <div class="section-title"><Gauge :size="15" /> Health</div>
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
        </div>
        <div class="artifact-strip">
          <code v-if="workflowRequestSummary.runCli">{{ workflowRequestSummary.runCli }}</code>
          <span v-else>No workflow request plan loaded</span>
        </div>
        <pre>{{ pretty({ request: workflowRequestPlan?.request, run: workflowRequestPlan?.run, bridge_routes: workflowRequestPlan?.bridge_routes, bridge_message: workflowRequestPlan?.bridge_message }) }}</pre>
      </section>
      <section>
        <div class="section-title"><Network :size="15" /> Connect Package</div>
        <div class="connect-summary">
          <div>
            <span>Status</span>
            <strong>{{ connectSummary.status }}</strong>
          </div>
          <div>
            <span>External</span>
            <strong>{{ connectSummary.externalProtocol }}</strong>
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
            <span>Demo</span>
            <strong>{{ connectSummary.demoStageCount }}</strong>
          </div>
        </div>
        <div class="evidence-row">
          <span :class="['pill-inline', connectPackage?.ok ? 'ok' : 'blocked']">{{ connectSummary.acceptedKinds }}</span>
          <span class="pill-inline">{{ connectSummary.nextAction }}</span>
          <span class="pill-inline">{{ connectSummary.studioToken }}</span>
          <span class="pill-inline">{{ connectSummary.studioMode }}</span>
          <span class="pill-inline">{{ connectSummary.quickstartStatus }}</span>
          <span class="pill-inline">{{ connectSummary.authHeaderStatus }}</span>
          <span class="pill-inline">{{ connectSummary.quickstartRequestCount }} requests</span>
          <span class="pill-inline">{{ connectSummary.acceptanceStatus }}</span>
          <span class="pill-inline">{{ connectSummary.acceptanceCheckCount }} checks</span>
          <span class="pill-inline">{{ connectSummary.demoReadinessStatus }}</span>
          <span :class="['pill-inline', acceptanceRunSummary.status === 'passed' ? 'ok' : acceptanceRunSummary.status === 'failed' ? 'blocked' : '']">
            {{ acceptanceRunSummary.status }}
          </span>
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
          <code v-if="connectSummary.studioLink">{{ connectSummary.studioLink }}</code>
          <span v-else>No Workflow Studio link loaded</span>
        </div>
        <div class="acceptance-summary">
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
        <div class="quickstart-grid">
          <div>
            <span>Agent session</span>
            <code>{{ connectAgentBundle.session?.agent_id || "not loaded" }}</code>
          </div>
          <div>
            <span>Agent bridge</span>
            <code>{{ connectAgentBundle.bridge_message?.channel || connectAgentBundle.bridge_message_channel || "not loaded" }}</code>
          </div>
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
        <div class="request-sequence">
          <div v-for="request in quickstartRequests.slice(0, 10)" :key="request.id || request.url">
            <code>{{ request.method || "GET" }}</code>
            <span>{{ request.id || "request" }}</span>
            <small>{{ request.url || "not loaded" }}</small>
            <em>{{ request.curl || "curl not loaded" }}</em>
          </div>
          <span v-if="!quickstartRequests.length">No quickstart requests loaded</span>
        </div>
        <div class="acceptance-list">
          <div v-for="check in acceptanceChecks.slice(0, 10)" :key="check.id || check.request_id" :class="acceptanceResult(check)?.status || 'pending'">
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
        <div class="endpoint-list">
          <div v-for="endpoint in connectEndpoints.slice(0, 6)" :key="`${endpoint.method}:${endpoint.path}`">
            <code>{{ endpoint.method }}</code>
            <span>{{ endpoint.path }}</span>
          </div>
        </div>
        <pre>{{ pretty({ daemon_verify: networkVerifyReport, workflow_studio: connectPackage?.workflow_studio, demo_readiness: connectPackage?.demo_readiness, agent_node_bundle: connectPackage?.agent_node_bundle, consumer_quickstart: connectPackage?.consumer_quickstart, acceptance: connectPackage?.acceptance, protocols: connectPackage?.protocols, contracts: connectPackage?.contracts, next_commands: connectPackage?.next_commands }) }}</pre>
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
        <div class="stage-list">
          <div v-for="stage in demoReport?.stages || []" :key="stage.id" class="stage-row">
            <span :class="['dot', stage.status]"></span>
            <span>{{ stage.title }}</span>
            <code>{{ stage.status }}</code>
          </div>
        </div>
        <pre>{{ pretty(demoReport?.summary || demoReport) }}</pre>
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
