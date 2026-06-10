import json
import tempfile
import unittest
from pathlib import Path

from cbn_audit.log import AuditLog
from cbn_artifacts.store import ArtifactStore
from cbn_core.manifest import ManifestRegistry
from cbn_execution.executor import CapabilityExecutor
from cbn_workflow.package import compile_workflow_package, inspect_workflow_package, run_workflow_package
from cbn_workflow.runner import WorkflowRunner


class WorkflowPackageTests(unittest.TestCase):
    def test_compile_writes_required_package_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = ManifestRegistry()
            registry.load_dir(Path("manifests"))
            package_dir = Path(tmp) / "package"

            report = compile_workflow_package(Path("workflows/example.json"), package_dir, registry)

            self.assertEqual(report["workflow_id"], "example.git-check")
            self.assertTrue((package_dir / "workflow.yaml").exists())
            self.assertTrue((package_dir / "tool_bindings.lock").exists())
            self.assertTrue((package_dir / "policy_profile.yaml").exists())
            self.assertTrue((package_dir / "compile_report.json").exists())
            self.assertTrue((package_dir / "golden_run.jsonl").exists())
            self.assertTrue((package_dir / "artifact_schemas" / "git-version.output.schema.json").exists())
            self.assertTrue(report["lock_status"]["ok"])

    def test_run_package_writes_stable_golden_and_run_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = ManifestRegistry()
            registry.load_dir(Path("manifests"))
            package_dir = Path(tmp) / "package"
            compile_workflow_package(Path("workflows/example.json"), package_dir, registry)

            runner = _runner(registry, Path(tmp) / "runtime")
            first = run_workflow_package(
                package_dir,
                registry,
                runner,
                dry_run=True,
                write_golden=True,
            )
            golden = (package_dir / "golden_run.jsonl").read_text(encoding="utf-8")
            second = run_workflow_package(
                package_dir,
                registry,
                runner,
                dry_run=True,
                write_golden=True,
            )

            self.assertTrue(first["ok"])
            self.assertTrue(second["ok"])
            self.assertEqual(golden, (package_dir / "golden_run.jsonl").read_text(encoding="utf-8"))
            state = json.loads((package_dir / "run_state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "completed")
            self.assertEqual(state["event_count"], 8)
            self.assertEqual(state["last_event_index"], 7)
            self.assertEqual(state["completed_task_count"], 2)
            self.assertEqual([task["status"] for task in state["tasks"]], ["completed", "completed"])
            self.assertTrue(all(item["valid"] for item in first["schema_validation"]))

    def test_inspect_package_reports_files_lock_run_state_and_golden_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = ManifestRegistry()
            registry.load_dir(Path("manifests"))
            package_dir = Path(tmp) / "package"
            compile_workflow_package(Path("workflows/example.json"), package_dir, registry)

            runner = _runner(registry, Path(tmp) / "runtime")
            run_workflow_package(
                package_dir,
                registry,
                runner,
                dry_run=True,
                write_golden=True,
            )

            inspection = inspect_workflow_package(package_dir, registry=registry)

            self.assertTrue(inspection["ok"])
            self.assertEqual(inspection["workflow_id"], "example.git-check")
            self.assertTrue(inspection["lock_status"]["ok"])
            self.assertEqual(inspection["run_state"]["status"], "completed")
            self.assertEqual(inspection["golden_run"]["event_count"], 8)
            self.assertTrue(all(item["exists"] for item in inspection["file_status"]))


def _runner(registry: ManifestRegistry, root: Path) -> WorkflowRunner:
    executor = CapabilityExecutor(
        registry,
        AuditLog(root / "audit.jsonl"),
        artifact_store=ArtifactStore(root / "artifacts"),
    )
    return WorkflowRunner(executor, audit_log=AuditLog(root / "workflow-audit.jsonl"))


if __name__ == "__main__":
    unittest.main()
