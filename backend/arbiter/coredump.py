"""Zephyr coredump to backtrace, with no probe attached.

An image built with CONFIG_DEBUG_COREDUMP=y and CONFIG_DEBUG_COREDUMP_BACKEND_LOGGING=y
prints its dump on the console as `#CD:` lines when it crashes. The crash watcher keeps
those lines; this module runs Zephyr's own tools on them:

    scripts/coredump/coredump_serial_log_parser.py  dump.log -> dump.bin
    scripts/coredump/coredump_gdbserver.py --pipe   a GDB server over stdio
    the toolchain's gdb, batch mode                 bt, info threads, thread apply all bt

GDB talks to the server through a loopback socket that arbiter bridges to the server's
stdin/stdout, so no shell command line (and no quoting of Windows paths) is involved.
Everything comes from the build: ZEPHYR_BASE, Python3_EXECUTABLE and CMAKE_GDB in its
CMakeCache."""

from __future__ import annotations

import contextlib
import re
import socket
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

from .workspace import build_python, cache_value, zephyr_base_from_build

GDB_COMMANDS = [
    "set pagination off",
    "set confirm off",
    "set print frame-arguments scalars",
    "bt",
    "info registers",
    "info threads",
    "thread apply all bt",
]
TIMEOUT_S = 60.0
MAX_TEXT = 8000  # characters of gdb output kept in the report

_FRAME = re.compile(
    r"^#(?P<n>\d+)\s+(?:(?P<addr>0x[0-9a-fA-F]+) in )?(?P<func>[\w:~<>.$]+|\?\?)\s*"
    r"\((?P<args>.*?)\)(?:\s+at\s+(?P<file>\S+?):(?P<line>\d+)|\s+from\s+\S+)?\s*$"
)
_MISSING = (
    "Build with CONFIG_DEBUG_COREDUMP=y and CONFIG_DEBUG_COREDUMP_BACKEND_LOGGING=y "
    "to get a coredump on the console."
)


@dataclass
class Tools:
    python: list[str]
    parser: Path
    gdbserver: Path
    gdb: list[str]

    @property
    def server_cmd(self) -> list[str]:
        return [*self.python, str(self.gdbserver), "--pipe"]


@dataclass
class CoredumpReport:
    ok: bool = False
    backtrace: list[dict[str, Any]] = field(default_factory=list)
    threads: list[str] = field(default_factory=list)
    gdb_output: str = ""
    files: dict[str, str] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"ok": self.ok, "backtrace": self.backtrace, "files": self.files}
        if self.threads:
            d["threads"] = self.threads
        if self.error:
            d["error"] = self.error
        if self.gdb_output:
            d["gdb_output"] = self.gdb_output[-MAX_TEXT:]
        return d


def complete(lines: list[str]) -> str | None:
    """None if the `#CD:` lines hold a whole dump, else what is wrong with them."""
    if not lines:
        return "no coredump was printed. " + _MISSING
    if not any("#CD:BEGIN#" in ln for ln in lines):
        return "the coredump's start (#CD:BEGIN#) is missing"
    if any("#CD:ERROR" in ln for ln in lines):
        return "the device reported an error while dumping (#CD:ERROR)"
    if not any("#CD:END#" in ln for ln in lines):
        return "the coredump was cut off before #CD:END#"
    return None


def find_tools(image_dir: Path, build_dir: Path) -> Tools | str:
    """Zephyr's coredump scripts, the build's Python and the build's gdb, or why not."""
    cache = image_dir / "CMakeCache.txt"
    zephyr = zephyr_base_from_build(build_dir)
    if zephyr is None:
        return "cannot find ZEPHYR_BASE for this build (no CMakeCache.txt?)"
    scripts = zephyr / "scripts" / "coredump"
    parser, server = scripts / "coredump_serial_log_parser.py", scripts / "coredump_gdbserver.py"
    if not (parser.exists() and server.exists()):
        return f"Zephyr's coredump scripts are not in {scripts}"
    python = build_python(image_dir, build_dir)
    gdb = cache_value(cache, "CMAKE_GDB")
    if not gdb or not Path(gdb).exists():
        return "the build's CMakeCache names no gdb (CMAKE_GDB); is the Zephyr SDK installed?"
    return Tools(python, parser, server, [gdb])


def analyze(lines: list[str], elf: Path, tools: Tools, work_dir: Path) -> CoredumpReport:
    """Run the parser, the GDB server and gdb on one dump. Never raises."""
    rep = CoredumpReport()
    why = complete(lines)
    if why:
        rep.error = why
        return rep
    work_dir.mkdir(parents=True, exist_ok=True)
    log_path, bin_path = work_dir / "coredump.log", work_dir / "coredump.bin"
    out_path = work_dir / "gdb.txt"
    log_path.write_text("\n".join(lines) + "\n")
    rep.files = {"log": str(log_path), "bin": str(bin_path), "gdb": str(out_path)}
    try:
        p = subprocess.run(
            [*tools.python, str(tools.parser), str(log_path), str(bin_path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as e:
        rep.error = f"coredump_serial_log_parser.py failed to run: {e}"
        return rep
    if p.returncode != 0 or not bin_path.exists():
        rep.error = "coredump_serial_log_parser.py failed: " + _last(p.stderr or p.stdout)
        return rep
    try:
        text = run_gdb([*tools.server_cmd, str(elf), str(bin_path)], tools.gdb, elf)
    except (OSError, subprocess.SubprocessError, TimeoutError) as e:
        rep.error = f"gdb on the coredump failed: {e}"
        return rep
    out_path.write_text(text)
    rep.gdb_output = text
    rep.backtrace, rep.threads = parse_gdb(text)
    rep.ok = bool(rep.backtrace)
    if not rep.ok:
        rep.error = "gdb printed no backtrace: " + _last(text)
    return rep


def run_gdb(
    server_cmd: list[str], gdb_cmd: list[str], elf: Path, timeout: float = TIMEOUT_S
) -> str:
    """gdb in batch mode against a stdio GDB server, bridged through a loopback socket."""
    with socket.create_server(("127.0.0.1", 0)) as lsock:
        port = lsock.getsockname()[1]
        lsock.settimeout(timeout)
        server = subprocess.Popen(
            server_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        args = [*gdb_cmd, "-batch", "-nx", "-q"]
        for c in [*GDB_COMMANDS[:3], f"target remote 127.0.0.1:{port}", *GDB_COMMANDS[3:]]:
            args += ["-ex", c]
        gdb = subprocess.Popen(
            [*args, str(elf)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            conn, _ = lsock.accept()
            with conn:
                assert server.stdin is not None and server.stdout is not None
                threads = [
                    threading.Thread(target=_to_proc, args=(conn, server.stdin), daemon=True),
                    threading.Thread(target=_to_sock, args=(server.stdout, conn), daemon=True),
                ]
                for t in threads:
                    t.start()
                out, _ = gdb.communicate(timeout=timeout)
        finally:
            for proc in (gdb, server):
                if proc.poll() is None:
                    proc.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(5)
        return out or ""


def _to_proc(conn: socket.socket, dst: IO[bytes]) -> None:
    with contextlib.suppress(OSError, ValueError):
        while data := conn.recv(4096):
            dst.write(data)
            dst.flush()
    with contextlib.suppress(OSError, ValueError):
        dst.close()


def _to_sock(src: IO[bytes], conn: socket.socket) -> None:
    with contextlib.suppress(OSError, ValueError):
        while data := src.read1(4096):  # type: ignore[attr-defined]
            conn.sendall(data)
    with contextlib.suppress(OSError):
        conn.shutdown(socket.SHUT_WR)


def parse_gdb(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Frames of the first `bt`, and the `info threads` lines."""
    frames: list[dict[str, Any]] = []
    threads: list[str] = []
    in_threads = False
    for raw in text.splitlines():
        line = raw.rstrip()
        m = _FRAME.match(line)
        if m:
            n = int(m["n"])
            if n == 0 and frames:
                break  # the next backtrace (thread apply all bt) starts
            frames.append(
                {
                    "frame": n,
                    "function": None if m["func"] == "??" else m["func"],
                    "args": m["args"] or None,
                    "file": m["file"],
                    "line": int(m["line"]) if m["line"] else None,
                    "address": m["addr"],
                }
            )
            continue
        if line.lstrip().startswith("Id ") and "Target Id" in line:
            in_threads = True
            continue
        if in_threads:
            if re.match(r"^\*?\s+\d+\s", line):
                threads.append(line.strip())
            elif line.strip():
                in_threads = False
    return frames, threads


def _last(text: str, n: int = 3) -> str:
    lines = [ln for ln in (text or "").strip().splitlines() if ln.strip()]
    return " | ".join(lines[-n:]) or "no output"
