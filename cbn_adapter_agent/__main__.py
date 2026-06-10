"""Command line entrypoint for the CBN Adapter Agent harness."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from cbn_adapter_agent.compiler import (
    BUILT_IN_PROFILES,
    build_adapter_draft,
    build_adapter_draft_batch,
    write_adapter_draft,
)
from cbn_adapter_agent.coordinator import build_multi_agent_coordination_plan
from cbn_adapter_agent.llm_validation import validate_with_glm
from cbn_adapter_agent.manifest_bootstrap import build_manifest_bootstrap_plan
from cbn_adapter_agent.orchestrator import DEFAULT_WORKFLOW_PATH, build_orchestration_turn
from cbn_adapter_agent.tool_call_plan import build_agent_tool_call_plan, write_agent_loop_checkpoint
from cbn_adapter_agent.workflow_init import build_workflow_initialization_plan
from cbn_adapter_agent.workflow_setup import build_workflow_setup_plan


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="python -m cbn_adapter_agent")
    parser.add_argument("--profile", action="append", default=[], help="Built-in adapter profile to draft.")
    parser.add_argument("--all", action="store_true", help="Draft every built-in adapter profile.")
    parser.add_argument("--root", help="Project root. Defaults to the current CBN checkout.")
    parser.add_argument("--manifest-bootstrap", action="store_true", help="Build the split Manifest Bootstrap Agent plan.")
    parser.add_argument("--workflow-init", help="Build initial workflow setup guidance for auth-gated nodes.")
    parser.add_argument("--workflow-setup", help="Build the split Workflow Setup Agent plan.")
    parser.add_argument("--coordination-plan", action="store_true", help="Build the split multi-agent coordination plan.")
    parser.add_argument("--tool-call-plan", action="store_true", help="Build Adapter Agent tool-call and long-loop plan.")
    parser.add_argument("--write-loop-checkpoint", action="store_true", help="Write long-loop checkpoint when used with --tool-call-plan.")
    parser.add_argument("--orchestrate", action="store_true", help="Run one Adapter Agent orchestration turn.")
    parser.add_argument("--message", default="", help="User message for --orchestrate.")
    parser.add_argument(
        "--workflow-path",
        default=DEFAULT_WORKFLOW_PATH,
        help="Workflow JSON path for --orchestrate. Defaults to the auth-gated first-run example.",
    )
    parser.add_argument("--glm-validate", action="store_true", help="Validate the draft/plan with GLM using ZAI_API_KEY.")
    parser.add_argument("--write-draft", action="store_true", help="Write draft JSON files under runtime.")
    parser.add_argument("--out", help="Draft output directory when --write-draft is used.")
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else None
    if args.orchestrate:
        payload = build_orchestration_turn(
            message=args.message,
            workflow_path=args.workflow_path,
            root=root,
            use_glm=args.glm_validate,
        )
    elif args.coordination_plan:
        payload = build_multi_agent_coordination_plan(
            message=args.message,
            workflow_path=args.workflow_path,
            profiles=tuple(args.profile) or None,
            root=root,
        )
    elif args.tool_call_plan:
        payload = build_agent_tool_call_plan(
            message=args.message,
            workflow_path=args.workflow_path,
            root=root,
        )
        if args.write_loop_checkpoint:
            payload = {**payload, "loop_checkpoint": write_agent_loop_checkpoint(payload, root=root)}
    elif args.workflow_setup:
        payload = build_workflow_setup_plan(Path(args.workflow_setup), root=root)
    elif args.workflow_init:
        payload = build_workflow_initialization_plan(Path(args.workflow_init), root=root)
    elif args.manifest_bootstrap:
        payload = build_manifest_bootstrap_plan(profiles=tuple(args.profile) or None, root=root)
    elif args.all:
        payload = build_adapter_draft_batch(root=root)
    else:
        profiles = tuple(args.profile) or ("feishu",)
        if len(profiles) == 1:
            payload = build_adapter_draft(profiles[0], root=root)
        else:
            payload = build_adapter_draft_batch(profiles=profiles, root=root)

    written: list[dict[str, str]] = []
    if args.write_draft:
        output_dir = Path(args.out) if args.out else None
        if payload.get("kind") in {"AdapterAgentDraftBatch", "ManifestBootstrapPlan"}:
            drafts = payload.get("drafts", [])
        elif payload.get("kind") == "AdapterAgentDraft":
            drafts = [payload]
        else:
            drafts = []
        written = [write_adapter_draft(draft, output_dir=output_dir, root=root) for draft in drafts]
        payload = {**payload, "written": written}

    if args.glm_validate and payload.get("kind") != "AdapterAgentOrchestrationTurn":
        payload = {**payload, "llm_validation": validate_with_glm(payload)}

    print(json.dumps(payload, ensure_ascii=False, indent=args.indent))
    if payload.get("kind") in {
        "WorkflowInitializationPlan",
        "WorkflowSetupPlan",
        "AdapterAgentCoordinationPlan",
        "AdapterAgentToolCallPlan",
        "AdapterAgentOrchestrationTurn",
    }:
        return 0
    return 0 if payload.get("ok", True) else 6


if __name__ == "__main__":
    raise SystemExit(main())
