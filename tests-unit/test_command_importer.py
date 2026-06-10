import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cbn_core.command_importer import command_import_report


class CommandImporterTests(unittest.TestCase):
    def test_command_import_report_builds_valid_manifest_without_write(self):
        payload = command_import_report(
            capability_id="local.echo",
            command="python",
            args_template=("-c", "print('ok')"),
            title="Local Echo",
            parser_ref="raw.text",
            known_parser_refs={"raw.text"},
        )
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["written"])
        self.assertEqual(payload["kind"], "CommandImportReport")
        self.assertEqual(payload["manifest"]["metadata"]["id"], "local.echo")
        self.assertEqual(payload["manifest"]["spec"]["transport"]["command"], "python")
        self.assertEqual(payload["manifest"]["spec"]["transport"]["argsTemplate"], ["-c", "print('ok')"])

    def test_cli_import_command_can_write_manifest_to_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "local.echo.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "cbn",
                    "import",
                    "command",
                    "local.echo",
                    "--command",
                    "python",
                    "--arg=-c",
                    "--arg",
                    "print('ok')",
                    "--output",
                    str(target),
                    "--write",
                ],
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["written"])
            self.assertTrue(target.exists())
            manifest = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(manifest["kind"], "ToolManifest")
            self.assertEqual(manifest["metadata"]["id"], "local.echo")


if __name__ == "__main__":
    unittest.main()
