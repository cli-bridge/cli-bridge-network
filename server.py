"""Server composition boundary for CBN.

The initial skeleton does not start a network listener. This module exists so
future gateway work has a stable import target, mirroring ComfyUI's split
between process startup and server route composition.
"""

from __future__ import annotations

from api_server.routes.health import health_payload
from app.registry import CapabilityRegistry


def create_server_state(registry: CapabilityRegistry | None = None) -> dict[str, object]:
    """Build the minimal state object shared by future gateway routes."""
    active_registry = registry or CapabilityRegistry()
    return {
        "health": health_payload(),
        "registry": active_registry,
    }

