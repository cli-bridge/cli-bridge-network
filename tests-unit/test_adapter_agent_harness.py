import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cbn_adapter_agent.compiler import (
    build_adapter_draft,
    build_adapter_draft_batch,
    write_adapter_draft,
)


class AdapterAgentHarnessTests(unittest.TestCase):
    def test_adapter_agent_draft_collects_profile_candidates(self):
        draft = build_adapter_draft("jimeng")

        self.assertEqual(draft["kind"], "AdapterAgentDraft")
        self.assertEqual(draft["profile"]["profile_id"], "jimeng")
        self.assertFalse(draft["agent_policy"]["llm_runtime_dependency"])

        candidates = {item["capability_id"]: item for item in draft["capability_candidates"]}
        self.assertIn("jimeng.version", candidates)
        self.assertIn("jimeng.text2image.submit", candidates)
        self.assertEqual(candidates["jimeng.version"]["policy"]["risk"], "read")
        self.assertEqual(candidates["jimeng.text2image.submit"]["policy"]["risk"], "external-network")

    def test_adapter_agent_draft_keeps_unverified_outputs_partial(self):
        draft = build_adapter_draft("caw")
        stages = {stage["id"]: stage for stage in draft["stages"]}

        self.assertEqual(stages["parser_contracts"]["status"], "partial")
        self.assertIn("caw.status", stages["parser_contracts"]["evidence"]["unverified_capabilities"])
        self.assertIn("present structured diff", " ".join(draft["next_actions"]))

    def test_adapter_agent_batch_summarizes_all_profiles(self):
        batch = build_adapter_draft_batch()

        self.assertEqual(batch["kind"], "AdapterAgentDraftBatch")
        self.assertEqual(batch["summary"]["profile_count"], 4)
        self.assertGreaterEqual(batch["summary"]["candidate_count"], 17)

    def test_adapter_agent_cli_outputs_json(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn_adapter_agent", "--profile", "feishu"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)

        self.assertEqual(payload["profile"]["profile_id"], "feishu")
        self.assertTrue(payload["adapter_lock_preview"]["digest"])
        self.assertEqual(proc.stderr, "")

    def test_adapter_agent_write_draft_uses_utf8_json(self):
        draft = build_adapter_draft("obsidian-cli")
        with tempfile.TemporaryDirectory() as tmp:
            result = write_adapter_draft(draft, output_dir=Path(tmp))
            payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))

        self.assertEqual(payload["profile"]["profile_id"], "obsidian-cli")


if __name__ == "__main__":
    unittest.main()
