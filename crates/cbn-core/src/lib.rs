pub const PACKAGE_NAME: &str = "cbn-core";

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RiskLevel {
    Read,
    WriteWorkspace,
    Privileged,
    ExternalNetwork,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CapabilityRecord {
    pub capability_id: String,
    pub title: String,
    pub transport: String,
    pub risk: RiskLevel,
}

