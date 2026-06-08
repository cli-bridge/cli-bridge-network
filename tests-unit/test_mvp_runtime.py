import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cbn_audit.log import AuditLog
from cbn_approval.store import ApprovalStore
from cbn_artifacts.store import ArtifactStore
from cbn_core.manifest import CapabilityManifest, ManifestRegistry
from cbn_events.bus import EventBus
from cbn_execution.executor import CapabilityExecutor
from cbn_policy.engine import PolicyEngine
from cbn_runtime.context import build_runtime


class MvpRuntimeTests(unittest.TestCase):
    def test_runtime_loads_builtin_manifests(self):
        runtime = build_runtime()
        ids = {manifest.capability_id for manifest in runtime.registry.list()}
        self.assertIn("git.version", ids)
        self.assertIn("git.status", ids)
        self.assertIn("ffprobe.inspect", ids)

    def test_cli_registry_list_outputs_manifest_records(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn", "registry", "list"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertTrue(any(item["capability_id"] == "git.version" for item in payload))

    def test_cli_call_dry_run_outputs_command_without_real_execution(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn", "call", "git.version", "--dry-run"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["allowed"])
        self.assertEqual(payload["reason"], "dry-run")
        self.assertIn("git --version", payload["stdout"])

    def test_policy_blocks_privileged_without_confirmation(self):
        runtime = build_runtime()
        manifest_type = type(runtime.registry.require("git.version"))
        danger = manifest_type.from_dict(
            {
                "apiVersion": "bridge.dev/v1alpha1",
                "kind": "ToolManifest",
                "metadata": {"id": "test.danger", "title": "Danger"},
                "spec": {
                    "transport": {
                        "kind": "stdio",
                        "command": "python",
                        "argsTemplate": ["--version"],
                        "cwdPolicy": "workspace",
                    },
                    "policy": {
                        "risk": "privileged",
                        "requiresConfirmation": True,
                        "network": "deny",
                    },
                    "output": {"verified": False},
                },
            }
        )
        decision = PolicyEngine().evaluate(danger, confirmed=False)
        self.assertFalse(decision.allowed)

    def test_executor_creates_and_consumes_approval_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = ManifestRegistry()
            registry.register(_danger_manifest())
            approvals = ApprovalStore(Path(tmp) / "approvals.jsonl")
            executor = CapabilityExecutor(
                registry,
                AuditLog(Path(tmp) / "audit.jsonl"),
                approval_store=approvals,
                event_bus=EventBus(Path(tmp) / "events.jsonl"),
                artifact_store=ArtifactStore(Path(tmp) / "artifacts"),
            )
            blocked = executor.call("test.danger", dry_run=True)
            self.assertFalse(blocked["allowed"])
            self.assertEqual(blocked["approval"]["status"], "pending")

            approval_id = blocked["approval"]["approval_id"]
            approvals.decide(approval_id, "approved", actor="test")
            allowed = executor.call("test.danger", dry_run=True, approval_id=approval_id)
            self.assertTrue(allowed["allowed"])
            self.assertEqual(allowed["approval_id"], approval_id)
            self.assertEqual(approvals.inspect(approval_id)["status"], "used")

    def test_executor_writes_audit_for_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = ManifestRegistry()
            registry.load_dir(Path("manifests"))
            audit = AuditLog(Path(tmp) / "audit.jsonl")
            executor = CapabilityExecutor(
                registry,
                audit,
                event_bus=EventBus(Path(tmp) / "events.jsonl"),
                artifact_store=ArtifactStore(Path(tmp) / "artifacts"),
            )
            result = executor.call("git.version", dry_run=True)
            self.assertTrue(result["allowed"])
            self.assertTrue(result["artifacts"])
            events = audit.tail(limit=5)
            self.assertTrue(any(event["type"] == "tool_call.completed" for event in events))

    def test_executor_publishes_events_for_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = ManifestRegistry()
            registry.load_dir(Path("manifests"))
            event_bus = EventBus(Path(tmp) / "events.jsonl")
            executor = CapabilityExecutor(
                registry,
                AuditLog(Path(tmp) / "audit.jsonl"),
                event_bus=event_bus,
                artifact_store=ArtifactStore(Path(tmp) / "artifacts"),
            )
            result = executor.call("git.version", dry_run=True)
            event_tail = event_bus.tail(limit=10)
            event_types = [event["type"] for event in event_tail]
            self.assertIn("tool_call.started", event_types)
            self.assertIn("artifact.created", event_types)
            self.assertIn("tool_call.completed", event_types)
            self.assertEqual(event_tail[-1]["correlation_id"], result["call_id"])

    def test_cli_artifact_and_event_commands_are_available(self):
        subprocess.run(
            [sys.executable, "-m", "cbn", "call", "git.version", "--dry-run"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        events = subprocess.run(
            [sys.executable, "-m", "cbn", "event", "tail", "--limit", "5"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        artifacts = subprocess.run(
            [sys.executable, "-m", "cbn", "artifact", "list", "--limit", "5"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        self.assertTrue(json.loads(events.stdout))
        self.assertTrue(json.loads(artifacts.stdout))

    def test_cli_approval_commands_are_available(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn", "approvals", "list", "--limit", "1"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        self.assertIsInstance(json.loads(proc.stdout), list)

    def test_daemon_routes_are_listed(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn", "daemon", "routes"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertTrue(any(route["path"] == "/plugins/plan" for route in payload))
        self.assertTrue(any(route["path"] == "/events" for route in payload))
        self.assertTrue(any(route["path"] == "/artifacts" for route in payload))
        self.assertTrue(any(route["path"] == "/approvals" for route in payload))
        self.assertTrue(any(route["path"] == "/workflows/run" for route in payload))


def _danger_manifest() -> CapabilityManifest:
    return CapabilityManifest.from_dict(
        {
            "apiVersion": "bridge.dev/v1alpha1",
            "kind": "ToolManifest",
            "metadata": {"id": "test.danger", "title": "Danger"},
            "spec": {
                "transport": {
                    "kind": "stdio",
                    "command": "python",
                    "argsTemplate": ["--version"],
                    "cwdPolicy": "workspace",
                },
                "policy": {
                    "risk": "privileged",
                    "requiresConfirmation": True,
                    "network": "deny",
                },
                "output": {"verified": False},
            },
        }
    )


if __name__ == "__main__":
    unittest.main()
