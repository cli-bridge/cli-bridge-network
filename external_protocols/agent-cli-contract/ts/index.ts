export type AgentCliApiVersion = "agent-cli.dev/v1alpha1";

export type AgentCliRisk = "read" | "write-workspace" | "privileged" | "external-network";

export interface AgentCliCard {
  apiVersion: AgentCliApiVersion;
  kind: "AgentCliCard";
  metadata: {
    id: string;
    name: string;
    version: string;
    description?: string;
    homepage?: string;
    labels?: Record<string, string>;
    [key: string]: unknown;
  };
  spec: {
    runtime?: {
      kind?: "stdio" | "pty" | "http" | "mcp" | "agent";
      command?: string;
      cwdPolicy?: "workspace" | "manifest" | "fixed" | "none";
      [key: string]: unknown;
    };
    commands: AgentCliCommand[];
    [key: string]: unknown;
  };
}

export interface AgentCliCommand {
  id: string;
  title: string;
  description?: string;
  argv: string[];
  inputSchema?: Record<string, unknown>;
  output?: {
    mediaType?: string;
    parser?: string;
    [key: string]: unknown;
  };
  policy?: {
    risk?: AgentCliRisk;
    requiresConfirmation?: boolean;
    network?: string;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export type RunReceiptStatus = "completed" | "failed" | "blocked" | "running" | "canceled";

export interface RunReceipt {
  apiVersion: AgentCliApiVersion;
  kind: "RunReceipt";
  runId: string;
  cardId: string;
  commandId: string;
  status: RunReceiptStatus;
  startedAt?: string;
  completedAt?: string;
  exitCode?: number | null;
  stdout?: string;
  stderr?: string;
  parsed?: Record<string, unknown>;
  artifacts?: RunReceiptArtifact[];
  error?: {
    code?: string;
    message?: string;
    retryable?: boolean;
    [key: string]: unknown;
  };
  correlation?: {
    traceId?: string;
    parentRunId?: string;
    [key: string]: unknown;
  };
}

export interface RunReceiptArtifact {
  id: string;
  kind: string;
  uri?: string;
  mediaType?: string;
  sizeBytes?: number;
  sha256?: string;
  [key: string]: unknown;
}
