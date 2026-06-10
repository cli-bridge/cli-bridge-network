export interface StudioConfig {
  daemonUrl: string;
  sessionToken: string;
  workflowPath: string;
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
