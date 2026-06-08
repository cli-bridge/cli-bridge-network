"""Local artifact store for capability outputs."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    created_at: str
    capability_id: str
    call_id: str
    kind: str
    media_type: str
    path: str
    size_bytes: int
    truncated: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "created_at": self.created_at,
            "capability_id": self.capability_id,
            "call_id": self.call_id,
            "kind": self.kind,
            "media_type": self.media_type,
            "path": self.path,
            "size_bytes": self.size_bytes,
            "truncated": self.truncated,
        }


class ArtifactStore:
    def __init__(self, root: Path, max_inline_chars: int = 65536) -> None:
        self.root = root
        self.max_inline_chars = max_inline_chars
        self.index_path = self.root / "index.jsonl"
        self.root.mkdir(parents=True, exist_ok=True)

    def create_text(
        self,
        capability_id: str,
        call_id: str,
        kind: str,
        text: str,
        media_type: str = "text/plain; charset=utf-8",
    ) -> ArtifactRecord | None:
        if text == "":
            return None
        artifact_id = str(uuid.uuid4())
        truncated = len(text) > self.max_inline_chars
        stored_text = text[: self.max_inline_chars] if truncated else text
        path = self.root / f"{artifact_id}.{kind}.txt"
        path.write_text(stored_text, encoding="utf-8")
        record = ArtifactRecord(
            artifact_id=artifact_id,
            created_at=now_iso(),
            capability_id=capability_id,
            call_id=call_id,
            kind=kind,
            media_type=media_type,
            path=str(path),
            size_bytes=len(stored_text.encode("utf-8")),
            truncated=truncated,
        )
        with self.index_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record.as_dict(), ensure_ascii=False) + "\n")
        return record

    def create_json(
        self,
        capability_id: str,
        call_id: str,
        kind: str,
        payload: dict[str, Any],
    ) -> ArtifactRecord:
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        record = self.create_text(
            capability_id=capability_id,
            call_id=call_id,
            kind=kind,
            text=text,
            media_type="application/json; charset=utf-8",
        )
        if record is None:
            raise ValueError("json artifact payload cannot be empty")
        return record

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.index_path.exists():
            return []
        lines = self.index_path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines[-limit:] if line.strip()]

    def inspect(self, artifact_id: str) -> dict[str, Any]:
        for record in reversed(self.list(limit=1000)):
            if record["artifact_id"] == artifact_id:
                path = Path(record["path"])
                payload = dict(record)
                payload["content"] = path.read_text(encoding="utf-8") if path.exists() else None
                return payload
        raise KeyError(f"unknown artifact: {artifact_id}")
