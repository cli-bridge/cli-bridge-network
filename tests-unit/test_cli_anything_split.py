import json
import subprocess
import sys
import unittest
from pathlib import Path

from cbn_plugins.cli_anything import CliAnythingHub
from cbn_plugins.cli_anything_parts import EXPECTED_PART_MODULES, module_split_report


class CliAnythingSplitTests(unittest.TestCase):
    def test_module_split_report_tracks_expected_parts(self):
        report = module_split_report(facade_path=Path("cbn_plugins/cli_anything.py"))

        self.assertEqual(report["kind"], "CliAnythingModuleSplitReport")
        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["expected_part_count"], len(EXPECTED_PART_MODULES))
        self.assertEqual(report["present_part_count"], len(EXPECTED_PART_MODULES))
        self.assertGreater(report["facade_line_count"], 100)
        self.assertEqual({part["id"] for part in report["parts"]}, set(EXPECTED_PART_MODULES))
        self.assertTrue(all(part["present"] for part in report["parts"]))

    def test_cli_anything_status_includes_module_split_health(self):
        status = CliAnythingHub().status()

        self.assertEqual(status["module_split"]["kind"], "CliAnythingModuleSplitReport")
        self.assertEqual(status["module_split"]["status"], "ready")
        self.assertEqual(status["module_split"]["present_part_count"], len(EXPECTED_PART_MODULES))

    def test_plugin_status_cli_outputs_module_split_health(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn", "plugin", "status", "cli-anything"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)

        self.assertEqual(payload["module_split"]["status"], "ready")
        self.assertIn("manifest_factory", {part["id"] for part in payload["module_split"]["parts"]})


if __name__ == "__main__":
    unittest.main()
