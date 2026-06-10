"""Capability node registry.

ComfyUI exposes node classes through a central registry. CBN uses the same
shape for adapter-backed capabilities, but the registered objects describe CLI
and protocol capabilities instead of image-processing nodes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CapabilityNode:
    node_id: str
    title: str
    category: str
    risk: str = "read"


CAPABILITY_NODE_MAPPINGS: dict[str, CapabilityNode] = {}


def register_node(node: CapabilityNode) -> None:
    if node.node_id in CAPABILITY_NODE_MAPPINGS:
        raise ValueError(f"duplicate capability node: {node.node_id}")
    CAPABILITY_NODE_MAPPINGS[node.node_id] = node


def init_builtin_nodes() -> None:
    if CAPABILITY_NODE_MAPPINGS:
        return
    register_node(CapabilityNode("cbn.health", "CBN Health", "system"))
    register_node(CapabilityNode("cbn.registry.list", "List Capabilities", "registry"))
    register_node(CapabilityNode("cbn.adapter.stdio", "stdio Adapter", "adapter"))


async def init_extra_nodes(init_custom_nodes: bool = True) -> None:
    """Initialize built-in nodes and reserve a hook for custom node loading."""
    init_builtin_nodes()
    if init_custom_nodes:
        # Custom adapter discovery will land after the manifest contract is stable.
        return

