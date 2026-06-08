import sys
import tempfile
import unittest
import json
from pathlib import Path

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
            self.assertEqual(result["results"][0]["exit_code"], 0)
            self.assertTrue(result["results"][0]["artifact_ids"])
            event_types = [event["type"] for event in events.tail(limit=10)]
            self.assertIn("plugin.operation.started", event_types)
            self.assertIn("plugin.command.completed", event_types)
            self.assertIn("plugin.operation.completed", event_types)
            audit_types = [event["type"] for event in audit.tail(limit=10)]
            self.assertIn("plugin.operation.completed", audit_types)
            self.assertEqual(artifacts.list(limit=1)[0]["kind"].split(".")[-1], "stdout")

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


if __name__ == "__main__":
    unittest.main()
