import json
import subprocess
import sys
import unittest

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


if __name__ == "__main__":
    unittest.main()
