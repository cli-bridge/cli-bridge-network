import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cbn_parsers.registry import ParserRegistry
from cbn_protocol.envelope import (
    BridgeMessage,
    bridge_args_from_selectors,
    select_bridge_value,
    validate_bridge_message,
)


class ParserProtocolTests(unittest.TestCase):
    def test_git_status_parser_returns_entries(self):
        parsed = ParserRegistry.builtins().parse(
            "git.status.short",
            " M README.md\n?? tmp.txt\n",
            "",
        )
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["data"]["entries"][0]["worktree"], "M")
        self.assertEqual(parsed["data"]["entries"][1]["path"], "tmp.txt")

    def test_json_parser_returns_json_payload(self):
        parsed = ParserRegistry.builtins().parse("json.stdout", '{"ok": true}', "")
        self.assertEqual(parsed["data"]["json"], {"ok": True})

    def test_bridge_message_envelope_shape(self):
        message = BridgeMessage(
            producer="git.status",
            channel="capability.output",
            correlation_id="call-1",
            payload={"parser_ref": "git.status.short", "ok": True, "data": {}},
        ).as_dict()
        self.assertEqual(message["apiVersion"], "bridge.dev/v1alpha1")
        self.assertEqual(message["kind"], "BridgeMessage")
        self.assertEqual(message["metadata"]["producer"], "git.status")
        self.assertEqual(message["metadata"]["correlationId"], "call-1")

    def test_bridge_message_validation_and_selectors(self):
        message = BridgeMessage(
            producer="git.status",
            channel="capability.output",
            correlation_id="call-1",
            payload={"parser_ref": "raw.text", "data": {"stdout": "git status --short"}},
            artifacts=({"artifact_id": "artifact-1", "kind": "stdout"},),
        ).as_dict()
        self.assertTrue(validate_bridge_message(message)["valid"])
        self.assertEqual(select_bridge_value(message, "payload.data.stdout")["value"], "git status --short")
        self.assertEqual(select_bridge_value(message, "artifacts[0].artifact_id")["value"], "artifact-1")

    def test_bridge_message_args_from_selectors(self):
        message = BridgeMessage(
            producer="json.tool",
            channel="capability.output",
            correlation_id="call-1",
            payload={
                "parser_ref": "json.stdout",
                "data": {
                    "name": "gimp",
                    "enabled": True,
                    "options": {"mode": "batch", "scale": 2},
                    "empty": None,
                },
            },
        ).as_dict()
        routed = bridge_args_from_selectors(
            message,
            [
                "payload.data.name",
                "payload.data.enabled",
                "payload.data.options",
                "payload.data.empty",
            ],
        )
        self.assertTrue(routed["valid"])
        self.assertEqual(
            routed["args"],
            ["gimp", "True", '{"mode": "batch", "scale": 2}', ""],
        )
        self.assertEqual(routed["mappings"][2]["selector"], "payload.data.options")

    def test_invalid_bridge_message_reports_errors(self):
        result = validate_bridge_message({"kind": "BridgeMessage", "payload": []})
        self.assertFalse(result["valid"])
        self.assertIn("metadata must be an object", result["errors"])
        self.assertIn("payload must be an object", result["errors"])

    def test_cli_parser_list_and_call_message(self):
        parsers = subprocess.run(
            [sys.executable, "-m", "cbn", "parser", "list"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        parser_refs = {item["parser_ref"] for item in json.loads(parsers.stdout)}
        self.assertIn("git.status.short", parser_refs)

        call = subprocess.run(
            [sys.executable, "-m", "cbn", "call", "git.version", "--dry-run"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(call.stdout)
        self.assertEqual(payload["parsed"]["parser_ref"], "raw.text")
        self.assertEqual(payload["message"]["kind"], "BridgeMessage")
        self.assertEqual(payload["message"]["metadata"]["producer"], "git.version")

    def test_cli_message_validate_and_select(self):
        message = BridgeMessage(
            producer="git.version",
            channel="capability.output",
            correlation_id="call-1",
            payload={"parser_ref": "raw.text", "data": {"stdout": "git --version"}},
        ).as_dict()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "message.json"
            path.write_text(json.dumps(message, ensure_ascii=False), encoding="utf-8")
            validated = subprocess.run(
                [sys.executable, "-m", "cbn", "message", "validate", str(path)],
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            self.assertTrue(json.loads(validated.stdout)["valid"])

            selected = subprocess.run(
                [sys.executable, "-m", "cbn", "message", "select", str(path), "payload.data.stdout"],
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            self.assertEqual(json.loads(selected.stdout)["value"], "git --version")

            args = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "cbn",
                    "message",
                    "args",
                    str(path),
                    "payload.data.stdout",
                    "metadata.producer",
                ],
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            payload = json.loads(args.stdout)
            self.assertEqual(payload["args"], ["git --version", "git.version"])
            self.assertEqual(payload["mappings"][0]["selector"], "payload.data.stdout")

    def test_dry_run_uses_raw_parser_even_for_structured_capability(self):
        call = subprocess.run(
            [sys.executable, "-m", "cbn", "call", "git.status", "--dry-run"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(call.stdout)
        self.assertEqual(payload["reason"], "dry-run")
        self.assertEqual(payload["parsed"]["parser_ref"], "raw.text")
        self.assertTrue(payload["parsed"]["dry_run"])
        self.assertIn("git status --short", payload["parsed"]["data"]["stdout"])


if __name__ == "__main__":
    unittest.main()
