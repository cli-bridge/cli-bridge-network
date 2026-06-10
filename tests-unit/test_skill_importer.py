import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cbn_core.skill_importer import read_skill_descriptor, skill_import_report


class SkillImporterTests(unittest.TestCase):
    def test_read_skill_descriptor_from_markdown_frontmatter(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_path = Path(temp_dir) / "SKILL.md"
            skill_path.write_text(
                "---\nid: note-summarizer\ntitle: Note Summarizer\nversion: 0.1.0\n---\n"
                "# Note Summarizer\nSummarize local notes.\n",
                encoding="utf-8",
            )
            descriptor = read_skill_descriptor(skill_path)
            self.assertEqual(descriptor["id"], "note-summarizer")
            self.assertEqual(descriptor["title"], "Note Summarizer")
            self.assertEqual(descriptor["version"], "0.1.0")

    def test_read_skill_descriptor_sniffs_json_without_suffix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_path = Path(temp_dir) / "skill.tmp"
            skill_path.write_text(
                json.dumps({"id": "note-summarizer", "title": "Note Summarizer"}, ensure_ascii=False),
                encoding="utf-8",
            )
            descriptor = read_skill_descriptor(skill_path)
            self.assertEqual(descriptor["id"], "note-summarizer")
            self.assertEqual(descriptor["title"], "Note Summarizer")

    def test_skill_import_report_builds_valid_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_path = Path(temp_dir) / "skill.json"
            skill_path.write_text(
                json.dumps(
                    {
                        "id": "note-summarizer",
                        "title": "Note Summarizer",
                        "summary": "Summarize local notes.",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            payload = skill_import_report(
                skill_path,
                command="python",
                args_template=("-m", "cbn_skill_runner", "note-summarizer"),
                known_parser_refs={"raw.text"},
            )
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["written"])
            self.assertEqual(payload["kind"], "SkillImportReport")
            self.assertEqual(payload["capability_id"], "skill.note-summarizer")
            manifest = payload["manifest"]
            self.assertEqual(manifest["metadata"]["labels"]["source"], "skill")
            self.assertEqual(manifest["metadata"]["annotations"]["cbn.skill.id"], "note-summarizer")
            self.assertIn("cbn import skill", payload["next_commands"][0])

    def test_cli_import_skill_can_write_manifest_to_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_path = Path(temp_dir) / "skill.json"
            target = Path(temp_dir) / "skill.note-summarizer.json"
            skill_path.write_text(
                json.dumps({"id": "note-summarizer", "title": "Note Summarizer"}, ensure_ascii=False),
                encoding="utf-8",
            )
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "cbn",
                    "import",
                    "skill",
                    str(skill_path),
                    "--command",
                    "python",
                    "--arg=-m",
                    "--arg",
                    "cbn_skill_runner",
                    "--arg",
                    "note-summarizer",
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
            manifest = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(manifest["metadata"]["id"], "skill.note-summarizer")
            self.assertEqual(manifest["spec"]["transport"]["argsTemplate"], ["-m", "cbn_skill_runner", "note-summarizer"])


if __name__ == "__main__":
    unittest.main()
