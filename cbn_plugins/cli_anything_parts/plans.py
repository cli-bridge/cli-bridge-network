"""Plugin operation plans for CLI-Anything harness lifecycle actions."""

from __future__ import annotations

from typing import Any

from cbn_plugins.cli_anything_parts.manifest_factory import sanitize_harness_name
from cbn_plugins.manager import (
    PluginCommand,
    PluginPlan,
    verification_report_for_plan,
)


PLUGIN_ID = "cli-anything"


def harness_plan(
    hub: Any,
    action: str,
    harness_name: str,
    extra_args: tuple[str, ...] = (),
) -> PluginPlan:
    if action not in {"install", "update", "uninstall", "launch"}:
        raise ValueError(f"unsupported CLI-Anything harness action: {action}")
    safe_name = sanitize_harness_name(harness_name)
    if action == "launch":
        argv = (hub.entrypoint, "launch", harness_name, *extra_args)
    else:
        argv = (hub.entrypoint, action, harness_name)
    return PluginPlan(
        plugin_id=PLUGIN_ID,
        action=f"harness-{action}-{safe_name}",
        plugin_dir=str(hub.paths.external_plugins / PLUGIN_ID),
        commands=(
            PluginCommand(
                label=f"CLI-Anything harness {action}: {harness_name}",
                argv=argv,
            ),
        ),
        notes=(
            f"Preflight install/update with: python -m cbn plugin evaluate-harness cli-anything {harness_name}",
        )
        if action in {"install", "update"}
        else (),
        verification_commands=(
            f"python -m cbn plugin harness cli-anything status {harness_name} --from-market",
            f"python -m cbn plugin verify-harness cli-anything {harness_name} --no-workflows",
            f"python -m cbn call cli-anything.{safe_name}.launch --dry-run",
        )
        if action in {"install", "update"}
        else (
            f"python -m cbn plugin harness cli-anything status {harness_name} --from-market",
        ),
    )

def verify_harness_plan(
    hub: Any,
    action: str,
    harness_name: str,
    extra_args: tuple[str, ...] = (),
    run: bool = False,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    safe_name = sanitize_harness_name(harness_name)
    plan = harness_plan(hub, action, harness_name, extra_args=extra_args)
    return verification_report_for_plan(
        plan,
        report_kind="CliAnythingHarnessPlanVerificationReport",
        run=run,
        timeout_seconds=timeout_seconds,
        next_commands=(
            (
                f"python -m cbn plugin verify-harness-plan cli-anything {action} "
                f"{harness_name}"
            ),
            (
                f"python -m cbn plugin verify-harness-plan cli-anything {action} "
                f"{harness_name} --run"
            ),
        ),
        extra={
            "harness_name": harness_name,
            "safe_name": safe_name,
            "capability_id": f"cli-anything.{safe_name}.launch",
        },
    )
