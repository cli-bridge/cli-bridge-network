import unittest
from pathlib import Path

from cbn_plugins.cli_anything_parts.repair import (
    entrypoint_diagnosis,
    entrypoint_package_candidates,
    entrypoint_wrapper_path,
    manifest_policy_from_recheck,
    normalize_package_candidate,
    packages_from_install_command,
    python_module_wrapper_content,
    repair_policy_network,
)


class CliAnythingRepairTests(unittest.TestCase):
    def test_entrypoint_package_candidates_preserves_stable_order_and_skips_urls(self):
        candidates = entrypoint_package_candidates(
            "fallback-tool",
            {
                "name": "gimp",
                "pip_package": "gimp[extra]>=1.0",
                "install_cmd": "pip install --upgrade git+https://example.invalid/repo gimp-tools",
            },
            {
                "cli_hub_info": {
                    "fields": {
                        "install_cmd": "uv pip install fallback-tool another_tool",
                    }
                }
            },
        )

        self.assertEqual(candidates, ["gimp", "gimp-tools", "fallback-tool", "another_tool"])

    def test_install_command_parser_and_candidate_normalizer(self):
        self.assertEqual(
            packages_from_install_command("pip install --upgrade foo bar"),
            ["foo", "bar"],
        )
        self.assertEqual(normalize_package_candidate("foo[dev]>=1.0"), "foo")
        self.assertIsNone(normalize_package_candidate("git+https://example.invalid/foo"))
        self.assertIsNone(normalize_package_candidate("../unsafe"))

    def test_entrypoint_diagnosis_detects_installed_missing_entrypoint(self):
        result = entrypoint_diagnosis(
            entry_point="missing-tool",
            entrypoint_path=None,
            script_candidates=[],
            distribution_reports=[
                {
                    "package": "missing-tool",
                    "installed": True,
                    "console_scripts": [{"name": "other-tool", "value": "pkg:main"}],
                }
            ],
            module_reports=[{"package": "missing_tool", "importable": True, "module_main": True}],
            evaluation={"gates": {"installed": True, "entrypoint_available": False}},
        )

        self.assertEqual(result["state"], "installed_entrypoint_missing")
        self.assertTrue(result["repair_required"])
        self.assertEqual(
            result["recommended_next_action"],
            "repair_market_metadata_or_create_entrypoint_wrapper",
        )
        self.assertIn("installed package has no matching console_script", result["findings"])
        self.assertIn("package exposes a python -m module entry", result["findings"])

    def test_entrypoint_diagnosis_reports_available_entrypoint(self):
        result = entrypoint_diagnosis(
            entry_point="tool",
            entrypoint_path="C:/bin/tool.exe",
            script_candidates=[],
            distribution_reports=[],
            module_reports=[],
            evaluation={},
        )

        self.assertFalse(result["repair_required"])
        self.assertEqual(result["state"], "entrypoint_available")

    def test_wrapper_path_and_content_are_project_local(self):
        path = entrypoint_wrapper_path(Path("external_plugins"), "Tool Name", safe_name="tool-name")
        content = python_module_wrapper_content("pip")

        self.assertEqual(path, Path("external_plugins") / "cli-anything" / "entrypoints" / "tool-name.py")
        self.assertIn("MODULE = 'pip'", content)
        self.assertIn("runpy.run_module(MODULE, run_name=\"__main__\", alter_sys=True)", content)

    def test_repair_policy_network_and_manifest_policy_mapping(self):
        self.assertEqual(repair_policy_network("deny", "localhost"), "localhost")
        self.assertEqual(repair_policy_network("localhost", "requires-confirmation"), "requires-confirmation")
        self.assertEqual(repair_policy_network("", ""), "deny")
        self.assertEqual(
            manifest_policy_from_recheck(
                {
                    "risk": "external-network",
                    "requires_confirmation": True,
                    "network": "requires-confirmation",
                }
            ),
            {
                "risk": "external-network",
                "requiresConfirmation": True,
                "network": "requires-confirmation",
            },
        )


if __name__ == "__main__":
    unittest.main()
