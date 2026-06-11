"""Machine-readable CLI import surface for external CBN consumers."""

from __future__ import annotations

from typing import Any


IMPORT_CATALOG_API_VERSION = "bridge.dev/v1alpha1"


def cli_registration_surface(api_version: str = IMPORT_CATALOG_API_VERSION) -> dict[str, Any]:
    """Return the dry-run-first importer catalog exposed by CBN."""

    importers = [
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
        {
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
        },
        {
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
        },
        {
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
        },
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
    return {
        "apiVersion": api_version,
        "kind": "CliRegistrationSurface",
        "status": "ready",
        "importer_count": len(importers),
        "default_policy": {
            "dry_run_by_default": True,
            "writes_require_explicit_flag": True,
            "side_effects_require_confirmation": True,
            "utf8_required": True,
        },
        "importers": importers,
        "next_commands": [
            "python -m cbn import catalog",
            *(str(importer["help_command"]) for importer in importers),
        ],
    }
