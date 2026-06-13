<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch, type Component } from "vue";
import {
  Archive,
  Bell,
  Boxes,
  BrainCircuit,
  CheckCircle2,
  ChevronDown,
  CircleDot,
  Code2,
  Command,
  FileJson,
  Gauge,
  HardDriveDownload,
  Layers3,
  Library,
  ListChecks,
  Maximize2,
  Minus,
  Network,
  PackageCheck,
  PanelRight,
  Play,
  Plus,
  RefreshCw,
  Rocket,
  Search,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  TerminalSquare,
  UploadCloud,
  User,
  Waypoints,
  Workflow,
  X,
  Zap,
} from "lucide-vue-next";
import { StudioApi } from "./api";
import { mountWorkflowGraph, type StudioGraph } from "./graph";
import { mountMiniGraph } from "./MiniGraph";
import { useDraggableCard } from "./composables/useDraggableCard";
import { layoutStore } from "./composables/layoutStore";
import type {
  AcceptanceExecutionResult,
  AdapterAgentNodeBundle,
  AdapterAgentToolCallPlan,
  AgentWorkflowRequestPlan,
  BridgeContractReport,
  CliRegistrationSurface,
  ConnectSummary,
  ConnectionAcceptanceCheck,
  ConsumerLaunchContract,
  ConsumerSdkBootstrap,
  DirectCliReadinessReport,
  DockState,
  KillerDemoReport,
  KillerMvpReadiness,
  NetworkConsumerManifest,
  NetworkConnectPackage,
  NetworkConnectionAcceptance,
  NetworkConnectionAcceptanceReport,
  NetworkConnectQuickstart,
  NetworkEntryProfile,
  NetworkHarnessAgent,
  ProtocolWireConformanceReport,
  StudioConfig,
  WorkflowInspect,
  WorkflowTask,
} from "./types";

type Icon = Component;
type PanelTarget = "registry" | "connect" | "direct" | "market" | "permissions" | "settings";
type PermissionMode = "default" | "auto" | "full";
type ToastTone = "info" | "success" | "warning" | "danger";
type AgentPanelMode = "floating" | "docked" | "minimized";
type LeftNavMode = "threads" | "favorites";

interface DesktopAppBridge {
  getState: () => Promise<DesktopAppState>;
  getWindowState: () => Promise<DesktopWindowState>;
  minimizeWindow: () => Promise<DesktopWindowState>;
  toggleMaximizeWindow: () => Promise<DesktopWindowState>;
  closeWindow: () => Promise<{ ok: boolean }>;
  openExternal: (url: string) => Promise<{ ok: boolean; error?: string }>;
  relaunchDaemon: () => Promise<DesktopAppState["daemon"]>;
  onWindowStateChange: (callback: (state: DesktopWindowState) => void) => () => void;
}

interface DesktopWindowState {
  isMaximized: boolean;
  isMinimized: boolean;
  isFullScreen: boolean;
  bounds: {
    x: number;
    y: number;
    width: number;
    height: number;
  } | null;
}

interface DesktopAppState {
  appName: string;
  appVersion: string;
  daemonUrl: string;
  rendererUrl: string;
  isPackaged: boolean;
  platform: string;
  workspaceRoot: string;
  daemon: {
    mode: string;
    url: string;
    healthy: boolean;
    message: string;
  };
}

declare global {
  interface Window {
    __cbnApp?: DesktopAppBridge;
  }
}

interface SequenceStepView {
  id: string;
  order: number | string;
  title: string;
  method: string;
  target: string;
}

interface RibbonAction {
  id: string;
  label: string;
  level: "L1" | "L2" | "L3" | "L4";
  icon: Icon;
  detail: string;
  target?: PanelTarget | "audit" | "artifacts";
}

interface RibbonGroup {
  id: string;
  title: string;
  tone: "blue" | "teal" | "violet" | "amber" | "green";
  actions: RibbonAction[];
}

interface RibbonTab {
  id: string;
  label: string;
  groups: RibbonGroup[];
}

interface ConversationThread {
  id: string;
  title: string;
  meta: string;
  tone: "active" | "ok" | "warn" | "idle";
}

interface WorkflowCard {
  id: string;
  title: string;
  status: string;
  saved: boolean;
  tasks: WorkflowTask[];
  tools: string[];
  artifacts: ArtifactRow[];
}

interface ArtifactRow {
  id: string;
  name: string;
  kind: string;
  source: string;
  size: string;
  path?: string;
}

interface PluginRow {
  id: string;
  name: string;
  version: string;
  status: string;
  category: string;
  capabilities: string[];
}

interface ToastMessage {
  id: number;
  tone: ToastTone;
  title: string;
  detail: string;
}

const ribbonTabs: RibbonTab[] = [
  {
    id: "workflow",
    label: "Workflow Foundry",
    groups: [
      {
        id: "run",
        title: "运行与验证",
        tone: "green",
        actions: [
          { id: "refresh-run", label: "刷新运行", level: "L3", icon: RefreshCw, detail: "刷新工作区并运行当前 workflow" },
          { id: "demo", label: "演示", level: "L3", icon: Play, detail: "运行 killer demo 并收集演示证据" },
          { id: "contract", label: "契约", level: "L3", icon: FileJson, detail: "查看 ToolManifest、BridgeMessage 与 selector 契约" },
          { id: "setup-plan", label: "入手计划", level: "L2", icon: ListChecks, detail: "首轮初始化、缺失配置与用户引导" },
        ],
      },
      {
        id: "deliver",
        title: "项目资产",
        tone: "amber",
        actions: [
          { id: "outputs", label: "产物", level: "L2", icon: Archive, detail: "查看 workflow 生成的用户产物", target: "artifacts" },
          { id: "preview", label: "预览", level: "L2", icon: Maximize2, detail: "在白板上预览选中产物" },
          { id: "package", label: "打包", level: "L3", icon: PackageCheck, detail: "导出可复用 workflow 包" },
        ],
      },
    ],
  },
  {
    id: "connect",
    label: "CLI Registry",
    groups: [
      {
        id: "registry",
        title: "接入入口",
        tone: "blue",
        actions: [
          { id: "connect", label: "Connect", level: "L2", icon: Network, detail: "外部 CLI 接入 CBN 的主入口", target: "connect" },
          { id: "quick", label: "Quick", level: "L3", icon: Zap, detail: "快速接入脚本和第一通调用", target: "connect" },
          { id: "profile", label: "Profile", level: "L3", icon: SlidersHorizontal, detail: "入口配置、运行画像与能力范围", target: "connect" },
          { id: "harness", label: "Harness", level: "L3", icon: BrainCircuit, detail: "CLI 注册 Agent 与能力梳理 Agent", target: "connect" },
        ],
      },
      {
        id: "ship",
        title: "发布清单",
        tone: "violet",
        actions: [
          { id: "sdk", label: "SDK", level: "L3", icon: Code2, detail: "consumer SDK bootstrap 与调用样例", target: "connect" },
          { id: "manifest", label: "Manifest", level: "L3", icon: FileJson, detail: "生成和校验 capability manifest", target: "connect" },
          { id: "launch", label: "Launch", level: "L3", icon: Rocket, detail: "启动契约、依赖和运行入口", target: "connect" },
          { id: "accept", label: "Accept", level: "L3", icon: CheckCircle2, detail: "验收条件、接入检查和自动验证", target: "connect" },
          { id: "ready", label: "Ready", level: "L3", icon: Gauge, detail: "readiness 状态与演示就绪度", target: "connect" },
          { id: "imports", label: "Imports", level: "L3", icon: HardDriveDownload, detail: "从 CLI、MCP、skills、AgentCard 导入能力", target: "direct" },
          { id: "directwire", label: "DirectWire", level: "L4", icon: Waypoints, detail: "协议兼容与 wire conformance 深层证据", target: "direct" },
        ],
      },
    ],
  },
  {
    id: "cli-market",
    label: "CLI Market",
    groups: [
      {
        id: "browse",
        title: "浏览与发现",
        tone: "teal",
        actions: [
          { id: "market", label: "市场", level: "L2", icon: UploadCloud, detail: "浏览可安装的外部 CLI 与插件", target: "market" },
          { id: "installed", label: "已安装", level: "L2", icon: Boxes, detail: "查看已安装 CLI 与插件能力清单", target: "registry" },
          { id: "market-search", label: "搜索", level: "L3", icon: Search, detail: "按名称、能力、来源搜索插件" },
        ],
      },
      {
        id: "lifecycle",
        title: "安装与更新",
        tone: "green",
        actions: [
          { id: "market-install", label: "安装", level: "L3", icon: HardDriveDownload, detail: "安装排队、阻塞原因与安装计划" },
          { id: "market-update", label: "更新", level: "L3", icon: RefreshCw, detail: "检查更新与升级计划" },
          { id: "market-verify", label: "验证", level: "L3", icon: ShieldCheck, detail: "来源、签名与 live verification" },
        ],
      },
    ],
  },
];

// Stable action lookup so call sites don't depend on tab/group/index order.
function ribbonAction(id: string): RibbonAction {
  for (const tab of ribbonTabs) {
    for (const group of tab.groups) {
      const found = group.actions.find((action) => action.id === id);
      if (found) return found;
    }
  }
  return { id, label: id, level: "L2", icon: Search, detail: "" };
}

const DEFAULT_DAEMON_URL = "http://127.0.0.1:8787";
const DEFAULT_WORKFLOW_PATH = "workflows/cli-anything-macrocli-mermaid-routing.example.json";
const DEFAULT_AGENT_MESSAGE = "Run this workflow as a reusable CLI-CLI harness agent and surface setup gates.";

const config = reactive<StudioConfig>({
  daemonUrl: DEFAULT_DAEMON_URL,
  sessionToken: "",
  workflowPath: DEFAULT_WORKFLOW_PATH,
  agentMessage: DEFAULT_AGENT_MESSAGE,
  dryRun: false,
  confirmed: true,
});

const api = computed(() => new StudioApi(config));
const activeRibbonTab = ref("workflow");
const activeActionId = ref("refresh-run");
const rightPanelTab = ref<PanelTarget>("registry");
const rightPanelOpen = ref(false);
const rightDockPosition = reactive({ x: 0, y: 0 });
const rightDockDrag = reactive({ active: false, offsetX: 0, offsetY: 0 });
const selectedWorkflowId = ref("current");
const expandedWorkflowId = ref("current");
const expandedPluginId = ref("");
const agentPanelMode = ref<AgentPanelMode>("floating");
const ribbonCollapsed = ref(false);
const leftNavCollapsed = ref(false);
const leftNavMode = ref<LeftNavMode>("threads");
const showAudit = ref(false);
const showDiagnostics = ref(false);
const showArtifactsPanel = ref(false);
const artifactStoreTree = ref<Array<Record<string, unknown>>>([]);
const artifactGroups = computed(() => artifactStoreTree.value as Array<{
  producer: string;
  count: number;
  kinds: Array<{ kind: string; count: number; items: Array<Record<string, unknown>> }>;
}>);
const agentEvents = ref<Array<Record<string, unknown>>>([]);
const agentRunning = ref(false);
const conversationThreadsReal = ref<ConversationThread[]>([]);
const currentThreadId = ref("");
const cardRows = ref<Array<Record<string, unknown>>>([]);
const miniGraphHandles = new Map<string, { dispose: () => void }>();
const cliAnythingCatalog = ref<{ status: Record<string, unknown>; catalog: Array<Record<string, unknown>> }>({ status: {}, catalog: [] });
const showCliMarketPanel = ref(false);
const cliMarketQuery = ref("");
const mcpIngressServers = ref<Array<Record<string, unknown>>>([]);
const mcpIngressCommand = ref("python");
const mcpIngressArgs = ref("-m cbn mcp serve --stdio");
const mcpIngressBusy = ref(false);
const installingName = ref("");
const installLines = ref<string[]>([]);
const permissionMode = ref<PermissionMode>("full");
const zoom = ref(100);
const graphCanvasEl = ref<HTMLCanvasElement | null>(null);
let studioGraph: StudioGraph | null = null;
const canvasSurfaceEl = ref<HTMLElement | null>(null);
const viewportW = ref(typeof window !== "undefined" ? window.innerWidth : 1280);
const dragEnabled = computed(() => viewportW.value >= 1280);

const savedAreaEl = ref<HTMLElement | null>(null);
const temporaryAreaEl = ref<HTMLElement | null>(null);
const agentConsoleEl = ref<HTMLElement | null>(null);
const detailPopoverEl = ref<HTMLElement | null>(null);
const artifactsPanelEl = ref<HTMLElement | null>(null);

const draggableCards = useDraggableCards();

function useDraggableCards() {
  const opts = (el: () => HTMLElement | null, storageKey: string, enabled: () => boolean) => ({
    storageKey,
    boundsEl: () => canvasSurfaceEl.value,
    cardEl: el,
    enabled,
  });
  return {
    saved: useDraggableCard(opts(() => savedAreaEl.value, "cbn.studio.card.saved-area", () => dragEnabled.value)),
    temporary: useDraggableCard(opts(() => temporaryAreaEl.value, "cbn.studio.card.temporary-area", () => dragEnabled.value)),
    agent: useDraggableCard(opts(() => agentConsoleEl.value, "cbn.studio.card.agent-console", () => dragEnabled.value && agentPanelMode.value === "floating")),
    detail: useDraggableCard(opts(() => detailPopoverEl.value, "cbn.studio.card.detail-popover", () => dragEnabled.value)),
    artifacts: useDraggableCard(opts(() => artifactsPanelEl.value, "cbn.studio.card.artifacts-panel", () => dragEnabled.value)),
  };
}
const loading = ref("");
const error = ref("");
const copiedText = ref("");
const toasts = ref<ToastMessage[]>([]);
let nextToastId = 1;

const health = ref<unknown>(null);
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
const consumerManifest = ref<NetworkConsumerManifest | null>(null);
const directAcceptance = ref<NetworkConnectionAcceptance | null>(null);
const directReadiness = ref<KillerMvpReadiness | null>(null);
const importCatalog = ref<CliRegistrationSurface | null>(null);
const directCliReadiness = ref<DirectCliReadinessReport | null>(null);
const protocolWireReport = ref<ProtocolWireConformanceReport | null>(null);
const networkVerifyReport = ref<NetworkConnectionAcceptanceReport | null>(null);
const acceptanceResults = ref<AcceptanceExecutionResult[]>([]);
const desktopApp = ref<DesktopAppState | null>(null);
const windowState = ref<DesktopWindowState>({
  isMaximized: false,
  isMinimized: false,
  isFullScreen: false,
  bounds: null,
});
const dock = reactive<DockState>({ events: [], audit: [], artifacts: [] });
let disposeWindowState: (() => void) | null = null;

const activeTab = computed(() => ribbonTabs.find((tab) => tab.id === activeRibbonTab.value) ?? ribbonTabs[0]);
const activeAction = computed(() => {
  for (const tab of ribbonTabs) {
    for (const group of tab.groups) {
      const action = group.actions.find((candidate) => candidate.id === activeActionId.value);
      if (action) return action;
    }
  }
  return ribbonTabs[0].groups[0].actions[0];
});
const activeGroup = computed(() => activeTab.value.groups.find((group) => group.actions.some((action) => action.id === activeAction.value.id)));
const activeTrail = computed(() => [activeTab.value.label, activeGroup.value?.title || "工作区", activeAction.value.label, activeAction.value.level]);
const rightDockStyle = computed(() => ({
  left: `${rightDockPosition.x}px`,
  top: `${rightDockPosition.y}px`,
}));
const tasks = computed<WorkflowTask[]>(() => (Array.isArray(workflow.value?.tasks) ? workflow.value.tasks : []));
const currentWorkflowTitle = computed(() => workflow.value?.title || workflow.value?.workflow_id || "Current Workflow");
const currentWorkflowStatus = computed(() => {
  if (runResult.value) return "运行结果已返回";
  if (demoReport.value?.ok) return "演示已完成";
  if (workflow.value?.valid === false) return "契约异常";
  if (workflow.value?.valid) return "已加载";
  return "等待 daemon";
});
const bridgeRouteCount = computed(() => Number(contract.value?.summary?.route_count ?? connectPackage.value?.summary?.bridge_route_count ?? 0));
const routeReadyCount = computed(() => Number(contract.value?.summary?.route_ready_count ?? 0));
const workflowCards = computed<WorkflowCard[]>(() => {
  const cards: WorkflowCard[] = [
    {
      id: "current",
      title: currentWorkflowTitle.value,
      status: currentWorkflowStatus.value,
      saved: true,
      tasks: tasks.value,
      tools: unique(tasks.value.map((task) => task.uses).filter(Boolean)),
      artifacts: artifactRows.value.slice(0, 4),
    },
  ];
  if (connectPackage.value?.summary) {
    cards.push({
      id: "connect",
      title: "CLI 接入初始化",
      status: String(connectPackage.value.summary.setup_status || connectPackage.value.summary.mvp_readiness_status || "ready"),
      saved: true,
      tasks: [],
      tools: pluginRows.value.slice(0, 5).map((plugin) => plugin.name),
      artifacts: artifactRows.value.slice(0, 2),
    });
  }
  if (demoReport.value) {
    cards.push({
      id: "demo",
      title: "Killer Demo Run",
      status: demoReport.value.ok ? "演示成功" : "演示待处理",
      saved: false,
      tasks: [],
      tools: ["MCP", "A2A", "ACP"].filter((item) => item),
      artifacts: artifactRows.value.slice(0, 3),
    });
  }
  return cards;
});
const selectedWorkflow = computed(() => workflowCards.value.find((card) => card.id === selectedWorkflowId.value) ?? workflowCards.value[0]);
const favoriteWorkflowCards = computed(() =>
  favoriteCards.value.map((c) => ({
    id: String(c.card_id),
    title: String(c.title ?? "收藏工作流"),
    status: `${Number(c.task_count ?? 0)} 节点`,
    saved: true,
    tasks: [],
    tools: [],
    artifacts: [],
  })),
);

const conversationThreads = computed<ConversationThread[]>(() => conversationThreadsReal.value);
const artifactRows = computed<ArtifactRow[]>(() => {
  const rows: ArtifactRow[] = [];
  const demoArtifacts = demoReport.value?.evidence?.task_artifacts ?? [];
  for (const artifact of demoArtifacts) {
    rows.push({
      id: artifact.artifact_id || artifact.path || `demo-${rows.length}`,
      name: artifact.label || artifact.path || artifact.artifact_id || `artifact-${rows.length + 1}`,
      kind: artifact.kind || artifact.content_type || "demo",
      source: "killer demo",
      size: formatBytes(artifact.bytes),
      path: artifact.path,
    });
  }
  for (const artifact of dock.artifacts) {
    const record = asRecord(artifact);
    rows.push({
      id: String(record.artifact_id || record.id || record.path || `artifact-${rows.length}`),
      name: String(record.label || record.name || record.path || record.artifact_id || `artifact-${rows.length + 1}`),
      kind: String(record.kind || record.content_type || "artifact"),
      source: String(record.workflow_id || record.run_id || "artifact store"),
      size: formatBytes(toNumber(record.bytes ?? record.size)),
      path: typeof record.path === "string" ? record.path : undefined,
    });
  }
  if (!rows.length) {
    rows.push(
      { id: "placeholder-html", name: "daily-news-preview.html", kind: "HTML", source: "preview", size: "128 KB" },
      { id: "placeholder-json", name: "summary.json", kind: "JSON", source: "preview", size: "32 KB" },
      { id: "placeholder-prompt", name: "cover-prompt.txt", kind: "TXT", source: "preview", size: "8 KB" },
    );
  }
  return dedupeRows(rows);
});
const pluginRows = computed<PluginRow[]>(() => {
  const rows: PluginRow[] = [];
  const importers = importCatalog.value?.importers ?? connectPackage.value?.registration_surface?.importers ?? [];
  for (const importer of importers) {
    rows.push({
      id: importer.id || importer.entrypoint || `importer-${rows.length}`,
      name: importer.title || importer.id || importer.entrypoint || "CLI Importer",
      version: "registry",
      status: importer.write_gate || importer.confirm_gate ? "需确认" : "就绪",
      category: "importer",
      capabilities: [importer.entrypoint, ...(importer.produces ?? []), ...(importer.accepts ?? [])].filter((item): item is string => Boolean(item)),
    });
  }
  for (const profile of directCliReadiness.value?.profiles ?? []) {
    rows.push({
      id: profile.profile || `profile-${rows.length}`,
      name: profile.profile || "Direct CLI Profile",
      version: `${profile.capability_count ?? 0} caps`,
      status: profile.status || "ready",
      category: "direct-cli",
      capabilities: (profile.capabilities ?? []).map((capability) => capability.capability_id || capability.title || capability.action || "capability"),
    });
  }
  const cliAnything = connectPackage.value?.plugins?.cli_anything;
  if (cliAnything) {
    rows.unshift({
      id: "cli-anything",
      name: "CLI-Anything",
      version: cliAnything.version || "local",
      status: cliAnything.module_split?.status || (cliAnything.entrypoint_available ? "就绪" : "需配置"),
      category: "plugin",
      capabilities: (cliAnything.module_split?.parts ?? []).map((part) => part.id || part.module || "part").slice(0, 8),
    });
  }
  if (!rows.length) {
    rows.push(
      { id: "web-fetcher", name: "web-fetcher", version: "1.2.0", status: "就绪", category: "core CLI", capabilities: ["fetch", "html", "network"] },
      { id: "llm-summarizer", name: "llm-summarizer", version: "2.0.1", status: "就绪", category: "core CLI", capabilities: ["summarize", "prompt", "json"] },
      { id: "file-writer", name: "file-writer", version: "1.1.0", status: "就绪", category: "core CLI", capabilities: ["write", "artifact", "project"] },
      { id: "email-sender", name: "email-sender", version: "1.0.3", status: "需确认", category: "external", capabilities: ["smtp", "notification"] },
    );
  }
  return rows.slice(0, 12);
});
const selectedPlugin = computed(() => pluginRows.value.find((plugin) => plugin.id === expandedPluginId.value) ?? pluginRows.value[0]);
const toolCalls = computed(() => toolCallPlan.value?.tool_calls ?? []);
const setupCheckpoints = computed(() => toolCallPlan.value?.long_running_loop?.checkpoints ?? []);
const agentCards = computed(() => agentBundle.value?.cards ?? connectPackage.value?.agent_node_bundle?.cards ?? []);
const registryMetrics = computed(() => ({
  registered: pluginRows.value.length,
  ready: pluginRows.value.filter((plugin) => /ready|就绪|ok|installed|已/.test(plugin.status)).length,
  gated: pluginRows.value.filter((plugin) => /确认|需|gate|blocked/.test(plugin.status)).length,
  routes: bridgeRouteCount.value,
}));
const connectSummary = computed<Partial<ConnectSummary>>(() => ({
  status: connectPackage.value?.summary?.mvp_readiness_status || connectPackage.value?.summary?.setup_status || "not loaded",
  quickstartStatus: directQuickstart.value?.status || connectPackage.value?.consumer_quickstart?.status || "not loaded",
  entryProfileStatus: entryProfile.value?.status || connectPackage.value?.network_entry_profile?.status || "not loaded",
  networkHarnessStatus: networkHarnessAgent.value?.status || connectPackage.value?.network_harness_agent?.status || "not loaded",
  acceptanceStatus: directAcceptance.value?.status || connectPackage.value?.acceptance?.status || "not loaded",
}));
const agentTasks = computed(() => agentBundle.value?.tasks ?? connectPackage.value?.agent_node_bundle?.tasks ?? []);
const agentHandoffs = computed(() => agentBundle.value?.source_coordination_plan?.handoffs ?? []);
const connectQuickstart = computed<Partial<NetworkConnectQuickstart>>(() => directQuickstart.value ?? connectPackage.value?.consumer_quickstart ?? {});
const quickstartRequests = computed(() => connectQuickstart.value.requests ?? []);
const quickstartSequenceSteps = computed<SequenceStepView[]>(() => {
  const steps = connectQuickstart.value.sequence_steps;
  const source = Array.isArray(steps) && steps.length
    ? steps
    : quickstartRequests.value.map((request, index) => ({
      order: index + 1,
      id: request.id || `request-${index + 1}`,
      title: request.id || "Quickstart request",
      method: request.method || "GET",
      target: request.url,
    }));
  return source.map((step, index) => {
    const record = asRecord(step);
    const id = String(record.id || record.request_id || `step-${index + 1}`);
    return {
      id,
      order: typeof record.order === "number" || typeof record.order === "string" ? record.order : index + 1,
      title: String(record.title || record.intent || id),
      method: String(record.method || record.kind || "GET"),
      target: String(record.url || record.target || record.success_signal || "not loaded"),
    };
  });
});
const connectAcceptance = computed<Partial<NetworkConnectionAcceptance>>(() => directAcceptance.value ?? connectPackage.value?.acceptance ?? connectPackage.value?.consumer_quickstart?.acceptance ?? {});
const acceptanceChecks = computed<ConnectionAcceptanceCheck[]>(() => connectAcceptance.value.checks ?? []);
const acceptanceSummary = computed(() => ({
  total: acceptanceChecks.value.length,
  passed: acceptanceResults.value.filter((result) => result.status === "passed").length,
  failed: acceptanceResults.value.filter((result) => result.status === "failed").length,
  skipped: acceptanceResults.value.filter((result) => result.status === "skipped").length,
}));
const connectNextCommands = computed(() => unique([
  ...(connectPackage.value?.next_commands ?? []),
  ...(connectPackage.value?.consumer_manifest?.next_commands ?? []),
  ...(connectPackage.value?.demo_readiness?.next_commands ?? []),
  ...(connectPackage.value?.demo_playbook?.next_commands ?? []),
  ...(connectPackage.value?.registration_surface?.next_commands ?? []),
]));
const connectDemoStages = computed(() => connectPackage.value?.demo_readiness?.stages ?? []);
const connectAgentCards = computed(() => connectPackage.value?.agent_node_bundle?.cards ?? []);
const connectAgentHarnesses = computed(() => connectPackage.value?.agent_node_bundle?.harnesses ?? []);
const connectHarnessRoutes = computed(() => connectPackage.value?.agent_workflow_request?.bridge_routes ?? []);
const directImporters = computed(() => importCatalog.value?.importers ?? connectPackage.value?.registration_surface?.importers ?? []);
const directCliProfiles = computed(() => directCliReadiness.value?.profiles ?? connectPackage.value?.direct_cli_readiness?.profiles ?? []);
const directCliRecovery = computed(() => directCliReadiness.value?.error_recovery ?? connectPackage.value?.direct_cli_readiness?.error_recovery ?? []);
const directCliMetrics = computed(() => {
  const summary = directCliReadiness.value?.summary ?? connectPackage.value?.direct_cli_readiness?.summary ?? {};
  return {
    status: (directCliReadiness.value?.ok ?? connectPackage.value?.direct_cli_readiness?.ok) ? "ready" : "not loaded",
    profiles: summary.profile_count ?? directCliProfiles.value.length,
    actions: summary.action_count ?? 0,
    capabilities: summary.capability_count ?? 0,
    verified: summary.verified_output_count ?? 0,
    gated: summary.gated_capability_count ?? 0,
    recovery: summary.recovery_type_count ?? directCliRecovery.value.length,
  };
});
const protocolWireSummary = computed(() => {
  const protocols = Object.entries(protocolWireReport.value?.protocols ?? {}).map(([id, report]) => ({
    id,
    status: report.wire_compatible ? "wire compatible" : report.summary?.failed_count ? "blocked" : "pending",
    checks: report.summary?.check_count ?? report.checks?.length ?? 0,
  }));
  return {
    status: protocolWireReport.value?.wire_compatible ? "wire compatible" : protocolWireReport.value ? "needs review" : "not loaded",
    checks: protocolWireReport.value?.summary?.check_count ?? 0,
    failures: protocolWireReport.value?.summary?.failed_count ?? 0,
    protocols,
  };
});
const healthText = computed(() => {
  const record = asRecord(health.value);
  if (record.ok === true) return "System Healthy";
  if (record.status) return String(record.status);
  if (error.value) return "Needs Attention";
  return "Connecting";
});
const appShellText = computed(() => desktopApp.value ? `App · ${desktopApp.value.daemon.mode}` : "App starting");

function setTab(tabId: string) {
  activeRibbonTab.value = tabId;
  const nextTab = activeTab.value;
  activeActionId.value = nextTab.groups[0]?.actions[0]?.id ?? activeActionId.value;
  if (tabId === "workflow") {
    void Promise.allSettled([loadWorkflow(true), loadContract(true)]);
  } else if (tabId === "connect") {
    rightPanelTab.value = "connect";
    void loadConnectPackage(true);
  } else if (tabId === "cli-market") {
    showCliMarketPanel.value = true;
    void loadCliAnythingCatalog();
    void loadMcpIngressServers();
  }
}

function selectWorkflow(id: string) {
  selectedWorkflowId.value = id;
  expandedWorkflowId.value = expandedWorkflowId.value === id ? "" : id;
}

function setPermissionMode(mode: PermissionMode) {
  permissionMode.value = mode;
  // All three modes run LIVE (real execution, no dry-run simulation). They differ
  // only in approval autonomy:
  //   default = every capability blocks for human approval (maximally interactive)
  //   auto    = low-risk auto-runs, risky/external still asks (policy-gated; agent-loop refines)
  //   full    = autonomous long-horizon, no per-step approval (recommended default)
  config.dryRun = false;
  config.confirmed = mode === "full";
  const autonomy = mode === "full" ? "Agent 自主长程" : mode === "auto" ? "风险操作确认" : "每步人工确认";
  notify("权限模式已切换", `${mode} · live · ${autonomy}`, "success");
}

function setZoom(nextZoom: number) {
  zoom.value = Math.min(500, Math.max(10, nextZoom));
  studioGraph?.setZoom(zoom.value / 100);
}

function resetGraphView() {
  zoom.value = 100;
  studioGraph?.resetView();
}

async function selectThread(threadId: string) {
  if (!threadId) return;
  try {
    const thread = await api.value.thread(threadId);
    currentThreadId.value = threadId;
    selectedWorkflowId.value = "current";
    const messages = Array.isArray(thread.messages) ? (thread.messages as Array<Record<string, unknown>>) : [];
    const replay: Record<string, unknown>[] = [];
    for (const m of messages) {
      const role = String(m.role ?? "");
      const payload = m.payload as Record<string, unknown> | undefined;
      if (role === "user") {
        replay.push({ type: "user", text: String(payload?.text ?? "") });
      } else if (payload && typeof payload === "object") {
        replay.push(payload);
      }
    }
    agentEvents.value = replay;
  } catch (err) {
    notify("打开线程", err instanceof Error ? err.message : String(err), "warning");
  }
}

async function loadThreads() {
  try {
    const { threads: rows } = await api.value.threads();
    conversationThreadsReal.value = rows.map((r) => {
      const tone = String(r.tone ?? "idle");
      return {
        id: String(r.thread_id ?? ""),
        title: String(r.title ?? "对话"),
        meta: `${Number(r.message_count ?? 0)} 条 · ${r.has_workflow ? "有工作流" : "对话"}`,
        tone: (["active", "ok", "warn", "idle"].includes(tone) ? tone : "idle") as ConversationThread["tone"],
      };
    });
  } catch {
    // daemon may be down — keep the list as-is
  }
}

function startNewThread() {
  currentThreadId.value = "";
  agentEvents.value = [];
  config.agentMessage = "";
  notify("新对话", "已开始新线程，输入任务后运行。", "info");
}

// Workflow cards (drafts from threads + favorites) — each card IS a workflow graph.
const favoriteCards = computed(() => cardRows.value.filter((c) => c.favorite));
const draftCards = computed(() => cardRows.value.filter((c) => !c.favorite));

async function loadCards() {
  try {
    const { cards } = await api.value.cards();
    cardRows.value = cards;
  } catch {
    // daemon may be down — keep current cards
  }
}

async function favoriteCard(card: Record<string, unknown>) {
  const sourceId = String(card.source_thread_id ?? "");
  if (!sourceId) {
    notify("收藏失败", "该卡片没有来源线程。", "warning");
    return;
  }
  try {
    await api.value.saveFavorite(sourceId, String(card.title ?? "收藏工作流"));
    notify("已收藏", String(card.title ?? "收藏工作流"), "success");
    await loadCards();
  } catch (err) {
    notify("收藏失败", err instanceof Error ? err.message : String(err), "warning");
  }
}

async function reuseCard(card: Record<string, unknown>) {
  const workflow = card.workflow as Record<string, unknown> | undefined;
  if (!workflow) {
    notify("运行失败", "该卡片没有工作流体。", "warning");
    return;
  }
  try {
    const result = (await api.value.runWorkflowBody(workflow)) as Record<string, unknown>;
    notify("重新运行", `工作流已提交：${result?.status ?? "已运行"}`, "success");
  } catch (err) {
    notify("运行失败", err instanceof Error ? err.message : String(err), "warning");
  }
}

function mountCardMiniGraphs() {
  // Dispose handles whose cards disappeared, then mount any new card canvases.
  const liveIds = new Set(cardRows.value.map((c) => String(c.card_id)));
  for (const [id, handle] of miniGraphHandles) {
    if (!liveIds.has(id)) {
      handle.dispose();
      miniGraphHandles.delete(id);
    }
  }
  void nextTick(() => {
    const canvases = document.querySelectorAll<HTMLElement>(".card-mini-graph[data-card-id]");
    canvases.forEach((el) => {
      const cardId = el.getAttribute("data-card-id") || "";
      if (!cardId || miniGraphHandles.has(cardId)) return;
      const card = cardRows.value.find((c) => String(c.card_id) === cardId);
      const workflow = card?.workflow as { spec?: { tasks?: unknown[] } } | undefined;
      const handle = mountMiniGraph(el as HTMLCanvasElement, workflow ?? null);
      if (handle) miniGraphHandles.set(cardId, handle);
    });
  });
}

watch(cardRows, () => mountCardMiniGraphs(), { flush: "post" });

function openRightPanel(tab: PanelTarget) {
  rightPanelTab.value = tab;
  ensureRightDockPosition();
  rightPanelOpen.value = true;
  if (tab === "connect") {    void loadConnectPackage(true);
  } else if (tab === "direct") {
    void Promise.allSettled([loadImportCatalog(true), loadDirectCliReadiness(true), loadProtocolWire(true)]);
  } else if (tab === "registry") {
    void loadImportCatalog(true);
  }
}

function toggleRightPanel(tab: PanelTarget) {
  if (rightPanelOpen.value && rightPanelTab.value === tab) {
    rightPanelOpen.value = false;
  } else {
    openRightPanel(tab);
  }
}

function defaultRightDockPosition() {
  const width = Math.min(windowState.value.isMaximized ? 420 : 392, Math.max(300, window.innerWidth - 72));
  const top = ribbonCollapsed.value ? 58 : windowState.value.isMaximized ? 104 : 94;
  return {
    x: Math.max(12, window.innerWidth - width - 18),
    y: Math.max(12, top),
  };
}

function clampRightDockPosition(x: number, y: number) {
  const dockWidth = Math.min(windowState.value.isMaximized ? 420 : 392, Math.max(300, window.innerWidth - 72));
  // Keep the dock on the right rail so it cannot be dragged over the canvas cards.
  const minX = Math.max(12, Math.floor(window.innerWidth * 0.5));
  const maxX = Math.max(minX, window.innerWidth - dockWidth - 12);
  const maxY = Math.max(12, window.innerHeight - 132);
  return {
    x: Math.min(Math.max(minX, x), maxX),
    y: Math.min(Math.max(48, y), maxY),
  };
}

function saveRightDockPosition() {
  layoutStore.setRightDock({ x: rightDockPosition.x, y: rightDockPosition.y });
}

function ensureRightDockPosition() {
  if (rightDockPosition.x || rightDockPosition.y) {
    const next = clampRightDockPosition(rightDockPosition.x, rightDockPosition.y);
    rightDockPosition.x = next.x;
    rightDockPosition.y = next.y;
    return;
  }
  const next = defaultRightDockPosition();
  rightDockPosition.x = next.x;
  rightDockPosition.y = next.y;
}

function restoreRightDockPosition() {
  const saved = layoutStore.getRightDock();
  if (saved) {
    const next = clampRightDockPosition(saved.x, saved.y);
    rightDockPosition.x = next.x;
    rightDockPosition.y = next.y;
    return;
  }
  const next = defaultRightDockPosition();
  rightDockPosition.x = next.x;
  rightDockPosition.y = next.y;
}

function startRightDockDrag(event: PointerEvent) {
  if (event.button !== 0) return;
  const dockElement = (event.currentTarget as HTMLElement).closest(".floating-dock") as HTMLElement | null;
  if (!dockElement) return;
  const rect = dockElement.getBoundingClientRect();
  rightDockDrag.active = true;
  rightDockDrag.offsetX = event.clientX - rect.left;
  rightDockDrag.offsetY = event.clientY - rect.top;
  dockElement.setPointerCapture?.(event.pointerId);
  event.preventDefault();
}

function handleRightDockDrag(event: PointerEvent) {
  if (!rightDockDrag.active) return;
  const next = clampRightDockPosition(event.clientX - rightDockDrag.offsetX, event.clientY - rightDockDrag.offsetY);
  rightDockPosition.x = next.x;
  rightDockPosition.y = next.y;
}

function stopRightDockDrag() {
  if (!rightDockDrag.active) return;
  rightDockDrag.active = false;
  saveRightDockPosition();
}

function handleWindowResize() {
  viewportW.value = typeof window !== "undefined" ? window.innerWidth : viewportW.value;
  draggableCards.saved.reclamp();
  draggableCards.temporary.reclamp();
  draggableCards.agent.reclamp();
  draggableCards.detail.reclamp();
  draggableCards.artifacts.reclamp();
  if (!rightDockPosition.x && !rightDockPosition.y) return;
  const next = clampRightDockPosition(rightDockPosition.x, rightDockPosition.y);
  rightDockPosition.x = next.x;
  rightDockPosition.y = next.y;
  saveRightDockPosition();
}

function setAgentPanelMode(mode: AgentPanelMode) {
  agentPanelMode.value = agentPanelMode.value === mode && mode !== "floating" ? "floating" : mode;
  notify("Agent 面板状态", agentPanelMode.value, "info");
}

function agentEventSummary(result: unknown): string {
  if (!result || typeof result !== "object") return String(result ?? "");
  const r = result as Record<string, unknown>;
  const content = r.parsed_content ?? r.stdout ?? r.reason ?? r.error;
  if (typeof content === "string" && content) return content.slice(0, 240);
  if (Array.isArray(r.artifacts) && r.artifacts.length) {
    const first = r.artifacts[0] as Record<string, unknown> | undefined;
    return `artifact: ${first?.artifact_id ?? ""}`;
  }
  return JSON.stringify(r).slice(0, 160);
}

// Drive the REAL built-in Workflow Agent loop (GLM function-calling -> real CBN bus).
// Streams start/thinking/tool_call/tool_result/final/error/done into agentEvents.
async function runAgentTurn() {
  if (agentRunning.value || !config.agentMessage.trim()) return;
  const message = config.agentMessage.trim();
  const continueId = currentThreadId.value;
  agentRunning.value = true;
  agentEvents.value = continueId
    ? [...agentEvents.value, { type: "user", text: message }]
    : [{ type: "user", text: message }];
  try {
    await api.value.runAgent(message, permissionMode.value, continueId, (event) => {
      if (event.type === "thread" && event.thread_id) {
        currentThreadId.value = String(event.thread_id);
      }
      agentEvents.value = [...agentEvents.value, event];
    });
  } catch (err) {
    agentEvents.value = [...agentEvents.value, { type: "error", error: String(err) }];
  } finally {
    agentRunning.value = false;
    void loadThreads();
    void loadCards();
  }
}

// CLI-Anything dedicated market panel (秋叶 AAAKI-style plugin browser).
async function loadCliAnythingCatalog() {
  try {
    cliAnythingCatalog.value = await api.value.cliAnythingCatalog();
  } catch (err) {
    notify("CLI-Anything 市场", `加载失败: ${err instanceof Error ? err.message : String(err)}`, "warning");
  }
}

// MCP ingress: accept an external MCP server as CBN nodes (dogfood: python -m cbn mcp serve --stdio).
async function loadMcpIngressServers() {
  try {
    const { servers } = await api.value.mcpIngressServers();
    mcpIngressServers.value = servers;
  } catch {
    /* daemon down */
  }
}

async function connectMcpIngress() {
  const command = mcpIngressCommand.value.trim();
  if (!command || mcpIngressBusy.value) return;
  mcpIngressBusy.value = true;
  try {
    const args = mcpIngressArgs.value.trim().split(/\s+/).filter(Boolean);
    const serverId = `mcp-${Date.now().toString(36)}`;
    const result = await api.value.mcpIngressConnect(serverId, command, args);
    if (result.ok) {
      notify("MCP 入口", `已接入 ${result.registered ? (result.registered as string[]).length : 0} 个工具`, "success");
      await loadMcpIngressServers();
    } else {
      notify("MCP 入口", String(result.error ?? "接入失败"), "warning");
    }
  } catch (err) {
    notify("MCP 入口", err instanceof Error ? err.message : String(err), "warning");
  } finally {
    mcpIngressBusy.value = false;
  }
}

async function disconnectMcpIngress(serverId: string) {
  try {
    await api.value.mcpIngressDisconnect(serverId);
    await loadMcpIngressServers();
  } catch (err) {
    notify("MCP 入口", String(err), "warning");
  }
}

// Shared产物 directory (the real shared ArtifactStore, grouped by producer).
async function loadArtifactStore() {
  try {
    const { tree } = await api.value.artifactsGrouped();
    artifactStoreTree.value = tree;
  } catch {
    // daemon may be down — keep current tree
  }
}

function toggleArtifactsPanel() {
  showArtifactsPanel.value = !showArtifactsPanel.value;
  if (showArtifactsPanel.value) void loadArtifactStore();
}

async function inspectArtifact(artifactId: string) {
  if (!artifactId) return;
  try {
    const detail = await api.value.inspectArtifact(artifactId);
    const content = String((detail as Record<string, unknown>).content ?? "");
    notify("产物内容", content.slice(0, 240) || "(空)", "info");
  } catch (err) {
    notify("产物", err instanceof Error ? err.message : String(err), "warning");
  }
}

// One-click harness install (real `cli-hub install <name>`, pip from GitHub, streamed).
async function installHarness(name: string) {
  if (installingName.value) return;
  installingName.value = name;
  installLines.value = [];
  try {
    await api.value.installHarness(name, (e) => {
      if (e.type === "line") installLines.value = [...installLines.value, String(e.text ?? "")];
      else if (e.type === "done") notify(`安装 ${name}`, e.ok ? "完成" : "失败（见日志）", e.ok ? "success" : "warning");
      else if (e.type === "error") notify(`安装 ${name}`, String(e.error ?? ""), "warning");
    });
  } catch (err) {
    notify(`安装 ${name}`, String(err), "warning");
  } finally {
    installingName.value = "";
  }
}

const filteredCliMarket = computed(() => {
  const q = cliMarketQuery.value.trim().toLowerCase();
  const items = cliAnythingCatalog.value.catalog;
  if (!q) return items;
  return items.filter((h) =>
    `${h.name ?? ""} ${h.display_name ?? ""} ${h.description ?? ""}`.toLowerCase().includes(q),
  );
});

const cliHubReady = computed(() => !!cliAnythingCatalog.value.status.entrypoint_available);

async function loadDesktopAppState(silent = false): Promise<boolean> {
  if (!window.__cbnApp) {
    desktopApp.value = null;
    if (!silent) notify("App Bridge 不可用", "请通过 npm run app:dev 启动桌面端入口。", "warning");
    return false;
  }
  try {
    desktopApp.value = await window.__cbnApp.getState();
    if (desktopApp.value?.daemonUrl && config.daemonUrl !== desktopApp.value.daemonUrl) {
      config.daemonUrl = desktopApp.value.daemonUrl;
    }
    return true;
  } catch (err) {
    if (!silent) notify("App 状态读取失败", err instanceof Error ? err.message : String(err), "warning");
    return false;
  }
}

async function bindWindowState() {
  if (!window.__cbnApp) return;
  try {
    windowState.value = await window.__cbnApp.getWindowState();
    disposeWindowState?.();
    disposeWindowState = window.__cbnApp.onWindowStateChange((state) => {
      windowState.value = state;
      handleWindowResize();
    });
  } catch (err) {
    notify("窗口状态读取失败", err instanceof Error ? err.message : String(err), "warning");
  }
}

async function minimizeAppWindow() {
  if (!window.__cbnApp) return;
  windowState.value = await window.__cbnApp.minimizeWindow();
}

async function toggleMaximizeAppWindow() {
  if (!window.__cbnApp) return;
  windowState.value = await window.__cbnApp.toggleMaximizeWindow();
}

async function closeAppWindow() {
  if (!window.__cbnApp) return;
  await window.__cbnApp.closeWindow();
}

async function relaunchDesktopDaemon() {
  if (!window.__cbnApp) {
    notify("当前不是 App 壳", "请使用 npm run app:dev 启动桌面端。", "warning");
    return;
  }
  const daemon = await window.__cbnApp.relaunchDaemon();
  const current = desktopApp.value ?? {
    appName: "CLI Bridge Network",
    appVersion: "0.1.0",
    daemonUrl: daemon.url,
    rendererUrl: window.location.origin,
    isPackaged: false,
    platform: navigator.platform,
    workspaceRoot: "local",
    daemon,
  };
  desktopApp.value = { ...current, daemon, daemonUrl: daemon.url };
  await loadHealth();
}

function notify(title: string, detail = "", tone: ToastTone = "info") {
  const id = nextToastId++;
  toasts.value = [...toasts.value, { id, tone, title, detail }];
  window.setTimeout(() => dismissToast(id), tone === "danger" ? 5600 : 3400);
}

function dismissToast(id: number) {
  toasts.value = toasts.value.filter((toast) => toast.id !== id);
}

async function copyText(id: string, text: string) {
  if (!text) return;
  await navigator.clipboard.writeText(text);
  copiedText.value = id;
  notify("已复制", text.slice(0, 80), "success");
  window.setTimeout(() => {
    if (copiedText.value === id) copiedText.value = "";
  }, 1800);
}

async function call<T>(label: string, fn: () => Promise<T>, options: { silent?: boolean } = {}): Promise<T | null> {
  loading.value = label;
  if (!options.silent) error.value = "";
  try {
    return await fn();
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    error.value = message;
    if (!options.silent) notify(`${humanLabel(label)} 未完成`, message, "danger");
    return null;
  } finally {
    loading.value = "";
  }
}

async function loadInitial() {
  loading.value = "workspace";
  error.value = "";
  await Promise.allSettled([
    loadHealth(true),
    loadWorkflowList(true),
    loadWorkflow(true),
    loadContract(true),
    loadAgentBundle(true),
    loadWorkflowRequestPlan(true),
    loadToolCallPlan(true),
    loadConnectPackage(true),
    loadQuickstart(true),
    loadEntryProfile(true),
    loadHarnessAgent(true),
    loadLaunchContract(true),
    loadSdkBootstrap(true),
    loadConsumerManifest(true),
    loadAcceptance(true),
    loadReadiness(true),
    loadImportCatalog(true),
    loadDirectCliReadiness(true),
    loadProtocolWire(true),
    loadDock(true),
  ]);
  loading.value = "";
}

async function loadHealth(silent = false) {
  const result = await call("health", () => api.value.health(), { silent });
  if (result) health.value = result;
}

async function loadWorkflowList(silent = false) {
  const result = await call("workflows", () => api.value.workflows(), { silent });
  if (result) workflowList.value = result;
}

async function loadWorkflow(silent = false) {
  const result = await call("workflow", () => api.value.workflow(config.workflowPath), { silent });
  if (result) workflow.value = result as WorkflowInspect;
}

async function loadContract(silent = false) {
  const result = await call("contract", () => api.value.contract(config.workflowPath), { silent });
  if (result) contract.value = result as BridgeContractReport;
}

async function loadAgentBundle(silent = false) {
  const result = await call("agent", () => api.value.adapterAgentNodeBundle(), { silent });
  if (result) agentBundle.value = result as AdapterAgentNodeBundle;
}

async function loadWorkflowRequestPlan(silent = false) {
  const result = await call("plan", () => api.value.workflowRequestPlan(), { silent });
  if (result) workflowRequestPlan.value = result as AgentWorkflowRequestPlan;
}

async function loadToolCallPlan(silent = false) {
  const result = await call("setup plan", () => api.value.toolCallPlan(), { silent });
  if (result) toolCallPlan.value = result as AdapterAgentToolCallPlan;
}

async function loadConnectPackage(silent = false) {
  const result = await call("connect", () => api.value.networkConnectPackage(), { silent });
  if (result) connectPackage.value = result as NetworkConnectPackage;
}

async function loadQuickstart(silent = false) {
  const result = await call("quickstart", () => api.value.networkQuickstart(), { silent });
  if (result) directQuickstart.value = result as NetworkConnectQuickstart;
}

async function loadLaunchContract(silent = false) {
  const result = await call("launch", () => api.value.networkLaunchContract(), { silent });
  if (result) launchContract.value = result as ConsumerLaunchContract;
}

async function loadEntryProfile(silent = false) {
  const result = await call("profile", () => api.value.networkEntryProfile(), { silent });
  if (result) entryProfile.value = result as NetworkEntryProfile;
}

async function loadHarnessAgent(silent = false) {
  const result = await call("harness", () => api.value.networkHarnessAgent(), { silent });
  if (result) networkHarnessAgent.value = result as NetworkHarnessAgent;
}

async function loadSdkBootstrap(silent = false) {
  const result = await call("sdk bootstrap", () => api.value.networkSdkBootstrap(), { silent });
  if (result) sdkBootstrap.value = result as ConsumerSdkBootstrap;
}

async function loadConsumerManifest(silent = false) {
  const result = await call("consumer manifest", () => api.value.networkConsumerManifest(), { silent });
  if (result) consumerManifest.value = result as NetworkConsumerManifest;
}

async function loadAcceptance(silent = false) {
  const result = await call("acceptance", () => api.value.networkAcceptance(), { silent });
  if (result) directAcceptance.value = result as NetworkConnectionAcceptance;
}

async function loadReadiness(silent = false) {
  const result = await call("readiness", () => api.value.networkReadiness(), { silent });
  if (result) directReadiness.value = result as KillerMvpReadiness;
}

async function loadImportCatalog(silent = false) {
  const result = await call("imports", () => api.value.importCatalog(), { silent });
  if (result) importCatalog.value = result as CliRegistrationSurface;
}

async function loadDirectCliReadiness(silent = false) {
  const result = await call("direct CLI", () => api.value.directCliReadiness(), { silent });
  if (result) directCliReadiness.value = result as DirectCliReadinessReport;
}

async function loadProtocolWire(silent = false) {
  const result = await call("direct wire", () => api.value.protocolWireConformance(), { silent });
  if (result) protocolWireReport.value = result as ProtocolWireConformanceReport;
}

async function verifyNetwork() {
  const result = await call("network verify", () => api.value.networkVerify());
  if (result) networkVerifyReport.value = result as NetworkConnectionAcceptanceReport;
}

async function runAcceptanceChecks() {
  if (!quickstartRequests.value.length || !acceptanceChecks.value.length) {
    await loadQuickstart();
    await loadAcceptance();
  }
  loading.value = "acceptance";
  const results: AcceptanceExecutionResult[] = [];
  for (const check of acceptanceChecks.value) {
    const request = quickstartRequests.value.find((candidate) => candidate.id === check.request_id);
    if (!request) {
      results.push({
        check_id: check.id || check.request_id || "acceptance",
        request_id: check.request_id || "missing",
        status: "skipped",
        proves: check.proves,
        error: "matching quickstart request not found",
      });
      continue;
    }
    try {
      const response = await api.value.quickstartRequest(request);
      results.push({
        check_id: check.id || check.request_id || request.id || "acceptance",
        request_id: request.id || check.request_id || "request",
        status: response.http_status >= 200 && response.http_status < 300 ? "passed" : "failed",
        http_status: response.http_status,
        proves: check.proves,
        expect: check.expect,
        evidence: asRecord(response.payload),
      });
    } catch (err) {
      results.push({
        check_id: check.id || check.request_id || request.id || "acceptance",
        request_id: request.id || check.request_id || "request",
        status: "failed",
        proves: check.proves,
        expect: check.expect,
        error: err instanceof Error ? err.message : String(err),
      });
    }
  }
  acceptanceResults.value = results;
  loading.value = "";
  notify("验收检查完成", `通过 ${acceptanceSummary.value.passed} 项，失败 ${acceptanceSummary.value.failed} 项。`, acceptanceSummary.value.failed ? "warning" : "success");
}

async function loadDock(silent = false) {
  const [events, audit, artifacts] = await Promise.all([
    call("events", () => api.value.events(), { silent }),
    call("audit", () => api.value.audit(), { silent }),
    call("artifacts", () => api.value.artifacts(), { silent }),
  ]);
  if (Array.isArray(events)) dock.events = events;
  if (Array.isArray(audit)) dock.audit = audit;
  if (Array.isArray(artifacts)) dock.artifacts = artifacts;
}

async function runWorkflow() {
  const result = await call("run", () => api.value.runWorkflow());
  if (result) {
    runResult.value = result;
    notify("Workflow 已运行", config.dryRun ? "dry-run 模式，结果已进入工作台。" : "真实运行已完成。", "success");
    await loadDock(true);
  }
}

async function runDemo() {
  const result = await call("demo", () => api.value.killerDemo());
  if (result) {
    demoReport.value = result as KillerDemoReport;
    notify("演示已完成", "Killer demo 结果已进入项目资产与审计中心。", "success");
    await loadDock(true);
  }
}

async function performAction(action: RibbonAction) {
  activeActionId.value = action.id;
  if (action.target === "audit") {
    showAudit.value = true;
    await loadDock(true);
    return;
  }
  if (action.target === "artifacts") {
    await loadDock();
    return;
  }
  if (action.target) openRightPanel(action.target);
  switch (action.id) {
    case "refresh-run":
      await loadInitial();
      await runWorkflow();
      break;
    case "demo":
      await runDemo();
      break;
    case "contract":
      await loadContract();
      break;
    case "setup-plan":
      await loadToolCallPlan();
      break;
    case "connect":
      await loadConnectPackage();
      break;
    case "quick":
      await loadQuickstart();
      break;
    case "profile":
      await loadEntryProfile();
      break;
    case "harness":
      await loadHarnessAgent();
      break;
    case "launch":
      await loadLaunchContract();
      break;
    case "sdk":
      await loadSdkBootstrap();
      break;
    case "manifest":
      await loadConsumerManifest();
      break;
    case "accept":
      await loadAcceptance();
      await runAcceptanceChecks();
      break;
    case "ready":
      await loadReadiness();
      await verifyNetwork();
      break;
    case "imports":
      rightPanelTab.value = "direct";
      await loadImportCatalog();
      break;
    case "directwire":
      rightPanelTab.value = "direct";
      await loadProtocolWire();
      break;
    case "installed":
      openRightPanel("registry");
      break;
    case "market":
      openRightPanel("market");
      break;
    default:
      notify("入口已定位", `${action.label} 已切换到对应工作区，后续接入真实操作。`, "info");
  }
}

function humanLabel(label: string): string {
  const labels: Record<string, string> = {
    health: "连接本地服务",
    workflows: "读取流程列表",
    workflow: "读取流程",
    contract: "读取契约",
    agent: "读取 Agent",
    plan: "生成计划",
    "setup plan": "检查入手计划",
    connect: "准备 CLI 接入",
    quickstart: "准备 Quickstart",
    launch: "读取 Launch Contract",
    profile: "读取 Profile",
    harness: "读取 Harness",
    "sdk bootstrap": "读取 SDK Bootstrap",
    "consumer manifest": "读取 Consumer Manifest",
    acceptance: "读取验收",
    readiness: "读取 Readiness",
    imports: "读取导入目录",
    "direct CLI": "检查 Direct CLI",
    "direct wire": "检查 DirectWire",
    "network verify": "执行网络验收",
    run: "运行 Workflow",
    demo: "运行演示",
    events: "刷新事件",
    audit: "刷新审计",
    artifacts: "刷新产物",
    workspace: "加载工作台",
  };
  return labels[label] ?? label;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function toNumber(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && Number.isFinite(Number(value))) return Number(value);
  return undefined;
}

function formatBytes(value: unknown): string {
  const bytes = toNumber(value);
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function unique(values: string[]): string[] {
  return Array.from(new Set(values.filter((value) => value.trim().length > 0)));
}

function dedupeRows(rows: ArtifactRow[]): ArtifactRow[] {
  const seen = new Set<string>();
  return rows.filter((row) => {
    if (seen.has(row.id)) return false;
    seen.add(row.id);
    return true;
  });
}

function shortJson(value: unknown): string {
  if (value === null || value === undefined) return "not loaded";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function mountStudioGraph() {
  if (!graphCanvasEl.value || studioGraph) return;
  studioGraph = mountWorkflowGraph(graphCanvasEl.value);
  studioGraph.render(workflow.value, agentBundle.value);
}

watch(workflow, () => studioGraph?.render(workflow.value, agentBundle.value));
watch(agentBundle, () => studioGraph?.render(workflow.value, agentBundle.value));
watch(leftNavCollapsed, () => {
  draggableCards.saved.reclamp();
  draggableCards.temporary.reclamp();
  draggableCards.agent.reclamp();
  draggableCards.detail.reclamp();
  draggableCards.artifacts.reclamp();
});

onMounted(async () => {
  restoreRightDockPosition();
  draggableCards.saved.restore();
  draggableCards.temporary.restore();
  draggableCards.agent.restore();
  draggableCards.detail.restore();
  draggableCards.artifacts.restore();
  window.addEventListener("pointermove", handleRightDockDrag);
  window.addEventListener("pointerup", stopRightDockDrag);
  window.addEventListener("resize", handleWindowResize);
  await bindWindowState();
  const appReady = await loadDesktopAppState(true);
  if (!appReady) {
    error.value = "Desktop app bridge unavailable. Start CLI Bridge Network with npm run app:dev.";
    notify("桌面端入口不可用", "当前 renderer 未连接 Electron preload，已停止加载旧网页端路径。", "warning");
    return;
  }
  await loadInitial();
  void loadThreads();
  void loadCards();
  mountStudioGraph();
});

onUnmounted(() => {
  window.removeEventListener("pointermove", handleRightDockDrag);
  window.removeEventListener("pointerup", stopRightDockDrag);
  window.removeEventListener("resize", handleWindowResize);
  studioGraph?.dispose();
  studioGraph = null;
  disposeWindowState?.();
  disposeWindowState = null;
});
</script>

<template>
  <main :class="['ribbon-shell', { maximized: windowState.isMaximized, 'ribbon-collapsed': ribbonCollapsed, 'left-collapsed': leftNavCollapsed }]">
    <header class="topbar">
      <div class="brand app-drag-region">
        <div class="brand-mark"><Command :size="19" /></div>
        <div>
          <strong>CLI Bridge Network</strong>
          <span>对话驱动 · 工作流为结果</span>
        </div>
      </div>
      <label class="global-search" aria-label="Search workflows agents tools">
        <Search :size="15" />
        <input value="搜索工作流、CLI、节点、产物..." readonly />
      </label>
      <div class="top-actions">
        <button type="button" :class="['status-pill', 'shell', desktopApp?.daemon.healthy ? '' : 'warn']" @click="loadDesktopAppState()">
          <HardDriveDownload :size="14" />
          {{ appShellText }}
        </button>
        <button type="button" :class="['status-pill', 'health', error ? 'warn' : 'ok']" @click="loadHealth()">
          <CheckCircle2 v-if="!error" :size="14" />
          <CircleDot v-else :size="14" />
          {{ healthText }}
        </button>
        <button type="button" class="bell" :title="`打开审计中心 · ${dock.events.length} 条事件`" @click="showAudit = true">
          <Bell :size="15" />
          <span v-if="dock.events.length" class="bell-badge">{{ dock.events.length }}</span>
        </button>
        <button type="button" class="icon-btn" title="设置 · Daemon / Token / Workflow 路径" @click="openRightPanel('settings')">
          <Settings :size="15" />
        </button>
        <button type="button" class="topbar-avatar" title="账户与会话配置" @click="openRightPanel('settings')">
          <User :size="15" />
        </button>
      </div>
      <div class="window-controls" aria-label="Window controls">
        <button type="button" title="最小化" @click="minimizeAppWindow()">
          <Minus :size="15" />
        </button>
        <button type="button" :title="windowState.isMaximized ? '还原' : '最大化'" @click="toggleMaximizeAppWindow()">
          <Maximize2 :size="15" />
        </button>
        <button type="button" class="close" title="关闭" @click="closeAppWindow()">
          <X :size="15" />
        </button>
      </div>
    </header>

    <nav :class="['ribbon', { collapsed: ribbonCollapsed }]" aria-label="Workflow Studio ribbon">
      <div class="ribbon-tabs">
        <button v-for="tab in ribbonTabs" :key="tab.id" type="button" :class="{ active: activeRibbonTab === tab.id }" @click="setTab(tab.id)">
          {{ tab.label }}
        </button>
        <button type="button" class="ribbon-collapse" :title="ribbonCollapsed ? '展开 Ribbon' : '收起 Ribbon'" @click="ribbonCollapsed = !ribbonCollapsed">
          <ChevronDown :class="{ open: !ribbonCollapsed }" :size="15" />
        </button>
      </div>
      <div v-if="!ribbonCollapsed" class="ribbon-bands">
        <section v-for="group in activeTab.groups" :key="group.id" :class="['ribbon-group', group.tone]">
          <header>{{ group.title }}</header>
          <div>
            <button
              v-for="action in group.actions"
              :key="action.id"
              type="button"
              :class="['ribbon-command', { active: activeAction.id === action.id }]"
              :title="action.detail"
              @click="performAction(action)"
            >
              <component :is="action.icon" :size="17" />
              <span>{{ action.label }}</span>
              <small>{{ action.level }}</small>
            </button>
          </div>
        </section>
        <section class="context-card">
          <span>当前入口</span>
          <strong>{{ activeAction.label }}</strong>
          <p>{{ activeAction.detail }}</p>
          <code>{{ activeTrail.join(" / ") }}</code>
        </section>
      </div>
    </nav>

    <section class="studio-workbench">
      <button type="button" class="left-collapse-tab" :title="leftNavCollapsed ? '展开左侧栏' : '收起左侧栏'" @click="leftNavCollapsed = !leftNavCollapsed">
        <span class="collapse-glyph">{{ leftNavCollapsed ? ">" : "<" }}</span>
      </button>
      <aside class="left-ide">
        <template v-if="!leftNavCollapsed">
          <section class="panel workspace-nav">
            <header class="panel-header">
              <div>
                <span>工作导航</span>
                <strong>{{ leftNavMode === "threads" ? "Agent Sessions" : "Favorite Workflows" }}</strong>
              </div>
              <button
                v-if="leftNavMode === 'threads'"
                type="button"
                title="新建线程"
                @click="startNewThread()"
              >
                <Plus :size="15" />
              </button>
              <button v-else type="button" title="刷新收藏工作流" @click="loadInitial()">
                <RefreshCw :size="15" />
              </button>
            </header>
            <div class="nav-switch" role="tablist" aria-label="左侧导航切换">
              <span :class="['switch-thumb', leftNavMode]"></span>
              <button type="button" :class="{ active: leftNavMode === 'threads' }" @click="leftNavMode = 'threads'">对话线程</button>
              <button type="button" :class="{ active: leftNavMode === 'favorites' }" @click="leftNavMode = 'favorites'">收藏工作流</button>
            </div>
            <Transition name="nav-slide" mode="out-in">
              <div v-if="leftNavMode === 'threads'" key="threads" class="thread-list nav-scroll">
                <button
                  v-for="thread in conversationThreads"
                  :key="thread.id"
                  type="button"
                  :class="['thread-row', thread.tone, { active: thread.id === selectedWorkflowId }]"
                  @click="selectThread(thread.id)"
                >
                  <span></span>
                  <strong>{{ thread.title }}</strong>
                  <small>{{ thread.meta }}</small>
                </button>
              </div>
              <div v-else key="favorites" class="favorite-list nav-scroll">
                <button
                  v-for="card in favoriteWorkflowCards"
                  :key="card.id"
                  type="button"
                  :class="['favorite-row', { active: selectedWorkflow.id === card.id }]"
                  @click="selectWorkflow(card.id)"
                >
                  <Workflow :size="14" />
                  <span>
                    <strong>{{ card.title }}</strong>
                    <small>{{ card.status }} · {{ card.tools.length }} CLI</small>
                  </span>
                </button>
              </div>
            </Transition>
          </section>

          <section class="panel team-space">
            <header class="panel-header">
              <div>
                <span>团队空间</span>
                <strong>Workspace</strong>
              </div>
              <button type="button" title="打开团队资产" @click="openRightPanel('registry')">
                <Library :size="15" />
              </button>
            </header>
            <div class="team-list">
              <div class="team-row active">
                <Layers3 :size="14" />
                <span><strong>团队空间</strong><small>共享 workflow、manifest 与权限策略将在协作层接入</small></span>
              </div>
            </div>
          </section>
        </template>
      </aside>

      <section class="main-ide">
        <div class="canvas-toolbar">
          <div class="breadcrumbs">
            <span v-for="crumb in activeTrail" :key="crumb">{{ crumb }}</span>
          </div>
          <div class="toolbar-actions">
            <button type="button" title="刷新工作台" @click="loadInitial()"><RefreshCw :size="14" /> 刷新</button>
            <button type="button" title="运行当前 workflow" @click="runWorkflow()"><Play :size="14" /> 运行</button>
            <button type="button" @click="setZoom(zoom - 10)">-</button>
            <strong>{{ zoom }}%</strong>
            <button type="button" @click="setZoom(zoom + 10)">+</button>
            <button type="button" title="复位视图" @click="resetGraphView()"><RefreshCw :size="14" /> 复位</button>
          </div>
        </div>

        <div ref="canvasSurfaceEl" class="canvas-surface">
          <canvas ref="graphCanvasEl" class="workflow-graph-canvas" aria-label="Workflow graph whiteboard" />
          <section ref="savedAreaEl" data-draggable-card class="workflow-stage saved-area" :style="draggableCards.saved.style.value">
            <header class="drag-handle" @pointerdown="draggableCards.saved.startDrag">
              <span>已保存区</span>
              <strong>Pinned Workflows · {{ favoriteCards.length }}</strong>
            </header>
            <div class="workflow-cards wf-cards-mini">
              <article v-for="card in favoriteCards" :key="String(card.card_id)" class="workflow-card wf-card-mini">
                <canvas class="card-mini-graph" :data-card-id="String(card.card_id)" aria-label="workflow graph" />
                <div class="wf-card-body">
                  <strong>{{ card.title }}</strong>
                  <small>{{ Number(card.task_count ?? 0) }} 节点</small>
                </div>
                <button type="button" class="wf-card-run" @click="reuseCard(card)"><Play :size="13" /> 运行</button>
              </article>
              <span v-if="!favoriteCards.length" class="wf-card-empty">收藏的工作流卡片显示在这里</span>
            </div>
          </section>

          <section ref="temporaryAreaEl" data-draggable-card class="workflow-stage temporary-area" :style="draggableCards.temporary.style.value">
            <header class="drag-handle" @pointerdown="draggableCards.temporary.startDrag">
              <span>临时区</span>
              <strong>Draft Workflows · {{ draftCards.length }}</strong>
            </header>
            <div class="workflow-cards wf-cards-mini">
              <article v-for="card in draftCards" :key="String(card.card_id)" class="workflow-card wf-card-mini">
                <canvas class="card-mini-graph" :data-card-id="String(card.card_id)" aria-label="workflow graph" />
                <div class="wf-card-body">
                  <strong>{{ card.title }}</strong>
                  <small>{{ Number(card.task_count ?? 0) }} 节点 · 草稿</small>
                </div>
                <div class="wf-card-actions">
                  <button type="button" class="wf-card-fav" @click="favoriteCard(card)">★ 收藏</button>
                  <button type="button" class="wf-card-run" @click="reuseCard(card)"><Play :size="13" /> 运行</button>
                </div>
              </article>
              <span v-if="!draftCards.length" class="wf-card-empty">Agent 跑通后生成的草稿工作流卡片显示在这里</span>
            </div>
          </section>

          <section ref="agentConsoleEl" data-draggable-card :class="['agent-console', 'floating-card', agentPanelMode, { dragged: draggableCards.agent.hasDragged.value && agentPanelMode === 'floating' }]" :style="draggableCards.agent.style.value">
            <header class="drag-handle" @pointerdown="draggableCards.agent.startDrag">
              <div>
                <span>Workflow Orchestration Agent</span>
                <strong>Z.ai Streaming Agent</strong>
              </div>
              <div class="window-actions" @pointerdown.stop>
                <button type="button" title="缩小" @click="setAgentPanelMode('minimized')"><Minus :size="13" /></button>
                <button type="button" title="停靠" @click="setAgentPanelMode('docked')"><PanelRight :size="13" /></button>
                <button type="button" title="扩展" @click="setAgentPanelMode('floating')"><Maximize2 :size="13" /></button>
              </div>
            </header>
            <div v-if="agentPanelMode !== 'minimized'" class="agent-perm-bar" @pointerdown.stop>
              <span class="agent-perm-label">权限</span>
              <div class="agent-perm-seg" role="radiogroup" aria-label="权限模式">
                <button type="button" :class="{ active: permissionMode === 'default' }" @click="setPermissionMode('default')" title="默认审批 · 每步人工确认">默认</button>
                <button type="button" :class="{ active: permissionMode === 'auto' }" @click="setPermissionMode('auto')" title="自动审查 · 普通自动、风险确认">自动</button>
                <button type="button" :class="{ active: permissionMode === 'full' }" @click="setPermissionMode('full')" title="完全访问 · Agent 自主长程（推荐）">完全</button>
              </div>
            </div>
            <div v-if="agentPanelMode !== 'minimized'" class="message-feed">
              <template v-if="!agentEvents.length">
                <p><b>你</b> {{ config.agentMessage }}</p>
                <p>
                  <b>Agent</b>
                  输入任务后点运行——内置 Agent 会真实驱动 CLI 总线（obsidian / jimeng …），思考、工具调用、产物实时显示。
                </p>
              </template>
              <template v-for="(ev, idx) in agentEvents" :key="idx">
                <p v-if="ev.type === 'user'" class="ev-user"><b>你</b> {{ ev.text }}</p>
                <p v-else-if="ev.type === 'thinking'" class="ev-think"><b>思考</b> {{ ev.text }}</p>
                <div v-else-if="ev.type === 'tool_call'" class="ev-tool">
                  <TerminalSquare :size="14" />
                  <strong>{{ ev.name }}</strong>
                  <code>{{ JSON.stringify(ev.args) }}</code>
                </div>
                <div v-else-if="ev.type === 'tool_result'" class="ev-result" :class="{ ok: ev.ok }">
                  <span>{{ ev.ok ? '✓' : '✗' }} {{ ev.name }}</span>
                  <small>{{ agentEventSummary(ev.result) }}</small>
                </div>
                <p v-else-if="ev.type === 'final'" class="ev-final"><b>Agent</b> {{ ev.text }}</p>
                <p v-else-if="ev.type === 'error'" class="ev-error"><b>错误</b> {{ ev.error }}</p>
              </template>
              <div v-if="agentRunning" class="ev-running"><span class="dot"></span> Agent 运行中…</div>
            </div>
            <div v-if="agentPanelMode !== 'minimized'" class="composer">
              <input v-model="config.agentMessage" aria-label="Agent message" @keyup.enter="runAgentTurn()" />
              <button type="button" :disabled="agentRunning" :title="agentRunning ? '运行中…' : '运行 Agent（真实）'" @click="runAgentTurn()"><Play :size="14" /></button>
            </div>
          </section>

          <section ref="detailPopoverEl" data-draggable-card class="detail-popover floating-card" :style="draggableCards.detail.style.value">
            <header class="drag-handle" @pointerdown="draggableCards.detail.startDrag">
              <div>
                <span>工作流详情</span>
                <strong>{{ selectedWorkflow.title }}</strong>
              </div>
              <button type="button" @pointerdown.stop @click="runWorkflow()"><Play :size="14" /> 运行</button>
            </header>
            <div class="detail-grid">
              <div><span>Route Ready</span><strong>{{ routeReadyCount }}/{{ bridgeRouteCount }}</strong></div>
              <div><span>Agent Cards</span><strong>{{ agentCards.length }}</strong></div>
              <div><span>Tasks</span><strong>{{ tasks.length }}</strong></div>
              <div><span>Artifacts</span><strong>{{ artifactRows.length }}</strong></div>
            </div>
            <div class="detail-tags">
              <code>{{ config.dryRun ? "dry-run" : "live" }}</code>
              <code>{{ config.confirmed ? "confirmed" : "approval required" }}</code>
              <code>{{ permissionMode }}</code>
            </div>
          </section>

          <section v-if="showArtifactsPanel" ref="artifactsPanelEl" data-draggable-card class="artifacts-panel floating-card" :style="draggableCards.artifacts.style.value">
            <header class="drag-handle" @pointerdown="draggableCards.artifacts.startDrag">
              <div>
                <span>项目产物</span>
                <strong>Artifacts · {{ artifactRows.length }}</strong>
              </div>
              <button type="button" title="关闭" @pointerdown.stop @click="showArtifactsPanel = false"><X :size="14" /></button>
            </header>
            <div class="artifact-tree nav-scroll">
              <details v-for="group in artifactGroups" :key="group.producer" class="artifact-group" open>
                <summary><strong>{{ group.producer }}</strong> <small>{{ group.count }} 产物</small></summary>
                <article v-for="kind in group.kinds" :key="kind.kind" class="artifact-kind">
                  <header><FileJson :size="13" /> <span>{{ kind.kind }}</span> <small>{{ kind.count }}</small></header>
                  <button v-for="(item, idx) in kind.items" :key="String(item.artifact_id ?? idx)" type="button" class="artifact-item" @click="String(item.artifact_id) && inspectArtifact(String(item.artifact_id))">
                    <span>{{ Number(item.size_bytes ?? 0) }} B</span>
                    <small>{{ String(item.created_at ?? "").slice(5, 16) }}</small>
                  </button>
                </article>
              </details>
              <span v-if="!artifactGroups.length" class="artifact-empty">暂无产物 · 运行 workflow 后生成（共享目录 runtime/artifacts/）</span>
            </div>
          </section>
        </div>

      </section>

      <Transition name="dock-float">
      <aside v-if="rightPanelOpen" :class="['right-dock', 'floating-dock', { dragging: rightDockDrag.active }]" :style="rightDockStyle">
        <header class="dock-header dock-drag-handle" @pointerdown="startRightDockDrag">
          <div>
            <span>命令与工具库</span>
            <strong>CLI Library</strong>
          </div>
          <div class="dock-header-actions">
            <button type="button" title="设置" @pointerdown.stop @click="rightPanelTab = 'settings'"><Settings :size="15" /></button>
            <button type="button" title="关闭浮窗" @pointerdown.stop @click="rightPanelOpen = false"><X :size="15" /></button>
          </div>
        </header>
        <div class="dock-tabs">
          <button type="button" :class="{ active: rightPanelTab === 'registry' }" @click="openRightPanel('registry')">已安装</button>
          <button type="button" :class="{ active: rightPanelTab === 'connect' }" @click="openRightPanel('connect')">Connect</button>
          <button type="button" :class="{ active: rightPanelTab === 'direct' }" @click="openRightPanel('direct')">Direct</button>
          <button type="button" :class="{ active: rightPanelTab === 'market' }" @click="openRightPanel('market')">市场</button>
          <button type="button" :class="{ active: rightPanelTab === 'permissions' }" @click="openRightPanel('permissions')">权限</button>
          <button type="button" :class="{ active: rightPanelTab === 'settings' }" @click="openRightPanel('settings')">设置</button>
        </div>

        <section v-if="rightPanelTab === 'registry'" class="dock-body">
          <div class="dock-metrics">
            <div><span>已注册</span><strong>{{ registryMetrics.registered }}</strong></div>
            <div><span>就绪</span><strong>{{ registryMetrics.ready }}</strong></div>
            <div><span>需配置</span><strong>{{ registryMetrics.gated }}</strong></div>
            <div><span>路由</span><strong>{{ registryMetrics.routes }}</strong></div>
          </div>
          <article v-for="plugin in pluginRows" :key="plugin.id" class="plugin-row">
            <button type="button" class="plugin-main" @click="expandedPluginId = expandedPluginId === plugin.id ? '' : plugin.id">
              <Boxes :size="15" />
              <span>
                <strong>{{ plugin.name }}</strong>
                <small>{{ plugin.category }} · {{ plugin.version }}</small>
              </span>
              <em>{{ plugin.status }}</em>
            </button>
            <div v-if="expandedPluginId === plugin.id" class="plugin-expanded">
              <code v-for="capability in plugin.capabilities.slice(0, 10)" :key="capability">{{ capability }}</code>
              <button type="button" @click="performAction(ribbonAction('harness'))">
                <BrainCircuit :size="13" /> 交给 Harness
              </button>
            </div>
          </article>
        </section>

        <section v-else-if="rightPanelTab === 'connect'" class="dock-body">
          <div class="dock-metrics">
            <div><span>Connect</span><strong>{{ connectSummary.status }}</strong></div>
            <div><span>Quick</span><strong>{{ connectSummary.quickstartStatus }}</strong></div>
            <div><span>Accept</span><strong>{{ connectSummary.acceptanceStatus }}</strong></div>
            <div><span>Ready</span><strong>{{ directReadiness?.score || connectPackage?.summary?.mvp_readiness_score || "—" }}</strong></div>
          </div>
          <article class="info-block">
            <header><strong>Launch / Profile / Harness</strong><span>{{ launchContract?.status || "launch pending" }}</span></header>
            <div class="kv-grid">
              <div><span>Launch</span><code>{{ launchContract?.contract_id || connectPackage?.consumer_launch_contract?.contract_id || "not loaded" }}</code></div>
              <div><span>Profile</span><code>{{ entryProfile?.profile_id || connectPackage?.network_entry_profile?.profile_id || "not loaded" }}</code></div>
              <div><span>Harness</span><code>{{ networkHarnessAgent?.contract_id || connectPackage?.network_harness_agent?.contract_id || "not loaded" }}</code></div>
              <div><span>Run</span><code>{{ networkHarnessAgent?.run?.endpoint || connectPackage?.network_harness_agent?.run?.endpoint || "not loaded" }}</code></div>
            </div>
          </article>
          <article class="info-block">
            <header><strong>SDK / Manifest</strong><span>{{ sdkBootstrap?.status || consumerManifest?.status || "pending" }}</span></header>
            <div class="kv-grid">
              <div><span>SDK</span><code>{{ sdkBootstrap?.bootstrap_id || connectPackage?.consumer_sdk_bootstrap?.bootstrap_id || "not loaded" }}</code></div>
              <div><span>Requests</span><code>{{ sdkBootstrap?.request_count ?? connectPackage?.consumer_sdk_bootstrap?.request_count ?? quickstartRequests.length }}</code></div>
              <div><span>Manifest</span><code>{{ consumerManifest?.manifest_id || connectPackage?.consumer_manifest?.manifest_id || "not loaded" }}</code></div>
              <div><span>Sequence</span><code>{{ consumerManifest?.request_sequence?.length ?? quickstartSequenceSteps.length }}</code></div>
            </div>
          </article>
          <article class="info-block">
            <header><strong>First-Call Sequence</strong><button type="button" @click="loadQuickstart()">刷新 Quick</button></header>
            <div class="compact-sequence">
              <div v-for="step in quickstartSequenceSteps.slice(0, 8)" :key="step.id">
                <code>{{ step.order }}</code>
                <span>{{ step.title }}</span>
                <small>{{ step.method }} {{ step.target }}</small>
              </div>
              <span v-if="!quickstartSequenceSteps.length">No first-call sequence loaded</span>
            </div>
          </article>
          <article class="info-block">
            <header><strong>Acceptance</strong><button type="button" @click="runAcceptanceChecks()">运行验收</button></header>
            <div class="kv-grid">
              <div><span>Total</span><code>{{ acceptanceSummary.total }}</code></div>
              <div><span>Passed</span><code>{{ acceptanceSummary.passed }}</code></div>
              <div><span>Failed</span><code>{{ acceptanceSummary.failed }}</code></div>
              <div><span>Skipped</span><code>{{ acceptanceSummary.skipped }}</code></div>
            </div>
            <div class="compact-sequence">
              <div v-for="check in acceptanceChecks.slice(0, 6)" :key="check.id || check.request_id">
                <code>{{ check.request_id || "request" }}</code>
                <span>{{ check.id || "check" }}</span>
                <small>{{ check.proves || "acceptance evidence" }}</small>
              </div>
              <span v-if="!acceptanceChecks.length">No acceptance checks loaded</span>
            </div>
          </article>
          <article class="info-block">
            <header><strong>Next Commands</strong><button type="button" :disabled="!connectNextCommands.length" @click="copyText('next-commands', connectNextCommands.join('\n'))">复制</button></header>
            <div class="command-list">
              <code v-for="command in connectNextCommands.slice(0, 6)" :key="command">{{ command }}</code>
              <span v-if="!connectNextCommands.length">No next commands loaded</span>
            </div>
          </article>
        </section>

        <section v-else-if="rightPanelTab === 'direct'" class="dock-body">
          <div class="dock-metrics">
            <div><span>Imports</span><strong>{{ directImporters.length }}</strong></div>
            <div><span>Profiles</span><strong>{{ directCliMetrics.profiles }}</strong></div>
            <div><span>Caps</span><strong>{{ directCliMetrics.capabilities }}</strong></div>
            <div><span>Wire</span><strong>{{ protocolWireSummary.failures }}</strong></div>
          </div>
          <article class="info-block">
            <header><strong>Import Catalog</strong><button type="button" @click="loadImportCatalog()">刷新</button></header>
            <div class="compact-sequence">
              <div v-for="importer in directImporters.slice(0, 8)" :key="importer.id || importer.entrypoint">
                <code>{{ importer.entrypoint || importer.id || "import" }}</code>
                <span>{{ importer.title || importer.id || "CLI registration" }}</span>
                <small>{{ importer.default_side_effects || "dry-run first" }}</small>
              </div>
              <span v-if="!directImporters.length">No import catalog loaded</span>
            </div>
          </article>
          <article class="info-block">
            <header><strong>Direct CLI Readiness</strong><button type="button" @click="loadDirectCliReadiness()">刷新</button></header>
            <div class="kv-grid">
              <div><span>Status</span><code>{{ directCliMetrics.status }}</code></div>
              <div><span>Actions</span><code>{{ directCliMetrics.actions }}</code></div>
              <div><span>Verified</span><code>{{ directCliMetrics.verified }}</code></div>
              <div><span>Gated</span><code>{{ directCliMetrics.gated }}</code></div>
            </div>
            <div class="compact-sequence">
              <div v-for="profile in directCliProfiles.slice(0, 6)" :key="profile.profile">
                <code>{{ profile.profile || "profile" }}</code>
                <span>{{ profile.status || "status pending" }}</span>
                <small>{{ profile.capability_count ?? profile.capabilities?.length ?? 0 }} capabilities · {{ profile.setup_action_count ?? 0 }} setup</small>
              </div>
              <span v-if="!directCliProfiles.length">No direct CLI profile loaded</span>
            </div>
          </article>
          <article class="info-block">
            <header><strong>DirectWire</strong><button type="button" @click="loadProtocolWire()">刷新</button></header>
            <div class="kv-grid">
              <div><span>Status</span><code>{{ protocolWireSummary.status }}</code></div>
              <div><span>Checks</span><code>{{ protocolWireSummary.checks }}</code></div>
              <div><span>Failures</span><code>{{ protocolWireSummary.failures }}</code></div>
              <div><span>Target</span><code>{{ protocolWireReport?.target || "all" }}</code></div>
            </div>
            <div class="compact-sequence">
              <div v-for="protocol in protocolWireSummary.protocols" :key="protocol.id">
                <code>{{ protocol.id }}</code>
                <span>{{ protocol.status }}</span>
                <small>{{ protocol.checks }} checks</small>
              </div>
              <span v-if="!protocolWireSummary.protocols.length">No direct wire report loaded</span>
            </div>
          </article>
        </section>

        <section v-else-if="rightPanelTab === 'market'" class="dock-body">
          <article class="market-row">
            <div><strong>CLI-Anything Adapter</strong><span>本地 CLI 探测、Manifest 生成、repair</span></div>
            <button type="button" @click="loadImportCatalog()">刷新</button>
          </article>
          <article class="market-row">
            <div><strong>Jimeng Image CLI</strong><span>文生图 workflow 插件占位</span></div>
            <button type="button" @click="notify('插件入口', 'Jimeng Image CLI 将进入 CLI Registry / Connect 初始化流程。', 'info')">接入</button>
          </article>
          <article class="market-row">
            <div><strong>Obsidian Bridge</strong><span>vault search、note read、prompt extraction</span></div>
            <button type="button" @click="notify('插件入口', 'Obsidian Bridge 将进入 harness agent 引导流程。', 'info')">接入</button>
          </article>
        </section>

        <section v-else-if="rightPanelTab === 'permissions'" class="dock-body">
          <button type="button" :class="['permission-card', { active: permissionMode === 'default' }]" @click="setPermissionMode('default')">
            <ShieldCheck :size="17" />
            <span><strong>默认审批</strong><small>所有操作需要用户确认</small></span>
          </button>
          <button type="button" :class="['permission-card', { active: permissionMode === 'auto' }]" @click="setPermissionMode('auto')">
            <CheckCircle2 :size="17" />
            <span><strong>自动审查</strong><small>安全操作自动放行，敏感操作确认</small></span>
          </button>
          <button type="button" :class="['permission-card', { active: permissionMode === 'full' }]" @click="setPermissionMode('full')">
            <Zap :size="17" />
            <span><strong>完全访问</strong><small>允许真实执行，审计仍保留</small></span>
          </button>
        </section>

        <section v-else class="dock-body settings-body">
          <label>
            <span>Daemon URL · App managed</span>
            <input :value="config.daemonUrl" readonly />
          </label>
          <label>
            <span>Session Token</span>
            <input v-model="config.sessionToken" />
          </label>
          <label>
            <span>Workflow Path</span>
            <input v-model="config.workflowPath" />
          </label>
          <div class="settings-actions">
            <button type="button" @click="loadInitial()">应用并刷新</button>
            <button type="button" @click="relaunchDesktopDaemon()">重启 Daemon</button>
            <button type="button" @click="showDiagnostics = true">Raw JSON</button>
          </div>
        </section>
      </aside>
      </Transition>
    </section>

    <section v-if="showCliMarketPanel" class="cli-market-panel">
      <header class="cli-market-head">
        <div>
          <span>插件市场</span>
          <strong>CLI-Anything · {{ cliAnythingCatalog.catalog.length }} harnesses · cli-hub {{ cliHubReady ? '就绪' : '未就绪' }}</strong>
        </div>
        <div class="cli-market-head-actions">
          <button type="button" title="刷新市场" @click="loadCliAnythingCatalog()"><RefreshCw :size="15" /></button>
          <button type="button" title="关闭" @click="showCliMarketPanel = false"><X :size="16" /></button>
        </div>
      </header>
      <div class="cli-market-toolbar">
        <Search :size="14" />
        <input v-model="cliMarketQuery" placeholder="搜索 harness（名称 / 描述）…" />
      </div>
      <div class="cli-market-list nav-scroll">
        <article v-for="h in filteredCliMarket" :key="String(h.name)" class="cli-market-row">
          <div class="cm-row-main">
            <strong>{{ h.display_name || h.name }}</strong>
            <small>{{ h.description }}</small>
          </div>
          <div class="cm-row-meta">
            <code>{{ h.name }}</code>
            <em>v{{ h.version || "?" }}</em>
            <button type="button" class="cm-install" :disabled="!!installingName" @click="installHarness(String(h.name))">
              {{ installingName === h.name ? "安装中…" : "安装" }}
            </button>
          </div>
        </article>
        <span v-if="!filteredCliMarket.length" class="artifact-empty">未找到匹配的 harness</span>
      </div>
      <div class="mcp-ingress">
        <header><span>MCP 入口</span><strong>接入外部 MCP 服务为节点</strong></header>
        <div class="mcp-ingress-form">
          <input v-model="mcpIngressCommand" placeholder="command（如 python）" />
          <input v-model="mcpIngressArgs" placeholder="args（如 -m cbn mcp serve --stdio）" />
          <button type="button" :disabled="mcpIngressBusy" @click="connectMcpIngress()">{{ mcpIngressBusy ? "接入中…" : "接入" }}</button>
        </div>
        <div v-if="mcpIngressServers.length" class="mcp-ingress-list">
          <div v-for="srv in mcpIngressServers" :key="String(srv.server_id)" class="mcp-ingress-row">
            <Network :size="13" />
            <span><strong>{{ srv.server_id }}</strong><small>{{ String(srv.command) }} · {{ srv.connected ? "已连接" : "离线" }} · {{ Number(srv.tool_count ?? 0) }} 工具</small></span>
            <button type="button" @click="disconnectMcpIngress(String(srv.server_id))">断开</button>
          </div>
        </div>
      </div>
      <div v-if="installingName || installLines.length" class="cli-market-log">
        <header><span>安装日志</span><strong>{{ installingName || "完成" }}</strong></header>
        <pre>{{ installLines.slice(-40).join("\n") }}</pre>
      </div>
    </section>

    <footer class="bottom-rail">
      <button type="button" :class="{ active: rightPanelOpen && rightPanelTab === 'registry' }" @click="toggleRightPanel('registry')"><Boxes :size="16" /> CLI 库</button>
      <button type="button" :class="{ active: showArtifactsPanel }" @click="toggleArtifactsPanel()"><Archive :size="16" /> 产物</button>
      <button type="button" :class="{ active: rightPanelOpen && rightPanelTab === 'permissions' }" @click="toggleRightPanel('permissions')"><ShieldCheck :size="16" /> 权限</button>
      <button type="button" @click="showAudit = true"><ListChecks :size="16" /> 审计中心</button>
    </footer>

    <div v-if="showAudit" class="drawer-backdrop" @click.self="showAudit = false">
      <aside class="audit-drawer">
        <header>
          <div>
            <span>审计中心</span>
            <strong>Audit & Governance</strong>
          </div>
          <button type="button" title="关闭审计中心" @click="showAudit = false"><X :size="16" /></button>
        </header>
        <section class="audit-grid">
          <article><span>执行日志</span><strong>{{ dock.events.length }}</strong><p>运行事件只在审计中心呈现。</p></article>
          <article><span>审批记录</span><strong>{{ dock.audit.length }}</strong><p>敏感操作、API key、外部网络和文件写入确认。</p></article>
          <article><span>安全事件</span><strong>{{ permissionMode }}</strong><p>默认审批、自动审查、完全访问三档治理。</p></article>
          <article><span>产物证据</span><strong>{{ dock.artifacts.length }}</strong><p>原始 artifact 证据与用户产物分开管理。</p></article>
        </section>
        <div class="audit-columns">
          <section>
            <header>Events</header>
            <pre>{{ shortJson(dock.events) }}</pre>
          </section>
          <section>
            <header>Audit</header>
            <pre>{{ shortJson(dock.audit) }}</pre>
          </section>
          <section>
            <header>Artifacts</header>
            <pre>{{ shortJson(dock.artifacts) }}</pre>
          </section>
        </div>
      </aside>
    </div>

    <div v-if="showDiagnostics" class="drawer-backdrop" @click.self="showDiagnostics = false">
      <aside class="diagnostic-drawer">
        <header>
          <div>
            <span>技术详情</span>
            <strong>Raw Integration State</strong>
          </div>
          <button type="button" title="关闭" @click="showDiagnostics = false"><X :size="16" /></button>
        </header>
        <pre>{{ shortJson({ health, workflowList, workflow, contract, runResult, demoReport, agentBundle, workflowRequestPlan, toolCallPlan, connectPackage, directQuickstart, entryProfile, networkHarnessAgent, directAcceptance, importCatalog, directCliReadiness, protocolWireReport, networkVerifyReport }) }}</pre>
      </aside>
    </div>

    <div class="toast-stack" aria-live="polite" aria-atomic="false">
      <button v-for="toast in toasts" :key="toast.id" :class="['toast-card', toast.tone]" type="button" @click="dismissToast(toast.id)">
        <strong>{{ toast.title }}</strong>
        <span v-if="toast.detail">{{ toast.detail }}</span>
      </button>
    </div>
  </main>
</template>
