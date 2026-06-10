import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cbn_core.agent_cli_importer import agent_cli_card_import_report


CONTRACT_ROOT = Path("external_protocols/agent-cli-contract")
CARD_PATH = CONTRACT_ROOT / "fixtures/agent-cli-card.valid.json"


class AgentCliImporterTests(unittest.TestCase):
    def test_agent_cli_card_import_report_builds_valid_manifests(self):
        payload = agent_cli_card_import_report(
            CARD_PATH,
            output_dir=Path("runtime/manifests"),
            known_parser_refs={"raw.text"},
        )
        self.assertTrue(payload["ok"], payload["errors"])
        self.assertFalse(payload["write"])
        self.assertEqual(payload["kind"], "AgentCliCardImportReport")
        self.assertEqual(payload["card_id"], "example.macrocli")
        self.assertEqual(payload["summary"]["manifest_count"], 1)
        entry = payload["manifests"][0]
        self.assertFalse(entry["written"])
        self.assertEqual(entry["capability_id"], "example.macrocli.backends")
        self.assertEqual(entry["manifest"]["metadata"]["annotations"]["cbn.external_protocol"], "agent-cli-contract")

    def test_agent_cli_card_import_report_writes_to_output_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            payload = agent_cli_card_import_report(
                CARD_PATH,
                write=True,
                output_dir=Path(temp_dir),
                known_parser_refs={"raw.text"},
            )
            self.assertTrue(payload["ok"], payload["errors"])
            self.assertEqual(payload["summary"]["written_count"], 1)
            target = Path(temp_dir) / "example.macrocli.backends.json"
            self.assertTrue(target.exists())
            manifest = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(manifest["metadata"]["id"], "example.macrocli.backends")

    def test_cli_import_agent_cli_card_reports_draft(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "import",
                "agent-cli-card",
                "--card-file",
                str(CARD_PATH),
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"], proc.stderr)
        self.assertEqual(payload["kind"], "AgentCliCardImportReport")
        self.assertEqual(payload["card_id"], "example.macrocli")
        self.assertEqual(payload["summary"]["manifest_count"], 1)


if __name__ == "__main__":
    unittest.main()
