"""What the TUI shows, without Textual: the console model (ANSI state, sender tags, Zephyr
log levels, boot folding), shell-command completion and board status text.

It mirrors the dashboard's terminal in dashboard/app.js, so both read the same console the
same way. Kept free of Textual so it is unit tested on its own."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

_SGR = re.compile(r"\x1b\[([0-9;]*)m")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_OTHER_COLOUR = re.compile(r"3[0-7]|9[0-7]")
# Lines sent to the board arrive as dim notes: "[you] > cmd" and "[claude-1a2b] > cmd"
# (older daemons: "[human:Fame] > cmd" and "[agent:claude-1] > cmd").
_OLD_TAG = re.compile(r"^\[(human|agent):([^\]]*)\] > ")
_TAG = re.compile(r"^\[([^\]\s]+)\] > ")
_SRC = re.compile(r"^\[([^\]\s]+)\] ")
# Zephyr log timestamps ("[00:00:01.234,567] " or "[00012345] ") and shell prompts.
_TS = re.compile(r"^\[(\d{2}:\d{2}:\d{2}\.\d{3}(,\d{3})?|\d{8})\] ")
_PROMPT = re.compile(r"^[\w.-]+:~\$ ?")
# Zephyr marks the level even with log colours off, so <err>/<wrn> win over ANSI.
_ERR = re.compile(r"<err>|\bASSERTION FAIL|\bFATAL\b|Kernel panic|\bFAIL(ED)?\b")
_WRN = re.compile(r"<wrn>|\bWARN(ING)?\b")
_BOOT_ERR = re.compile(r"^(E: |\[ERR\])")
_BOOT_WRN = re.compile(r"^(W: |\[WRN\])")


def boot_title(text: str, in_boot: bool) -> str | None:
    """Is this a line of boot output (NSIB, MCUboot, TF-M, the Zephyr banner)? Returns its
    title ("" for a boot line without one) or None. `in_boot` says a boot block is already
    open, which lets the bootloaders' short log prefixes join it."""
    t = text.strip()
    m = re.match(r"^\*\*\* Booting (.+?) \*\*\*$", t)
    if m:
        return m.group(1).replace("Zephyr OS build ", "Zephyr OS ", 1)
    if re.match(r"^\*\*\* (Using|Booting) .*\*\*\*$", t):
        return ""
    m = re.match(r"^Booting TF-M (v\S+)", t)
    if m:
        return f"TF-M {m.group(1)}"
    if re.search(r"Starting bootloader|^Attempting to boot|^\[Sec Thread\]|^\[INF\] .*TF-M", t):
        return ""
    if in_boot and (
        not t
        or re.match(r"^[IWED]: ", t)
        or re.match(r"^\[(INF|WRN|ERR|DBG)\]", t)
        or re.match(
            r"^(Verifying signature|Hash: 0x|Firmware (signature verified|version)"
            r"|Booting \(0x|TF-M |Non-Secure system starting)",
            t,
        )
    ):
        return ""
    return None


@dataclass
class Line:
    """One console line, split into the parts the view can show or hide."""

    text: str = ""
    kind: str = ""  # "" firmware output, "note" (dim arbiter note), "you", "agent"
    level: str = ""  # "", "w" warning, "e" error
    tag: str | None = None  # "[you]" or "[claude-1a2b]" on lines someone sent
    src: str | None = None  # "[uart:app] " on the All channel
    ts: str | None = None
    prompt: str | None = None
    boot: str | None = None  # boot title ("" = untitled boot line), None = not boot output

    @property
    def bare_prompt(self) -> bool:
        return self.prompt is not None and not self.text.strip()


@dataclass
class BootBlock:
    """Consecutive boot lines, shown folded as one "Booted <title>" line."""

    lines: list[Line] = field(default_factory=list)
    title: str = ""
    level: str = ""
    open: bool = False

    def add(self, line: Line) -> None:
        self.lines.append(line)
        if line.boot:
            self.title = line.boot
        if line.level == "e":
            self.level = "e"
        elif line.level == "w" and not self.level:
            self.level = "w"

    def summary(self) -> str:
        n = len(self.lines)
        issues = {"e": ", has errors", "w": ", has warnings"}.get(self.level, "")
        head = f"Booted {self.title}" if self.title else "Booting"
        return f"{head} ({n} line{'' if n == 1 else 's'}{issues})"


Entry = Line | BootBlock


class ConsoleModel:
    """The console text as lines and boot blocks. `feed()` takes decoded text as it
    arrives; the widget asks `take_dirty()` which entries to draw again."""

    MAX_LINES = 5000
    TRIM_SLACK = 500  # trim in batches, so a full log doesn't redraw on every line

    def __init__(self, names: Iterable[str] = (), me: str | None = None):
        self.entries: list[Entry] = []
        self.partial: Line | None = None  # the current unfinished line
        self.names = set(names)  # channel names, to spot "[uart:app] " on the All channel
        self.me = me  # the human's name, for older daemons' "[human:Fame]" tags
        self._pending = ""
        self._dim = False
        self._colour = ""
        self._in_boot = False
        self._lines = 0
        self._dirty = 0

    def feed(self, text: str) -> None:
        parts = (self._pending + text).split("\n")
        self._pending = parts.pop()
        for raw in parts:
            self._add(self._parse(raw, partial=False))
        self.partial = self._parse(self._pending, partial=True) if self._pending else None
        if self._lines > self.MAX_LINES + self.TRIM_SLACK:
            self._trim()

    def note(self, text: str) -> None:
        """A dim line from the TUI itself, like the dashboard's "[dashboard] ..." notes."""
        self.feed(f"{chr(10) if self._pending else ''}\x1b[2m{text}\x1b[0m\n")

    def clear(self) -> None:
        self.entries.clear()
        self._lines = 0
        self._in_boot = False
        self._dirty = 0

    def mark_dirty(self, index: int) -> None:
        self._dirty = min(self._dirty, index)

    def take_dirty(self) -> int:
        """The first entry that changed since the last call (len(entries) if none did)."""
        d = self._dirty
        self._dirty = len(self.entries)
        return d

    # ---------------------------------------------------------------- internals
    def _add(self, line: Line) -> None:
        self._lines += 1
        if line.boot is not None:
            last = self.entries[-1] if self.entries else None
            if self._in_boot and isinstance(last, BootBlock):
                last.add(line)
                self.mark_dirty(len(self.entries) - 1)
                return
            block = BootBlock()
            block.add(line)
            self._in_boot = True
            self.mark_dirty(len(self.entries))
            self.entries.append(block)
            return
        self._in_boot = False
        self.mark_dirty(len(self.entries))
        self.entries.append(line)

    def _trim(self) -> None:
        drop = 0
        while self._lines > self.MAX_LINES and drop < len(self.entries):
            e = self.entries[drop]
            self._lines -= len(e.lines) if isinstance(e, BootBlock) else 1
            drop += 1
        del self.entries[:drop]
        self._dirty = 0

    def _parse(self, raw: str, partial: bool) -> Line:
        # Track the ANSI state we show: dim (arbiter notes) and the firmware's own red and
        # yellow. Other colours and cursor codes are dropped.
        dim, colour = self._dim, self._colour
        start = (dim, colour)
        first: tuple[bool, str] | None = None
        for m in _SGR.finditer(raw):
            for c in (m.group(1) or "0").split(";"):
                if c == "2":
                    dim = True
                elif c in ("0", ""):
                    dim, colour = False, ""
                elif c == "22":
                    dim = False
                elif c in ("31", "91"):
                    colour = "e"
                elif c in ("33", "93"):
                    colour = "w"
                elif c == "39" or _OTHER_COLOUR.fullmatch(c):
                    colour = ""
                if first is None and (colour or dim):
                    first = (dim, colour)
        if not partial:
            self._dim, self._colour = dim, colour
        shown_dim, shown_colour = first or start
        was_dim = shown_dim or start[0]
        text = _ANSI.sub("", raw).replace("\r", "")
        line = Line()

        sent: tuple[str, str, str] | None = None
        old = _OLD_TAG.match(text)
        if old:
            sent = (old.group(0), old.group(1), old.group(2))
        elif was_dim:
            tag = _TAG.match(text)
            if tag:
                sent = (tag.group(0), "human" if tag.group(1) == "you" else "agent", tag.group(1))
        if sent:
            mine = sent[1] == "human" and (sent[2] == "you" or not self.me or sent[2] == self.me)
            line.tag = "[you]" if mine else f"[{sent[2]}]"
            line.kind = "you" if mine else "agent"
            text = text[len(sent[0]) - 2 :]  # keep "> cmd"
        elif was_dim:
            line.kind = "note"

        if _ERR.search(text):
            line.level = "e"
        elif _WRN.search(text):
            line.level = "w"
        elif not sent and shown_colour:
            line.level = shown_colour

        if not sent:
            src = _SRC.match(text)
            if src and src.group(1) in self.names and src.group(1) != "all":
                line.src, text = src.group(0), text[src.end() :]
            ts = _TS.match(text)
            if ts:
                line.ts, text = ts.group(0), text[ts.end() :]
            prompt = _PROMPT.match(text)
            if prompt:
                line.prompt, text = prompt.group(0), text[prompt.end() :]
                # A log line printed right after the prompt: "uart:~$ [00:00:03.120,000] <wrn> ..."
                ts = None if line.ts else _TS.match(text)
                if ts:
                    line.ts, text = ts.group(0), text[ts.end() :]
        line.text = text

        if not partial and not sent:
            line.boot = boot_title(text, self._in_boot)
            if line.boot is not None:
                # The bootloaders mark their own errors and warnings.
                if _BOOT_ERR.match(text):
                    line.level = "e"
                elif _BOOT_WRN.match(text) and line.level != "e":
                    line.level = "w"
        return line


# -------------------------------------------------------------------- shell commands
@dataclass
class Resolved:
    node: dict[str, Any] | None
    partial: str
    level: list[dict[str, Any]] | None = None
    dynamic: bool = False


class ShellTree:
    """Completion over the shell commands found in the flashed image's ELF
    (GET /api/boards/{id}/shell), so hints work even with the firmware's own tab
    completion turned off."""

    def __init__(self, data: dict[str, Any] | None = None):
        self.data = data or {}
        self.available = bool(self.data.get("available"))
        self.commands: list[dict[str, Any]] = list(self.data.get("commands") or [])

    @property
    def count(self) -> int:
        return int(self.data.get("count") or len(self.commands))

    def resolve(self, text: str) -> Resolved:
        """Walk the typed words through the command tree."""
        words = re.split(r"\s+", text.lstrip())
        partial = words.pop()
        level: list[dict[str, Any]] = self.commands if self.available else []
        node: dict[str, Any] | None = None
        for w in words:
            if node is not None and node.get("dynamic"):
                return Resolved(node, partial, dynamic=True)
            nxt = next((c for c in level if c.get("name") == w), None)
            if nxt is None:
                return Resolved(None, partial)
            node = nxt
            level = list(nxt.get("subcommands") or [])
        return Resolved(node, partial, level, bool(node and node.get("dynamic")))

    def options(self, text: str, forced: bool = False) -> list[dict[str, Any]]:
        """Commands that complete the last word. An empty line lists nothing until Tab
        (`forced`), so Up still recalls history."""
        if not self.available or not (text.strip() or forced):
            return []
        r = self.resolve(text)
        if r.level is None or r.dynamic:
            return []
        return [
            c
            for c in r.level
            if str(c.get("name", "")).startswith(r.partial) and c.get("name") != r.partial
        ]

    def accept(self, text: str, name: str) -> str:
        cut = len(text) - len(self.resolve(text).partial)
        return f"{text[:cut]}{name} "

    def help_for(self, text: str) -> str:
        if not self.available or not text.strip():
            return ""
        r = self.resolve(text)
        exact = next((c for c in r.level or [] if c.get("name") == r.partial), None)
        node = exact or r.node
        if node and node.get("help"):
            return f"{node['name']}  {str(node['help']).splitlines()[0]}"
        if r.dynamic and r.node:
            return f"{r.node['name']} takes values only the running firmware knows, so type them freely."
        return ""


# -------------------------------------------------------------------- board status
STATUS = {
    "AVAILABLE": "free",
    "LEASED": "in use",
    "PAUSED": "paused",
    "HUMAN": "held by human",
    "MAINTENANCE": "maintenance",
    "OFFLINE": "offline",
    "NEEDS_RECOVER": "needs attention",
}
OP_WORDS = {"flash": "flashing", "test": "testing", "recover": "recovering", "measure": "measuring"}


def who(s: Any) -> str:
    """'agent:claude: lte test' -> 'claude: lte test'; 'human:Fame' -> 'Fame'."""
    return re.sub(r"^(agent|human):", "", str(s or ""))


def dur(s: float) -> str:
    s = max(0, round(s))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {(s % 3600) // 60:02d}m"


def board_status(b: dict[str, Any]) -> tuple[str, str]:
    """Short status text and its level ("", "warn" or "err")."""
    lease = b.get("lease") or None
    op = b.get("op") or None
    text = STATUS.get(b["state"], str(b["state"]).lower())
    level = ""
    if b["state"] == "LEASED" and op and op.get("running"):
        text = OP_WORDS.get(op.get("kind", ""), op.get("kind", ""))
    if b["state"] == "HUMAN":
        text = f"held by {who(b.get('held_by')) or 'human'}"
    if lease and lease.get("state") == "PAUSING":
        text = f"pausing (finishing {op['kind'] if op else 'operation'})"
    if lease and lease.get("state") == "EXPIRING":
        text, level = "agent not responding", "warn"
    if b["state"] in ("OFFLINE", "NEEDS_RECOVER"):
        level = "err"
    if b.get("supported") is False:
        level = level or "warn"
    return text, level


def lease_left(b: dict[str, Any], now: float) -> str | None:
    lease = b.get("lease")
    if not lease or not lease.get("expires_at"):
        return None
    if lease.get("state") in ("PAUSED", "PAUSING"):
        return "on hold"
    if lease.get("state") == "EXPIRING" and lease.get("grace_until"):
        return f"ends in {dur(lease['grace_until'] - now)}"
    return f"{dur(lease['expires_at'] - now)} left"


def queue_for(state: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    """Queue entries that could get this board."""
    out = []
    for e in state.get("queue") or []:
        sel = e.get("selector") or {}
        if sel.get("board_id") and sel["board_id"] != b["id"]:
            continue
        plat = sel.get("platform")
        if plat and not (b["platform"] == plat or b["platform"].split("/")[0] == plat):
            continue
        if all(t in (b.get("tags") or []) for t in sel.get("tags") or []):
            out.append(e)
    return out


def channel_names(b: dict[str, Any]) -> list[str]:
    names = ["all"]
    for n in [
        *((b.get("console") or {}).get("sources") or []),
        *((b.get("console_channels") or {}).get("ends") or {}),
    ]:
        if n not in names:
            names.append(n)
    return names
