import unittest

from cbn_agent import (
    AgentBridgeMessage,
    AgentCard,
    AgentHarness,
    AgentSession,
    AgentTask,
    agent_bridge_message,
)
from cbn_core.message import validate_bridge_message


class CbnAgentModelTests(unittest.TestCase):
    def test_agent_card_and_harness_are_stable_records(self):
        card = AgentCard(
            agent_id="workflow-setup-agent",
            role="workflow-setup",
            title="Workflow Setup Agent",
            capabilities=("guide-auth-setup", "collect-runtime-inputs"),
            transport={"kind": "in-process"},
            policy={"risk": "write-workspace"},
        )
        harness = AgentHarness(harness_id="setup-harness", card=card)

        card_payload = card.as_dict()
        harness_payload = harness.as_dict()

        self.assertEqual(card_payload["kind"], "AgentCard")
        self.assertEqual(card_payload["metadata"]["role"], "workflow-setup")
        self.assertEqual(card_payload["spec"]["capabilities"], ["guide-auth-setup", "collect-runtime-inputs"])
        self.assertEqual(harness_payload["kind"], "AgentHarness")
        self.assertEqual(harness_payload["spec"]["accepts"], ["BridgeMessage"])
        self.assertIn("Artifact", harness_payload["spec"]["emits"])

    def test_agent_session_and_task_map_to_workflow_node(self):
        session = AgentSession(
            agent_id="orchestration-coordinator-agent",
            workflow_id="auth.workflow",
            session_id="session-1",
            context={"resume_command": "python -m cbn workflow run"},
        )
        task = AgentTask(
            task_id="route-cli-output",
            agent_id="orchestration-coordinator-agent",
            instruction="Route previous CLI payload into Mermaid",
            uses="cli-anything.mermaid.set-diagram",
            selectors=("payload.data.diagram",),
            inputs={"format": "mermaid"},
        )

        self.assertEqual(session.as_dict()["metadata"]["workflowId"], "auth.workflow")
        node = task.as_workflow_node()
        self.assertEqual(node["agent"], "orchestration-coordinator-agent")
        self.assertEqual(node["uses"], "cli-anything.mermaid.set-diagram")
        self.assertEqual(node["argsFrom"], [{"selector": "payload.data.diagram"}])
        self.assertEqual(node["with"], {"format": "mermaid"})

    def test_agent_bridge_message_validates_as_core_bridge_message(self):
        message = agent_bridge_message(
            agent_id="verification-agent",
            session_id="session-1",
            task_id="verify-output",
            channel="agent.verification",
            data={"status": "passed"},
            artifacts=(
                {
                    "artifact_id": "artifact-1",
                    "kind": "report",
                    "path": "runtime/reports/verify.json",
                },
            ),
        )

        validation = validate_bridge_message(message)

        self.assertTrue(validation["valid"], validation["errors"])
        self.assertEqual(validation["producer"], "agent:verification-agent")
        self.assertEqual(validation["channel"], "agent.verification")
        self.assertEqual(validation["correlation_id"], "session-1:verify-output")
        self.assertEqual(validation["payload_parser_ref"], "cbn.agent.bridge_message")
        self.assertEqual(validation["artifact_count"], 1)

    def test_agent_bridge_message_dataclass_handles_error_payload(self):
        message = AgentBridgeMessage(
            agent_id="workflow-setup-agent",
            session_id="session-2",
            task_id="collect-secret",
            channel="agent.setup",
            ok=False,
            error="missing API key",
            data={"missing": ["JIMENG_API_KEY"]},
        ).as_bridge_message()

        validation = validate_bridge_message(message)

        self.assertTrue(validation["valid"], validation["errors"])
        self.assertFalse(validation["payload_ok"])
        self.assertEqual(message["payload"]["error"], "missing API key")


if __name__ == "__main__":
    unittest.main()
