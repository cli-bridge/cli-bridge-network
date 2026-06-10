import json
import subprocess
import sys
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
