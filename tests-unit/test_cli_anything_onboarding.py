import unittest

from cbn_plugins.cli_anything_parts.onboarding import (
    onboarding_next_commands,
    onboarding_stage_results,
    onboarding_summary,
    probe_blocked_onboarding_report,
)


class CliAnythingOnboardingTests(unittest.TestCase):
    def test_probe_blocked_report_preserves_onboarding_shape(self):
        report = probe_blocked_onboarding_report(
            plugin_id="cli-anything",
            harness_name="missing",
            from_market=True,
            write=True,
            confirmed=False,
            install=True,
            allow_blocked=False,
            include_workflows=True,
            run_smoke_suite=False,
            probe={"ok": False, "error": "market record not found"},
        )

        self.assertFalse(report["ok"])
        self.assertEqual(report["kind"], "CliAnythingHarnessOnboarding")
        self.assertEqual(report["error"], "market record not found")
        self.assertEqual(report["stage_results"][0]["id"], "probe")
        self.assertEqual(report["stage_results"][0]["status"], "blocked")
        self.assertIn("onboard-harness cli-anything missing --offline", report["next_commands"][1])

    def test_onboarding_summary_status_precedence(self):
        blocked = onboarding_summary(
            ready_for_manifest_write=True,
            manifest_written=False,
            write_blocked_by_gate=True,
            write_requested_without_confirmation=False,
            ready_for_install=False,
            install_requested_without_confirmation=False,
            install_execution_status="not_requested",
            ready_for_runtime_verification=False,
            smoke_suite={},
            recommended_next_action="resolve_blockers",
        )
        requires_confirmation = onboarding_summary(
            ready_for_manifest_write=True,
            manifest_written=False,
            write_blocked_by_gate=False,
            write_requested_without_confirmation=True,
            ready_for_install=True,
            install_requested_without_confirmation=True,
            install_execution_status="requires_confirmation",
            ready_for_runtime_verification=False,
            smoke_suite={},
            recommended_next_action="write_manifest",
        )
        completed = onboarding_summary(
            ready_for_manifest_write=True,
            manifest_written=True,
            write_blocked_by_gate=False,
            write_requested_without_confirmation=False,
            ready_for_install=True,
            install_requested_without_confirmation=False,
            install_execution_status="completed",
            ready_for_runtime_verification=True,
            smoke_suite={"run": True, "ok": True},
            recommended_next_action="verify_harness",
        )

        self.assertEqual(blocked["manifest_write_status"], "blocked")
        self.assertEqual(requires_confirmation["manifest_write_status"], "requires_confirmation")
        self.assertTrue(requires_confirmation["install_requires_confirmation"])
        self.assertEqual(completed["manifest_write_status"], "completed")
        self.assertTrue(completed["install_executed"])
        self.assertTrue(completed["smoke_suite_ready"])

    def test_onboarding_stage_results_marks_ready_completed_and_blocked_stages(self):
        stages = onboarding_stage_results(
            evaluation={
                "blockers": [],
                "recommended_next_action": "write_manifest",
            },
            probe={
                "ready": True,
                "probes": [{"id": "declared-requirements", "severity": "info", "status": "satisfied"}],
            },
            adaptation={"written": None},
            install_gate={"ok": True, "blockers": []},
            verification_blockers=["manifest is not imported into manifests/"],
            ready_for_manifest_write=True,
            ready_for_install=True,
            ready_for_runtime_verification=False,
            manifest_written=False,
            manifest_already_imported=False,
            harness_already_installed=False,
            write=False,
            confirmed=False,
            install=False,
            allow_blocked=False,
            write_blocked_by_gate=False,
            install_execution_status="not_requested",
            install_execution_blockers=[],
            smoke_suite={},
        )
        by_id = {stage["id"]: stage for stage in stages}

        self.assertEqual(by_id["evaluate"]["status"], "completed")
        self.assertEqual(by_id["probe_dependencies"]["status"], "completed")
        self.assertEqual(by_id["adapt_manifest"]["status"], "ready")
        self.assertEqual(by_id["install_harness"]["status"], "ready")
        self.assertEqual(by_id["verify_runtime"]["status"], "blocked")
        self.assertEqual(by_id["smoke_protocol_facades"]["status"], "pending")

    def test_onboarding_stage_results_carries_blockers(self):
        stages = onboarding_stage_results(
            evaluation={
                "blockers": ["policy requires elevated confirmation"],
                "recommended_next_action": "resolve_blockers",
            },
            probe={
                "ready": False,
                "probes": [
                    {"id": "env:API_KEY", "severity": "blocker", "status": "missing"},
                ],
            },
            adaptation={"written": None},
            install_gate={"ok": False, "blockers": ["dependency probes have blocker-level failures"]},
            verification_blockers=["dependency probes have blocker-level failures"],
            ready_for_manifest_write=False,
            ready_for_install=False,
            ready_for_runtime_verification=False,
            manifest_written=False,
            manifest_already_imported=False,
            harness_already_installed=False,
            write=True,
            confirmed=True,
            install=True,
            allow_blocked=False,
            write_blocked_by_gate=True,
            install_execution_status="blocked",
            install_execution_blockers=["install gate blocked"],
            smoke_suite={"run": True, "ok": False},
        )
        by_id = {stage["id"]: stage for stage in stages}

        self.assertEqual(by_id["probe_dependencies"]["blockers"], ["env:API_KEY"])
        self.assertEqual(by_id["adapt_manifest"]["blockers"], ["manifest write blocked by harness evaluation"])
        self.assertEqual(by_id["install_harness"]["blockers"], ["install gate blocked"])
        self.assertEqual(by_id["smoke_protocol_facades"]["status"], "blocked")

    def test_onboarding_next_commands_cover_write_install_verify_and_call(self):
        commands = onboarding_next_commands("gimp", "cli-anything.gimp.launch")

        self.assertEqual(commands[0], "python -m cbn plugin onboard-harness cli-anything gimp --from-market")
        self.assertIn("--write --yes", commands[1])
        self.assertIn("plugin harness cli-anything install gimp --yes", commands[2])
        self.assertIn("verify-harness cli-anything gimp --smoke-suite", commands[4])
        self.assertEqual(commands[5], "python -m cbn call cli-anything.gimp.launch --dry-run")


if __name__ == "__main__":
    unittest.main()
