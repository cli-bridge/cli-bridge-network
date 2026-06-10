"""Compatibility exports for the renamed Workflow Setup Agent."""

from __future__ import annotations

from cbn_adapter_agent.workflow_setup import (
    build_workflow_initialization_plan,
    build_workflow_setup_plan,
)

__all__ = ["build_workflow_initialization_plan", "build_workflow_setup_plan"]
