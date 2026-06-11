"""Market candidate and install queue helpers for CLI-Anything."""

from __future__ import annotations

from typing import Any, Protocol

from cbn_plugins.cli_anything_parts.lifecycle import (
    attach_candidate_readiness,
    refresh_candidate_lifecycle,
)
from cbn_plugins.cli_anything_parts.market import (
    mark_candidate_collisions,
    market_records_from_result,
)


PLUGIN_ID = "cli-anything"


class CommandResultLike(Protocol):
    argv: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    parsed_json: Any | None

    def as_dict(self) -> dict[str, Any]:
        ...


def candidate_harnesses(
    hub: Any,
    query: str | None = None,
    limit: int = 50,
    with_probes: bool = False,
    compact: bool = False,
) -> dict[str, Any]:
    result = hub.search_market(query) if query else hub.list_market()
    records = market_records_from_result(result.parsed_json)
    if result.exit_code != 0:
        return {
            "ok": False,
            "plugin_id": PLUGIN_ID,
            "query": query,
            "limit": max(0, min(limit, 500)),
            "with_probes": with_probes,
            "compact": compact,
            "error": "CLI-Anything market command failed",
            "market": market_command_payload(result, compact=compact),
            "selected_count": 0,
            "install_candidate_count": 0,
            "blocked_count": 0,
            "candidates": [],
            "candidate_summary": [],
        }
    if records is None:
        return {
            "ok": False,
            "plugin_id": PLUGIN_ID,
            "query": query,
            "limit": max(0, min(limit, 500)),
            "with_probes": with_probes,
            "compact": compact,
            "error": "CLI-Anything market command did not return a supported JSON list shape",
            "market": market_command_payload(result, compact=compact),
            "selected_count": 0,
            "install_candidate_count": 0,
            "blocked_count": 0,
            "candidates": [],
            "candidate_summary": [],
        }
    bounded_limit = max(0, min(limit, 500))
    candidates = [
        hub._candidate_from_market_record(record, market_index=index)
        for index, record in enumerate(records)
    ]
    mark_candidate_collisions(candidates)
    for item in candidates:
        refresh_candidate_lifecycle(item)
        if with_probes:
            attach_candidate_readiness(item)
    candidates.sort(
        key=lambda item: (
            not bool(item.get("install_candidate")),
            len(item.get("blockers", [])),
            item.get("harness_name") or "",
            item.get("market_index", 0),
        )
    )
    selected = candidates[:bounded_limit]
    for rank, item in enumerate(selected, start=1):
        item["rank"] = rank
    install_candidate_count = sum(1 for item in selected if item.get("install_candidate"))
    blocked_count = sum(1 for item in selected if not item.get("install_candidate"))
    probe_ready_count = sum(
        1
        for item in selected
        if isinstance(item.get("readiness"), dict) and item["readiness"].get("ready")
    )
    probe_blocked_count = sum(
        1
        for item in selected
        if isinstance(item.get("readiness"), dict) and item["readiness"].get("probe_blocker_count", 0) > 0
    )
    return {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "query": query,
        "limit": bounded_limit,
        "with_probes": with_probes,
        "compact": compact,
        "market_count": len(records),
        "evaluated_count": len(candidates),
        "selected_count": len(selected),
        "install_candidate_count": install_candidate_count,
        "blocked_count": blocked_count,
        "probe_ready_count": probe_ready_count if with_probes else None,
        "probe_blocked_count": probe_blocked_count if with_probes else None,
        "market": market_command_payload(result, compact=compact),
        "candidates": selected,
        "candidate_summary": candidate_summary(selected),
        "next_commands": [
            "python -m cbn plugin candidates cli-anything --query <query> --limit 20 --compact",
            "python -m cbn plugin candidates cli-anything --query <query> --limit 20 --with-probes --compact",
            "python -m cbn plugin evaluate-harness cli-anything <harness>",
            "python -m cbn plugin adapt-harness cli-anything <harness> --from-market --write",
            "python -m cbn plugin harness cli-anything install <harness> --yes",
        ],
    }


def market_install_queue(
    hub: Any,
    query: str | None = None,
    limit: int = 50,
    max_installs: int = 10,
    include_blocked: bool = True,
) -> dict[str, Any]:
    candidate_scan = hub.candidate_harnesses(
        query=query,
        limit=limit,
        with_probes=True,
        compact=True,
    )
    bounded_max_installs = max(0, min(max_installs, 100))
    if not candidate_scan.get("ok"):
        return {
            "ok": False,
            "plugin_id": PLUGIN_ID,
            "kind": "CliAnythingMarketInstallQueue",
            "query": query,
            "limit": max(0, min(limit, 500)),
            "max_installs": bounded_max_installs,
            "include_blocked": include_blocked,
            "error": candidate_scan.get("error", "CLI-Anything candidate scan failed"),
            "summary": {
                "candidate_count": 0,
                "queued_count": 0,
                "blocked_count": 0,
                "skipped_count": 0,
            },
            "queue": [],
            "blocked": [],
            "skipped": [],
            "candidate_scan": candidate_scan,
        }

    queue = []
    blocked = []
    skipped = []
    candidates = candidate_scan.get("candidates", [])
    if not isinstance(candidates, list):
        candidates = []

    for item in candidates:
        if not isinstance(item, dict):
            continue
        harness_name = item.get("harness_name")
        if not isinstance(harness_name, str) or not harness_name:
            blocked.append(install_queue_blocked_entry(item, "market record is missing harness_name"))
            continue
        gates = item.get("gates") if isinstance(item.get("gates"), dict) else {}
        if bool(item.get("install_candidate")) and not bool(gates.get("launch_ready")):
            evaluation = hub.evaluate_harness(harness_name, from_market=True)
            if not evaluation.get("ok"):
                blocked.append(
                    install_queue_blocked_entry(
                        item,
                        "harness evaluation failed before queueing",
                        evaluation=evaluation,
                    )
                )
                continue
            eval_gates = evaluation.get("gates") if isinstance(evaluation.get("gates"), dict) else {}
            if bool(eval_gates.get("launch_ready")):
                skipped.append(
                    install_queue_skipped_entry(
                        item,
                        "harness is already launch-ready",
                        evaluation=evaluation,
                    )
                )
                continue
            if not bool(evaluation.get("install_candidate")):
                blocked.append(
                    install_queue_blocked_entry(
                        item,
                        "harness evaluation blockers must be resolved first",
                        evaluation=evaluation,
                    )
                )
                continue
            if len(queue) >= bounded_max_installs:
                skipped.append(
                    install_queue_skipped_entry(
                        item,
                        "max_installs limit reached",
                        evaluation=evaluation,
                    )
                )
                continue
            queue.append(
                install_queue_entry(
                    item,
                    install_plan=hub.harness_plan("install", harness_name).as_dict(),
                    evaluation=evaluation,
                )
            )
        elif bool(item.get("install_candidate")) and bool(gates.get("launch_ready")):
            skipped.append(install_queue_skipped_entry(item, "harness is already launch-ready"))
        elif include_blocked:
            blocked.append(install_queue_blocked_entry(item, "candidate blockers must be resolved first"))

    return {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "kind": "CliAnythingMarketInstallQueue",
        "query": query,
        "limit": candidate_scan.get("limit"),
        "max_installs": bounded_max_installs,
        "include_blocked": include_blocked,
        "summary": {
            "candidate_count": len(candidates),
            "install_candidate_count": candidate_scan.get("install_candidate_count"),
            "probe_ready_count": candidate_scan.get("probe_ready_count"),
            "probe_blocked_count": candidate_scan.get("probe_blocked_count"),
            "queued_count": len(queue),
            "blocked_count": len(blocked),
            "skipped_count": len(skipped),
        },
        "queue": queue,
        "blocked": blocked,
        "skipped": skipped,
        "candidate_summary": candidate_scan.get("candidate_summary", []),
        "candidate_scan": candidate_scan,
        "next_commands": [
            "python -m cbn plugin install-queue cli-anything --query <query> --limit 20",
            "python -m cbn plugin onboard-harness cli-anything <harness> --from-market --write --install --yes --smoke-suite --smoke-extra-arg=--help --no-workflows",
            "python -m cbn plugin harness cli-anything install <harness> --yes",
        ],
    }


def market_command_payload(result: CommandResultLike, compact: bool) -> dict[str, Any]:
    if not compact:
        return result.as_dict()
    parsed = result.parsed_json
    payload: dict[str, Any] = {
        "argv": list(result.argv),
        "exit_code": result.exit_code,
        "stdout_chars": len(result.stdout or ""),
        "stderr_chars": len(result.stderr or ""),
        "stdout_omitted": bool(result.stdout),
        "parsed_json_omitted": parsed is not None,
        "parsed_json_type": type(parsed).__name__ if parsed is not None else None,
    }
    if isinstance(parsed, list):
        payload["parsed_json_count"] = len(parsed)
    elif isinstance(parsed, dict):
        payload["parsed_json_keys"] = sorted(str(key) for key in parsed.keys())
    if result.stderr:
        payload["stderr_tail"] = result.stderr[-4000:]
    return payload


def candidate_summary(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for item in candidates:
        readiness = item.get("readiness") if isinstance(item.get("readiness"), dict) else {}
        lifecycle = item.get("lifecycle") if isinstance(item.get("lifecycle"), dict) else {}
        local_status = item.get("local_status") if isinstance(item.get("local_status"), dict) else {}
        summary.append(
            {
                "rank": item.get("rank"),
                "harness_name": item.get("harness_name"),
                "display_name": item.get("display_name"),
                "capability_id": item.get("capability_id"),
                "install_candidate": bool(item.get("install_candidate")),
                "recommended_next_action": item.get("recommended_next_action"),
                "lifecycle_state": lifecycle.get("state"),
                "blocker_count": len(item.get("blockers", [])),
                "blockers": item.get("blockers", []),
                "launch_ready": bool(local_status.get("launch_ready")),
                "manifest_imported": bool(local_status.get("manifest_imported")),
                "entrypoint_available": bool(local_status.get("entrypoint_available")),
                "readiness_ready": readiness.get("ready"),
                "probe_blocker_count": readiness.get("probe_blocker_count"),
            }
        )
    return summary


def install_queue_entry(
    item: dict[str, Any],
    install_plan: dict[str, Any],
    evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    harness_name = item.get("harness_name")
    capability_id = item.get("capability_id")
    return {
        "rank": item.get("rank"),
        "harness_name": harness_name,
        "display_name": item.get("display_name"),
        "capability_id": capability_id,
        "state": "queued",
        "ready_for_install": True,
        "requires_confirmation": True,
        "recommended_next_action": item.get("recommended_next_action"),
        "lifecycle": item.get("lifecycle"),
        "gates": item.get("gates"),
        "readiness": item.get("readiness"),
        "evaluation": evaluation,
        "plan": install_plan,
        "commands": {
            "evaluate": f"python -m cbn plugin evaluate-harness cli-anything {harness_name}",
            "adapt_preview": f"python -m cbn plugin adapt-harness cli-anything {harness_name} --from-market",
            "onboard_preview": f"python -m cbn plugin onboard-harness cli-anything {harness_name} --from-market --smoke-suite --smoke-extra-arg=--help --no-workflows",
            "onboard_install": f"python -m cbn plugin onboard-harness cli-anything {harness_name} --from-market --write --install --yes --smoke-suite --smoke-extra-arg=--help --no-workflows",
            "install": f"python -m cbn plugin harness cli-anything install {harness_name} --yes",
            "dry_run_call": f"python -m cbn call {capability_id} --dry-run" if capability_id else None,
        },
    }


def install_queue_blocked_entry(
    item: dict[str, Any],
    reason: str,
    evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blockers = list(item.get("blockers", []))
    if evaluation and isinstance(evaluation.get("blockers"), list):
        for blocker in evaluation["blockers"]:
            if blocker not in blockers:
                blockers.append(blocker)
    return {
        "rank": item.get("rank"),
        "harness_name": item.get("harness_name"),
        "display_name": item.get("display_name"),
        "capability_id": item.get("capability_id"),
        "state": "blocked",
        "ready_for_install": False,
        "reason": reason,
        "blockers": blockers,
        "recommended_next_action": item.get("recommended_next_action"),
        "lifecycle": item.get("lifecycle"),
        "gates": item.get("gates"),
        "readiness": item.get("readiness"),
        "evaluation": evaluation,
        "commands": {
            "evaluate": f"python -m cbn plugin evaluate-harness cli-anything {item.get('harness_name')}",
            "probe": f"python -m cbn plugin probe-harness cli-anything {item.get('harness_name')}",
        },
    }


def install_queue_skipped_entry(
    item: dict[str, Any],
    reason: str,
    evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "rank": item.get("rank"),
        "harness_name": item.get("harness_name"),
        "display_name": item.get("display_name"),
        "capability_id": item.get("capability_id"),
        "state": "skipped",
        "ready_for_install": False,
        "reason": reason,
        "recommended_next_action": item.get("recommended_next_action"),
        "lifecycle": item.get("lifecycle"),
        "gates": item.get("gates"),
        "readiness": item.get("readiness"),
        "evaluation": evaluation,
    }


def blocked_entry_from_evaluation(harness_name: str, evaluation: dict[str, Any]) -> dict[str, Any]:
    capability_id = evaluation.get("capability_id")
    return {
        "rank": None,
        "harness_name": harness_name,
        "display_name": harness_name,
        "capability_id": capability_id,
        "state": "blocked" if not evaluation.get("install_candidate") else "review",
        "ready_for_install": bool(evaluation.get("install_candidate")),
        "reason": "harness evaluation blockers must be resolved first"
        if not evaluation.get("install_candidate")
        else "harness is not blocked by evaluation",
        "blockers": evaluation.get("blockers", []),
        "recommended_next_action": evaluation.get("recommended_next_action"),
        "lifecycle": evaluation.get("lifecycle"),
        "gates": evaluation.get("gates"),
        "readiness": None,
        "evaluation": evaluation,
    }


def blocked_harness_decision(item: dict[str, Any]) -> dict[str, Any]:
    harness_name = item.get("harness_name")
    capability_id = item.get("capability_id")
    blockers = [str(blocker) for blocker in item.get("blockers", [])]
    categories = blocker_categories(blockers)
    entrypoint_missing = "installed-entrypoint-missing" in categories
    manual_resolution_required = bool(
        {"manual-dependency", "installed-entrypoint-missing", "platform", "manifest"}
        & set(categories)
    )
    override_available = bool(categories) and not entrypoint_missing
    override_mode = (
        "repair_required"
        if entrypoint_missing
        else "explicit_risk_acceptance"
        if "external-network-or-risk" in categories
        else "manual_dependency_acknowledgement"
        if "manual-dependency" in categories
        else "explicit_override"
    )
    decision_ready = bool(categories)
    commands = {
        "evaluate": f"python -m cbn plugin evaluate-harness cli-anything {harness_name} --from-market",
        "probe": f"python -m cbn plugin probe-harness cli-anything {harness_name} --from-market",
        "onboard_preview": f"python -m cbn plugin onboard-harness cli-anything {harness_name} --from-market --smoke-suite --smoke-extra-arg=--help --no-workflows",
        "onboard_write": f"python -m cbn plugin onboard-harness cli-anything {harness_name} --from-market --write --yes",
        "onboard_install_override": (
            f"python -m cbn plugin onboard-harness cli-anything {harness_name} "
            "--from-market --write --install --yes --allow-blocked "
            "--smoke-suite --smoke-extra-arg=--help --no-workflows"
        ),
        "harness_install_override": f"python -m cbn plugin harness cli-anything install {harness_name} --yes --allow-blocked",
        "dry_run_call": f"python -m cbn call {capability_id} --dry-run" if capability_id else None,
    }
    return {
        "rank": item.get("rank"),
        "harness_name": harness_name,
        "display_name": item.get("display_name"),
        "capability_id": capability_id,
        "reason": item.get("reason"),
        "blockers": blockers,
        "categories": categories,
        "decision_ready": decision_ready,
        "manual_resolution_required": manual_resolution_required,
        "override": {
            "available": override_available,
            "mode": override_mode,
            "requires_confirmation": True,
            "recommended": False,
            "blocked_reason": "repair entrypoint before reinstalling" if entrypoint_missing else None,
        },
        "recommended_next_action": blocked_recommended_next_action(categories),
        "commands": commands,
        "evidence": {
            "gates": item.get("gates"),
            "readiness": item.get("readiness"),
            "evaluation": item.get("evaluation"),
            "lifecycle": item.get("lifecycle"),
        },
    }


def blocker_categories(blockers: list[str]) -> list[str]:
    categories = []
    text = "\n".join(blockers).casefold()
    mapping = (
        ("installed-entrypoint-missing", ("entrypoint is missing", "entrypoint missing", "not found on path")),
        ("external-network-or-risk", ("policy requires elevated confirmation", "external-network")),
        ("manual-dependency", ("declared requirements need external app", "dependency probe failed", "backend")),
        ("platform", ("platform",)),
        ("manifest", ("manifest", "duplicate capability_id")),
        ("tooling", ("cli-hub is not available", "market record")),
    )
    for category, markers in mapping:
        if any(marker in text for marker in markers):
            categories.append(category)
    if not categories and blockers:
        categories.append("unknown")
    return categories


def blocked_recommended_next_action(categories: list[str]) -> str:
    if "installed-entrypoint-missing" in categories:
        return "repair_entrypoint_or_market_metadata"
    if "external-network-or-risk" in categories:
        return "review_and_accept_external_network_risk"
    if "manual-dependency" in categories:
        return "install_or_configure_manual_dependency"
    if "platform" in categories:
        return "use_compatible_platform"
    if "manifest" in categories:
        return "fix_manifest_or_market_metadata"
    return "inspect_blockers"
