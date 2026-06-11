"""Plugin operation catalog helpers."""

from __future__ import annotations

import re
from typing import Any

from cbn_plugins.manifest import PluginManifest


def operation_catalog_for_manifest(manifest: PluginManifest, installed: bool) -> dict[str, Any]:
    operations = _enrich_operations(
        _dedupe_operations(
            [
                *_generic_plugin_operations(manifest),
                *[operation.as_dict() for operation in manifest.operations],
                *_provider_operations(manifest),
            ]
        )
    )
    by_kind: dict[str, int] = {}
    for operation in operations:
        kind = str(operation.get("kind", "unknown"))
        by_kind[kind] = by_kind.get(kind, 0) + 1
    return {
        "ok": True,
        "kind": "PluginProviderOperationCatalog",
        "plugin_api_version": manifest.plugin_api_version,
        "plugin_id": manifest.plugin_id,
        "provider": manifest.provider,
        "title": manifest.title,
        "installed": installed,
        "operation_kinds": ["report", "gate", "plan", "execute", "write"],
        "operations": operations,
        "summary": {
            "operation_count": len(operations),
            "by_kind": by_kind,
            "requires_confirmation_count": sum(
                1 for operation in operations if operation.get("requires_confirmation")
            ),
            "write_or_execute_count": sum(
                1 for operation in operations if operation.get("kind") in {"execute", "write"}
            ),
        },
        "validation": _validate_operation_catalog(manifest, operations),
        "next_commands": [
            f"python -m cbn plugin operations {manifest.plugin_id}",
            f"python -m cbn plugin validate-operations {manifest.plugin_id}",
            f"python -m cbn plugin gate {manifest.plugin_id} --action install",
            f"python -m cbn plugin plan {manifest.plugin_id}",
        ],
    }


def catalog_list_validation(catalogs: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    for catalog in catalogs:
        validation = catalog.get("validation", {})
        errors.extend(f"{catalog.get('plugin_id')}: {error}" for error in validation.get("errors", []))
        warnings.extend(f"{catalog.get('plugin_id')}: {warning}" for warning in validation.get("warnings", []))
    return {
        "ok": not errors,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }


def resolve_string_template(template: str, inputs: dict[str, Any]) -> tuple[str, list[str]]:
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in inputs:
            missing.append(key)
            return match.group(0)
        return str(inputs[key])

    return _PLACEHOLDER_RE.sub(replace, template), missing


def resolve_value_template(value: Any, inputs: dict[str, Any]) -> tuple[Any, list[str]]:
    if isinstance(value, str):
        exact = _PLACEHOLDER_RE.fullmatch(value)
        if exact:
            key = exact.group(1)
            if key not in inputs:
                return value, [key]
            return inputs[key], []
        return resolve_string_template(value, inputs)
    if isinstance(value, list):
        resolved_items = []
        missing: list[str] = []
        for item in value:
            resolved, item_missing = resolve_value_template(item, inputs)
            resolved_items.append(resolved)
            missing.extend(item_missing)
        return resolved_items, missing
    if isinstance(value, dict):
        resolved_dict: dict[str, Any] = {}
        missing: list[str] = []
        for key, item in value.items():
            resolved, item_missing = resolve_value_template(item, inputs)
            resolved_dict[key] = resolved
            missing.extend(item_missing)
        return resolved_dict, missing
    return value, []


def operation_api_request(api: dict[str, Any] | None, payload: Any) -> dict[str, Any] | None:
    if not api:
        return None
    method = api.get("method")
    path = api.get("path")
    request = {
        "method": method,
        "path": path,
    }
    if method == "POST":
        request["json"] = payload if isinstance(payload, dict) else {}
    else:
        request["query"] = payload if isinstance(payload, dict) else {}
    return request


def _generic_plugin_operations(manifest: PluginManifest) -> list[dict[str, Any]]:
    plugin_id = manifest.plugin_id
    return [
        _operation("info", "Plugin Metadata", "report", f"python -m cbn plugin info {plugin_id}"),
        _operation(
            "preflight",
            "Install Preflight",
            "report",
            f"python -m cbn plugin preflight {plugin_id}",
            api={"method": "GET", "path": f"/plugins/{plugin_id}/preflight"} if plugin_id == "cli-anything" else None,
        ),
        _operation(
            "provenance",
            "Source Provenance",
            "report",
            f"python -m cbn plugin provenance {plugin_id}",
            api={"method": "GET", "path": f"/plugins/{plugin_id}/provenance"} if plugin_id == "cli-anything" else None,
        ),
        _operation(
            "check-update",
            "Check Updates",
            "report",
            f"python -m cbn plugin check-update {plugin_id}",
            api={"method": "POST", "path": "/plugins/check-update"},
            payload_template={"plugin_id": plugin_id, "remote": False},
            input_schema={"remote": "boolean"},
        ),
        _operation(
            "install-gate",
            "Install Gate",
            "gate",
            f"python -m cbn plugin gate {plugin_id} --action install",
            api={"method": "POST", "path": "/plugins/gate"},
            payload_template={"plugin_id": plugin_id, "action": "install"},
        ),
        _operation(
            "update-gate",
            "Update Gate",
            "gate",
            f"python -m cbn plugin gate {plugin_id} --action update",
            api={"method": "POST", "path": "/plugins/gate"},
            payload_template={"plugin_id": plugin_id, "action": "update"},
        ),
        _operation(
            "install-plan",
            "Install Plan",
            "plan",
            f"python -m cbn plugin plan {plugin_id}",
            api={"method": "POST", "path": "/plugins/plan"},
            payload_template={"plugin_id": plugin_id, "action": "install"},
        ),
        _operation(
            "update-plan",
            "Update Plan",
            "plan",
            f"python -m cbn plugin plan {plugin_id} --action update",
            api={"method": "POST", "path": "/plugins/plan"},
            payload_template={"plugin_id": plugin_id, "action": "update"},
        ),
        _operation(
            "verify-plan",
            "Post-Operation Verification",
            "report",
            f"python -m cbn plugin verify-plan {plugin_id}",
            api={"method": "POST", "path": "/plugins/verify-plan"},
            payload_template={"plugin_id": plugin_id, "action": "install", "run": False},
            input_schema={"action": "string", "run": "boolean"},
        ),
        _operation(
            "install-execute",
            "Install",
            "execute",
            f"python -m cbn plugin install {plugin_id} --yes",
            api={"method": "POST", "path": "/plugins/execute"},
            requires_confirmation=True,
            side_effects=("subprocess", "external_plugins", "pip", "git"),
            payload_template={"plugin_id": plugin_id, "action": "install", "confirmed": True},
        ),
        _operation(
            "update-execute",
            "Update",
            "execute",
            f"python -m cbn plugin update {plugin_id} --yes",
            api={"method": "POST", "path": "/plugins/execute"},
            requires_confirmation=True,
            side_effects=("subprocess", "external_plugins", "pip", "git"),
            payload_template={"plugin_id": plugin_id, "action": "update", "confirmed": True},
        ),
    ]


def _provider_operations(manifest: PluginManifest) -> list[dict[str, Any]]:
    if manifest.provider != "cli-anything" and manifest.plugin_id != "cli-anything":
        return []
    plugin_id = manifest.plugin_id
    return [
        _operation(
            "status",
            "CLI-Hub Status",
            "report",
            f"python -m cbn plugin status {plugin_id}",
            api={"method": "GET", "path": f"/plugins/{plugin_id}/status"},
        ),
        _operation(
            "market-list",
            "Market List",
            "report",
            f"python -m cbn plugin market {plugin_id} list",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/market"},
            payload_template={"command": "list"},
        ),
        _operation(
            "candidates",
            "Rank Candidates",
            "report",
            f"python -m cbn plugin candidates {plugin_id} --query file --limit 20 --compact",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/candidates"},
            payload_template={"query": "file", "limit": 20, "compact": True},
            input_schema={"query": "string", "limit": "integer", "compact": "boolean"},
        ),
        _operation(
            "install-queue",
            "Install Queue",
            "gate",
            f"python -m cbn plugin install-queue {plugin_id} --query file --limit 20 --max-installs 5",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/install-queue"},
            payload_template={"query": "file", "limit": 20, "max_installs": 5, "include_blocked": True},
        ),
        _operation(
            "blocked-plan",
            "Blocked Plan",
            "gate",
            f"python -m cbn plugin blocked-plan {plugin_id} --query file --limit 20",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/blocked-plan"},
            payload_template={"query": "file", "limit": 20},
        ),
        _operation(
            "repair-plan",
            "Repair Plan",
            "report",
            f"python -m cbn plugin repair-plan {plugin_id} <harness>",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/repair-plan"},
            payload_template={"harness_name": "<harness>", "from_market": True},
        ),
        _operation(
            "adapter-targets",
            "Adapter Targets",
            "report",
            f"python -m cbn plugin adapter-targets {plugin_id} <harness> --from-market",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/adapter-targets"},
            payload_template={"harness_name": "<harness>", "from_market": True, "limit": 20},
        ),
        _operation(
            "adapter-smoke",
            "Adapter Smoke",
            "execute",
            f"python -m cbn plugin adapter-smoke {plugin_id} <harness> --module <module> --run --yes",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/adapter-smoke"},
            requires_confirmation=True,
            side_effects=("subprocess", "runtime/artifacts"),
            payload_template={
                "harness_name": "<harness>",
                "module": "<module>",
                "run": True,
                "confirmed": True,
                "smoke_args": ["--help"],
            },
        ),
        _operation(
            "repair-entrypoint",
            "Repair Entrypoint",
            "write",
            f"python -m cbn plugin repair-entrypoint {plugin_id} <harness> --module <module> --write --yes",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/repair-entrypoint"},
            requires_confirmation=True,
            side_effects=("external_plugins/entrypoints", "runtime/manifests", "audit", "events"),
            payload_template={
                "harness_name": "<harness>",
                "module": "<module>",
                "write": True,
                "confirmed": True,
                "smoke_args": ["--help"],
            },
        ),
        _operation(
            "adaptation-gate",
            "Adaptation Gate",
            "gate",
            f"python -m cbn plugin adaptation-gate {plugin_id} <harness> --from-market",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/adaptation-gate"},
            payload_template={"harness_name": "<harness>", "from_market": True, "require_smoke": True},
        ),
        _operation(
            "adaptation-queue",
            "Adaptation Queue",
            "gate",
            f"python -m cbn plugin adaptation-queue {plugin_id} --query file --max-harnesses 5",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/adaptation-queue"},
            payload_template={"query": "file", "limit": 20, "max_harnesses": 5, "include_blocked": True},
        ),
        _operation(
            "promotion-gate",
            "Promotion Gate",
            "gate",
            f"python -m cbn plugin promotion-gate {plugin_id} <harness> --from-market",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/promotion-gate"},
            payload_template={"harness_name": "<harness>", "from_market": True},
        ),
        _operation(
            "live-verification",
            "Live Verification",
            "report",
            f"python -m cbn plugin live-verification {plugin_id}",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/live-verification"},
            payload_template={"harnesses": ["mermaid", "macrocli"], "candidate_query": "file"},
        ),
        _operation(
            "mvp-plan",
            "MVP Plan",
            "report",
            f"python -m cbn plugin mvp-plan {plugin_id} --query file --limit 20 --max-harnesses 5",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/mvp-plan"},
            payload_template={"query": "file", "limit": 20, "max_harnesses": 5, "include_blocked": True},
        ),
        _operation(
            "bootstrap-plan",
            "Bootstrap Plan",
            "plan",
            f"python -m cbn plugin bootstrap-plan {plugin_id} --harness mermaid --query file",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/bootstrap-plan"},
            payload_template={"harness_name": "mermaid", "query": "file", "include_workflows": True},
        ),
        _operation(
            "harness-verify-plan",
            "Harness Post-Operation Verification",
            "report",
            f"python -m cbn plugin verify-harness-plan {plugin_id} install <harness>",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/verify-harness-plan"},
            payload_template={"action": "install", "harness_name": "<harness>", "run": False},
            input_schema={"harness": "string", "action": "string", "run": "boolean"},
        ),
        _operation(
            "harness-install",
            "Harness Install",
            "execute",
            f"python -m cbn plugin harness {plugin_id} install <harness> --yes",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/harness"},
            requires_confirmation=True,
            side_effects=("subprocess", "pip", "cli-hub"),
            payload_template={"action": "install", "harness_name": "<harness>", "confirmed": True},
        ),
    ]


def _operation(
    operation_id: str,
    title: str,
    kind: str,
    command: str,
    api: dict[str, str] | None = None,
    requires_confirmation: bool = False,
    side_effects: tuple[str, ...] = (),
    input_schema: dict[str, Any] | None = None,
    payload_template: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _enrich_operation_descriptor({
        "id": operation_id,
        "title": title,
        "kind": kind,
        "command": command,
        "api": api,
        "requires_confirmation": requires_confirmation,
        "side_effects": list(side_effects),
        "input_schema": input_schema or {},
        "payload_template": payload_template or {},
    })


def _dedupe_operations(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for operation in operations:
        operation_id = str(operation.get("id", ""))
        if not operation_id or operation_id in seen:
            continue
        selected.append(operation)
        seen.add(operation_id)
    return selected


def _enrich_operations(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_enrich_operation_descriptor(operation) for operation in operations]


def _enrich_operation_descriptor(operation: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(operation)
    command = enriched.get("command", "")
    payload = enriched.get("payload_template", {})
    required_inputs = sorted(_required_inputs_for_templates(command, payload))
    input_schema = enriched.get("input_schema", {})
    if input_schema is None:
        input_schema = {}
    if isinstance(input_schema, dict):
        input_schema = dict(input_schema)
        for name in required_inputs:
            input_schema.setdefault(name, "string")
    enriched["required_inputs"] = required_inputs
    enriched["input_schema"] = input_schema
    enriched["input_count"] = len(required_inputs)
    enriched["has_required_inputs"] = bool(required_inputs)
    return enriched


def _required_inputs_for_templates(command: Any, payload: Any) -> set[str]:
    inputs: set[str] = set()
    if isinstance(command, str):
        inputs.update(_PLACEHOLDER_RE.findall(command))
    _collect_placeholders(payload, inputs)
    return inputs


def _collect_placeholders(value: Any, inputs: set[str]) -> None:
    if isinstance(value, str):
        inputs.update(_PLACEHOLDER_RE.findall(value))
    elif isinstance(value, list):
        for item in value:
            _collect_placeholders(item, inputs)
    elif isinstance(value, dict):
        for item in value.values():
            _collect_placeholders(item, inputs)


_OPERATION_KINDS = {"report", "gate", "plan", "execute", "write"}


def _validate_operation_catalog(manifest: PluginManifest, operations: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if manifest.plugin_api_version != "cbn.plugin.v1":
        errors.append(f"unsupported plugin_api_version: {manifest.plugin_api_version}")
    if not manifest.provider:
        errors.append("provider is required")
    seen: set[str] = set()
    for index, operation in enumerate(operations):
        prefix = f"operations[{index}]"
        operation_id = operation.get("id")
        if not isinstance(operation_id, str) or not operation_id:
            errors.append(f"{prefix}.id is required")
            operation_id = f"<missing:{index}>"
        elif operation_id in seen:
            errors.append(f"duplicate operation id: {operation_id}")
        seen.add(str(operation_id))
        kind = operation.get("kind")
        if kind not in _OPERATION_KINDS:
            errors.append(f"{prefix}.kind is invalid: {kind}")
        required_inputs = operation.get("required_inputs", [])
        input_schema = operation.get("input_schema", {})
        if not isinstance(required_inputs, list) or not all(isinstance(item, str) for item in required_inputs):
            errors.append(f"{prefix}.required_inputs must be a list of strings")
            required_inputs = []
        if not isinstance(input_schema, dict):
            errors.append(f"{prefix}.input_schema must be an object")
            input_schema = {}
        for name in required_inputs:
            if name not in input_schema:
                errors.append(f"{prefix}.input_schema is missing required input: {name}")
        command = operation.get("command")
        api = operation.get("api")
        if not isinstance(command, str) or not command:
            errors.append(f"{prefix}.command is required")
        if api is not None:
            _validate_operation_api(prefix, api, kind, errors)
        elif kind in {"execute", "write"}:
            warnings.append(f"{prefix}.api is missing for side-effecting operation {operation_id}")
        side_effects = operation.get("side_effects", [])
        if kind in {"execute", "write"}:
            if operation.get("requires_confirmation") is not True:
                errors.append(f"{prefix}.requires_confirmation must be true for {kind}")
            if not isinstance(side_effects, list) or not side_effects:
                errors.append(f"{prefix}.side_effects must be non-empty for {kind}")
            payload = operation.get("payload_template", {})
            if isinstance(payload, dict) and payload.get("confirmed") is False:
                errors.append(f"{prefix}.payload_template.confirmed cannot be false for {kind}")
        elif operation.get("requires_confirmation"):
            warnings.append(f"{prefix}.requires_confirmation is true for non-side-effect kind {kind}")
        if not isinstance(operation.get("payload_template", {}), dict):
            errors.append(f"{prefix}.payload_template must be an object")
    return {
        "ok": not errors,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }


def _validate_operation_api(prefix: str, api: Any, kind: Any, errors: list[str]) -> None:
    if not isinstance(api, dict):
        errors.append(f"{prefix}.api must be an object when present")
        return
    method = api.get("method")
    path = api.get("path")
    if method not in {"GET", "POST"}:
        errors.append(f"{prefix}.api.method must be GET or POST")
    if not isinstance(path, str) or not path.startswith("/"):
        errors.append(f"{prefix}.api.path must start with /")
    if kind in {"execute", "write"} and method != "POST":
        errors.append(f"{prefix}.api.method must be POST for {kind}")


_PLACEHOLDER_RE = re.compile(r"<([A-Za-z_][A-Za-z0-9_]*)>")
