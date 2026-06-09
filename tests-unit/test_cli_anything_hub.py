import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cbn_core.manifest import CapabilityManifest
from cbn_plugins.cli_anything import (
    CliAnythingHub,
    CliHubCommandResult,
    infer_market_policy,
    sanitize_harness_name,
)


SAMPLE_MARKET_RECORD = {
    "name": "gimp",
    "display_name": "GIMP",
    "version": "1.0.0",
    "description": "Raster image processing via gimp -i -b (batch mode)",
    "requires": "gimp (apt install gimp)",
    "homepage": "https://www.gimp.org",
    "install_cmd": "pip install git+https://github.com/HKUDS/CLI-Anything.git#subdirectory=gimp/agent-harness",
    "entry_point": "cli-anything-gimp",
    "skill_md": "skills/cli-anything-gimp/SKILL.md",
    "category": "image",
    "contributors": [{"name": "CLI-Anything-Team", "url": "https://github.com/HKUDS/CLI-Anything"}],
    "_source": "harness",
}

SAMPLE_MERMAID_RECORD = {
    "name": "mermaid",
    "display_name": "Mermaid",
    "version": "1.0.0",
    "description": "Mermaid Live Editor state files and renderer URLs",
    "requires": None,
    "homepage": "https://mermaid.js.org",
    "install_cmd": "pip install git+https://github.com/HKUDS/CLI-Anything.git#subdirectory=mermaid/agent-harness",
    "entry_point": "cli-anything-mermaid",
    "category": "diagrams",
    "_source": "harness",
}

SAMPLE_3MF_RECORD = {
    "name": "3mf",
    "display_name": "3MF Tools",
    "version": "1.0.0",
    "description": "Inspect and transform 3MF model files",
    "requires": "Python 3.10+; numpy, scipy, trimesh",
    "install_cmd": "pip install git+https://github.com/HKUDS/CLI-Anything.git#subdirectory=3mf/agent-harness",
    "entry_point": "cli-anything-3mf",
    "category": "file",
    "_source": "harness",
}

SAMPLE_BLENDER_RECORD = {
    "name": "blender",
    "display_name": "Blender",
    "version": "1.0.0",
    "description": "3D modeling, animation, and rendering via blender --background --python",
    "requires": "blender >= 4.2",
    "install_cmd": "pip install git+https://github.com/HKUDS/CLI-Anything.git#subdirectory=blender/agent-harness",
    "entry_point": "cli-anything-blender",
    "category": "3d",
    "_source": "harness",
}

SAMPLE_LIBREOFFICE_RECORD = {
    "name": "libreoffice",
    "display_name": "LibreOffice",
    "version": "1.0.1",
    "description": "Create and manipulate ODF documents, export to PDF/DOCX/XLSX/PPTX via headless mode",
    "requires": "libreoffice",
    "install_cmd": "pip install git+https://github.com/HKUDS/CLI-Anything.git#subdirectory=libreoffice/agent-harness",
    "entry_point": "cli-anything-libreoffice",
    "category": "office",
    "_source": "harness",
}

SAMPLE_OBS_STUDIO_RECORD = {
    "name": "obs-studio",
    "display_name": "OBS Studio",
    "version": "1.0.0",
    "description": "Control OBS Studio recording and streaming sessions.",
    "requires": "obs-studio",
    "install_cmd": "pip install git+https://github.com/HKUDS/CLI-Anything.git#subdirectory=obs-studio/agent-harness",
    "entry_point": "cli-anything-obs-studio",
    "category": "video",
    "_source": "harness",
}

SAMPLE_N8N_RECORD = {
    "name": "n8n",
    "display_name": "n8n",
    "version": "2.4.7",
    "description": "Workflow automation via n8n REST API - 55+ commands",
    "requires": "n8n >= 1.0.0",
    "install_cmd": "pip install git+https://github.com/HKUDS/CLI-Anything.git#subdirectory=n8n/agent-harness",
    "entry_point": "cli-anything-n8n",
    "category": "automation",
    "_source": "harness",
}

SAMPLE_UNIMOL_RECORD = {
    "name": "unimol_tools",
    "display_name": "Uni-Mol Tools",
    "version": "1.0.0",
    "description": "Molecular property prediction, train and predict for drug discovery.",
    "requires": "PyTorch 1.12+, Uni-Mol Tools backend",
    "install_cmd": "pip install git+https://github.com/HKUDS/CLI-Anything.git#subdirectory=unimol_tools/agent-harness",
    "entry_point": "cli-anything-unimol-tools",
    "category": "science",
    "_source": "harness",
}


class CliAnythingHubTests(unittest.TestCase):
    def test_sanitize_harness_name_keeps_manifest_safe(self):
        self.assertEqual(sanitize_harness_name("GIMP"), "gimp")
        self.assertEqual(sanitize_harness_name("image tools/gimp"), "image-tools-gimp")
        with self.assertRaises(ValueError):
            sanitize_harness_name("   ")

    def test_status_handles_missing_cli_hub_without_failing(self):
        hub = CliAnythingHub(entrypoint="cbn-cli-hub-that-does-not-exist")
        status = hub.status()
        self.assertEqual(status["plugin_id"], "cli-anything")
        self.assertFalse(status["entrypoint_available"])
        self.assertIsNone(status["entrypoint_path"])

    def test_market_command_handles_missing_cli_hub_without_failing(self):
        hub = CliAnythingHub(entrypoint="cbn-cli-hub-that-does-not-exist")
        result = hub.list_market()
        self.assertEqual(result.exit_code, 127)
        self.assertIn("not installed", result.stderr)

    def test_harness_status_handles_missing_cli_hub(self):
        hub = CliAnythingHub(entrypoint="cbn-cli-hub-that-does-not-exist")
        status = hub.harness_status("gimp")
        self.assertFalse(status["cli_hub_available"])
        self.assertFalse(status["installed"])
        self.assertFalse(status["launch_ready"])

    def test_market_record_lookup_handles_missing_cli_hub(self):
        hub = CliAnythingHub(entrypoint="cbn-cli-hub-that-does-not-exist")
        self.assertIsNone(hub.market_record_for_harness("gimp"))

    def test_market_record_lookup_skips_bad_market_records(self):
        class FakeHub(CliAnythingHub):
            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[{"name": ""}, SAMPLE_MARKET_RECORD],
                )

        self.assertEqual(FakeHub().market_record_for_harness("gimp")["name"], "gimp")

    def test_harness_status_reports_entrypoint_and_manifest(self):
        class FakeHub(CliAnythingHub):
            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout=f"Entry point: {sys.executable}\nStatus: installed\n",
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_MARKET_RECORD],
                )

        with tempfile.TemporaryDirectory() as tmp:
            hub = FakeHub(root=Path(tmp))
            hub.write_harness_manifest("gimp", market_record=SAMPLE_MARKET_RECORD)
            status = hub.harness_status("gimp", from_market=True)
            self.assertTrue(status["installed"])
            self.assertTrue(status["launch_ready"])
            self.assertTrue(status["manifest_imported"])
            self.assertTrue(status["entrypoint_available"])
            self.assertTrue(status["market_record_available"])

    def test_adapt_harness_previews_manifest_status_and_next_commands(self):
        class FakeHub(CliAnythingHub):
            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout="Entry point: cli-anything-gimp\nStatus: not installed\n",
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_MARKET_RECORD],
                )

        with tempfile.TemporaryDirectory() as tmp:
            result = FakeHub(root=Path(tmp)).adapt_harness("gimp", from_market=True)
            self.assertTrue(result["ok"])
            self.assertFalse(result["write"])
            self.assertIsNone(result["written"])
            self.assertTrue(result["market_record_available"])
            self.assertEqual(result["manifest"]["metadata"]["id"], "cli-anything.gimp.launch")
            self.assertTrue(result["validation"]["valid"])
            self.assertFalse(result["status"]["manifest_imported"])
            self.assertIn("python -m cbn call cli-anything.gimp.launch --dry-run", result["next_commands"])

    def test_adapt_harness_write_imports_manifest(self):
        class FakeHub(CliAnythingHub):
            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout=f"Entry point: {sys.executable}\nStatus: installed\n",
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_MARKET_RECORD],
                )

        with tempfile.TemporaryDirectory() as tmp:
            result = FakeHub(root=Path(tmp)).adapt_harness("gimp", from_market=True, write=True)
            self.assertTrue(result["ok"])
            self.assertTrue(result["write"])
            self.assertTrue(Path(result["written"]).exists())
            self.assertTrue(result["status"]["manifest_imported"])

    def test_adapt_harness_write_preserves_verified_parser_contract(self):
        class FakeHub(CliAnythingHub):
            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout=f"Entry point: {sys.executable}\nStatus: installed\n",
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_MARKET_RECORD],
                )

        with tempfile.TemporaryDirectory() as tmp:
            hub = FakeHub(root=Path(tmp))
            existing = hub.manifest_for_harness("gimp", market_record=SAMPLE_MARKET_RECORD)
            existing["spec"]["output"]["verified"] = True
            existing["metadata"].setdefault("annotations", {})[
                "cbn.parser_fixture"
            ] = "parser_fixtures/cli-anything.raw.launch.json"
            path = Path(tmp) / "manifests" / "cli-anything.gimp.launch.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            result = hub.adapt_harness("gimp", from_market=True, write=True)

            self.assertTrue(result["ok"])
            self.assertTrue(result["manifest"]["spec"]["output"]["verified"])
            self.assertEqual(
                result["manifest"]["metadata"]["annotations"]["cbn.parser_fixture"],
                "parser_fixtures/cli-anything.raw.launch.json",
            )
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(persisted["spec"]["output"]["verified"])

    def test_prepare_harness_returns_gates_and_lifecycle_plans(self):
        class FakeHub(CliAnythingHub):
            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout=f"Entry point: {sys.executable}\nStatus: installed\n",
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_MARKET_RECORD],
                )

        with tempfile.TemporaryDirectory() as tmp:
            result = FakeHub(root=Path(tmp)).prepare_harness("gimp", from_market=True)
            self.assertTrue(result["ok"])
            self.assertTrue(result["gates"]["manifest_valid"])
            self.assertTrue(result["gates"]["market_required_satisfied"])
            self.assertTrue(result["gates"]["launch_ready"])
            self.assertEqual(result["plans"]["install"]["commands"][0]["argv"], ["cli-hub", "install", "gimp"])
            self.assertEqual(result["plans"]["launch"]["commands"][0]["argv"], ["cli-hub", "launch", "gimp"])

    def test_prepare_harness_reports_missing_required_market_record(self):
        class FakeHub(CliAnythingHub):
            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[],
                )

        result = FakeHub().prepare_harness("missing", from_market=True)
        self.assertFalse(result["ok"])
        self.assertIn("market record not found", result["error"])

    def test_evaluate_harness_recommends_low_dependency_market_candidate(self):
        class FakeHub(CliAnythingHub):
            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout="Entry point: cli-anything-mermaid\nRequires: nothing\nStatus: not installed\n",
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_MERMAID_RECORD],
                )

        with tempfile.TemporaryDirectory() as tmp:
            result = FakeHub(root=Path(tmp)).evaluate_harness("mermaid", from_market=True)
            self.assertTrue(result["ok"])
            self.assertTrue(result["install_candidate"])
            self.assertEqual(result["recommended_next_action"], "write_manifest")
            self.assertTrue(result["gates"]["external_dependency_free"])
            self.assertTrue(result["gates"]["low_policy_risk"])
            self.assertFalse(result["gates"]["installed"])
            self.assertEqual(result["requirements"]["signals"], [])
            self.assertEqual(result["capability_id"], "cli-anything.mermaid.launch")
            self.assertEqual(result["lifecycle"]["state"], "market_candidate")
            self.assertTrue(result["lifecycle"]["ready_for_install"])
            self.assertFalse(result["lifecycle"]["requires_override"])
            stages = {item["id"]: item["status"] for item in result["lifecycle"]["stages"]}
            self.assertEqual(stages["write_manifest"], "ready")
            self.assertEqual(stages["install_harness"], "pending")

    def test_evaluate_harness_allows_managed_python_package_requirements(self):
        class FakeHub(CliAnythingHub):
            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout=(
                        "Entry point: cli-anything-3mf\n"
                        "Requires: Python 3.10+; numpy, scipy, trimesh\n"
                        "Status: not installed\n"
                    ),
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_3MF_RECORD],
                )

        with tempfile.TemporaryDirectory() as tmp:
            result = FakeHub(root=Path(tmp)).evaluate_harness("3mf", from_market=True)
            self.assertTrue(result["ok"])
            self.assertTrue(result["install_candidate"])
            self.assertTrue(result["gates"]["external_dependency_free"])
            self.assertEqual(result["requirements"]["dependency_class"], "managed-package")
            self.assertTrue(result["requirements"]["managed_dependency_only"])
            self.assertFalse(result["requirements"]["manual_dependency_required"])
            self.assertIn("python-runtime", result["requirements"]["signals"])
            self.assertIn("managed-packages", result["requirements"]["signals"])
            self.assertNotIn(
                "declared requirements need external app, account, token, or service",
                result["blockers"],
            )

    def test_evaluate_harness_blocks_installed_harness_with_missing_entrypoint(self):
        class FakeHub(CliAnythingHub):
            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout=(
                        "Entry point: tracecsr\n"
                        "Requires: Python >= 3.10\n"
                        "Status: installed\n"
                    ),
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[
                        {
                            "name": "py4csr",
                            "display_name": "TraceCSR / Py4CSR CLI",
                            "requires": "Python >= 3.10",
                            "entry_point": "tracecsr",
                            "install_cmd": "pip install py4csr",
                            "category": "data-science",
                        }
                    ],
                )

        with tempfile.TemporaryDirectory() as tmp:
            result = FakeHub(root=Path(tmp)).evaluate_harness("py4csr", from_market=True)
            self.assertTrue(result["ok"])
            self.assertFalse(result["install_candidate"])
            self.assertTrue(result["gates"]["installed"])
            self.assertFalse(result["gates"]["entrypoint_available"])
            self.assertFalse(result["gates"]["launch_ready"])
            self.assertEqual(result["recommended_next_action"], "resolve_blockers")
            self.assertIn("installed harness entrypoint is missing from PATH", result["blockers"])
            self.assertTrue(result["lifecycle"]["requires_override"])

    def test_evaluate_harness_blocks_rest_api_harness_without_confirmation(self):
        class FakeHub(CliAnythingHub):
            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout=(
                        "Entry point: cli-anything-n8n\n"
                        "Requires: n8n >= 1.0.0\n"
                        "Status: not installed\n"
                    ),
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_N8N_RECORD],
                )

        with tempfile.TemporaryDirectory() as tmp:
            result = FakeHub(root=Path(tmp)).evaluate_harness("n8n", from_market=True)
            self.assertTrue(result["ok"])
            self.assertFalse(result["install_candidate"])
            self.assertEqual(result["policy"]["risk"], "external-network")
            self.assertTrue(result["policy"]["requiresConfirmation"])
            self.assertEqual(result["policy"]["network"], "requires-confirmation")
            self.assertIn("policy requires elevated confirmation", result["blockers"])

    def test_evaluate_harness_blocks_backend_requirements(self):
        class FakeHub(CliAnythingHub):
            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout=(
                        "Entry point: cli-anything-unimol-tools\n"
                        "Requires: PyTorch 1.12+, Uni-Mol Tools backend\n"
                        "Status: not installed\n"
                    ),
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_UNIMOL_RECORD],
                )

        with tempfile.TemporaryDirectory() as tmp:
            result = FakeHub(root=Path(tmp)).evaluate_harness("unimol_tools", from_market=True)
            self.assertTrue(result["ok"])
            self.assertFalse(result["install_candidate"])
            self.assertFalse(result["gates"]["external_dependency_free"])
            self.assertEqual(result["requirements"]["dependency_class"], "manual-or-external")
            self.assertIn("backend", result["requirements"]["signals"])
            self.assertIn(
                "declared requirements need external app, account, token, or service",
                result["blockers"],
            )

    def test_evaluate_harness_blocks_external_desktop_app_requirements(self):
        class FakeHub(CliAnythingHub):
            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout=(
                        "Entry point: cli-anything-blender\n"
                        "Requires: blender >= 4.2\n"
                        "Status: not installed\n"
                    ),
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_BLENDER_RECORD],
                )

        with tempfile.TemporaryDirectory() as tmp:
            result = FakeHub(root=Path(tmp)).evaluate_harness("blender", from_market=True)
            self.assertTrue(result["ok"])
            self.assertFalse(result["install_candidate"])
            self.assertFalse(result["gates"]["external_dependency_free"])
            self.assertEqual(result["requirements"]["dependency_class"], "manual-or-external")
            self.assertFalse(result["requirements"]["managed_dependency_only"])
            self.assertTrue(result["requirements"]["manual_dependency_required"])
            self.assertIn("external-app:blender", result["requirements"]["signals"])
            self.assertIn(
                "declared requirements need external app, account, token, or service",
                result["blockers"],
            )

    def test_evaluate_harness_blocks_account_or_token_requirements(self):
        class FakeHub(CliAnythingHub):
            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout="Entry point: generate-veo\nRequires: GOOGLE_CLOUD_PROJECT and API key\nStatus: not installed\n",
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[
                        {
                            "name": "generate-veo-video",
                            "display_name": "Generate Veo Video",
                            "description": "Generate videos with Google Veo via Vertex AI and Gemini",
                            "requires": "GOOGLE_CLOUD_PROJECT env var and GEMINI_API_KEY optional",
                            "entry_point": "generate-veo",
                        }
                    ],
                )

        result = FakeHub().evaluate_harness("generate-veo-video", from_market=True)
        self.assertTrue(result["ok"])
        self.assertFalse(result["install_candidate"])
        self.assertFalse(result["gates"]["external_dependency_free"])
        self.assertFalse(result["gates"]["low_policy_risk"])
        self.assertIn("policy requires elevated confirmation", result["blockers"])
        self.assertIn("declared requirements need external app, account, token, or service", result["blockers"])
        self.assertEqual(result["lifecycle"]["state"], "blocked")
        self.assertTrue(result["lifecycle"]["requires_override"])

    def test_probe_harness_marks_low_dependency_candidate_ready(self):
        class FakeHub(CliAnythingHub):
            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout="Entry point: cli-anything-mermaid\nRequires: nothing\nStatus: not installed\n",
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_MERMAID_RECORD],
                )

        result = FakeHub().probe_harness("mermaid", from_market=True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["ready"])
        self.assertEqual(result["probe_blocker_count"], 0)
        self.assertTrue(any(item["id"] == "declared-requirements" for item in result["probes"]))

    def test_verify_harness_previews_protocol_checks_before_manifest_write(self):
        class FakeHub(CliAnythingHub):
            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout="Entry point: cli-anything-mermaid\nRequires: nothing\nStatus: not installed\n",
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_MERMAID_RECORD],
                )

        with tempfile.TemporaryDirectory() as tmp:
            result = FakeHub(root=Path(tmp)).verify_harness("mermaid", from_market=True)
            self.assertTrue(result["ok"])
            self.assertEqual(result["capability_id"], "cli-anything.mermaid.launch")
            self.assertFalse(result["registry"]["manifest_imported"])
            self.assertEqual(result["registry"]["protocol_check_source"], "generated_preview")
            self.assertIn("manifest is not imported into manifests/", result["verification_blockers"])
            self.assertIn("mcp", result["protocols"])
            self.assertIn("status_counts", result["protocols"]["mcp"])
            self.assertEqual(result["parser_contract"]["parser_ref"], "cli-anything.raw")
            self.assertFalse(result["protocol_smoke_suite"]["run"])
            self.assertEqual(result["protocol_smoke_suite"]["status"], "not_run")
            stage_ids = [item["id"] for item in result["verification_stages"]]
            self.assertIn("check_protocol_exports", stage_ids)
            self.assertIn("smoke_protocol_facades", stage_ids)

    def test_verify_harness_can_run_protocol_smoke_suite(self):
        class FakeHub(CliAnythingHub):
            def status(self) -> dict:
                return {
                    "plugin_id": "cli-anything",
                    "entrypoint": "cli-hub",
                    "entrypoint_path": sys.executable,
                    "entrypoint_available": True,
                    "source_repo_dir": "external_plugins/cli-anything/repo",
                    "source_repo_available": True,
                    "version": "cli-hub test",
                }

            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout=f"Entry point: {sys.executable}\nRequires: nothing\nStatus: installed\n",
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_MERMAID_RECORD],
                )

        with tempfile.TemporaryDirectory() as tmp:
            hub = FakeHub(root=Path(tmp))
            hub.write_harness_manifest("mermaid", market_record=SAMPLE_MERMAID_RECORD)
            with patch(
                "cbn_plugins.cli_anything.pty_backend_status",
                return_value={
                    "kind": "pty",
                    "platform": sys.platform,
                    "backend": "test-pty",
                    "available": True,
                    "install_hint": None,
                },
            ), patch(
                "cbn_plugins.cli_anything.protocol_smoke_suite",
                return_value={
                    "ok": True,
                    "wire_compatible": False,
                    "summary": {"check_count": 3, "failed_count": 0},
                    "readiness": {"internal_bridge_ready": True},
                    "bridge_contract": {"ok": True},
                    "failures": [],
                },
            ) as smoke:
                result = hub.verify_harness(
                    "mermaid",
                    from_market=True,
                    include_workflows=False,
                    run_smoke_suite=True,
                    smoke_extra_args=("--help",),
                )

            self.assertTrue(result["protocol_smoke_suite"]["run"])
            self.assertTrue(result["protocol_smoke_suite"]["ok"])
            self.assertEqual(result["protocol_smoke_suite"]["summary"]["failed_count"], 0)
            self.assertIn("--extra-arg=--help", result["protocol_smoke_suite"]["command"])
            self.assertEqual(result["protocol_smoke_suite"]["workflow_paths"], [])
            stages = {item["id"]: item for item in result["verification_stages"]}
            self.assertEqual(stages["smoke_protocol_facades"]["status"], "completed")
            smoke.assert_called_once()
            self.assertEqual(smoke.call_args.kwargs["capability_ids"], ("cli-anything.mermaid.launch",))
            self.assertEqual(smoke.call_args.kwargs["workflow_paths"], ())
            self.assertEqual(smoke.call_args.kwargs["extra_args"], ("--help",))

    def test_verify_harness_reports_runtime_ready_after_import_and_install(self):
        class FakeHub(CliAnythingHub):
            def status(self) -> dict:
                return {
                    "plugin_id": "cli-anything",
                    "entrypoint": "cli-hub",
                    "entrypoint_path": sys.executable,
                    "entrypoint_available": True,
                    "source_repo_dir": "external_plugins/cli-anything/repo",
                    "source_repo_available": True,
                    "version": "cli-hub test",
                }

            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout=f"Entry point: {sys.executable}\nRequires: nothing\nStatus: installed\n",
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_MERMAID_RECORD],
                )

        with tempfile.TemporaryDirectory() as tmp:
            hub = FakeHub(root=Path(tmp))
            hub.write_harness_manifest("mermaid", market_record=SAMPLE_MERMAID_RECORD)
            with patch(
                "cbn_plugins.cli_anything.pty_backend_status",
                return_value={
                    "kind": "pty",
                    "platform": sys.platform,
                    "backend": "test-pty",
                    "available": True,
                    "install_hint": None,
                },
            ):
                result = hub.verify_harness("mermaid", from_market=True)
            self.assertTrue(result["ok"])
            self.assertTrue(result["registry"]["manifest_imported"])
            self.assertEqual(result["registry"]["protocol_check_source"], "current_registry")
            self.assertTrue(result["ready_for_runtime_verification"])
            self.assertEqual(result["verification_blockers"], [])
            stages = {item["id"]: item["status"] for item in result["verification_stages"]}
            self.assertEqual(stages["write_manifest"], "completed")
            self.assertEqual(stages["install_harness"], "completed")
            self.assertEqual(stages["dry_run_call"], "ready")

    def test_onboard_harness_previews_full_acceptance_chain(self):
        class FakeHub(CliAnythingHub):
            def status(self) -> dict:
                return {
                    "plugin_id": "cli-anything",
                    "entrypoint": "cli-hub",
                    "entrypoint_path": sys.executable,
                    "entrypoint_available": True,
                    "source_repo_dir": "external_plugins/cli-anything/repo",
                    "source_repo_available": True,
                    "version": "cli-hub test",
                }

            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout=f"Entry point: {sys.executable}\nRequires: nothing\nStatus: installed\n",
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_MERMAID_RECORD],
                )

        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "cbn_plugins.cli_anything.pty_backend_status",
                return_value={
                    "kind": "pty",
                    "platform": sys.platform,
                    "backend": "test-pty",
                    "available": True,
                    "install_hint": None,
                },
            ):
                result = FakeHub(root=Path(tmp)).onboard_harness("mermaid", from_market=True)
            self.assertTrue(result["ok"])
            self.assertEqual(result["kind"], "CliAnythingHarnessOnboarding")
            self.assertFalse(result["summary"]["manifest_written"])
            self.assertTrue(result["summary"]["ready_for_manifest_write"])
            self.assertTrue(result["summary"]["ready_for_install"])
            self.assertIn("install_gate", result["reports"])
            self.assertIn("verification", result["reports"])
            self.assertIn("smoke_protocol_facades", [stage["id"] for stage in result["stage_results"]])
            self.assertIn(
                "python -m cbn plugin harness cli-anything install mermaid --yes",
                result["next_commands"],
            )

    def test_onboard_harness_requires_confirmation_before_manifest_write(self):
        class FakeHub(CliAnythingHub):
            def status(self) -> dict:
                return {
                    "plugin_id": "cli-anything",
                    "entrypoint": "cli-hub",
                    "entrypoint_path": sys.executable,
                    "entrypoint_available": True,
                    "source_repo_dir": "external_plugins/cli-anything/repo",
                    "source_repo_available": True,
                    "version": "cli-hub test",
                }

            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout=f"Entry point: {sys.executable}\nRequires: nothing\nStatus: installed\n",
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_MERMAID_RECORD],
                )

        with tempfile.TemporaryDirectory() as tmp:
            result = FakeHub(root=Path(tmp)).onboard_harness(
                "mermaid",
                from_market=True,
                write=True,
                confirmed=False,
            )
            self.assertTrue(result["ok"])
            self.assertTrue(result["summary"]["write_requires_confirmation"])
            self.assertFalse(result["summary"]["manifest_written"])
            self.assertFalse((Path(tmp) / "manifests" / "cli-anything.mermaid.launch.json").exists())

    def test_onboard_harness_confirmed_write_updates_verification_registry(self):
        class FakeHub(CliAnythingHub):
            def status(self) -> dict:
                return {
                    "plugin_id": "cli-anything",
                    "entrypoint": "cli-hub",
                    "entrypoint_path": sys.executable,
                    "entrypoint_available": True,
                    "source_repo_dir": "external_plugins/cli-anything/repo",
                    "source_repo_available": True,
                    "version": "cli-hub test",
                }

            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout=f"Entry point: {sys.executable}\nRequires: nothing\nStatus: installed\n",
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_MERMAID_RECORD],
                )

        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "cbn_plugins.cli_anything.pty_backend_status",
                return_value={
                    "kind": "pty",
                    "platform": sys.platform,
                    "backend": "test-pty",
                    "available": True,
                    "install_hint": None,
                },
            ):
                result = FakeHub(root=Path(tmp)).onboard_harness(
                    "mermaid",
                    from_market=True,
                    write=True,
                    confirmed=True,
                )
            self.assertTrue(result["ok"])
            self.assertTrue(result["summary"]["manifest_written"])
            self.assertTrue(Path(result["reports"]["adaptation"]["written"]).exists())
            self.assertTrue(result["reports"]["verification"]["registry"]["manifest_imported"])

    def test_onboard_harness_install_requires_confirmation(self):
        class FakeHub(CliAnythingHub):
            def status(self) -> dict:
                return {
                    "plugin_id": "cli-anything",
                    "entrypoint": "cli-hub",
                    "entrypoint_path": sys.executable,
                    "entrypoint_available": True,
                    "source_repo_dir": "external_plugins/cli-anything/repo",
                    "source_repo_available": True,
                    "version": "cli-hub test",
                }

            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout=f"Entry point: {sys.executable}\nRequires: nothing\nStatus: not installed\n",
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_MERMAID_RECORD],
                )

        class FakeRunner:
            called = False

            def execute(self, plan):
                self.called = True
                return {"status": "completed", "plugin_id": plan.plugin_id, "action": plan.action, "results": []}

        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner()
            result = FakeHub(root=Path(tmp)).onboard_harness(
                "mermaid",
                from_market=True,
                install=True,
                confirmed=False,
                operation_runner=runner,
            )
            self.assertTrue(result["ok"])
            self.assertTrue(result["summary"]["install_requires_confirmation"])
            self.assertFalse(result["summary"]["install_executed"])
            self.assertEqual(result["summary"]["install_execution_status"], "requires_confirmation")
            self.assertFalse(runner.called)

    def test_onboard_harness_confirmed_install_runs_operation_runner(self):
        class FakeHub(CliAnythingHub):
            def status(self) -> dict:
                return {
                    "plugin_id": "cli-anything",
                    "entrypoint": "cli-hub",
                    "entrypoint_path": sys.executable,
                    "entrypoint_available": True,
                    "source_repo_dir": "external_plugins/cli-anything/repo",
                    "source_repo_available": True,
                    "version": "cli-hub test",
                }

            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout=f"Entry point: {sys.executable}\nRequires: nothing\nStatus: not installed\n",
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_MERMAID_RECORD],
                )

        class FakeRunner:
            def __init__(self) -> None:
                self.plan = None

            def execute(self, plan):
                self.plan = plan
                return {
                    "operation_id": "op-test",
                    "status": "completed",
                    "plugin_id": plan.plugin_id,
                    "action": plan.action,
                    "results": [{"exit_code": 0}],
                }

        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner()
            result = FakeHub(root=Path(tmp)).onboard_harness(
                "mermaid",
                from_market=True,
                install=True,
                confirmed=True,
                operation_runner=runner,
            )
            self.assertTrue(result["ok"])
            self.assertIsNotNone(runner.plan)
            self.assertEqual(runner.plan.action, "harness-install-mermaid")
            self.assertTrue(result["summary"]["install_executed"])
            self.assertEqual(result["reports"]["install_result"]["status"], "completed")
            stages = {stage["id"]: stage for stage in result["stage_results"]}
            self.assertEqual(stages["install_harness"]["execution"], "completed")

    def test_live_verification_summarizes_harness_candidates_and_readiness(self):
        class FakeHub(CliAnythingHub):
            def status(self) -> dict:
                return {
                    "plugin_id": "cli-anything",
                    "entrypoint": "cli-hub",
                    "entrypoint_path": sys.executable,
                    "entrypoint_available": True,
                    "source_repo_dir": "external_plugins/cli-anything/repo",
                    "source_repo_available": True,
                    "version": "cli-hub test",
                }

            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout=f"Entry point: {sys.executable}\nRequires: nothing\nStatus: installed\n",
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_MERMAID_RECORD, SAMPLE_MARKET_RECORD],
                )

        with tempfile.TemporaryDirectory() as tmp:
            hub = FakeHub(root=Path(tmp))
            hub.write_harness_manifest("mermaid", market_record=SAMPLE_MERMAID_RECORD)
            with patch(
                "cbn_plugins.cli_anything.pty_backend_status",
                return_value={
                    "kind": "pty",
                    "platform": sys.platform,
                    "backend": "test-pty",
                    "available": True,
                    "install_hint": None,
                },
            ):
                result = hub.live_verification(
                    harnesses=("mermaid",),
                    candidate_query="image",
                    candidate_limit=2,
                    include_candidates=True,
                    include_workflows=False,
                )
            self.assertTrue(result["ok"])
            self.assertEqual(result["kind"], "CliAnythingLiveVerification")
            self.assertEqual(result["summary"]["verified_harness_count"], 1)
            self.assertEqual(result["summary"]["launch_ready_harness_count"], 1)
            self.assertEqual(result["harnesses"][0]["harness_name"], "mermaid")
            self.assertIn("candidate_summary", result["candidate_scan"])
            self.assertIsNone(result["workflow_readiness"])

    def test_verify_harness_blocks_runtime_when_pty_backend_missing(self):
        class FakeHub(CliAnythingHub):
            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout=f"Entry point: {sys.executable}\nRequires: nothing\nStatus: installed\n",
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_MERMAID_RECORD],
                )

        with tempfile.TemporaryDirectory() as tmp:
            hub = FakeHub(root=Path(tmp))
            hub.write_harness_manifest("mermaid", market_record=SAMPLE_MERMAID_RECORD)
            with patch(
                "cbn_plugins.cli_anything.pty_backend_status",
                return_value={
                    "kind": "pty",
                    "platform": sys.platform,
                    "backend": "test-pty",
                    "available": False,
                    "install_hint": "pip install cli-bridge-network[pty]",
                },
            ):
                result = hub.verify_harness("mermaid", from_market=True)
            self.assertTrue(result["ok"])
            self.assertFalse(result["ready_for_runtime_verification"])
            self.assertFalse(result["evaluation"]["gates"]["runtime_transport_ready"])
            self.assertIn("runtime transport is not ready", result["verification_blockers"])

    def test_probe_harness_reports_missing_system_command(self):
        class FakeHub(CliAnythingHub):
            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout=(
                        "Entry point: cli-anything-missing\n"
                        "Requires: cbn-definitely-missing-binary (apt install cbn-definitely-missing-binary)\n"
                        "Status: not installed\n"
                    ),
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[
                        {
                            "name": "missing-command",
                            "display_name": "Missing Command",
                            "requires": "cbn-definitely-missing-binary (apt install cbn-definitely-missing-binary)",
                            "entry_point": "cli-anything-missing",
                        }
                    ],
                )

        result = FakeHub().probe_harness("missing-command", from_market=True)
        self.assertTrue(result["ok"])
        self.assertFalse(result["ready"])
        command_probe = next(item for item in result["probes"] if item["id"] == "command:cbn-definitely-missing-binary")
        self.assertEqual(command_probe["status"], "missing")
        self.assertEqual(command_probe["severity"], "blocker")

    def test_probe_harness_reports_missing_env_and_manual_api_key(self):
        class FakeHub(CliAnythingHub):
            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout=(
                        "Entry point: generate-veo\n"
                        "Requires: CBN_TEST_REQUIRED_ENV_NEVER_SET env var and API key\n"
                        "Status: not installed\n"
                    ),
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[
                        {
                            "name": "env-required",
                            "display_name": "Env Required",
                            "description": "External API harness",
                            "requires": "CBN_TEST_REQUIRED_ENV_NEVER_SET env var and API key",
                            "entry_point": "generate-veo",
                        }
                    ],
                )

        result = FakeHub().probe_harness("env-required", from_market=True)
        self.assertTrue(result["ok"])
        self.assertFalse(result["ready"])
        env_probe = next(item for item in result["probes"] if item["id"] == "env:CBN_TEST_REQUIRED_ENV_NEVER_SET")
        self.assertEqual(env_probe["status"], "missing")
        manual_probe = next(item for item in result["probes"] if item["id"] == "manual-account-or-api-key")
        self.assertEqual(manual_probe["status"], "manual_required")

    def test_harness_operation_gate_allows_low_dependency_install(self):
        class FakeHub(CliAnythingHub):
            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout="Entry point: cli-anything-mermaid\nRequires: nothing\nStatus: not installed\n",
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_MERMAID_RECORD],
                )

        gate = FakeHub().harness_operation_gate("install", "mermaid", from_market=True)
        self.assertTrue(gate["ok"])
        self.assertTrue(gate["gated"])
        self.assertEqual(gate["blockers"], [])
        self.assertTrue(gate["evaluation"]["install_candidate"])
        self.assertTrue(gate["readiness"]["ready"])
        self.assertEqual(gate["readiness"]["probe_blocker_count"], 0)

    def test_harness_operation_gate_blocks_external_dependencies_before_install(self):
        class FakeHub(CliAnythingHub):
            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout="Entry point: cli-anything-gimp\nRequires: gimp (apt install gimp)\nStatus: not installed\n",
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_MARKET_RECORD],
                )

        gate = FakeHub().harness_operation_gate("install", "gimp", from_market=True)
        self.assertFalse(gate["ok"])
        self.assertEqual(gate["override_flag"], "--allow-blocked")
        self.assertIn("declared requirements need external app, account, token, or service", gate["blockers"])
        self.assertIn("harness is not an install candidate", gate["blockers"])
        self.assertIn("dependency probe failed: command:gimp", gate["blockers"])
        self.assertFalse(gate["readiness"]["ready"])
        self.assertGreaterEqual(gate["readiness"]["probe_blocker_count"], 1)

    def test_harness_operation_gate_blocks_update_when_harness_is_not_installed(self):
        class FakeHub(CliAnythingHub):
            def info(self, harness_name: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "info", harness_name),
                    exit_code=0,
                    stdout="Entry point: cli-anything-mermaid\nRequires: nothing\nStatus: not installed\n",
                    stderr="",
                )

            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_MERMAID_RECORD],
                )

        gate = FakeHub().harness_operation_gate("update", "mermaid", from_market=True)
        self.assertFalse(gate["ok"])
        self.assertIn("harness is not installed", gate["blockers"])

    def test_candidate_harnesses_ranks_low_dependency_market_records(self):
        class FakeHub(CliAnythingHub):
            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_MARKET_RECORD, SAMPLE_MERMAID_RECORD],
                )

        with tempfile.TemporaryDirectory() as tmp, patch("cbn_plugins.cli_anything.shutil.which", return_value=None):
            result = FakeHub(root=Path(tmp)).candidate_harnesses(query="image", limit=10)
            self.assertTrue(result["ok"])
            self.assertEqual(result["selected_count"], 2)
            self.assertEqual(result["install_candidate_count"], 1)
            self.assertEqual(result["blocked_count"], 1)
            first = result["candidates"][0]
            self.assertEqual(first["harness_name"], "mermaid")
            self.assertTrue(first["install_candidate"])
            self.assertEqual(first["rank"], 1)
            self.assertEqual(first["lifecycle"]["state"], "market_candidate")
            self.assertEqual(first["lifecycle"]["stages"][1]["status"], "ready")
            blocked = result["candidates"][1]
            self.assertEqual(blocked["harness_name"], "gimp")
            self.assertFalse(blocked["install_candidate"])
            self.assertIn("declared requirements need external app, account, token, or service", blocked["blockers"])
            self.assertEqual(blocked["recommended_next_action"], "resolve_blockers")
            self.assertEqual(blocked["lifecycle"]["state"], "blocked")
            self.assertTrue(blocked["lifecycle"]["requires_override"])
            self.assertNotIn("readiness", first)

    def test_candidate_harnesses_can_attach_probe_readiness(self):
        class FakeHub(CliAnythingHub):
            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_MARKET_RECORD, SAMPLE_MERMAID_RECORD],
                )

        with tempfile.TemporaryDirectory() as tmp, patch("cbn_plugins.cli_anything.shutil.which", return_value=None):
            result = FakeHub(root=Path(tmp)).candidate_harnesses(
                query="image",
                limit=10,
                with_probes=True,
            )
            self.assertTrue(result["ok"])
            self.assertTrue(result["with_probes"])
            self.assertEqual(result["probe_ready_count"], 1)
            self.assertEqual(result["probe_blocked_count"], 1)
            first = result["candidates"][0]
            self.assertEqual(first["harness_name"], "mermaid")
            self.assertTrue(first["readiness"]["ready"])
            blocked = result["candidates"][1]
            self.assertEqual(blocked["harness_name"], "gimp")
            self.assertFalse(blocked["readiness"]["ready"])
            self.assertGreaterEqual(blocked["readiness"]["probe_blocker_count"], 1)
            self.assertTrue(any(item["id"] == "command:gimp" for item in blocked["readiness"]["probes"]))

    def test_candidate_harnesses_probe_readiness_accepts_managed_package_requirements(self):
        class FakeHub(CliAnythingHub):
            def list_market(self) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "list", "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_3MF_RECORD],
                )

        with tempfile.TemporaryDirectory() as tmp, patch("cbn_plugins.cli_anything.shutil.which", return_value=None):
            result = FakeHub(root=Path(tmp)).candidate_harnesses(limit=10, with_probes=True)
            self.assertTrue(result["ok"])
            self.assertEqual(result["install_candidate_count"], 1)
            self.assertEqual(result["probe_ready_count"], 1)
            candidate = result["candidates"][0]
            self.assertEqual(candidate["harness_name"], "3mf")
            self.assertTrue(candidate["install_candidate"])
            self.assertTrue(candidate["readiness"]["ready"])
            self.assertEqual(candidate["readiness"]["probe_blocker_count"], 0)
            declared = candidate["readiness"]["probes"][0]
            self.assertEqual(declared["id"], "declared-requirements")
            self.assertEqual(declared["severity"], "info")
            self.assertEqual(declared["dependency_class"], "managed-package")

    def test_candidate_harnesses_blocks_external_desktop_app_requirements(self):
        class FakeHub(CliAnythingHub):
            def list_market(self) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "list", "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[
                        SAMPLE_BLENDER_RECORD,
                        SAMPLE_LIBREOFFICE_RECORD,
                        SAMPLE_OBS_STUDIO_RECORD,
                        SAMPLE_3MF_RECORD,
                    ],
                )

        with tempfile.TemporaryDirectory() as tmp, patch("cbn_plugins.cli_anything.shutil.which", return_value=None):
            result = FakeHub(root=Path(tmp)).candidate_harnesses(limit=10, with_probes=True)
            self.assertTrue(result["ok"])
            self.assertEqual(result["install_candidate_count"], 1)
            by_name = {candidate["harness_name"]: candidate for candidate in result["candidates"]}
            self.assertTrue(by_name["3mf"]["install_candidate"])
            for name, signal in {
                "blender": "external-app:blender",
                "libreoffice": "external-app:libreoffice",
                "obs-studio": "external-app:obs-studio",
            }.items():
                candidate = by_name[name]
                self.assertFalse(candidate["install_candidate"])
                self.assertFalse(candidate["requirements"]["external_dependency_free"])
                self.assertEqual(candidate["requirements"]["dependency_class"], "manual-or-external")
                self.assertIn(signal, candidate["requirements"]["signals"])
                self.assertIn(
                    "declared requirements need external app, account, token, or service",
                    candidate["blockers"],
                )

    def test_candidate_harnesses_probe_blockers_downgrade_install_candidate(self):
        api_key_record = {
            "name": "mailchimp",
            "display_name": "Mailchimp",
            "version": "1.0.0",
            "description": "Mailchimp campaign operations",
            "requires": "CBN_TEST_MAILCHIMP_API_KEY",
            "install_cmd": "pip install cli-anything-mailchimp",
            "entry_point": "cli-anything-mailchimp",
            "category": "marketing",
            "_source": "harness",
        }

        class FakeHub(CliAnythingHub):
            def list_market(self) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "list", "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[api_key_record, SAMPLE_3MF_RECORD],
                )

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("cbn_plugins.cli_anything.shutil.which", return_value=None),
            patch.dict(os.environ, {}, clear=True),
        ):
            result = FakeHub(root=Path(tmp)).candidate_harnesses(limit=10, with_probes=True)
            self.assertTrue(result["ok"])
            self.assertEqual(result["install_candidate_count"], 1)
            self.assertEqual(result["probe_ready_count"], 1)
            self.assertEqual(result["probe_blocked_count"], 1)
            by_name = {candidate["harness_name"]: candidate for candidate in result["candidates"]}
            candidate = by_name["mailchimp"]
            self.assertFalse(candidate["install_candidate"])
            self.assertFalse(candidate["readiness"]["ready"])
            self.assertFalse(candidate["gates"]["external_dependency_free"])
            self.assertEqual(candidate["recommended_next_action"], "resolve_blockers")
            self.assertIn("dependency probe failed: env:CBN_TEST_MAILCHIMP_API_KEY", candidate["blockers"])
            self.assertEqual(candidate["lifecycle"]["state"], "blocked")

    def test_market_install_queue_builds_read_only_queue_from_probed_candidates(self):
        class FakeHub(CliAnythingHub):
            def list_market(self) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "list", "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_3MF_RECORD, SAMPLE_BLENDER_RECORD],
                )

            def evaluate_harness(self, harness_name, title=None, from_market=True):
                return {
                    "ok": True,
                    "harness_name": harness_name,
                    "install_candidate": harness_name == "3mf",
                    "blockers": [] if harness_name == "3mf" else ["blocked"],
                    "gates": {"launch_ready": False},
                }

        with tempfile.TemporaryDirectory() as tmp, patch("cbn_plugins.cli_anything.shutil.which", return_value=None):
            result = FakeHub(root=Path(tmp)).market_install_queue(limit=10, max_installs=5)
            self.assertTrue(result["ok"])
            self.assertEqual(result["kind"], "CliAnythingMarketInstallQueue")
            self.assertEqual(result["summary"]["candidate_count"], 2)
            self.assertEqual(result["summary"]["queued_count"], 1)
            self.assertEqual(result["summary"]["blocked_count"], 1)
            self.assertEqual(result["summary"]["probe_ready_count"], 1)
            queued = result["queue"][0]
            self.assertEqual(queued["harness_name"], "3mf")
            self.assertTrue(queued["ready_for_install"])
            self.assertTrue(queued["requires_confirmation"])
            self.assertEqual(queued["plan"]["action"], "harness-install-3mf")
            self.assertEqual(queued["plan"]["commands"][0]["argv"], ["cli-hub", "install", "3mf"])
            self.assertIn("--write --install --yes", queued["commands"]["onboard_install"])
            blocked = result["blocked"][0]
            self.assertEqual(blocked["harness_name"], "blender")
            self.assertIn("external-app:blender", blocked["readiness"]["probes"][0]["signals"])

    def test_market_install_queue_respects_max_installs_and_no_blocked(self):
        class FakeHub(CliAnythingHub):
            def list_market(self) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "list", "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_3MF_RECORD, SAMPLE_MERMAID_RECORD, SAMPLE_BLENDER_RECORD],
                )

            def evaluate_harness(self, harness_name, title=None, from_market=True):
                return {
                    "ok": True,
                    "harness_name": harness_name,
                    "install_candidate": harness_name in {"3mf", "mermaid"},
                    "blockers": [] if harness_name in {"3mf", "mermaid"} else ["blocked"],
                    "gates": {"launch_ready": False},
                }

        with tempfile.TemporaryDirectory() as tmp, patch("cbn_plugins.cli_anything.shutil.which", return_value=None):
            result = FakeHub(root=Path(tmp)).market_install_queue(
                limit=10,
                max_installs=1,
                include_blocked=False,
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["summary"]["queued_count"], 1)
            self.assertEqual(result["summary"]["blocked_count"], 0)
            self.assertEqual(result["summary"]["skipped_count"], 1)
            self.assertEqual(result["skipped"][0]["reason"], "max_installs limit reached")

    def test_blocked_harness_plan_classifies_override_and_repair_paths(self):
        class FakeHub(CliAnythingHub):
            def evaluate_harness(self, harness_name, title=None, from_market=True):
                blockers = {
                    "n8n": ["policy requires elevated confirmation"],
                    "py4csr": ["installed harness entrypoint is missing from PATH"],
                    "unimol_tools": ["declared requirements need external app, account, token, or service"],
                }[harness_name]
                return {
                    "ok": True,
                    "harness_name": harness_name,
                    "capability_id": f"cli-anything.{harness_name}.launch",
                    "install_candidate": False,
                    "recommended_next_action": "resolve_blockers",
                    "blockers": blockers,
                    "gates": {"launch_ready": False},
                }

        result = FakeHub().blocked_harness_plan(harnesses=("n8n", "py4csr", "unimol_tools"))
        self.assertTrue(result["ok"])
        self.assertEqual(result["kind"], "CliAnythingBlockedHarnessPlan")
        self.assertEqual(result["summary"]["blocked_count"], 3)
        self.assertEqual(result["summary"]["manual_resolution_count"], 2)
        by_name = {item["harness_name"]: item for item in result["blocked"]}
        self.assertIn("external-network-or-risk", by_name["n8n"]["categories"])
        self.assertTrue(by_name["n8n"]["override"]["available"])
        self.assertEqual(by_name["n8n"]["override"]["mode"], "explicit_risk_acceptance")
        self.assertIn("installed-entrypoint-missing", by_name["py4csr"]["categories"])
        self.assertFalse(by_name["py4csr"]["override"]["available"])
        self.assertEqual(by_name["py4csr"]["recommended_next_action"], "repair_entrypoint_or_market_metadata")
        self.assertIn("manual-dependency", by_name["unimol_tools"]["categories"])
        self.assertIn("--allow-blocked", by_name["unimol_tools"]["commands"]["onboard_install_override"])

    def test_entrypoint_repair_plan_detects_installed_package_without_console_script(self):
        class FakeHub(CliAnythingHub):
            def evaluate_harness(self, harness_name, title=None, from_market=True):
                return {
                    "ok": True,
                    "harness_name": harness_name,
                    "capability_id": "cli-anything.broken.launch",
                    "install_candidate": False,
                    "recommended_next_action": "resolve_blockers",
                    "blockers": ["installed harness entrypoint is missing from PATH"],
                    "gates": {
                        "installed": True,
                        "entrypoint_available": False,
                        "launch_ready": False,
                    },
                    "status": {
                        "entry_point": "definitely-missing-pip-entrypoint",
                        "entrypoint_available": False,
                        "installed": True,
                        "market_record": {
                            "name": "pip",
                            "install_cmd": "pip install pip",
                            "entry_point": "definitely-missing-pip-entrypoint",
                        },
                    },
                }

        result = FakeHub().entrypoint_repair_plan("broken", from_market=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["kind"], "CliAnythingEntrypointRepairPlan")
        self.assertFalse(result["entrypoint_available"])
        self.assertIn("pip", result["package_candidates"])
        pip_report = next(item for item in result["distributions"] if item["package"] == "pip")
        self.assertTrue(pip_report["installed"])
        self.assertEqual(result["diagnosis"]["state"], "installed_entrypoint_missing")
        self.assertTrue(result["diagnosis"]["repair_required"])
        self.assertIn("installed package has no matching console_script", result["diagnosis"]["findings"])

    def test_repair_entrypoint_blocks_without_adapter_target(self):
        class FakeHub(CliAnythingHub):
            def entrypoint_repair_plan(self, harness_name, from_market=True):
                return {
                    "ok": True,
                    "plugin_id": "cli-anything",
                    "kind": "CliAnythingEntrypointRepairPlan",
                    "harness_name": harness_name,
                    "from_market": from_market,
                    "capability_id": "cli-anything.broken.launch",
                    "modules": [{"package": "broken", "importable": True, "module_main": False}],
                    "diagnosis": {"repair_required": True},
                    "evaluation": {
                        "adaptation": {
                            "manifest_path": str(self.paths.manifests / "cli-anything.broken.launch.json"),
                            "manifest": {
                                "apiVersion": "bridge.dev/v1alpha1",
                                "kind": "ToolManifest",
                                "metadata": {
                                    "id": "cli-anything.broken.launch",
                                    "title": "Broken",
                                    "labels": {"plugin": "cli-anything", "harness": "broken"},
                                    "annotations": {},
                                },
                                "spec": {
                                    "transport": {
                                        "kind": "pty",
                                        "command": "cli-hub",
                                        "argsTemplate": ["launch", "broken", "--"],
                                    },
                                    "policy": {
                                        "risk": "read",
                                        "requiresConfirmation": False,
                                        "network": "deny",
                                    },
                                    "output": {"parserRef": "cli-anything.raw", "verified": False},
                                },
                            },
                        }
                    },
                }

        with tempfile.TemporaryDirectory() as tempdir:
            result = FakeHub(root=Path(tempdir)).repair_entrypoint("broken", from_market=True)
            self.assertTrue(result["ok"])
            self.assertEqual(result["kind"], "CliAnythingEntrypointRepair")
            self.assertFalse(result["strategy"]["ready"])
            self.assertEqual(result["strategy"]["state"], "adapter_target_required")
            self.assertEqual(result["execution"]["status"], "not_requested")

    def test_repair_entrypoint_writes_project_local_wrapper_when_confirmed(self):
        class FakeHub(CliAnythingHub):
            def entrypoint_repair_plan(self, harness_name, from_market=True):
                return {
                    "ok": True,
                    "plugin_id": "cli-anything",
                    "kind": "CliAnythingEntrypointRepairPlan",
                    "harness_name": harness_name,
                    "from_market": from_market,
                    "capability_id": "cli-anything.piptool.launch",
                    "modules": [{"package": "pip", "importable": True, "module_main": True}],
                    "diagnosis": {"repair_required": True},
                    "evaluation": {
                        "adaptation": {
                            "manifest_path": str(self.paths.manifests / "cli-anything.piptool.launch.json"),
                            "manifest": {
                                "apiVersion": "bridge.dev/v1alpha1",
                                "kind": "ToolManifest",
                                "metadata": {
                                    "id": "cli-anything.piptool.launch",
                                    "title": "Pip Tool",
                                    "labels": {"plugin": "cli-anything", "harness": "piptool"},
                                    "annotations": {},
                                },
                                "spec": {
                                    "transport": {
                                        "kind": "pty",
                                        "command": "cli-hub",
                                        "argsTemplate": ["launch", "piptool", "--"],
                                    },
                                    "policy": {
                                        "risk": "read",
                                        "requiresConfirmation": False,
                                        "network": "deny",
                                    },
                                    "output": {"parserRef": "cli-anything.raw", "verified": False},
                                },
                            },
                        }
                    },
                }

        with tempfile.TemporaryDirectory() as tempdir:
            hub = FakeHub(root=Path(tempdir))
            blocked = hub.repair_entrypoint("piptool", module="pip", write=True, confirmed=False)
            self.assertEqual(blocked["execution"]["status"], "requires_confirmation")
            self.assertFalse(Path(blocked["wrapper_path"]).exists())

            result = hub.repair_entrypoint("piptool", module="pip", write=True, confirmed=True)
            self.assertEqual(result["execution"]["status"], "completed")
            wrapper_path = Path(result["wrapper_path"])
            manifest_path = Path(tempdir) / "manifests" / "cli-anything.piptool.launch.json"
            self.assertTrue(wrapper_path.exists())
            self.assertTrue(manifest_path.exists())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["spec"]["transport"]["command"], sys.executable)
            self.assertEqual(manifest["spec"]["transport"]["argsTemplate"], [str(wrapper_path)])
            self.assertEqual(manifest["metadata"]["annotations"]["cbn.repair.python_module"], "pip")
            self.assertTrue(result["validation"]["valid"])

    def test_candidate_harnesses_limits_after_ranking_full_market(self):
        class FakeHub(CliAnythingHub):
            def list_market(self) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "list", "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[SAMPLE_MARKET_RECORD, SAMPLE_MERMAID_RECORD],
                )

        with tempfile.TemporaryDirectory() as tmp, patch("cbn_plugins.cli_anything.shutil.which", return_value=None):
            result = FakeHub(root=Path(tmp)).candidate_harnesses(limit=1)
            self.assertTrue(result["ok"])
            self.assertEqual(result["market_count"], 2)
            self.assertEqual(result["evaluated_count"], 2)
            self.assertEqual(result["selected_count"], 1)
            self.assertEqual(result["install_candidate_count"], 1)
            self.assertEqual(result["candidates"][0]["harness_name"], "mermaid")

    def test_candidate_harnesses_compact_payload_omits_raw_market_stdout(self):
        market_stdout = "x" * 5000

        class FakeHub(CliAnythingHub):
            def list_market(self) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "list", "--json"),
                    exit_code=0,
                    stdout=market_stdout,
                    stderr="warning line",
                    parsed_json=[SAMPLE_MERMAID_RECORD],
                )

        with tempfile.TemporaryDirectory() as tmp, patch("cbn_plugins.cli_anything.shutil.which", return_value=None):
            full = FakeHub(root=Path(tmp)).candidate_harnesses(limit=1)
            compact = FakeHub(root=Path(tmp)).candidate_harnesses(limit=1, compact=True)

            self.assertFalse(full["compact"])
            self.assertEqual(full["market"]["stdout"], market_stdout)
            self.assertTrue(compact["compact"])
            self.assertNotIn("stdout", compact["market"])
            self.assertNotIn("parsed_json", compact["market"])
            self.assertEqual(compact["market"]["stdout_chars"], len(market_stdout))
            self.assertTrue(compact["market"]["stdout_omitted"])
            self.assertTrue(compact["market"]["parsed_json_omitted"])
            self.assertEqual(compact["market"]["parsed_json_type"], "list")
            self.assertEqual(compact["market"]["parsed_json_count"], 1)
            self.assertEqual(compact["market"]["stderr_tail"], "warning line")
            self.assertEqual(compact["candidate_summary"][0]["harness_name"], "mermaid")
            self.assertEqual(compact["candidate_summary"][0]["rank"], 1)
            self.assertEqual(compact["candidate_summary"][0]["lifecycle_state"], "market_candidate")

    def test_candidate_harnesses_reports_local_launch_ready_status(self):
        local_record = dict(SAMPLE_MERMAID_RECORD)
        local_record["entry_point"] = sys.executable

        class FakeHub(CliAnythingHub):
            def list_market(self) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "list", "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[local_record],
                )

        with tempfile.TemporaryDirectory() as tmp:
            hub = FakeHub(root=Path(tmp))
            hub.write_harness_manifest("mermaid", market_record=local_record)
            result = hub.candidate_harnesses(limit=1)
            candidate = result["candidates"][0]
            self.assertEqual(candidate["recommended_next_action"], "call_capability")
            self.assertTrue(candidate["local_status"]["manifest_imported"])
            self.assertTrue(candidate["local_status"]["entrypoint_available"])
            self.assertTrue(candidate["local_status"]["launch_ready"])
            self.assertEqual(candidate["lifecycle"]["state"], "launch_ready")

    def test_candidate_harnesses_uses_imported_manifest_validation_status(self):
        local_record = dict(SAMPLE_MERMAID_RECORD)
        local_record["entry_point"] = sys.executable

        class FakeHub(CliAnythingHub):
            def list_market(self) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "list", "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[local_record],
                )

        with tempfile.TemporaryDirectory() as tmp:
            hub = FakeHub(root=Path(tmp))
            path = hub.write_harness_manifest("mermaid", market_record=local_record)
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["spec"]["output"]["verified"] = True
            path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            result = hub.candidate_harnesses(limit=1)
            candidate = result["candidates"][0]
            self.assertTrue(candidate["validation"]["valid"])
            self.assertEqual(candidate["validation"]["warnings"], [])
            self.assertTrue(candidate["local_status"]["manifest_imported"])

    def test_candidate_harnesses_reports_market_failures_without_crashing(self):
        hub = CliAnythingHub(entrypoint="cbn-cli-hub-that-does-not-exist")
        result = hub.candidate_harnesses(query="image")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "CLI-Anything market command failed")
        self.assertEqual(result["candidates"], [])

    def test_candidate_harnesses_marks_capability_collisions(self):
        class FakeHub(CliAnythingHub):
            def list_market(self) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "list", "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[
                        {"name": "gimp", "display_name": "GIMP", "_source": "harness"},
                        {"name": "GIMP!", "display_name": "GIMP duplicate", "_source": "public"},
                    ],
                )

        with tempfile.TemporaryDirectory() as tmp:
            result = FakeHub(root=Path(tmp)).candidate_harnesses()
            self.assertTrue(result["ok"])
            self.assertEqual(result["install_candidate_count"], 0)
            self.assertEqual(result["blocked_count"], 2)
            self.assertTrue(
                all(
                    "duplicate capability_id generated from market records" in item["blockers"]
                    for item in result["candidates"]
                )
            )
            self.assertTrue(all(item["lifecycle"]["state"] == "blocked" for item in result["candidates"]))

    def test_candidate_harnesses_blocks_generic_declared_requirements(self):
        class FakeHub(CliAnythingHub):
            def list_market(self) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "list", "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[
                        {
                            "name": "krita",
                            "display_name": "Krita",
                            "description": "Digital painting and raster image editing",
                            "requires": "krita (krita.org)",
                            "entry_point": "cli-anything-krita",
                        }
                    ],
                )

        with tempfile.TemporaryDirectory() as tmp:
            result = FakeHub(root=Path(tmp)).candidate_harnesses()
            self.assertTrue(result["ok"])
            self.assertEqual(result["install_candidate_count"], 0)
            candidate = result["candidates"][0]
            self.assertFalse(candidate["install_candidate"])
            self.assertEqual(candidate["requirements"]["signals"], ["external-app:krita"])
            self.assertIn("declared requirements need external app, account, token, or service", candidate["blockers"])

    def test_sync_market_previews_multiple_harness_manifests(self):
        class FakeHub(CliAnythingHub):
            def search_market(self, query: str) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "search", query, "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json={"items": [SAMPLE_MARKET_RECORD, {"display_name": "ffmpeg", "category": "video"}]},
                )

        with tempfile.TemporaryDirectory() as tmp:
            result = FakeHub(root=Path(tmp)).sync_market(query="image", limit=10)
            self.assertTrue(result["ok"])
            self.assertFalse(result["write"])
            self.assertEqual(result["market_count"], 2)
            self.assertEqual(result["importable_count"], 2)
            ids = [item["capability_id"] for item in result["manifests"]]
            self.assertEqual(ids, ["cli-anything.gimp.launch", "cli-anything.ffmpeg.launch"])
            self.assertTrue(all(item["validation"]["valid"] for item in result["manifests"]))
            self.assertFalse(Path(result["manifests"][0]["manifest_path"]).exists())

    def test_sync_market_write_imports_bounded_manifests(self):
        class FakeHub(CliAnythingHub):
            def list_market(self) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "list", "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[
                        SAMPLE_MARKET_RECORD,
                        {"name": "imagemagick", "display_name": "ImageMagick", "category": "image"},
                    ],
                )

        with tempfile.TemporaryDirectory() as tmp:
            result = FakeHub(root=Path(tmp)).sync_market(limit=1, write=True)
            self.assertTrue(result["ok"])
            self.assertTrue(result["write"])
            self.assertEqual(result["selected_count"], 1)
            written = Path(result["manifests"][0]["written"])
            self.assertTrue(written.exists())
            payload = json.loads(written.read_text(encoding="utf-8"))
            self.assertEqual(payload["metadata"]["id"], "cli-anything.gimp.launch")

    def test_sync_market_reports_capability_id_collisions_without_writing(self):
        class FakeHub(CliAnythingHub):
            def list_market(self) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "list", "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[
                        {"name": "gimp", "display_name": "GIMP", "_source": "harness"},
                        {"name": "GIMP!", "display_name": "GIMP duplicate", "_source": "public"},
                    ],
                )

        with tempfile.TemporaryDirectory() as tmp:
            result = FakeHub(root=Path(tmp)).sync_market(write=True)
            self.assertFalse(result["ok"])
            self.assertTrue(result["write"])
            self.assertEqual(result["conflict_count"], 2)
            self.assertEqual(result["failed_count"], 2)
            self.assertEqual(result["importable_count"], 0)
            self.assertFalse((Path(tmp) / "manifests" / "cli-anything.gimp.launch.json").exists())
            errors = {item["error"] for item in result["manifests"]}
            self.assertEqual(errors, {"duplicate capability_id generated from market records"})
            collision = result["manifests"][0]["collision"]
            self.assertEqual(collision["capability_id"], "cli-anything.gimp.launch")
            self.assertEqual(len(collision["market_records"]), 2)

    def test_sync_market_writes_only_non_colliding_valid_manifests(self):
        class FakeHub(CliAnythingHub):
            def list_market(self) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "list", "--json"),
                    exit_code=0,
                    stdout="",
                    stderr="",
                    parsed_json=[
                        {"name": "gimp", "display_name": "GIMP", "_source": "harness"},
                        {"name": "GIMP!", "display_name": "GIMP duplicate", "_source": "public"},
                        {"name": "inkscape", "display_name": "Inkscape", "_source": "harness"},
                    ],
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = FakeHub(root=root).sync_market(write=True)
            self.assertFalse(result["ok"])
            self.assertEqual(result["conflict_count"], 2)
            self.assertEqual(result["failed_count"], 2)
            self.assertEqual(result["importable_count"], 1)
            self.assertFalse((root / "manifests" / "cli-anything.gimp.launch.json").exists())
            self.assertTrue((root / "manifests" / "cli-anything.inkscape.launch.json").exists())

    def test_sync_market_reports_unsupported_json_shape(self):
        class FakeHub(CliAnythingHub):
            def list_market(self) -> CliHubCommandResult:
                return CliHubCommandResult(
                    argv=("cli-hub", "list", "--json"),
                    exit_code=0,
                    stdout="{}",
                    stderr="",
                    parsed_json={"unexpected": []},
                )

        result = FakeHub().sync_market()
        self.assertFalse(result["ok"])
        self.assertIn("supported JSON list shape", result["error"])

    def test_manifest_for_harness_uses_pty_launch_boundary(self):
        manifest = CliAnythingHub().manifest_for_harness("gimp")
        self.assertEqual(manifest["metadata"]["id"], "cli-anything.gimp.launch")
        self.assertEqual(manifest["metadata"]["labels"]["plugin"], "cli-anything")
        self.assertEqual(manifest["spec"]["transport"]["kind"], "pty")
        self.assertEqual(manifest["spec"]["transport"]["argsTemplate"], ["launch", "gimp", "--"])
        self.assertEqual(manifest["spec"]["transport"]["timeoutSeconds"], 600)
        self.assertFalse(manifest["spec"]["output"]["verified"])

    def test_manifest_for_harness_infers_write_workspace_policy(self):
        manifest = CliAnythingHub().manifest_for_harness("gimp", market_record=SAMPLE_MARKET_RECORD)
        self.assertEqual(manifest["spec"]["policy"]["risk"], "write-workspace")
        self.assertFalse(manifest["spec"]["policy"]["requiresConfirmation"])
        self.assertEqual(manifest["spec"]["policy"]["network"], "deny")
        self.assertIn("cli-anything.policy_inference", manifest["metadata"]["annotations"])

    def test_manifest_for_harness_infers_external_network_policy(self):
        market_record = {
            "name": "generate-veo-video",
            "display_name": "Generate Veo Video",
            "description": "Generate videos with Google Veo via Vertex AI and Gemini",
            "requires": "GOOGLE_CLOUD_PROJECT env var and GEMINI_API_KEY optional",
            "entry_point": "generate-veo",
            "_source": "public",
        }
        manifest = CliAnythingHub().manifest_for_harness(
            "generate-veo-video",
            market_record=market_record,
        )
        policy = manifest["spec"]["policy"]
        self.assertEqual(policy["risk"], "external-network")
        self.assertTrue(policy["requiresConfirmation"])
        self.assertEqual(policy["network"], "requires-confirmation")

    def test_manifest_for_harness_keeps_local_service_policy_local(self):
        market_record = {
            "name": "comfyui",
            "display_name": "ComfyUI",
            "description": "AI image generation workflow management via ComfyUI REST API",
            "requires": "ComfyUI running at http://localhost:8188",
            "entry_point": "cli-anything-comfyui",
        }
        manifest = CliAnythingHub().manifest_for_harness("comfyui", market_record=market_record)
        policy = manifest["spec"]["policy"]
        self.assertEqual(policy["risk"], "write-workspace")
        self.assertFalse(policy["requiresConfirmation"])
        self.assertEqual(policy["network"], "localhost")

    def test_infer_market_policy_only_escalates_risk(self):
        policy = infer_market_policy(SAMPLE_MARKET_RECORD, requested_risk="privileged")
        self.assertEqual(policy["risk"], "privileged")
        self.assertTrue(policy["requires_confirmation"])

    def test_manifest_ir_preserves_harness_labels(self):
        manifest = CapabilityManifest.from_dict(CliAnythingHub().manifest_for_harness("gimp"))
        self.assertEqual(manifest.labels["plugin"], "cli-anything")
        self.assertEqual(manifest.labels["harness"], "gimp")
        self.assertEqual(manifest.as_record()["labels"]["harness"], "gimp")

    def test_manifest_for_harness_keeps_market_metadata(self):
        manifest = CliAnythingHub().manifest_for_harness("gimp", market_record=SAMPLE_MARKET_RECORD)
        metadata = manifest["metadata"]
        self.assertEqual(metadata["title"], "CLI-Anything GIMP")
        self.assertEqual(metadata["labels"]["category"], "image")
        self.assertEqual(metadata["labels"]["source"], "harness")
        self.assertEqual(metadata["annotations"]["cli-anything.version"], "1.0.0")
        self.assertEqual(metadata["annotations"]["cli-anything.entry_point"], "cli-anything-gimp")
        self.assertIn("CLI-Anything-Team", metadata["annotations"]["cli-anything.contributors"])

    def test_harness_plan_uses_cli_hub_lifecycle_command(self):
        plan = CliAnythingHub().harness_plan("install", "gimp")
        self.assertEqual(plan.plugin_id, "cli-anything")
        self.assertEqual(plan.action, "harness-install-gimp")
        self.assertEqual(plan.commands[0].argv, ("cli-hub", "install", "gimp"))
        self.assertIn("evaluate-harness", plan.as_dict()["notes"][0])

        uninstall = CliAnythingHub().harness_plan("uninstall", "gimp")
        self.assertEqual(uninstall.action, "harness-uninstall-gimp")
        self.assertEqual(uninstall.commands[0].argv, ("cli-hub", "uninstall", "gimp"))
        self.assertEqual(uninstall.as_dict()["notes"], [])

    def test_cli_harness_plan_does_not_execute_without_yes(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "plugin",
                "harness",
                "cli-anything",
                "install",
                "gimp",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(proc.returncode, 2)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["plugin_id"], "cli-anything")
        self.assertEqual(payload["commands"][0]["argv"], ["cli-hub", "install", "gimp"])
        self.assertTrue(payload["notes"])

    def test_cli_harness_uninstall_plan_does_not_execute_without_yes(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "plugin",
                "harness",
                "cli-anything",
                "uninstall",
                "gimp",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(proc.returncode, 2)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["action"], "harness-uninstall-gimp")
        self.assertEqual(payload["commands"][0]["argv"], ["cli-hub", "uninstall", "gimp"])

    def test_cli_harness_status_outputs_json(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "plugin",
                "harness",
                "cli-anything",
                "status",
                "gimp",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["plugin_id"], "cli-anything")
        self.assertEqual(payload["harness_name"], "gimp")
        self.assertIn("launch_ready", payload)

    def test_cli_adapt_harness_outputs_adaptation_report(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "plugin",
                "adapt-harness",
                "cli-anything",
                "gimp",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["manifest"]["metadata"]["id"], "cli-anything.gimp.launch")
        self.assertFalse(payload["write"])
        self.assertIn("next_commands", payload)

    def test_cli_onboard_harness_outputs_onboarding_report_offline(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "plugin",
                "onboard-harness",
                "cli-anything",
                "gimp",
                "--offline",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["kind"], "CliAnythingHarnessOnboarding")
        self.assertEqual(payload["harness_name"], "gimp")
        self.assertFalse(payload["from_market"])
        self.assertIn("stage_results", payload)
        self.assertIn("verification", payload["reports"])

    def test_cli_onboard_harness_install_preview_requires_yes(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "plugin",
                "onboard-harness",
                "cli-anything",
                "gimp",
                "--offline",
                "--install",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["install"])
        self.assertTrue(payload["summary"]["install_requires_confirmation"])
        self.assertFalse(payload["summary"]["install_executed"])
        self.assertEqual(payload["summary"]["install_execution_status"], "requires_confirmation")

    def test_cli_prepare_harness_outputs_preparation_report(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "plugin",
                "prepare-harness",
                "cli-anything",
                "gimp",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["plugin_id"], "cli-anything")
        self.assertEqual(payload["harness_name"], "gimp")
        self.assertTrue(payload["gates"]["manifest_valid"])
        self.assertIn("install", payload["plans"])

    def test_cli_evaluate_harness_outputs_candidate_report(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "plugin",
                "evaluate-harness",
                "cli-anything",
                "mermaid",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertIn(proc.returncode, {0, 6})
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["plugin_id"], "cli-anything")
        self.assertEqual(payload["harness_name"], "mermaid")
        self.assertIn("install_candidate", payload)
        self.assertIn("recommended_next_action", payload)

    def test_cli_verify_harness_outputs_verification_report_offline(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "plugin",
                "verify-harness",
                "cli-anything",
                "mermaid",
                "--offline",
                "--no-workflows",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["plugin_id"], "cli-anything")
        self.assertEqual(payload["harness_name"], "mermaid")
        self.assertIn("protocols", payload)
        self.assertIn("verification_stages", payload)

    def test_cli_live_verification_outputs_snapshot(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "plugin",
                "live-verification",
                "cli-anything",
                "--harness",
                "mermaid",
                "--no-candidates",
                "--no-workflows",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertIn(proc.returncode, {0, 6})
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["plugin_id"], "cli-anything")
        self.assertEqual(payload["kind"], "CliAnythingLiveVerification")
        self.assertIn("summary", payload)
        self.assertIn("harnesses", payload)

    def test_cli_candidates_handles_missing_cli_hub_without_crashing(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "plugin",
                "candidates",
                "cli-anything",
                "--query",
                "image",
                "--limit",
                "5",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertIn(proc.returncode, {0, 6})
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["plugin_id"], "cli-anything")
        self.assertIn("candidates", payload)
        self.assertIn("install_candidate_count", payload)

    def test_cli_install_queue_handles_missing_cli_hub_without_crashing(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "plugin",
                "install-queue",
                "cli-anything",
                "--query",
                "file",
                "--limit",
                "5",
                "--max-installs",
                "2",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertIn(proc.returncode, {0, 6})
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["plugin_id"], "cli-anything")
        self.assertEqual(payload["kind"], "CliAnythingMarketInstallQueue")
        self.assertIn("queue", payload)
        self.assertIn("summary", payload)

    def test_cli_blocked_plan_outputs_decision_report(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "plugin",
                "blocked-plan",
                "cli-anything",
                "--harness",
                "py4csr",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertIn(proc.returncode, {0, 6})
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["plugin_id"], "cli-anything")
        self.assertEqual(payload["kind"], "CliAnythingBlockedHarnessPlan")
        self.assertIn("blocked", payload)
        self.assertIn("summary", payload)

    def test_cli_repair_plan_outputs_entrypoint_report(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "plugin",
                "repair-plan",
                "cli-anything",
                "py4csr",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertIn(proc.returncode, {0, 6})
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["plugin_id"], "cli-anything")
        self.assertEqual(payload["kind"], "CliAnythingEntrypointRepairPlan")
        self.assertIn("diagnosis", payload)
        self.assertIn("commands", payload)

    def test_cli_repair_entrypoint_outputs_blocked_adapter_target_report(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "plugin",
                "repair-entrypoint",
                "cli-anything",
                "py4csr",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertIn(proc.returncode, {0, 6})
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["plugin_id"], "cli-anything")
        self.assertEqual(payload["kind"], "CliAnythingEntrypointRepair")
        self.assertIn("strategy", payload)
        self.assertIn("execution", payload)

    def test_cli_sync_market_handles_missing_cli_hub_without_crashing(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn",
                "plugin",
                "sync-market",
                "cli-anything",
                "--query",
                "image",
                "--limit",
                "5",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertIn(proc.returncode, {0, 6})
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["plugin_id"], "cli-anything")
        self.assertIn("manifests", payload)

    def test_write_harness_manifest_writes_utf8_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hub = CliAnythingHub(root=root)
            path = hub.write_harness_manifest("GIMP")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(path.name, "cli-anything.gimp.launch.json")
            self.assertEqual(payload["metadata"]["id"], "cli-anything.gimp.launch")

    def test_cli_import_harness_prints_manifest_without_writing(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cbn", "plugin", "import-harness", "cli-anything", "gimp"],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["metadata"]["id"], "cli-anything.gimp.launch")
        self.assertEqual(payload["spec"]["transport"]["argsTemplate"], ["launch", "gimp", "--"])


if __name__ == "__main__":
    unittest.main()
