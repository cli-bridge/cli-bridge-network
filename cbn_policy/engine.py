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
    requires_confirmation: bool

    def as_dict(self) -> dict[str, str | bool]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "risk": self.risk,
            "requires_confirmation": self.requires_confirmation,
        }


class PolicyEngine:
    def evaluate(self, manifest: CapabilityManifest, confirmed: bool = False) -> PolicyDecision:
        validate_risk(manifest.policy.risk)
        requires_confirmation = manifest.policy.requires_confirmation or manifest.policy.risk in {
            "privileged",
            "external-network",
        }
        if requires_confirmation and not confirmed:
            return PolicyDecision(
                allowed=False,
                reason=f"risk={manifest.policy.risk} requires explicit confirmation",
                risk=manifest.policy.risk,
                requires_confirmation=True,
            )
        if manifest.policy.risk not in VALID_RISKS:
            return PolicyDecision(
                allowed=False,
                reason=f"unknown risk={manifest.policy.risk}",
                risk=manifest.policy.risk,
                requires_confirmation=requires_confirmation,
            )
        return PolicyDecision(
            allowed=True,
            reason="allowed",
            risk=manifest.policy.risk,
            requires_confirmation=requires_confirmation,
        )

