from pathlib import Path
import unittest


class DashboardStaticTests(unittest.TestCase):
    def setUp(self):
        self.root = Path("packages/dashboard/src")
        self.html = (self.root / "index.html").read_text(encoding="utf-8")
        self.js = (self.root / "app.js").read_text(encoding="utf-8")

    def test_cli_anything_lifecycle_buttons_exist(self):
        for label in ["Download / Clone", "Install", "Check Updates", "Update"]:
            self.assertIn(label, self.html)

    def test_cli_anything_commands_are_staged(self):
        self.assertIn("python -m cbn plugin plan cli-anything", self.html)
        self.assertIn("python -m cbn plugin preflight cli-anything", self.html)
        self.assertIn("python -m cbn plugin install cli-anything --yes", self.html)
        self.assertIn("python -m cbn plugin update cli-anything --yes", self.html)
        self.assertIn("python -m cbn plugin status cli-anything", self.html)
        self.assertIn("python -m cbn plugin market cli-anything list", self.html)
        self.assertIn("python -m cbn plugin candidates cli-anything --query image --limit 20", self.html)
        self.assertIn("python -m cbn plugin probe-harness cli-anything mermaid", self.html)
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
        self.assertIn("python -m cbn plugin evaluate-harness cli-anything macrocli", self.html)
        self.assertIn("python -m cbn plugin harness cli-anything install macrocli --yes", self.html)
        self.assertIn("python -m cbn call cli-anything.macrocli.backends", self.html)
        self.assertIn("python -m cbn mcp smoke --capability-id git.version", self.html)
        self.assertIn("python -m cbn a2a smoke --capability-id git.version", self.html)
        self.assertIn("python -m cbn acp smoke --capability-id git.version", self.html)

    def test_static_js_queues_commands(self):
        self.assertIn("stageCommand", self.js)
        self.assertIn("commandQueue", self.js)


if __name__ == "__main__":
    unittest.main()
