import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cbn_plugins.cli_anything import CliAnythingHub, sanitize_harness_name


class CliAnythingHubTests(unittest.TestCase):
    def test_sanitize_harness_name_keeps_manifest_safe(self):
        self.assertEqual(sanitize_harness_name("GIMP"), "gimp")
        self.assertEqual(sanitize_harness_name("image tools/gimp"), "image-tools-gimp")
        with self.assertRaises(ValueError):
            sanitize_harness_name("   ")

    def test_status_handles_missing_cli_hub_without_failing(self):
        hub = CliAnythingHub(entrypoint="cbn-cli-hub-that-does-not-exist")
        status = hub.status()
        self.assertEqual(status["plugin_id"], "cli-anything")
        self.assertFalse(status["entrypoint_available"])
        self.assertIsNone(status["entrypoint_path"])

    def test_market_command_handles_missing_cli_hub_without_failing(self):
        hub = CliAnythingHub(entrypoint="cbn-cli-hub-that-does-not-exist")
        result = hub.list_market()
        self.assertEqual(result.exit_code, 127)
        self.assertIn("not installed", result.stderr)

    def test_manifest_for_harness_uses_stdio_launch_boundary(self):
        manifest = CliAnythingHub().manifest_for_harness("gimp")
        self.assertEqual(manifest["metadata"]["id"], "cli-anything.gimp.launch")
        self.assertEqual(manifest["metadata"]["labels"]["plugin"], "cli-anything")
        self.assertEqual(manifest["spec"]["transport"]["kind"], "stdio")
        self.assertEqual(manifest["spec"]["transport"]["argsTemplate"], ["launch", "gimp"])
        self.assertFalse(manifest["spec"]["output"]["verified"])

    def test_harness_plan_uses_cli_hub_lifecycle_command(self):
        plan = CliAnythingHub().harness_plan("install", "gimp")
        self.assertEqual(plan.plugin_id, "cli-anything")
        self.assertEqual(plan.action, "harness-install-gimp")
        self.assertEqual(plan.commands[0].argv, ("cli-hub", "install", "gimp"))

    def test_cli_harness_plan_does_not_execute_without_yes(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "plugin",
                "harness",
                "cli-anything",
                "install",
                "gimp",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(proc.returncode, 2)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["plugin_id"], "cli-anything")
        self.assertEqual(payload["commands"][0]["argv"], ["cli-hub", "install", "gimp"])

    def test_write_harness_manifest_writes_utf8_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hub = CliAnythingHub(root=root)
            path = hub.write_harness_manifest("GIMP")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(path.name, "cli-anything.gimp.launch.json")
            self.assertEqual(payload["metadata"]["id"], "cli-anything.gimp.launch")

    def test_cli_import_harness_prints_manifest_without_writing(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn", "plugin", "import-harness", "cli-anything", "gimp"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["metadata"]["id"], "cli-anything.gimp.launch")
        self.assertEqual(payload["spec"]["transport"]["argsTemplate"], ["launch", "gimp"])


if __name__ == "__main__":
    unittest.main()
