import json
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from cbn_tools.macrocli_backends_to_mermaid import build_mermaid_source, main, write_mermaid_source


class MacrocliMermaidTransformTests(unittest.TestCase):
    def test_build_mermaid_source_from_parser_payload(self):
        payload = {
            "backend_count": 2,
            "available_count": 1,
            "backends": [
                {"id": "native_api", "name": "native_api", "priority": 100, "available": True},
                {"id": "semantic-ui", "name": "semantic-ui", "priority": 50, "available": False},
            ],
        }
        source = build_mermaid_source(payload)
        self.assertIn("flowchart LR", source)
        self.assertIn('summary["MacroCLI Backends\\n2 total"]', source)
        self.assertIn('native_api["native_api\\npriority 100\\navailable"]:::available', source)
        self.assertIn('semantic_ui["semantic-ui\\npriority 50\\nunavailable"]:::unavailable', source)

    def test_write_mermaid_source_uses_utf8_file(self):
        payload = {
            "backends": [
                {"id": "cn_backend", "name": "中文后端", "priority": 10, "available": True},
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = write_mermaid_source(payload, Path(tmp) / "diagram.mmd")
            self.assertIn("中文后端", path.read_text(encoding="utf-8"))

    def test_cli_accepts_json_file_and_prints_output_path(self):
        payload = {
            "backends": [
                {"id": "native_api", "name": "native_api", "priority": 100, "available": True},
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "payload.json"
            output_path = Path(tmp) / "diagram.mmd"
            input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main([str(input_path), "--output", str(output_path)])
            self.assertEqual(code, 0)
            self.assertEqual(stdout.getvalue(), output_path.as_posix())
            self.assertTrue(output_path.exists())


if __name__ == "__main__":
    unittest.main()
