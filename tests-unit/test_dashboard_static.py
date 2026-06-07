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
        self.assertIn("python -m cbn plugin install cli-anything --yes", self.html)
        self.assertIn("python -m cbn plugin update cli-anything --yes", self.html)

    def test_static_js_queues_commands(self):
        self.assertIn("stageCommand", self.js)
        self.assertIn("commandQueue", self.js)


if __name__ == "__main__":
    unittest.main()
