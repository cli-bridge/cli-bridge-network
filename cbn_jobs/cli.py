"""CLI dispatcher for ERC-8183 Job Commerce offchain lifecycle.

Invoked as ``python -m cbn_jobs <action> [...]``. Every action prints one JSON
object to stdout (parsed by the ``direct-cli.typed`` parser). This is the
offchain state spine; onchain ERC-8183 settlement is layered on top via the
``caw.erc8183.*`` CAW capabilities (see runtime/erc8183-job-commerce-plan.md).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from cbn_jobs.store import ACTIONS, JobStore, TERMINAL


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.write("\n")


def _load_json(name: str, raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(_err(f"--{name} is not valid JSON: {exc}"))
    if not isinstance(value, dict):
        raise SystemExit(_err(f"--{name} must be a JSON object"))
    return value


def _err(msg: str) -> str:
    return json.dumps({"ok": False, "error": msg}, ensure_ascii=False)


def _row(rec: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "job_id": rec["job_id"], "state": rec["state"],
            "spec_hash": rec.get("spec_hash"), "parent_job_id": rec.get("parent_job_id"),
            "evidence_count": len(rec.get("evidence") or []),
            "has_deliverable": bool(rec.get("deliverable")),
            "chain": rec.get("chain"), "contract": rec.get("contract")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cbn_jobs", description="ERC-8183 Job Commerce offchain CLI")
    sub = parser.add_subparsers(dest="action", required=True)
    store = JobStore()

    p_draft = sub.add_parser("draft", help="create a job in drafting")
    p_draft.add_argument("--spec", help="job_spec JSON object")
    p_draft.add_argument("--brief")
    p_draft.add_argument("--client", default="")
    p_draft.add_argument("--provider", default="")
    p_draft.add_argument("--evaluator", default="")
    p_draft.add_argument("--chain", default="")
    p_draft.add_argument("--contract", default="")

    p_pub = sub.add_parser("publish", help="drafting -> job_created")
    p_pub.add_argument("job_id")

    p_fund = sub.add_parser("fund", help="job_created -> escrow_funded")
    p_fund.add_argument("job_id")

    p_work = sub.add_parser("start-work", help="escrow_funded -> work_running")
    p_work.add_argument("job_id")

    p_sub = sub.add_parser("submit", help="record deliverable + -> deliverable_submitted")
    p_sub.add_argument("job_id")
    p_sub.add_argument("--deliverable", required=True, help="deliverable_package JSON object")

    p_eval_req = sub.add_parser("request-evaluation", help="-> evaluation_pending")
    p_eval_req.add_argument("job_id")

    p_eval = sub.add_parser("evaluate", help="policy-driven evaluator")
    p_eval.add_argument("job_id")
    p_eval.add_argument("--permission", choices=["full", "auto", "default"], default="auto")

    p_complete = sub.add_parser("complete", help="evaluation_pending -> completed")
    p_complete.add_argument("job_id")
    p_complete.add_argument("--reason", default="evaluator accepted")

    p_reject = sub.add_parser("reject", help="evaluation_pending -> rejected (terminal)")
    p_reject.add_argument("job_id")
    p_reject.add_argument("--reason", required=True)

    p_revision = sub.add_parser("revision", help="create a linked revision job")
    p_revision.add_argument("job_id")
    p_revision.add_argument("--spec", required=True)

    p_expire = sub.add_parser("expire", help="-> expired (claimable refund)")
    p_expire.add_argument("job_id")

    p_get = sub.add_parser("get", help="show one job")
    p_get.add_argument("job_id")
    sub.add_parser("list", help="list jobs")
    sub.add_parser("states", help="print state machine")

    args = parser.parse_args(argv)

    try:
        if args.action == "draft":
            spec = _load_json("spec", args.spec) if args.spec else {}
            if args.brief:
                spec.setdefault("brief", args.brief)
            rec = store.draft(spec, client=args.client, provider=args.provider,
                              evaluator=args.evaluator, chain=args.chain, contract=args.contract)
            _emit(_row(rec) | {"note": "onchain createJob pending — run caw.erc8183.create-job"})
        elif args.action == "publish":
            _emit(_row(store.transition(args.job_id, "publish")))
        elif args.action == "fund":
            rec = store.transition(args.job_id, "fund")
            _emit(_row(rec) | {"note": "onchain fund pending — run caw.erc8183.fund"})
        elif args.action == "start-work":
            _emit(_row(store.transition(args.job_id, "start_work")))
        elif args.action == "submit":
            deliverable = _load_json("deliverable", args.deliverable)
            store.set_deliverable(args.job_id, deliverable)
            rec = store.transition(args.job_id, "submit")
            from cbn_jobs.notify import post_job_event
            notify = post_job_event(rec, event="submit",
                                    extra={"summary": str((deliverable.get("summary") or "")[:60])})
            _emit(_row(rec) | {"feishu": notify})
        elif args.action == "request-evaluation":
            _emit(_row(store.transition(args.job_id, "request_evaluation")))
        elif args.action == "evaluate":
            _emit(_evaluate(store, args.job_id, args.permission))
        elif args.action == "complete":
            store.set_evaluation(args.job_id, "accept", args.reason, "human-confirm")
            rec = store.transition(args.job_id, "complete")
            # REAL onchain settlement (hybrid): transfer testnet SETH to the provider
            # via the CAW settlement pact. Fixed demo amount (0.001 SETH) since the
            # faucet provides SETH, not USDC. Daemon-side subprocess — not subject to
            # the interactive bash classifier, so the agent can fire it during a run.
            settle_result = None
            provider = str((rec.get("roles") or {}).get("provider") or "")
            if provider.startswith("0x") and len(provider) == 42:
                try:
                    from cbn_jobs.onchain import settle
                    settle_result = settle(provider, "0.001")
                except Exception as exc:
                    settle_result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            else:
                settle_result = {"ok": False, "skipped": "job has no 0x provider address; set roles.provider to settle onchain"}
            from cbn_jobs.notify import post_job_event
            settle_tx = (settle_result.get("stdout") or "")[:60] if settle_result.get("ok") else "n/a"
            notify = post_job_event(rec, event="complete",
                                    extra={"settle": "0.001 SETH → provider", "tx": settle_tx})
            _emit(_row(rec) | {"settle": settle_result, "feishu": notify,
                               "note": "onchain SETH settlement attempted at complete (hybrid path)"})
        elif args.action == "reject":
            store.set_evaluation(args.job_id, "reject", args.reason, "human-confirm")
            _emit(_row(store.transition(args.job_id, "reject"))
                  | {"note": "onchain refund pending — run caw.erc8183.reject; rejected is terminal — use 'revision' to rework"})
        elif args.action == "revision":
            spec = _load_json("spec", args.spec)
            _emit(_row(store.revision(args.job_id, spec)))
        elif args.action == "expire":
            rec = store.get(args.job_id)
            action = "expire_funded" if rec and rec["state"] == "escrow_funded" else "expire_submitted"
            _emit(_row(store.transition(args.job_id, action))
                  | {"note": "onchain claimRefund pending — run caw.erc8183.claim-refund"})
        elif args.action == "get":
            rec = store.get(args.job_id)
            _emit(rec if rec else {"ok": False, "error": f"unknown job: {args.job_id}"})
        elif args.action == "list":
            _emit({"ok": True, "jobs": store.list()})
        elif args.action == "states":
            _emit({"ok": True, "states": list(ACTIONS), "terminal": sorted(TERMINAL)})
    except (KeyError, ValueError) as exc:
        _emit({"ok": False, "error": str(exc)})
        return 1
    return 0


def _evaluate(store: JobStore, job_id: str, permission: str) -> dict[str, Any]:
    rec = store.get(job_id)
    if rec is None:
        return {"ok": False, "error": f"unknown job: {job_id}"}
    if rec["state"] not in {"deliverable_submitted", "evaluation_pending"}:
        return {"ok": False, "error": f"evaluate needs deliverable_submitted/evaluation_pending, job is {rec['state']}"}
    deliverable = rec.get("deliverable") or {}
    checks = {
        "has_evidence_hash": bool(deliverable.get("evidence_hash")),
        "has_media": bool(deliverable.get("media")),
        "has_summary": bool(deliverable.get("summary")),
    }
    passed = all(checks.values())
    missing = [k for k, v in checks.items() if not v]
    reason = "deliverable has evidence_hash + media + summary" if passed else f"missing evidence: {missing}"

    if permission == "full":
        # testnet funds + full trust -> auto-settle on evidence
        if rec["state"] == "deliverable_submitted":
            store.transition(job_id, "request_evaluation")
        if passed:
            store.set_evaluation(job_id, "accept", reason, "auto(full)")
            store.transition(job_id, "complete")
            return {"ok": True, "job_id": job_id, "verdict": "accepted", "auto": True,
                    "permission": "full", "checks": checks, "reason": reason,
                    "next": "caw.erc8183.complete releases escrow"}
        store.set_evaluation(job_id, "reject", reason, "auto(full)")
        store.transition(job_id, "reject")
        return {"ok": True, "job_id": job_id, "verdict": "rejected", "auto": True,
                "permission": "full", "checks": checks, "reason": reason,
                "next": "caw.erc8183.reject refunds; revision to rework"}

    # auto / default -> agent suggests, human confirms (testnet but gated)
    if rec["state"] == "deliverable_submitted":
        store.transition(job_id, "request_evaluation")
    suggestion = "accept" if passed else "reject"
    store.set_evaluation(job_id, f"suggest:{suggestion}", reason, f"semi({permission})")
    return {"ok": True, "job_id": job_id, "verdict": f"suggest:{suggestion}", "auto": False,
            "permission": permission, "checks": checks, "reason": reason,
            "needs_human_confirm": True,
            "next": f"human confirms via feishu card -> cbn.jobs.{ 'complete' if passed else 'reject' }"}
