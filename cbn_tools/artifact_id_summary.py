"""Summarize a CBN artifact by id for workflow routing tests."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from cbn_artifacts.store import ArtifactStore


def summarize_artifact(artifact_id: str, root: Path = Path("runtime/artifacts")) -> dict[str, object]:
    artifact = ArtifactStore(root).inspect(artifact_id)
    content = artifact.get("content")
    if isinstance(content, str):
        content_preview = content[:120]
    else:
        content_preview = None
    return {
        "artifact_id": artifact["artifact_id"],
        "capability_id": artifact["capability_id"],
        "call_id": artifact["call_id"],
        "kind": artifact["kind"],
        "media_type": artifact["media_type"],
        "size_bytes": artifact["size_bytes"],
        "content_preview": content_preview,
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python -m cbn_tools.artifact_id_summary <artifact-id>", file=sys.stderr)
        return 2
    root = Path(os.environ.get("CBN_ARTIFACT_ROOT", "runtime/artifacts"))
    try:
        payload = summarize_artifact(args[0], root=root)
    except KeyError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
