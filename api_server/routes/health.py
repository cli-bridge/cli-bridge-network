"""Health route payloads."""

from __future__ import annotations

from cbn.version import __version__


def health_payload() -> dict[str, str]:
    return {
        "name": "CLI Bridge Network",
        "status": "ok",
        "version": __version__,
    }

