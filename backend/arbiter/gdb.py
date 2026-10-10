"""Debugging a leased board through GDB/MI (design doc §9).

`DebugSession` starts the board's GDB server (`west debugserver` on a free port, through
the driver) and the build's gdb in MI mode, and keeps both for the lease. Agents send
allowlisted CLI commands in batches and get plain text back; execution commands (continue,
next, finish, ...) wait for the target to stop, up to a limit_s, and interrupt it after
that, so a call never hangs on a running target.

`inspect_hung` halts the board, takes the current backtrace, walks Zephyr's thread list
(`_kernel.threads`, needs CONFIG_THREAD_MONITOR) with each thread's state and the object
it is pended on, and lets the board run again: "where is it stuck?" in one call."""

from __future__ import annotations

import asyncio
import contextlib
import re
import shutil
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .coredump import parse_gdb
from .elf import EM_386, EM_AARCH64, EM_ARM, EM_RISCV, EM_X86_64, Elf, ElfError
from .errors import ArbiterError
from .workspace import cache_value

CONNECT_S = 20.0  # how long the GDB server may take to come up
CMD_TIMEOUT_S = 15.0
MAX_OUTPUT = 6000  # characters of output per command
MAX_THREADS = 48

# CLI commands an agent may send (first word, without /FMT). Execution commands wait for
# the target to stop. Everything that runs host code, writes files or changes the target
# setup (shell, python, source, dump, restore, file, load, target, call, ...) is refused.
READ_CMDS = {
    "bt", "backtrace", "where", "frame", "f", "up", "down", "info", "i", "print", "p",
    "output", "x", "ptype", "whatis", "list", "l", "display", "undisplay", "thread", "echo",
}  # fmt: skip
BREAK_CMDS = {
    "break", "b", "tbreak", "hbreak", "thbreak", "delete", "d", "disable", "enable",
    "condition", "ignore", "watch", "rwatch", "awatch", "clear",
}  # fmt: skip
EXEC_CMDS = {
    "continue", "c", "next", "n", "step", "s", "stepi", "si", "nexti", "ni", "finish",
    "fin", "until", "u", "advance",
}  # fmt: skip
MONITOR_OK = {"reset", "halt", "go", "r", "h"}

# Zephyr's k_thread.base.thread_state bits (kernel/include/kthread.h, Zephyr 3.x/4.x)
THREAD_STATES = {
    0x01: "dummy",
    0x02: "pending",
    0x04: "sleeping",
    0x08: "dead",
    0x10: "suspended",
    0x20: "aborting",
    0x40: "suspending",
    0x80: "queued",
}

_STRING = r'"((?:[^"\\]|\\.)*)"'
_RESULT = re.compile(r"^(\d*)\^(done|running|connected|error|exit)(.*)$")


def check_command(cmd: str) -> None:
    """Raise unless `cmd` is an allowed gdb CLI command."""
    words = cmd.strip().split()
    if not words:
        raise ArbiterError("BAD_REQUEST", "empty gdb command")
    first = words[0].split("/", 1)[0].lower()
    if first == "thread" and len(words) > 3 and words[1] == "apply":
        return check_command(" ".join(words[3:]))  # thread apply <ids|all> <command>
    if first in READ_CMDS | BREAK_CMDS | EXEC_CMDS:
        return None
    if first == "set" and len(words) > 1 and words[1] in ("var", "variable"):
        return None
    if first in ("monitor", "mon") and len(words) > 1 and words[1].lower() in MONITOR_OK:
        return None
    raise ArbiterError(
        "NOT_ALLOWED",
        f"gdb command {words[0]!r} is not allowed",
        hint="Allowed: inspection (bt, info, print, x, list, frame, thread), breakpoints and "
        "watchpoints, stepping (next, step, finish, until; continue via gdb_continue), "
        "'set var', and 'monitor reset/halt/go'.",
    )


def is_exec(cmd: str) -> bool:
    return cmd.strip().split()[0].split("/", 1)[0].lower() in EXEC_CMDS


def mi_quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def mi_unquote(text: str) -> str:
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            simple = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "r": "\r", "e": "\x1b"}
            if nxt in simple:
                out.append(simple[nxt])
                i += 2
                continue
            m = re.match(r"[0-7]{1,3}", text[i + 1 :])
            if m:
                out.append(chr(int(m.group(0), 8)))
                i += 1 + len(m.group(0))
                continue
        out.append(ch)
        i += 1
    # octal escapes are UTF-8 bytes
    return "".join(out).encode("latin-1", errors="replace").decode("utf-8", errors="replace")


def mi_field(record: str, name: str) -> str | None:
    m = re.search(rf"\b{name}={_STRING}", record)
    return mi_unquote(m.group(1)) if m else None


@dataclass
class MiReply:
    result: str  # done | running | error | connected | exit | limit_s
    console: str = ""
    record: str = ""
    stopped: str | None = None  # the *stopped record, for execution commands
    interrupted: bool = False

    @property
    def error(self) -> str | None:
        return mi_field(self.record, "msg") if self.result == "error" else None

    def stop_info(self) -> dict[str, Any] | None:
        if self.stopped is None:
            return None
        info: dict[str, Any] = {"reason": mi_field(self.stopped, "reason") or "unknown"}
        for key in ("func", "file", "line", "addr", "signal-name"):
            value = mi_field(self.stopped, key)
            if value is not None:
                info[key.replace("-", "_")] = int(value) if key == "line" else value
        if self.interrupted:
            info["interrupted_after_timeout"] = True
        return info


class MiGdb:
    """A gdb process in MI mode, one command at a time."""

    def __init__(self, proc: asyncio.subprocess.Process):
        self.proc = proc
        self.token = 0
        self.lock = asyncio.Lock()
        self.running = False

    @classmethod
    async def start(cls, gdb: list[str], elf: Path) -> MiGdb:
        proc = await asyncio.create_subprocess_exec(
            *gdb,
            "--interpreter=mi3",
            "-nx",
            "-q",
            str(elf),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        mi = cls(proc)
        await mi._read_until(lambda line: line.startswith("(gdb)"), 15)
        await mi.mi("-gdb-set pagination off")
        await mi.mi("-gdb-set confirm off")
        # Without async mode gdb doesn't read commands while the target runs, so
        # -exec-interrupt would never arrive.
        await mi.mi("-gdb-set mi-async on")
        return mi

    async def _readline(self, limit_s: float) -> str:
        assert self.proc.stdout is not None
        raw = await asyncio.wait_for(self.proc.stdout.readline(), limit_s)
        if not raw:
            raise ArbiterError("OP_FAILED", "gdb exited")
        return raw.decode(errors="replace").rstrip("\r\n")

    async def _read_until(self, done: Callable[[str], bool], limit_s: float) -> list[str]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + limit_s
        lines = []
        while True:
            line = await self._readline(max(0.01, deadline - loop.time()))
            lines.append(line)
            if done(line):
                return lines

    async def _send(self, text: str) -> int:
        assert self.proc.stdin is not None
        self.token += 1
        self.proc.stdin.write(f"{self.token}{text}\n".encode())
        await self.proc.stdin.drain()
        return self.token

    async def mi(self, command: str, limit_s: float = CMD_TIMEOUT_S) -> MiReply:
        """An MI command; for ^running, waits for *stopped (interrupting after `limit_s`)."""
        async with self.lock:
            return await self._mi(command, limit_s)

    async def cli(self, command: str, limit_s: float = CMD_TIMEOUT_S) -> MiReply:
        return await self.mi(f"-interpreter-exec console {mi_quote(command)}", limit_s)

    async def _mi(self, command: str, limit_s: float) -> MiReply:
        token = await self._send(command)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + limit_s
        console: list[str] = []
        reply = MiReply("limit_s")
        try:
            while True:
                line = await self._readline(max(0.01, deadline - loop.time()))
                if line.startswith(("~", "@")):
                    console.append(mi_unquote(line[2:-1]))
                    continue
                m = _RESULT.match(line)
                if m and m.group(1) == str(token):
                    reply.result, reply.record = m.group(2), line
                    break
        except TimeoutError:
            reply.console = "".join(console)
            return reply
        if reply.result == "running":
            self.running = True
            reply.stopped, more, reply.interrupted = await self._wait_stopped(deadline)
            console += more
        reply.console = "".join(console)
        return reply

    async def _wait_stopped(self, deadline: float) -> tuple[str | None, list[str], bool]:
        loop = asyncio.get_running_loop()
        console: list[str] = []
        interrupted = False
        while True:
            try:
                line = await self._readline(max(0.01, deadline - loop.time()))
            except TimeoutError:
                if interrupted:
                    return None, console, True
                interrupted = True
                await self._send("-exec-interrupt")
                deadline = loop.time() + 5
                continue
            if line.startswith(("~", "@")):
                console.append(mi_unquote(line[2:-1]))
            elif line.startswith("*stopped"):
                self.running = False
                return line, console, interrupted

    async def resume(self) -> None:
        """Let the target run, without waiting for it to stop."""
        async with self.lock:
            if self.running:
                return
            token = await self._send("-exec-continue")
            lines = await self._read_until(
                lambda line: bool((m := _RESULT.match(line)) and m.group(1) == str(token)), 10
            )
            self.running = "^running" in lines[-1]

    async def interrupt(self, limit_s: float = 5) -> str | None:
        """Halt a running target; returns the *stopped record."""
        async with self.lock:
            if not self.running:
                return None
            await self._send("-exec-interrupt")
            loop = asyncio.get_running_loop()
            stopped, _console, _ = await self._wait_stopped(loop.time() + limit_s)
            return stopped

    async def close(self) -> None:
        if self.proc.returncode is None:
            with contextlib.suppress(Exception):
                assert self.proc.stdin is not None
                self.proc.stdin.write(b"-gdb-exit\n")
                await self.proc.stdin.drain()
                await asyncio.wait_for(self.proc.wait(), 3)
            if self.proc.returncode is None:
                self.proc.kill()
                with contextlib.suppress(Exception):
                    await self.proc.wait()


# ---------------------------------------------------------------------------- tools
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def find_gdb(image: dict[str, Any]) -> list[str]:
    """The build's gdb (CMAKE_GDB), else a gdb for the ELF's architecture on PATH."""
    image_dir = Path(image["image_dir"])
    for cache in (image_dir / "CMakeCache.txt", Path(image["build_dir"]) / "CMakeCache.txt"):
        found = cache_value(cache, "CMAKE_GDB")
        if found and Path(found).exists():
            return [found]
    try:
        machine = Elf.load(Path(image["elf"])).machine
    except ElfError:
        machine = None
    names = {
        EM_ARM: ["arm-zephyr-eabi-gdb", "arm-none-eabi-gdb", "gdb-multiarch"],
        EM_AARCH64: ["aarch64-zephyr-elf-gdb", "gdb-multiarch"],
        EM_RISCV: ["riscv64-zephyr-elf-gdb", "gdb-multiarch"],
        EM_X86_64: ["gdb"],
        EM_386: ["gdb"],
    }.get(machine or 0, ["gdb-multiarch", "gdb"])
    for name in names:
        if found := shutil.which(name):
            return [found]
    raise ArbiterError(
        "NOT_SUPPORTED",
        "no gdb for this build",
        hint="The build's CMakeCache names no CMAKE_GDB and none of "
        + ", ".join(names)
        + " is on PATH. Install the Zephyr SDK.",
    )


# ---------------------------------------------------------------------------- session
ServerStarter = Callable[[int], Awaitable[asyncio.subprocess.Process]]


@dataclass
class DebugSession:
    board: str
    elf: Path
    server: asyncio.subprocess.Process
    gdb: MiGdb
    port: int
    detached: list[str] = field(default_factory=list)  # console sources to give back (RTT)

    @classmethod
    async def open(
        cls, board: str, image: dict[str, Any], start_server: ServerStarter
    ) -> DebugSession:
        elf = Path(image["elf"])
        if not await asyncio.to_thread(elf.exists):
            raise ArbiterError("OP_FAILED", f"ELF not found: {elf}")
        gdb_cmd = find_gdb(image)
        port = free_port()
        server = await start_server(port)
        gdb: MiGdb | None = None
        try:
            gdb = await MiGdb.start(gdb_cmd, elf)
            await _connect(gdb, server, port)
        except BaseException:
            if gdb is not None:
                await gdb.close()
            await _kill(server)
            raise
        return cls(board, elf, server, gdb, port)

    async def where(self) -> dict[str, Any]:
        rep = await self.gdb.cli("bt 12")
        frames, _ = parse_gdb(rep.console)
        return {"backtrace": frames} if frames else {"output": _trim(rep.console)}

    async def batch(self, cmds: list[str], timeout_s: float) -> list[dict[str, Any]]:
        for c in cmds:
            check_command(c)
        out = []
        for c in cmds:
            rep = await self.gdb.cli(c, timeout_s)
            item: dict[str, Any] = {"cmd": c, "output": _trim(rep.console)}
            if rep.error:
                item["error"] = rep.error
            if rep.result == "limit_s":
                item["error"] = f"no answer from gdb within {timeout_s:g} s"
            stop = rep.stop_info()
            if stop:
                item["stopped"] = stop
            out.append(item)
            if item.get("error"):
                break
        return out

    async def cont(self, timeout_s: float) -> dict[str, Any]:
        rep = await self.gdb.mi("-exec-continue", timeout_s)
        out: dict[str, Any] = {"stopped": rep.stop_info()}
        if rep.error:
            out["error"] = rep.error
        if rep.stopped is not None:
            out.update(await self.where())
        return out

    async def inspect(self) -> dict[str, Any]:
        """Halt, back-trace, list the kernel's threads, then let the target run again."""
        was_running = self.gdb.running
        if was_running:
            await self.gdb.interrupt()
        out: dict[str, Any] = {}
        bt = await self.gdb.cli("bt 16")
        frames, _ = parse_gdb(bt.console)
        out["backtrace"] = frames or []
        info = await self.gdb.cli("info threads")
        rtos = [ln.strip() for ln in info.console.splitlines() if re.match(r"^\*?\s+\d+\s", ln)]
        out["rtos_aware"] = len(rtos) > 1
        if out["rtos_aware"]:
            all_bt = await self.gdb.cli("thread apply all bt 8", 30)
            out["all_threads_bt"] = _trim(all_bt.console)
        threads, note = await self.kernel_threads()
        out["threads"] = threads
        if note:
            out.setdefault("hints", []).append(note)
        if not out["rtos_aware"]:
            out.setdefault("hints", []).append(
                "The GDB server is not thread-aware, so only the current thread has a "
                "backtrace. For J-Link, Zephyr's RTOS plugin needs CONFIG_DEBUG_THREAD_INFO=y."
            )
        return out

    async def kernel_threads(self) -> tuple[list[dict[str, Any]], str | None]:
        first = await self.eval("(unsigned long)_kernel.threads")
        if first is None:
            return [], (
                "Cannot read _kernel.threads: build with CONFIG_THREAD_MONITOR=y "
                "(and CONFIG_THREAD_NAME=y for names) to list threads."
            )
        current = await self.eval("(unsigned long)_kernel.cpus[0].current")
        threads: list[dict[str, Any]] = []
        addr = _int(first)
        seen = set()
        while addr and addr not in seen and len(threads) < MAX_THREADS:
            seen.add(addr)
            t = f"((struct k_thread *){addr:#x})"
            state = _int(await self.eval(f"(unsigned int){t}->base.thread_state"))
            entry: dict[str, Any] = {
                "address": f"{addr:#010x}",
                "name": _cstring(await self.eval(f"{t}->name")),
                "priority": _int(await self.eval(f"(int){t}->base.prio"), signed=True),
                "state": [n for bit, n in THREAD_STATES.items() if state & bit] or ["ready"],
            }
            if current is not None and _int(current) == addr:
                entry["current"] = True
            pended = _int(await self.eval(f"(unsigned long){t}->base.pended_on"))
            if pended:
                sym = await self.gdb.cli(f"info symbol {pended:#x}")
                entry["pended_on"] = sym.console.strip().split(" in section")[0] or hex(pended)
            threads.append(entry)
            addr = _int(await self.eval(f"(unsigned long){t}->next_thread"))
        return threads, None

    async def eval(self, expr: str) -> str | None:
        rep = await self.gdb.mi(f"-data-evaluate-expression {mi_quote(expr)}")
        return mi_field(rep.record, "value") if rep.result == "done" else None

    async def close(self, resume: bool = True) -> None:
        with contextlib.suppress(Exception):
            if self.gdb.running:
                await self.gdb.interrupt()
            if resume:
                await self.gdb.mi("-target-detach", 5)  # lets the target run on
        await self.gdb.close()
        await _kill(self.server)


async def _connect(gdb: MiGdb, server: asyncio.subprocess.Process, port: int) -> None:
    """Connect gdb to the server, retrying while the server starts up."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + CONNECT_S
    while True:
        rep = await gdb.mi(f"-target-select extended-remote 127.0.0.1:{port}", 10)
        if rep.result == "connected":
            return
        if server.returncode is not None:
            raise ArbiterError(
                "OP_FAILED",
                f"the GDB server exited with code {server.returncode}",
                hint="See the debugserver log; another debugger may hold the probe.",
            )
        if loop.time() > deadline:
            raise ArbiterError("OP_FAILED", f"cannot connect gdb to the GDB server: {rep.error}")
        await asyncio.sleep(0.5)


async def _kill(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    from .procs import kill_tree

    with contextlib.suppress(Exception):
        await asyncio.to_thread(kill_tree, proc.pid)
    with contextlib.suppress(Exception):
        await asyncio.wait_for(proc.wait(), 5)


def _trim(text: str) -> str:
    text = text.strip()
    if len(text) > MAX_OUTPUT:
        return text[:MAX_OUTPUT] + f"\n... ({len(text) - MAX_OUTPUT} more characters)"
    return text


def _int(value: str | None, signed: bool = False) -> int:
    if not value:
        return 0
    m = re.search(r"-?(?:0x[0-9a-fA-F]+|\d+)", value)
    if not m:
        return 0
    n = int(m.group(0), 0)
    return n if signed or n >= 0 else n & 0xFFFFFFFF


def _cstring(value: str | None) -> str | None:
    """A gdb char array value like `"main", '\\000' <repeats 27 times>` as text."""
    if not value:
        return None
    m = re.search(r'"((?:[^"\\]|\\.)*)"', value)
    return m.group(1) if m else None
