import json
import subprocess
import sys
import unittest
from pathlib import Path

from cbn_core.manifest import ManifestRegistry
from cbn_protocol.exports import export_all_protocols, export_protocol, list_protocol_exports


class ProtocolExportTests(unittest.TestCase):
    def setUp(self):
        self.registry = ManifestRegistry()
        self.registry.load_dir(Path("manifests"))

    def test_protocol_export_list_is_explicitly_descriptor_only(self):
        exports = list_protocol_exports()
        self.assertEqual({item["protocol"] for item in exports}, {"mcp", "a2a", "acp"})
        self.assertTrue(all(item["wire_compatible"] is False for item in exports))

    def test_mcp_export_maps_capability_to_tool(self):
        payload = export_protocol(self.registry, "mcp", capability_id="git.status")
        self.assertFalse(payload["wire_compatible"])
        self.assertEqual(payload["tools"][0]["name"], "git.status")
        self.assertEqual(payload["tools"][0]["_meta"]["cbn"]["parser_ref"], "git.status.short")

    def test_a2a_and_acp_exports_include_git_status(self):
        payload = export_all_protocols(self.registry, capability_id="git.status")
        self.assertEqual(payload["exports"]["a2a"]["agentCard"]["skills"][0]["id"], "git.status")
        self.assertEqual(payload["exports"]["acp"]["tools"][0]["id"], "git.status")

    def test_cli_protocol_export(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn", "protocol", "export", "mcp", "--capability-id", "git.status"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["protocol"], "mcp")
        self.assertEqual(payload["tools"][0]["name"], "git.status")


if __name__ == "__main__":
    unittest.main()
