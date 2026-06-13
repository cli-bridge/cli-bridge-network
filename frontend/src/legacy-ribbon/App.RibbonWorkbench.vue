<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, type Component } from "vue";
import {
  Archive,
  Bell,
  Bot,
  Boxes,
  BrainCircuit,
  CheckCircle2,
  ChevronDown,
  CircleDot,
  Clock3,
  Code2,
  Command,
  Copy,
  Database,
  FileCheck2,
  FileJson,
  Files,
  Gauge,
  GitBranch,
  HardDriveDownload,
  History,
  KeyRound,
  Layers3,
  Library,
  ListChecks,
  Maximize2,
  MessageSquareText,
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
  Sparkles,
  TerminalSquare,
  UploadCloud,
  Waypoints,
  Workflow,
  Wrench,
  X,
  Zap,
} from "lucide-vue-next";
import { StudioApi } from "./api";
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
type InspectorTab = "preview" | "workflow" | "agent" | "connect" | "demo" | "raw";
type ArtifactTab = "artifacts" | "files" | "variables" | "environment";
type AgentPanelMode = "floating" | "docked" | "minimized";

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

interface AgentCardView {
  id: string;
  title: string;
  role: string;
  status: string;
  capabilities: string[];
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
    id: "orchestrate",
    label: "Agent Orchestration",
    groups: [
      {
        id: "agent",
        title: "对话与任务",
        tone: "blue",
        actions: [
          { id: "new-thread", label: "新建线程", level: "L2", icon: Plus, detail: "创建持久化的 workflow 对话会话" },
          { id: "stream-chat", label: "流式对话", level: "L2", icon: MessageSquareText, detail: "主 Agent 消息流、工具调用和断点状态" },
          { id: "tool-calls", label: "工具调用", level: "L3", icon: Wrench, detail: "加载 Agent 工具调用计划和执行批次" },
          { id: "long-task", label: "长程任务", level: "L3", icon: Clock3, detail: "长任务 checkpoint、审批和恢复点" },
        ],
      },
      {
        id: "workflow-core",
        title: "工作流生成",
        tone: "teal",
        actions: [
          { id: "graph", label: "节点图", level: "L2", icon: Workflow, detail: "ComfyUI 式 workflow graph 预览与编辑" },
          { id: "save-card", label: "保存卡片", level: "L2", icon: FileCheck2, detail: "将临时 workflow 固定到工作台" },
          { id: "version", label: "版本", level: "L3", icon: GitBranch, detail: "保存、回滚、导入导出与团队复用" },
        ],
      },
    ],
  },
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
        title: "产物目录",
        tone: "amber",
        actions: [
          { id: "outputs", label: "产物", level: "L2", icon: Archive, detail: "查看 workflow 生成的用户产物", target: "artifacts" },
          { id: "preview", label: "预览", level: "L2", icon: Maximize2, detail: "在 IDE 面板中预览选中产物" },
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
    id: "assets",
    label: "Reusable Assets",
    groups: [
      {
        id: "library",
        title: "资产与收藏",
        tone: "teal",
        actions: [
          { id: "favorites", label: "收藏工作流", level: "L2", icon: Library, detail: "可展开、可保存、可恢复的 workflow 栈" },
          { id: "project-assets", label: "项目资产", level: "L2", icon: Files, detail: "项目产物、提示词、配置和导出包", target: "artifacts" },
          { id: "workspace", label: "团队库", level: "L3", icon: Database, detail: "团队可复用工作流和插件资产" },
        ],
      },
      {
        id: "plugin",
        title: "插件",
        tone: "green",
        actions: [
          { id: "installed", label: "已安装", level: "L2", icon: Boxes, detail: "右侧浮窗列出已安装 CLI 与插件", target: "registry" },
          { id: "market", label: "市场", level: "L2", icon: UploadCloud, detail: "可安装、可更新的外部插件接口", target: "market" },
        ],
      },
    ],
  },
  {
    id: "govern",
    label: "Governance",
    groups: [
      {
        id: "permission",
        title: "受控执行",
        tone: "amber",
        actions: [
          { id: "permissions", label: "权限模式", level: "L2", icon: ShieldCheck, detail: "默认审批、自动审查、完全访问三档", target: "permissions" },
          { id: "approval", label: "审批队列", level: "L3", icon: KeyRound, detail: "敏感操作确认与审批历史", target: "audit" },
          { id: "audit", label: "审计中心", level: "L2", icon: History, detail: "日志、安全、审批、性能统一归档", target: "audit" },
          { id: "settings", label: "设置", level: "L2", icon: Settings, detail: "模型、base_url、主题、工作区与导出策略", target: "settings" },
        ],
      },
    ],
  },
];

const DEFAULT_DAEMON_URL = "http://127.0.0.1:8787";
const DEFAULT_WORKFLOW_PATH = "workflows/cli-anything-macrocli-mermaid-routing.example.json";
const DEFAULT_AGENT_MESSAGE = "Run this workflow as a reusable CLI-CLI harness agent and surface setup gates.";

const config = reactive<StudioConfig>({
  daemonUrl: DEFAULT_DAEMON_URL,
  sessionToken: "",
  workflowPath: DEFAULT_WORKFLOW_PATH,
  agentMessage: DEFAULT_AGENT_MESSAGE,
  dryRun: true,
  confirmed: false,
});

const api = computed(() => new StudioApi(config));
const activeRibbonTab = ref("orchestrate");
const activeActionId = ref("stream-chat");
const rightPanelTab = ref<PanelTarget>("registry");
const selectedWorkflowId = ref("current");
const expandedWorkflowId = ref("current");
const expandedPluginId = ref("");
const selectedArtifactId = ref("");
const inspectorTab = ref<InspectorTab>("preview");
const artifactTab = ref<ArtifactTab>("artifacts");
const agentPanelMode = ref<AgentPanelMode>("floating");
const showAudit = ref(false);
const showDiagnostics = ref(false);
const permissionMode = ref<PermissionMode>(config.confirmed ? (config.dryRun ? "auto" : "full") : "default");
const theme = ref<"dark" | "light">("dark");
const zoom = ref(100);
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
  return ribbonTabs[0].groups[0].actions[1];
});
const activeGroup = computed(() => activeTab.value.groups.find((group) => group.actions.some((action) => action.id === activeAction.value.id)));
const activeTrail = computed(() => [activeTab.value.label, activeGroup.value?.title || "工作区", activeAction.value.label, activeAction.value.level]);
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
const selectedArtifact = computed(() => artifactRows.value.find((artifact) => artifact.id === selectedArtifactId.value) ?? artifactRows.value[0] ?? null);
const conversationThreads = computed<ConversationThread[]>(() => [
  {
    id: "current",
    title: currentWorkflowTitle.value,
    meta: `${currentWorkflowStatus.value} · ${tasks.value.length} tasks`,
    tone: loading.value ? "active" : workflow.value?.valid === false ? "warn" : "ok",
  },
  {
    id: "setup",
    title: "CLI 引导与初始化",
    meta: `${connectPackage.value?.summary?.setup_status || "待加载"} · ${connectPackage.value?.summary?.setup_user_gate_count ?? 0} gates`,
    tone: Number(connectPackage.value?.summary?.setup_user_gate_count ?? 0) > 0 ? "warn" : "idle",
  },
  {
    id: "agent",
    title: "Agent 编排计划",
    meta: `${toolCallPlan.value?.summary?.tool_call_count ?? 0} tool calls · ${toolCallPlan.value?.summary?.batch_count ?? 0} batches`,
    tone: toolCallPlan.value ? "active" : "idle",
  },
  {
    id: "network",
    title: "Network Connect",
    meta: `${connectPackage.value?.summary?.registration_importer_count ?? importCatalog.value?.importer_count ?? 0} importers`,
    tone: connectPackage.value?.ok ? "ok" : "idle",
  },
]);
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
const agentCardViews = computed<AgentCardView[]>(() => agentCards.value.map((card, index) => {
  const record = asRecord(card);
  const metadata = asRecord(record.metadata);
  const spec = asRecord(record.spec);
  const rawCapabilities = Array.isArray(spec.capabilities)
    ? spec.capabilities
    : Array.isArray(record.capabilities)
      ? record.capabilities
      : [];
  const id = String(metadata.id || record.id || `agent-card-${index + 1}`);
  return {
    id,
    title: String(metadata.title || record.title || id),
    role: String(metadata.role || record.role || "agent"),
    status: String(metadata.status || record.status || "ready"),
    capabilities: rawCapabilities.filter((item): item is string => typeof item === "string").slice(0, 8),
  };
}));
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
const workflowRows = computed(() => tasks.value.map((task) => ({
  id: task.id,
  uses: task.uses,
  needs: (task.needs ?? []).join(", ") || "root",
  routes: task.argsFrom?.length ?? 0,
  risk: task.capability?.risk || "normal",
  parser: task.capability?.parser_ref || "parser pending",
  verified: task.capability?.verified ? "verified" : "unverified",
})));
const contractSections = computed(() => {
  const sections = contract.value?.contract?.contracts ?? {};
  return Object.entries(sections).map(([id, section]) => ({
    id,
    kind: section?.kind || "contract",
    owner: section?.owner || "core",
    scope: section?.scope || "runtime",
    required: [
      ...(section?.required_metadata ?? []),
      ...(section?.required_payload ?? []),
      ...(section?.required_fields ?? []),
      ...(section?.required_spec ?? []),
    ].join(", ") || "none",
  }));
});
const agentTasks = computed(() => agentBundle.value?.tasks ?? connectPackage.value?.agent_node_bundle?.tasks ?? []);
const agentHandoffs = computed(() => agentBundle.value?.source_coordination_plan?.handoffs ?? []);
const setupBatches = computed(() => toolCallPlan.value?.execution_batches ?? []);
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
const quickstartSdkSnippets = computed(() => connectQuickstart.value.sdk_snippets ?? []);
const connectAcceptance = computed<Partial<NetworkConnectionAcceptance>>(() => directAcceptance.value ?? connectPackage.value?.acceptance ?? connectPackage.value?.consumer_quickstart?.acceptance ?? {});
const acceptanceChecks = computed<ConnectionAcceptanceCheck[]>(() => connectAcceptance.value.checks ?? []);
const acceptanceSummary = computed(() => ({
  total: acceptanceChecks.value.length,
  passed: acceptanceResults.value.filter((result) => result.status === "passed").length,
  failed: acceptanceResults.value.filter((result) => result.status === "failed").length,
  skipped: acceptanceResults.value.filter((result) => result.status === "skipped").length,
}));
const connectEndpoints = computed(() => connectPackage.value?.daemon_endpoints ?? []);
const connectNextCommands = computed(() => unique([
  ...(connectPackage.value?.next_commands ?? []),
  ...(connectPackage.value?.consumer_manifest?.next_commands ?? []),
  ...(connectPackage.value?.demo_readiness?.next_commands ?? []),
  ...(connectPackage.value?.demo_playbook?.next_commands ?? []),
  ...(connectPackage.value?.registration_surface?.next_commands ?? []),
]));
const connectDemoStages = computed(() => connectPackage.value?.demo_readiness?.stages ?? []);
const connectDemoPlaybookSteps = computed(() => connectPackage.value?.demo_playbook?.steps ?? []);
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
const demoStages = computed(() => demoReport.value?.stages ?? []);
const demoHandoffs = computed(() => demoReport.value?.communication_trace?.handoffs ?? []);
const demoArtifacts = computed(() => demoReport.value?.evidence?.task_artifacts ?? []);
const protocolExports = computed(() => demoReport.value?.protocol_exports?.exports ?? {});
const protocolCards = computed(() => [
  {
    id: "MCP",
    count: Array.isArray(protocolExports.value.mcp?.workflowTools) ? protocolExports.value.mcp.workflowTools.length : 0,
    wire: protocolExports.value.mcp?.wire_compatible ? "wire" : "pending",
  },
  {
    id: "A2A",
    count: Array.isArray(protocolExports.value.a2a?.agentCard?.skills) ? protocolExports.value.a2a.agentCard.skills.length : 0,
    wire: protocolExports.value.a2a?.wire_compatible ? "wire" : "pending",
  },
  {
    id: "ACP",
    count: Array.isArray(protocolExports.value.acp?.workflows) ? protocolExports.value.acp.workflows.length : 0,
    wire: protocolExports.value.acp?.wire_compatible ? "wire" : "pending",
  },
]);
const inspectorTabs: Array<{ id: InspectorTab; label: string }> = [
  { id: "preview", label: "预览" },
  { id: "workflow", label: "Workflow" },
  { id: "agent", label: "Agent" },
  { id: "connect", label: "Connect" },
  { id: "demo", label: "Demo" },
  { id: "raw", label: "Raw" },
];
const healthText = computed(() => {
  const record = asRecord(health.value);
  if (record.ok === true) return "System Healthy";
  if (record.status) return String(record.status);
  if (error.value) return "Needs Attention";
  return "Connecting";
});
const appShellText = computed(() => desktopApp.value ? `App · ${desktopApp.value.daemon.mode}` : "App starting");
const visibleArtifactRows = computed(() => {
  if (artifactTab.value === "artifacts") return artifactRows.value;
  if (artifactTab.value === "files") return artifactRows.value.filter((artifact) => /file|html|json|txt|pdf|artifact/i.test(artifact.kind));
  if (artifactTab.value === "variables") {
    return [
      { id: "var-workflow", name: "workflowPath", kind: "VAR", source: config.workflowPath, size: "runtime" },
      { id: "var-daemon", name: "daemonUrl", kind: "VAR", source: config.daemonUrl, size: "app" },
      { id: "var-permission", name: "permissionMode", kind: "VAR", source: permissionMode.value, size: config.dryRun ? "dry-run" : "live" },
    ];
  }
  return [
    { id: "env-shell", name: "shell", kind: "ENV", source: "desktop app", size: appShellText.value },
    { id: "env-daemon", name: "daemon", kind: "ENV", source: config.daemonUrl, size: healthText.value },
    { id: "env-workspace", name: "workspace", kind: "ENV", source: desktopApp.value?.workspaceRoot || "local", size: "UTF-8" },
  ];
});

function setTab(tabId: string) {
  activeRibbonTab.value = tabId;
  const nextTab = activeTab.value;
  activeActionId.value = nextTab.groups[0]?.actions[0]?.id ?? activeActionId.value;
  if (tabId === "orchestrate") {
    inspectorTab.value = "agent";
    rightPanelTab.value = "registry";
    void loadToolCallPlan(true);
  } else if (tabId === "workflow") {
    inspectorTab.value = "workflow";
    void Promise.allSettled([loadWorkflow(true), loadContract(true)]);
  } else if (tabId === "connect") {
    inspectorTab.value = "connect";
    rightPanelTab.value = "connect";
    void loadConnectPackage(true);
  } else if (tabId === "assets") {
    inspectorTab.value = "preview";
    rightPanelTab.value = "registry";
    void loadDock(true);
  } else if (tabId === "govern") {
    rightPanelTab.value = "permissions";
    inspectorTab.value = "raw";
  }
}

function selectWorkflow(id: string) {
  selectedWorkflowId.value = id;
  expandedWorkflowId.value = expandedWorkflowId.value === id ? "" : id;
  inspectorTab.value = "workflow";
}

function setPermissionMode(mode: PermissionMode) {
  permissionMode.value = mode;
  if (mode === "default") {
    config.dryRun = true;
    config.confirmed = false;
  } else if (mode === "auto") {
    config.dryRun = true;
    config.confirmed = true;
  } else {
    config.dryRun = false;
    config.confirmed = true;
  }
  notify("权限模式已切换", `${mode} · ${config.dryRun ? "dry-run" : "live"} · ${config.confirmed ? "confirmed" : "approval required"}`, "success");
}

function setZoom(nextZoom: number) {
  zoom.value = Math.min(500, Math.max(10, nextZoom));
}

function setArtifactTab(tab: ArtifactTab) {
  artifactTab.value = tab;
  inspectorTab.value = "preview";
  if (tab === "artifacts" || tab === "files") {
    void loadDock(true);
  }
}

function selectThread(threadId: string) {
  if (threadId === "current") {
    selectedWorkflowId.value = "current";
    inspectorTab.value = "workflow";
    void loadWorkflow(true);
  } else if (threadId === "setup" || threadId === "network") {
    selectedWorkflowId.value = "connect";
    activeRibbonTab.value = "connect";
    rightPanelTab.value = "connect";
    inspectorTab.value = "connect";
    void loadConnectPackage(true);
  } else if (threadId === "agent") {
    inspectorTab.value = "agent";
    activeRibbonTab.value = "orchestrate";
    void loadToolCallPlan(true);
  }
}

function openRightPanel(tab: PanelTarget) {
  rightPanelTab.value = tab;
  if (tab === "connect") {
    inspectorTab.value = "connect";
    void loadConnectPackage(true);
  } else if (tab === "direct") {
    void Promise.allSettled([loadImportCatalog(true), loadDirectCliReadiness(true), loadProtocolWire(true)]);
  } else if (tab === "registry") {
    void loadImportCatalog(true);
  }
}

function setAgentPanelMode(mode: AgentPanelMode) {
  agentPanelMode.value = agentPanelMode.value === mode && mode !== "floating" ? "floating" : mode;
  notify("Agent 面板状态", agentPanelMode.value, "info");
}

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
    notify("演示已完成", "Killer demo 结果已进入产物目录与审计中心。", "success");
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
    inspectorTab.value = "preview";
    await loadDock();
    return;
  }
  if (action.target) openRightPanel(action.target);
  if (action.id === "refresh-run") {
    inspectorTab.value = "workflow";
    await loadInitial();
    await runWorkflow();
  } else if (action.id === "demo") {
    inspectorTab.value = "demo";
    await runDemo();
  } else if (action.id === "contract") {
    inspectorTab.value = "workflow";
    await loadContract();
  } else if (action.id === "graph") {
    inspectorTab.value = "workflow";
    await Promise.allSettled([loadWorkflow(), loadContract()]);
  } else if (action.id === "setup-plan" || action.id === "tool-calls" || action.id === "long-task") {
    inspectorTab.value = "agent";
    await loadToolCallPlan();
  } else if (action.id === "connect") {
    inspectorTab.value = "connect";
    await loadConnectPackage();
  } else if (action.id === "quick") {
    inspectorTab.value = "connect";
    await loadQuickstart();
  } else if (action.id === "profile") {
    inspectorTab.value = "connect";
    await loadEntryProfile();
  } else if (action.id === "harness") {
    inspectorTab.value = "connect";
    await loadHarnessAgent();
  } else if (action.id === "launch") {
    inspectorTab.value = "connect";
    await loadLaunchContract();
  } else if (action.id === "sdk") {
    inspectorTab.value = "connect";
    await loadSdkBootstrap();
  } else if (action.id === "manifest") {
    inspectorTab.value = "connect";
    await loadConsumerManifest();
  } else if (action.id === "accept") {
    inspectorTab.value = "connect";
    await loadAcceptance();
    await runAcceptanceChecks();
  } else if (action.id === "ready") {
    inspectorTab.value = "connect";
    await loadReadiness();
    await verifyNetwork();
  } else if (action.id === "imports") {
    rightPanelTab.value = "direct";
    await loadImportCatalog();
  } else if (action.id === "directwire") {
    rightPanelTab.value = "direct";
    await loadProtocolWire();
  } else if (action.id === "stream-chat" || action.id === "new-thread") {
    inspectorTab.value = "agent";
    await loadWorkflowRequestPlan();
  } else if (action.id === "installed") {
    openRightPanel("registry");
  } else if (action.id === "market") {
    openRightPanel("market");
  } else if (action.id === "permissions") {
    openRightPanel("permissions");
  } else if (action.id === "settings") {
    openRightPanel("settings");
  } else if (action.id === "preview") {
    inspectorTab.value = "preview";
  } else if (action.id === "save-card") {
    notify("保存卡片", "当前 workflow 已固定在工作台视图；持久化接口将在工作流存储层接入。", "info");
  } else if (action.id === "version" || action.id === "package" || action.id === "favorites" || action.id === "workspace") {
    notify("入口已定位", `${action.label} 已切换到对应工作区，后续可接入真实存储/导出操作。`, "info");
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

onMounted(async () => {
  await bindWindowState();
  const appReady = await loadDesktopAppState(true);
  if (!appReady) {
    error.value = "Desktop app bridge unavailable. Start CLI Bridge Network with npm run app:dev.";
    notify("桌面端入口不可用", "当前 renderer 未连接 Electron preload，已停止加载旧网页端路径。", "warning");
    return;
  }
  await loadInitial();
});

onUnmounted(() => {
  disposeWindowState?.();
  disposeWindowState = null;
});
</script>

<template>
  <main :class="['ribbon-shell', theme, { maximized: windowState.isMaximized }]">
    <header class="topbar">
      <div class="brand app-drag-region">
        <div class="brand-mark"><Command :size="19" /></div>
        <div>
          <strong>CLI Bridge Network</strong>
          <span>Workflow Studio</span>
        </div>
      </div>
      <div class="workspace-path">
        <Layers3 :size="15" />
        <span>Local Workspace</span>
        <ChevronDown :size="14" />
        <em>{{ config.workflowPath }}</em>
      </div>
      <label class="global-search" aria-label="Search workflows agents tools">
        <Search :size="15" />
        <input value="搜索工作流、CLI、节点、产物..." readonly />
        <kbd>Ctrl K</kbd>
      </label>
      <div class="top-actions">
        <button type="button" :class="['status-pill', desktopApp?.daemon.healthy ? '' : 'warn']" @click="loadDesktopAppState()">
          <HardDriveDownload :size="14" />
          {{ appShellText }}
        </button>
        <button type="button" :class="['status-pill', error ? 'warn' : '']" @click="loadHealth()">
          <CircleDot :size="14" />
          {{ healthText }}
        </button>
        <button type="button" title="切换主题" @click="theme = theme === 'dark' ? 'light' : 'dark'">
          <Sparkles :size="15" />
          {{ theme === "dark" ? "Light" : "Dark" }}
        </button>
        <button type="button" title="打开审计中心" @click="showAudit = true">
          <ShieldCheck :size="15" />
          Audit
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

    <nav class="ribbon" aria-label="Workflow Studio ribbon">
      <div class="ribbon-tabs">
        <button v-for="tab in ribbonTabs" :key="tab.id" type="button" :class="{ active: activeRibbonTab === tab.id }" @click="setTab(tab.id)">
          {{ tab.label }}
        </button>
      </div>
      <div class="ribbon-bands">
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
      <aside class="left-ide">
        <section class="panel threads-panel">
          <header class="panel-header">
            <div>
              <span>对话线程</span>
              <strong>Agent Sessions</strong>
            </div>
            <button type="button" title="新建线程" @click="performAction(ribbonTabs[0].groups[0].actions[0])">
              <Plus :size="15" />
            </button>
          </header>
          <div class="thread-list">
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
        </section>

        <section class="panel artifact-panel">
          <header class="panel-header">
            <div>
              <span>产物目录</span>
              <strong>Artifacts</strong>
            </div>
            <button type="button" title="刷新产物" @click="loadDock()">
              <RefreshCw :size="15" />
            </button>
          </header>
          <div class="artifact-tabs">
            <button type="button" :class="{ active: artifactTab === 'artifacts' }" @click="setArtifactTab('artifacts')">产物</button>
            <button type="button" :class="{ active: artifactTab === 'files' }" @click="setArtifactTab('files')">文件</button>
            <button type="button" :class="{ active: artifactTab === 'variables' }" @click="setArtifactTab('variables')">变量</button>
            <button type="button" :class="{ active: artifactTab === 'environment' }" @click="setArtifactTab('environment')">环境</button>
          </div>
          <div class="artifact-list">
            <button
              v-for="artifact in visibleArtifactRows"
              :key="artifact.id"
              type="button"
              :class="['artifact-row', { active: selectedArtifact?.id === artifact.id }]"
              @click="selectedArtifactId = artifact.id"
            >
              <Files :size="14" />
              <span>
                <strong>{{ artifact.name }}</strong>
                <small>{{ artifact.kind }} · {{ artifact.source }} · {{ artifact.size }}</small>
              </span>
            </button>
          </div>
        </section>
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
          </div>
        </div>

        <div class="canvas-surface">
          <section class="workflow-stage saved-area">
            <header>
              <span>已保存区</span>
              <strong>Pinned Workflows</strong>
            </header>
            <div class="workflow-cards">
              <article
                v-for="card in workflowCards.slice(0, 3)"
                :key="card.id"
                :class="['workflow-card', { active: selectedWorkflow.id === card.id, unsaved: !card.saved }]"
              >
                <button type="button" class="workflow-card-main" @click="selectWorkflow(card.id)">
                  <Workflow :size="17" />
                  <span>
                    <strong>{{ card.title }}</strong>
                    <small>{{ card.status }}</small>
                  </span>
                  <ChevronDown :class="{ open: expandedWorkflowId === card.id }" :size="15" />
                </button>
                <div class="card-meta">
                  <span>{{ card.tools.length }} CLI</span>
                  <span>{{ card.tasks.length || bridgeRouteCount }} 步骤</span>
                  <span>{{ card.artifacts.length }} 产物</span>
                </div>
                <div v-if="expandedWorkflowId === card.id" class="workflow-expanded">
                  <code v-for="tool in card.tools.slice(0, 4)" :key="tool">{{ tool }}</code>
                  <button type="button" @click="performAction(ribbonTabs[1].groups[0].actions[2])">查看契约</button>
                </div>
              </article>
            </div>
          </section>

          <section class="workflow-stage temporary-area">
            <header>
              <span>临时区</span>
              <strong>Draft Workflows</strong>
            </header>
            <div class="draft-drop">
              <Plus :size="24" />
              <span>Agent 跑通后生成临时卡片</span>
              <small>保存后固定到白板，否则保留在历史会话中</small>
            </div>
          </section>

          <section :class="['agent-console', 'floating-card', agentPanelMode]">
            <header>
              <div>
                <span>Workflow Orchestration Agent</span>
                <strong>Z.ai Streaming Agent</strong>
              </div>
              <div class="window-actions">
                <button type="button" title="缩小" @click="setAgentPanelMode('minimized')"><Minus :size="13" /></button>
                <button type="button" title="停靠" @click="setAgentPanelMode('docked')"><PanelRight :size="13" /></button>
                <button type="button" title="扩展" @click="setAgentPanelMode('floating')"><Maximize2 :size="13" /></button>
              </div>
            </header>
            <div v-if="agentPanelMode !== 'minimized'" class="message-feed">
              <p><b>你</b> {{ config.agentMessage }}</p>
              <p>
                <b>Agent</b>
                当前 workflow 已加载 {{ tasks.length }} 个 task，{{ bridgeRouteCount }} 条 BridgeMessage 路由。
              </p>
              <div class="tool-call">
                <TerminalSquare :size="15" />
                <span>tool calls</span>
                <strong>{{ toolCalls.length }} planned · {{ setupCheckpoints.length }} checkpoints</strong>
                <em>{{ loading ? humanLabel(loading) : "idle" }}</em>
              </div>
            </div>
            <div v-if="agentPanelMode !== 'minimized'" class="composer">
              <input v-model="config.agentMessage" aria-label="Agent message" />
              <button type="button" title="生成计划" @click="performAction(ribbonTabs[0].groups[0].actions[1])"><Play :size="14" /></button>
            </div>
          </section>

          <section class="graph-preview floating-card">
            <header>
              <div>
                <span>节点图预览</span>
                <strong>{{ selectedWorkflow.title }}</strong>
              </div>
              <button type="button" @click="performAction(ribbonTabs[0].groups[1].actions[0])">
                <Workflow :size="14" /> 编辑
              </button>
            </header>
            <div class="node-lane">
              <span v-for="task in tasks.slice(0, 7)" :key="task.id">{{ task.id }}</span>
              <span v-if="!tasks.length">等待 workflow</span>
            </div>
            <div class="tool-chips">
              <code v-for="tool in selectedWorkflow.tools.slice(0, 8)" :key="tool">{{ tool }}</code>
              <code v-if="!selectedWorkflow.tools.length">no CLI loaded</code>
            </div>
          </section>

          <section class="detail-popover floating-card">
            <header>
              <div>
                <span>工作流详情</span>
                <strong>{{ selectedWorkflow.title }}</strong>
              </div>
              <button type="button" @click="runWorkflow()"><Play :size="14" /> 运行</button>
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
        </div>

        <section class="bottom-preview">
          <header>
            <div>
              <span>IDE Inspector</span>
              <strong>{{ inspectorTabs.find((tab) => tab.id === inspectorTab)?.label || "Inspector" }}</strong>
            </div>
            <div class="inspector-tabs">
              <button
                v-for="tab in inspectorTabs"
                :key="tab.id"
                type="button"
                :class="{ active: inspectorTab === tab.id }"
                @click="inspectorTab = tab.id"
              >
                {{ tab.label }}
              </button>
            </div>
          </header>
          <div v-if="inspectorTab === 'preview'" class="preview-grid">
            <div class="preview-card">
              <span>产物</span>
              <strong>{{ selectedArtifact?.kind || "—" }}</strong>
              <p>{{ selectedArtifact?.path || selectedArtifact?.source || "选择左下角产物后在这里预览。" }}</p>
            </div>
            <div class="preview-card">
              <span>Contract</span>
              <strong>{{ contract?.ok === false ? "blocked" : contract ? "loaded" : "not loaded" }}</strong>
              <p>{{ bridgeRouteCount }} routes · {{ routeReadyCount }} ready · {{ contract?.apiVersion || "apiVersion pending" }}</p>
            </div>
            <div class="preview-card">
              <span>Run Result</span>
              <strong>{{ runResult ? "available" : "not run" }}</strong>
              <p>{{ demoReport?.ok ? "Killer demo evidence is available." : "运行 workflow 或 demo 后显示用户可用结果。" }}</p>
            </div>
          </div>
          <div v-else-if="inspectorTab === 'workflow'" class="inspector-table">
            <div class="table-head"><span>Task</span><span>Uses</span><span>Needs</span><span>Routes</span><span>Contract</span></div>
            <div v-for="row in workflowRows" :key="row.id">
              <strong>{{ row.id }}</strong>
              <code>{{ row.uses }}</code>
              <span>{{ row.needs }}</span>
              <span>{{ row.routes }}</span>
              <small>{{ row.risk }} · {{ row.verified }}</small>
            </div>
            <div v-if="!workflowRows.length" class="empty-row">No workflow tasks loaded</div>
            <div v-for="section in contractSections" :key="section.id" class="contract-row">
              <strong>{{ section.id }}</strong>
              <code>{{ section.kind }}</code>
              <span>{{ section.owner }}</span>
              <span>{{ section.scope }}</span>
              <small>{{ section.required }}</small>
            </div>
          </div>
          <div v-else-if="inspectorTab === 'agent'" class="inspector-split">
            <section>
              <header>Agent Cards</header>
              <div v-for="card in agentCardViews.slice(0, 6)" :key="card.id" class="inspector-item">
                <strong>{{ card.title }}</strong>
                <span>{{ card.role }} · {{ card.status }}</span>
                <code>{{ card.capabilities.slice(0, 5).join(", ") || "capabilities pending" }}</code>
              </div>
              <span v-if="!agentCardViews.length" class="empty-row">No agent cards loaded</span>
            </section>
            <section>
              <header>Tool Calls / Batches</header>
              <div v-for="callItem in toolCalls.slice(0, 6)" :key="callItem.call_id || callItem.tool_use_id || callItem.action" class="inspector-item">
                <strong>{{ callItem.action || callItem.tool || callItem.kind || "tool call" }}</strong>
                <span>{{ callItem.risk || "normal" }} · {{ callItem.initial_status || "pending" }}</span>
                <code>{{ (callItem.argv || []).join(" ") || callItem.permission_flow?.reason || "argv pending" }}</code>
              </div>
              <div v-for="batch in setupBatches.slice(0, 3)" :key="batch.batch_id" class="inspector-item">
                <strong>{{ batch.batch_id || "batch" }}</strong>
                <span>{{ batch.mode || "execution" }} · {{ batch.concurrency_safe ? "parallel" : "serial" }}</span>
                <code>{{ (batch.tool_call_ids || batch.tool_use_ids || []).join(", ") }}</code>
              </div>
              <span v-if="!toolCalls.length && !setupBatches.length" class="empty-row">No tool plan loaded</span>
            </section>
          </div>
          <div v-else-if="inspectorTab === 'connect'" class="inspector-split">
            <section>
              <header>Quickstart / SDK</header>
              <div v-for="request in quickstartRequests.slice(0, 8)" :key="request.id || request.url" class="inspector-item">
                <strong>{{ request.id || "request" }}</strong>
                <span>{{ request.method || "GET" }}</span>
                <code>{{ request.url || "not loaded" }}</code>
              </div>
              <div v-for="snippet in quickstartSdkSnippets.slice(0, 3)" :key="snippet.id || snippet.language" class="inspector-item">
                <strong>{{ snippet.title || snippet.id || "SDK snippet" }}</strong>
                <span>{{ snippet.language || "code" }} · {{ snippet.runtime || "runtime" }}</span>
                <button type="button" @click="copyText(`snippet-${snippet.id || snippet.language}`, snippet.code || '')">
                  <Copy :size="13" /> 复制
                </button>
              </div>
            </section>
            <section>
              <header>Endpoints / Playbook</header>
              <div v-for="endpoint in connectEndpoints.slice(0, 6)" :key="`${endpoint.method}:${endpoint.path}`" class="inspector-item">
                <strong>{{ endpoint.method }}</strong>
                <span>{{ endpoint.purpose || "daemon endpoint" }}</span>
                <code>{{ endpoint.path || endpoint.url }}</code>
              </div>
              <div v-for="step in connectDemoPlaybookSteps.slice(0, 4)" :key="step.id || step.title" class="inspector-item">
                <strong>{{ step.title || step.id || "Demo step" }}</strong>
                <span>{{ step.action || "action" }}</span>
                <code>{{ step.command || step.success_signal || "ready" }}</code>
              </div>
            </section>
          </div>
          <div v-else-if="inspectorTab === 'demo'" class="inspector-split">
            <section>
              <header>Killer Demo / Protocols</header>
              <div v-for="stage in demoStages" :key="stage.id" class="inspector-item">
                <strong>{{ stage.title }}</strong>
                <span>{{ stage.status }}</span>
                <code>{{ stage.id }}</code>
              </div>
              <div v-for="protocol in protocolCards" :key="protocol.id" class="inspector-item">
                <strong>{{ protocol.id }}</strong>
                <span>{{ protocol.count }} exported</span>
                <code>{{ protocol.wire }}</code>
              </div>
            </section>
            <section>
              <header>Bridge Handoffs / Artifacts</header>
              <div v-for="handoff in demoHandoffs.slice(0, 6)" :key="`${handoff.producer_task}:${handoff.consumer_task}:${handoff.selector}`" class="inspector-item">
                <strong>{{ handoff.producer_task || "producer" }} -> {{ handoff.consumer_task || "consumer" }}</strong>
                <span>{{ handoff.communication || "BridgeMessage" }}</span>
                <code>{{ handoff.selector || "selector" }}</code>
              </div>
              <div v-for="artifact in demoArtifacts.slice(0, 4)" :key="artifact.artifact_id || artifact.path" class="inspector-item">
                <strong>{{ artifact.label || artifact.artifact_id || "artifact" }}</strong>
                <span>{{ artifact.kind || artifact.content_type || "artifact" }}</span>
                <code>{{ artifact.path || artifact.artifact_id }}</code>
              </div>
            </section>
          </div>
          <div v-else class="raw-grid">
            <pre>{{ shortJson({ workflow, contract, workflowRequestPlan, toolCallPlan, connectPackage, directQuickstart, launchContract, entryProfile, networkHarnessAgent, sdkBootstrap, consumerManifest, directAcceptance, directReadiness, importCatalog, directCliReadiness, protocolWireReport, networkVerifyReport, runResult, demoReport }) }}</pre>
          </div>
        </section>
      </section>

      <aside class="right-dock">
        <header class="dock-header">
          <div>
            <span>CLI 接入</span>
            <strong>Registry & Plugins</strong>
          </div>
          <button type="button" title="设置" @click="rightPanelTab = 'settings'"><Settings :size="15" /></button>
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
              <button type="button" @click="performAction(ribbonTabs[2].groups[0].actions[3])">
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
    </section>

    <footer class="bottom-rail">
      <button type="button" @click="setTab('orchestrate')"><BrainCircuit :size="16" /> Agent Orchestration</button>
      <button type="button" @click="setTab('workflow')"><Workflow :size="16" /> Workflow Graph</button>
      <button type="button" @click="setTab('connect')"><Network :size="16" /> CLI Registry</button>
      <button type="button" @click="setTab('assets')"><Library :size="16" /> Reusable Assets</button>
      <button type="button" @click="showAudit = true"><ShieldCheck :size="16" /> Audit Center</button>
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
