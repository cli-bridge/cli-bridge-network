"""Network acceptance checklist and live request evaluation helpers."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from cbn_demo.network_specs import (
    NETWORK_ACCEPTANCE_CHECK_SPECS,
    NETWORK_ACCEPTANCE_FAILURE_RECOVERY,
    NETWORK_ACCEPTANCE_SUCCESS_SIGNALS,
)


def network_connection_acceptance(*, workflow_path: str, requests: list[dict[str, Any]]) -> dict[str, Any]:
    request_ids = [str(request.get("id", "")) for request in requests if request.get("id")]
    checks = [
        {
            "id": check_id,
            "request_id": request_id,
            "proves": proves,
            "expect": expect,
        }
        for check_id, request_id, proves, expect in NETWORK_ACCEPTANCE_CHECK_SPECS
    ]
    return {
        "kind": "NetworkConnectionAcceptance",
        "status": "ready",
        "workflow_path": workflow_path,
        "required_request_ids": request_ids,
        "check_count": len(checks),
        "checks": checks,
        "success_signals": list(NETWORK_ACCEPTANCE_SUCCESS_SIGNALS),
        "failure_recovery": list(NETWORK_ACCEPTANCE_FAILURE_RECOVERY),
    }


def run_acceptance_check(
    check: dict[str, Any],
    requests_by_id: dict[str, dict[str, Any]],
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    check_id = str(check.get("id") or check.get("request_id") or "acceptance_check")
    request_id = str(check.get("request_id") or "")
    request = requests_by_id.get(request_id)
    if request is None:
        return acceptance_check_result(check, check_id, request_id or "unknown", "skipped", error="matching quickstart request not found")
    response = _execute_quickstart_request(request, timeout_seconds=timeout_seconds)
    if response.get("error"):
        return acceptance_check_result(
            check,
            check_id,
            request_id,
            "failed",
            http_status=response.get("http_status", 0),
            error=response.get("error"),
        )
    evaluation = _evaluate_acceptance_expectation(
        check.get("expect", {}) if isinstance(check.get("expect"), dict) else {},
        response.get("payload"),
        int(response.get("http_status", 0)),
    )
    status = "passed" if evaluation["passed"] else "failed"
    return acceptance_check_result(
        check,
        check_id,
        request_id,
        status,
        http_status=response.get("http_status", 0),
        evidence=evaluation["evidence"],
        error=evaluation.get("error"),
    )


def acceptance_check_result(
    check: dict[str, Any],
    check_id: str,
    request_id: str,
    status: str,
    *,
    http_status: Any = None,
    evidence: Any = None,
    error: Any = None,
) -> dict[str, Any]:
    result = {
        "check_id": check_id,
        "request_id": request_id,
        "status": status,
        "proves": check.get("proves"),
        "expect": check.get("expect", {}),
        "error": error,
    }
    if http_status is not None:
        result["http_status"] = http_status
    if evidence is not None:
        result["evidence"] = evidence
    return {
        key: value
        for key, value in result.items()
        if value is not None or key == "error"
    }


def _execute_quickstart_request(request: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
    method = str(request.get("method") or "GET")
    url = str(request.get("url") or "")
    headers = _quickstart_headers(request)
    data = _quickstart_json_body(request)
    if data is not None:
        headers["Content-Type"] = "application/json"
    try:
        http_request = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(http_request, timeout=timeout_seconds) as response:
            return _http_payload_response(response.status, response.read())
    except urllib.error.HTTPError as exc:
        return _http_payload_response(exc.code, exc.read())
    except urllib.error.URLError as exc:
        return {
            "http_status": 0,
            "payload": None,
            "error": str(exc.reason),
        }
    except TimeoutError as exc:
        return {
            "http_status": 0,
            "payload": None,
            "error": str(exc),
        }


def _quickstart_headers(request: dict[str, Any]) -> dict[str, str]:
    raw_headers = request.get("headers") if isinstance(request.get("headers"), dict) else {}
    return {str(key): str(value) for key, value in raw_headers.items()}


def _quickstart_json_body(request: dict[str, Any]) -> bytes | None:
    payload = request.get("json")
    if not isinstance(payload, dict):
        return None
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _http_payload_response(status: int, body: bytes) -> dict[str, Any]:
    return {
        "http_status": status,
        "payload": _decode_json_body(body),
    }


def _decode_json_body(body: bytes) -> Any:
    if not body:
        return None
    text = body.decode("utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def _evaluate_acceptance_expectation(
    expect: dict[str, Any],
    payload: Any,
    http_status: int,
) -> dict[str, Any]:
    evidence = {}
    failures = []
    for key, expected in expect.items():
        actual = _acceptance_actual_value(str(key), payload, http_status)
        ok = _acceptance_value_matches(str(key), actual, expected)
        evidence[str(key)] = {"expected": expected, "actual": actual, "ok": ok}
        if not ok:
            failures.append(f"{key} expected {expected!r} but got {actual!r}")
    return {
        "passed": not failures,
        "evidence": evidence,
        "error": "; ".join(failures) if failures else None,
    }


def _acceptance_actual_value(key: str, payload: Any, http_status: int) -> Any:
    if key == "http_status":
        return http_status
    if not key.startswith("json."):
        return None
    json_key = key.removeprefix("json.")
    if json_key == "type":
        return _json_type_name(payload)
    if json_key in {"count_min", "length_min"}:
        return len(payload) if isinstance(payload, (list, dict, str)) else None
    if json_key.endswith("_count_min"):
        value = _json_path(payload, json_key.removesuffix("_count_min"))
        if isinstance(value, (list, dict, str)):
            return len(value)
    if json_key.endswith("_min"):
        return _json_path(payload, json_key.removesuffix("_min"))
    if json_key.endswith("_type"):
        return _json_type_name(_json_path(payload, json_key.removesuffix("_type")))
    return _json_path(payload, json_key)


def _acceptance_value_matches(key: str, actual: Any, expected: Any) -> bool:
    if key.endswith("_min") and isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return actual >= expected
    return actual == expected


def _json_path(payload: Any, path: str) -> Any:
    current = payload
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _json_type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if value is None:
        return "null"
    return type(value).__name__
