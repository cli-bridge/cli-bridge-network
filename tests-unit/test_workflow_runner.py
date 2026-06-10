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
from cbn_protocol.envelope import validate_bridge_message
from cbn_tools.artifact_id_summary import summarize_artifact
from cbn_workflow.catalog import inspect_workflow, list_workflows
from cbn_workflow.runner import WorkflowRunner


class WorkflowRunnerTests(unittest.TestCase):
    def test_workflow_graph_orders_dependencies(self):
        graph = WorkflowGraph.from_file(Path("workflows/example.json"))
        self.assertEqual([task.task_id for task in graph.topological_order()], ["git-version", "git-status"])

    def test_workflow_graph_keeps_args_from_in_plan(self):
        graph = WorkflowGraph.from_dict(
            {
                "apiVersion": "bridge.dev/v1alpha1",
                "kind": "Workflow",
                "metadata": {"id": "message-route"},
                "spec": {
                    "tasks": [
                        {"id": "source", "uses": "git.version"},
                        {
                            "id": "consumer",
                            "uses": "git.version",
                            "needs": ["source"],
                            "argsFrom": [{"task": "source", "selector": "payload.data.stdout"}],
                        },
                    ]
                },
            }
        )
        plan = graph.as_plan()
        self.assertEqual(plan["tasks"][1]["argsFrom"][0]["selector"], "payload.data.stdout")

    def test_cli_anything_mermaid_workflow_routes_file_path_from_bridge_message(self):
        graph = WorkflowGraph.from_file(Path("workflows/cli-anything-mermaid-routing.example.json"))
        plan = graph.as_plan()
        consumer = plan["tasks"][1]
        self.assertEqual(plan["workflow_id"], "example.cli-anything-mermaid-routing")
        self.assertEqual(consumer["uses"], "cli-anything.mermaid.set-diagram")
        self.assertEqual(consumer["args"], [])
        self.assertEqual(
            consumer["argsFrom"],
            [{"task": "source-diagram", "selector": "payload.data.stdout"}],
        )

    def test_cli_anything_macrocli_mermaid_workflow_routes_parser_payload(self):
        graph = WorkflowGraph.from_file(Path("workflows/cli-anything-macrocli-mermaid-routing.example.json"))
        plan = graph.as_plan()
        transform = plan["tasks"][1]
        consumer = plan["tasks"][2]
        self.assertEqual(plan["workflow_id"], "example.cli-anything-macrocli-mermaid-routing")
        self.assertEqual([task["uses"] for task in plan["tasks"]], [
            "cli-anything.macrocli.backends",
            "cbn.transform.macrocli-backends-to-mermaid",
            "cli-anything.mermaid.set-diagram",
        ])
        self.assertEqual(
            transform["argsFrom"],
            [{"task": "macrocli-backends", "selector": "payload.data"}],
        )
        self.assertEqual(
            consumer["argsFrom"],
            [{"task": "backend-diagram-source", "selector": "payload.data.stdout"}],
        )

    def test_artifact_id_workflow_routes_artifact_reference(self):
        graph = WorkflowGraph.from_file(Path("workflows/artifact-id-routing.example.json"))
        plan = graph.as_plan()
        consumer = plan["tasks"][1]
        self.assertEqual(plan["workflow_id"], "example.artifact-id-routing")
        self.assertEqual(consumer["uses"], "cbn.sample.artifact-id-summary")
        self.assertEqual(
            consumer["argsFrom"],
            [{"task": "artifact-source", "selector": "artifacts[0].artifact_id"}],
        )

    def test_workflow_catalog_lists_descriptors_with_capability_summaries(self):
        registry = ManifestRegistry()
        registry.load_dir(Path("manifests"))
        descriptors = list_workflows(registry=registry)
        by_id = {item["workflow_id"]: item for item in descriptors}
        self.assertIn("example.cli-anything-macrocli-mermaid-routing", by_id)
        workflow = by_id["example.cli-anything-macrocli-mermaid-routing"]
        self.assertTrue(workflow["valid"])
        self.assertEqual(workflow["task_count"], 3)
        self.assertEqual(workflow["tasks"][0]["capability"]["parser_ref"], "cli-anything.macrocli.backends")
        self.assertEqual(workflow["tasks"][1]["capability"]["risk"], "write-workspace")
        self.assertTrue(workflow["tasks"][2]["capability"]["verified"])

    def test_workflow_catalog_reports_invalid_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{}", encoding="utf-8")
            descriptor = inspect_workflow(path)
            self.assertFalse(descriptor["valid"])
            self.assertIn("unsupported workflow apiVersion", descriptor["errors"][0])

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

    def test_workflow_graph_requires_args_from_dependency(self):
        graph = WorkflowGraph.from_dict(
            {
                "apiVersion": "bridge.dev/v1alpha1",
                "kind": "Workflow",
                "metadata": {"id": "missing-arg-dep"},
                "spec": {
                    "tasks": [
                        {"id": "source", "uses": "git.version"},
                        {
                            "id": "consumer",
                            "uses": "git.version",
                            "argsFrom": [{"task": "source", "selector": "payload.data.stdout"}],
                        },
                    ]
                },
            }
        )
        with self.assertRaisesRegex(ValueError, "must also be listed in needs"):
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

    def test_runner_resolves_args_from_bridge_message_selector(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = ManifestRegistry()
            registry.load_dir(Path("manifests"))
            executor = CapabilityExecutor(
                registry,
                AuditLog(Path(tmp) / "audit.jsonl"),
                artifact_store=ArtifactStore(Path(tmp) / "artifacts"),
            )
            runner = WorkflowRunner(executor)
            graph = WorkflowGraph.from_dict(
                {
                    "apiVersion": "bridge.dev/v1alpha1",
                    "kind": "Workflow",
                    "metadata": {"id": "message-route"},
                    "spec": {
                        "tasks": [
                            {"id": "source", "uses": "git.version"},
                            {
                                "id": "consumer",
                                "uses": "git.version",
                                "needs": ["source"],
                                "argsFrom": [{"task": "source", "selector": "payload.data.stdout"}],
                            },
                        ]
                    },
                }
            )
            result = runner.run(graph, dry_run=True)
            consumer = result["tasks"][1]
            self.assertEqual(consumer["resolved_args"], ["git --version"])
            self.assertEqual(consumer["result"]["stdout"], "git --version git --version")

    def test_runner_reports_recoverable_args_from_selector_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = ManifestRegistry()
            registry.load_dir(Path("manifests"))
            executor = CapabilityExecutor(registry, AuditLog(Path(tmp) / "audit.jsonl"))
            runner = WorkflowRunner(executor)
            graph = WorkflowGraph.from_dict(
                {
                    "apiVersion": "bridge.dev/v1alpha1",
                    "kind": "Workflow",
                    "metadata": {"id": "bad-selector"},
                    "spec": {
                        "tasks": [
                            {"id": "source", "uses": "git.version"},
                            {
                                "id": "consumer",
                                "uses": "git.version",
                                "needs": ["source"],
                                "argsFrom": [{"task": "source", "selector": "payload.data.missing"}],
                            },
                        ]
                    },
                }
            )
            result = runner.run(graph, dry_run=True)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["summary"]["failed_count"], 1)
            self.assertEqual(result["recovery"]["action"], "fix_args_from_selector")
            consumer = result["tasks"][1]
            self.assertEqual(consumer["status"], "failed")
            self.assertEqual(consumer["result"]["reason"], "args_resolution_failed")
            self.assertEqual(consumer["recovery"]["resume_mode"], "rerun_after_fix")

    def test_runner_marks_blocked_task_and_skips_downstream(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = ManifestRegistry()
            registry.load_dir(Path("manifests"))
            executor = CapabilityExecutor(registry, AuditLog(Path(tmp) / "audit.jsonl"))
            runner = WorkflowRunner(executor)
            graph = WorkflowGraph.from_dict(
                {
                    "apiVersion": "bridge.dev/v1alpha1",
                    "kind": "Workflow",
                    "metadata": {"id": "approval-blocked"},
                    "spec": {
                        "tasks": [
                            {"id": "write", "uses": "jimeng.user_credit"},
                            {"id": "after", "uses": "git.version", "needs": ["write"]},
                        ]
                    },
                }
            )
            result = runner.run(graph)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["summary"]["blocked_count"], 1)
            self.assertEqual(result["summary"]["skipped_count"], 1)
            self.assertEqual(result["recovery"]["action"], "request_approval")
            self.assertEqual(result["tasks"][0]["status"], "blocked")
            self.assertEqual(result["tasks"][0]["recovery"]["resume_mode"], "rerun_after_approval")
            self.assertEqual(result["tasks"][1]["status"], "skipped")
            self.assertEqual(result["tasks"][1]["result"]["upstream_task_id"], "write")

    def test_runner_routes_artifact_id_to_downstream_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = ManifestRegistry()
            registry.load_dir(Path("manifests"))
            executor = CapabilityExecutor(
                registry,
                AuditLog(Path(tmp) / "audit.jsonl"),
                artifact_store=ArtifactStore(Path(tmp) / "artifacts"),
            )
            runner = WorkflowRunner(executor)
            result = runner.run(WorkflowGraph.from_file(Path("workflows/artifact-id-routing.example.json")))
            self.assertEqual(result["status"], "completed")
            source = result["tasks"][0]
            consumer = result["tasks"][1]
            artifact_id = source["result"]["artifacts"][0]["artifact_id"]
            summary = consumer["result"]["parsed"]["data"]["json"]
            self.assertEqual(consumer["resolved_args"], [artifact_id])
            self.assertEqual(summary["artifact_id"], artifact_id)
            self.assertEqual(summary["kind"], "stdout")
            self.assertIn("git version", summary["content_preview"])
            for task in result["tasks"]:
                validation = validate_bridge_message(task["result"]["message"])
                self.assertTrue(validation["valid"], validation["errors"])
                self.assertIsInstance(validation["payload_ok"], bool)
                self.assertGreaterEqual(validation["artifact_count"], 1)

    def test_artifact_id_summary_reads_artifact_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ArtifactStore(Path(tmp) / "artifacts")
            record = store.create_text("sample.source", "call-1", "stdout", "artifact payload")
            self.assertIsNotNone(record)
            payload = summarize_artifact(record.artifact_id, root=store.root)
            self.assertEqual(payload["artifact_id"], record.artifact_id)
            self.assertEqual(payload["content_preview"], "artifact payload")

    def test_cli_workflow_validate_plan_and_run(self):
        for args in (
            ["workflow", "validate", "workflows/example.json"],
            ["workflow", "list"],
            ["workflow", "inspect", "workflows/cli-anything-macrocli-mermaid-routing.example.json"],
            ["workflow", "plan", "workflows/example.json"],
            ["workflow", "run", "workflows/example.json", "--dry-run"],
            ["workflow", "run", "workflows/message-routing.example.json", "--dry-run"],
            ["workflow", "validate", "workflows/artifact-id-routing.example.json"],
            ["workflow", "validate", "workflows/cli-anything-macrocli-mermaid-routing.example.json"],
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
