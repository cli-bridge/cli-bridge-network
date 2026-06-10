import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cbn_core.mcp_importer import mcp_import_report, select_mcp_tool


class McpImporterTests(unittest.TestCase):
    def test_mcp_import_report_builds_valid_manifest(self):
        payload = mcp_import_report(
            {
                "name": "search",
                "description": "Search docs",
                "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
            server_id="docs",
            adapter_command="python",
            adapter_args=("-m", "cbn_mcp_adapter", "--tool", "{tool_name}"),
            known_parser_refs={"raw.text"},
        )
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["written"])
        self.assertEqual(payload["kind"], "McpImportReport")
        self.assertEqual(payload["capability_id"], "mcp.docs.search")
        manifest = payload["manifest"]
        self.assertEqual(manifest["metadata"]["labels"]["protocol"], "mcp")
        self.assertEqual(manifest["spec"]["transport"]["argsTemplate"], ["-m", "cbn_mcp_adapter", "--tool", "search"])
        self.assertIn("cbn.mcp.input_schema", manifest["metadata"]["annotations"])

    def test_select_mcp_tool_requires_name_for_multiple_tools(self):
        with self.assertRaises(ValueError):
            select_mcp_tool({"tools": [{"name": "one"}, {"name": "two"}]})
        tool = select_mcp_tool({"tools": [{"name": "one"}, {"name": "two"}]}, tool_name="two")
        self.assertEqual(tool["name"], "two")

    def test_cli_import_mcp_can_write_manifest_to_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tool_path = Path(temp_dir) / "tool.json"
            target = Path(temp_dir) / "mcp.docs.search.json"
            tool_path.write_text(
                json.dumps(
                    {
                        "name": "search",
                        "description": "Search docs",
                        "inputSchema": {"type": "object"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "cbn",
                    "import",
                    "mcp",
                    "--tool-file",
                    str(tool_path),
                    "--server-id",
                    "docs",
                    "--adapter-command",
                    "python",
                    "--adapter-arg=-m",
                    "--adapter-arg",
                    "cbn_mcp_adapter",
                    "--adapter-arg=--tool",
                    "--adapter-arg",
                    "{tool_name}",
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
            self.assertEqual(manifest["metadata"]["id"], "mcp.docs.search")
            self.assertEqual(manifest["metadata"]["labels"]["mcp_tool"], "search")


if __name__ == "__main__":
    unittest.main()
