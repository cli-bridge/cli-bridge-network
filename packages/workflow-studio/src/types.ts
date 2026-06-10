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
