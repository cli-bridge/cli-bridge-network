"""Health route payloads."""

from __future__ import annotations

from typing import Any

from cbn.version import __version__


def health_payload(*, session_token_required: bool = False, session_token_supplied: bool = False) -> dict[str, Any]:
    return {
        "name": "CLI Bridge Network",
        "status": "ok",
        "version": __version__,
        "auth": {
            "session_token_required": session_token_required,
            "session_token_supplied": session_token_supplied,
            "accepted_headers": ["X-CBN-Session", "Authorization: Bearer"],
        },
    }
