"""Auth and account setup guidance for Adapter Agent workflow initialization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cbn.paths import resolve_project_paths
from cbn_core.manifest import CapabilityManifest
from cbn_tools.external_cli import require_action


@dataclass(frozen=True)
class SetupCommand:
    id: str
    title: str
    argv: tuple[str, ...]
    execution: str = "user-run"

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "argv": list(self.argv),
            "execution": self.execution,
        }


@dataclass(frozen=True)
class AuthSetupGuide:
    setup_id: str
    profile: str
    capability_id: str
    title: str
    status: str
    reason: str
    secret_inputs: tuple[dict[str, object], ...]
    user_steps: tuple[str, ...]
    verification_commands: tuple[SetupCommand, ...]
    resume_hint: str

    def as_dict(self) -> dict[str, object]:
        return {
            "setup_id": self.setup_id,
            "profile": self.profile,
            "capability_id": self.capability_id,
            "title": self.title,
            "status": self.status,
            "reason": self.reason,
            "secret_inputs": list(self.secret_inputs),
            "user_steps": list(self.user_steps),
            "verification_commands": [command.as_dict() for command in self.verification_commands],
            "resume_hint": self.resume_hint,
        }


def auth_setup_required(manifest: CapabilityManifest) -> bool:
    gate = manifest.annotations.get("cbn.auth_gate", "").strip().casefold()
    return bool(gate) and not gate.startswith("none")


def runtime_input_requirements(manifest: CapabilityManifest) -> list[dict[str, object]]:
    capability_id = manifest.capability_id
    if capability_id == "jimeng.text2image.submit":
        return [
            {
                "name": "prompt",
                "kind": "text",
                "required": True,
                "source": "workflow args or argsFrom",
                "example_arg": "--prompt=a product concept image",
            },
            {
                "name": "generation_options",
                "kind": "cli-flags",
                "required": False,
                "source": "workflow args",
                "example_arg": "--ratio=1:1",
            },
        ]
    if capability_id == "obsidian-cli.local-rest.note.read":
        return [
            {
                "name": "note_path",
                "kind": "vault-relative-path",
                "required": True,
                "source": "workflow args or UI note picker",
                "example_arg": "Projects/demo.md",
            },
            {
                "name": "OBSIDIAN_API_KEY",
                "kind": "secret",
                "required": True,
                "source": "environment variable or secret store",
                "persist_in_repo": False,
            },
        ]
    return []


def build_auth_setup_guide(
    manifest: CapabilityManifest,
    *,
    workflow_path: Path | None = None,
    root: Path | None = None,
) -> AuthSetupGuide | None:
    if not auth_setup_required(manifest):
        return None
    profile = manifest.annotations.get("cbn.adapter.profile") or manifest.labels.get("profile") or "unknown"
    if profile == "jimeng":
        return _jimeng_setup_guide(manifest, workflow_path=workflow_path, root=root)
    if profile == "obsidian-cli":
        return _obsidian_setup_guide(manifest, workflow_path=workflow_path, root=root)
    if profile == "feishu":
        return _feishu_setup_guide(manifest, workflow_path=workflow_path, root=root)
    if profile == "caw":
        return _caw_setup_guide(manifest, workflow_path=workflow_path, root=root)
    return _generic_setup_guide(manifest, workflow_path=workflow_path)


def _jimeng_setup_guide(
    manifest: CapabilityManifest,
    *,
    workflow_path: Path | None,
    root: Path | None,
) -> AuthSetupGuide:
    paths = resolve_project_paths(root)
    login = require_action("jimeng", "login").argv(paths.root)
    headless = require_action("jimeng", "login-headless").argv(paths.root)
    verify = require_action("jimeng", "user-credit").argv(paths.root)
    return AuthSetupGuide(
        setup_id="jimeng-oauth-login",
        profile="jimeng",
        capability_id=manifest.capability_id,
        title="Jimeng/Dreamina OAuth Login",
        status="pending_user_action",
        reason=manifest.annotations.get("cbn.auth_gate", "Dreamina account login is required."),
        secret_inputs=(),
        user_steps=(
            "Run the interactive login command and complete the OAuth device flow in the browser.",
            "For headless sessions, run the headless login command, open the verification URI, enter the user code, then poll with login checklogin using the printed device_code.",
            "After login, run the verification command to confirm the local Dreamina session before resuming the workflow.",
        ),
        verification_commands=(
            SetupCommand("login", "Start interactive Dreamina OAuth login", tuple(login)),
            SetupCommand("login-headless", "Start headless Dreamina OAuth login", tuple(headless)),
            SetupCommand("verify-user-credit", "Verify Dreamina login and account credit", tuple(verify)),
        ),
        resume_hint=_resume_hint(workflow_path),
    )


def _obsidian_setup_guide(
    manifest: CapabilityManifest,
    *,
    workflow_path: Path | None,
    root: Path | None,
) -> AuthSetupGuide:
    paths = resolve_project_paths(root)
    status = require_action("obsidian-cli", "local-rest-server-status").argv(paths.root)
    official = require_action("obsidian-cli", "official-help").argv(paths.root)
    return AuthSetupGuide(
        setup_id="obsidian-local-rest-api-key",
        profile="obsidian-cli",
        capability_id=manifest.capability_id,
        title="Obsidian Local REST API Key and CLI Enablement",
        status="pending_user_action",
        reason=manifest.annotations.get("cbn.auth_gate", "Obsidian setup is required."),
        secret_inputs=(
            {
                "name": "OBSIDIAN_API_KEY",
                "kind": "environment-variable",
                "storage": "current-shell-or-user-secret-store",
                "persist_in_repo": False,
            },
        ),
        user_steps=(
            "Open the target Obsidian vault and enable the Local REST API plugin.",
            "Generate or copy the plugin API key and set OBSIDIAN_API_KEY in the current shell or your secret store; do not write it into the repository.",
            "If using the official Obsidian CLI shim, enable the desktop CLI toggle in Settings > General > Advanced.",
            "Run the server status verification command before resuming note-read workflow nodes.",
        ),
        verification_commands=(
            SetupCommand("verify-local-rest", "Verify Obsidian Local REST server status", tuple(status)),
            SetupCommand("verify-official-cli", "Verify official Obsidian CLI shim", tuple(official)),
        ),
        resume_hint=_resume_hint(workflow_path),
    )


def _feishu_setup_guide(
    manifest: CapabilityManifest,
    *,
    workflow_path: Path | None,
    root: Path | None,
) -> AuthSetupGuide:
    paths = resolve_project_paths(root)
    doctor = require_action("feishu", "doctor").argv(paths.root)
    return AuthSetupGuide(
        setup_id="feishu-profile-auth",
        profile="feishu",
        capability_id=manifest.capability_id,
        title="Feishu/Lark CLI Profile and Auth",
        status="pending_user_action",
        reason=manifest.annotations.get("cbn.auth_gate", "Feishu/Lark credentials are required."),
        secret_inputs=(
            {
                "name": "lark-cli profile credentials",
                "kind": "external-cli-profile",
                "storage": "lark-cli-managed-profile",
                "persist_in_repo": False,
            },
        ),
        user_steps=(
            "Configure the intended lark-cli profile with app credentials or OAuth credentials.",
            "Run lark-cli auth help or the auth flow required by your Feishu/Lark tenant.",
            "Run the doctor verification command before resuming workflow nodes that call Feishu/Lark APIs.",
        ),
        verification_commands=(
            SetupCommand("verify-doctor", "Verify Feishu/Lark CLI config and connectivity", tuple(doctor)),
        ),
        resume_hint=_resume_hint(workflow_path),
    )


def _caw_setup_guide(
    manifest: CapabilityManifest,
    *,
    workflow_path: Path | None,
    root: Path | None,
) -> AuthSetupGuide:
    paths = resolve_project_paths(root)
    status = require_action("caw", "status").argv(paths.root)
    return AuthSetupGuide(
        setup_id="caw-wallet-auth",
        profile="caw",
        capability_id=manifest.capability_id,
        title="Cobo Agentic Wallet Pairing or API Key",
        status="pending_user_action",
        reason=manifest.annotations.get("cbn.auth_gate", "Cobo Agentic Wallet auth is required."),
        secret_inputs=(
            {
                "name": "CAW API key",
                "kind": "api-key-or-wallet-pairing",
                "storage": "current-shell-or-caw-managed-state",
                "persist_in_repo": False,
            },
        ),
        user_steps=(
            "Pair or provision the Cobo Agentic Wallet account required for this workflow.",
            "If using an API key, pass it through the CLI or secret-managed environment; do not write it into manifests or workflow files.",
            "Run the status verification command before resuming wallet or chain workflow nodes.",
        ),
        verification_commands=(
            SetupCommand("verify-status", "Verify Cobo Agentic Wallet status", tuple(status)),
        ),
        resume_hint=_resume_hint(workflow_path),
    )


def _generic_setup_guide(
    manifest: CapabilityManifest,
    *,
    workflow_path: Path | None,
) -> AuthSetupGuide:
    profile = manifest.annotations.get("cbn.adapter.profile") or manifest.labels.get("profile") or "unknown"
    return AuthSetupGuide(
        setup_id=f"{profile}-manual-auth",
        profile=profile,
        capability_id=manifest.capability_id,
        title=f"{manifest.title} Auth Setup",
        status="pending_user_action",
        reason=manifest.annotations.get("cbn.auth_gate", "Manual auth setup is required."),
        secret_inputs=(),
        user_steps=("Complete the auth or account setup required by this capability, then run its safest status command.",),
        verification_commands=(),
        resume_hint=_resume_hint(workflow_path),
    )


def _resume_hint(workflow_path: Path | None) -> str:
    if workflow_path is None:
        return "Resume the workflow initialization after setup verification passes."
    return f"After setup verification passes, resume with: python -m cbn workflow run {workflow_path} --yes"
