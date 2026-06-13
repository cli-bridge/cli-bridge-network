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
from cbn_adapter_agent.nodes import build_adapter_agent_node_bundle
from cbn_adapter_agent.orchestrator import DEFAULT_WORKFLOW_PATH, build_orchestration_turn
from cbn_adapter_agent.tool_call_plan import build_agent_tool_call_plan, write_agent_loop_checkpoint
from cbn_adapter_agent.workflow_request import build_agent_workflow_request_plan
from cbn_adapter_agent.workflow_init import build_workflow_initialization_plan
from cbn_adapter_agent.workflow_setup import build_workflow_setup_plan


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = _build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root) if args.root else None
    payload = _select_payload(args, root)
    payload = _write_drafts_if_requested(payload, args, root)
    if args.glm_validate and payload.get("kind") != "AdapterAgentOrchestrationTurn":
        payload = {**payload, "llm_validation": validate_with_glm(payload)}

    print(json.dumps(payload, ensure_ascii=False, indent=args.indent))
    return _exit_code(payload)


def _configure_stdio() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m cbn_adapter_agent")
    parser.add_argument("--profile", action="append", default=[], help="Built-in adapter profile to draft.")
    parser.add_argument("--all", action="store_true", help="Draft every built-in adapter profile.")
    parser.add_argument("--root", help="Project root. Defaults to the current CBN checkout.")
    parser.add_argument("--manifest-bootstrap", action="store_true", help="Build the split Manifest Bootstrap Agent plan.")
    parser.add_argument("--workflow-init", help="Build initial workflow setup guidance for auth-gated nodes.")
    parser.add_argument("--workflow-setup", help="Build the split Workflow Setup Agent plan.")
    parser.add_argument("--coordination-plan", action="store_true", help="Build the split multi-agent coordination plan.")
    parser.add_argument("--node-bundle", action="store_true", help="Build core cbn_agent node records for the Adapter Agent roles.")
    parser.add_argument("--tool-call-plan", action="store_true", help="Build Adapter Agent tool-call and long-loop plan.")
    parser.add_argument("--workflow-request-plan", action="store_true", help="Build a reusable natural-language workflow invocation plan.")
    parser.add_argument("--write-loop-checkpoint", action="store_true", help="Write long-loop checkpoint when used with --tool-call-plan.")
    parser.add_argument("--orchestrate", action="store_true", help="Run one Adapter Agent orchestration turn.")
    parser.add_argument("--message", default="", help="User message for --orchestrate.")
    parser.add_argument(
        "--workflow-path",
        default=DEFAULT_WORKFLOW_PATH,
        help="Workflow JSON path for --orchestrate. Defaults to the auth-gated first-run example.",
    )
    parser.add_argument(
        "--glm-validate",
        action="store_true",
        help="Validate drafts with GLM; orchestration uses GLM by default.",
    )
    parser.add_argument("--no-glm", action="store_true", help="Disable GLM for an orchestration turn.")
    parser.add_argument("--write-draft", action="store_true", help="Write draft JSON files under runtime.")
    parser.add_argument("--out", help="Draft output directory when --write-draft is used.")
    parser.add_argument("--indent", type=int, default=2)
    return parser


def _select_payload(args: argparse.Namespace, root: Path | None) -> dict[str, object]:
    handler = _select_payload_handler(args)
    if handler:
        return handler(args, root)
    if args.all:
        return build_adapter_draft_batch(root=root)
    return _adapter_draft_payload(tuple(args.profile) or ("feishu",), root)


def _select_payload_handler(args: argparse.Namespace):
    handlers = (
        (args.orchestrate, _orchestration_payload),
        (args.coordination_plan, _coordination_payload),
        (args.node_bundle, _node_bundle_payload),
        (args.tool_call_plan, _tool_call_plan_payload),
        (args.workflow_request_plan, _workflow_request_payload),
        (args.workflow_setup, _workflow_setup_payload),
        (args.workflow_init, _workflow_init_payload),
        (args.manifest_bootstrap, _manifest_bootstrap_payload),
    )
    for enabled, handler in handlers:
        if enabled:
            return handler
    return None


def _orchestration_payload(args: argparse.Namespace, root: Path | None) -> dict[str, object]:
    return build_orchestration_turn(
        message=args.message,
        workflow_path=args.workflow_path,
        root=root,
        use_glm=not args.no_glm,
    )


def _coordination_payload(args: argparse.Namespace, root: Path | None) -> dict[str, object]:
    return build_multi_agent_coordination_plan(
        message=args.message,
        workflow_path=args.workflow_path,
        profiles=tuple(args.profile) or None,
        root=root,
    )


def _node_bundle_payload(args: argparse.Namespace, root: Path | None) -> dict[str, object]:
    return build_adapter_agent_node_bundle(
        message=args.message,
        workflow_path=args.workflow_path,
        profiles=tuple(args.profile) or None,
        root=root,
    )


def _tool_call_plan_payload(args: argparse.Namespace, root: Path | None) -> dict[str, object]:
    payload = build_agent_tool_call_plan(
        message=args.message,
        workflow_path=args.workflow_path,
        root=root,
    )
    if args.write_loop_checkpoint:
        return {**payload, "loop_checkpoint": write_agent_loop_checkpoint(payload, root=root)}
    return payload


def _workflow_request_payload(args: argparse.Namespace, root: Path | None) -> dict[str, object]:
    return build_agent_workflow_request_plan(
        message=args.message,
        workflow_path=args.workflow_path,
        root=root,
        dry_run=True,
        confirmed=False,
    )


def _workflow_setup_payload(args: argparse.Namespace, root: Path | None) -> dict[str, object]:
    return build_workflow_setup_plan(Path(args.workflow_setup), root=root)


def _workflow_init_payload(args: argparse.Namespace, root: Path | None) -> dict[str, object]:
    return build_workflow_initialization_plan(Path(args.workflow_init), root=root)


def _manifest_bootstrap_payload(args: argparse.Namespace, root: Path | None) -> dict[str, object]:
    return build_manifest_bootstrap_plan(profiles=tuple(args.profile) or None, root=root)


def _adapter_draft_payload(profiles: tuple[str, ...], root: Path | None) -> dict[str, object]:
    if len(profiles) == 1:
        return build_adapter_draft(profiles[0], root=root)
    return build_adapter_draft_batch(profiles=profiles, root=root)


def _write_drafts_if_requested(
    payload: dict[str, object],
    args: argparse.Namespace,
    root: Path | None,
) -> dict[str, object]:
    if not args.write_draft:
        return payload

    output_dir = Path(args.out) if args.out else None
    written = [write_adapter_draft(draft, output_dir=output_dir, root=root) for draft in _drafts_from_payload(payload)]
    return {**payload, "written": written}


def _drafts_from_payload(payload: dict[str, object]) -> list[dict[str, object]]:
    if payload.get("kind") in {"AdapterAgentDraftBatch", "ManifestBootstrapPlan"}:
        drafts = payload.get("drafts", [])
        return [draft for draft in drafts if isinstance(draft, dict)]
    if payload.get("kind") == "AdapterAgentDraft":
        return [payload]
    return []


def _exit_code(payload: dict[str, object]) -> int:
    if payload.get("kind") in {
        "WorkflowInitializationPlan",
        "WorkflowSetupPlan",
        "AdapterAgentCoordinationPlan",
        "AdapterAgentNodeBundle",
        "AdapterAgentToolCallPlan",
        "AdapterAgentOrchestrationTurn",
        "AdapterAgentWorkflowRequestPlan",
    }:
        return 0
    return 0 if payload.get("ok", True) else 6


if __name__ == "__main__":
    raise SystemExit(main())
