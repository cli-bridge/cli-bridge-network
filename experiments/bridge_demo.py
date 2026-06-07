#!/usr/bin/env python3
"""Universal CLI Bridge feasibility experiments.

This is intentionally a compact prototype rather than production code. It
validates the research report's core claims with local command execution,
manifest discovery, a minimal gateway, policy checks, parser output, and
replayable logs.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import http.server
import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
import wave
import math
import struct
from pathlib import Path
from statistics import mean, median
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "report"
LOGS = REPORT / "logs"
ARTIFACTS = REPORT / "artifacts"
AUDIT_LOG = LOGS / "audit.jsonl"


@dataclasses.dataclass(frozen=True)
class ToolSpec:
    tool_id: str
    command: list[str]
    help_command: list[str]
    mode: str
    risk: str
    parser: str | None = None
    timeout_s: float = 10.0


TOOLS: dict[str, ToolSpec] = {
    "git.version": ToolSpec("git.version", ["git", "--version"], ["git", "--help"], "read", "read"),
    "git.status": ToolSpec("git.status", ["git", "status", "--short"], ["git", "status", "-h"], "read", "read"),
    "node.version": ToolSpec("node.version", ["node", "--version"], ["node", "--help"], "read", "read"),
    "npm.version": ToolSpec("npm.version", ["npm", "--version"], ["npm", "help"], "read", "read"),
    "gh.version": ToolSpec("gh.version", ["gh", "--version"], ["gh", "--help"], "read", "read"),
    "ffprobe.inspect": ToolSpec(
        "ffprobe.inspect",
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json"],
        ["ffprobe", "-help"],
        "read",
        "read",
        parser="ffprobe.json",
    ),
    "bridge.danger.delete": ToolSpec(
        "bridge.danger.delete",
        ["python", "-c", "import shutil,sys; shutil.rmtree(sys.argv[1])"],
        ["python", "--help"],
        "write",
        "privileged",
    ),
    "bridge.network.fetch": ToolSpec(
        "bridge.network.fetch",
        ["python", "-c", "import urllib.request; print(urllib.request.urlopen('https://example.com', timeout=3).status)"],
        ["python", "--help"],
        "network",
        "external-network",
    ),
}


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def ensure_dirs() -> None:
    REPORT.mkdir(exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)


def append_audit(event: dict[str, Any]) -> None:
    event = {"ts": now_iso(), **event}
    with AUDIT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def run_cmd(
    args: list[str],
    cwd: Path | None = None,
    timeout_s: float = 10.0,
    extra_args: list[str] | None = None,
) -> dict[str, Any]:
    full = [*args, *(extra_args or [])]
    if full:
        resolved = shutil.which(full[0])
        if resolved:
            full = [resolved, *full[1:]]
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            full,
            cwd=str(cwd or ROOT),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_s,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        return {
            "command": full,
            "cwd": str(cwd or ROOT),
            "exit_code": proc.returncode,
            "elapsed_ms": round(elapsed_ms, 3),
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "timed_out": False,
        }
    except FileNotFoundError as exc:
        return {
            "command": full,
            "cwd": str(cwd or ROOT),
            "exit_code": 127,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "stdout": "",
            "stderr": str(exc),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": full,
            "cwd": str(cwd or ROOT),
            "exit_code": 124,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "timed_out": True,
        }


def summarize_text(text: str, limit: int = 240) -> str:
    compact = " ".join(text.replace("\r", "\n").split())
    return compact[:limit]


def parse_help_flags(text: str) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    seen: set[str] = set()
    pattern = re.compile(r"(?P<flag>(?:--?[A-Za-z0-9][A-Za-z0-9][\w-]*)(?:[ =][A-Z_][A-Z0-9_-]*)?)")
    for line in text.splitlines():
        if "-" not in line:
            continue
        matches = pattern.findall(line)
        if not matches:
            continue
        desc = re.sub(r"\s+", " ", line.strip())
        for flag in matches[:3]:
            key = flag.split()[0].split("=")[0]
            if key not in seen and key.startswith("-"):
                seen.add(key)
                flags.append({"name": key, "evidence": desc[:180]})
        if len(flags) >= 30:
            break
    return flags


def discover_tool(spec: ToolSpec) -> dict[str, Any]:
    available = shutil.which(spec.command[0]) is not None
    version = run_cmd(spec.command[:2] if len(spec.command) > 1 else spec.command, timeout_s=spec.timeout_s)
    help_result = run_cmd(spec.help_command, timeout_s=spec.timeout_s)
    help_text = f"{help_result['stdout']}\n{help_result['stderr']}"
    flags = parse_help_flags(help_text)
    confidence = 0.15
    sources: list[dict[str, Any]] = []
    if available:
        confidence += 0.25
    if version["exit_code"] == 0:
        confidence += 0.2
        sources.append({"kind": "version", "command": version["command"], "summary": summarize_text(version["stdout"] or version["stderr"])})
    if help_result["exit_code"] in (0, 1) and help_text.strip():
        confidence += 0.25
        sources.append({"kind": "help", "command": help_result["command"], "flags_found": len(flags)})
    if spec.parser:
        confidence += 0.1
    return {
        "apiVersion": "bridge.dev/v1alpha1",
        "kind": "ToolManifest",
        "metadata": {
            "id": spec.tool_id,
            "provenance": {
                "tool": spec.command[0],
                "sources": sources,
                "confidence": round(min(confidence, 0.98), 2),
            },
        },
        "spec": {
            "transport": {
                "kind": "stdio",
                "command": spec.command[0],
                "argsTemplate": spec.command[1:],
                "cwdPolicy": "workspace",
            },
            "execution": {
                "mode": spec.mode,
                "timeoutMs": int(spec.timeout_s * 1000),
                "pty": False,
            },
            "inputSchema": {
                "type": "object",
                "discoveredFlags": flags,
            },
            "output": {
                "parserRef": spec.parser,
                "verified": spec.parser is not None or spec.tool_id in {"git.version", "git.status"},
            },
            "policy": {
                "risk": spec.risk,
                "requiresConfirmation": spec.risk in {"privileged", "external-network"},
                "network": "deny" if spec.risk != "external-network" else "requires-confirmation",
            },
            "export": {
                "mcp": {"enabled": True, "toolName": spec.tool_id.replace(".", "_")},
                "rest": {"enabled": True, "method": "POST", "path": f"/tools/{spec.tool_id}/call"},
                "cli": {"enabled": True, "subcommand": spec.tool_id.replace(".", "-")},
            },
        },
    }


def discover_all() -> dict[str, Any]:
    manifests = [discover_tool(spec) for spec in TOOLS.values()]
    result = {
        "generated_at": now_iso(),
        "workspace": str(ROOT),
        "tools": manifests,
        "summary": {
            "tool_count": len(manifests),
            "available_count": sum(1 for m in manifests if m["metadata"]["provenance"]["confidence"] >= 0.4),
            "high_risk_count": sum(1 for m in manifests if m["spec"]["policy"]["requiresConfirmation"]),
        },
    }
    write_json(REPORT / "discovery_manifest.json", result)
    return result


def prepare_sample_repo() -> Path:
    sample = ARTIFACTS / "sample_repo"
    sample.mkdir(parents=True, exist_ok=True)
    if not (sample / ".git").exists():
        run_cmd(["git", "init"], cwd=sample)
    tracked = sample / "tracked.txt"
    tracked.write_text("baseline\n", encoding="utf-8")
    run_cmd(["git", "add", "tracked.txt"], cwd=sample)
    run_cmd(["git", "commit", "-m", "baseline"], cwd=sample, timeout_s=10)
    (sample / "untracked.txt").write_text("worktree change\n", encoding="utf-8")
    tracked.write_text("baseline\nmodified\n", encoding="utf-8")
    return sample


def write_sample_wav(path: Path, seconds: float = 0.25, rate: int = 8000) -> None:
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        for i in range(frames):
            value = int(16000 * math.sin(2 * math.pi * 440 * i / rate))
            f.writeframes(struct.pack("<h", value))


def policy_allows(spec: ToolSpec, confirm: bool) -> tuple[bool, str]:
    if spec.risk in {"privileged", "external-network"} and not confirm:
        return False, f"risk={spec.risk} requires explicit confirmation"
    return True, "allowed"


def call_tool(tool_id: str, cwd: Path | None = None, extra_args: list[str] | None = None, confirm: bool = False) -> dict[str, Any]:
    spec = TOOLS[tool_id]
    allowed, reason = policy_allows(spec, confirm=confirm)
    call_id = str(uuid.uuid4())
    if not allowed:
        result = {
            "call_id": call_id,
            "tool_id": tool_id,
            "allowed": False,
            "reason": reason,
            "exit_code": None,
            "elapsed_ms": 0,
        }
        append_audit(result)
        return result
    command = spec.command
    if tool_id == "ffprobe.inspect" and extra_args:
        command = [*spec.command, *extra_args]
    raw = run_cmd(command, cwd=cwd, timeout_s=spec.timeout_s)
    parsed: dict[str, Any] | None = None
    if spec.parser == "ffprobe.json" and raw["exit_code"] == 0:
        parsed_json = json.loads(raw["stdout"])
        parsed = {
            "format_name": parsed_json.get("format", {}).get("format_name"),
            "duration": parsed_json.get("format", {}).get("duration"),
            "stream_count": len(parsed_json.get("streams", [])),
            "codec_types": sorted({s.get("codec_type", "unknown") for s in parsed_json.get("streams", [])}),
        }
    result = {
        "call_id": call_id,
        "tool_id": tool_id,
        "allowed": True,
        "reason": reason,
        "exit_code": raw["exit_code"],
        "elapsed_ms": raw["elapsed_ms"],
        "stdout_summary": summarize_text(raw["stdout"]),
        "stderr_summary": summarize_text(raw["stderr"]),
        "parsed": parsed,
    }
    append_audit(result)
    return result


class BridgeGateway(http.server.ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], handler_class: type[http.server.BaseHTTPRequestHandler], sample_repo: Path, sample_audio: Path):
        super().__init__(server_address, handler_class)
        self.sample_repo = sample_repo
        self.sample_audio = sample_audio


class BridgeHandler(http.server.BaseHTTPRequestHandler):
    server: BridgeGateway

    def log_message(self, fmt: str, *args: Any) -> None:
        append_audit({"event": "http_log", "message": fmt % args})

    def _send(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/tools":
            self._send(200, {"tools": sorted(TOOLS)})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        if self.path != "/call":
            self._send(404, {"error": "not found"})
            return
        tool_id = payload.get("tool_id")
        if tool_id not in TOOLS:
            self._send(400, {"error": "unknown tool"})
            return
        cwd = self.server.sample_repo if tool_id == "git.status" else ROOT
        extra_args = [str(self.server.sample_audio)] if tool_id == "ffprobe.inspect" else None
        result = call_tool(tool_id, cwd=cwd, extra_args=extra_args, confirm=bool(payload.get("confirm")))
        self._send(200 if result["allowed"] else 403, result)


def free_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextlib.contextmanager
def gateway(sample_repo: Path, sample_audio: Path):
    port = free_port()
    server = BridgeGateway(("127.0.0.1", port), BridgeHandler, sample_repo, sample_audio)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=3)


def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"runs": 0, "mean_ms": 0, "p50_ms": 0, "p95_ms": 0}
    ordered = sorted(values)
    p95_idx = min(len(ordered) - 1, int(len(ordered) * 0.95))
    return {
        "runs": len(values),
        "mean_ms": round(mean(values), 3),
        "p50_ms": round(median(values), 3),
        "p95_ms": round(ordered[p95_idx], 3),
        "min_ms": round(ordered[0], 3),
        "max_ms": round(ordered[-1], 3),
    }


def bench_stdio(sample_repo: Path, runs: int) -> dict[str, Any]:
    timings: dict[str, list[float]] = {"git.version": [], "git.status": []}
    for _ in range(runs):
        timings["git.version"].append(call_tool("git.version")["elapsed_ms"])
        timings["git.status"].append(call_tool("git.status", cwd=sample_repo)["elapsed_ms"])
    return {tool_id: stats(values) for tool_id, values in timings.items()}


def bench_gateway(sample_repo: Path, sample_audio: Path, runs: int, concurrency: int) -> dict[str, Any]:
    timings: list[float] = []
    failures: list[str] = []
    work: queue.Queue[int] = queue.Queue()
    for i in range(runs):
        work.put(i)

    with gateway(sample_repo, sample_audio) as base:
        def worker() -> None:
            while True:
                try:
                    work.get_nowait()
                except queue.Empty:
                    return
                started = time.perf_counter()
                try:
                    post_json(f"{base}/call", {"tool_id": "git.version"})
                    timings.append((time.perf_counter() - started) * 1000)
                except Exception as exc:  # pragma: no cover - captured in report
                    failures.append(str(exc))
                finally:
                    work.task_done()

        threads = [threading.Thread(target=worker) for _ in range(concurrency)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    return {"git.version": stats(timings), "failures": failures[:10], "failure_count": len(failures), "concurrency": concurrency}


def run_security_tests(sample_repo: Path, sample_audio: Path) -> dict[str, Any]:
    cases = [
        call_tool("bridge.danger.delete", extra_args=[str(ARTIFACTS / "never_delete")], confirm=False),
        call_tool("bridge.network.fetch", confirm=False),
    ]
    with gateway(sample_repo, sample_audio) as base:
        try:
            post_json(f"{base}/call", {"tool_id": "bridge.network.fetch"})
            gateway_denied = False
        except urllib.error.HTTPError as exc:
            gateway_denied = exc.code == 403
    return {
        "cases": cases,
        "gateway_external_network_without_confirmation_denied": gateway_denied,
        "blocked_count": sum(1 for c in cases if not c["allowed"]) + int(gateway_denied),
        "total_cases": len(cases) + 1,
    }


def run_parser_tests(sample_audio: Path) -> dict[str, Any]:
    return {
        "ffprobe": call_tool("ffprobe.inspect", extra_args=[str(sample_audio)]),
        "sample_audio": str(sample_audio),
        "sample_audio_size_bytes": sample_audio.stat().st_size,
    }


def toolchain_probe() -> dict[str, Any]:
    commands = {
        "python": ["python", "--version"],
        "node": ["node", "--version"],
        "npm": ["npm", "--version"],
        "git": ["git", "--version"],
        "gh": ["gh", "--version"],
        "ffmpeg": ["ffmpeg", "-version"],
        "ffprobe": ["ffprobe", "-version"],
        "docker": ["docker", "--version"],
        "docker_daemon": ["docker", "info", "--format", "{{json .ServerVersion}}"],
        "rustc": ["rustc", "--version"],
        "cargo": ["cargo", "--version"],
    }
    result: dict[str, Any] = {}
    for name, cmd in commands.items():
        raw = run_cmd(cmd, timeout_s=10)
        summary_source = raw["stdout"] if raw["exit_code"] == 0 else f"{raw['stdout']} {raw['stderr']}"
        result[name] = {
            "available": raw["exit_code"] == 0,
            "exit_code": raw["exit_code"],
            "elapsed_ms": raw["elapsed_ms"],
            "summary": summarize_text(summary_source, limit=300),
        }
    write_json(REPORT / "toolchain_probe.json", result)
    return result


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_all(runs: int, gateway_runs: int, concurrency: int) -> dict[str, Any]:
    ensure_dirs()
    if AUDIT_LOG.exists():
        AUDIT_LOG.unlink()

    sample_repo = prepare_sample_repo()
    sample_audio = ARTIFACTS / "sample.wav"
    write_sample_wav(sample_audio)

    results = {
        "generated_at": now_iso(),
        "workspace": str(ROOT),
        "claim_batches": [
            "discovery_to_manifest_ir",
            "controlled_stdio_execution_and_audit",
            "single_gateway_export",
            "policy_denial_for_high_risk_calls",
            "parser_registry_for_structured_outputs",
        ],
        "toolchain": toolchain_probe(),
        "discovery": discover_all()["summary"],
        "benchmarks": {
            "stdio_subprocess": bench_stdio(sample_repo, runs=runs),
            "hybrid_http_gateway": bench_gateway(sample_repo, sample_audio, runs=gateway_runs, concurrency=concurrency),
        },
        "security": run_security_tests(sample_repo, sample_audio),
        "parser": run_parser_tests(sample_audio),
        "artifacts": {
            "discovery_manifest": str(REPORT / "discovery_manifest.json"),
            "toolchain_probe": str(REPORT / "toolchain_probe.json"),
            "audit_log": str(AUDIT_LOG),
            "sample_repo": str(sample_repo),
            "sample_audio": str(sample_audio),
        },
    }
    write_json(REPORT / "experiment_results.json", results)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Universal CLI Bridge feasibility experiments.")
    parser.add_argument("--runs", type=int, default=30, help="stdio benchmark runs")
    parser.add_argument("--gateway-runs", type=int, default=50, help="gateway benchmark runs")
    parser.add_argument("--concurrency", type=int, default=10, help="gateway benchmark concurrency")
    args = parser.parse_args()
    results = run_all(runs=args.runs, gateway_runs=args.gateway_runs, concurrency=args.concurrency)
    print(json.dumps(results["benchmarks"], ensure_ascii=False, indent=2))
    print(f"Wrote {REPORT / 'experiment_results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
