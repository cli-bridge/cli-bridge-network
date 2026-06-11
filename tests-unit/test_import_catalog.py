import json
import subprocess
import sys
import unittest

from cbn_core.import_catalog import cli_registration_surface


class ImportCatalogTests(unittest.TestCase):
    def test_cli_registration_surface_lists_dry_run_first_importers(self):
        payload = cli_registration_surface()

        self.assertEqual(payload["kind"], "CliRegistrationSurface")
        self.assertEqual(payload["status"], "ready")
        self.assertTrue(payload["default_policy"]["dry_run_by_default"])
        self.assertTrue(payload["default_policy"]["writes_require_explicit_flag"])
        self.assertTrue(payload["default_policy"]["side_effects_require_confirmation"])
        importers = {importer["id"]: importer for importer in payload["importers"]}
        self.assertEqual(
            set(importers),
            {"command", "cli-anything", "agent-cli-card", "mcp", "skill", "parser-fixture"},
        )
        self.assertEqual(importers["command"]["entrypoint"], "cbn import command")
        self.assertIn("--command echo", importers["command"]["example"])
        self.assertEqual(importers["agent-cli-card"]["entrypoint"], "cbn import agent-cli-card")
        self.assertIn("--card-file", importers["agent-cli-card"]["example"])
        self.assertEqual(importers["parser-fixture"]["entrypoint"], "cbn record-parser-fixture")
        self.assertIn("python -m cbn import catalog", payload["next_commands"][0])

    def test_import_catalog_cli_outputs_same_surface(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn", "import", "catalog"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)

        self.assertEqual(payload["kind"], "CliRegistrationSurface")
        self.assertEqual(payload["importer_count"], 6)
        self.assertIn("python -m cbn import cli-anything --help", payload["next_commands"])
        self.assertTrue(all(importer["default_side_effects"] == "none" for importer in payload["importers"]))


if __name__ == "__main__":
    unittest.main()
