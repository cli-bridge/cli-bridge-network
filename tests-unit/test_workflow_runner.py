import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cbn_audit.log import AuditLog
from cbn_artifacts.store import ArtifactStore
from cbn_core.manifest import ManifestRegistry
from cbn_events.bus import EventBus
from cbn_execution.executor import CapabilityExecutor
from cbn_execution.graph import WorkflowGraph
from cbn_workflow.runner import WorkflowRunner


class WorkflowRunnerTests(unittest.TestCase):
    def test_workflow_graph_orders_dependencies(self):
        graph = WorkflowGraph.from_file(Path("workflows/example.json"))
        self.assertEqual([task.task_id for task in graph.topological_order()], ["git-version", "git-status"])

    def test_workflow_graph_rejects_cycles(self):
        graph = WorkflowGraph.from_dict(
            {
                "apiVersion": "bridge.dev/v1alpha1",
                "kind": "Workflow",
                "metadata": {"id": "cycle"},
                "spec": {
                    "tasks": [
                        {"id": "a", "uses": "git.version", "needs": ["b"]},
                        {"id": "b", "uses": "git.version", "needs": ["a"]},
                    ]
                },
            }
        )
        with self.assertRaises(ValueError):
            graph.validate()

    def test_runner_executes_example_workflow_as_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = ManifestRegistry()
            registry.load_dir(Path("manifests"))
            event_bus = EventBus(Path(tmp) / "events.jsonl")
            executor = CapabilityExecutor(
                registry,
                AuditLog(Path(tmp) / "audit.jsonl"),
                event_bus=event_bus,
                artifact_store=ArtifactStore(Path(tmp) / "artifacts"),
            )
            runner = WorkflowRunner(executor, event_bus=event_bus, audit_log=AuditLog(Path(tmp) / "audit.jsonl"))
            result = runner.run(WorkflowGraph.from_file(Path("workflows/example.json")), dry_run=True)
            self.assertEqual(result["status"], "completed")
            self.assertEqual([task["task_id"] for task in result["tasks"]], ["git-version", "git-status"])
            event_types = [event["type"] for event in event_bus.tail(limit=20)]
            self.assertIn("workflow.started", event_types)
            self.assertIn("workflow.completed", event_types)

    def test_cli_workflow_validate_plan_and_run(self):
        for args in (
            ["workflow", "validate", "workflows/example.json"],
            ["workflow", "plan", "workflows/example.json"],
            ["workflow", "run", "workflows/example.json", "--dry-run"],
        ):
            proc = subprocess.run(
                [sys.executable, "-m", "cbn", *args],
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            self.assertTrue(json.loads(proc.stdout))


if __name__ == "__main__":
    unittest.main()
