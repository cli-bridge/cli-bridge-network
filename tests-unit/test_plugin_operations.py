import sys
import tempfile
import unittest
import json
import os
from pathlib import Path
from unittest.mock import patch

from cbn_audit.log import AuditLog
from cbn_artifacts.store import ArtifactStore
from cbn_events.bus import EventBus
from cbn_plugins.manager import PluginCommand, PluginPlan
from cbn_plugins.operations import PluginOperationRunner


class PluginOperationTests(unittest.TestCase):
    def test_plugin_operation_records_events_audit_and_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit = AuditLog(root / "audit.jsonl")
            events = EventBus(root / "events.jsonl")
            artifacts = ArtifactStore(root / "artifacts")
            runner = PluginOperationRunner(
                audit_log=audit,
                event_bus=events,
                artifact_store=artifacts,
            )
            plan = PluginPlan(
                plugin_id="test-plugin",
                action="install",
                plugin_dir=str(root / "external_plugins" / "test-plugin"),
                commands=(
                    PluginCommand(
                        label="Emit stdout",
                        argv=(
                            sys.executable,
                            "-c",
                            "print('plugin operation ok')",
                        ),
                    ),
                ),
            )
            result = runner.execute(plan)

            self.assertEqual(result["status"], "completed")
            self.assertTrue(result["lock"]["acquired"])
            self.assertFalse((root / "external_plugins" / "test-plugin" / ".operation.lock").exists())
            self.assertEqual(result["results"][0]["exit_code"], 0)
            self.assertTrue(result["results"][0]["artifact_ids"])
            event_types = [event["type"] for event in events.tail(limit=10)]
            self.assertIn("plugin.operation.started", event_types)
            self.assertIn("plugin.command.completed", event_types)
            self.assertIn("plugin.operation.completed", event_types)
            audit_types = [event["type"] for event in audit.tail(limit=10)]
            self.assertIn("plugin.operation.completed", audit_types)
            self.assertEqual(artifacts.list(limit=1)[0]["kind"].split(".")[-1], "stdout")

    def test_plugin_operation_blocks_when_lock_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit = AuditLog(root / "audit.jsonl")
            events = EventBus(root / "events.jsonl")
            plugin_dir = root / "external_plugins" / "test-plugin"
            lock_dir = plugin_dir / ".operation.lock"
            lock_dir.mkdir(parents=True)
            (lock_dir / "holder.json").write_text(
                json.dumps(
                    {
                        "operation_id": "existing-operation",
                        "plugin_id": "test-plugin",
                        "action": "install",
                    }
                ),
                encoding="utf-8",
            )
            runner = PluginOperationRunner(
                audit_log=audit,
                event_bus=events,
                artifact_store=ArtifactStore(root / "artifacts"),
            )
            plan = PluginPlan(
                plugin_id="test-plugin",
                action="install",
                plugin_dir=str(plugin_dir),
                commands=(
                    PluginCommand(
                        label="Should not run",
                        argv=(sys.executable, "-c", "print('unexpected')"),
                    ),
                ),
            )

            result = runner.execute(plan)

            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["results"], [])
            self.assertFalse(result["lock"]["acquired"])
            self.assertEqual(result["lock"]["holder"]["operation_id"], "existing-operation")
            self.assertTrue(lock_dir.exists())
            audit_types = [event["type"] for event in audit.tail(limit=10)]
            self.assertIn("plugin.operation.blocked", audit_types)
            event_payloads = [
                event["payload"]
                for event in events.tail(limit=10)
                if event["type"] == "plugin.operation.completed"
            ]
            self.assertEqual(event_payloads[0]["status"], "blocked")

    def test_plugin_operation_stops_on_required_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner = PluginOperationRunner(
                audit_log=AuditLog(root / "audit.jsonl"),
                event_bus=EventBus(root / "events.jsonl"),
                artifact_store=ArtifactStore(root / "artifacts"),
            )
            plan = PluginPlan(
                plugin_id="test-plugin",
                action="install",
                plugin_dir=str(root / "external_plugins" / "test-plugin"),
                commands=(
                    PluginCommand(
                        label="Fail",
                        argv=(sys.executable, "-c", "raise SystemExit(7)"),
                    ),
                    PluginCommand(
                        label="Should not run",
                        argv=(sys.executable, "-c", "print('unexpected')"),
                    ),
                ),
            )
            result = runner.execute(plan)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(len(result["results"]), 1)

    def test_plugin_operation_handles_missing_executable_as_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner = PluginOperationRunner(
                audit_log=AuditLog(root / "audit.jsonl"),
                event_bus=EventBus(root / "events.jsonl"),
                artifact_store=ArtifactStore(root / "artifacts"),
            )
            plan = PluginPlan(
                plugin_id="test-plugin",
                action="install",
                plugin_dir=str(root / "external_plugins" / "test-plugin"),
                commands=(
                    PluginCommand(
                        label="Missing",
                        argv=("cbn-command-that-does-not-exist",),
                    ),
                ),
            )
            result = runner.execute(plan)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["results"][0]["exit_code"], 127)
            self.assertIn("cbn-command-that-does-not-exist", result["results"][0]["stderr"])

    def test_plugin_operation_sets_utf8_child_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner = PluginOperationRunner(
                audit_log=AuditLog(root / "audit.jsonl"),
                event_bus=EventBus(root / "events.jsonl"),
                artifact_store=ArtifactStore(root / "artifacts"),
            )
            plan = PluginPlan(
                plugin_id="test-plugin",
                action="install",
                plugin_dir=str(root / "external_plugins" / "test-plugin"),
                commands=(
                    PluginCommand(
                        label="Print env",
                        argv=(
                            sys.executable,
                            "-c",
                            (
                                "import json, os; "
                                "print(json.dumps({"
                                "'PYTHONIOENCODING': os.environ.get('PYTHONIOENCODING'), "
                                "'PYTHONUTF8': os.environ.get('PYTHONUTF8')"
                                "}))"
                            ),
                        ),
                    ),
                ),
            )
            result = runner.execute(plan)
            self.assertEqual(result["status"], "completed")
            env = json.loads(result["results"][0]["stdout"])
            self.assertEqual(env["PYTHONIOENCODING"], "utf-8")
            self.assertEqual(env["PYTHONUTF8"], "1")

    def test_plugin_operation_applies_command_env_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit = AuditLog(root / "audit.jsonl")
            runner = PluginOperationRunner(
                audit_log=audit,
                event_bus=EventBus(root / "events.jsonl"),
                artifact_store=ArtifactStore(root / "artifacts"),
            )
            plan = PluginPlan(
                plugin_id="test-plugin",
                action="adapter-smoke",
                plugin_dir=str(root / "external_plugins" / "test-plugin"),
                commands=(
                    PluginCommand(
                        label="Print smoke env",
                        argv=(
                            sys.executable,
                            "-c",
                            "import os; print(os.environ.get('CBN_ADAPTER_SMOKE'))",
                        ),
                        env={"CBN_ADAPTER_SMOKE": "1"},
                    ),
                ),
            )

            result = runner.execute(plan)

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["results"][0]["stdout"].strip(), "1")
            started = [
                event
                for event in audit.tail(limit=10)
                if event["type"] == "plugin.command.started"
            ][0]
            self.assertEqual(started["payload"]["env_overrides"], ["CBN_ADAPTER_SMOKE"])

    def test_plugin_operation_strips_secret_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit = AuditLog(root / "audit.jsonl")
            runner = PluginOperationRunner(
                audit_log=audit,
                event_bus=EventBus(root / "events.jsonl"),
                artifact_store=ArtifactStore(root / "artifacts"),
            )
            plan = PluginPlan(
                plugin_id="test-plugin",
                action="adapter-smoke",
                plugin_dir=str(root / "external_plugins" / "test-plugin"),
                commands=(
                    PluginCommand(
                        label="Print secret env",
                        argv=(
                            sys.executable,
                            "-c",
                            (
                                "import json, os; "
                                "print(json.dumps({"
                                "'inherited': os.environ.get('CBN_TEST_SECRET'), "
                                "'override': os.environ.get('CBN_OVERRIDE_TOKEN'), "
                                "'smoke': os.environ.get('CBN_ADAPTER_SMOKE')"
                                "}))"
                            ),
                        ),
                        env={"CBN_ADAPTER_SMOKE": "1", "CBN_OVERRIDE_TOKEN": "blocked"},
                    ),
                ),
            )

            with patch.dict(os.environ, {"CBN_TEST_SECRET": "leaked"}, clear=False):
                result = runner.execute(plan)

            self.assertEqual(result["status"], "completed")
            env = json.loads(result["results"][0]["stdout"])
            self.assertIsNone(env["inherited"])
            self.assertIsNone(env["override"])
            self.assertEqual(env["smoke"], "1")
            started = [
                event
                for event in audit.tail(limit=10)
                if event["type"] == "plugin.command.started"
            ][0]
            self.assertEqual(started["payload"]["env_policy"]["mode"], "allowlist")
            self.assertIn("CBN_OVERRIDE_TOKEN", started["payload"]["env_policy"]["denied"])

    def test_plugin_operation_caps_output_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts = ArtifactStore(root / "artifacts")
            runner = PluginOperationRunner(
                audit_log=AuditLog(root / "audit.jsonl"),
                event_bus=EventBus(root / "events.jsonl"),
                artifact_store=artifacts,
            )
            plan = PluginPlan(
                plugin_id="test-plugin",
                action="adapter-smoke",
                plugin_dir=str(root / "external_plugins" / "test-plugin"),
                commands=(
                    PluginCommand(
                        label="Large output",
                        argv=(sys.executable, "-c", "print('x' * 100)"),
                    ),
                ),
            )

            with patch("cbn_plugins.operations.PLUGIN_COMMAND_OUTPUT_LIMIT_BYTES", 20):
                result = runner.execute(plan)

            first = result["results"][0]
            self.assertEqual(result["status"], "completed")
            self.assertTrue(first["stdout_truncated"])
            self.assertEqual(first["output_limit_bytes"], 20)
            self.assertGreater(first["stdout_bytes"], 20)
            self.assertTrue(first["artifact_ids"])
            artifact = artifacts.inspect(first["artifact_ids"][0])
            self.assertIn("output truncated", artifact["content"])
            self.assertLessEqual(len(artifact["content"].encode("utf-8")), 128)

    def test_plugin_plan_serializes_command_timeout(self):
        plan = PluginPlan(
            plugin_id="test-plugin",
            action="install",
            plugin_dir="external_plugins/test-plugin",
            commands=(
                PluginCommand(
                    label="Timeout aware",
                    argv=(sys.executable, "--version"),
                    timeout_seconds=12,
                ),
            ),
        )
        payload = plan.as_dict()
        self.assertEqual(payload["commands"][0]["timeout_seconds"], 12)

    def test_plugin_operation_times_out_command_as_structured_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit = AuditLog(root / "audit.jsonl")
            events = EventBus(root / "events.jsonl")
            artifacts = ArtifactStore(root / "artifacts")
            runner = PluginOperationRunner(
                audit_log=audit,
                event_bus=events,
                artifact_store=artifacts,
            )
            plan = PluginPlan(
                plugin_id="test-plugin",
                action="install",
                plugin_dir=str(root / "external_plugins" / "test-plugin"),
                commands=(
                    PluginCommand(
                        label="Timeout",
                        argv=(sys.executable, "-c", "import time; print('before sleep'); time.sleep(5)"),
                        timeout_seconds=1,
                    ),
                    PluginCommand(
                        label="Should not run after timeout",
                        argv=(sys.executable, "-c", "print('unexpected')"),
                    ),
                ),
            )
            result = runner.execute(plan)

            self.assertEqual(result["status"], "failed")
            self.assertEqual(len(result["results"]), 1)
            first = result["results"][0]
            self.assertTrue(first["timed_out"])
            self.assertEqual(first["exit_code"], 124)
            self.assertEqual(first["timeout_seconds"], 1)
            self.assertIn("timed out", first["stderr"])
            self.assertTrue(first["artifact_ids"])
            completed = [
                event
                for event in events.tail(limit=10)
                if event["type"] == "plugin.command.completed"
            ][0]
            self.assertTrue(completed["payload"]["timed_out"])
            self.assertTrue(
                any(
                    event["payload"].get("timeout_seconds") == 1
                    for event in audit.tail(limit=10)
                    if event["type"] == "plugin.command.started"
                )
            )

    def test_plugin_write_operation_records_lock_audit_event_and_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit = AuditLog(root / "audit.jsonl")
            events = EventBus(root / "events.jsonl")
            artifacts = ArtifactStore(root / "artifacts")
            runner = PluginOperationRunner(
                audit_log=audit,
                event_bus=events,
                artifact_store=artifacts,
            )
            plan = PluginPlan(
                plugin_id="test-plugin",
                action="write-config",
                plugin_dir=str(root / "external_plugins" / "test-plugin"),
                commands=(),
            )

            result = runner.execute_write(
                plan,
                lambda operation_id: {
                    "status": "completed",
                    "operation_id": operation_id,
                    "written": [str(root / "config.json")],
                    "backups": [],
                },
            )

            self.assertEqual(result["status"], "completed")
            self.assertTrue(result["lock"]["acquired"])
            self.assertTrue(result["artifact_ids"])
            self.assertEqual(result["write_result"]["written"], [str(root / "config.json")])
            self.assertFalse((root / "external_plugins" / "test-plugin" / ".operation.lock").exists())
            audit_types = [event["type"] for event in audit.tail(limit=10)]
            self.assertIn("plugin.operation.started", audit_types)
            self.assertIn("plugin.operation.completed", audit_types)
            event_types = [event["type"] for event in events.tail(limit=10)]
            self.assertIn("plugin.operation.started", event_types)
            self.assertIn("plugin.operation.completed", event_types)
            artifact = artifacts.inspect(result["artifact_ids"][0])
            self.assertIn("config.json", artifact["content"])

    def test_plugin_write_operation_blocks_when_lock_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "external_plugins" / "test-plugin"
            lock_dir = plugin_dir / ".operation.lock"
            lock_dir.mkdir(parents=True)
            (lock_dir / "holder.json").write_text(
                json.dumps({"operation_id": "existing", "plugin_id": "test-plugin"}),
                encoding="utf-8",
            )
            runner = PluginOperationRunner(
                audit_log=AuditLog(root / "audit.jsonl"),
                event_bus=EventBus(root / "events.jsonl"),
                artifact_store=ArtifactStore(root / "artifacts"),
            )
            plan = PluginPlan(
                plugin_id="test-plugin",
                action="write-config",
                plugin_dir=str(plugin_dir),
                commands=(),
            )

            result = runner.execute_write(
                plan,
                lambda operation_id: {"status": "completed", "operation_id": operation_id},
            )

            self.assertEqual(result["status"], "blocked")
            self.assertFalse(result["lock"]["acquired"])
            self.assertEqual(result["lock"]["holder"]["operation_id"], "existing")
            self.assertIsNone(result["write_result"])
            self.assertEqual(result["artifact_ids"], [])


if __name__ == "__main__":
    unittest.main()
