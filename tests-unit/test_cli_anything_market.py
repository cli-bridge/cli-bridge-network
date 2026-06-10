import unittest

from cbn_plugins.cli_anything_parts.market import (
    CAPABILITY_COLLISION_ERROR,
    market_record_identity,
    market_records_from_result,
    mark_candidate_collisions,
    mark_capability_collisions,
)


class CliAnythingMarketTests(unittest.TestCase):
    def test_market_records_from_result_accepts_supported_list_shapes(self):
        direct = [{"name": "gimp"}, "ignored", {"name": "ffmpeg"}]
        self.assertEqual(market_records_from_result(direct), [{"name": "gimp"}, {"name": "ffmpeg"}])

        for key in ("items", "harnesses", "tools", "results", "data"):
            self.assertEqual(
                market_records_from_result({key: [{"name": key}], "other": []}),
                [{"name": key}],
            )

    def test_market_records_from_result_rejects_unsupported_shapes(self):
        self.assertIsNone(market_records_from_result(None))
        self.assertIsNone(market_records_from_result({"unexpected": [{"name": "gimp"}]}))
        self.assertIsNone(market_records_from_result("[]"))

    def test_market_record_identity_extracts_stable_collision_source(self):
        identity = market_record_identity(
            {
                "market_record": {
                    "name": "gimp",
                    "display_name": "GIMP",
                    "entry_point": "cli-anything-gimp",
                    "_source": "harness",
                }
            }
        )

        self.assertEqual(
            identity,
            {
                "name": "gimp",
                "display_name": "GIMP",
                "entry_point": "cli-anything-gimp",
                "source": "harness",
            },
        )

    def test_mark_capability_collisions_blocks_duplicate_manifest_imports(self):
        manifests = [
            {
                "ok": True,
                "capability_id": "cli-anything.gimp.launch",
                "market_record": {"name": "gimp", "_source": "harness"},
            },
            {
                "ok": True,
                "capability_id": "cli-anything.gimp.launch",
                "market_record": {"name": "GIMP!", "_source": "public"},
            },
            {
                "ok": True,
                "capability_id": "cli-anything.inkscape.launch",
                "market_record": {"name": "inkscape"},
            },
        ]

        mark_capability_collisions(manifests)

        self.assertFalse(manifests[0]["ok"])
        self.assertFalse(manifests[1]["ok"])
        self.assertTrue(manifests[2]["ok"])
        self.assertEqual(manifests[0]["error"], CAPABILITY_COLLISION_ERROR)
        self.assertEqual(manifests[0]["collision"]["capability_id"], "cli-anything.gimp.launch")
        self.assertEqual(len(manifests[0]["collision"]["market_records"]), 2)
        self.assertNotIn("collision", manifests[2])

    def test_mark_candidate_collisions_blocks_duplicate_install_candidates(self):
        candidates = [
            {
                "install_candidate": True,
                "recommended_next_action": "install_harness",
                "blockers": [],
                "capability_id": "cli-anything.gimp.launch",
                "market_record": {"name": "gimp", "_source": "harness"},
            },
            {
                "install_candidate": True,
                "recommended_next_action": "install_harness",
                "blockers": [],
                "capability_id": "cli-anything.gimp.launch",
                "market_record": {"name": "GIMP!", "_source": "public"},
            },
        ]

        mark_candidate_collisions(candidates)

        self.assertFalse(candidates[0]["install_candidate"])
        self.assertFalse(candidates[1]["install_candidate"])
        self.assertEqual(candidates[0]["recommended_next_action"], "resolve_blockers")
        self.assertIn(CAPABILITY_COLLISION_ERROR, candidates[0]["blockers"])
        self.assertEqual(len(candidates[0]["collision"]["market_records"]), 2)


if __name__ == "__main__":
    unittest.main()
