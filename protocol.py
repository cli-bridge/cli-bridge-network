"""Shared protocol constants for event and artifact messages."""

from enum import StrEnum


class EventType(StrEnum):
    CAPABILITY_REGISTERED = "capability.registered"
    TOOL_CALL_STARTED = "tool_call.started"
    TOOL_CALL_COMPLETED = "tool_call.completed"
    TOOL_CALL_BLOCKED = "tool_call.blocked"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_DECIDED = "approval.decided"
    ARTIFACT_CREATED = "artifact.created"
    OUTPUT_PARSED = "output.parsed"
    BRIDGE_MESSAGE_CREATED = "bridge.message.created"
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_TASK_STARTED = "workflow.task.started"
    WORKFLOW_TASK_COMPLETED = "workflow.task.completed"
    WORKFLOW_COMPLETED = "workflow.completed"
    PLUGIN_OPERATION_STARTED = "plugin.operation.started"
    PLUGIN_COMMAND_STARTED = "plugin.command.started"
    PLUGIN_COMMAND_COMPLETED = "plugin.command.completed"
    PLUGIN_OPERATION_COMPLETED = "plugin.operation.completed"
