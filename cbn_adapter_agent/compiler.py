"""Built-in Adapter Agent harness for compiling CLI profiles into CBN drafts.

The harness is not a chat runtime. It turns probe plans, existing manifests,
policy classifications, and parser fixture coverage into a structured draft
that a future UI can present as an adapter diff.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cbn.paths import resolve_project_paths
from cbn_core.manifest import CapabilityManifest, ManifestRegistry, validate_manifest_path
from cbn_parsers.fixtures import run_parser_fixtures
from cbn_adapter_agent.agent_roles import get_agent_role
from cbn_adapter_agent.auth_setup import build_auth_setup_guide
from cbn_tools.external_cli import require_action


@dataclass(frozen=True)
class AdapterProfile:
    profile_id: str
    title: str
    source: str
    actions: tuple[str, ...]
    notes: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "title": self.title,
            "source": self.source,
            "actions": list(self.actions),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class _AdapterDraftContext:
    profile: AdapterProfile
    probe_plans: list[dict[str, object]]
    candidate_records: list[dict[str, object]]
    risk_summary: dict[str, object]
    setup_guides: list[dict[str, object]]
    fixture_coverage: dict[str, Any]
    manifest_validation: dict[str, Any]
    stages: list[dict[str, object]]


BUILT_IN_PROFILES: dict[str, AdapterProfile] = {
    "feishu": AdapterProfile(
        profile_id="feishu",
        title="Feishu/Lark CLI",
        source="direct CLI plus CLI-Anything install evidence",
        actions=("version", "help", "schema-help", "doctor"),
        notes=(
            "lark-cli version/help are read-only probes.",
            "doctor can contact Feishu/Lark services and remains gated.",
        ),
    ),
    "obsidian-cli": AdapterProfile(
        profile_id="obsidian-cli",
        title="Obsidian CLI and Local REST Harness",
        source="official Obsidian CLI shim plus Local REST harness evidence",
        actions=("official-help", "local-rest-help", "local-rest-server-status", "local-rest-note-read"),
        notes=(
            "official CLI requires the desktop process and GUI CLI toggle.",
            "Local REST note reads are localhost transport but privacy-sensitive.",
        ),
    ),
    "jimeng": AdapterProfile(
        profile_id="jimeng",
        title="Jimeng/Dreamina CLI",
        source="WSL Dreamina binary installed from official script",
        actions=("version", "help", "user-credit", "list-task", "query-result", "text2image-submit"),
        notes=(
            "version/help are read-only probes.",
            "generation and account commands require OAuth and can consume credits.",
        ),
    ),
    "caw": AdapterProfile(
        profile_id="caw",
        title="Cobo Agentic Wallet CLI",
        source="WSL CAW binary installed from Cobo script",
        actions=("version", "help", "schema-help", "status"),
        notes=(
            "version/help/schema probes are read-only.",
            "wallet status and chain actions require explicit confirmation.",
        ),
    ),
}


def build_adapter_draft(profile_id: str, root: Path | None = None) -> dict[str, Any]:
    context = _adapter_draft_context(profile_id, root)
    return _adapter_draft_payload(context)


def _adapter_draft_context(profile_id: str, root: Path | None) -> _AdapterDraftContext:
    paths = resolve_project_paths(root)
    profile = _require_profile(profile_id)
    registry = ManifestRegistry()
    registry.load_dir(paths.manifests)
    candidates = _profile_candidates(registry, profile.profile_id)
    probe_plans = _probe_plans(profile, paths.root)
    fixture_coverage = _fixture_coverage(paths.root / "parser_fixtures")
    manifest_validation = validate_manifest_path(paths.manifests)
    verified_capabilities = set(fixture_coverage["verified_capabilities"])
    candidate_records = [
        _candidate_record(candidate, verified_capabilities=verified_capabilities)
        for candidate in candidates
    ]
    risk_summary = _risk_summary(candidate_records)
    setup_guides = _setup_guides(candidates, root=paths.root)
    stages = _stages(
        profile=profile,
        probe_plans=probe_plans,
        candidate_records=candidate_records,
        manifest_validation=manifest_validation,
        fixture_coverage=fixture_coverage,
    )
    return _AdapterDraftContext(
        profile=profile,
        probe_plans=probe_plans,
        candidate_records=candidate_records,
        risk_summary=risk_summary,
        setup_guides=setup_guides,
        fixture_coverage=fixture_coverage,
        manifest_validation=manifest_validation,
        stages=stages,
    )


def _adapter_draft_payload(context: _AdapterDraftContext) -> dict[str, Any]:
    return {
        "kind": "AdapterAgentDraft",
        "apiVersion": "bridge.dev/v1alpha1",
        "ok": all(stage["status"] != "blocked" for stage in context.stages),
        "agent_role": get_agent_role("manifest-bootstrap-agent"),
        "profile": context.profile.as_dict(),
        "agent_policy": {
            "role": "manifest-bootstrap-agent",
            "legacy_role": "initialization-compiler",
            "llm_runtime_dependency": False,
            "runtime_calls_use_accepted_manifests": True,
            "writes_require_explicit_flag": True,
            "high_risk_registration_requires_human_acceptance": True,
        },
        "probe_plans": context.probe_plans,
        "capability_candidates": context.candidate_records,
        "risk_summary": context.risk_summary,
        "setup_guides": context.setup_guides,
        "parser_fixture_coverage": context.fixture_coverage,
        "manifest_validation": {
            "valid": context.manifest_validation["valid"],
            "checked_count": context.manifest_validation["checked_count"],
            "error_count": context.manifest_validation["error_count"],
            "warning_count": context.manifest_validation["warning_count"],
        },
        "stages": context.stages,
        "adapter_lock_preview": _adapter_lock_preview(context.profile, context.candidate_records),
        "next_actions": _next_actions(context.stages),
    }


def build_adapter_draft_batch(
    profiles: tuple[str, ...] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    profile_ids = profiles or tuple(BUILT_IN_PROFILES)
    drafts = [build_adapter_draft(profile_id, root=root) for profile_id in profile_ids]
    return {
        "kind": "AdapterAgentDraftBatch",
        "apiVersion": "bridge.dev/v1alpha1",
        "ok": all(draft["ok"] for draft in drafts),
        "drafts": drafts,
        "summary": {
            "profile_count": len(drafts),
            "candidate_count": sum(len(draft["capability_candidates"]) for draft in drafts),
            "blocked_count": sum(1 for draft in drafts if not draft["ok"]),
        },
    }


def write_adapter_draft(
    draft: dict[str, Any],
    output_dir: Path | None = None,
    root: Path | None = None,
) -> dict[str, str]:
    paths = resolve_project_paths(root)
    target_dir = output_dir or (paths.runtime / "adapter-agent" / "drafts")
    target_dir.mkdir(parents=True, exist_ok=True)
    profile_id = str(draft["profile"]["profile_id"])
    path = target_dir / f"{profile_id}.adapter-draft.json"
    path.write_text(json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"profile_id": profile_id, "path": str(path)}


def _require_profile(profile_id: str) -> AdapterProfile:
    try:
        return BUILT_IN_PROFILES[profile_id]
    except KeyError as exc:
        known = ", ".join(sorted(BUILT_IN_PROFILES))
        raise KeyError(f"unknown adapter profile {profile_id!r}; known profiles: {known}") from exc


def _profile_candidates(registry: ManifestRegistry, profile_id: str) -> list[CapabilityManifest]:
    return [
        manifest
        for manifest in registry.list()
        if manifest.labels.get("profile") == profile_id
        or manifest.annotations.get("cbn.adapter.profile") == profile_id
    ]


def _probe_plans(profile: AdapterProfile, root: Path) -> list[dict[str, object]]:
    plans = []
    for action_id in profile.actions:
        action = require_action(profile.profile_id, action_id)
        plans.append(
            {
                "profile": profile.profile_id,
                "action": action_id,
                "title": action.title,
                "argv": action.argv(root),
                "execution": "planned-only",
            }
        )
    return plans


def _candidate_record(
    manifest: CapabilityManifest,
    verified_capabilities: set[str],
) -> dict[str, object]:
    source_text = ""
    source_digest = None
    if manifest.source_path is not None:
        source_text = manifest.source_path.read_text(encoding="utf-8")
        source_digest = _digest_text(source_text)
    return {
        "capability_id": manifest.capability_id,
        "title": manifest.title,
        "source_path": str(manifest.source_path) if manifest.source_path else None,
        "source_digest": source_digest,
        "adapter_action": manifest.annotations.get("cbn.adapter.action"),
        "transport": {
            "kind": manifest.transport.kind,
            "argv": list(manifest.transport.argv()),
            "timeout_seconds": manifest.transport.timeout_seconds,
        },
        "policy": {
            "risk": manifest.policy.risk,
            "network": manifest.policy.network,
            "requires_confirmation": manifest.policy.requires_confirmation,
        },
        "output": {
            "parser_ref": manifest.output.parser_ref,
            "manifest_verified": manifest.output.verified,
            "fixture_verified": manifest.capability_id in verified_capabilities,
        },
        "auth_gate": manifest.annotations.get("cbn.auth_gate"),
        "workflow_hint": manifest.annotations.get("cbn.workflow_hint"),
    }


def _setup_guides(candidates: list[CapabilityManifest], *, root: Path) -> list[dict[str, object]]:
    by_id: dict[str, dict[str, object]] = {}
    for manifest in candidates:
        guide = build_auth_setup_guide(manifest, root=root)
        if guide is None:
            continue
        payload = guide.as_dict()
        by_id.setdefault(str(payload["setup_id"]), payload)
    return list(by_id.values())


def _fixture_coverage(fixture_dir: Path) -> dict[str, Any]:
    if not fixture_dir.exists():
        return {
            "ok": True,
            "fixture_count": 0,
            "case_count": 0,
            "failed_case_count": 0,
            "verified_capabilities": [],
        }
    report = run_parser_fixtures(fixture_dir)
    verified = {
        capability
        for fixture in report["reports"]
        for capability in fixture.get("verified_capabilities", [])
    }
    return {
        "ok": report["ok"],
        "fixture_count": report["fixture_count"],
        "case_count": report["case_count"],
        "failed_case_count": report["failed_case_count"],
        "verified_capabilities": sorted(verified),
    }


def _risk_summary(candidates: list[dict[str, object]]) -> dict[str, object]:
    by_risk: dict[str, int] = {}
    gated = 0
    for candidate in candidates:
        policy = candidate["policy"]
        assert isinstance(policy, dict)
        risk = str(policy["risk"])
        by_risk[risk] = by_risk.get(risk, 0) + 1
        if policy.get("requires_confirmation"):
            gated += 1
    return {
        "by_risk": by_risk,
        "requires_confirmation_count": gated,
        "candidate_count": len(candidates),
    }


def _stages(
    profile: AdapterProfile,
    probe_plans: list[dict[str, object]],
    candidate_records: list[dict[str, object]],
    manifest_validation: dict[str, Any],
    fixture_coverage: dict[str, Any],
) -> list[dict[str, object]]:
    unverified = _unverified_capabilities(candidate_records)
    return [
        _discover_profile_stage(profile),
        _probe_plan_stage(probe_plans),
        _manifest_candidates_stage(candidate_records),
        _manifest_schema_stage(manifest_validation),
        _policy_classification_stage(candidate_records),
        _parser_contracts_stage(fixture_coverage, unverified),
        _acceptance_stage(),
    ]


def _unverified_capabilities(candidate_records: list[dict[str, object]]) -> list[object]:
    return [
        candidate["capability_id"]
        for candidate in candidate_records
        if not _candidate_output_verified(candidate)
    ]


def _discover_profile_stage(profile: AdapterProfile) -> dict[str, object]:
    return {
        "id": "discover_profile",
        "status": "passed",
        "evidence": profile.source,
    }


def _probe_plan_stage(probe_plans: list[dict[str, object]]) -> dict[str, object]:
    return {
        "id": "probe_plan",
        "status": "passed" if probe_plans else "blocked",
        "evidence": {"planned_probe_count": len(probe_plans)},
    }


def _manifest_candidates_stage(candidate_records: list[dict[str, object]]) -> dict[str, object]:
    return {
        "id": "manifest_candidates",
        "status": "passed" if candidate_records else "blocked",
        "evidence": {"candidate_count": len(candidate_records)},
    }


def _manifest_schema_stage(manifest_validation: dict[str, Any]) -> dict[str, object]:
    return {
        "id": "manifest_schema",
        "status": "passed" if manifest_validation["valid"] else "blocked",
        "evidence": {
            "checked_count": manifest_validation["checked_count"],
            "error_count": manifest_validation["error_count"],
            "warning_count": manifest_validation["warning_count"],
        },
    }


def _policy_classification_stage(candidate_records: list[dict[str, object]]) -> dict[str, object]:
    return {
        "id": "policy_classification",
        "status": "passed",
        "evidence": _risk_summary(candidate_records),
    }


def _parser_contracts_stage(
    fixture_coverage: dict[str, Any],
    unverified: list[object],
) -> dict[str, object]:
    return {
        "id": "parser_contracts",
        "status": "partial" if unverified else "passed",
        "evidence": {
            "fixture_ok": fixture_coverage["ok"],
            "unverified_capabilities": unverified,
        },
    }


def _acceptance_stage() -> dict[str, object]:
    return {
        "id": "acceptance",
        "status": "pending",
        "evidence": "requires user review before writing adapter.lock or promoting parsers",
    }


def _candidate_output_verified(candidate: dict[str, object]) -> bool:
    output = candidate["output"]
    assert isinstance(output, dict)
    return bool(output["manifest_verified"]) and bool(output["fixture_verified"])


def _adapter_lock_preview(
    profile: AdapterProfile,
    candidate_records: list[dict[str, object]],
) -> dict[str, object]:
    capabilities = [
        {
            "capability_id": str(candidate["capability_id"]),
            "source_digest": candidate["source_digest"],
            "adapter_action": candidate["adapter_action"],
        }
        for candidate in candidate_records
    ]
    return {
        "profile_id": profile.profile_id,
        "lock_kind": "adapter.lock.preview",
        "capability_count": len(capabilities),
        "digest": _digest_json({"profile": profile.profile_id, "capabilities": capabilities}),
        "capabilities": capabilities,
    }


def _next_actions(stages: list[dict[str, object]]) -> list[str]:
    blocked = [stage["id"] for stage in stages if stage["status"] == "blocked"]
    if blocked:
        return [f"resolve blocked stage: {stage_id}" for stage_id in blocked]
    partial = [stage["id"] for stage in stages if stage["status"] == "partial"]
    actions = [f"promote partial stage with fixtures or typed parsers: {stage_id}" for stage_id in partial]
    actions.append("present structured diff for user acceptance")
    actions.append("write adapter.lock only after acceptance")
    return actions


def _digest_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _digest_json(payload: dict[str, object]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _digest_text(text)
