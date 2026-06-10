"""Progress state for long-running calls."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ProgressState:
    current: int = 0
    total: int = 0
    message: str = ""

    def as_dict(self) -> dict[str, int | str]:
        return {"current": self.current, "total": self.total, "message": self.message}

