"""Crash triage: spot Zephyr fatal errors on a board's console and turn them into a short,
symbolised report an agent can act on (design doc §9, "faults in the console get
symbolised automatically").

A `CrashWatcher` per board sees every byte the console sources feed into the hub. When a
line looks like the start of a fatal error (a `***** BUS FAULT *****` banner, an
`ASSERTION FAIL`, `>>> ZEPHYR FATAL ERROR`, TF-M's `FATAL ERROR:`), it collects the block
with the lines before it, and hands a `Crash` to the service once the block ends
("Halting system", "Resetting system", the next boot banner, or a short quiet spell).

`symbolize` then maps pc, lr and any call-trace addresses to `function file:line` with the
toolchain's addr2line (found through the build's CMakeCache), or, without one, to
`function+offset` from the ELF's symbol table."""

from __future__ import annotations

import asyncio
import re
import secrets
import shutil
import subprocess
import sys
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .console.detect import image_dirs, parse_kconfig
from .elf import EM_386, EM_AARCH64, EM_ARM, EM_RISCV, EM_X86_64, Elf, ElfError
from .workspace import cache_value

CONTEXT_LINES = 30  # lines kept from before the crash
MAX_LINES = 120  # lines kept from the crash block itself
QUIET_S = 0.75  # a block with no end marker ends after this long without output
REPEAT_WINDOW_S = 120.0  # the same crash again within this window counts as a repeat

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# "[00:00:05.000,000] <err> os: " or "<err> os: ", as printed by Zephyr's log subsystem
_LOG_PREFIX = re.compile(r"^(?:\[[\d:.,\s]+\]\s*)?<\w+>\s+[\w.\-/]+:\s?")

_BANNER = re.compile(r"\*{3,}\s*([A-Z][A-Z /_-]*?(?:FAULT|EVENT|ERROR))\s*\*{3,}")
_ASSERT = re.compile(r"ASSERTION FAIL \[(?P<expr>.*)\] @ (?P<file>\S+?):(?P<line>\d+)")
_FATAL = re.compile(r">>> ZEPHYR FATAL ERROR (?P<code>\d+): (?P<reason>.+?)(?: on CPU \d+)?\s*$")
_TFM = re.compile(r"^\s*(?:FATAL ERROR: (?P<what>\w+)|Oops\.\.\. (?P<oops>.+))")
_THREAD = re.compile(r"Current thread: (?P<addr>0x[0-9a-fA-F]+|\(nil\)|\S+)(?: \((?P<name>.*)\))?")
_END = re.compile(r"Halting system|Resetting system|Rebooting|System halted")
_BOOT = re.compile(r"\*\*\* Booting |Booting Zephyr OS")
_REG = re.compile(
    r"\b(r\d{1,2}|ip|lr|sp|pc|xpsr|fpscr|ra|psp|msp)(?:/[a-z]+\d*)?:\s*(0x[0-9a-fA-F]+)"
)
_PC = re.compile(r"Faulting instruction address \(r15/pc\):\s*(0x[0-9a-fA-F]+)")
_TFM_REG = re.compile(r"^\s*(PC|LR|SP|R\d{1,2}):\s*(0x[0-9a-fA-F]+)")
_FAULT_ADDR = re.compile(r"\b(MMFAR|BFAR|SFAR|FAR|MTVAL|ELR) ?(?:Address)?:\s*(0x[0-9a-fA-F]+)")
_CALL_TRACE = re.compile(r"call trace|backtrace", re.IGNORECASE)
_TRACE_ADDR = re.compile(r"\b(?:lr|ra|pc|ip|elr):\s*(0x[0-9a-fA-F]+)")
_COREDUMP = re.compile(r"#CD:")

_REASONS = {
    0: "CPU exception",
    1: "spurious interrupt",
    2: "stack overflow",
    3: "kernel oops",
    4: "kernel panic",
}


def clean(line: str) -> str:
    """A console line without colours, carriage returns or Zephyr's log prefix."""
    return _LOG_PREFIX.sub("", _ANSI.sub("", line).rstrip("\r\n").replace("\r", ""))


def starts_crash(line: str) -> bool:
    return bool(
        _BANNER.search(line) or _ASSERT.search(line) or _FATAL.search(line) or _TFM.match(line)
    )


# ---------------------------------------------------------------------------- report
@dataclass
class Location:
    function: str | None = None
    file: str | None = None
    line: int | None = None
    inlined_by: list[str] = field(default_factory=list)

    def text(self) -> str:
        where = f"{self.file}:{self.line}" if self.file and self.line else (self.file or "")
        fn = (
            f"{self.function}()"
            if self.function and not self.function.endswith(")") and "+0x" not in self.function
            else self.function
        )
        return " at ".join(x for x in (fn, where) if x) or "??"


@dataclass
class Crash:
    id: str
    board: str
    channel: str
    at: float
    cursor: int  # the channel's cursor where the crash block starts
    kind: str = "fatal"  # fault | assert | stack_overflow | oops | panic | secure_fault | fatal
    title: str = ""
    reason: str | None = None
    reason_code: int | None = None
    details: list[str] = field(default_factory=list)
    registers: dict[str, str] = field(default_factory=dict)
    fault_address: dict[str, str] = field(default_factory=dict)
    thread: str | None = None
    thread_addr: str | None = None
    assertion: dict[str, Any] | None = None
    call_trace: list[str] = field(default_factory=list)
    ended_by: str | None = None  # halted | reset | reboot | quiet | truncated
    context: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    coredump: list[str] = field(default_factory=list)
    image: dict[str, Any] | None = None
    symbols: dict[str, Any] = field(default_factory=dict)
    symbolized_with: str | None = None
    hints: list[str] = field(default_factory=list)
    repeats: int = 1
    last_at: float = 0.0

    @property
    def signature(self) -> tuple[Any, ...]:
        return (
            self.channel,
            self.kind,
            self.reason_code,
            self.registers.get("pc"),
            self.registers.get("lr"),
            None if self.assertion is None else (self.assertion["file"], self.assertion["line"]),
        )

    def where(self) -> str | None:
        """Best single source location: the assert, else the faulting pc."""
        if self.assertion:
            return f"{self.assertion['file']}:{self.assertion['line']}"
        pc = self.symbols.get("pc")
        if pc:
            return str(pc["text"])
        if "pc" in self.registers:
            return f"pc {self.registers['pc']}"
        return None

    def summary(self) -> str:
        parts = [self.title or "fatal error"]
        if self.reason and self.reason.lower() not in parts[0].lower():
            parts[0] += f" ({self.reason})"
        if self.thread:
            parts.append(f"in thread {self.thread}")
        w = self.where()
        if w:
            parts.append(f"at {w}")
        s = " ".join(parts)
        if self.repeats > 1:
            s += f" [{self.repeats} times]"
        return s

    def brief(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "at": self.at,
            "channel": self.channel,
            "kind": self.kind,
            "summary": self.summary(),
            "where": self.where(),
            "repeats": self.repeats,
        }

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["summary"] = self.summary()
        d["where"] = self.where()
        return d


def parse_crash(c: Crash) -> Crash:
    """Fill in kind, title, registers, thread and assertion from the collected lines."""
    in_trace = False
    for raw in c.lines:
        line = clean(raw)
        if m := _BANNER.search(line):
            if not c.title or c.kind == "fatal":
                c.title = m.group(1).strip()
                c.kind = "secure_fault" if "SECURE" in c.title else "fault"
            continue
        if m := _ASSERT.search(line):
            c.assertion = {
                "expr": m["expr"],
                "file": m["file"],
                "line": int(m["line"]),
                "message": None,
            }
            c.kind, c.title = "assert", f"ASSERTION FAIL [{m['expr']}]"
            continue
        if c.assertion and c.assertion["message"] is None and raw.startswith(("\t", "    ")):
            c.assertion["message"] = line.strip()
            continue
        if m := _FATAL.search(line):
            c.reason_code = int(m["code"])
            c.reason = m["reason"].strip()
            if c.kind in ("fatal", "fault") and c.reason_code == 2:
                c.kind = "stack_overflow"
            elif c.kind == "fatal":
                c.kind = {3: "oops", 4: "panic"}.get(c.reason_code, "fatal")
            if not c.title:
                c.title = f"ZEPHYR FATAL ERROR {c.reason_code}"
            continue
        if m := _TFM.match(line):
            if m["what"]:
                c.title = c.title or f"TF-M {m['what']}"
                c.kind = "secure_fault" if "Secure" in m["what"] else c.kind
            elif not c.title:
                c.title = f"TF-M: {m['oops'].strip()}"
            continue
        if m := _THREAD.search(line):
            c.thread_addr = m["addr"]
            c.thread = m["name"] or None
            continue
        if m := _PC.search(line):
            c.registers["pc"] = _hex(m.group(1))
            continue
        if m := _FAULT_ADDR.search(line):
            c.fault_address[m.group(1)] = _hex(m.group(2))
        if _CALL_TRACE.search(line):
            in_trace = True
            continue
        if in_trace and (addrs := _TRACE_ADDR.findall(line)):
            c.call_trace.extend(_hex(a) for a in addrs[-1:])
            continue
        if m := _TFM_REG.match(line):
            c.registers.setdefault(m.group(1).lower(), _hex(m.group(2)))
            continue
        regs = _REG.findall(line)
        if regs:
            for name, value in regs:
                c.registers.setdefault(_reg_name(name), _hex(value))
            continue
        text = line.strip()
        if text and not _COREDUMP.search(text) and len(c.details) < 10 and not _END.search(text):
            c.details.append(text)
    if not c.title:
        c.title = "fatal error"
    return c


def _reg_name(name: str) -> str:
    return {"r14": "lr", "r15": "pc", "r13": "sp", "r12": "ip"}.get(name, name)


def _hex(s: str) -> str:
    return f"0x{int(s, 16):08x}"


# ---------------------------------------------------------------------------- watcher
class CrashWatcher:
    """Assembles console bytes into lines per channel and collects crash blocks."""

    def __init__(
        self,
        board_id: str,
        on_crash: Callable[[Crash], None],
        clock: Callable[[], float] = time.time,
        quiet_s: float = QUIET_S,
    ):
        self.board_id = board_id
        self.on_crash = on_crash
        self.clock = clock
        self.quiet_s = quiet_s
        self.ignore: set[str] = {"modem-trace"}
        self._partial: dict[str, tuple[int, bytes]] = {}  # channel -> (cursor, unfinished line)
        self._cursor: dict[str, int] = {}  # bytes seen per channel (matches the hub's cursors)
        self._recent: dict[str, deque[str]] = {}
        self._open: dict[str, Crash] = {}
        self._timers: dict[str, asyncio.TimerHandle] = {}

    def feed(self, channel: str, data: bytes, end: int | None = None) -> None:
        """Bytes from one channel; `end` is the channel's cursor after them, if known."""
        if channel in self.ignore or not data:
            return
        start = end - len(data) if end is not None else self._cursor.get(channel, 0)
        self._cursor[channel] = start + len(data)
        pos, buf = self._partial.pop(channel, (start, b""))
        buf += data
        *lines, tail = buf.split(b"\n")
        for line in lines:
            self._line(channel, line.decode(errors="replace"), pos)
            pos += len(line) + 1
        if tail:
            self._partial[channel] = (pos, tail)
        if channel in self._open:
            self._arm(channel)

    def _line(self, channel: str, raw: str, cursor: int) -> None:
        line = clean(raw)
        crash = self._open.get(channel)
        if crash is not None:
            if _BOOT.search(line):
                self._close(channel, "reboot")
            elif _COREDUMP.search(line):
                crash.coredump.append(line[line.find("#CD:") :])
                return
            else:
                if len(crash.lines) < MAX_LINES:
                    crash.lines.append(raw.rstrip("\r"))
                if m := _END.search(line):
                    word = m.group(0)
                    self._close(channel, "halted" if "alt" in word else "reset")
                elif len(crash.lines) >= MAX_LINES and not crash.coredump:
                    self._close(channel, "truncated")
                return
        recent = self._recent.setdefault(channel, deque(maxlen=CONTEXT_LINES))
        if starts_crash(line):
            self._open[channel] = Crash(
                id="cr-" + secrets.token_hex(3),
                board=self.board_id,
                channel=channel,
                at=self.clock(),
                cursor=cursor,
                context=list(recent),
                lines=[raw.rstrip("\r")],
            )
            recent.clear()
            self._arm(channel)
            return
        if line.strip():
            recent.append(raw.rstrip("\r"))

    def _arm(self, channel: str) -> None:
        t = self._timers.pop(channel, None)
        if t is not None:
            t.cancel()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._timers[channel] = loop.call_later(self.quiet_s, self._close, channel, "quiet")

    def _close(self, channel: str, why: str) -> None:
        t = self._timers.pop(channel, None)
        if t is not None:
            t.cancel()
        crash = self._open.pop(channel, None)
        if crash is None:
            return
        _pos, rest = self._partial.pop(channel, (0, b""))
        if rest.strip() and why == "quiet" and len(crash.lines) < MAX_LINES:
            crash.lines.append(rest.decode(errors="replace").rstrip("\r"))
        crash.ended_by = why
        crash.last_at = crash.at
        self.on_crash(parse_crash(crash))

    def flush(self) -> None:
        """End any open crash block now (used before reading the last crash)."""
        for channel in list(self._open):
            self._close(channel, "quiet")


# ---------------------------------------------------------------------------- symbols
def image_info(build_dir: Path) -> dict[str, Any] | None:
    """The default image of a build: its ELF and build directory."""
    dirs = image_dirs(Path(build_dir))
    if not dirs:
        return None
    name, d = dirs[0]
    elf = d / "zephyr" / "zephyr.elf"
    if not elf.exists():
        exe = d / "zephyr" / "zephyr.exe"  # native_sim
        elf = exe if exe.exists() else elf
    return {"build_dir": str(build_dir), "image": name, "image_dir": str(d), "elf": str(elf)}


_PREFIXES = {
    EM_ARM: ["arm-zephyr-eabi-", "arm-none-eabi-"],
    EM_AARCH64: ["aarch64-zephyr-elf-"],
    EM_RISCV: ["riscv64-zephyr-elf-"],
}


def find_addr2line(image_dir: Path | None, machine: int | None) -> str | None:
    """The toolchain's addr2line: from the build's CMakeCache (Zephyr records CMAKE_ADDR2LINE,
    or its siblings CMAKE_OBJDUMP / CMAKE_GDB / CMAKE_C_COMPILER), then from PATH."""
    exe = ".exe" if sys.platform == "win32" else ""
    if image_dir is not None:
        cache = image_dir / "CMakeCache.txt"
        found = cache_value(cache, "CMAKE_ADDR2LINE")
        if found and Path(found).exists():
            return found
        for key, tool in (
            ("CMAKE_OBJDUMP", "objdump"),
            ("CMAKE_GDB", "gdb"),
            ("CMAKE_C_COMPILER", "gcc"),
        ):
            value = cache_value(cache, key)
            if not value:
                continue
            p = Path(value)
            stem = p.name.removesuffix(".exe")
            if stem.endswith(tool):
                cand = p.with_name(stem[: -len(tool)] + "addr2line" + exe)
                if cand.exists():
                    return str(cand)
    for prefix in _PREFIXES.get(machine or 0, []):
        if found := shutil.which(prefix + "addr2line"):
            return found
    if found := shutil.which("llvm-addr2line"):
        return found
    if machine in (EM_X86_64, EM_386) and (found := shutil.which("addr2line")):
        return found
    return None


def run_addr2line(tool: str, elf: Path, addrs: list[int]) -> dict[int, Location]:
    """addr2line -f -i -C -a: per address the function and file:line, innermost first."""
    proc = subprocess.run(
        [tool, "-e", str(elf), "-f", "-i", "-C", "-a", *(f"0x{a:x}" for a in addrs)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    out: dict[int, Location] = {}
    cur: int | None = None
    pending: str | None = None
    for raw in proc.stdout.splitlines():
        line = raw.strip()
        if re.fullmatch(r"0x[0-9a-fA-F]+", line):
            cur, pending = int(line, 16), None
            continue
        if cur is None:
            continue
        if pending is None:
            pending = line
            continue
        loc = out.get(cur)
        func = None if pending == "??" else pending
        file, ln = _file_line(line)
        if loc is None:
            out[cur] = Location(func, file, ln)
        else:
            loc.inlined_by.append(Location(func, file, ln).text())
        pending = None
    return out


def _file_line(text: str) -> tuple[str | None, int | None]:
    text = re.sub(r"\s+\(discriminator \d+\)$", "", text)
    m = re.match(r"(.*):(\d+|\?)$", text)
    if not m or m.group(1) == "??":
        return None, None
    return _short_path(m.group(1)), int(m.group(2)) if m.group(2).isdigit() else None


def _short_path(path: str) -> str:
    """Trim a long absolute path to the part from a well-known workspace folder on."""
    norm = path.replace("\\", "/")
    for marker in ("/zephyr/", "/nrf/", "/modules/", "/nrfxlib/", "/bootloader/", "/src/", "/lib/"):
        i = norm.find(marker)
        if i > 0:
            return norm[i + 1 :]
    return norm


def symbolize(crash: Crash, image: dict[str, Any] | None) -> None:
    """Add `function file:line` for pc, lr and the call trace, plus hints, in place."""
    crash.image = image
    if image is None:
        crash.hints.append(
            "arbiter doesn't know which ELF is on the board (it was not flashed through arbiter "
            "since the daemon started), so addresses are not symbolised. Flash with the flash tool."
        )
        return
    _config_hints(crash, Path(image["image_dir"]))
    elf_path = Path(image["elf"])
    try:
        elf = Elf.load(elf_path)
    except ElfError as e:
        crash.hints.append(f"Cannot read {elf_path}: {e}")
        return
    arm = elf.machine == EM_ARM
    wanted: dict[str, int] = {}
    for reg in ("pc", "lr"):
        if reg in crash.registers:
            value = int(crash.registers[reg], 16)
            if arm:
                value &= ~1
            if reg == "lr" and value:
                value -= 1  # a return address: look up the call instruction before it
            wanted[reg] = value
    for i, a in enumerate(crash.call_trace):
        value = int(a, 16) & (~1 if arm else ~0)
        wanted[f"#{i}"] = max(0, value - 1) if i else value
    for name, addr in crash.fault_address.items():
        wanted[name] = int(addr, 16)
    if not wanted:
        return
    found: dict[int, Location] = {}
    tool = find_addr2line(Path(image["image_dir"]), elf.machine)
    if tool:
        try:
            found = run_addr2line(tool, elf_path, sorted(set(wanted.values())))
            crash.symbolized_with = "addr2line"
        except (OSError, subprocess.SubprocessError) as e:
            crash.hints.append(f"addr2line failed ({e}); fell back to the symbol table.")
    for name, value in wanted.items():
        loc = found.get(value)
        if loc is None or (loc.function is None and loc.file is None):
            fn = elf.function_at(value)
            if fn is None:
                continue
            loc = Location(f"{fn[0]}+0x{fn[1]:x}")
            crash.symbolized_with = crash.symbolized_with or "symtab"
        entry = {"address": f"0x{value:08x}", "text": loc.text(), **asdict(loc)}
        if name in crash.fault_address:
            crash.symbols.setdefault("fault_address", {})[name] = entry
        elif name.startswith("#"):
            crash.symbols.setdefault("call_trace", []).append(entry)
        else:
            crash.symbols[name] = entry
    if crash.symbolized_with == "symtab" and not tool:
        crash.hints.append(
            "No addr2line found (Zephyr SDK or llvm-addr2line), so only function+offset is shown."
        )


def _config_hints(crash: Crash, image_dir: Path) -> None:
    try:
        cfg = parse_kconfig(image_dir / "zephyr" / ".config")
    except OSError:
        return
    if cfg.get("CONFIG_LOG_MODE_DEFERRED") == "y":
        crash.hints.append(
            "Logging is deferred, so log lines from just before the crash may be missing. "
            "Build with CONFIG_LOG_MODE_IMMEDIATE=y while debugging."
        )
    if crash.kind == "assert" and cfg.get("CONFIG_ASSERT_VERBOSE") != "y":
        crash.hints.append("CONFIG_ASSERT_VERBOSE=y adds the assert's message.")
    if crash.kind == "stack_overflow" and cfg.get("CONFIG_THREAD_ANALYZER") != "y":
        crash.hints.append(
            "CONFIG_THREAD_ANALYZER=y with CONFIG_THREAD_ANALYZER_AUTO=y prints each thread's "
            "stack use, which shows how much to grow the stack."
        )
    if (
        crash.kind in ("fault", "secure_fault", "stack_overflow")
        and cfg.get("CONFIG_DEBUG_COREDUMP") != "y"
    ):
        crash.hints.append(
            "For a full backtrace with locals, build with CONFIG_DEBUG_COREDUMP=y and "
            "CONFIG_DEBUG_COREDUMP_BACKEND_LOGGING=y."
        )
