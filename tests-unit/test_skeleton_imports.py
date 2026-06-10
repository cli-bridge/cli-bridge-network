import json
import subprocess
import sys
import unittest

from app.registry import CapabilityRecord, CapabilityRegistry
from cbn.paths import resolve_project_paths
from cbn_execution.graph import TaskNode, WorkflowGraph
from cbn_execution.validation import validate_risk


class SkeletonImportTests(unittest.TestCase):
    def test_cli_health_runs(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn", "health"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "ok")

    def test_registry_roundtrip(self):
        registry = CapabilityRegistry()
        registry.register(CapabilityRecord("git.version", "Git Version", "stdio", "read"))
        self.assertEqual(registry.get("git.version").transport, "stdio")

    def test_graph_validation(self):
        graph = WorkflowGraph(
            tasks=[
                TaskNode("discover", "cbn.discover"),
                TaskNode("inspect", "cbn.inspect", needs=("discover",)),
            ]
        )
        graph.validate()

    def test_paths_resolve(self):
        paths = resolve_project_paths()
        self.assertTrue(paths.root.exists())

    def test_risk_validation(self):
        validate_risk("read")
        with self.assertRaises(ValueError):
            validate_risk("unknown")


if __name__ == "__main__":
    unittest.main()

