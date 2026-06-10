export type RiskLevel = "read" | "write-workspace" | "privileged" | "external-network";

export interface CapabilityRecord {
  capabilityId: string;
  title: string;
  transport: string;
  risk: RiskLevel;
}

