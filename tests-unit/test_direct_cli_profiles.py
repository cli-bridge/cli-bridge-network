import json
import subprocess
import sys
import unittest

from cbn_core.manifest import validate_manifest_path
from cbn_runtime.context import build_runtime
from cbn_tools.direct_cli_readiness import direct_cli_readiness_report
from cbn_tools.external_cli import _extract_dreamina_trace_messages, list_actions, require_action


DIRECT_CLI_CAPABILITIES = {
    "feishu.version",
    "feishu.help",
    "feishu.doctor",
    "feishu.schema.help",
    "obsidian-cli.official.help",
    "obsidian-cli.local-rest.help",
    "obsidian-cli.local-rest.server.status",
    "obsidian-cli.local-rest.note.read",
    "jimeng.version",
    "jimeng.help",
    "jimeng.user_credit",
    "jimeng.list_task",
    "jimeng.query_result",
    "jimeng.text2image.submit",
    "caw.version",
    "caw.help",
    "caw.status",
    "caw.schema.help",
}


class DirectCliProfileTests(unittest.TestCase):
    def test_external_cli_profile_actions_are_listed_without_execution(self):
        actions = {(item["profile"], item["action"]) for item in list_actions()}
        self.assertIn(("feishu", "version"), actions)
        self.assertIn(("obsidian-cli", "local-rest-help"), actions)
        self.assertIn(("jimeng", "text2image-submit"), actions)
        self.assertIn(("caw", "status"), actions)

    def test_external_cli_print_plan_outputs_resolved_argv(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn_tools.external_cli",
                "--print-plan",
                "feishu",
                "version",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["profile"], "feishu")
        self.assertEqual(payload["action"], "version")
        self.assertIn("--version", payload["argv"])

    def test_external_cli_action_accepts_runtime_extra_args(self):
        base_argv = require_action("jimeng", "text2image-submit").argv()
        self.assertIn("text2image", base_argv)

    def test_runtime_loads_direct_cli_manifests(self):
        runtime = build_runtime()
        loaded = {manifest.capability_id for manifest in runtime.registry.list()}
        self.assertTrue(DIRECT_CLI_CAPABILITIES.issubset(loaded))
        self.assertEqual(runtime.registry.require("feishu.doctor").output.parser_ref, "direct-cli.typed")
        self.assertTrue(runtime.registry.require("jimeng.user_credit").output.verified)

    def test_direct_cli_manifest_policies_keep_live_calls_gated(self):
        runtime = build_runtime()
        self.assertEqual(runtime.registry.require("feishu.version").policy.risk, "read")
        self.assertFalse(runtime.registry.require("feishu.version").policy.requires_confirmation)

        for capability_id in ("feishu.doctor", "jimeng.text2image.submit", "caw.status"):
            manifest = runtime.registry.require(capability_id)
            self.assertEqual(manifest.policy.risk, "external-network")
            self.assertTrue(manifest.policy.requires_confirmation)
            self.assertEqual(manifest.policy.network, "requires-confirmation")

        obsidian_note = runtime.registry.require("obsidian-cli.local-rest.note.read")
        self.assertEqual(obsidian_note.policy.network, "localhost")
        self.assertTrue(obsidian_note.policy.requires_confirmation)

    def test_manifest_validation_accepts_direct_cli_profiles(self):
        report = validate_manifest_path(build_runtime().registry.require("feishu.version").source_path.parent)
        self.assertTrue(report["valid"])
        self.assertEqual(report["error_count"], 0)

    def test_direct_cli_typed_parser_classifies_setup_errors(self):
        parsed = build_runtime().parser_registry.parse(
            "direct-cli.typed",
            "",
            "未检测到有效登录态，请先执行 dreamina login\n",
        )
        self.assertEqual(parsed["data"]["profile"], "jimeng")
        self.assertTrue(parsed["data"]["setup_required"])
        self.assertEqual(parsed["data"]["error_type"], "auth_required")

    def test_direct_cli_typed_parser_classifies_jimeng_account_permission(self):
        parsed = build_runtime().parser_registry.parse(
            "direct-cli.typed",
            "",
            "dreamina diagnostic: 当前账号没有 dreamina_cli 使用权限: current account is not maestro vip\n",
        )
        self.assertEqual(parsed["data"]["profile"], "jimeng")
        self.assertFalse(parsed["data"]["ready"])
        self.assertTrue(parsed["data"]["setup_required"])
        self.assertEqual(parsed["data"]["error_type"], "account_permission_required")

    def test_dreamina_trace_messages_decode_non_stdio_errors(self):
        trace = (
            '853 write(8, "\\345\\275\\223\\345\\211\\215\\350\\264\\246\\345\\217\\267\\346\\262\\241\\346\\234\\211 '
            'dreamina_cli \\344\\275\\277\\347\\224\\250\\346\\235\\203\\351\\231\\220: current account is not maestro vip\\n", 81) = 81\n'
        )
        self.assertEqual(
            _extract_dreamina_trace_messages(trace),
            ["当前账号没有 dreamina_cli 使用权限: current account is not maestro vip"],
        )

    def test_direct_cli_readiness_report_covers_profiles_and_recovery(self):
        payload = direct_cli_readiness_report(build_runtime())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["kind"], "DirectCliReadinessReport")
        self.assertEqual(payload["parser_ref"], "direct-cli.typed")
        self.assertEqual(payload["summary"]["profile_count"], 4)
        self.assertEqual(payload["summary"]["missing_runtime_capability_count"], 0)
        self.assertEqual(payload["parser_contract"]["failed_case_count"], 0)
        self.assertEqual(payload["summary"]["recovery_type_count"], 5)
        profiles = {item["profile"]: item for item in payload["profiles"]}
        self.assertGreaterEqual(profiles["jimeng"]["setup_action_count"], 3)
        self.assertGreaterEqual(profiles["obsidian-cli"]["capability_count"], 4)
        recovery = {item["error_type"]: item for item in payload["error_recovery"]}
        self.assertTrue(recovery["auth_required"]["covered"])
        self.assertTrue(recovery["local_rest_unavailable"]["covered"])
        self.assertTrue(recovery["launcher_failure"]["covered"])


if __name__ == "__main__":
    unittest.main()
