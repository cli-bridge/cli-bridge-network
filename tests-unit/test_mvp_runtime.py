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

    def test_cli_registry_search_outputs_ranked_matches(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn", "registry", "search", "git status"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload[0]["manifest"]["capability_id"], "git.status")
        self.assertIn("capability_id", payload[0]["match"]["fields"])

    def test_cli_registry_validate_outputs_manifest_report(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn", "registry", "validate", "manifests"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["valid"])
        self.assertGreaterEqual(payload["checked_count"], 3)
        self.assertEqual(payload["error_count"], 0)

    def test_cli_registry_validate_reports_bad_manifest_without_runtime_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(
                json.dumps(
                    {
                        "apiVersion": "bridge.dev/v1alpha1",
                        "kind": "ToolManifest",
                        "metadata": {"id": "bad"},
                        "spec": {
                            "transport": {"kind": "stdio", "command": "python"},
                            "policy": {"risk": "unknown", "network": "deny"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            proc = subprocess.run(
                [sys.executable, "-m", "cbn", "registry", "validate", str(path)],
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        self.assertEqual(proc.returncode, 7)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["valid"])
        self.assertIn("unknown spec.policy.risk", payload["reports"][0]["errors"][0])

    def test_cli_registry_validate_reports_unknown_parser_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad-parser.json"
            path.write_text(
                json.dumps(_manifest_dict("bad.parser", parser_ref="missing.parser")),
                encoding="utf-8",
            )
            proc = subprocess.run(
                [sys.executable, "-m", "cbn", "registry", "validate", str(path)],
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        self.assertEqual(proc.returncode, 7)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["valid"])
        self.assertIn("unknown spec.output.parserRef", payload["reports"][0]["errors"][0])

    def test_cli_registry_validate_reports_duplicate_capability_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "one.json").write_text(json.dumps(_manifest_dict("dupe.id")), encoding="utf-8")
            (root / "two.json").write_text(json.dumps(_manifest_dict("dupe.id")), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, "-m", "cbn", "registry", "validate", str(root)],
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        self.assertEqual(proc.returncode, 7)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["error_count"], 2)
        self.assertTrue(
            all("duplicate capability_id" in report["errors"][0] for report in payload["reports"])
        )

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
        self.assertEqual(decision.as_dict()["network"], "deny")

    def test_policy_blocks_network_requires_confirmation_without_confirmation(self):
        network_manifest = CapabilityManifest.from_dict(
            {
                "apiVersion": "bridge.dev/v1alpha1",
                "kind": "ToolManifest",
                "metadata": {"id": "test.network", "title": "Network"},
                "spec": {
                    "transport": {
                        "kind": "stdio",
                        "command": "python",
                        "argsTemplate": ["--version"],
                        "cwdPolicy": "workspace",
                    },
                    "policy": {
                        "risk": "read",
                        "requiresConfirmation": False,
                        "network": "requires-confirmation",
                    },
                    "output": {"parserRef": "raw.text", "verified": True},
                },
            }
        )
        decision = PolicyEngine().evaluate(network_manifest, confirmed=False)
        self.assertFalse(decision.allowed)
        self.assertIn("network=requires-confirmation", decision.reason)
        confirmed = PolicyEngine().evaluate(network_manifest, confirmed=True)
        self.assertTrue(confirmed.allowed)
        self.assertTrue(confirmed.requires_confirmation)

    def test_policy_allows_localhost_network_without_confirmation(self):
        manifest = CapabilityManifest.from_dict(
            {
                "apiVersion": "bridge.dev/v1alpha1",
                "kind": "ToolManifest",
                "metadata": {"id": "test.localhost", "title": "Localhost"},
                "spec": {
                    "transport": {
                        "kind": "stdio",
                        "command": "python",
                        "argsTemplate": ["--version"],
                        "cwdPolicy": "workspace",
                    },
                    "policy": {
                        "risk": "write-workspace",
                        "requiresConfirmation": False,
                        "network": "localhost",
                    },
                    "output": {"parserRef": "raw.text", "verified": True},
                },
            }
        )
        decision = PolicyEngine().evaluate(manifest, confirmed=False)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.as_dict()["network"], "localhost")

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
        self.assertTrue(any(route["path"] == "/registry?q=<query>" for route in payload))
        self.assertTrue(any(route["path"] == "/registry/validate" for route in payload))
        self.assertTrue(any(route["path"] == "/messages/validate" for route in payload))
        self.assertTrue(any(route["path"] == "/messages/select" for route in payload))
        self.assertTrue(any(route["path"] == "/messages/args" for route in payload))
        self.assertTrue(any(route["path"] == "/plugins/execute" for route in payload))
        self.assertTrue(any(route["path"] == "/plugins/cli-anything/preflight" for route in payload))
        self.assertTrue(any(route["path"] == "/plugins/cli-anything/adapt-harness" for route in payload))
        self.assertTrue(any(route["path"] == "/plugins/cli-anything/prepare-harness" for route in payload))
        self.assertTrue(any(route["path"] == "/plugins/cli-anything/sync-market" for route in payload))
        self.assertTrue(any(route["path"] == "/plugins/cli-anything/harness" for route in payload))
        self.assertTrue(any(route["path"] == "/events" for route in payload))
        self.assertTrue(any(route["path"] == "/artifacts" for route in payload))
        self.assertTrue(any(route["path"] == "/parsers" for route in payload))
        self.assertTrue(any(route["path"] == "/protocols" for route in payload))
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


def _manifest_dict(capability_id: str, parser_ref: str = "raw.text") -> dict:
    return {
        "apiVersion": "bridge.dev/v1alpha1",
        "kind": "ToolManifest",
        "metadata": {"id": capability_id, "title": capability_id},
        "spec": {
            "transport": {
                "kind": "stdio",
                "command": "python",
                "argsTemplate": ["--version"],
                "cwdPolicy": "workspace",
            },
            "policy": {"risk": "read", "requiresConfirmation": False, "network": "deny"},
            "output": {"parserRef": parser_ref, "verified": True},
        },
    }


if __name__ == "__main__":
    unittest.main()
