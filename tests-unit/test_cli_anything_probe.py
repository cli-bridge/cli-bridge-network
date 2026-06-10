import unittest

from cbn_plugins.cli_anything_parts.probe import (
    declared_requires,
    dependency_probes,
    platform_assessment,
    readiness_blocker_probes,
    readiness_summary,
    requirement_assessment,
    requirement_commands,
    requirement_env_vars,
    requirement_localhost_ports,
)


class CliAnythingProbeTests(unittest.TestCase):
    def test_declared_requires_prefers_market_record_then_cli_info(self):
        self.assertEqual(
            declared_requires(
                {"requires": "gimp (apt install gimp)"},
                {"cli_hub_info": {"fields": {"requires": "nothing"}}},
            ),
            "gimp (apt install gimp)",
        )
        self.assertEqual(
            declared_requires(
                {},
                {"cli_hub_info": {"fields": {"requires": "nothing"}}},
            ),
            "nothing",
        )

    def test_requirement_assessment_allows_managed_package_requirements(self):
        result = requirement_assessment("Python >= 3.10; pip package py4csr")

        self.assertTrue(result["external_dependency_free"])
        self.assertEqual(result["dependency_class"], "managed-package")
        self.assertTrue(result["managed_dependency_only"])
        self.assertFalse(result["manual_dependency_required"])
        self.assertIn("python-runtime", result["signals"])
        self.assertIn("python-package-manager", result["signals"])
        self.assertIn("managed-packages", result["signals"])

    def test_requirement_assessment_blocks_external_apps_and_tokens(self):
        result = requirement_assessment("Blender >= 4.2 and API key")

        self.assertFalse(result["external_dependency_free"])
        self.assertEqual(result["dependency_class"], "manual-or-external")
        self.assertTrue(result["manual_dependency_required"])
        self.assertIn("api key", result["signals"])
        self.assertIn("external-app:blender", result["signals"])

    def test_dependency_probes_reports_missing_env_and_manual_secret(self):
        probes = dependency_probes(
            "Set CBN_TEST_REQUIRED_ENV_NEVER_SET and API key",
            entry_point=None,
        )
        by_id = {probe["id"]: probe for probe in probes}

        self.assertEqual(by_id["declared-requirements"]["status"], "declared")
        self.assertEqual(by_id["env:CBN_TEST_REQUIRED_ENV_NEVER_SET"]["status"], "missing")
        self.assertEqual(by_id["manual-account-or-api-key"]["status"], "manual_required")

    def test_requirement_extractors_are_stable(self):
        self.assertEqual(requirement_commands("gimp (apt install gimp)"), ["gimp"])
        self.assertEqual(
            requirement_env_vars("Requires GOOGLE_CLOUD_PROJECT and GEMINI_API_KEY"),
            ["GEMINI_API_KEY", "GOOGLE_CLOUD_PROJECT"],
        )
        self.assertEqual(
            requirement_localhost_ports("ComfyUI at http://localhost:8188 and [::1]:9999"),
            [("::1", 9999), ("localhost", 8188)],
        )

    def test_platform_assessment_reports_host_and_signals(self):
        result = platform_assessment({"platform": "windows"}, "nothing")

        self.assertIn("host", result)
        self.assertIn("windows", result["signals"])

    def test_readiness_summary_counts_blocker_probes(self):
        probes = [
            {"id": "ok", "status": "available", "severity": "info"},
            {"id": "missing", "status": "missing", "severity": "blocker"},
        ]

        summary = readiness_summary(probes, install_candidate=True)

        self.assertFalse(summary["ready"])
        self.assertEqual(summary["probe_blocker_count"], 1)
        self.assertEqual(readiness_blocker_probes(summary), [probes[1]])


if __name__ == "__main__":
    unittest.main()
