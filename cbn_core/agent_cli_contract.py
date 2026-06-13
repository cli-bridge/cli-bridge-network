"""Mapping from external Agent CLI Contract objects to CBN core contracts."""

from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

from cbn_core.manifest import MANIFEST_API_VERSION
from cbn_core.message import BridgeMessage


AGENT_CLI_API_VERSION = "agent-cli.dev/v1alpha1"
AGENT_CLI_CARD_KIND = "AgentCliCard"
RUN_RECEIPT_KIND = "RunReceipt"
CONTRACT_PYTHON_ROOT = Path(__file__).resolve().parents[1] / "external_protocols" / "agent-cli-contract" / "python"
CONTRACT_ROOT = Path(__file__).resolve().parents[1] / "external_protocols" / "agent-cli-contract"
CONTRACT_CARD_FIXTURE = CONTRACT_ROOT / "fixtures" / "agent-cli-card.valid.json"
CONTRACT_RECEIPT_FIXTURE = CONTRACT_ROOT / "fixtures" / "run-receipt.valid.json"


def agent_cli_contract_package_boundary(root: Path | None = None) -> dict[str, Any]:
    """Return the standalone external protocol package boundary consumed by CBN."""

    contract_root = root or CONTRACT_ROOT
    return {
        "kind": "ExternalProtocolPackageBoundary",
        "package_name": "agent-cli-contract",
        "npm_name": "@agent-cli/contract",
        "python_name": "agent-cli-contract",
        "version": "0.1.0",
        "root": str(contract_root),
        "schemas": agent_cli_contract_schema_paths(contract_root),
        "typescript_types": str(contract_root / "ts" / "index.ts"),
        "python_validator": str(contract_root / "python" / "agent_cli_contract" / "validator.py"),
        "fixtures": agent_cli_contract_fixture_paths(contract_root),
        "conformance_smoke": agent_cli_contract_smoke_paths(contract_root),
        "dependency_boundary": agent_cli_contract_dependency_boundary(),
        "cbn_mapping_responsibility": {
            "AgentCliCard": "CBN maps external command declarations to ToolManifest records.",
            "RunReceipt": "CBN maps run receipts to BridgeMessage, Artifact records, Audit evidence, and Events.",
        },
    }


def agent_cli_contract_schema_paths(contract_root: Path) -> dict[str, str]:
    return {
        "AgentCliCard": str(contract_root / "schemas" / "agent-cli-card.schema.json"),
        "RunReceipt": str(contract_root / "schemas" / "run-receipt.schema.json"),
    }


def agent_cli_contract_fixture_paths(contract_root: Path) -> dict[str, str]:
    return {
        "AgentCliCard": str(contract_root / "fixtures" / "agent-cli-card.valid.json"),
        "RunReceipt": str(contract_root / "fixtures" / "run-receipt.valid.json"),
    }


def agent_cli_contract_smoke_paths(contract_root: Path) -> dict[str, str]:
    return {
        "command": "python external_protocols/agent-cli-contract/scripts/conformance_smoke.py",
        "script": str(contract_root / "scripts" / "conformance_smoke.py"),
    }


def agent_cli_contract_dependency_boundary() -> dict[str, Any]:
    return {
        "standalone": True,
        "forbidden_cbn_modules": _forbidden_cbn_modules(),
        "allowed_scope": [
            "AgentCliCard schema",
            "RunReceipt schema",
            "TypeScript types",
            "Python validation CLI",
            "fixtures",
            "conformance smoke",
        ],
    }


def agent_cli_contract_package_health(root: Path | None = None) -> dict[str, Any]:
    """Return machine-readable evidence that the external contract package is standalone."""

    contract_root = root or CONTRACT_ROOT
    boundary = agent_cli_contract_package_boundary(contract_root)
    files = _contract_package_files(contract_root)
    metadata = _contract_package_metadata(contract_root)
    independence = _contract_independence_report(contract_root)
    ok = (
        all(item["exists"] for item in files)
        and metadata["npm_name"] == boundary["npm_name"]
        and metadata["python_name"] == boundary["python_name"]
        and metadata["npm_version"] == boundary["version"]
        and metadata["python_version"] == boundary["version"]
        and independence["ok"]
    )
    return {
        "kind": "AgentCliContractPackageHealth",
        "ok": ok,
        "root": str(contract_root),
        "package_boundary": boundary,
        "metadata": metadata,
        "file_count": len(files),
        "files": files,
        "independence": independence,
    }


def agent_cli_card_to_tool_manifests(card: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert one AgentCliCard into CBN ToolManifest dictionaries."""

    _validate_external_contract(card, target="card")
    _require_agent_cli_card(card)
    metadata = card["metadata"]
    spec = card["spec"]
    runtime = spec.get("runtime") if isinstance(spec.get("runtime"), dict) else {}
    card_id = metadata["id"]
    return [_agent_cli_command_manifest(card_id, metadata, runtime, command) for command in spec["commands"]]


def _agent_cli_command_manifest(
    card_id: str,
    card_metadata: dict[str, Any],
    runtime: dict[str, Any],
    command: dict[str, Any],
) -> dict[str, Any]:
    command_id = command["id"]
    argv = list(command["argv"])
    capability_id = f"{card_id}.{command_id}"
    return {
        "apiVersion": MANIFEST_API_VERSION,
        "kind": "ToolManifest",
        "metadata": _agent_cli_manifest_metadata(capability_id, card_id, card_metadata, runtime, command),
        "spec": _agent_cli_manifest_spec(runtime, command, argv),
    }


def _agent_cli_manifest_metadata(
    capability_id: str,
    card_id: str,
    card_metadata: dict[str, Any],
    runtime: dict[str, Any],
    command: dict[str, Any],
) -> dict[str, Any]:
    command_id = command["id"]
    return {
        "id": capability_id,
        "title": command.get("title", capability_id),
        "labels": {
            "adapter": "agent-cli-contract",
            "agent_cli_card": card_id,
            **_string_labels(card_metadata.get("labels", {})),
        },
        "annotations": {
            "cbn.external_protocol": "agent-cli-contract",
            "cbn.agent_cli.card_id": card_id,
            "cbn.agent_cli.command_id": command_id,
            "cbn.agent_cli.runtime_kind": str(runtime.get("kind", "stdio")),
            "cbn.agent_cli.card_version": str(card_metadata.get("version", "")),
        },
    }


def _agent_cli_manifest_spec(
    runtime: dict[str, Any],
    command: dict[str, Any],
    argv: list[str],
) -> dict[str, Any]:
    policy = command.get("policy") if isinstance(command.get("policy"), dict) else {}
    output = command.get("output") if isinstance(command.get("output"), dict) else {}
    return {
        "transport": {
            "kind": _cbn_transport_kind(runtime.get("kind")),
            "command": argv[0],
            "argsTemplate": argv[1:],
            "cwdPolicy": str(runtime.get("cwdPolicy", "workspace")),
            "timeoutSeconds": int(command.get("timeoutSeconds", 30)),
        },
        "policy": {
            "risk": str(policy.get("risk", "read")),
            "requiresConfirmation": bool(policy.get("requiresConfirmation", False)),
            "network": str(policy.get("network", "deny")),
        },
        "output": {
            "parserRef": str(output.get("parser", "raw.text")),
            "verified": False,
        },
    }


def run_receipt_to_cbn_records(receipt: dict[str, Any]) -> dict[str, Any]:
    """Convert a RunReceipt into BridgeMessage plus audit/event correlation records."""

    _validate_external_contract(receipt, target="receipt")
    _require_run_receipt(receipt)
    run_id = receipt["runId"]
    producer = f"{receipt['cardId']}.{receipt['commandId']}"
    artifacts = tuple(_receipt_artifact_to_cbn(item) for item in receipt.get("artifacts", []))
    status = receipt["status"]
    return {
        "kind": "AgentCliRunReceiptMapping",
        "apiVersion": MANIFEST_API_VERSION,
        "message": _receipt_bridge_message(receipt, producer, run_id, artifacts),
        "artifacts": list(artifacts),
        "audit_event": _receipt_audit_event(receipt, producer, run_id, status),
        "event": _receipt_event(producer, run_id, status, artifacts),
    }


def _receipt_bridge_message(
    receipt: dict[str, Any],
    producer: str,
    run_id: str,
    artifacts: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    return BridgeMessage(
        producer=producer,
        channel="agent-cli.run.receipt",
        correlation_id=run_id,
        payload=_receipt_payload(receipt),
        artifacts=artifacts,
    ).as_dict()


def _receipt_payload(receipt: dict[str, Any]) -> dict[str, Any]:
    status = receipt["status"]
    payload = {
        "parser_ref": _receipt_parser_ref(receipt),
        "ok": status == "completed",
        "data": {
            "status": status,
            "exit_code": receipt.get("exitCode"),
            "stdout": receipt.get("stdout", ""),
            "stderr": receipt.get("stderr", ""),
            "parsed": receipt.get("parsed", {}),
        },
    }
    if status != "completed":
        error = receipt.get("error") if isinstance(receipt.get("error"), dict) else {}
        payload["error"] = str(error.get("message") or status)
    return payload


def _receipt_audit_event(
    receipt: dict[str, Any],
    producer: str,
    run_id: str,
    status: str,
) -> dict[str, Any]:
    return {
        "type": "agent_cli.run_receipt",
        "call_id": run_id,
        "capability_id": producer,
        "status": status,
        "exit_code": receipt.get("exitCode"),
        "correlation": receipt.get("correlation", {}),
    }


def _receipt_event(
    producer: str,
    run_id: str,
    status: str,
    artifacts: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    return {
        "type": "agent_cli.run.completed" if status == "completed" else "agent_cli.run.stopped",
        "subject": producer,
        "correlation_id": run_id,
        "payload": {
            "status": status,
            "artifact_count": len(artifacts),
        },
    }


def _validate_external_contract(payload: dict[str, Any], *, target: str) -> None:
    validators = _external_contract_validators()
    validator = validators[target]
    report = validator(payload)
    if not report.get("ok"):
        errors = report.get("errors", [])
        if isinstance(errors, list) and errors:
            raise ValueError(f"invalid Agent CLI {target}: {'; '.join(str(error) for error in errors)}")
        raise ValueError(f"invalid Agent CLI {target}")


def _external_contract_validators() -> dict[str, Any]:
    try:
        from agent_cli_contract import validate_agent_cli_card, validate_run_receipt
    except ModuleNotFoundError:
        if not CONTRACT_PYTHON_ROOT.exists():
            raise
        contract_path = str(CONTRACT_PYTHON_ROOT)
        if contract_path not in sys.path:
            sys.path.insert(0, contract_path)
        from agent_cli_contract import validate_agent_cli_card, validate_run_receipt
    return {
        "card": validate_agent_cli_card,
        "receipt": validate_run_receipt,
    }


def _require_agent_cli_card(card: dict[str, Any]) -> None:
    if card.get("apiVersion") != AGENT_CLI_API_VERSION:
        raise ValueError(f"unsupported AgentCliCard apiVersion: {card.get('apiVersion')}")
    if card.get("kind") != AGENT_CLI_CARD_KIND:
        raise ValueError(f"unsupported AgentCliCard kind: {card.get('kind')}")
    commands = _require_agent_cli_card_spec(card)
    _require_agent_cli_card_metadata(card)
    for index, command in enumerate(commands):
        _require_agent_cli_command(command, index)


def _require_agent_cli_card_metadata(card: dict[str, Any]) -> dict[str, Any]:
    metadata = card.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("id"), str):
        return metadata
    raise ValueError("AgentCliCard metadata.id is required")


def _require_agent_cli_card_spec(card: dict[str, Any]) -> list[Any]:
    spec = card.get("spec")
    if isinstance(spec, dict) and isinstance(spec.get("commands"), list):
        return spec["commands"]
    raise ValueError("AgentCliCard spec.commands is required")


def _require_agent_cli_command(command: Any, index: int) -> dict[str, Any]:
    if not isinstance(command, dict):
        raise ValueError(f"AgentCliCard spec.commands[{index}] must be an object")
    if not isinstance(command.get("id"), str) or not command["id"]:
        raise ValueError(f"AgentCliCard spec.commands[{index}].id is required")
    argv = command.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
        raise ValueError(f"AgentCliCard spec.commands[{index}].argv must be a non-empty string array")
    return command


def _require_run_receipt(receipt: dict[str, Any]) -> None:
    if receipt.get("apiVersion") != AGENT_CLI_API_VERSION:
        raise ValueError(f"unsupported RunReceipt apiVersion: {receipt.get('apiVersion')}")
    if receipt.get("kind") != RUN_RECEIPT_KIND:
        raise ValueError(f"unsupported RunReceipt kind: {receipt.get('kind')}")
    for key in ("runId", "cardId", "commandId", "status"):
        if not isinstance(receipt.get(key), str) or not receipt[key]:
            raise ValueError(f"RunReceipt {key} is required")


def _string_labels(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def _cbn_transport_kind(kind: Any) -> str:
    if kind in {"stdio", "pty"}:
        return str(kind)
    return "stdio"


def _receipt_parser_ref(receipt: dict[str, Any]) -> str:
    parsed = receipt.get("parsed")
    if isinstance(parsed, dict) and isinstance(parsed.get("parser_ref"), str):
        return parsed["parser_ref"]
    return "agent-cli.run-receipt"


def _receipt_artifact_to_cbn(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": str(artifact.get("id", "")),
        "kind": str(artifact.get("kind", "")),
        "path": str(artifact.get("uri", "")),
        "media_type": str(artifact.get("mediaType", "application/octet-stream")),
        "size_bytes": int(artifact.get("sizeBytes", 0)),
        "truncated": False,
    }


def _contract_package_files(root: Path) -> list[dict[str, Any]]:
    expected = [
        ("package_json", "package.json", "npm package metadata"),
        ("pyproject", "pyproject.toml", "Python package metadata"),
        ("readme", "README.md", "standalone package documentation"),
        ("agent_cli_card_schema", "schemas/agent-cli-card.schema.json", "AgentCliCard JSON Schema"),
        ("run_receipt_schema", "schemas/run-receipt.schema.json", "RunReceipt JSON Schema"),
        ("typescript_types", "ts/index.ts", "TypeScript type exports"),
        ("python_validator", "python/agent_cli_contract/validator.py", "Python validator API"),
        ("python_cli", "python/agent_cli_contract/__main__.py", "Python validation CLI"),
        ("card_fixture", "fixtures/agent-cli-card.valid.json", "valid AgentCliCard fixture"),
        ("receipt_fixture", "fixtures/run-receipt.valid.json", "valid RunReceipt fixture"),
        ("static_check", "scripts/check.mjs", "Node static contract check"),
        ("conformance_smoke", "scripts/conformance_smoke.py", "standalone conformance smoke"),
    ]
    return [
        {
            "id": file_id,
            "path": str(root / relative_path),
            "relative_path": relative_path,
            "role": role,
            "exists": (root / relative_path).exists(),
        }
        for file_id, relative_path, role in expected
    ]


def _contract_package_metadata(root: Path) -> dict[str, Any]:
    package_json = _read_optional_json(root / "package.json")
    pyproject = _read_optional_toml(root / "pyproject.toml")
    project = pyproject.get("project") if isinstance(pyproject.get("project"), dict) else {}
    return {
        "npm_name": package_json.get("name"),
        "npm_version": package_json.get("version"),
        "npm_private": package_json.get("private"),
        "npm_exports": package_json.get("exports", {}),
        "python_name": project.get("name"),
        "python_version": project.get("version"),
        "python_dependencies": project.get("dependencies", []),
        "python_requires": project.get("requires-python"),
    }


def _contract_independence_report(root: Path) -> dict[str, Any]:
    offenders = []
    forbidden = _forbidden_cbn_modules()
    for path in _contract_source_files(root):
        for module in _forbidden_imports_in_file(path, forbidden):
            offenders.append(
                {
                    "path": str(path.relative_to(root)),
                    "module": module,
                }
            )
    return {
        "ok": not offenders,
        "forbidden_cbn_modules": forbidden,
        "offenders": offenders,
        "source_file_count": len(_contract_source_files(root)),
    }


def _contract_source_files(root: Path) -> list[Path]:
    patterns = ["python/**/*.py", "scripts/*.py", "scripts/*.mjs", "ts/**/*.ts"]
    files: list[Path] = []
    for pattern in patterns:
        files.extend(path for path in root.glob(pattern) if path.is_file())
    return sorted(files)


def _forbidden_imports_in_file(path: Path, forbidden: list[str]) -> list[str]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        return _forbidden_python_imports(text, forbidden)
    return _forbidden_js_imports(text, forbidden)


def _forbidden_python_imports(text: str, forbidden: list[str]) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    return _matching_forbidden_modules(imported, forbidden)


def _forbidden_js_imports(text: str, forbidden: list[str]) -> list[str]:
    imported = []
    for match in re.finditer(r"(?:from\s+|import\s*\(\s*|require\s*\(\s*)['\"]([^'\"]+)['\"]", text):
        imported.append(match.group(1))
    return _matching_forbidden_modules(imported, forbidden)


def _matching_forbidden_modules(imported: list[str], forbidden: list[str]) -> list[str]:
    matches = []
    for module in forbidden:
        if any(item == module or item.startswith(f"{module}.") for item in imported):
            matches.append(module)
    return matches


def _forbidden_cbn_modules() -> list[str]:
    return [
        "api_server",
        "cbn",
        "cbn_agent",
        "cbn_core",
        "cbn_demo",
        "cbn_tools",
        "cbn_workflow",
        "cbn_runtime",
        "cbn_protocol",
        "cbn_artifact",
        "cbn_audit",
    ]


def _read_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_optional_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))
