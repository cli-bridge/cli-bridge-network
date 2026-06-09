from pathlib import Path
import unittest


class DashboardStaticTests(unittest.TestCase):
    def setUp(self):
        self.root = Path("packages/dashboard/src")
        self.html = (self.root / "index.html").read_text(encoding="utf-8")
        self.js = (self.root / "app.js").read_text(encoding="utf-8")

    def test_cli_anything_lifecycle_buttons_exist(self):
        for label in ["Download / Clone", "Install", "Check Updates", "Update", "Install PTY Backend"]:
            self.assertIn(label, self.html)
        self.assertIn("Candidate Summary", self.html)
        self.assertIn("candidateSummary", self.html)
        self.assertIn("clearCandidates", self.html)
        self.assertIn("Operation Detail", self.html)
        self.assertIn("operationDetail", self.html)
        self.assertIn("clearOperationDetail", self.html)

    def test_cli_anything_commands_are_staged(self):
        self.assertIn("python -m cbn plugin plan cli-anything", self.html)
        self.assertIn("python -m cbn plugin preflight cli-anything", self.html)
        self.assertIn("python -m cbn plugin install cli-anything --yes", self.html)
        self.assertIn("python -m cbn plugin install cli-anything --yes --allow-failed-preflight", self.html)
        self.assertIn("python -m cbn plugin update cli-anything --yes", self.html)
        self.assertIn("python -m cbn plugin update cli-anything --yes --allow-failed-preflight", self.html)
        self.assertIn("python -m cbn plugin status cli-anything", self.html)
        self.assertIn("python -m cbn runtime transport pty", self.html)
        self.assertIn("python -m cbn runtime transport pty --plan", self.html)
        self.assertIn("python -m cbn runtime transport pty --install --yes", self.html)
        self.assertIn("/runtime/transports?kind=pty", self.html)
        self.assertIn("/runtime/transports/install", self.html)
        self.assertIn("python -m cbn plugin provenance cli-anything", self.html)
        self.assertIn("python -m cbn plugin gate cli-anything --action install", self.html)
        self.assertIn("python -m cbn plugin gate cli-anything --action update", self.html)
        self.assertIn("python -m cbn plugin market cli-anything list", self.html)
        self.assertIn("python -m cbn plugin candidates cli-anything --query image --limit 20 --compact", self.html)
        self.assertIn(
            "python -m cbn plugin candidates cli-anything --query image --limit 20 --with-probes --compact",
            self.html,
        )
        self.assertIn('{"query":"image","limit":20,"compact":true}', self.html)
        self.assertIn('{"query":"image","limit":20,"with_probes":true,"compact":true}', self.html)
        self.assertIn("python -m cbn plugin probe-harness cli-anything mermaid", self.html)
        self.assertIn("python -m cbn plugin verify-harness cli-anything mermaid", self.html)
        self.assertIn("python -m cbn plugin import-harness cli-anything gimp", self.html)
        self.assertIn("python -m cbn plugin harness cli-anything install gimp", self.html)
        self.assertIn("python -m cbn event tail", self.html)
        self.assertIn("python -m cbn artifact list", self.html)
        self.assertIn("python -m cbn approvals list", self.html)
        self.assertIn("python -m cbn workflow list", self.html)
        self.assertIn("python -m cbn workflow run workflows/example.json --dry-run", self.html)
        self.assertIn("python -m cbn workflow run workflows/cli-anything-macrocli-mermaid-routing.example.json", self.html)
        self.assertIn("python -m cbn parser list", self.html)
        self.assertIn("python -m cbn protocol export all", self.html)
        self.assertIn("python -m cbn protocol export-workflows all", self.html)
        self.assertIn("python -m cbn protocol check all --capability-id cli-anything.mermaid.set-diagram", self.html)
        self.assertIn("python -m cbn protocol check all --workflow-path workflows/artifact-id-routing.example.json", self.html)
        self.assertIn("python -m cbn protocol matrix --include-workflows", self.html)
        self.assertIn("python -m cbn protocol readiness", self.html)
        self.assertIn("/protocols/readiness", self.html)
        self.assertIn("python -m cbn message contract", self.html)
        self.assertIn("/messages/contract", self.html)
        self.assertIn("python -m cbn plugin evaluate-harness cli-anything macrocli", self.html)
        self.assertIn("python -m cbn plugin harness cli-anything install macrocli --yes", self.html)
        self.assertIn("python -m cbn call cli-anything.macrocli.backends", self.html)
        self.assertIn("python -m cbn mcp smoke --capability-id git.version", self.html)
        self.assertIn("python -m cbn a2a smoke --capability-id git.version", self.html)
        self.assertIn("python -m cbn acp smoke --capability-id git.version", self.html)

    def test_static_js_queues_commands(self):
        self.assertIn("stageCommand", self.js)
        self.assertIn("commandQueue", self.js)
        self.assertIn("renderCandidateSummary", self.js)
        self.assertIn("displayPayload", self.js)
        self.assertIn("candidateSummaryFromCandidates", self.js)
        self.assertIn("candidateAction", self.js)
        self.assertIn("renderOperationDetail", self.js)
        self.assertIn("operationBlockers", self.js)
        self.assertIn("operationCommands", self.js)
        self.assertIn("/plugins/cli-anything/evaluate-harness", self.js)
        self.assertIn("/plugins/cli-anything/prepare-harness", self.js)
        self.assertIn("/plugins/cli-anything/harness", self.js)


if __name__ == "__main__":
    unittest.main()
