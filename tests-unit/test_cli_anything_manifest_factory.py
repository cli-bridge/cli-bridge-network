import json
import unittest

from cbn_plugins.cli_anything_parts.manifest_factory import (
    build_harness_manifest,
    preserve_existing_parser_contract,
)


SAMPLE_MARKET_RECORD = {
    "name": "gimp",
    "display_name": "GIMP",
    "category": "image",
    "_source": "harness",
    "version": "1.0.0",
    "description": "Generate and edit image assets locally",
    "requires": "gimp (apt install gimp)",
    "entry_point": "cli-anything-gimp",
    "contributors": "CLI-Anything-Team",
}


class CliAnythingManifestFactoryTests(unittest.TestCase):
    def test_build_harness_manifest_uses_pty_launch_boundary(self):
        manifest = build_harness_manifest(
            "gimp",
            entrypoint="cli-hub",
            market_record=SAMPLE_MARKET_RECORD,
        )

        self.assertEqual(manifest["metadata"]["id"], "cli-anything.gimp.launch")
        self.assertEqual(manifest["metadata"]["title"], "CLI-Anything GIMP")
        self.assertEqual(manifest["metadata"]["labels"]["plugin"], "cli-anything")
        self.assertEqual(manifest["metadata"]["labels"]["harness"], "gimp")
        self.assertEqual(manifest["metadata"]["labels"]["category"], "image")
        self.assertEqual(manifest["metadata"]["labels"]["source"], "harness")
        self.assertEqual(
            manifest["metadata"]["annotations"]["cli-anything.entry_point"],
            "cli-anything-gimp",
        )
        self.assertEqual(manifest["spec"]["transport"]["kind"], "pty")
        self.assertEqual(manifest["spec"]["transport"]["command"], "cli-hub")
        self.assertEqual(manifest["spec"]["transport"]["argsTemplate"], ["launch", "gimp", "--"])
        self.assertEqual(manifest["spec"]["policy"]["risk"], "write-workspace")
        self.assertEqual(manifest["spec"]["policy"]["network"], "deny")
        self.assertFalse(manifest["spec"]["policy"]["requiresConfirmation"])
        self.assertEqual(manifest["spec"]["output"]["parserRef"], "cli-anything.raw")
        self.assertFalse(manifest["spec"]["output"]["verified"])

    def test_build_harness_manifest_infers_external_network_policy(self):
        manifest = build_harness_manifest(
            "generate-veo-video",
            entrypoint="cli-hub",
            market_record={
                "name": "generate-veo-video",
                "display_name": "Generate Veo Video",
                "description": "Generate videos with Google Veo via Vertex AI and Gemini",
                "requires": "GOOGLE_CLOUD_PROJECT and GEMINI_API_KEY",
            },
        )

        policy = manifest["spec"]["policy"]
        self.assertEqual(policy["risk"], "external-network")
        self.assertTrue(policy["requiresConfirmation"])
        self.assertEqual(policy["network"], "requires-confirmation")
        reasons = json.loads(manifest["metadata"]["annotations"]["cli-anything.policy_inference"])
        self.assertIn("runtime mentions external API, cloud service, token, or API key", reasons)

    def test_preserve_existing_parser_contract_carries_verified_parser_metadata(self):
        generated = build_harness_manifest("gimp", entrypoint="cli-hub")
        existing = {
            "metadata": {
                "annotations": {
                    "cbn.parser.schema": "direct-cli/v1",
                    "cbn.parser.fixture": "parser_fixtures/gimp.case.json",
                    "unrelated": "ignored",
                }
            },
            "spec": {
                "output": {
                    "parserRef": "cli-anything.raw",
                    "verified": True,
                }
            },
        }

        preserved = preserve_existing_parser_contract(existing=existing, generated=generated)

        self.assertTrue(preserved["spec"]["output"]["verified"])
        self.assertEqual(
            preserved["metadata"]["annotations"]["cbn.parser.schema"],
            "direct-cli/v1",
        )
        self.assertEqual(
            preserved["metadata"]["annotations"]["cbn.parser.fixture"],
            "parser_fixtures/gimp.case.json",
        )
        self.assertNotIn("unrelated", preserved["metadata"]["annotations"])


if __name__ == "__main__":
    unittest.main()
