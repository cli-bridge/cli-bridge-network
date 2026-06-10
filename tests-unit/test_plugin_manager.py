import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_cli_anything_operation_catalog_exposes_provider_abi(self):
        result = PluginManager().operation_catalog("cli-anything")
        self.assertEqual(result["kind"], "PluginProviderOperationCatalog")
        self.assertEqual(result["plugin_api_version"], "cbn.plugin.v1")
        self.assertEqual(result["provider"], "cli-anything")
        self.assertTrue(result["validation"]["ok"])
        operation_ids = {operation["id"] for operation in result["operations"]}
        self.assertIn("install-gate", operation_ids)
        self.assertIn("adaptation-queue", operation_ids)
        self.assertIn("repair-entrypoint", operation_ids)
        repair = next(operation for operation in result["operations"] if operation["id"] == "repair-entrypoint")
        self.assertEqual(repair["kind"], "write")
        self.assertTrue(repair["requires_confirmation"])
        self.assertIn("runtime/manifests", repair["side_effects"])
        self.assertEqual(repair["required_inputs"], ["harness", "module"])
        self.assertEqual(repair["input_schema"]["harness"], "string")
        self.assertEqual(repair["input_schema"]["module"], "string")
        self.assertGreater(result["summary"]["by_kind"]["gate"], 0)
        self.assertGreater(result["summary"]["write_or_execute_count"], 0)

    def test_validate_operation_catalog_reports_safe_provider_contract(self):
        result = PluginManager().validate_operation_catalog("cli-anything")
        self.assertTrue(result["ok"])
        self.assertEqual(result["kind"], "PluginProviderOperationCatalogValidation")
        self.assertEqual(result["summary"]["error_count"], 0)
        self.assertGreater(result["summary"]["operation_count"], 0)

    def test_validate_operation_catalog_blocks_unsafe_execute_descriptor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_example_plugin_manifest(root, unsafe_execute=True)

            result = PluginManager(root=root).validate_operation_catalog("example")

        self.assertFalse(result["ok"])
        self.assertGreater(result["summary"]["error_count"], 0)
        self.assertTrue(
            any("requires_confirmation must be true" in error for error in result["errors"])
        )
        self.assertTrue(
            any("side_effects must be non-empty" in error for error in result["errors"])
        )

    def test_validate_operation_catalog_reports_invalid_input_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_example_plugin_manifest(root, invalid_input_schema=True)

            result = PluginManager(root=root).validate_operation_catalog("example")

        self.assertFalse(result["ok"])
        self.assertTrue(any("input_schema must be an object" in error for error in result["errors"]))

    def test_operation_plan_resolves_read_only_descriptor(self):
        result = PluginManager().operation_plan("cli-anything", "candidates")
        self.assertTrue(result["ok"])
        self.assertTrue(result["dispatch_ready"])
        self.assertEqual(result["operation_kind"], "report")
        self.assertEqual(result["api_request"]["path"], "/plugins/cli-anything/candidates")
        self.assertEqual(result["api_request"]["json"]["query"], "file")
        self.assertIn("plugin candidates cli-anything", result["resolved_command"])

    def test_operation_plan_blocks_side_effect_without_confirmation(self):
        result = PluginManager().operation_plan(
            "cli-anything",
            "repair-entrypoint",
            inputs={"harness": "py4csr", "module": "py4csr.tables.rtf_formatter"},
        )
        self.assertFalse(result["ok"])
        self.assertFalse(result["dispatch_ready"])
        self.assertIn("operation requires confirmed=true before dispatch", result["blockers"])
        self.assertEqual(result["required_inputs"], ["harness", "module"])
        self.assertEqual(result["missing_inputs"], [])
        self.assertEqual(result["resolved_payload"]["harness_name"], "py4csr")
        self.assertEqual(result["resolved_payload"]["module"], "py4csr.tables.rtf_formatter")

    def test_operation_plan_resolves_confirmed_side_effect_descriptor(self):
        result = PluginManager().operation_plan(
            "cli-anything",
            "repair-entrypoint",
            inputs={"harness": "py4csr", "module": "py4csr.tables.rtf_formatter"},
            confirmed=True,
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["dispatch_ready"])
        self.assertEqual(result["operation_kind"], "write")
        self.assertEqual(result["api_request"]["method"], "POST")
        self.assertTrue(result["api_request"]["json"]["confirmed"])
        self.assertIn("py4csr.tables.rtf_formatter", result["resolved_command"])

    def test_operation_plan_reports_missing_inputs(self):
        result = PluginManager().operation_plan("cli-anything", "adapter-smoke", inputs={"harness": "py4csr"})
        self.assertFalse(result["ok"])
        self.assertIn("missing input: module", result["blockers"])
        self.assertEqual(result["required_inputs"], ["harness", "module"])
        self.assertEqual(result["missing_inputs"], ["module"])

    def test_operation_catalog_supports_manifest_declared_fake_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_example_plugin_manifest(root)

            result = PluginManager(root=root).operation_catalog("example")

        self.assertEqual(result["provider"], "fake")
        operation_ids = {operation["id"] for operation in result["operations"]}
        self.assertIn("fake-report", operation_ids)
        self.assertIn("install-plan", operation_ids)
        fake = next(operation for operation in result["operations"] if operation["id"] == "fake-report")
        self.assertEqual(fake["kind"], "report")
        self.assertEqual(fake["api"]["path"], "/plugins/example/fake-report")
        self.assertEqual(fake["required_inputs"], [])
        self.assertNotIn("adaptation-queue", operation_ids)

    def test_cli_operations_command_outputs_catalog(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn", "plugin", "operations", "cli-anything"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["kind"], "PluginProviderOperationCatalog")
        self.assertEqual(payload["plugin_id"], "cli-anything")
        self.assertTrue(payload["operations"])

    def test_cli_validate_operations_command_outputs_report(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn", "plugin", "validate-operations", "cli-anything"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["kind"], "PluginProviderOperationCatalogValidation")
        self.assertEqual(payload["summary"]["error_count"], 0)

    def test_cli_operation_plan_command_outputs_resolved_plan(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "plugin",
                "operation-plan",
                "cli-anything",
                "repair-entrypoint",
                "--input",
                "harness=py4csr",
                "--input",
                "module=py4csr.tables.rtf_formatter",
                "--yes",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["kind"], "PluginProviderOperationPlan")
        self.assertTrue(payload["dispatch_ready"])
        self.assertEqual(payload["required_inputs"], ["harness", "module"])
        self.assertEqual(payload["missing_inputs"], [])
        self.assertTrue(payload["resolved_payload"]["confirmed"])

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

    def test_update_check_reports_not_downloaded_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_example_plugin_manifest(root)

            result = PluginManager(root=root).update_check("example")
            self.assertFalse(result["ready_for_update"])
            self.assertFalse(result["source_downloaded"])
            self.assertIn("plugin source repository is not downloaded", result["blockers"])
            self.assertFalse(result["repository"]["remote_probe"]["requested"])

    def test_update_check_compares_remote_head_when_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_example_plugin_manifest(root)
            provenance = {
                "plugin_id": "example",
                "title": "Example",
                "installed": True,
                "repo_dir": str(root / "external_plugins" / "example" / "repo"),
                "source_downloaded": True,
                "source_trusted": True,
                "repository": {
                    "exists": True,
                    "is_git": True,
                    "remote_url": "https://example.com/example.git",
                    "remote_matches_expected": True,
                    "branch": "main",
                    "head": "local-head",
                    "dirty": False,
                },
                "pip_packages": [],
                "entrypoints": [],
                "warnings": [],
            }

            with patch.object(PluginManager, "provenance", return_value=provenance), patch(
                "cbn_plugins.manager._run_command",
                return_value={"exit_code": 0, "stdout": "remote-head\tHEAD\n", "stderr": ""},
            ):
                result = PluginManager(root=root).update_check("example", remote=True)

            self.assertTrue(result["ready_for_update"])
            self.assertTrue(result["repository"]["remote_probe"]["checked"])
            self.assertEqual(result["repository"]["remote_probe"]["head"], "remote-head")
            self.assertTrue(result["repository"]["update_available"])

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

    def test_cli_check_update_command_outputs_json(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn", "plugin", "check-update", "cli-anything"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertIn(proc.returncode, {0, 13})
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["plugin_id"], "cli-anything")
        self.assertIn("ready_for_update", payload)
        self.assertIn("repository", payload)
        self.assertFalse(payload["repository"]["remote_probe"]["requested"])

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

    def test_runtime_transport_status_reports_pty_backend(self):
        result = PluginManager().runtime_transport_status("pty")
        self.assertEqual(result["kind"], "pty")
        self.assertIn("backend", result)
        self.assertIn("available", result)
        self.assertEqual(result["ready"], result["available"])
        self.assertIn("next_commands", result)

    def test_runtime_transport_plan_installs_pywinpty_on_missing_windows_backend(self):
        with patch(
            "cbn_plugins.manager.pty_backend_status",
            return_value={
                "kind": "pty",
                "platform": "win32",
                "backend": "pywinpty",
                "available": False,
                "install_hint": "pip install cli-bridge-network[pty]",
            },
        ), patch("cbn_plugins.manager.os.name", "nt"):
            plan = PluginManager().runtime_transport_plan("pty")

        payload = plan.as_dict()
        self.assertEqual(payload["plugin_id"], "runtime.pty")
        self.assertEqual(payload["action"], "install-runtime-pty")
        self.assertTrue(payload["requires_confirmation"])
        self.assertEqual(payload["commands"][0]["argv"][-1], "pywinpty>=2.0")

    def test_cli_runtime_transport_status_outputs_json(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn", "runtime", "transport", "pty"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertIn(proc.returncode, {0, 5})
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["kind"], "pty")
        self.assertIn("ready", payload)

    def test_cli_runtime_transport_install_without_yes_returns_plan(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn", "runtime", "transport", "pty", "--install"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(proc.returncode, 2)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["plugin_id"], "runtime.pty")
        self.assertTrue(payload["requires_confirmation"])

def write_example_plugin_manifest(
    root: Path,
    unsafe_execute: bool = False,
    invalid_input_schema: bool = False,
) -> None:
    registry = root / "plugins" / "registry"
    registry.mkdir(parents=True)
    operations = [
        {
            "id": "fake-report",
            "title": "Fake Report",
            "kind": "report",
            "command": "python -m cbn plugin fake-report example",
            "api": {"method": "GET", "path": "/plugins/example/fake-report"},
            "input_schema": [] if invalid_input_schema else {},
        }
    ]
    if unsafe_execute:
        operations.append(
            {
                "id": "unsafe-execute",
                "title": "Unsafe Execute",
                "kind": "execute",
                "command": "python -m cbn plugin unsafe example",
                "api": {"method": "POST", "path": "/plugins/example/unsafe"},
                "requires_confirmation": False,
                "side_effects": [],
            }
        )
    (registry / "example.json").write_text(
        json.dumps(
            {
                "id": "example",
                "plugin_api_version": "cbn.plugin.v1",
                "provider": "fake",
                "title": "Example",
                "description": "Example plugin",
                "source": {"repository": "https://example.com/example.git"},
                "install": {"pip_packages": [], "modes": ["fake"]},
                "entrypoints": [],
                "permissions": ["fake.read"],
                "operations": operations,
            }
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
