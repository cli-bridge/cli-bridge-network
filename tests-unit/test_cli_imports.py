import json
import subprocess
import sys
import unittest


class CliImportTests(unittest.TestCase):
    def test_cli_anything_import_requires_confirmation_for_side_effects(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "import",
                "cli-anything",
                "gimp",
                "--offline",
                "--write",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(proc.returncode, 6)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_type"], "confirmation_required")

    def test_cli_anything_import_outputs_onboarding_report(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "import",
                "cli-anything",
                "gimp",
                "--offline",
                "--no-workflows",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["entrypoint"], "cbn import cli-anything")
        self.assertEqual(payload["kind"], "CliAnythingHarnessOnboarding")
        self.assertEqual(payload["plugin_id"], "cli-anything")
        self.assertEqual(payload["harness_name"], "gimp")
        self.assertEqual(payload["capability_id"], "cli-anything.gimp.launch")
        self.assertEqual(payload["compatibility"]["facade_for"], "CliAnythingHub.onboard_harness")
        self.assertTrue(any(stage["id"] == "adapt_manifest" for stage in payload["stage_results"]))


if __name__ == "__main__":
    unittest.main()
