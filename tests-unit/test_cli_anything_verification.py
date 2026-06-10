import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from cbn_plugins.cli_anything_parts.verification import (
    manifest_has_entrypoint_repair,
    matching_parser_fixture_paths,
    parser_contract_report,
    parser_fixture_gate,
    policy_requires_confirmation,
    protocol_smoke_suite_command,
    protocol_verification_summary,
    registry_source_for_manifest,
    smoke_suite_stage_status,
    verification_blockers,
    verification_stages,
)


class CliAnythingVerificationTests(unittest.TestCase):
    def test_parser_contract_report_classifies_known_verified_and_unknown(self):
        verified = parser_contract_report(
            {"spec": {"output": {"parserRef": "cli-anything.raw", "verified": True}}},
            {"cli-anything.raw"},
        )
        unknown = parser_contract_report(
            {"spec": {"output": {"parserRef": "missing.parser"}}},
            {"cli-anything.raw"},
        )

        self.assertEqual(verified["status"], "verified")
        self.assertTrue(verified["known"])
        self.assertEqual(unknown["status"], "unknown_parser")
        self.assertFalse(unknown["known"])

    def test_protocol_verification_summary_collects_missing_and_partial(self):
        summary = protocol_verification_summary(
            {
                "mcp": {
                    "scope": "capability",
                    "wire_compatible": False,
                    "status_counts": {"missing": 1, "partial": 1},
                    "checks": [
                        {"requirement": "tool schema", "status": "missing"},
                        {"requirement": "result envelope", "status": "partial"},
                        {"requirement": "metadata", "status": "passed"},
                    ],
                    "next_steps": ["fix schema"],
                }
            }
        )

        self.assertEqual(summary["mcp"]["missing"], ["tool schema"])
        self.assertEqual(summary["mcp"]["partial"], ["result envelope"])

    def test_verification_blockers_respect_entrypoint_repair_overlay(self):
        blockers = verification_blockers(
            {
                "blockers": [
                    "installed harness entrypoint is missing from PATH",
                    "manual review required",
                ],
                "gates": {
                    "installed": True,
                    "runtime_transport_ready": True,
                    "launch_ready": False,
                },
            },
            {"probe_blocker_count": 0},
            {
                "entrypoint_repair_active": True,
                "manifest_imported": True,
            },
        )

        self.assertEqual(blockers, ["manual review required"])

    def test_manifest_repair_marker_and_registry_source(self):
        manifest = {
            "metadata": {
                "annotations": {
                    "cbn.repair.kind": "cli-anything-entrypoint-wrapper",
                }
            }
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local_dir = root / "runtime" / "manifests"
            local_dir.mkdir(parents=True)
            local_manifest = SimpleNamespace(source_path=local_dir / "tool.json")
            portable_manifest = SimpleNamespace(source_path=root / "manifests" / "tool.json")

            self.assertTrue(manifest_has_entrypoint_repair(manifest))
            self.assertEqual(
                registry_source_for_manifest(local_manifest, local_manifest_dir=local_dir),
                "runtime_local_overlay",
            )
            self.assertEqual(
                registry_source_for_manifest(portable_manifest, local_manifest_dir=local_dir),
                "current_registry",
            )
            self.assertEqual(
                registry_source_for_manifest(None, local_manifest_dir=local_dir),
                "generated_preview",
            )

    def test_verification_stages_and_smoke_command_are_stable(self):
        command = protocol_smoke_suite_command(
            "cli-anything.gimp.launch",
            ("--help",),
            ("workflows/example.json",),
        )
        stages = verification_stages(
            "gimp",
            "cli-anything.gimp.launch",
            {
                "ok": True,
                "gates": {
                    "manifest_valid": True,
                    "installed": True,
                    "launch_ready": True,
                },
            },
            {"probe_blocker_count": 0},
            {
                "manifest_imported": True,
                "protocol_check_source": "current_registry",
            },
            {"parser_ref": "cli-anything.raw", "verified": False},
            {"mcp": {"status_counts": {"passed": 3}}},
            {"run": False, "command": command, "ok": None, "summary": None},
        )

        by_id = {stage["id"]: stage for stage in stages}
        self.assertIn("--extra-arg=--help", command)
        self.assertIn("--workflow-path workflows/example.json --workflow-dry-run", command)
        self.assertEqual(by_id["dry_run_call"]["status"], "ready")
        self.assertEqual(by_id["smoke_protocol_facades"]["status"], "ready")
        self.assertEqual(smoke_suite_stage_status({"run": True, "ok": False}, {}), "failed")

    def test_parser_fixture_gate_and_paths_track_capability_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "parser_fixtures" / "gimp.case.json"
            report = {
                "ok": True,
                "parser_ref": "cli-anything.raw",
                "fixture_count": 1,
                "case_count": 2,
                "failed_case_count": 0,
                "reports": [
                    {
                        "fixture_id": "gimp.case",
                        "source_path": str(fixture),
                        "verified_capabilities": ["cli-anything.gimp.launch"],
                    },
                    {
                        "fixture_id": "other.case",
                        "verified_capabilities": ["cli-anything.other.launch"],
                    },
                ],
            }

            gate = parser_fixture_gate(report, "cli-anything.gimp.launch")
            paths = matching_parser_fixture_paths(report, "cli-anything.gimp.launch", root)

            self.assertTrue(gate["ok"])
            self.assertTrue(gate["capability_verified"])
            self.assertEqual(gate["matching_fixture_ids"], ["gimp.case"])
            self.assertEqual(paths, ["parser_fixtures/gimp.case.json"])

    def test_policy_requires_confirmation_accepts_both_manifest_shapes(self):
        self.assertTrue(policy_requires_confirmation({"requiresConfirmation": True}))
        self.assertTrue(policy_requires_confirmation({"requires_confirmation": True}))
        self.assertFalse(policy_requires_confirmation({}))


if __name__ == "__main__":
    unittest.main()
