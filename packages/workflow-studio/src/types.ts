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

export interface QuickstartSequenceStep {
  order?: number;
  id?: string;
  kind?: string;
  title?: string;
  intent?: string;
  request_id?: string;
  request_ids?: string[];
  method?: string;
  url?: string;
  target?: string;
  success_signal?: string;
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

export interface AdapterAgentSetupGuidance {
  kind?: "AdapterAgentSetupGuidance";
  ok?: boolean;
  status?: string;
  setup_required?: boolean;
  next_action?: string;
  workflow_path?: string;
  summary?: AdapterAgentToolCallPlan["summary"];
  requires_user_count?: number;
  secret_count?: number;
  setup_command_count?: number;
  workflow_capability_count?: number;
  tool_calls?: Array<
    Pick<
      AdapterAgentToolCall,
      | "call_id"
      | "tool_use_id"
      | "kind"
      | "agent_role"
      | "action"
      | "risk"
      | "initial_status"
      | "requires_user"
      | "concurrency_safe"
    > & {
      setup_id?: string;
      profile?: string;
      command_id?: string;
      secret_name?: string;
      task_id?: string;
      capability_id?: string;
      permission?: string;
      permission_reason?: string;
    }
  >;
  execution_batches?: AdapterAgentExecutionBatch[];
  checkpoints?: AdapterAgentLoopCheckpoint[];
  safety?: {
    read_only?: boolean;
    executes_tools?: boolean;
    secret_values_included?: boolean;
    secrets_must_not_be_pasted_in_chat?: boolean;
  };
}

export interface ConnectDemoStage {
  id?: string;
  title?: string;
  proves?: string;
  capability_ids?: string[];
  endpoint?: ConnectEndpoint;
  endpoints?: ConnectEndpoint[];
  bridge_route_count?: number;
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
    registration_importer_count?: number;
    consumer_snippet_count?: number;
    setup_status?: string;
    setup_required?: boolean;
    setup_user_gate_count?: number;
    setup_secret_count?: number;
    demo_ready?: boolean;
    demo_stage_count?: number;
    demo_playbook_step_count?: number;
    cli_anything_split_status?: string;
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
      package_boundary?: ExternalProtocolPackageBoundary;
      package_health?: AgentCliContractPackageHealth;
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
  plugins?: {
    cli_anything?: CliAnythingPluginHealth;
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
  demo_readiness?: {
    kind?: "KillerDemoReadiness";
    status?: string;
    workflow_path?: string;
    workflow_id?: string;
    stage_count?: number;
    stages?: ConnectDemoStage[];
    required_capability_ids?: string[];
    evidence_contracts?: string[];
    protocol_targets?: string[];
    studio_url?: string;
    demo_endpoint?: ConnectEndpoint;
    acceptance_request_ids?: string[];
    next_commands?: string[];
  };
  demo_playbook?: KillerMvpDemoPlaybook;
  network_entry_profile?: NetworkEntryProfile;
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
  agent_workflow_request?: AgentWorkflowRequestPlan;
  setup_guidance?: AdapterAgentSetupGuidance;
  registration_surface?: CliRegistrationSurface;
  acceptance?: NetworkConnectionAcceptance;
  consumer_quickstart?: {
    kind?: "NetworkConnectQuickstart";
    status?: string;
    required_headers?: Record<string, string>;
    entrypoints?: {
      open_studio?: string;
      health?: string;
      import_catalog?: string;
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
    sdk_snippets?: QuickstartSdkSnippet[];
    curl_script?: string;
    powershell_script?: string;
    sequence?: string[];
    sequence_steps?: QuickstartSequenceStep[];
  };
  next_commands?: string[];
}

export interface NetworkEntryProfile {
  kind?: "NetworkEntryProfile";
  status?: string;
  profile_id?: string;
  display_name?: string;
  workflow_path?: string;
  base_url?: string | null;
  integration_mode?: string;
  compatibility?: {
    api_version?: string;
    additive_fields_only?: boolean;
    external_protocol?: string;
    external_kinds?: string[];
    internal_bus?: string;
    stable_fields?: string[];
  };
  auth?: {
    required_headers?: Record<string, string>;
    session_token_required?: boolean;
    session_token_included?: boolean;
  };
  primary_entrypoints?: {
    open_studio?: string;
    health?: string;
    import_catalog?: string;
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
    verify_network?: string;
  };
  harness_agent?: {
    kind?: string;
    request_binding?: string;
    message?: string;
    accepts?: string[];
    emits?: string[];
    bridge_message_channel?: string;
    bridge_route_count?: number;
    plan_endpoint?: string;
    run_endpoint?: string;
  };
  evidence?: {
    acceptance_status?: string;
    acceptance_check_count?: number;
    required_request_ids?: string[];
    evidence_endpoints?: {
      events?: string;
      audit?: string;
      artifacts?: string;
    };
    demo_status?: string;
    demo_stage_count?: number;
    playbook_status?: string;
    playbook_step_count?: number;
  };
  registration?: {
    status?: string;
    importer_count?: number;
    importer_ids?: string[];
    next_commands?: string[];
  };
  setup?: {
    status?: string;
    setup_required?: boolean;
    requires_user_count?: number;
    secret_count?: number;
  };
  protocol_facades?: {
    targets?: string[];
    export_count?: number;
  };
}

export interface CliAnythingPluginHealth {
  plugin_id?: string;
  entrypoint?: string;
  entrypoint_path?: string | null;
  entrypoint_available?: boolean;
  source_repo_dir?: string;
  source_repo_available?: boolean;
  version?: string | null;
  module_split?: CliAnythingModuleSplitReport;
}

export interface CliAnythingModuleSplitReport {
  kind?: "CliAnythingModuleSplitReport";
  status?: string;
  facade_module?: string;
  facade_path?: string | null;
  facade_line_count?: number | null;
  expected_part_count?: number;
  present_part_count?: number;
  parts?: Array<{
    id?: string;
    module?: string;
    present?: boolean;
    path?: string | null;
  }>;
  strategy?: string;
  next_targets?: string[];
}

export interface ExternalProtocolPackageBoundary {
  kind?: "ExternalProtocolPackageBoundary";
  package_name?: string;
  npm_name?: string;
  python_name?: string;
  version?: string;
  root?: string;
  schemas?: Record<string, string>;
  typescript_types?: string;
  python_validator?: string;
  fixtures?: Record<string, string>;
  conformance_smoke?: {
    command?: string;
    script?: string;
  };
  dependency_boundary?: {
    standalone?: boolean;
    forbidden_cbn_modules?: string[];
    allowed_scope?: string[];
  };
  cbn_mapping_responsibility?: Record<string, string>;
}

export interface AgentCliContractPackageHealth {
  kind?: "AgentCliContractPackageHealth";
  ok?: boolean;
  root?: string;
  package_boundary?: ExternalProtocolPackageBoundary;
  metadata?: {
    npm_name?: string;
    npm_version?: string;
    npm_private?: boolean;
    npm_exports?: Record<string, unknown>;
    python_name?: string;
    python_version?: string;
    python_dependencies?: string[];
    python_requires?: string;
  };
  file_count?: number;
  files?: Array<{
    id?: string;
    path?: string;
    relative_path?: string;
    role?: string;
    exists?: boolean;
  }>;
  independence?: {
    ok?: boolean;
    forbidden_cbn_modules?: string[];
    offenders?: Array<{
      path?: string;
      module?: string;
    }>;
    source_file_count?: number;
  };
}

export interface ConnectSummary {
  status: string;
  entryProfileStatus: string;
  entryProfileMode: string;
  entryProfileId: string;
  entryProfileStableFields: string;
  entryProfileAuth: string;
  entryProfileEvidence: string;
  externalProtocol: string;
  acceptedKinds: string;
  externalPackageStatus: string;
  externalPackageFiles: number;
  externalPackageSourceFiles: number;
  externalPackageNpm: string;
  externalPackagePython: string;
  generatedCapabilities: string[];
  bridgeRoutes: number;
  endpointCount: number;
  protocolExports: number;
  agentCards: number;
  registrationImporters: number;
  consumerSnippets: number;
  registrationPolicy: string;
  cliAnythingSplitStatus: string;
  cliAnythingSplitParts: string;
  cliAnythingFacadeLines: number;
  cliAnythingEntrypoint: string;
  demoReadinessStatus: string;
  demoStageCount: number;
  demoPlaybookStatus: string;
  demoPlaybookSteps: number;
  setupStatus: string;
  setupRequired: string;
  setupUserGates: number;
  setupSecrets: number;
  setupCommands: number;
  setupSafety: string;
  harnessKind: string;
  harnessBinding: string;
  harnessRouteCount: number;
  harnessRunEndpoint: string;
  harnessBridgeChannel: string;
  demoEndpoint: string;
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

export interface QuickstartSdkSnippet {
  id?: string;
  title?: string;
  language?: string;
  runtime?: string;
  entrypoint?: string;
  workflow_path?: string;
  uses_request_ids?: string[];
  code?: string;
  safety?: {
    dry_run?: boolean;
    confirmed?: boolean;
    writes_files?: boolean;
    requires_daemon?: boolean;
  };
}

export interface DemoPlaybookStep {
  id?: string;
  title?: string;
  intent?: string;
  action?: string;
  target?: unknown;
  command?: string;
  success_signal?: string;
}

export interface KillerMvpDemoPlaybook {
  kind?: "KillerMvpDemoPlaybook";
  status?: string;
  workflow_path?: string;
  step_count?: number;
  steps?: DemoPlaybookStep[];
  success_criteria?: string[];
  next_commands?: string[];
}

export interface CliRegistrationImporter {
  id?: string;
  title?: string;
  entrypoint?: string;
  accepts?: string[];
  produces?: string[];
  default_side_effects?: string;
  write_gate?: string | null;
  confirm_gate?: string | null;
  example?: string;
}

export interface CliRegistrationSurface {
  kind?: "CliRegistrationSurface";
  status?: string;
  importer_count?: number;
  default_policy?: {
    dry_run_by_default?: boolean;
    writes_require_explicit_flag?: boolean;
    side_effects_require_confirmation?: boolean;
    utf8_required?: boolean;
  };
  importers?: CliRegistrationImporter[];
  next_commands?: string[];
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
  workflow_id?: string;
  workflow_title?: string;
  task_count?: number;
  bridge_route_count?: number;
  agent_card_count?: number;
  recommended_next_action?: string;
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
  bridge_message_channel?: string;
  next_commands?: string[];
}

export interface AdapterAgentToolCall {
  call_id?: string;
  tool_use_id?: string;
  kind?: string;
  agent_role?: string;
  tool?: string;
  action?: string;
  argv?: string[];
  risk?: string;
  initial_status?: string;
  requires_user?: boolean;
  concurrency_safe?: boolean;
  permission_flow?: {
    default_behavior?: string;
    reason?: string;
  };
  source?: {
    setup_id?: string;
    profile?: string;
    command_id?: string;
    secret_name?: string;
  };
}

export interface AdapterAgentExecutionBatch {
  batch_id?: string;
  mode?: string;
  concurrency_safe?: boolean;
  tool_call_ids?: string[];
  tool_use_ids?: string[];
  reason?: string;
}

export interface AdapterAgentLoopCheckpoint {
  id?: string;
  owner?: string;
  status?: string;
  evidence?: unknown;
}

export interface AdapterAgentToolCallPlan {
  kind?: "AdapterAgentToolCallPlan";
  ok?: boolean;
  status?: string | null;
  workflow_path?: string;
  summary?: {
    tool_call_count?: number;
    batch_count?: number;
    concurrency_safe_count?: number;
    serial_count?: number;
    requires_user_count?: number;
    by_initial_status?: Record<string, number>;
    by_kind?: Record<string, number>;
  };
  tool_calls?: AdapterAgentToolCall[];
  execution_batches?: AdapterAgentExecutionBatch[];
  long_running_loop?: {
    kind?: "AdapterAgentLoopPlan";
    status?: string;
    checkpoints?: AdapterAgentLoopCheckpoint[];
  };
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
