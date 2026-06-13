"""PTY subprocess adapter for interactive CLI harnesses.

The adapter uses stdlib PTY support on POSIX and an optional pywinpty backend on
Windows. Missing optional backends are reported as structured runtime failures
instead of silently falling back to stdio.
"""

from __future__ import annotations

import importlib.util
import os
import queue
import subprocess
import sys
import threading
import time
from typing import Any

from adapters.base import ToolCall, ToolResult


class PtyAdapter:
    def call(self, request: ToolCall) -> ToolResult:
        if request.dry_run:
            return ToolResult(
                capability_id=request.capability_id,
                allowed=True,
                exit_code=0,
                stdout=" ".join(request.argv),
                reason="dry-run",
            )
        if os.name == "nt":
            if importlib.util.find_spec("winpty") is None:
                return ToolResult(
                    capability_id=request.capability_id,
                    allowed=True,
                    exit_code=127,
                    stderr="PTY transport requires optional dependency: pywinpty",
                    reason="pty-dependency-missing",
                )
            return self._call_windows_winpty(request)
        return self._call_posix_pty(request)

    def _call_windows_winpty(self, request: ToolCall) -> ToolResult:
        try:
            from winpty import PtyProcess  # type: ignore[import-not-found]
        except Exception as exc:
            return _winpty_import_failed_result(request, exc)

        return _run_windows_winpty(request, PtyProcess)

    def _call_posix_pty(self, request: ToolCall) -> ToolResult:
        import pty
        import select

        master_fd, slave_fd = pty.openpty()
        output_parts: list[str] = []
        proc = None
        try:
            proc = _spawn_posix_pty_process(request, slave_fd)
            os.close(slave_fd)
            slave_fd = -1
            return _wait_for_posix_pty(request, proc, master_fd, output_parts, select)
        except OSError as exc:
            return _spawn_failed_result(request, exc)
        finally:
            _close_posix_pty(master_fd, slave_fd, proc)


def _run_windows_winpty(request: ToolCall, pty_process: Any) -> ToolResult:
    env = _merged_env(request.env)
    started = time.monotonic()
    output_parts: list[str] = []
    output_queue: queue.Queue[str] = queue.Queue()
    stop_reader = threading.Event()
    proc = None
    try:
        proc = pty_process.spawn(
            list(request.argv),
            cwd=request.cwd,
            env=env,
            dimensions=(120, 40),
        )
        reader = _start_winpty_reader(proc, output_queue, stop_reader)
        return _wait_for_winpty(request, proc, reader, started, output_queue, output_parts, stop_reader)
    except OSError as exc:
        return _spawn_failed_result(request, exc)
    finally:
        _close_winpty(proc, stop_reader)


def pty_backend_status() -> dict[str, object]:
    if os.name == "nt":
        return {
            "kind": "pty",
            "platform": sys.platform,
            "backend": "pywinpty",
            "available": importlib.util.find_spec("winpty") is not None,
            "install_hint": "pip install cli-bridge-network[pty]",
        }
    return {
        "kind": "pty",
        "platform": sys.platform,
        "backend": "stdlib-pty",
        "available": True,
        "install_hint": None,
    }


def _merged_env(extra: dict[str, str] | None) -> dict[str, str]:
    env = os.environ.copy()
    if extra:
        env.update(extra)
    return env


def _timeout_result(request: ToolCall, output_parts: list[str]) -> ToolResult:
    return ToolResult(
        capability_id=request.capability_id,
        allowed=True,
        exit_code=124,
        stdout="".join(output_parts),
        stderr=f"command timed out after {request.timeout_seconds} seconds",
        reason="timeout",
    )


def _allowed_result(request: ToolCall, exit_code: int | None, output_parts: list[str]) -> ToolResult:
    return ToolResult(
        capability_id=request.capability_id,
        allowed=True,
        exit_code=int(exit_code or 0),
        stdout="".join(output_parts),
        reason="allowed",
    )


def _spawn_failed_result(request: ToolCall, exc: OSError) -> ToolResult:
    return ToolResult(
        capability_id=request.capability_id,
        allowed=True,
        exit_code=127,
        stderr=f"{request.argv[0]} failed to start in PTY: {exc}",
        reason="spawn-failed",
    )


def _winpty_import_failed_result(request: ToolCall, exc: Exception) -> ToolResult:
    return ToolResult(
        capability_id=request.capability_id,
        allowed=True,
        exit_code=127,
        stderr=f"PTY transport failed to import pywinpty: {exc}",
        reason="pty-dependency-missing",
    )


def _start_winpty_reader(
    proc: object,
    output_queue: queue.Queue[str],
    stop_reader: threading.Event,
) -> threading.Thread:
    reader = threading.Thread(
        target=_read_winpty_output,
        args=(proc, output_queue, stop_reader),
        daemon=True,
    )
    reader.start()
    return reader


def _wait_for_winpty(
    request: ToolCall,
    proc: object,
    reader: threading.Thread,
    started: float,
    output_queue: queue.Queue[str],
    output_parts: list[str],
    stop_reader: threading.Event,
) -> ToolResult:
    while proc.isalive():  # type: ignore[attr-defined]
        _drain_queue(output_queue, output_parts)
        if time.monotonic() - started > request.timeout_seconds:
            proc.kill()  # type: ignore[attr-defined]
            _finish_winpty_reader(reader, output_queue, output_parts, stop_reader)
            return _timeout_result(request, output_parts)
        time.sleep(0.02)
    _finish_winpty_reader(reader, output_queue, output_parts, stop_reader)
    return _allowed_result(request, _winpty_exit_code(proc), output_parts)


def _finish_winpty_reader(
    reader: threading.Thread,
    output_queue: queue.Queue[str],
    output_parts: list[str],
    stop_reader: threading.Event,
) -> None:
    stop_reader.set()
    reader.join(timeout=1)
    _drain_queue(output_queue, output_parts)


def _winpty_exit_code(proc: object) -> int:
    exit_code = getattr(proc, "exitstatus", None)
    return int(exit_code if exit_code is not None else 0)


def _close_winpty(proc: object | None, stop_reader: threading.Event) -> None:
    stop_reader.set()
    if proc is not None and proc.isalive():  # type: ignore[attr-defined]
        proc.kill()  # type: ignore[attr-defined]


def _spawn_posix_pty_process(
    request: ToolCall,
    slave_fd: int,
) -> subprocess.Popen[bytes]:
    env = _merged_env(request.env) if request.env else None
    return subprocess.Popen(
        list(request.argv),
        cwd=request.cwd,
        env=env,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
    )


def _wait_for_posix_pty(
    request: ToolCall,
    proc: subprocess.Popen[bytes],
    master_fd: int,
    output_parts: list[str],
    select_module: Any,
) -> ToolResult:
    started = time.monotonic()
    while True:
        if time.monotonic() - started > request.timeout_seconds:
            proc.kill()
            return _timeout_result(request, output_parts)
        _read_posix_ready(master_fd, output_parts, select_module, timeout=0.05)
        if proc.poll() is not None:
            _drain_posix_pty(master_fd, output_parts, select_module)
            return _allowed_result(request, proc.returncode, output_parts)


def _read_posix_ready(
    master_fd: int,
    output_parts: list[str],
    select_module: Any,
    timeout: float,
) -> bool:
    ready, _, _ = select_module.select([master_fd], [], [], timeout)
    if not ready:
        return False
    try:
        chunk = os.read(master_fd, 4096)
    except OSError:
        return False
    if chunk:
        output_parts.append(chunk.decode("utf-8", errors="replace"))
    return bool(chunk)


def _drain_posix_pty(master_fd: int, output_parts: list[str], select_module: Any) -> None:
    while _read_posix_ready(master_fd, output_parts, select_module, timeout=0):
        pass


def _close_posix_pty(
    master_fd: int,
    slave_fd: int,
    proc: subprocess.Popen[bytes] | None,
) -> None:
    if slave_fd >= 0:
        os.close(slave_fd)
    os.close(master_fd)
    if proc is not None and proc.poll() is None:
        proc.kill()


def _read_winpty_output(
    proc: object,
    output_queue: queue.Queue[str],
    stop_reader: threading.Event,
) -> None:
    while not stop_reader.is_set():
        try:
            try:
                chunk = proc.read(4096)  # type: ignore[attr-defined]
            except TypeError:
                chunk = proc.read()  # type: ignore[attr-defined]
        except EOFError:
            break
        except OSError as exc:
            output_queue.put(str(exc))
            break
        if chunk:
            output_queue.put(str(chunk))
        else:
            time.sleep(0.02)


def _drain_queue(output_queue: queue.Queue[str], output_parts: list[str]) -> None:
    while True:
        try:
            output_parts.append(output_queue.get_nowait())
        except queue.Empty:
            break
