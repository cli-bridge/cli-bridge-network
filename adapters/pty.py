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
            return ToolResult(
                capability_id=request.capability_id,
                allowed=True,
                exit_code=127,
                stderr=f"PTY transport failed to import pywinpty: {exc}",
                reason="pty-dependency-missing",
            )

        env = os.environ.copy()
        if request.env:
            env.update(request.env)
        started = time.monotonic()
        output_parts: list[str] = []
        output_queue: queue.Queue[str] = queue.Queue()
        stop_reader = threading.Event()
        proc = None
        try:
            proc = PtyProcess.spawn(
                list(request.argv),
                cwd=request.cwd,
                env=env,
                dimensions=(120, 40),
            )
            reader = threading.Thread(
                target=_read_winpty_output,
                args=(proc, output_queue, stop_reader),
                daemon=True,
            )
            reader.start()
            while proc.isalive():
                _drain_queue(output_queue, output_parts)
                if time.monotonic() - started > request.timeout_seconds:
                    proc.kill()
                    stop_reader.set()
                    reader.join(timeout=1)
                    _drain_queue(output_queue, output_parts)
                    return ToolResult(
                        capability_id=request.capability_id,
                        allowed=True,
                        exit_code=124,
                        stdout="".join(output_parts),
                        stderr=f"command timed out after {request.timeout_seconds} seconds",
                        reason="timeout",
                    )
                time.sleep(0.02)
            stop_reader.set()
            reader.join(timeout=1)
            _drain_queue(output_queue, output_parts)
            exit_code = getattr(proc, "exitstatus", None)
            if exit_code is None:
                exit_code = 0
            return ToolResult(
                capability_id=request.capability_id,
                allowed=True,
                exit_code=int(exit_code),
                stdout="".join(output_parts),
                reason="allowed",
            )
        except OSError as exc:
            return ToolResult(
                capability_id=request.capability_id,
                allowed=True,
                exit_code=127,
                stderr=f"{request.argv[0]} failed to start in PTY: {exc}",
                reason="spawn-failed",
            )
        finally:
            stop_reader.set()
            if proc is not None and proc.isalive():
                proc.kill()

    def _call_posix_pty(self, request: ToolCall) -> ToolResult:
        import pty
        import select

        env = None
        if request.env:
            env = os.environ.copy()
            env.update(request.env)
        master_fd, slave_fd = pty.openpty()
        started = time.monotonic()
        output_parts: list[str] = []
        proc = None
        try:
            proc = subprocess.Popen(
                list(request.argv),
                cwd=request.cwd,
                env=env,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
            )
            os.close(slave_fd)
            slave_fd = -1
            while True:
                if time.monotonic() - started > request.timeout_seconds:
                    proc.kill()
                    return ToolResult(
                        capability_id=request.capability_id,
                        allowed=True,
                        exit_code=124,
                        stdout="".join(output_parts),
                        stderr=f"command timed out after {request.timeout_seconds} seconds",
                        reason="timeout",
                    )
                ready, _, _ = select.select([master_fd], [], [], 0.05)
                if ready:
                    try:
                        chunk = os.read(master_fd, 4096)
                    except OSError:
                        chunk = b""
                    if chunk:
                        output_parts.append(chunk.decode("utf-8", errors="replace"))
                if proc.poll() is not None:
                    while True:
                        ready, _, _ = select.select([master_fd], [], [], 0)
                        if not ready:
                            break
                        try:
                            chunk = os.read(master_fd, 4096)
                        except OSError:
                            break
                        if not chunk:
                            break
                        output_parts.append(chunk.decode("utf-8", errors="replace"))
                    break
            return ToolResult(
                capability_id=request.capability_id,
                allowed=True,
                exit_code=proc.returncode,
                stdout="".join(output_parts),
                reason="allowed",
            )
        except OSError as exc:
            return ToolResult(
                capability_id=request.capability_id,
                allowed=True,
                exit_code=127,
                stderr=f"{request.argv[0]} failed to start in PTY: {exc}",
                reason="spawn-failed",
            )
        finally:
            if slave_fd >= 0:
                os.close(slave_fd)
            os.close(master_fd)
            if proc is not None and proc.poll() is None:
                proc.kill()


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
