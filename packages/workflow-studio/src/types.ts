export interface StudioConfig {
  daemonUrl: string;
  sessionToken: string;
  workflowPath: string;
  agentMessage: string;
  dryRun: boolean;
  confirmed: boolean;
}

export interface WorkflowTask {
  id: string;
  uses: string;
  args?: string[];
  argsFrom?: Array<{ task: string; selector: string }>;
  needs?: string[];
  dryRun?: boolean;
  approvalId?: string | null;
  capability?: {
    risk?: string;
    parser_ref?: string;
    verified?: boolean;
  };
}

export interface WorkflowInspect {
  valid?: boolean;
  workflow_id?: string;
  title?: string;
  task_count?: number;
  tasks?: WorkflowTask[];
  errors?: string[];
}

export interface BridgeContractSection {
  kind?: string;
  owner?: string;
  scope?: string;
  required_metadata?: string[];
  required_payload?: string[];
  required_fields?: string[];
  required_spec?: string[];
  valid_roots?: string[];
}

export interface BridgeContractReport {
  ok?: boolean;
  apiVersion?: string;
  workflow_path?: string;
  contract?: {
    protocol_name?: string;
    contracts?: {
      tool_manifest?: BridgeContractSection;
      bridge_message?: BridgeContractSection;
      artifact?: BridgeContractSection;
      workflow_selector?: BridgeContractSection;
    };
  };
  summary?: {
    workflow_count?: number;
    route_count?: number;
    route_ready_count?: number;
    blocked_route_count?: number;
    payload_route_count?: number;
    artifact_route_count?: number;
    metadata_route_count?: number;
  };
  workflows?: Array<Record<string, unknown>>;
}

export interface BridgeContractSummary {
  status: string;
  protocolName: string;
  routeReady: string;
  blockedRoutes: number;
  sections: Array<{
    id: string;
    title: string;
    kind: string;
    owner: string;
    scope: string;
    required: string;
  }>;
}

export interface DockState {
  events: unknown[];
  audit: unknown[];
  artifacts: unknown[];
}

export interface DemoStage {
  id: string;
  title: string;
  status: string;
  evidence?: Record<string, unknown>;
}

export interface KillerDemoReport {
  ok?: boolean;
  kind?: string;
  summary?: Record<string, unknown>;
  stages?: DemoStage[];
  workflow_path?: string;
  evidence?: DemoEvidence;
  protocol_exports?: ProtocolExports;
  protocol_smoke_suite?: ProtocolSmokeSuite;
  next_commands?: string[];
}

export interface DemoArtifact {
  artifact_id?: string;
  label?: string;
  kind?: string;
  content_type?: string;
  bytes?: number;
  path?: string;
}

export interface DemoEvidence {
  run_id?: string;
  task_artifact_count?: number;
  task_artifacts?: DemoArtifact[];
  event_count?: number;
  audit_count?: number;
  artifact_count?: number;
  events?: unknown[];
  audit?: unknown[];
  artifacts?: unknown[];
}

export interface EvidenceSummary {
  status: string;
  workflowStatus: string;
  completedStages: number;
  blockedStages: number;
  routeCount: number;
  taskArtifactCount: number;
  eventCount: number;
  auditCount: number;
  smokeOk: string;
  bridgeLabOk: string;
  artifactIds: string[];
}

export interface ProtocolExports {
  exports?: {
    mcp?: {
      wire_compatible?: boolean;
      workflowTools?: unknown[];
    };
    a2a?: {
      wire_compatible?: boolean;
      agentCard?: {
        skills?: unknown[];
      };
    };
    acp?: {
      wire_compatible?: boolean;
      workflows?: unknown[];
    };
  };
}

export interface ProtocolSmokeSuite {
  ok?: boolean;
  summary?: {
    failed_count?: number;
    passed_count?: number;
    check_count?: number;
    by_protocol?: Record<string, { passed?: number; failed?: number }>;
  };
}

export interface ProtocolSummary {
  mcpWorkflowTools: number;
  a2aSkills: number;
  acpWorkflows: number;
  mcpSmoke: string;
  a2aSmoke: string;
  acpSmoke: string;
  smokeChecks: number;
  smokeFailures: number;
  wireCompatible: {
    mcp: string;
    a2a: string;
    acp: string;
  };
}

export interface AgentCardRecord {
  kind: "AgentCard";
  metadata: {
    id: string;
    title?: string;
    role?: string;
    status?: string;
    sequence?: number;
  };
  spec: {
    capabilities?: string[];
    policy?: {
      risk?: string;
      allowedActions?: string[];
      deniedActions?: string[];
    };
  };
}

export interface AgentTaskRecord {
  kind: "AgentTask";
  metadata: {
    id: string;
    agentId: string;
  };
  spec: {
    instruction?: string;
    uses?: string;
    inputs?: Record<string, unknown>;
  };
}

export interface AgentWorkflowNode {
  id: string;
  agent: string;
  instruction?: string;
  uses?: string;
  with?: Record<string, unknown>;
}

export interface AdapterAgentNodeBundle {
  ok?: boolean;
  kind?: "AdapterAgentNodeBundle";
  status?: string;
  workflow_path?: string;
  cards?: AgentCardRecord[];
  tasks?: AgentTaskRecord[];
  workflow_nodes?: AgentWorkflowNode[];
  bridge_message?: unknown;
  source_coordination_plan?: {
    handoffs?: Array<Record<string, unknown>>;
    profile_scope?: string[];
    tool_call_plan_summary?: Record<string, unknown>;
  };
}

export interface CompactAgentSession {
  kind?: "AgentSession";
  id?: string;
  agent_id?: string;
  workflow_id?: string;
  state?: string;
}

export interface CompactAgentCard {
  kind?: "AgentCard";
  id?: string;
  title?: string;
  role?: string;
  status?: string;
  capabilities?: string[];
  transport?: string;
  risk?: string;
}

export interface CompactAgentHarness {
  kind?: "AgentHarness";
  id?: string;
  agent_id?: string;
  accepts?: string[];
  emits?: string[];
}

export interface CompactAgentTask {
  kind?: "AgentTask";
  id?: string;
  agent_id?: string;
  instruction?: string;
  uses?: string;
  selectors?: string[];
}

export interface CompactAgentBridgeMessage {
  kind?: "BridgeMessage";
  producer?: string;
  channel?: string;
  correlation_id?: string;
}

export interface ConnectEndpoint {
  method: string;
  path: string;
  url?: string;
  purpose?: string;
}

export interface QuickstartRequest {
  id?: string;
  method?: string;
  url?: string;
  headers?: Record<string, string>;
  json?: Record<string, unknown>;
  curl?: string;
}

export interface ConnectionAcceptanceCheck {
  id?: string;
  request_id?: string;
  proves?: string;
  expect?: Record<string, unknown>;
}

export interface NetworkConnectionAcceptance {
  kind?: "NetworkConnectionAcceptance";
  status?: string;
  workflow_path?: string;
  required_request_ids?: string[];
  check_count?: number;
  checks?: ConnectionAcceptanceCheck[];
  success_signals?: string[];
  failure_recovery?: string[];
}

export interface AcceptanceExecutionResult {
  check_id: string;
  request_id: string;
  status: "passed" | "failed" | "skipped";
  http_status?: number;
  proves?: string;
  expect?: Record<string, unknown>;
  evidence?: Record<string, unknown>;
  error?: string;
}

export interface NetworkConnectionAcceptanceReport {
  ok?: boolean;
  kind?: "NetworkConnectionAcceptanceReport";
  status?: string;
  workflow_path?: string;
  base_url?: string;
  summary?: {
    connect_package_ok?: boolean;
    request_count?: number;
    check_count?: number;
    passed?: number;
    failed?: number;
    skipped?: number;
  };
  acceptance?: NetworkConnectionAcceptance;
  results?: AcceptanceExecutionResult[];
  next_commands?: string[];
}

export interface NetworkConnectPackage {
  ok?: boolean;
  kind?: "NetworkConnectPackage";
  summary?: {
    workflow_id?: string;
    task_count?: number;
    bridge_route_count?: number;
    protocol_export_count?: number;
    agent_card_count?: number;
    external_contract_ready?: boolean;
    recommended_next_action?: string;
  };
  contracts?: {
    internal?: {
      protocol?: string;
      api_version?: string;
      contract_sections?: string[];
      contracts?: {
        tool_manifest?: BridgeContractSection;
        bridge_message?: BridgeContractSection;
        artifact?: BridgeContractSection;
        workflow_selector?: BridgeContractSection;
      };
      bridge_contract?: {
        ok?: boolean;
        summary?: BridgeContractReport["summary"];
        contract?: BridgeContractReport["contract"];
      };
    };
    external?: {
      protocol?: string;
      accepted_kinds?: string[];
      generated_capability_ids?: string[];
      receipt_mapping?: {
        message_kind?: string;
        message_channel?: string;
        artifact_count?: number;
      };
    };
  };
  daemon_endpoints?: ConnectEndpoint[];
  protocols?: {
    targets?: string[];
    mcp?: { workflow_tool_count?: number; wire_facade?: string };
    a2a?: { skill_count?: number; wire_facade?: string };
    acp?: { workflow_count?: number; wire_facade?: string };
  };
  workflow_studio?: {
    kind?: "WorkflowStudioDemoLink";
    ok?: boolean;
    studio_url?: string;
    dashboard_url?: string | null;
    daemon_url?: string | null;
    workflow_path?: string;
    dry_run?: boolean;
    confirmed?: boolean;
    session_token_included?: boolean;
    url?: string;
    query?: Record<string, string>;
  };
  agent_node_bundle?: {
    kind?: "AdapterAgentNodeBundle";
    ok?: boolean;
    status?: string;
    card_count?: number;
    task_count?: number;
    session?: CompactAgentSession;
    cards?: CompactAgentCard[];
    harnesses?: CompactAgentHarness[];
    tasks?: CompactAgentTask[];
    bridge_message_channel?: string;
    bridge_message?: CompactAgentBridgeMessage;
    workflow_nodes?: AgentWorkflowNode[];
  };
  acceptance?: NetworkConnectionAcceptance;
  consumer_quickstart?: {
    kind?: "NetworkConnectQuickstart";
    status?: string;
    required_headers?: Record<string, string>;
    entrypoints?: {
      open_studio?: string;
      health?: string;
      inspect_workflow?: string;
      inspect_bridge_contract?: string;
      inspect_agent_nodes?: string;
      export_protocols?: string;
      plan_agent_request?: {
        method?: string;
        url?: string;
        json?: Record<string, unknown>;
      };
      run_workflow?: {
        method?: string;
        url?: string;
        json?: Record<string, unknown>;
      };
      events?: string;
      audit?: string;
      artifacts?: string;
    };
    requests?: QuickstartRequest[];
    acceptance?: NetworkConnectionAcceptance;
    curl_script?: string;
    powershell_script?: string;
    sequence?: string[];
  };
  next_commands?: string[];
}

export interface ConnectSummary {
  status: string;
  externalProtocol: string;
  acceptedKinds: string;
  generatedCapabilities: string[];
  bridgeRoutes: number;
  endpointCount: number;
  protocolExports: number;
  agentCards: number;
  nextAction: string;
  studioLink: string;
  studioToken: string;
  studioMode: string;
  quickstartStatus: string;
  authHeaderStatus: string;
  runEndpoint: string;
  planEndpoint: string;
  agentNodesEndpoint: string;
  protocolExportsEndpoint: string;
  quickstartRequestCount: number;
  acceptanceStatus: string;
  acceptanceCheckCount: number;
  curlScript: string;
  powershellScript: string;
}

export interface AcceptanceRunSummary {
  status: string;
  passed: number;
  failed: number;
  skipped: number;
  total: number;
}

export interface AgentWorkflowRequestPlan {
  ok?: boolean;
  kind?: "AdapterAgentWorkflowRequestPlan";
  status?: string;
  workflow_path?: string;
  request?: {
    message?: string;
    intent?: {
      mentions_run?: boolean;
      mentions_reuse?: boolean;
      mentions_artifact?: boolean;
    };
    binding?: string;
  };
  summary?: {
    workflow_id?: string;
    workflow_title?: string;
    task_count?: number;
    bridge_route_count?: number;
    agent_card_count?: number;
    recommended_next_action?: string;
  };
  run?: {
    payload?: Record<string, unknown>;
    cli?: string;
    http?: {
      method?: string;
      path?: string;
      url?: string;
      json?: Record<string, unknown>;
    };
  };
  reusable_harness?: {
    kind?: string;
    accepts?: string[];
    emits?: string[];
    contract?: string;
  };
  bridge_routes?: Array<Record<string, unknown>>;
  bridge_message?: unknown;
  next_commands?: string[];
}

export interface WorkflowRequestSummary {
  status: string;
  workflowId: string;
  tasks: number;
  routes: number;
  agents: number;
  nextAction: string;
  harnessKind: string;
  runCli: string;
}
