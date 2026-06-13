"""Market candidate and install queue helpers for CLI-Anything."""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class CandidateHarnessesReportInput:
    query: str | None
    limit: int
    with_probes: bool
    compact: bool
    result: "CommandResultLike"
    records: list[dict[str, Any]]
    candidates: list[dict[str, Any]]
    selected: list[dict[str, Any]]
    counts: dict[str, int]


@dataclass(frozen=True)
class MarketInstallQueueReportInput:
    query: str | None
    candidate_scan: dict[str, Any]
    bounded_max_installs: int
    include_blocked: bool
    candidates: list[dict[str, Any]]
    queue: list[dict[str, Any]]
    blocked: list[dict[str, Any]]
    skipped: list[dict[str, Any]]


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
    bounded_limit = bounded_candidate_limit(limit)
    result = hub.search_market(query) if query else hub.list_market()
    records, error = market_candidate_records(result)
    if error:
        return failed_candidate_harnesses_report(
            query=query,
            limit=bounded_limit,
            with_probes=with_probes,
            compact=compact,
            result=result,
            error=error,
        )

    candidates = prepared_candidate_harnesses(hub, records, with_probes=with_probes)
    selected = ranked_candidate_selection(candidates, bounded_limit)
    counts = candidate_selection_counts(selected)
    return successful_candidate_harnesses_report(CandidateHarnessesReportInput(
        query=query,
        limit=bounded_limit,
        with_probes=with_probes,
        compact=compact,
        result=result,
        records=records,
        candidates=candidates,
        selected=selected,
        counts=counts,
    ))


def market_candidate_records(result: CommandResultLike) -> tuple[list[dict[str, Any]], str | None]:
    records = market_records_from_result(result.parsed_json)
    if result.exit_code != 0:
        return [], "CLI-Anything market command failed"
    if records is None:
        return [], "CLI-Anything market command did not return a supported JSON list shape"
    return records, None


def bounded_candidate_limit(limit: int) -> int:
    return max(0, min(limit, 500))


def failed_candidate_harnesses_report(
    *,
    query: str | None,
    limit: int,
    with_probes: bool,
    compact: bool,
    result: CommandResultLike,
    error: str,
) -> dict[str, Any]:
    return {
        "ok": False,
        "plugin_id": PLUGIN_ID,
        "query": query,
        "limit": limit,
        "with_probes": with_probes,
        "compact": compact,
        "error": error,
        "market": market_command_payload(result, compact=compact),
        "selected_count": 0,
        "install_candidate_count": 0,
        "blocked_count": 0,
        "candidates": [],
        "candidate_summary": [],
    }


def prepared_candidate_harnesses(
    hub: Any,
    records: list[dict[str, Any]],
    *,
    with_probes: bool,
) -> list[dict[str, Any]]:
    candidates = [
        hub._candidate_from_market_record(record, market_index=index)
        for index, record in enumerate(records)
    ]
    mark_candidate_collisions(candidates)
    for item in candidates:
        prepare_candidate_harness(item, with_probes=with_probes)
    candidates.sort(key=candidate_sort_key)
    return candidates


def prepare_candidate_harness(item: dict[str, Any], *, with_probes: bool) -> None:
    refresh_candidate_lifecycle(item)
    if with_probes:
        attach_candidate_readiness(item)


def candidate_sort_key(item: dict[str, Any]) -> tuple[bool, int, Any, Any]:
    return (
        not bool(item.get("install_candidate")),
        len(item.get("blockers", [])),
        item.get("harness_name") or "",
        item.get("market_index", 0),
    )


def ranked_candidate_selection(
    candidates: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    selected = candidates[:limit]
    for rank, item in enumerate(selected, start=1):
        item["rank"] = rank
    return selected


def candidate_selection_counts(selected: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "install_candidate_count": sum(1 for item in selected if item.get("install_candidate")),
        "blocked_count": sum(1 for item in selected if not item.get("install_candidate")),
        "probe_ready_count": sum(
            1
            for item in selected
            if isinstance(item.get("readiness"), dict) and item["readiness"].get("ready")
        ),
        "probe_blocked_count": sum(
            1
            for item in selected
            if isinstance(item.get("readiness"), dict)
            and item["readiness"].get("probe_blocker_count", 0) > 0
        ),
    }


def successful_candidate_harnesses_report(report: CandidateHarnessesReportInput) -> dict[str, Any]:
    return {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "query": report.query,
        "limit": report.limit,
        "with_probes": report.with_probes,
        "compact": report.compact,
        "market_count": len(report.records),
        "evaluated_count": len(report.candidates),
        "selected_count": len(report.selected),
        "install_candidate_count": report.counts["install_candidate_count"],
        "blocked_count": report.counts["blocked_count"],
        "probe_ready_count": report.counts["probe_ready_count"] if report.with_probes else None,
        "probe_blocked_count": report.counts["probe_blocked_count"] if report.with_probes else None,
        "market": market_command_payload(report.result, compact=report.compact),
        "candidates": report.selected,
        "candidate_summary": candidate_summary(report.selected),
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
        return failed_market_install_queue_report(
            query=query,
            limit=limit,
            bounded_max_installs=bounded_max_installs,
            include_blocked=include_blocked,
            candidate_scan=candidate_scan,
        )
    candidates = install_queue_candidates(candidate_scan)
    queue, blocked, skipped = classify_install_queue_candidates(
        hub,
        candidates=candidates,
        bounded_max_installs=bounded_max_installs,
        include_blocked=include_blocked,
    )
    return successful_market_install_queue_report(MarketInstallQueueReportInput(
        query=query,
        candidate_scan=candidate_scan,
        bounded_max_installs=bounded_max_installs,
        include_blocked=include_blocked,
        candidates=candidates,
        queue=queue,
        blocked=blocked,
        skipped=skipped,
    ))


def failed_market_install_queue_report(
    *,
    query: str | None,
    limit: int,
    bounded_max_installs: int,
    include_blocked: bool,
    candidate_scan: dict[str, Any],
) -> dict[str, Any]:
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


def install_queue_candidates(candidate_scan: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = candidate_scan.get("candidates", [])
    if not isinstance(candidates, list):
        return []
    return [item for item in candidates if isinstance(item, dict)]


def classify_install_queue_candidates(
    hub: Any,
    *,
    candidates: list[dict[str, Any]],
    bounded_max_installs: int,
    include_blocked: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    queue: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in candidates:
        classification = classify_install_queue_candidate(
            hub,
            item=item,
            queued_count=len(queue),
            bounded_max_installs=bounded_max_installs,
            include_blocked=include_blocked,
        )
        bucket = classification.get("bucket")
        entry = classification.get("entry")
        if bucket == "queue" and isinstance(entry, dict):
            queue.append(entry)
        elif bucket == "blocked" and isinstance(entry, dict):
            blocked.append(entry)
        elif bucket == "skipped" and isinstance(entry, dict):
            skipped.append(entry)
    return queue, blocked, skipped


def classify_install_queue_candidate(
    hub: Any,
    *,
    item: dict[str, Any],
    queued_count: int,
    bounded_max_installs: int,
    include_blocked: bool,
) -> dict[str, Any]:
    harness_name = item.get("harness_name")
    if not isinstance(harness_name, str) or not harness_name:
        return {
            "bucket": "blocked",
            "entry": install_queue_blocked_entry(item, "market record is missing harness_name"),
        }
    gates = item.get("gates") if isinstance(item.get("gates"), dict) else {}
    install_candidate = bool(item.get("install_candidate"))
    launch_ready = bool(gates.get("launch_ready"))
    if install_candidate and launch_ready:
        return {
            "bucket": "skipped",
            "entry": install_queue_skipped_entry(item, "harness is already launch-ready"),
        }
    if install_candidate:
        return classify_install_ready_candidate(
            hub,
            item=item,
            harness_name=harness_name,
            queued_count=queued_count,
            bounded_max_installs=bounded_max_installs,
        )
    if include_blocked:
        return {
            "bucket": "blocked",
            "entry": install_queue_blocked_entry(item, "candidate blockers must be resolved first"),
        }
    return {"bucket": "ignored", "entry": None}


def classify_install_ready_candidate(
    hub: Any,
    *,
    item: dict[str, Any],
    harness_name: str,
    queued_count: int,
    bounded_max_installs: int,
) -> dict[str, Any]:
    evaluation = hub.evaluate_harness(harness_name, from_market=True)
    if not evaluation.get("ok"):
        return ready_candidate_blocked(item, "harness evaluation failed before queueing", evaluation)
    eval_gates = evaluation.get("gates") if isinstance(evaluation.get("gates"), dict) else {}
    if bool(eval_gates.get("launch_ready")):
        return ready_candidate_skipped(item, "harness is already launch-ready", evaluation)
    if not bool(evaluation.get("install_candidate")):
        return ready_candidate_blocked(item, "harness evaluation blockers must be resolved first", evaluation)
    if queued_count >= bounded_max_installs:
        return ready_candidate_skipped(item, "max_installs limit reached", evaluation)
    return ready_candidate_queued(hub, item, harness_name, evaluation)


def ready_candidate_blocked(
    item: dict[str, Any],
    reason: str,
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "bucket": "blocked",
        "entry": install_queue_blocked_entry(item, reason, evaluation=evaluation),
    }


def ready_candidate_skipped(
    item: dict[str, Any],
    reason: str,
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "bucket": "skipped",
        "entry": install_queue_skipped_entry(item, reason, evaluation=evaluation),
    }


def ready_candidate_queued(
    hub: Any,
    item: dict[str, Any],
    harness_name: str,
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "bucket": "queue",
        "entry": install_queue_entry(
            item,
            install_plan=hub.harness_plan("install", harness_name).as_dict(),
            evaluation=evaluation,
        ),
    }


def successful_market_install_queue_report(report: MarketInstallQueueReportInput) -> dict[str, Any]:
    return {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "kind": "CliAnythingMarketInstallQueue",
        "query": report.query,
        "limit": report.candidate_scan.get("limit"),
        "max_installs": report.bounded_max_installs,
        "include_blocked": report.include_blocked,
        "summary": {
            "candidate_count": len(report.candidates),
            "install_candidate_count": report.candidate_scan.get("install_candidate_count"),
            "probe_ready_count": report.candidate_scan.get("probe_ready_count"),
            "probe_blocked_count": report.candidate_scan.get("probe_blocked_count"),
            "queued_count": len(report.queue),
            "blocked_count": len(report.blocked),
            "skipped_count": len(report.skipped),
        },
        "queue": report.queue,
        "blocked": report.blocked,
        "skipped": report.skipped,
        "candidate_summary": report.candidate_scan.get("candidate_summary", []),
        "candidate_scan": report.candidate_scan,
        "next_commands": [
            "python -m cbn plugin install-queue cli-anything --query <query> --limit 20",
            "python -m cbn plugin onboard-harness cli-anything <harness> --from-market --write --install --yes --smoke-suite --smoke-extra-arg=--help --no-workflows",
            "python -m cbn plugin harness cli-anything install <harness> --yes",
        ],
    }


def blocked_harness_plan(
    hub: Any,
    harnesses: tuple[str, ...] = (),
    query: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    bounded_limit = max(0, min(limit, 500))
    source = "explicit_harnesses" if harnesses else "market_install_queue"
    source_report, blocked_entries = blocked_harness_source_entries(
        hub,
        harnesses=harnesses,
        query=query,
        limit=bounded_limit,
    )
    if source_report is not None and not source_report.get("ok"):
        return failed_blocked_harness_plan_report(
            source=source,
            query=query,
            limit=bounded_limit,
            source_report=source_report,
        )
    decisions = [blocked_harness_decision(item) for item in blocked_entries]
    return successful_blocked_harness_plan_report(
        source=source,
        query=query,
        limit=bounded_limit,
        harnesses=harnesses,
        decisions=decisions,
        source_report=source_report,
    )


def blocked_harness_source_entries(
    hub: Any,
    *,
    harnesses: tuple[str, ...],
    query: str | None,
    limit: int,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if harnesses:
        return None, [
            blocked_entry_from_evaluation(
                harness_name,
                hub.evaluate_harness(harness_name, from_market=True),
            )
            for harness_name in harnesses
        ]
    source_report = hub.market_install_queue(
        query=query,
        limit=limit,
        max_installs=100,
        include_blocked=True,
    )
    if not source_report.get("ok"):
        return source_report, []
    return source_report, blocked_entries_from_install_queue(source_report)


def blocked_entries_from_install_queue(source_report: dict[str, Any]) -> list[dict[str, Any]]:
    blocked_raw = source_report.get("blocked", [])
    if not isinstance(blocked_raw, list):
        return []
    return [item for item in blocked_raw if isinstance(item, dict)]


def failed_blocked_harness_plan_report(
    *,
    source: str,
    query: str | None,
    limit: int,
    source_report: dict[str, Any],
) -> dict[str, Any]:
    return {
        "ok": False,
        "plugin_id": PLUGIN_ID,
        "kind": "CliAnythingBlockedHarnessPlan",
        "source": source,
        "query": query,
        "limit": limit,
        "error": source_report.get("error", "CLI-Anything install queue failed"),
        "summary": empty_blocked_harness_summary(),
        "blocked": [],
        "source_report": source_report,
    }


def empty_blocked_harness_summary() -> dict[str, int]:
    return {
        "blocked_count": 0,
        "override_candidate_count": 0,
        "manual_resolution_count": 0,
        "unresolved_count": 0,
    }


def successful_blocked_harness_plan_report(
    *,
    source: str,
    query: str | None,
    limit: int,
    harnesses: tuple[str, ...],
    decisions: list[dict[str, Any]],
    source_report: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "kind": "CliAnythingBlockedHarnessPlan",
        "source": source,
        "query": query,
        "limit": limit,
        "harnesses": list(harnesses),
        "summary": blocked_harness_summary(decisions),
        "blocked": decisions,
        "source_report": source_report,
        "next_commands": [
            "python -m cbn plugin blocked-plan cli-anything --harness <harness>",
            "python -m cbn plugin evaluate-harness cli-anything <harness> --from-market",
            "python -m cbn plugin probe-harness cli-anything <harness> --from-market",
            "python -m cbn plugin onboard-harness cli-anything <harness> --from-market --write --install --yes --allow-blocked --smoke-suite --smoke-extra-arg=--help --no-workflows",
        ],
    }


def blocked_harness_summary(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "blocked_count": len(decisions),
        "override_candidate_count": sum(
            1 for item in decisions if item.get("override", {}).get("available")
        ),
        "manual_resolution_count": sum(
            1 for item in decisions if item.get("manual_resolution_required")
        ),
        "unresolved_count": sum(1 for item in decisions if not item.get("decision_ready")),
        "category_counts": blocked_harness_category_counts(decisions),
    }


def blocked_harness_category_counts(decisions: list[dict[str, Any]]) -> dict[str, int]:
    category_counts: dict[str, int] = {}
    for decision in decisions:
        for category in decision.get("categories", []):
            category_counts[category] = category_counts.get(category, 0) + 1
    return category_counts


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
    return {
        "rank": item.get("rank"),
        "harness_name": harness_name,
        "display_name": item.get("display_name"),
        "capability_id": capability_id,
        "reason": item.get("reason"),
        "blockers": blockers,
        "categories": categories,
        "decision_ready": bool(categories),
        "manual_resolution_required": blocked_manual_resolution_required(categories),
        "override": blocked_harness_override(categories, entrypoint_missing),
        "recommended_next_action": blocked_recommended_next_action(categories),
        "commands": blocked_harness_commands(harness_name, capability_id),
        "evidence": blocked_harness_evidence(item),
    }


def blocked_manual_resolution_required(categories: list[str]) -> bool:
    manual_categories = {"manual-dependency", "installed-entrypoint-missing", "platform", "manifest"}
    return bool(manual_categories & set(categories))


def blocked_harness_override(
    categories: list[str],
    entrypoint_missing: bool,
) -> dict[str, Any]:
    return {
        "available": bool(categories) and not entrypoint_missing,
        "mode": blocked_harness_override_mode(categories, entrypoint_missing),
        "requires_confirmation": True,
        "recommended": False,
        "blocked_reason": "repair entrypoint before reinstalling" if entrypoint_missing else None,
    }


def blocked_harness_override_mode(categories: list[str], entrypoint_missing: bool) -> str:
    if entrypoint_missing:
        return "repair_required"
    if "external-network-or-risk" in categories:
        return "explicit_risk_acceptance"
    if "manual-dependency" in categories:
        return "manual_dependency_acknowledgement"
    return "explicit_override"


def blocked_harness_commands(harness_name: Any, capability_id: Any) -> dict[str, str | None]:
    return {
        "evaluate": f"python -m cbn plugin evaluate-harness cli-anything {harness_name} --from-market",
        "probe": f"python -m cbn plugin probe-harness cli-anything {harness_name} --from-market",
        "onboard_preview": (
            f"python -m cbn plugin onboard-harness cli-anything {harness_name} "
            "--from-market --smoke-suite --smoke-extra-arg=--help --no-workflows"
        ),
        "onboard_write": (
            f"python -m cbn plugin onboard-harness cli-anything {harness_name} --from-market --write --yes"
        ),
        "onboard_install_override": (
            f"python -m cbn plugin onboard-harness cli-anything {harness_name} "
            "--from-market --write --install --yes --allow-blocked "
            "--smoke-suite --smoke-extra-arg=--help --no-workflows"
        ),
        "harness_install_override": (
            f"python -m cbn plugin harness cli-anything install {harness_name} --yes --allow-blocked"
        ),
        "dry_run_call": f"python -m cbn call {capability_id} --dry-run" if capability_id else None,
    }


def blocked_harness_evidence(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "gates": item.get("gates"),
        "readiness": item.get("readiness"),
        "evaluation": item.get("evaluation"),
        "lifecycle": item.get("lifecycle"),
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
