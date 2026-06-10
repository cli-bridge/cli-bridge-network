"""Protocol export registry for CBN capabilities."""

from __future__ import annotations

from typing import Any
from pathlib import Path

from cbn_core.manifest import CapabilityManifest, ManifestRegistry
from cbn_workflow.catalog import inspect_workflow, list_workflows
from protocols import a2a, acp, mcp


PROTOCOL_EXPORTS = {
    "mcp": mcp.export_capabilities,
    "a2a": a2a.export_capabilities,
    "acp": acp.export_capabilities,
}


def list_protocol_exports() -> list[dict[str, Any]]:
    return [
        {
            "protocol": name,
            "wire_compatible": False,
            "description": "MVP descriptor export; not a full protocol server.",
        }
        for name in sorted(PROTOCOL_EXPORTS)
    ]


def export_protocol(
    registry: ManifestRegistry,
    protocol: str,
    capability_id: str | None = None,
) -> dict[str, Any]:
    if protocol not in PROTOCOL_EXPORTS:
        raise KeyError(f"unknown protocol export: {protocol}")
    manifests: list[CapabilityManifest]
    if capability_id:
        manifests = [registry.require(capability_id)]
    else:
        manifests = registry.list()
    return PROTOCOL_EXPORTS[protocol](manifests)


def export_all_protocols(
    registry: ManifestRegistry,
    capability_id: str | None = None,
) -> dict[str, Any]:
    return {
        "exports": {
            protocol: export_protocol(registry, protocol, capability_id=capability_id)
            for protocol in sorted(PROTOCOL_EXPORTS)
        }
    }


def export_workflow_protocol(
    registry: ManifestRegistry,
    protocol: str,
    workflow_path: str | None = None,
) -> dict[str, Any]:
    if protocol not in PROTOCOL_EXPORTS:
        raise KeyError(f"unknown protocol export: {protocol}")
    workflows = _workflow_descriptors(registry, workflow_path=workflow_path)
    if protocol == "mcp":
        return _export_mcp_workflows(workflows)
    if protocol == "a2a":
        return _export_a2a_workflows(workflows)
    return _export_acp_workflows(workflows)


def export_all_workflow_protocols(
    registry: ManifestRegistry,
    workflow_path: str | None = None,
) -> dict[str, Any]:
    return {
        "exports": {
            protocol: export_workflow_protocol(registry, protocol, workflow_path=workflow_path)
            for protocol in sorted(PROTOCOL_EXPORTS)
        }
    }


def _workflow_descriptors(
    registry: ManifestRegistry,
    workflow_path: str | None,
) -> list[dict[str, Any]]:
    if workflow_path:
        return [inspect_workflow(Path(workflow_path), registry=registry)]
    return list_workflows(registry=registry)


def _export_mcp_workflows(workflows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "protocol": "mcp",
        "wire_compatible": False,
        "workflowTools": [
            {
                "name": f"workflow:{workflow['workflow_id'] or workflow['path']}",
                "description": workflow["title"] or workflow["path"],
                "inputSchema": _workflow_input_schema(),
                "_meta": {
                    "cbn": _workflow_cbn_contract(workflow),
                    "cbn_workflow": workflow,
                },
            }
            for workflow in workflows
        ],
    }


def _export_a2a_workflows(workflows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "protocol": "a2a",
        "wire_compatible": False,
        "agentCard": {
            "name": "CLI Bridge Network",
            "description": "Local-first CBN workflow export descriptor.",
            "skills": [
                {
                    "id": f"workflow:{workflow['workflow_id'] or workflow['path']}",
                    "name": workflow["title"] or workflow["path"],
                    "description": "CBN workflow descriptor for multi-capability routing.",
                    "inputModes": ["application/json"],
                    "outputModes": ["application/json"],
                    "metadata": {
                        "cbn_input": {
                            "metadata.cbn.workflow_id": workflow["workflow_id"],
                            "metadata.cbn.workflow_path": workflow["path"],
                            "metadata.cbn.dry_run": "boolean",
                            "metadata.cbn.confirmed": "boolean",
                        }
                    },
                    "tags": ["workflow", f"tasks:{workflow['task_count']}"],
                    "cbn": _workflow_cbn_contract(workflow),
                    "cbn_workflow": workflow,
                }
                for workflow in workflows
            ],
        },
    }


def _export_acp_workflows(workflows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "protocol": "acp",
        "wire_compatible": False,
        "workflows": [
            {
                "id": f"workflow:{workflow['workflow_id'] or workflow['path']}",
                "title": workflow["title"] or workflow["path"],
                "kind": "workflow",
                "input": {
                    "workflow_id": "string",
                    "workflow_path": "string",
                    "dry_run": "boolean",
                    "confirmed": "boolean",
                },
                "output": {
                    "run": "WorkflowRun",
                    "messages": "BridgeMessage[]",
                },
                "cbn": _workflow_cbn_contract(workflow),
                "cbn_workflow": workflow,
            }
            for workflow in workflows
        ],
    }


def _workflow_input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "dry_run": {"type": "boolean"},
            "confirmed": {"type": "boolean"},
            "workflow_id": {
                "type": "string",
                "description": "Optional stable workflow id; omitted when calling a workflow:<id> tool.",
            },
            "workflow_path": {
                "type": "string",
                "description": "Local compatibility fallback; prefer workflow_id or the workflow:<id> tool name.",
            },
        },
        "additionalProperties": False,
    }


def _workflow_cbn_contract(workflow: dict[str, Any]) -> dict[str, Any]:
    return {
        "apiVersion": "bridge.dev/v1alpha1",
        "kind": "WorkflowDescriptor",
        "workflow_id": workflow["workflow_id"],
        "path": workflow["path"],
        "valid": workflow["valid"],
        "task_count": workflow["task_count"],
        "runner": "cbn.workflow.run",
        "output": {
            "message_kind": "WorkflowRun",
            "task_message_kind": "BridgeMessage",
        },
    }
