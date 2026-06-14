"""ERC-8183 Job Commerce — offchain Job store + state machine.

Each Job is one JSON file under ``runtime/jobs/``. The store is the SOURCE OF
TRUTH for the detailed offchain lifecycle (richer than the onchain ERC-8183
terminal states). Onchain settlement (createJob/fund/complete/reject) is a
separate CAW layer that records tx hashes back here.

Design (per runtime/erc8183-job-commerce-plan.md):
- Three temporary roles per job: client / provider / evaluator (NOT fixed identities).
- Rejected is terminal — to rework, create a *revision* job with parent_job_id.
- Every CLI that produces evidence appends to ``evidence[]`` so the evaluator
  settles on proof, not trust.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


# --------------------------------------------------------------------------- #
# State machine
# --------------------------------------------------------------------------- #
STATES = (
    "drafting",            # spec being assembled (obsidian context pulled)
    "job_created",         # published (ERC-8183 createJob intent)
    "escrow_funded",       # budget escrowed (ERC-8183 fund intent)
    "work_running",        # provider pipeline executing (jimeng/feishu/...)
    "deliverable_submitted",  # deliverable_package.json + hash recorded
    "evaluation_pending",  # awaiting evaluator verdict
    "completed",           # accepted — payment released (terminal)
    "rejected",            # rejected — refund (terminal)
    "expired",             # timeout — claimable refund (terminal)
)
TERMINAL = {"completed", "rejected", "expired"}

# action -> (from_state, to_state)
ACTIONS: dict[str, tuple[str, str]] = {
    "publish": ("drafting", "job_created"),
    "fund": ("job_created", "escrow_funded"),
    "start_work": ("escrow_funded", "work_running"),
    "submit": ("escrow_funded", "deliverable_submitted"),     # also from work_running
    "request_evaluation": ("deliverable_submitted", "evaluation_pending"),
    "complete": ("evaluation_pending", "completed"),
    "reject": ("evaluation_pending", "rejected"),
    "expire_funded": ("escrow_funded", "expired"),
    "expire_submitted": ("deliverable_submitted", "expired"),
}


def _allowed_next(state: str) -> set[str]:
    return {to_ for (from_, to_) in ACTIONS.values() if from_ == state}


class JobStore:
    def __init__(self, jobs_dir: Path | None = None) -> None:
        self.dir = Path(jobs_dir or (ROOT / "runtime" / "jobs"))
        self.dir.mkdir(parents=True, exist_ok=True)

    # -- path helpers --------------------------------------------------------
    def _path(self, job_id: str) -> Path:
        return self.dir / f"{job_id}.json"

    # -- create --------------------------------------------------------------
    def draft(
        self,
        spec: dict[str, Any],
        *,
        client: str = "",
        provider: str = "",
        evaluator: str = "",
        chain: str = "",
        contract: str = "",
        parent_job_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a job in `drafting`. ``spec`` is the job_spec (brief, criteria, budget...)."""
        job_id = f"job-{uuid.uuid4().hex[:10]}"
        ts = now_iso()
        spec_hash = _hash_json(spec)
        record: dict[str, Any] = {
            "job_id": job_id,
            "parent_job_id": parent_job_id,
            "state": "drafting",
            "roles": {"client": client, "provider": provider, "evaluator": evaluator},
            "chain": chain,
            "contract": contract,
            "spec": spec,
            "spec_hash": spec_hash,
            "escrow": {"funded": False, "tx_hash": None, "token": spec.get("budget_token", ""),
                       "amount": str(spec.get("budget_amount", ""))},
            "deliverable": None,
            "evaluation": None,
            "onchain": {"create_tx": None, "fund_tx": None, "complete_tx": None,
                        "reject_tx": None, "refund_tx": None},
            "evidence": [],
            "created_at": ts,
            "updated_at": ts,
        }
        self._write(record)
        return record

    # -- read ----------------------------------------------------------------
    def get(self, job_id: str) -> dict[str, Any] | None:
        path = self._path(job_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        files = sorted(self.dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        rows: list[dict[str, Any]] = []
        for path in files[:limit]:
            try:
                rec = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            rows.append(self._row(rec))
        return rows

    @staticmethod
    def _row(rec: dict[str, Any]) -> dict[str, Any]:
        return {
            "job_id": rec.get("job_id"),
            "state": rec.get("state"),
            "parent_job_id": rec.get("parent_job_id"),
            "brief": (rec.get("spec") or {}).get("brief", "")[:80],
            "chain": rec.get("chain"),
            "contract": rec.get("contract"),
            "updated_at": rec.get("updated_at"),
        }

    # -- state transitions ---------------------------------------------------
    def transition(
        self,
        job_id: str,
        action: str,
        *,
        fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        rec = self.get(job_id)
        if rec is None:
            raise KeyError(f"unknown job: {job_id}")
        if action not in ACTIONS:
            raise ValueError(f"unknown action: {action}")
        from_state, to_state = ACTIONS[action]
        # submit is allowed from work_running too
        if action == "submit" and rec["state"] == "work_running":
            pass
        elif rec["state"] != from_state:
            if rec["state"] in TERMINAL:
                raise ValueError(f"job {job_id} is terminal ({rec['state']}); create a revision instead")
            raise ValueError(f"action '{action}' requires state {from_state}, job is {rec['state']}")
        rec["state"] = to_state
        if fields:
            _deep_merge(rec, fields)
        rec["updated_at"] = now_iso()
        self._write(rec)
        return rec

    # -- evidence + deliverable ---------------------------------------------
    def add_evidence(self, job_id: str, source: str, *, hash_value: str = "",
                     url: str = "", note: str = "") -> dict[str, Any]:
        rec = self._require(job_id)
        rec["evidence"].append(
            {"source": source, "hash": hash_value, "url": url, "note": note, "ts": now_iso()}
        )
        rec["updated_at"] = now_iso()
        self._write(rec)
        return rec

    def set_deliverable(self, job_id: str, deliverable: dict[str, Any]) -> dict[str, Any]:
        rec = self._require(job_id)
        evidence_hash = deliverable.get("evidence_hash") or _hash_json(deliverable)
        deliverable.setdefault("evidence_hash", evidence_hash)
        rec["deliverable"] = deliverable
        rec["updated_at"] = now_iso()
        self._write(rec)
        return rec

    def set_evaluation(self, job_id: str, verdict: str, reason: str,
                       evaluator_mode: str) -> dict[str, Any]:
        rec = self._require(job_id)
        rec["evaluation"] = {"verdict": verdict, "reason": reason,
                             "evaluator_mode": evaluator_mode, "ts": now_iso()}
        rec["updated_at"] = now_iso()
        self._write(rec)
        return rec

    # -- revision (Rejected is terminal -> new linked job) -------------------
    def revision(self, job_id: str, spec: dict[str, Any]) -> dict[str, Any]:
        parent = self.get(job_id)
        if parent is None:
            raise KeyError(f"unknown parent job: {job_id}")
        return self.draft(
            spec,
            client=(parent.get("roles") or {}).get("client", ""),
            provider=(parent.get("roles") or {}).get("provider", ""),
            evaluator=(parent.get("roles") or {}).get("evaluator", ""),
            chain=parent.get("chain", ""),
            contract=parent.get("contract", ""),
            parent_job_id=job_id,
        )

    # -- internals -----------------------------------------------------------
    def _require(self, job_id: str) -> dict[str, Any]:
        rec = self.get(job_id)
        if rec is None:
            raise KeyError(f"unknown job: {job_id}")
        return rec

    def _write(self, record: dict[str, Any]) -> None:
        self._path(record["job_id"]).write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _hash_json(obj: Any) -> str:
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return "0x" + hashlib.sha256(payload).hexdigest()


def _deep_merge(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value
