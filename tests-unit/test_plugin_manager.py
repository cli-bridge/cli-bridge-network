import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cbn_plugins.manager import PluginManager


class PluginManagerTests(unittest.TestCase):
    def test_cli_anything_manifest_is_listed(self):
        plugins = PluginManager().list_plugins()
        plugin_ids = {plugin["id"] for plugin in plugins}
        self.assertIn("cli-anything", plugin_ids)

    def test_install_plan_does_not_execute_without_yes(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn", "plugin", "install", "cli-anything"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(proc.returncode, 2)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["requires_confirmation"])
        self.assertEqual(payload["action"], "install")
        self.assertIn("cli-anything", payload["plugin_dir"])

    def test_update_plan_uses_git_pull(self):
        plan = PluginManager().plan("cli-anything", action="update")
        commands = [command.as_dict() for command in plan.commands]
        self.assertTrue(any(command["argv"][0] == "git" for command in commands))
        self.assertTrue(any("pull" in command["argv"] for command in commands))

    def test_cli_anything_preflight_reports_required_checks(self):
        result = PluginManager().preflight("cli-anything")
        check_ids = {check["check_id"] for check in result["checks"]}
        self.assertEqual(result["plugin_id"], "cli-anything")
        self.assertIn("python.runtime", check_ids)
        self.assertIn("python.pip", check_ids)
        self.assertIn("executable.git", check_ids)
        self.assertIn("external_plugins.writable", check_ids)
        self.assertIn("plugin.entrypoints", check_ids)
        self.assertTrue(all(check["severity"] in {"error", "warning"} for check in result["checks"]))

    def test_provenance_reports_source_package_and_entrypoint_fields(self):
        result = PluginManager().provenance("cli-anything")
        self.assertEqual(result["plugin_id"], "cli-anything")
        self.assertIn("repository", result)
        self.assertIn("pip_packages", result)
        self.assertIn("entrypoints", result)
        self.assertIn("ready_for_cli_hub", result)
        self.assertIn("source_downloaded", result)
        self.assertIn("next_commands", result)

    def test_provenance_handles_not_downloaded_plugin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_example_plugin_manifest(root)

            result = PluginManager(root=root).provenance("example")
            self.assertFalse(result["source_downloaded"])
            self.assertIsNone(result["source_trusted"])
            self.assertFalse(result["repository"]["exists"])
            self.assertEqual(result["pip_packages"], [])
            self.assertEqual(result["entrypoints"], [])
            self.assertEqual(result["blockers"], [])

    def test_operation_gate_allows_clean_install_before_source_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_example_plugin_manifest(root)

            gate = PluginManager(root=root).operation_gate("example", "install")
            self.assertTrue(gate["ok"])
            self.assertEqual(gate["blockers"], [])
            self.assertFalse(gate["provenance"]["source_downloaded"])

    def test_operation_gate_blocks_update_without_downloaded_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_example_plugin_manifest(root)

            gate = PluginManager(root=root).operation_gate("example", "update")
            self.assertFalse(gate["ok"])
            self.assertIn("plugin source repository is not downloaded", gate["blockers"])
            self.assertIn("preflight", gate)
            self.assertIn("provenance", gate)

    def test_operation_gate_blocks_install_when_error_preflight_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_example_plugin_manifest(root)
            (root / "external_plugins").write_text("not a directory", encoding="utf-8")

            gate = PluginManager(root=root).operation_gate("example", "install")
            self.assertFalse(gate["ok"])
            self.assertIn("preflight failed: external_plugins.writable", gate["blockers"])
            self.assertEqual(gate["override_flag"], "--allow-failed-preflight")

    def test_cli_preflight_command_outputs_json(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn", "plugin", "preflight", "cli-anything"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertIn(proc.returncode, {0, 5})
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["plugin_id"], "cli-anything")
        self.assertTrue(payload["checks"])

    def test_cli_provenance_command_outputs_json(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn", "plugin", "provenance", "cli-anything"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["plugin_id"], "cli-anything")
        self.assertIn("repository", payload)
        self.assertIn("entrypoints", payload)

    def test_cli_gate_command_outputs_json(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn", "plugin", "gate", "cli-anything", "--action", "install"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertIn(proc.returncode, {0, 13})
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["plugin_id"], "cli-anything")
        self.assertEqual(payload["action"], "install")
        self.assertTrue(payload["gated"])
        self.assertIn("preflight", payload)
        self.assertIn("provenance", payload)

def write_example_plugin_manifest(root: Path) -> None:
    registry = root / "plugins" / "registry"
    registry.mkdir(parents=True)
    (registry / "example.json").write_text(
        json.dumps(
            {
                "id": "example",
                "title": "Example",
                "description": "Example plugin",
                "source": {"repository": "https://example.com/example.git"},
                "install": {"pip_packages": []},
                "entrypoints": [],
            }
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
