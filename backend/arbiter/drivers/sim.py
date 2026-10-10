"""A simulated Zephyr board, so the whole system runs and tests without hardware.

It boots with a Zephyr-style banner, answers a small shell (`help`, `kernel
uptime`, `test`, `sim fault`, `sim assert`, `sim coredump`, `sim sleep`, ...), and "flashes" any existing
build directory. Options under `[board.options]`:

    speed = 1.0          # >1 makes delays shorter (tests use 50)
    fail_flash = false   # every flash fails
    heartbeat_s = 0      # print a log line every N seconds (0 = off)
    app = "hello"        # app name shown in the banner before the first flash
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from pathlib import Path
from typing import Any

from ..config import BoardConfig
from ..console.detect import detect_from_build
from ..console.hub import ConsoleHub
from ..console.sources import CallbackSource
from ..errors import ArbiterError
from ..procs import ProcResult
from ..zephyr_shell import ShellCommand, ShellCommands
from .base import BoardDriver, LineFn

PROMPT = "uart:~$ "


class SimDriver(BoardDriver):
    kind = "sim"
    capabilities = frozenset(
        {"flash", "reset", "halt", "recover", "console", "run", "power", "modem_trace", "dfu"}
    )

    def __init__(self, cfg: BoardConfig, hub: ConsoleHub, state_dir: Path | None = None):
        super().__init__(cfg, hub, state_dir)
        o = cfg.options
        self.speed = float(o.get("speed", 1.0))
        self.fail_flash = bool(o.get("fail_flash", False))
        self.heartbeat_s = float(o.get("heartbeat_s", 0))
        self.app: str | None = o.get("app", "hello")
        self.powered = True
        self.halted = False
        self.booted_at = time.monotonic()
        self._line = ""
        self._boot_task: asyncio.Task[Any] | None = None
        self._hb_task: asyncio.Task[Any] | None = None
        self._trace_task: asyncio.Task[Any] | None = None
        self.health = "ok"
        # MCUboot slots for simulated MCUmgr: image 0, slot 0 runs, slot 1 takes uploads.
        self.slots: list[dict[str, Any] | None] = [
            {"version": "1.0.0", "hash": "a0" * 32, "flags": ["active", "confirmed"]},
            None,
        ]

    def _d(self, s: float) -> float:
        return s / self.speed

    def _out(self, text: str) -> None:
        if self.powered and not self.halted:
            self.hub.feed(text.encode(), "uart:app")

    # ---------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        await self.hub.attach(CallbackSource("uart:app", self._on_input))
        self._boot()
        if self.heartbeat_s > 0:
            self._hb_task = asyncio.create_task(self._heartbeat())

    async def stop(self) -> None:
        for t in (self._boot_task, self._hb_task, self._trace_task):
            if t:
                t.cancel()
        await super().stop()

    async def _heartbeat(self) -> None:
        n = 0
        while True:
            await asyncio.sleep(self._d(self.heartbeat_s))
            n += 1
            if self.app and self.powered and not self.halted:
                up = time.monotonic() - self.booted_at
                self._out(f"[{_ts(up)}] <inf> {self.app}: tick {n}\r\n")

    def _boot(self) -> None:
        if self._boot_task:
            self._boot_task.cancel()
        self._boot_task = asyncio.create_task(self._boot_seq())

    async def _boot_seq(self) -> None:
        self.booted_at = time.monotonic()
        self.halted = False
        await asyncio.sleep(self._d(0.2))
        if not self.app:
            return  # erased chip: silence
        self._out("*** Booting nRF Connect SDK v2.7.0 ***\r\n")
        self._out("*** Using Zephyr OS v3.6.99-100befc70c74 ***\r\n")
        await asyncio.sleep(self._d(0.1))
        self._out(f"[00:00:00.251,000] <inf> {self.app}: started on {self.cfg.platform}\r\n")
        self._out(PROMPT)

    # ---------------------------------------------------------------- shell
    async def _on_input(self, data: bytes) -> None:
        if not self.powered or self.halted:
            return
        for ch in data.decode(errors="replace"):
            if ch in "\r\n":
                line, self._line = self._line.strip(), ""
                self._out("\r\n")
                await self._cmd(line)
                self._out(PROMPT)
            else:
                self._line += ch
                self._out(ch)  # echo, like the Zephyr shell

    async def _cmd(self, line: str) -> None:
        if not line:
            return
        up = time.monotonic() - self.booted_at
        if line == "help":
            self._out("Available commands:\r\n  help  kernel  device  test  sim\r\n")
        elif line == "kernel version":
            self._out("Zephyr version 3.6.99\r\n")
        elif line == "kernel uptime":
            self._out(f"Uptime: {int(up * 1000)} ms\r\n")
        elif line == "kernel thread list":
            self._out(SIM_THREADS)
        elif line == "device list":
            self._out("devices:\r\n- uart@8000 (READY)\r\n- gpio@842500 (READY)\r\n")
        elif line == "test":
            self._out(
                "Running TESTSUITE sim_suite\r\n===================================================================\r\n"
            )
            await asyncio.sleep(self._d(0.3))
            self._out("PASS - test_boot in 0.001 seconds\r\nPASS - test_uart in 0.002 seconds\r\n")
            self._out("TESTSUITE sim_suite succeeded\r\nPROJECT EXECUTION SUCCESSFUL\r\n")
        elif line == "sim fault":
            t = f"[{_ts(up)}] <err> os:"
            self._out(
                f"{t} ***** BUS FAULT *****\r\n"
                f"{t}   Precise data bus error\r\n"
                f"{t}   BFAR Address: 0x50008120\r\n"
                f"{t} r0/a1:  0x00000000  r1/a2:  0x00000001  r2/a3:  0x20001c40\r\n"
                f"{t} r3/a4:  0x50008120 r12/ip:  0x00000000 r14/lr:  0x0000a3e5\r\n"
                f"{t}  xpsr:  0x61000000\r\n"
                f"{t} Faulting instruction address (r15/pc): 0x0000a3f2\r\n"
                f"{t} >>> ZEPHYR FATAL ERROR 0: CPU exception on CPU 0\r\n"
                f"{t} Current thread: 0x20000c08 (main)\r\n"
                f"[{_ts(up)}] <err> fatal_error: Resetting system\r\n"
            )
            self._boot()
        elif line == "sim coredump":
            t = f"[{_ts(up)}] <err> os:"
            self._out(
                f"{t} ***** HARD FAULT *****\r\n"
                f"{t} Faulting instruction address (r15/pc): 0x0000a3f2\r\n"
                f"{t} >>> ZEPHYR FATAL ERROR 0: CPU exception on CPU 0\r\n"
                f"{t} Current thread: 0x20000c08 (main)\r\n"
                f"{t} Halting system\r\n"
                f"{t} #CD:BEGIN#\r\n"
                f"{t} #CD:5a4501000300050000000000\r\n"
                f"{t} #CD:END#\r\n"
            )
            self.halted = True
        elif line == "sim assert":
            self._out(
                "ASSERTION FAIL [buf != NULL] @ WEST_TOPDIR/app/src/main.c:42\r\n"
                "\tbuffer pool exhausted\r\n"
                f"[{_ts(up)}] <err> os: >>> ZEPHYR FATAL ERROR 4: Kernel panic on CPU 0\r\n"
                f"[{_ts(up)}] <err> os: Current thread: 0x20000c08 (main)\r\n"
                f"[{_ts(up)}] <err> os: Halting system\r\n"
            )
            self.halted = True
        elif line.startswith("at "):
            reply = SIM_AT.get(line[3:].strip().upper())
            self._out((reply + "\r\nOK" if reply else "OK") if reply is not None else "ERROR")
            self._out("\r\n")
        elif line == "sim sleep":
            self._out(f"[{_ts(up)}] <inf> {self.app}: Entering sleep\r\n")
        else:
            self._out(f"{line.split(maxsplit=1)[0]}: command not found\r\n")

    def shell_commands(self, build_dir: Path) -> ShellCommands:
        """The simulator's own shell, so console completion can be tried without hardware."""
        c = ShellCommand
        return ShellCommands(
            True,
            commands=[
                c("at", "Send an AT command to the modem", 1),
                c("device", "Device commands", 1, subcommands=[c("list", "List devices", 1)]),
                c("help", "Prints the help message.", 1),
                c(
                    "kernel",
                    "Kernel commands",
                    1,
                    subcommands=[
                        c(
                            "thread",
                            "Thread commands.",
                            1,
                            subcommands=[c("list", "List kernel threads.", 1)],
                        ),
                        c("uptime", "Kernel uptime.", 1),
                        c("version", "Kernel version.", 1),
                    ],
                ),
                c(
                    "sim",
                    "Simulator controls",
                    1,
                    subcommands=[
                        c("assert", "Fail an assert and halt", 1),
                        c("coredump", "Hard fault with a coredump, then halt", 1),
                        c("fault", "Bus fault, then reset", 1),
                        c("sleep", "Log entering sleep", 1),
                    ],
                ),
                c("test", "Run the simulated test suite", 1),
            ],
        )

    # ---------------------------------------------------------------- operations
    async def flash(
        self,
        build_dir: Path,
        *,
        domain: str | None,
        erase: bool,
        cwd: Path | None,
        log_path: Path,
        on_line: LineFn,
    ) -> dict[str, Any]:
        build_dir = await asyncio.to_thread(Path(build_dir).resolve)
        if not await asyncio.to_thread(build_dir.exists):
            raise ArbiterError("OP_FAILED", f"build dir not found: {build_dir}")
        lines = [
            "-- west flash: rebuilding (sim)",
            f"-- runners.sim: Flashing file: {build_dir}/zephyr/zephyr.hex",
        ]
        if erase:
            lines.append("-- runners.sim: Erasing all flash")
        lines += ["-- runners.sim: Programming 64 kB", "-- runners.sim: Verifying"]
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a") as f:
            for ln in lines:
                f.write(ln + "\n")
                on_line(ln)
                await asyncio.sleep(self._d(0.3))
            if self.fail_flash:
                msg = "ERROR: runners.sim: target not responding (simulated failure)"
                f.write(msg + "\n")
                return {
                    "ok": False,
                    "exit_code": 1,
                    "tail": [*lines, msg],
                    "log_path": str(log_path),
                }
            f.write("-- runners.sim: Board reset\n")
        self.app = build_dir.name if build_dir.name not in ("build", "") else build_dir.parent.name
        self.console_map = detect_from_build(build_dir)
        self._boot()
        return {"ok": True, "exit_code": 0, "tail": lines[-3:], "log_path": str(log_path)}

    async def reset(self, *, halt: bool, log_path: Path) -> dict[str, Any]:
        self._out("\r\n")
        if halt:
            self.halted = True
            return {"ok": True, "halted": True}
        self._boot()
        return {"ok": True, "halted": False}

    async def smp(self, args: list[str], *, log_path: Path, timeout_s: float = 60) -> ProcResult:
        """Simulated `mcumgr`: upload, list, test, confirm and reset with MCUboot's swap."""
        t0 = time.monotonic()
        out: list[str] = []
        code = 0
        s0, s1 = self.slots
        match args:
            case ["image", "upload", path]:
                data = await asyncio.to_thread(Path(path).read_bytes)
                await asyncio.sleep(self._d(0.3))
                self.slots[1] = {
                    "version": "1.1.0",
                    "hash": hashlib.sha256(data).hexdigest(),
                    "flags": [],
                }
                out = [f"{len(data)} / {len(data)} [=====] 100.00%", "Done"]
            case ["image", "list"]:
                out = ["Images:"]
                for i, s in enumerate(self.slots):
                    if s is not None:
                        out += [
                            f" image=0 slot={i}",
                            f"    version: {s['version']}",
                            "    bootable: true",
                            f"    flags: {' '.join(s['flags'])}",
                            f"    hash: {s['hash']}",
                        ]
                out.append("Split status: N/A (0)")
            case ["image", "test", h] if s1 is not None and s1["hash"] == h:
                s1["flags"] = ["pending"]
            case ["image", "confirm", *h] if s0 is not None and h in ([], [s0["hash"]]):
                s0["flags"] = ["active", "confirmed"]
                if s1 is not None:
                    s1["flags"] = []
            case ["reset"]:
                if s1 is not None and "pending" in s1["flags"] and s0 is not None:
                    s1["flags"], s0["flags"] = ["active"], ["confirmed"]
                    self.slots = [s1, s0]
                elif s0 is not None and "confirmed" not in s0["flags"] and s1 is not None:
                    s1["flags"], s0["flags"] = ["active", "confirmed"], []  # MCUboot reverts
                    self.slots = [s1, s0]
                self._out("\r\n")
                self._boot()
            case _:
                code, out = 1, [f"Error: simulated mcumgr cannot do {' '.join(args)}"]
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a") as f:
            f.write("\n".join(out) + "\n")
        return ProcResult(["mcumgr", *args], code, time.monotonic() - t0, out, str(log_path))

    async def recover(self, *, log_path: Path) -> dict[str, Any]:
        await asyncio.sleep(self._d(0.5))
        self.app = None
        self._boot()
        return {"ok": True, "erased": True}

    async def modem_trace(self, on: bool) -> None:
        """Simulated modem trace: a few bytes of binary data every 50 ms."""
        if self._trace_task:
            self._trace_task.cancel()
            self._trace_task = None
        if on:
            self._trace_task = asyncio.create_task(self._trace())

    async def _trace(self) -> None:
        n = 0
        while True:
            await asyncio.sleep(0.05)
            n += 1
            self.hub.feed(bytes([0xEF, 0xBE, n & 0xFF, 0x00, 0x10]), "modem-trace")

    # ---------------------------------------------------------------- power (used by SimPower)
    def set_power(self, on: bool) -> None:
        if on and not self.powered:
            self.powered = True
            self._boot()
        elif not on and self.powered:
            if self._boot_task:
                self._boot_task.cancel()
            self.powered = False


# `kernel thread list` with CONFIG_THREAD_STACK_INFO and CONFIG_INIT_STACKS: the system
# work queue is close to overflowing.
SIM_THREADS = (
    "Scheduler: 2 since last call\r\n"
    "Threads:\r\n"
    "*0x20000c08 shell_uart\r\n"
    "\toptions: 0x0, priority: 14 timeout: 0\r\n"
    "\tstate: queued, entry: 0x0000b1c5\r\n"
    "\tstack size 2048, unused 1272, usage 776 / 2048 (37 %)\r\n"
    "\r\n"
    " 0x20000d28 sysworkq\r\n"
    "\toptions: 0x0, priority: -1 timeout: 0\r\n"
    "\tstate: pending, entry: 0x0000c2a1\r\n"
    "\tstack size 1024, unused 96, usage 928 / 1024 (90 %)\r\n"
    "\r\n"
    " 0x20000b48 idle\r\n"
    "\toptions: 0x1, priority: 15 timeout: 0\r\n"
    "\tstate: , entry: 0x0000a0f1\r\n"
    "\tstack size 320, unused 256, usage 64 / 320 (20 %)\r\n"
)


# Replies of a registered nRF9161 on LTE-M, for the `at` shell command. "" means just OK.
SIM_AT = {
    "AT": "",
    "AT+CFUN?": "+CFUN: 1",
    "AT+CEREG?": "+CEREG: 0,1",
    "AT%XMONITOR": '%XMONITOR: 1,"Sim Telco","SIMT","24201","0A1B",7,20,"0001A2B3",123,6400,52,20,'
    '"11100000","11100000","00001000","00100001"',
    "AT%XSYSTEMMODE?": "%XSYSTEMMODE: 1,0,1,0",
    "AT+CGDCONT?": '+CGDCONT: 0,"IP","iot.example","10.160.12.34",0,0',
    "AT%XICCID": "%XICCID: 8901234567890123456",
    "AT+CGMR": "mfw_nrf91x1_2.0.2",
    "AT+CFUN=1": "",
    "AT+CFUN=0": "",
}


def _ts(seconds: float) -> str:
    ms = int(seconds * 1000)
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d},000"
