import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cbn_parsers.fixture_recorder import record_parser_fixture


class ParserFixtureRecorderTests(unittest.TestCase):
    def test_record_parser_fixture_previews_valid_fixture(self):
        payload = record_parser_fixture(
            parser_ref="raw.text",
            case_id="local-hello",
            stdout="hello\n",
            verified_capabilities=("local.hello",),
        )
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["written"])
        self.assertEqual(payload["kind"], "ParserFixtureRecordReport")
        self.assertEqual(payload["validation"]["failed_case_count"], 0)
        self.assertEqual(payload["fixture"]["metadata"]["parserRef"], "raw.text")
        self.assertEqual(payload["fixture"]["cases"][0]["expect"]["data"]["stdout"]["equals"], "hello\n")

    def test_record_parser_fixture_writes_target_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "raw.text.local-hello.json"
            payload = record_parser_fixture(
                parser_ref="raw.text",
                case_id="local-hello",
                stdout="hello\n",
                output_path=target,
                write=True,
            )
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["written"])
            fixture = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(fixture["kind"], "ParserFixture")
            self.assertEqual(fixture["cases"][0]["stdout"], "hello\n")

    def test_cli_record_parser_fixture_outputs_report(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "record-parser-fixture",
                "raw.text",
                "local-hello",
                "--stdout",
                "hello\n",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["parser_ref"], "raw.text")
        self.assertEqual(payload["case_id"], "local-hello")


if __name__ == "__main__":
    unittest.main()
