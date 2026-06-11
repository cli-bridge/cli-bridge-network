import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from cbn_core.agent_cli_contract import agent_cli_card_to_tool_manifests, run_receipt_to_cbn_records
from cbn_core.manifest import validate_manifest_dict
from cbn_core.message import validate_bridge_message


CONTRACT_ROOT = Path("external_protocols/agent-cli-contract")
sys.path.insert(0, str(CONTRACT_ROOT / "python"))

from agent_cli_contract import validate_agent_cli_card, validate_run_receipt  # noqa: E402


class AgentCliContractTests(unittest.TestCase):
    def test_valid_fixtures_pass_standalone_validator(self):
        card = json.loads((CONTRACT_ROOT / "fixtures/agent-cli-card.valid.json").read_text(encoding="utf-8"))
        receipt = json.loads((CONTRACT_ROOT / "fixtures/run-receipt.valid.json").read_text(encoding="utf-8"))
        card_report = validate_agent_cli_card(card)
        receipt_report = validate_run_receipt(receipt)
        self.assertTrue(card_report["ok"], card_report["errors"])
        self.assertEqual(card_report["command_ids"], ["backends"])
        self.assertTrue(receipt_report["ok"], receipt_report["errors"])
        self.assertEqual(receipt_report["artifact_count"], 1)

    def test_conformance_smoke_runs_without_cbn_imports(self):
        proc = subprocess.run(
            [sys.executable, "external_protocols/agent-cli-contract/scripts/conformance_smoke.py"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["independent_boundary"]["ok"])

    def test_standalone_cli_validates_card_and_receipt(self):
        env = {**os.environ, "PYTHONPATH": str(CONTRACT_ROOT / "python")}
        card_proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "agent_cli_contract",
                "validate",
                "card",
                str(CONTRACT_ROOT / "fixtures/agent-cli-card.valid.json"),
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            env=env,
        )
        receipt_proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "agent_cli_contract",
                "validate",
                "receipt",
                str(CONTRACT_ROOT / "fixtures/run-receipt.valid.json"),
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            env=env,
        )
        self.assertTrue(json.loads(card_proc.stdout)["ok"])
        self.assertEqual(json.loads(card_proc.stdout)["target"], "card")
        self.assertTrue(json.loads(receipt_proc.stdout)["ok"])
        self.assertEqual(json.loads(receipt_proc.stdout)["target"], "receipt")

    def test_standalone_cli_returns_json_error_for_missing_file(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "agent_cli_contract",
                "validate",
                "card",
                "external_protocols/agent-cli-contract/fixtures/missing.json",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "PYTHONPATH": str(CONTRACT_ROOT / "python")},
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["target"], "card")
        self.assertIn("file not found", payload["errors"][0])

    def test_agent_cli_card_maps_to_cbn_tool_manifest(self):
        card = json.loads((CONTRACT_ROOT / "fixtures/agent-cli-card.valid.json").read_text(encoding="utf-8"))
        manifests = agent_cli_card_to_tool_manifests(card)
        self.assertEqual(len(manifests), 1)
        manifest = manifests[0]
        self.assertEqual(manifest["metadata"]["id"], "example.macrocli.backends")
        self.assertEqual(manifest["spec"]["transport"]["command"], "macrocli")
        self.assertEqual(manifest["spec"]["transport"]["argsTemplate"], ["backends", "--json"])
        self.assertEqual(manifest["metadata"]["annotations"]["cbn.external_protocol"], "agent-cli-contract")
        report = validate_manifest_dict(manifest)
        self.assertTrue(report["valid"], report["errors"])

    def test_cbn_mapping_uses_external_card_validator(self):
        card = json.loads((CONTRACT_ROOT / "fixtures/agent-cli-card.valid.json").read_text(encoding="utf-8"))
        card["spec"]["commands"][0]["policy"]["risk"] = "unsafe"

        with self.assertRaisesRegex(ValueError, "policy.risk is unsupported"):
            agent_cli_card_to_tool_manifests(card)

    def test_run_receipt_maps_to_bridge_message_and_correlation_records(self):
        receipt = json.loads((CONTRACT_ROOT / "fixtures/run-receipt.valid.json").read_text(encoding="utf-8"))
        records = run_receipt_to_cbn_records(receipt)
        self.assertEqual(records["kind"], "AgentCliRunReceiptMapping")
        self.assertEqual(records["audit_event"]["call_id"], "run-001")
        self.assertEqual(records["event"]["correlation_id"], "run-001")
        self.assertEqual(records["event"]["payload"]["artifact_count"], 1)
        message = records["message"]
        self.assertEqual(message["metadata"]["producer"], "example.macrocli.backends")
        self.assertEqual(message["metadata"]["channel"], "agent-cli.run.receipt")
        self.assertTrue(validate_bridge_message(message)["valid"])

    def test_cbn_mapping_uses_external_receipt_validator(self):
        receipt = json.loads((CONTRACT_ROOT / "fixtures/run-receipt.valid.json").read_text(encoding="utf-8"))
        receipt["status"] = "unknown"

        with self.assertRaisesRegex(ValueError, "status is unsupported"):
            run_receipt_to_cbn_records(receipt)


if __name__ == "__main__":
    unittest.main()
