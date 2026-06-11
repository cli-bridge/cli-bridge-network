"""Health route payloads."""

from __future__ import annotations

from typing import Any

from cbn.version import __version__


def health_payload(
    *,
    session_token_required: bool = False,
    session_token_supplied: bool = False,
    session_token_mode: str | None = None,
    session_token_source: str | None = None,
    local_session_token_default: bool | None = None,
) -> dict[str, Any]:
    auth: dict[str, Any] = {
        "session_token_required": session_token_required,
        "session_token_supplied": session_token_supplied,
        "accepted_headers": ["X-CBN-Session", "Authorization: Bearer"],
    }
    if session_token_mode is not None:
        auth["session_token_mode"] = session_token_mode
    if session_token_source is not None:
        auth["session_token_source"] = session_token_source
    if local_session_token_default is not None:
        auth["local_session_token_default"] = local_session_token_default
    return {
        "name": "CLI Bridge Network",
        "status": "ok",
        "version": __version__,
        "auth": auth,
    }
