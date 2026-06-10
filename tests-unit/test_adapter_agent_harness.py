import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cbn_adapter_agent.compiler import (
    build_adapter_draft,
    build_adapter_draft_batch,
    write_adapter_draft,
)
from cbn_adapter_agent.llm_validation import _bounded_payload, validate_with_glm
from cbn_adapter_agent.orchestrator import build_orchestration_turn
from cbn_adapter_agent.workflow_init import build_workflow_initialization_plan


class AdapterAgentHarnessTests(unittest.TestCase):
    def test_adapter_agent_draft_collects_profile_candidates(self):
        draft = build_adapter_draft("jimeng")

        self.assertEqual(draft["kind"], "AdapterAgentDraft")
        self.assertEqual(draft["profile"]["profile_id"], "jimeng")
        self.assertFalse(draft["agent_policy"]["llm_runtime_dependency"])

        candidates = {item["capability_id"]: item for item in draft["capability_candidates"]}
        self.assertIn("jimeng.version", candidates)
        self.assertIn("jimeng.text2image.submit", candidates)
        self.assertIn("jimeng.query_result", candidates)
        self.assertEqual(candidates["jimeng.version"]["policy"]["risk"], "read")
        self.assertEqual(candidates["jimeng.text2image.submit"]["policy"]["risk"], "external-network")
        setup_ids = {guide["setup_id"] for guide in draft["setup_guides"]}
        self.assertIn("jimeng-oauth-login", setup_ids)

    def test_adapter_agent_draft_keeps_acceptance_pending_after_parser_verification(self):
        draft = build_adapter_draft("caw")
        stages = {stage["id"]: stage for stage in draft["stages"]}

        self.assertEqual(stages["parser_contracts"]["status"], "passed")
        self.assertEqual(stages["parser_contracts"]["evidence"]["unverified_capabilities"], [])
        self.assertEqual(stages["acceptance"]["status"], "pending")
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

    def test_workflow_initialization_guides_auth_gated_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            workflow_path = Path(tmp) / "auth-workflow.json"
            workflow_path.write_text(
                json.dumps(
                    {
                        "apiVersion": "bridge.dev/v1alpha1",
                        "kind": "Workflow",
                        "metadata": {"id": "auth.workflow", "title": "Auth Workflow"},
                        "spec": {
                            "tasks": [
                                {"id": "draft-image", "uses": "jimeng.text2image.submit"},
                                {
                                    "id": "read-note",
                                    "uses": "obsidian-cli.local-rest.note.read",
                                    "needs": ["draft-image"],
                                },
                            ]
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            plan = build_workflow_initialization_plan(workflow_path)

        self.assertEqual(plan["kind"], "WorkflowInitializationPlan")
        self.assertEqual(plan["status"], "requires_user_setup_and_inputs")
        self.assertEqual(plan["summary"]["blocking_task_count"], 2)
        self.assertEqual(plan["summary"]["input_blocking_task_count"], 2)
        setup_ids = {guide["setup_id"] for guide in plan["setup_guides"]}
        self.assertIn("jimeng-oauth-login", setup_ids)
        self.assertIn("obsidian-local-rest-api-key", setup_ids)

        obsidian = next(guide for guide in plan["setup_guides"] if guide["setup_id"] == "obsidian-local-rest-api-key")
        self.assertEqual(obsidian["secret_inputs"][0]["name"], "OBSIDIAN_API_KEY")
        self.assertFalse(obsidian["secret_inputs"][0]["persist_in_repo"])
        note_task = next(task for task in plan["tasks"] if task["uses"] == "obsidian-cli.local-rest.note.read")
        missing_names = {item["name"] for item in note_task["missing_runtime_inputs"]}
        self.assertIn("note_path", missing_names)
        self.assertIn("OBSIDIAN_API_KEY", missing_names)
        self.assertIn("--yes", plan["continuation"]["command"])

    def test_workflow_initialization_marks_jimeng_query_result_submit_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            workflow_path = Path(tmp) / "query-workflow.json"
            workflow_path.write_text(
                json.dumps(
                    {
                        "apiVersion": "bridge.dev/v1alpha1",
                        "kind": "Workflow",
                        "metadata": {"id": "query.workflow"},
                        "spec": {"tasks": [{"id": "query", "uses": "jimeng.query_result"}]},
                    }
                ),
                encoding="utf-8",
            )

            plan = build_workflow_initialization_plan(workflow_path)

        query_task = plan["tasks"][0]
        missing_names = {item["name"] for item in query_task["missing_runtime_inputs"]}
        self.assertIn("submit_id", missing_names)
        self.assertEqual(query_task["status"], "requires_setup_and_inputs")

    def test_workflow_initialization_resolves_relative_path_from_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_dir = root / "manifests"
            manifest_dir.mkdir()
            (manifest_dir / "jimeng.user-credit.json").write_text(
                Path("manifests/jimeng.user-credit.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            workflow_dir = root / "workflows"
            workflow_dir.mkdir()
            workflow_path = workflow_dir / "auth-workflow.json"
            workflow_path.write_text(
                json.dumps(
                    {
                        "apiVersion": "bridge.dev/v1alpha1",
                        "kind": "Workflow",
                        "metadata": {"id": "auth.workflow"},
                        "spec": {"tasks": [{"id": "credit", "uses": "jimeng.user_credit"}]},
                    }
                ),
                encoding="utf-8",
            )
            plan = build_workflow_initialization_plan(Path("workflows/auth-workflow.json"), root=root)

        self.assertEqual(plan["workflow"]["path"], str(Path("workflows/auth-workflow.json")))
        self.assertEqual(plan["tasks"][0]["uses"], "jimeng.user_credit")

    def test_adapter_agent_workflow_init_cli_outputs_guidance(self):
        with tempfile.TemporaryDirectory() as tmp:
            workflow_path = Path(tmp) / "auth-workflow.json"
            workflow_path.write_text(
                json.dumps(
                    {
                        "apiVersion": "bridge.dev/v1alpha1",
                        "kind": "Workflow",
                        "metadata": {"id": "auth.workflow"},
                        "spec": {"tasks": [{"id": "credit", "uses": "jimeng.user_credit"}]},
                    }
                ),
                encoding="utf-8",
            )
            proc = subprocess.run(
                [sys.executable, "-m", "cbn_adapter_agent", "--workflow-init", str(workflow_path)],
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "requires_user_setup")
        self.assertEqual(payload["setup_guides"][0]["setup_id"], "jimeng-oauth-login")

    def test_adapter_agent_orchestration_turn_guides_auth_fallback(self):
        turn = build_orchestration_turn(
            message="Initialize. api-key:dummy-redaction-token.abcdefghijklmnopqrstuvwxyz",
            workflow_path="workflows/auth-gated-first-run.example.json",
            use_glm=False,
        )

        self.assertEqual(turn["kind"], "AdapterAgentOrchestrationTurn")
        self.assertEqual(turn["status"], "requires_user_setup_and_inputs")
        self.assertTrue(turn["message_redacted"])
        self.assertNotIn("dummy-redaction-token", json.dumps(turn, ensure_ascii=False))
        setup_ids = {
            fallback["setup"]["setup_id"]
            for fallback in turn["auth_fallbacks"]
            if fallback.get("setup")
        }
        self.assertIn("jimeng-oauth-login", setup_ids)
        self.assertIn("obsidian-local-rest-api-key", setup_ids)
        route_by_task = {route["task_id"]: route for route in turn["cli_routes"]}
        self.assertEqual(route_by_task["query-image-result"]["args_from"][0]["task"], "draft-image")
        self.assertIn("--yes", turn["continuation"]["command"])

    def test_adapter_agent_orchestrate_cli_outputs_guidance_without_failure_exit(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn_adapter_agent",
                "--orchestrate",
                "--workflow-path",
                "workflows/auth-gated-first-run.example.json",
                "--message",
                "initialize",
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["kind"], "AdapterAgentOrchestrationTurn")
        self.assertEqual(payload["recommended_next_action"], "guide_user_setup_and_collect_inputs")
        self.assertEqual(proc.stderr, "")

    def test_glm_validation_skips_without_key(self):
        with patch.dict("os.environ", {}, clear=True):
            result = validate_with_glm({"kind": "sample"})
        self.assertTrue(result["skipped"])
        self.assertFalse(result["ok"])

    def test_glm_validation_bounds_adapter_batch_without_dropping_drafts(self):
        batch = build_adapter_draft_batch()
        batch["padding"] = "x" * 20000
        bounded = _bounded_payload(batch)

        self.assertEqual(bounded["truncation_strategy"], "adapter-draft-summary")
        self.assertEqual(len(bounded["drafts"]), 4)
        first = bounded["drafts"][0]
        self.assertIn("capability_candidates", first)
        self.assertTrue(first["capability_candidates"])

    def test_glm_validation_bounds_orchestration_turn_without_dropping_setup(self):
        turn = build_orchestration_turn(
            message="Initialize",
            workflow_path="workflows/auth-gated-first-run.example.json",
            use_glm=False,
        )
        turn["padding"] = "x" * 20000
        bounded = _bounded_payload(turn)

        self.assertEqual(bounded["truncation_strategy"], "adapter-orchestration-turn")
        self.assertEqual(bounded["workflow_initialization"]["status"], "requires_user_setup_and_inputs")
        setup_ids = {
            guide["setup_id"]
            for guide in bounded["workflow_initialization"]["setup_guides"]
        }
        self.assertIn("jimeng-oauth-login", setup_ids)
        self.assertIn("obsidian-local-rest-api-key", setup_ids)
        self.assertTrue(bounded["auth_fallbacks"])


if __name__ == "__main__":
    unittest.main()
