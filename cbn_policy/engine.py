"""Risk and confirmation policy checks."""

from __future__ import annotations

from dataclasses import dataclass

from cbn_core.manifest import CapabilityManifest
from cbn_execution.validation import VALID_RISKS, validate_risk


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    risk: str
    network: str
    requires_confirmation: bool

    def as_dict(self) -> dict[str, str | bool]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "risk": self.risk,
            "network": self.network,
            "requires_confirmation": self.requires_confirmation,
        }


class PolicyEngine:
    def evaluate(self, manifest: CapabilityManifest, confirmed: bool = False) -> PolicyDecision:
        validate_risk(manifest.policy.risk)
        requires_confirmation = manifest.policy.requires_confirmation or manifest.policy.risk in {
            "privileged",
            "external-network",
        } or manifest.policy.network == "requires-confirmation"
        if requires_confirmation and not confirmed:
            reason = _confirmation_reason(manifest)
            return PolicyDecision(
                allowed=False,
                reason=f"{reason} requires explicit confirmation",
                risk=manifest.policy.risk,
                network=manifest.policy.network,
                requires_confirmation=True,
            )
        if manifest.policy.risk not in VALID_RISKS:
            return PolicyDecision(
                allowed=False,
                reason=f"unknown risk={manifest.policy.risk}",
                risk=manifest.policy.risk,
                network=manifest.policy.network,
                requires_confirmation=requires_confirmation,
            )
        return PolicyDecision(
            allowed=True,
            reason="allowed",
            risk=manifest.policy.risk,
            network=manifest.policy.network,
            requires_confirmation=requires_confirmation,
        )


def _confirmation_reason(manifest: CapabilityManifest) -> str:
    reasons = []
    if manifest.policy.requires_confirmation:
        reasons.append("manifest policy")
    if manifest.policy.risk in {"privileged", "external-network"}:
        reasons.append(f"risk={manifest.policy.risk}")
    if manifest.policy.network == "requires-confirmation":
        reasons.append("network=requires-confirmation")
    return ", ".join(reasons) if reasons else "policy"
