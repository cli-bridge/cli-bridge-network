import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cbn_core.manifest import CapabilityManifest
from cbn_plugins.cli_anything import (
    CliAnythingHub,
    CliHubCommandResult,
    infer_market_policy,
    sanitize_harness_name,
)


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

SAMPLE_MERMAID_RECORD = {
    "name": "mermaid",
    "display_name": "Mermaid",
    "version": "1.0.0",
    "description": "Mermaid Live Editor state files and renderer URLs",
    "requires": None,
    "homepage": "https://mermaid.js.org",
    "install_cmd": "pip install git+https://github.com/HKUDS/CLI-Anything.git#subdirectory=mermaid/agent-harness",
    "entry_point": "cli-anything-mermaid",
    "category": "diagrams",
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
            self.assertTrue(result["validation"]["valid"])
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

    def test_prepare_harness_returns_gates_and_lifecycle_plans(self):
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
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_MARKET_RECORD],
                )

        with tempfile.TemporaryDirectory() as tmp:
            result = FakeHub(root=Path(tmp)).prepare_harness("gimp", from_market=True)
            self.assertTrue(result["ok"])
            self.assertTrue(result["gates"]["manifest_valid"])
            self.assertTrue(result["gates"]["market_required_satisfied"])
            self.assertTrue(result["gates"]["launch_ready"])
            self.assertEqual(result["plans"]["install"]["commands"][0]["argv"], ["cli-hub", "install", "gimp"])
            self.assertEqual(result["plans"]["launch"]["commands"][0]["argv"], ["cli-hub", "launch", "gimp"])

    def test_prepare_harness_reports_missing_required_market_record(self):
        class FakeHub(CliAnythingHub):
            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[],
                )

        result = FakeHub().prepare_harness("missing", from_market=True)
        self.assertFalse(result["ok"])
        self.assertIn("market record not found", result["error"])

    def test_evaluate_harness_recommends_low_dependency_market_candidate(self):
        class FakeHub(CliAnythingHub):
            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout="Entry point: cli-anything-mermaid\nRequires: nothing\nStatus: not installed\n",
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_MERMAID_RECORD],
                )

        with tempfile.TemporaryDirectory() as tmp:
            result = FakeHub(root=Path(tmp)).evaluate_harness("mermaid", from_market=True)
            self.assertTrue(result["ok"])
            self.assertTrue(result["install_candidate"])
            self.assertEqual(result["recommended_next_action"], "write_manifest")
            self.assertTrue(result["gates"]["external_dependency_free"])
            self.assertTrue(result["gates"]["low_policy_risk"])
            self.assertFalse(result["gates"]["installed"])
            self.assertEqual(result["requirements"]["signals"], [])
            self.assertEqual(result["capability_id"], "cli-anything.mermaid.launch")

    def test_evaluate_harness_blocks_account_or_token_requirements(self):
        class FakeHub(CliAnythingHub):
            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout="Entry point: generate-veo\nRequires: GOOGLE_CLOUD_PROJECT and API key\nStatus: not installed\n",
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[
                        {
                            "name": "generate-veo-video",
                            "display_name": "Generate Veo Video",
                            "description": "Generate videos with Google Veo via Vertex AI and Gemini",
                            "requires": "GOOGLE_CLOUD_PROJECT env var and GEMINI_API_KEY optional",
                            "entry_point": "generate-veo",
                        }
                    ],
                )

        result = FakeHub().evaluate_harness("generate-veo-video", from_market=True)
        self.assertTrue(result["ok"])
        self.assertFalse(result["install_candidate"])
        self.assertFalse(result["gates"]["external_dependency_free"])
        self.assertFalse(result["gates"]["low_policy_risk"])
        self.assertIn("policy requires elevated confirmation", result["blockers"])
        self.assertIn("declared requirements need external app, account, token, or service", result["blockers"])

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
            self.assertTrue(all(item["validation"]["valid"] for item in result["manifests"]))
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

    def test_sync_market_reports_capability_id_collisions_without_writing(self):
        class FakeHub(CliAnythingHub):
            def list_market(self) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "list", "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[
                        {"name": "gimp", "display_name": "GIMP", "_source": "harness"},
                        {"name": "GIMP!", "display_name": "GIMP duplicate", "_source": "public"},
                    ],
                )

        with tempfile.TemporaryDirectory() as tmp:
            result = FakeHub(root=Path(tmp)).sync_market(write=True)
            self.assertFalse(result["ok"])
            self.assertTrue(result["write"])
            self.assertEqual(result["conflict_count"], 2)
            self.assertEqual(result["failed_count"], 2)
            self.assertEqual(result["importable_count"], 0)
            self.assertFalse((Path(tmp) / "manifests" / "cli-anything.gimp.launch.json").exists())
            errors = {item["error"] for item in result["manifests"]}
            self.assertEqual(errors, {"duplicate capability_id generated from market records"})
            collision = result["manifests"][0]["collision"]
            self.assertEqual(collision["capability_id"], "cli-anything.gimp.launch")
            self.assertEqual(len(collision["market_records"]), 2)

    def test_sync_market_writes_only_non_colliding_valid_manifests(self):
        class FakeHub(CliAnythingHub):
            def list_market(self) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "list", "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[
                        {"name": "gimp", "display_name": "GIMP", "_source": "harness"},
                        {"name": "GIMP!", "display_name": "GIMP duplicate", "_source": "public"},
                        {"name": "inkscape", "display_name": "Inkscape", "_source": "harness"},
                    ],
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = FakeHub(root=root).sync_market(write=True)
            self.assertFalse(result["ok"])
            self.assertEqual(result["conflict_count"], 2)
            self.assertEqual(result["failed_count"], 2)
            self.assertEqual(result["importable_count"], 1)
            self.assertFalse((root / "manifests" / "cli-anything.gimp.launch.json").exists())
            self.assertTrue((root / "manifests" / "cli-anything.inkscape.launch.json").exists())

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
        self.assertEqual(manifest["spec"]["transport"]["argsTemplate"], ["launch", "gimp", "--"])
        self.assertEqual(manifest["spec"]["transport"]["timeoutSeconds"], 600)
        self.assertFalse(manifest["spec"]["output"]["verified"])

    def test_manifest_for_harness_infers_write_workspace_policy(self):
        manifest = CliAnythingHub().manifest_for_harness("gimp", market_record=SAMPLE_MARKET_RECORD)
        self.assertEqual(manifest["spec"]["policy"]["risk"], "write-workspace")
        self.assertFalse(manifest["spec"]["policy"]["requiresConfirmation"])
        self.assertEqual(manifest["spec"]["policy"]["network"], "deny")
        self.assertIn("cli-anything.policy_inference", manifest["metadata"]["annotations"])

    def test_manifest_for_harness_infers_external_network_policy(self):
        market_record = {
            "name": "generate-veo-video",
            "display_name": "Generate Veo Video",
            "description": "Generate videos with Google Veo via Vertex AI and Gemini",
            "requires": "GOOGLE_CLOUD_PROJECT env var and GEMINI_API_KEY optional",
            "entry_point": "generate-veo",
            "_source": "public",
        }
        manifest = CliAnythingHub().manifest_for_harness(
            "generate-veo-video",
            market_record=market_record,
        )
        policy = manifest["spec"]["policy"]
        self.assertEqual(policy["risk"], "external-network")
        self.assertTrue(policy["requiresConfirmation"])
        self.assertEqual(policy["network"], "requires-confirmation")

    def test_manifest_for_harness_keeps_local_service_policy_local(self):
        market_record = {
            "name": "comfyui",
            "display_name": "ComfyUI",
            "description": "AI image generation workflow management via ComfyUI REST API",
            "requires": "ComfyUI running at http://localhost:8188",
            "entry_point": "cli-anything-comfyui",
        }
        manifest = CliAnythingHub().manifest_for_harness("comfyui", market_record=market_record)
        policy = manifest["spec"]["policy"]
        self.assertEqual(policy["risk"], "write-workspace")
        self.assertFalse(policy["requiresConfirmation"])
        self.assertEqual(policy["network"], "localhost")

    def test_infer_market_policy_only_escalates_risk(self):
        policy = infer_market_policy(SAMPLE_MARKET_RECORD, requested_risk="privileged")
        self.assertEqual(policy["risk"], "privileged")
        self.assertTrue(policy["requires_confirmation"])

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

    def test_cli_prepare_harness_outputs_preparation_report(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "plugin",
                "prepare-harness",
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
        self.assertEqual(payload["plugin_id"], "cli-anything")
        self.assertEqual(payload["harness_name"], "gimp")
        self.assertTrue(payload["gates"]["manifest_valid"])
        self.assertIn("install", payload["plans"])

    def test_cli_evaluate_harness_outputs_candidate_report(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "plugin",
                "evaluate-harness",
                "cli-anything",
                "mermaid",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertIn(proc.returncode, {0, 6})
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["plugin_id"], "cli-anything")
        self.assertEqual(payload["harness_name"], "mermaid")
        self.assertIn("install_candidate", payload)
        self.assertIn("recommended_next_action", payload)

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
        self.assertEqual(payload["spec"]["transport"]["argsTemplate"], ["launch", "gimp", "--"])


if __name__ == "__main__":
    unittest.main()
