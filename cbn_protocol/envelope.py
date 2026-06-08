"""Bridge message envelope for CLI-to-CLI interchange."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


BRIDGE_MESSAGE_API_VERSION = "bridge.dev/v1alpha1"


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


@dataclass(frozen=True)
class BridgeMessage:
    producer: str
    channel: str
    correlation_id: str
    payload: dict[str, Any]
    artifacts: tuple[dict[str, Any], ...] = ()
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=now_iso)

    def as_dict(self) -> dict[str, Any]:
        return {
            "apiVersion": BRIDGE_MESSAGE_API_VERSION,
            "kind": "BridgeMessage",
            "metadata": {
                "id": self.message_id,
                "createdAt": self.created_at,
                "producer": self.producer,
                "channel": self.channel,
                "correlationId": self.correlation_id,
            },
            "payload": self.payload,
            "artifacts": list(self.artifacts),
        }
