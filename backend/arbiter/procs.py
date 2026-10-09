"""Subprocess runner: argv lists only (never shell strings), stdin closed, each
process in its own group/job, whole tree killed on timeout or cancel."""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import signal
import subprocess
import sys
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

IS_WINDOWS = sys.platform == "win32"


@dataclass
class ProcResult:
    argv: list[str]
    exit_code: int | None
    duration_s: float
    tail: list[str] = field(default_factory=list)
    log_path: str | None = None
    timed_out: bool = False
    cancelled: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.cancelled

    def summary(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "exit_code": self.exit_code,
            "duration_s": round(self.duration_s, 1),
            "timed_out": self.timed_out,
            "cancelled": self.cancelled,
            "log_path": self.log_path,
            "tail": self.tail,
        }


def which(name: str, override: str | None = None) -> str | None:
    if override:
        return override if Path(override).exists() or shutil.which(override) else None
    return shutil.which(name)


def kill_tree(pid: int, sig_first: bool = True, grace: float = 3.0) -> None:
    try:
        import psutil
    except ImportError:  # pragma: no cover
        with contextlib.suppress(OSError):
            if sys.platform == "win32":
                os.kill(pid, signal.SIGTERM)
            else:
                os.kill(pid, signal.SIGKILL)
        return
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    procs = [*parent.children(recursive=True), parent]
    if sig_first:
        for p in procs:
            try:
                if IS_WINDOWS:
                    p.terminate()
                else:
                    p.send_signal(signal.SIGINT)
            except psutil.NoSuchProcess:
                pass
        _gone, alive = psutil.wait_procs(procs, timeout=grace)
        procs = alive
    for p in procs:
        with contextlib.suppress(psutil.NoSuchProcess):
            p.kill()


async def start_detached(
    argv: list[str], cwd: str | Path | None, env: dict[str, str], log_path: Path
) -> asyncio.subprocess.Process:
    """A long-running helper (a GDB server) with its output going to `log_path`."""
    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as logf:
        logf.write(f"$ {' '.join(argv)}\n".encode())
        logf.flush()
        return await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd) if cwd else None,
            env={"PYTHONIOENCODING": "utf-8", **os.environ, **env},
            stdin=asyncio.subprocess.DEVNULL,
            stdout=logf,
            stderr=asyncio.subprocess.STDOUT,
            **kwargs,
        )


async def run_proc(
    argv: list[str],
    cwd: str | Path | None = None,
    env: dict[str, Any] | None = None,
    timeout_s: float = 300,
    log_path: Path | None = None,
    on_line: Callable[[str], None] | None = None,
    tail_lines: int = 40,
    on_start: Callable[[int], None] | None = None,
) -> ProcResult:
    t0 = time.monotonic()
    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    # Python tools (west, twister) print device output with odd bytes in it; on Windows
    # their console encoding would be cp1252 and logging raises UnicodeEncodeError.
    full_env = {"PYTHONIOENCODING": "utf-8", **os.environ, **(env or {})}
    tail: deque[str] = deque(maxlen=tail_lines)
    logf = None
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logf = await asyncio.to_thread(log_path.open, "a", encoding="utf-8", errors="replace")
        logf.write(f"$ {' '.join(argv)}\n")
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd) if cwd else None,
            env=full_env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            **kwargs,
        )
    except FileNotFoundError as e:
        if logf:
            logf.write(f"not found: {e}\n")
            logf.close()
        return ProcResult(
            argv, 127, 0.0, [f"command not found: {argv[0]}"], str(log_path) if log_path else None
        )
    if on_start:
        on_start(proc.pid)

    async def pump() -> None:
        assert proc.stdout
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").rstrip("\r\n")
            tail.append(line)
            if logf:
                logf.write(line + "\n")
            if on_line:
                on_line(line)

    res = ProcResult(argv, None, 0.0, log_path=str(log_path) if log_path else None)
    pump_task = asyncio.create_task(pump())
    try:
        await asyncio.wait_for(proc.wait(), timeout_s)
    except TimeoutError:
        res.timed_out = True
        await asyncio.to_thread(kill_tree, proc.pid)
    except asyncio.CancelledError:
        res.cancelled = True
        await asyncio.to_thread(kill_tree, proc.pid)
        await _finish(proc, pump_task)
        res.exit_code, res.duration_s, res.tail = proc.returncode, time.monotonic() - t0, list(tail)
        if logf:
            logf.write("[cancelled]\n")
            logf.close()
        raise
    await _finish(proc, pump_task)
    res.exit_code, res.duration_s, res.tail = proc.returncode, time.monotonic() - t0, list(tail)
    if logf:
        logf.write(f"[exit {res.exit_code}{' timeout' if res.timed_out else ''}]\n")
        logf.close()
    return res


async def _finish(proc: asyncio.subprocess.Process, pump_task: asyncio.Task[Any]) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(proc.wait(), 5)
    try:
        await asyncio.wait_for(pump_task, 2)
    except (TimeoutError, asyncio.CancelledError):
        pump_task.cancel()
