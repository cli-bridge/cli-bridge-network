import json
import subprocess
import sys
import unittest

from cbn_demo.killer import DEFAULT_KILLER_WORKFLOW_PATH, killer_demo_report
from cbn_runtime.context import build_runtime


class KillerDemoTests(unittest.TestCase):
    def test_killer_demo_report_runs_cli_to_cli_chain(self):
        runtime = build_runtime()
        payload = killer_demo_report(
            runtime.registry,
            runtime.workflow_runner,
            workflow_path=DEFAULT_KILLER_WORKFLOW_PATH,
            run=True,
            dry_run=True,
            run_smoke_suite=False,
            event_tail=runtime.event_bus.tail(limit=10),
            audit_tail=runtime.audit_log.tail(limit=10),
            artifact_list=runtime.artifact_store.list(limit=10),
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["kind"], "CbnKillerDemoReport")
        self.assertEqual(payload["summary"]["route_count"], 2)
        self.assertEqual(payload["summary"]["workflow_status"], "completed")
        self.assertGreaterEqual(payload["summary"]["artifact_count"], 6)
        self.assertEqual(payload["summary"]["recommended_next_action"], "open_workflow_studio_demo")
        self.assertEqual(
            [stage["id"] for stage in payload["stages"][:6]],
            [
                "import_cli_anything_harness",
                "generate_manifest",
                "run_macrocli",
                "parse_payload",
                "transform_to_mermaid",
                "run_mermaid",
            ],
        )

    def test_cli_demo_killer_outputs_report(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn", "demo", "killer", "--run", "--dry-run"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["kind"], "CbnKillerDemoReport")
        self.assertEqual(payload["summary"]["completed_stage_count"], 8)
        self.assertIsNone(payload["summary"]["smoke_ok"])


if __name__ == "__main__":
    unittest.main()
