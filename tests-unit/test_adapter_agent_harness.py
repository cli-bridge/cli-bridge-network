import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cbn_audit.log import AuditLog
from cbn_adapter_agent.compiler import (
    build_adapter_draft,
    build_adapter_draft_batch,
    write_adapter_draft,
)
from cbn_adapter_agent.coordinator import build_multi_agent_coordination_plan
from cbn_adapter_agent.llm_validation import _bounded_payload, stream_with_glm, validate_with_glm
from cbn_adapter_agent.manifest_bootstrap import build_manifest_bootstrap_plan
from cbn_adapter_agent.orchestrator import build_orchestration_turn
from cbn_adapter_agent.tool_call_plan import build_agent_tool_call_plan, write_agent_loop_checkpoint
from cbn_adapter_agent.tool_use import run_setup_tool, store_session_secret
from cbn_adapter_agent.workflow_init import build_workflow_initialization_plan
from cbn_adapter_agent.workflow_setup import build_workflow_setup_plan
from cbn_events.bus import EventBus


class AdapterAgentHarnessTests(unittest.TestCase):
    def test_adapter_agent_draft_collects_profile_candidates(self):
        draft = build_adapter_draft("jimeng")

        self.assertEqual(draft["kind"], "AdapterAgentDraft")
        self.assertEqual(draft["profile"]["profile_id"], "jimeng")
        self.assertEqual(draft["agent_role"]["role_id"], "manifest-bootstrap-agent")
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

    def test_manifest_bootstrap_plan_is_separate_agent(self):
        plan = build_manifest_bootstrap_plan(profiles=("jimeng",), include_drafts=False)

        self.assertEqual(plan["kind"], "ManifestBootstrapPlan")
        self.assertEqual(plan["agent_role"]["role_id"], "manifest-bootstrap-agent")
        self.assertFalse(plan["agent_policy"]["installs_tools"])
        self.assertFalse(plan["agent_policy"]["runs_workflow_tasks"])
        self.assertEqual(plan["handoff"]["to"], "workflow-setup-agent")
        self.assertEqual(plan["profile_scope"], ["jimeng"])
        self.assertNotIn("drafts", plan)

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
        self.assertEqual(plan["agent_role"]["role_id"], "workflow-setup-agent")
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

    def test_workflow_setup_plan_is_split_agent_payload(self):
        plan = build_workflow_setup_plan(Path("workflows/auth-gated-first-run.example.json"))

        self.assertEqual(plan["kind"], "WorkflowSetupPlan")
        self.assertEqual(plan["agent_role"]["role_id"], "workflow-setup-agent")
        self.assertFalse(plan["agent_policy"]["drafts_manifests"])
        self.assertEqual(plan["handoff"]["from"], "manifest-bootstrap-agent")
        self.assertEqual(plan["handoff"]["to"], "workflow-setup-agent")

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

    def test_adapter_agent_coordination_plan_splits_roles(self):
        plan = build_multi_agent_coordination_plan(
            message="initialize",
            workflow_path="workflows/auth-gated-first-run.example.json",
        )

        self.assertEqual(plan["kind"], "AdapterAgentCoordinationPlan")
        roles = {agent["role_id"]: agent for agent in plan["agents"]}
        self.assertIn("manifest-bootstrap-agent", roles)
        self.assertIn("workflow-setup-agent", roles)
        self.assertIn("orchestration-coordinator-agent", roles)
        self.assertIn("verification-agent", roles)
        self.assertNotEqual(
            roles["manifest-bootstrap-agent"]["output_kind"],
            roles["workflow-setup-agent"]["output_kind"],
        )
        handoff_pairs = {(handoff["from"], handoff["to"]) for handoff in plan["handoffs"]}
        self.assertIn(("manifest-bootstrap-agent", "workflow-setup-agent"), handoff_pairs)
        self.assertIn(("workflow-setup-agent", "orchestration-coordinator-agent"), handoff_pairs)
        self.assertEqual(plan["tool_call_plan_summary"]["tool_call_count"], 9)
        self.assertEqual(plan["long_running_loop"]["kind"], "AdapterAgentLoopPlan")

    def test_adapter_agent_coordination_plan_cli_outputs_json(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn_adapter_agent",
                "--coordination-plan",
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
        self.assertEqual(payload["kind"], "AdapterAgentCoordinationPlan")
        self.assertEqual(payload["agents"][0]["role_id"], "manifest-bootstrap-agent")
        self.assertEqual(proc.stderr, "")

    def test_adapter_agent_tool_call_plan_models_batches_hooks_and_loop(self):
        plan = build_agent_tool_call_plan(
            message="initialize",
            workflow_path="workflows/auth-gated-first-run.example.json",
        )

        self.assertEqual(plan["kind"], "AdapterAgentToolCallPlan")
        self.assertEqual(plan["duplicate_guard"]["tracks"], "tool_use_id")
        self.assertEqual(plan["summary"]["tool_call_count"], 9)
        self.assertEqual(plan["summary"]["by_kind"]["setup-command"], 5)
        self.assertEqual(plan["summary"]["by_kind"]["setup-secret"], 1)
        self.assertEqual(plan["summary"]["by_kind"]["workflow-capability"], 3)
        self.assertGreaterEqual(plan["summary"]["requires_user_count"], 4)
        batch_modes = {batch["mode"] for batch in plan["execution_batches"]}
        self.assertIn("parallel", batch_modes)
        self.assertIn("serial", batch_modes)
        parallel_batches = [batch for batch in plan["execution_batches"] if batch["mode"] == "parallel"]
        self.assertTrue(any(len(batch["tool_call_ids"]) >= 2 for batch in parallel_batches))
        first_call = plan["tool_calls"][0]
        self.assertIn("pre_tool_use_hooks", first_call["permission_flow"]["order"])
        self.assertTrue(any(hook["event"] == "PermissionRequest" for hook in first_call["hook_points"]))
        loop = plan["long_running_loop"]
        self.assertEqual(loop["status"], "waiting_on_setup")
        checkpoint_ids = {checkpoint["id"] for checkpoint in loop["checkpoints"]}
        self.assertIn("completion-audit", checkpoint_ids)
        self.assertIn("approval_state", loop["session_scoped_state"])

    def test_adapter_agent_tool_call_plan_cli_outputs_json(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbn_adapter_agent",
                "--tool-call-plan",
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
        self.assertEqual(payload["kind"], "AdapterAgentToolCallPlan")
        self.assertEqual(payload["long_running_loop"]["kind"], "AdapterAgentLoopPlan")
        self.assertEqual(proc.stderr, "")

    def test_adapter_agent_loop_checkpoint_writes_utf8_json(self):
        plan = build_agent_tool_call_plan(workflow_path="workflows/auth-gated-first-run.example.json")
        with tempfile.TemporaryDirectory() as tmp:
            result = write_agent_loop_checkpoint(plan, root=Path(tmp))
            payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))

        self.assertEqual(payload["kind"], "AdapterAgentLoopPlan")
        self.assertEqual(payload["loop_id"], result["loop_id"])

    def test_adapter_agent_orchestration_turn_guides_auth_fallback(self):
        turn = build_orchestration_turn(
            message="Initialize. api-key:dummy-redaction-token.abcdefghijklmnopqrstuvwxyz",
            workflow_path="workflows/auth-gated-first-run.example.json",
            use_glm=False,
        )

        self.assertEqual(turn["kind"], "AdapterAgentOrchestrationTurn")
        self.assertEqual(turn["status"], "requires_user_setup_and_inputs")
        self.assertEqual(turn["coordination_plan"]["kind"], "AdapterAgentCoordinationPlan")
        role_ids = {agent["role_id"] for agent in turn["coordination_plan"]["agents"]}
        self.assertIn("manifest-bootstrap-agent", role_ids)
        self.assertIn("workflow-setup-agent", role_ids)
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

    def test_glm_stream_reports_missing_key_without_network(self):
        with patch.dict("os.environ", {}, clear=True):
            events = list(stream_with_glm({"kind": "sample"}, system_prompt="test"))

        self.assertEqual(events[0]["type"], "error")
        self.assertTrue(events[0]["skipped"])
        self.assertFalse(events[0]["ok"])

    def test_adapter_agent_tool_use_stores_secret_without_echoing_value(self):
        env_store = {}
        result = store_session_secret(env_store, name="OBSIDIAN_API_KEY", value="test-secret-value")

        self.assertTrue(result["ok"])
        self.assertTrue(result["call_id"])
        self.assertEqual(env_store["OBSIDIAN_API_KEY"], "test-secret-value")
        self.assertEqual(result["stored"], "OBSIDIAN_API_KEY")
        self.assertNotIn("test-secret-value", json.dumps(result, ensure_ascii=False))

    def test_adapter_agent_tool_use_emits_audit_and_events_without_secret_value(self):
        env_store = {}
        with tempfile.TemporaryDirectory() as tmp:
            audit = AuditLog(Path(tmp) / "audit.jsonl")
            events = EventBus(Path(tmp) / "events.jsonl")
            result = store_session_secret(
                env_store,
                name="OBSIDIAN_API_KEY",
                value="test-secret-value",
                audit_log=audit,
                event_bus=events,
            )
            audit_text = Path(tmp, "audit.jsonl").read_text(encoding="utf-8")
            event_types = [event["type"] for event in events.tail(limit=10)]

        self.assertTrue(result["ok"])
        self.assertIn("adapter_agent.tool_call.started", audit_text)
        self.assertIn("adapter_agent.tool_call.completed", audit_text)
        self.assertIn("adapter_agent.tool_call.started", event_types)
        self.assertIn("adapter_agent.tool_call.completed", event_types)
        self.assertNotIn("test-secret-value", audit_text)

    def test_adapter_agent_tool_use_rejects_unknown_setup_command(self):
        result = run_setup_tool(
            workflow_path="workflows/auth-gated-first-run.example.json",
            setup_id="jimeng-oauth-login",
            command_id="not-declared",
        )

        self.assertFalse(result["ok"])
        self.assertTrue(result["call_id"])
        self.assertIn("unknown command_id", result["error"])

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
