"""ToolManifest factory for CLI-Anything harnesses."""

from __future__ import annotations

import json
import re
from typing import Any


PLUGIN_ID = "cli-anything"
MARKET_LABEL_KEYS = ("category", "_source", "package_manager", "platform")
MARKET_ANNOTATION_KEYS = (
    "display_name",
    "version",
    "description",
    "requires",
    "homepage",
    "docs_url",
    "source_url",
    "install_cmd",
    "update_cmd",
    "uninstall_cmd",
    "entry_point",
    "skill_md",
    "npm_package",
    "npx_cmd",
    "contributors",
)
RISK_ORDER = ("read", "write-workspace", "external-network", "privileged")
RUNTIME_TEXT_KEYS = ("description", "requires")
LOCAL_NETWORK_MARKERS = ("localhost", "127.0.0.1", "::1")
EXTERNAL_NETWORK_MARKERS = (
    "api key",
    "apikey",
    "access token",
    "auth token",
    "bearer token",
    "n8n rest api",
    "cloud api",
    "remote api",
    "google_cloud_project",
    "gemini_api_key",
    "openai_api_key",
    "anthropic_api_key",
    "vertex ai",
    "gemini",
    "openai",
    "anthropic",
    "replicate",
    "huggingface",
    "cloud",
)
WRITE_WORKSPACE_MARKERS = (
    "generate",
    "generation",
    "export",
    "convert",
    "transcode",
    "render",
    "edit",
    "image",
    "video",
    "svg",
    "raster",
    "painting",
)


def build_harness_manifest(
    harness_name: str,
    entrypoint: str,
    title: str | None = None,
    risk: str = "read",
    market_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    market_record = market_record or {}
    market_name = str(market_record.get("name") or harness_name)
    display_name = str(market_record.get("display_name") or market_name)
    safe_name = sanitize_harness_name(market_name)
    capability_id = f"cli-anything.{safe_name}.launch"
    labels = {
        "plugin": PLUGIN_ID,
        "harness": market_name,
    }
    labels.update(market_labels(market_record))
    annotations = market_annotations(market_record)
    policy = infer_market_policy(market_record, requested_risk=risk)
    if policy["reasons"]:
        annotations["cli-anything.policy_inference"] = json.dumps(
            policy["reasons"],
            ensure_ascii=False,
            sort_keys=True,
        )
    return {
        "apiVersion": "bridge.dev/v1alpha1",
        "kind": "ToolManifest",
        "metadata": {
            "id": capability_id,
            "title": title or f"CLI-Anything {display_name}",
            "labels": labels,
            "annotations": annotations,
        },
        "spec": {
            "transport": {
                "kind": "pty",
                "command": entrypoint,
                "argsTemplate": ["launch", market_name, "--"],
                "cwdPolicy": "workspace",
                "timeoutSeconds": 600,
            },
            "policy": {
                "risk": policy["risk"],
                "requiresConfirmation": policy["requires_confirmation"],
                "network": policy["network"],
            },
            "output": {
                "parserRef": "cli-anything.raw",
                "verified": False,
            },
        },
    }


def sanitize_harness_name(name: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", name.strip()).strip("-._")
    if not normalized:
        raise ValueError("harness name cannot be empty")
    return normalized.lower()


def market_labels(market_record: dict[str, Any]) -> dict[str, str]:
    labels = {}
    for key in MARKET_LABEL_KEYS:
        value = market_record.get(key)
        if value is None or value == "":
            continue
        labels[key.strip("_")] = str(value)
    return labels


def market_annotations(market_record: dict[str, Any]) -> dict[str, str]:
    annotations = {}
    for key in MARKET_ANNOTATION_KEYS:
        value = market_record.get(key)
        if value is None or value == "":
            continue
        annotation_key = f"cli-anything.{key}"
        if isinstance(value, (dict, list)):
            annotations[annotation_key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
        else:
            annotations[annotation_key] = str(value)
    return annotations


def infer_market_policy(
    market_record: dict[str, Any] | None,
    requested_risk: str = "read",
) -> dict[str, Any]:
    risk = requested_risk
    network = "deny"
    reasons: list[str] = []
    if market_record:
        runtime_text = market_runtime_text(market_record)
        if has_local_network_signal(runtime_text):
            network = "localhost"
            reasons.append("runtime mentions local service or localhost dependency")
        if has_external_network_signal(runtime_text):
            risk = max_risk(risk, "external-network")
            network = "requires-confirmation"
            reasons.append("runtime mentions external API, cloud service, token, or API key")
        if has_write_workspace_signal(runtime_text):
            risk = max_risk(risk, "write-workspace")
            reasons.append("runtime appears to generate, edit, render, convert, or export artifacts")
    requires_confirmation = risk in {"privileged", "external-network"}
    if risk in {"privileged", "external-network"}:
        network = "requires-confirmation" if risk == "external-network" else network
    return {
        "risk": risk,
        "requires_confirmation": requires_confirmation,
        "network": network,
        "reasons": reasons,
    }


def preserve_existing_parser_contract(
    existing: dict[str, Any],
    generated: dict[str, Any],
) -> dict[str, Any]:
    existing_output = ((existing.get("spec") or {}).get("output") or {})
    generated_output = ((generated.get("spec") or {}).get("output") or {})
    if (
        existing_output.get("verified") is True
        and existing_output.get("parserRef") == generated_output.get("parserRef")
    ):
        generated_output["verified"] = True
        generated_annotations = generated.setdefault("metadata", {}).setdefault("annotations", {})
        existing_annotations = (existing.get("metadata") or {}).get("annotations") or {}
        for key, value in existing_annotations.items():
            if str(key).startswith("cbn.parser"):
                generated_annotations.setdefault(key, value)
    return generated


def market_runtime_text(market_record: dict[str, Any]) -> str:
    values = []
    for key in RUNTIME_TEXT_KEYS:
        value = market_record.get(key)
        if value:
            values.append(str(value))
    return "\n".join(values).casefold()


def has_local_network_signal(text: str) -> bool:
    return any(marker in text for marker in LOCAL_NETWORK_MARKERS)


def has_external_network_signal(text: str) -> bool:
    if any(marker in text for marker in EXTERNAL_NETWORK_MARKERS):
        return True
    for match in re.findall(r"https?://[^\s)]+", text):
        if not any(local in match for local in LOCAL_NETWORK_MARKERS):
            return True
    return False


def has_write_workspace_signal(text: str) -> bool:
    return any(marker in text for marker in WRITE_WORKSPACE_MARKERS)


def max_risk(left: str, right: str) -> str:
    try:
        left_rank = RISK_ORDER.index(left)
        right_rank = RISK_ORDER.index(right)
    except ValueError as exc:
        raise ValueError(f"unknown risk level for CLI-Anything policy inference: {exc}") from exc
    return left if left_rank >= right_rank else right
