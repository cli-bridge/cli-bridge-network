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

    def test_harness_status_handles_missing_cli_hub(self):
        hub = CliAnythingHub(entrypoint="cbn-cli-hub-that-does-not-exist")
        status = hub.harness_status("gimp")
        self.assertFalse(status["cli_hub_available"])
        self.assertFalse(status["installed"])
        self.assertFalse(status["launch_ready"])

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

    def test_harness_status_reports_entrypoint_and_manifest(self):
        class FakeHub(CliAnythingHub):
            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout=f"Entry point: {sys.executable}\nStatus: installed\n",
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_MARKET_RECORD],
                )

        with tempfile.TemporaryDirectory() as tmp:
            hub = FakeHub(root=Path(tmp))
            hub.write_harness_manifest("gimp", market_record=SAMPLE_MARKET_RECORD)
            status = hub.harness_status("gimp", from_market=True)
            self.assertTrue(status["installed"])
            self.assertTrue(status["launch_ready"])
            self.assertTrue(status["manifest_imported"])
            self.assertTrue(status["entrypoint_available"])
            self.assertTrue(status["market_record_available"])

    def test_adapt_harness_previews_manifest_status_and_next_commands(self):
        class FakeHub(CliAnythingHub):
            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout="Entry point: cli-anything-gimp\nStatus: not installed\n",
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_MARKET_RECORD],
                )

        with tempfile.TemporaryDirectory() as tmp:
            result = FakeHub(root=Path(tmp)).adapt_harness("gimp", from_market=True)
            self.assertTrue(result["ok"])
            self.assertFalse(result["write"])
            self.assertIsNone(result["written"])
            self.assertTrue(result["market_record_available"])
            self.assertEqual(result["manifest"]["metadata"]["id"], "cli-anything.gimp.launch")
            self.assertFalse(result["status"]["manifest_imported"])
            self.assertIn("python -m cbn call cli-anything.gimp.launch --dry-run", result["next_commands"])

    def test_adapt_harness_write_imports_manifest(self):
        class FakeHub(CliAnythingHub):
            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout=f"Entry point: {sys.executable}\nStatus: installed\n",
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_MARKET_RECORD],
                )

        with tempfile.TemporaryDirectory() as tmp:
            result = FakeHub(root=Path(tmp)).adapt_harness("gimp", from_market=True, write=True)
            self.assertTrue(result["ok"])
            self.assertTrue(result["write"])
            self.assertTrue(Path(result["written"]).exists())
            self.assertTrue(result["status"]["manifest_imported"])

    def test_sync_market_previews_multiple_harness_manifests(self):
        class FakeHub(CliAnythingHub):
            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json={"items": [SAMPLE_MARKET_RECORD, {"display_name": "ffmpeg", "category": "video"}]},
                )

        with tempfile.TemporaryDirectory() as tmp:
            result = FakeHub(root=Path(tmp)).sync_market(query="image", limit=10)
            self.assertTrue(result["ok"])
            self.assertFalse(result["write"])
            self.assertEqual(result["market_count"], 2)
            self.assertEqual(result["importable_count"], 2)
            ids = [item["capability_id"] for item in result["manifests"]]
            self.assertEqual(ids, ["cli-anything.gimp.launch", "cli-anything.ffmpeg.launch"])
            self.assertFalse(Path(result["manifests"][0]["manifest_path"]).exists())

    def test_sync_market_write_imports_bounded_manifests(self):
        class FakeHub(CliAnythingHub):
            def list_market(self) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "list", "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[
                        SAMPLE_MARKET_RECORD,
                        {"name": "imagemagick", "display_name": "ImageMagick", "category": "image"},
                    ],
                )

        with tempfile.TemporaryDirectory() as tmp:
            result = FakeHub(root=Path(tmp)).sync_market(limit=1, write=True)
            self.assertTrue(result["ok"])
            self.assertTrue(result["write"])
            self.assertEqual(result["selected_count"], 1)
            written = Path(result["manifests"][0]["written"])
            self.assertTrue(written.exists())
            payload = json.loads(written.read_text(encoding="utf-8"))
            self.assertEqual(payload["metadata"]["id"], "cli-anything.gimp.launch")

    def test_sync_market_reports_unsupported_json_shape(self):
        class FakeHub(CliAnythingHub):
            def list_market(self) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "list", "--json"),
                    exit_code=0,
                    stdout="{}",
                    stderr="",
                    parsed_json={"unexpected": []},
                )

        result = FakeHub().sync_market()
        self.assertFalse(result["ok"])
        self.assertIn("supported JSON list shape", result["error"])

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

        uninstall = CliAnythingHub().harness_plan("uninstall", "gimp")
        self.assertEqual(uninstall.action, "harness-uninstall-gimp")
        self.assertEqual(uninstall.commands[0].argv, ("cli-hub", "uninstall", "gimp"))

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

    def test_cli_harness_uninstall_plan_does_not_execute_without_yes(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "plugin",
                "harness",
                "cli-anything",
                "uninstall",
                "gimp",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(proc.returncode, 2)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["action"], "harness-uninstall-gimp")
        self.assertEqual(payload["commands"][0]["argv"], ["cli-hub", "uninstall", "gimp"])

    def test_cli_harness_status_outputs_json(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "plugin",
                "harness",
                "cli-anything",
                "status",
                "gimp",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["plugin_id"], "cli-anything")
        self.assertEqual(payload["harness_name"], "gimp")
        self.assertIn("launch_ready", payload)

    def test_cli_adapt_harness_outputs_adaptation_report(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "plugin",
                "adapt-harness",
                "cli-anything",
                "gimp",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["manifest"]["metadata"]["id"], "cli-anything.gimp.launch")
        self.assertFalse(payload["write"])
        self.assertIn("next_commands", payload)

    def test_cli_sync_market_handles_missing_cli_hub_without_crashing(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "plugin",
                "sync-market",
                "cli-anything",
                "--query",
                "image",
                "--limit",
                "5",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertIn(proc.returncode, {0, 6})
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["plugin_id"], "cli-anything")
        self.assertIn("manifests", payload)

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
