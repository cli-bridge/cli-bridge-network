"""Machine-readable CLI import surface for external CBN consumers."""

from __future__ import annotations

from typing import Any


IMPORT_CATALOG_API_VERSION = "bridge.dev/v1alpha1"


def cli_registration_surface(api_version: str = IMPORT_CATALOG_API_VERSION) -> dict[str, Any]:
    """Return the dry-run-first importer catalog exposed by CBN."""

    importers = _importers()
    return {
        "apiVersion": api_version,
        "kind": "CliRegistrationSurface",
        "status": "ready",
        "importer_count": len(importers),
        "default_policy": _default_policy(),
        "importers": importers,
        "next_commands": _next_commands(importers),
    }


def _importers() -> list[dict[str, Any]]:
    return [
        *_cli_importers(),
        *_descriptor_importers(),
        *_fixture_importers(),
    ]


def _cli_importers() -> list[dict[str, Any]]:
    return [
        {
            "id": "command",
            "title": "Import ordinary CLI command",
            "entrypoint": "cbn import command",
            "help_command": "python -m cbn import command --help",
            "accepts": ["capability_id", "executable", "args_template", "parser_ref"],
            "produces": ["ToolManifest"],
            "default_side_effects": "none",
            "write_gate": "--write",
            "confirm_gate": None,
            "example": "python -m cbn import command demo.echo --command echo --arg hello",
        },
        {
            "id": "cli-anything",
            "title": "Import CLI-Anything harness",
            "entrypoint": "cbn import cli-anything",
            "help_command": "python -m cbn import cli-anything --help",
            "accepts": ["harness_name", "market metadata", "optional install request"],
            "produces": ["ToolManifest", "onboarding report", "verification plan"],
            "default_side_effects": "none",
            "write_gate": "--write",
            "confirm_gate": "--yes for --write or --install",
            "example": "python -m cbn import cli-anything mermaid --from-market",
        },
    ]


def _descriptor_importers() -> list[dict[str, Any]]:
    return [
        _agent_cli_card_importer(),
        _mcp_descriptor_importer(),
        _skill_descriptor_importer(),
    ]


def _agent_cli_card_importer() -> dict[str, Any]:
    return {
        "id": "agent-cli-card",
        "title": "Import AgentCliCard",
        "entrypoint": "cbn import agent-cli-card",
        "help_command": "python -m cbn import agent-cli-card --help",
        "accepts": ["agent-cli-contract AgentCliCard JSON"],
        "produces": ["ToolManifest"],
        "default_side_effects": "none",
        "write_gate": "--write",
        "confirm_gate": None,
        "example": (
            "python -m cbn import agent-cli-card "
            "--card-file external_protocols/agent-cli-contract/fixtures/agent-cli-card.valid.json"
        ),
    }


def _mcp_descriptor_importer() -> dict[str, Any]:
    return {
        "id": "mcp",
        "title": "Import MCP tool descriptor",
        "entrypoint": "cbn import mcp",
        "help_command": "python -m cbn import mcp --help",
        "accepts": ["MCP tool descriptor JSON", "adapter command"],
        "produces": ["ToolManifest"],
        "default_side_effects": "none",
        "write_gate": "--write",
        "confirm_gate": None,
        "example": "python -m cbn import mcp --tool-file tool.json --server-id local --adapter-command python",
    }


def _skill_descriptor_importer() -> dict[str, Any]:
    return {
        "id": "skill",
        "title": "Import skill descriptor",
        "entrypoint": "cbn import skill",
        "help_command": "python -m cbn import skill --help",
        "accepts": ["UTF-8 JSON or Markdown skill descriptor", "runner command"],
        "produces": ["ToolManifest"],
        "default_side_effects": "none",
        "write_gate": "--write",
        "confirm_gate": None,
        "example": "python -m cbn import skill SKILL.md --command python",
    }


def _fixture_importers() -> list[dict[str, Any]]:
    return [
        {
            "id": "parser-fixture",
            "title": "Record parser fixture",
            "entrypoint": "cbn record-parser-fixture",
            "help_command": "python -m cbn record-parser-fixture --help",
            "accepts": ["parser_ref", "stdout", "stderr", "exit_code"],
            "produces": ["ParserFixture"],
            "default_side_effects": "none",
            "write_gate": "--write",
            "confirm_gate": None,
            "example": "python -m cbn record-parser-fixture raw.text demo --stdout output.txt",
        },
    ]


def _default_policy() -> dict[str, bool]:
    return {
        "dry_run_by_default": True,
        "writes_require_explicit_flag": True,
        "side_effects_require_confirmation": True,
        "utf8_required": True,
    }


def _next_commands(importers: list[dict[str, Any]]) -> list[str]:
    return [
        "python -m cbn import catalog",
        *(str(importer["help_command"]) for importer in importers),
    ]
