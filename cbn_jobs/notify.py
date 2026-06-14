"""Feishu evidence channel for ERC-8183 jobs.

Posts lifecycle cards (deliverable submitted, job completed + settled) to a Feishu
user/chat via lark-cli, so every job step leaves an external evidence trail.
Mirrors cbn_jobs/onchain.py (direct external-CLI subprocess; daemon-side, so not
subject to the interactive bash classifier when fired during an agent run).

receive_id defaults to the tenant user discovered via the contact API; override
with the CBN_FEISHU_RECEIVE_ID env var (or a chat_id with receive_id_type=chat_id).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Tenant user open_id (the demo recipient). Override via env if you want a group chat.
RECEIVE_ID = os.environ.get("CBN_FEISHU_RECEIVE_ID", "ou_d2d7c091c9b1da5b48f8721ff0bb2dc8")


def _lark() -> str:
    from cbn_tools.external_cli import _lark_cli
    return _lark_cli(ROOT)


def post_card(title: str, md_lines: list[str], template: str = "green") -> dict:
    """Post a Feishu message. Uses text msg_type (most reliable); `template` is
    accepted for API symmetry but ignored for text. Upgrade to interactive card later."""
    body = title + "\n" + "\n".join(md_lines)
    content = {"text": body}
    data = {"receive_id": RECEIVE_ID, "msg_type": "text", "content": json.dumps(content, ensure_ascii=False)}
    try:
        r = subprocess.run(
            [_lark(), "api", "POST", "/open-apis/im/v1/messages",
             "--params", json.dumps({"receive_id_type": "open_id"}),
             "--data", json.dumps(data, ensure_ascii=True)],
            capture_output=True, timeout=50,
        )
        out = (r.stdout or b"").decode("utf-8", "replace")
        err = (r.stderr or b"").decode("utf-8", "replace")
        msg_id = ""
        try:
            d = json.loads(out or err)
            msg_id = (d.get("data") or {}).get("message_id", "")
        except Exception:
            pass
        return {"ok": bool(msg_id), "message_id": msg_id, "receive_id": RECEIVE_ID,
                "exit_code": r.returncode, "stdout": out[:400], "stderr": err[:400]}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def post_job_event(rec: dict, *, event: str, extra: dict | None = None) -> dict:
    """Convenience: build + post a card for a job lifecycle event."""
    jid = rec.get("job_id", "?")
    state = rec.get("state", "?")
    title_map = {
        "deliverable_submitted": ("[ERC-8183] 交付物已提交 · " + jid, "blue"),
        "completed": ("[ERC-8183] Job 完成并已结算 · " + jid, "green"),
        "rejected": ("[ERC-8183] Job 已驳回 · " + jid, "red"),
    }
    title, tpl = title_map.get(state, (f"[ERC-8183] Job {event} · {jid}", "turquoise"))
    lines = [f"**State:** {state}", f"**Spec hash:** `{rec.get('spec_hash', '')[:18]}…`"]
    if extra:
        for k, v in extra.items():
            lines.append(f"**{k}:** {v}")
    return post_card(title, lines, tpl)
