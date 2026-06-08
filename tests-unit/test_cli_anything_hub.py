import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cbn_core.manifest import CapabilityManifest
from cbn_plugins.cli_anything import CliAnythingHub, CliHubCommandResult, sanitize_harness_name


SAMPLE_MARKET_RECORD = {
    "name": "gimp",
    "display_name": "GIMP",
    "version": "1.0.0",
    "description": "Raster image processing via gimp -i -b (batch mode)",
    "requires": "gimp (apt install gimp)",
    "homepage": "https://www.gimp.org",
    "install_cmd": "pip install git+https://github.com/HKUDS/CLI-Anything.git#subdirectory=gimp/agent-harness",
    "entry_point": "cli-anything-gimp",
    "skill_md": "skills/cli-anything-gimp/SKILL.md",
    "category": "image",
    "contributors": [{"name": "CLI-Anything-Team", "url": "https://github.com/HKUDS/CLI-Anything"}],
    "_source": "harness",
}


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

    def test_market_record_lookup_handles_missing_cli_hub(self):
        hub = CliAnythingHub(entrypoint="cbn-cli-hub-that-does-not-exist")
        self.assertIsNone(hub.market_record_for_harness("gimp"))

    def test_market_record_lookup_skips_bad_market_records(self):
        class FakeHub(CliAnythingHub):
            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[{"name": ""}, SAMPLE_MARKET_RECORD],
                )

        self.assertEqual(FakeHub().market_record_for_harness("gimp")["name"], "gimp")

    def test_manifest_for_harness_uses_stdio_launch_boundary(self):
        manifest = CliAnythingHub().manifest_for_harness("gimp")
        self.assertEqual(manifest["metadata"]["id"], "cli-anything.gimp.launch")
        self.assertEqual(manifest["metadata"]["labels"]["plugin"], "cli-anything")
        self.assertEqual(manifest["spec"]["transport"]["kind"], "stdio")
        self.assertEqual(manifest["spec"]["transport"]["argsTemplate"], ["launch", "gimp"])
        self.assertFalse(manifest["spec"]["output"]["verified"])

    def test_manifest_ir_preserves_harness_labels(self):
        manifest = CapabilityManifest.from_dict(CliAnythingHub().manifest_for_harness("gimp"))
        self.assertEqual(manifest.labels["plugin"], "cli-anything")
        self.assertEqual(manifest.labels["harness"], "gimp")
        self.assertEqual(manifest.as_record()["labels"]["harness"], "gimp")

    def test_manifest_for_harness_keeps_market_metadata(self):
        manifest = CliAnythingHub().manifest_for_harness("gimp", market_record=SAMPLE_MARKET_RECORD)
        metadata = manifest["metadata"]
        self.assertEqual(metadata["title"], "CLI-Anything GIMP")
        self.assertEqual(metadata["labels"]["category"], "image")
        self.assertEqual(metadata["labels"]["source"], "harness")
        self.assertEqual(metadata["annotations"]["cli-anything.version"], "1.0.0")
        self.assertEqual(metadata["annotations"]["cli-anything.entry_point"], "cli-anything-gimp")
        self.assertIn("CLI-Anything-Team", metadata["annotations"]["cli-anything.contributors"])

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
