"""Capability registry service."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CapabilityRecord:
    capability_id: str
    title: str
    transport: str
    risk: str


class CapabilityRegistry:
    def __init__(self) -> None:
        self._records: dict[str, CapabilityRecord] = {}

    def register(self, record: CapabilityRecord) -> None:
        if record.capability_id in self._records:
            raise ValueError(f"duplicate capability: {record.capability_id}")
        self._records[record.capability_id] = record

    def list(self) -> list[CapabilityRecord]:
        return [self._records[key] for key in sorted(self._records)]

    def get(self, capability_id: str) -> CapabilityRecord | None:
        return self._records.get(capability_id)

