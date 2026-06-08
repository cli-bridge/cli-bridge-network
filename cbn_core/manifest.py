"""Versioned Manifest IR for CBN capabilities."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MANIFEST_API_VERSION = "bridge.dev/v1alpha1"


@dataclass(frozen=True)
class TransportSpec:
    kind: str
    command: str
    args_template: tuple[str, ...]
    cwd_policy: str = "workspace"

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TransportSpec":
        return cls(
            kind=raw["kind"],
            command=raw["command"],
            args_template=tuple(raw.get("argsTemplate", [])),
            cwd_policy=raw.get("cwdPolicy", "workspace"),
        )

    def argv(self, extra_args: tuple[str, ...] = ()) -> tuple[str, ...]:
        return (self.command, *self.args_template, *extra_args)


@dataclass(frozen=True)
class PolicySpec:
    risk: str
    requires_confirmation: bool
    network: str = "deny"

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PolicySpec":
        return cls(
            risk=raw["risk"],
            requires_confirmation=bool(raw.get("requiresConfirmation", False)),
            network=raw.get("network", "deny"),
        )


@dataclass(frozen=True)
class OutputSpec:
    parser_ref: str | None = None
    verified: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "OutputSpec":
        return cls(parser_ref=raw.get("parserRef"), verified=bool(raw.get("verified", False)))


@dataclass(frozen=True)
class CapabilityManifest:
    capability_id: str
    title: str
    transport: TransportSpec
    policy: PolicySpec
    output: OutputSpec
    labels: dict[str, str]
    annotations: dict[str, str]
    source_path: Path | None = None

    @classmethod
    def from_dict(
        cls,
        raw: dict[str, Any],
        source_path: Path | None = None,
    ) -> "CapabilityManifest":
        if raw.get("apiVersion") != MANIFEST_API_VERSION:
            raise ValueError(f"unsupported manifest apiVersion: {raw.get('apiVersion')}")
        if raw.get("kind") != "ToolManifest":
            raise ValueError(f"unsupported manifest kind: {raw.get('kind')}")
        metadata = raw["metadata"]
        spec = raw["spec"]
        return cls(
            capability_id=metadata["id"],
            title=metadata.get("title", metadata["id"]),
            transport=TransportSpec.from_dict(spec["transport"]),
            policy=PolicySpec.from_dict(spec["policy"]),
            output=OutputSpec.from_dict(spec.get("output", {})),
            labels={str(key): str(value) for key, value in metadata.get("labels", {}).items()},
            annotations={str(key): str(value) for key, value in metadata.get("annotations", {}).items()},
            source_path=source_path,
        )

    @classmethod
    def from_file(cls, path: Path) -> "CapabilityManifest":
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(raw, source_path=path)

    def as_record(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "title": self.title,
            "transport": self.transport.kind,
            "risk": self.policy.risk,
            "requires_confirmation": self.policy.requires_confirmation,
            "parser_ref": self.output.parser_ref,
            "verified": self.output.verified,
            "labels": self.labels,
            "annotations": self.annotations,
            "source_path": str(self.source_path) if self.source_path else None,
        }

    def search_text(self) -> dict[str, str]:
        return {
            "capability_id": self.capability_id,
            "title": self.title,
            "transport": self.transport.kind,
            "command": " ".join(self.transport.argv()),
            "risk": self.policy.risk,
            "parser_ref": self.output.parser_ref or "",
            "labels": " ".join(f"{key}:{value}" for key, value in sorted(self.labels.items())),
            "annotations": " ".join(f"{key}:{value}" for key, value in sorted(self.annotations.items())),
            "source_path": str(self.source_path) if self.source_path else "",
        }


class ManifestRegistry:
    def __init__(self) -> None:
        self._manifests: dict[str, CapabilityManifest] = {}

    def register(self, manifest: CapabilityManifest) -> None:
        if manifest.capability_id in self._manifests:
            raise ValueError(f"duplicate capability manifest: {manifest.capability_id}")
        self._manifests[manifest.capability_id] = manifest

    def load_dir(self, manifest_dir: Path) -> None:
        if not manifest_dir.exists():
            return
        for path in sorted(manifest_dir.glob("*.json")):
            self.register(CapabilityManifest.from_file(path))

    def list(self) -> list[CapabilityManifest]:
        return [self._manifests[key] for key in sorted(self._manifests)]

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(0, min(limit, 100))
        tokens = [token for token in query.casefold().split() if token]
        if not tokens:
            return [
                {"manifest": manifest.as_record(), "match": {"score": 0, "fields": []}}
                for manifest in self.list()[:limit]
            ]
        matches = []
        for manifest in self.list():
            fields = manifest.search_text()
            haystack = {field: value.casefold() for field, value in fields.items()}
            if not all(any(token in value for value in haystack.values()) for token in tokens):
                continue
            matched_fields = sorted(
                field
                for field, value in haystack.items()
                if any(token in value for token in tokens)
            )
            score = sum(
                3 if value.startswith(token) else value.count(token)
                for value in haystack.values()
                for token in tokens
            )
            matches.append(
                {
                    "manifest": manifest.as_record(),
                    "match": {
                        "score": score,
                        "fields": matched_fields,
                    },
                }
            )
        matches.sort(
            key=lambda item: (
                -item["match"]["score"],
                item["manifest"]["capability_id"],
            )
        )
        return matches[:limit]

    def get(self, capability_id: str) -> CapabilityManifest | None:
        return self._manifests.get(capability_id)

    def require(self, capability_id: str) -> CapabilityManifest:
        manifest = self.get(capability_id)
        if manifest is None:
            raise KeyError(f"unknown capability: {capability_id}")
        return manifest
