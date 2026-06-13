"""Manifest Bootstrap Agent plan builder."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbn_adapter_agent.agent_roles import get_agent_role
from cbn_adapter_agent.compiler import BUILT_IN_PROFILES, build_adapter_draft_batch


def build_manifest_bootstrap_plan(
    profiles: tuple[str, ...] | None = None,
    *,
    root: Path | None = None,
    include_drafts: bool = True,
) -> dict[str, Any]:
    """Build a role-scoped plan for manifest/profile bootstrap work."""

    profile_ids = profiles or tuple(BUILT_IN_PROFILES)
    batch = build_adapter_draft_batch(profiles=profile_ids, root=root)
    profile_summaries = [_profile_summary(draft) for draft in batch["drafts"]]
    payload: dict[str, Any] = {
        "kind": "ManifestBootstrapPlan",
        "apiVersion": "bridge.dev/v1alpha1",
        "ok": batch["ok"],
        "agent_role": get_agent_role("manifest-bootstrap-agent"),
        "agent_policy": _manifest_bootstrap_policy(),
        "profile_scope": list(profile_ids),
        "summary": _manifest_bootstrap_summary(batch["summary"], profile_summaries),
        "profile_summaries": profile_summaries,
        "handoff": _manifest_bootstrap_handoff(),
        "next_actions": _next_actions(profile_summaries),
    }
    if include_drafts:
        payload["drafts"] = batch["drafts"]
    return payload


def _manifest_bootstrap_policy() -> dict[str, Any]:
    return {
        "role": "manifest-bootstrap-agent",
        "plans_probes_only": True,
        "installs_tools": False,
        "runs_workflow_tasks": False,
        "writes_adapter_lock": False,
        "acceptance_required_before_promotion": True,
    }


def _manifest_bootstrap_summary(
    batch_summary: dict[str, Any],
    profile_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        **batch_summary,
        "setup_guide_count": sum(item["setup_guide_count"] for item in profile_summaries),
        "unverified_capability_count": sum(len(item["unverified_capabilities"]) for item in profile_summaries),
    }


def _manifest_bootstrap_handoff() -> dict[str, Any]:
    return {
        "from": "manifest-bootstrap-agent",
        "to": "workflow-setup-agent",
        "artifact": "accepted CapabilityManifest registry plus adapter.lock preview",
        "requires_user_acceptance": True,
    }


def _profile_summary(draft: dict[str, Any]) -> dict[str, Any]:
    stages = {
        str(stage["id"]): str(stage["status"])
        for stage in draft.get("stages", [])
    }
    unverified = []
    for candidate in draft.get("capability_candidates", []):
        output = candidate.get("output") if isinstance(candidate, dict) else None
        if not isinstance(output, dict):
            continue
        if not output.get("manifest_verified") or not output.get("fixture_verified"):
            unverified.append(candidate.get("capability_id"))
    return {
        "profile": draft.get("profile"),
        "ok": draft.get("ok"),
        "candidate_count": len(draft.get("capability_candidates", [])),
        "setup_guide_count": len(draft.get("setup_guides", [])),
        "risk_summary": draft.get("risk_summary"),
        "stage_statuses": stages,
        "unverified_capabilities": unverified,
        "adapter_lock_preview": {
            "profile_id": (draft.get("adapter_lock_preview") or {}).get("profile_id"),
            "capability_count": (draft.get("adapter_lock_preview") or {}).get("capability_count"),
            "digest": (draft.get("adapter_lock_preview") or {}).get("digest"),
        },
        "next_actions": draft.get("next_actions"),
    }


def _next_actions(profile_summaries: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    unverified_profiles = [
        str(item["profile"]["profile_id"])
        for item in profile_summaries
        if item.get("unverified_capabilities")
    ]
    if unverified_profiles:
        actions.append("add parser fixtures before promoting profiles: " + ", ".join(unverified_profiles))
    actions.append("present manifest bootstrap diff for user acceptance")
    actions.append("handoff accepted manifests to workflow-setup-agent")
    return actions
