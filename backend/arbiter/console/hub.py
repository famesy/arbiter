"""ConsoleHub: one per board. Owns the console sources (UART ports, RTT, the
simulator, a native_sim process) and keeps each one as its own named channel
(design doc §7, "several channels at once"):

    uart:app     the application UART (VCOM0 on Nordic DKs)
    uart:tfm     TF-M's secure UART, or any other aux port (uart:<name>)
    rtt          SEGGER RTT up-buffer 0
    stdout       a native_sim process's own stdout (pty mode)
    modem-trace  binary; logged, never shown

Every channel has its own ring buffer addressed by absolute byte cursors and its
own log file. The *primary* channel ("console") is the one the firmware's
console goes to. The virtual channel "all" interleaves the others in arrival
order with a per-line `[name]` prefix (leaving out uart:tfm and binary channels);
the dashboard terminal shows it. Annotations from arbiter go to the primary
channel and to "all"."""

from __future__ import annotations

import asyncio
import contextlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Protocol

from ..errors import ArbiterError

PRIMARY = "console"
ALL = "all"
ANY = "any"
NOT_IN_ALL = {"uart:tfm", "modem-trace"}
BINARY = {"modem-trace"}
WRITE_ORDER = ("uart:app", "rtt")


class ConsoleSource(Protocol):
    name: str
    writable: bool

    async def start(self, hub: ConsoleHub) -> None: ...
    async def stop(self) -> None: ...
    async def write(self, data: bytes) -> None: ...


@dataclass
class Channel:
    name: str
    capacity: int
    buf: bytearray = field(default_factory=bytearray)
    start: int = 0  # absolute cursor of buf[0]
    at_line_start: bool = True
    log: IO[bytes] | None = None
    subs: set[asyncio.Queue[bytes]] = field(default_factory=set)

    @property
    def end(self) -> int:
        return self.start + len(self.buf)

    def append(self, data: bytes) -> None:
        self.buf += data
        if len(self.buf) > self.capacity:
            cut = len(self.buf) - self.capacity
            del self.buf[:cut]
            self.start += cut
        self.at_line_start = data.endswith(b"\n")
        if self.log is not None:
            with contextlib.suppress(OSError):
                self.log.write(data)
        for q in list(self.subs):
            if q.qsize() < 1000:
                q.put_nowait(data)

    def read(self, cursor: int | None, max_bytes: int) -> tuple[bytes, int, int]:
        if cursor is None or cursor < 0:
            cursor = max(self.start, self.end - max_bytes)
        dropped = max(0, self.start - cursor)
        cursor = max(cursor, self.start)
        off = cursor - self.start
        data = bytes(self.buf[off : off + max_bytes])
        return data, cursor + len(data), dropped

    def since(self, cursor: int) -> bytes:
        return bytes(self.buf[max(cursor, self.start) - self.start :])


class ConsoleHub:
    def __init__(self, board_id: str, log_dir: Path | None = None, capacity: int = 1 << 20):
        self.board_id = board_id
        self.capacity = capacity
        self.log_dir = log_dir
        if log_dir:
            log_dir.mkdir(parents=True, exist_ok=True)
        self.channels: dict[str, Channel] = {}
        self.sources: dict[str, ConsoleSource] = {}
        self.primary = "uart:app"
        self.lent: str | None = None
        self._changed = asyncio.Event()
        self._all = self._channel(ALL)

    # ------------------------------------------------------------- channels
    def _channel(self, name: str) -> Channel:
        ch = self.channels.get(name)
        if ch is None:
            ch = Channel(name, self.capacity)
            if self.log_dir:
                fname = (
                    f"console-{self.board_id}.log"
                    if name == ALL
                    else f"console-{self.board_id}-{name.replace(':', '-')}.log"
                )
                ch.log = (self.log_dir / fname).open("ab", buffering=0)
            self.channels[name] = ch
        return ch

    def resolve(self, channel: str | None) -> str:
        """Map "console"/None to the primary channel; check the name exists."""
        if channel in (None, "", PRIMARY):
            return self.primary
        if channel == ALL or channel in self.channels:
            return channel
        if channel == "uart" and "uart:app" in self.channels:
            return "uart:app"
        raise ArbiterError(
            "BAD_REQUEST",
            f"no console channel {channel!r} on {self.board_id}",
            channels=self.channel_names(),
        )

    def resolve_many(self, channel: str | list[str] | None) -> list[str]:
        if channel == ANY:
            return [n for n in self.channels if n != ALL and n not in BINARY] or [self.primary]
        if isinstance(channel, list):
            return [self.resolve(c) for c in channel]
        return [self.resolve(channel)]

    def channel_names(self) -> list[str]:
        return sorted(n for n in self.channels if n != ALL)

    def set_primary(self, name: str) -> None:
        self.primary = name
        self._channel(name)

    def end(self, channel: str | None = None) -> int:
        name = self.resolve(channel) if channel not in (None, "", PRIMARY) else self.primary
        ch = self.channels.get(name)
        return ch.end if ch else 0

    def ends(self) -> dict[str, int]:
        return {n: c.end for n, c in self.channels.items()}

    def new_lines(self, cursors: dict[str, int], exclude: set[str]) -> dict[str, int]:
        """Lines written to each other channel since the given cursors (for "also active" hints)."""
        out = {}
        for n, ch in self.channels.items():
            if n in exclude or n == ALL or n in BINARY:
                continue
            count = ch.since(cursors.get(n, 0)).count(b"\n")
            if count:
                out[n] = count
        return out

    # --------------------------------------------------------------- input
    def feed(self, data: bytes, source: str) -> None:
        """Called by sources (on the event loop) with bytes from the device."""
        if not data:
            return
        self._channel(source).append(data)
        if source not in NOT_IN_ALL and source not in BINARY:
            self._all.append(self._tag(data, source))
        self._wake()

    def annotate(self, text: str) -> None:
        """Out-of-band note, e.g. "[agent:claude-1] > help", shown dim in terminals."""
        line = f"\x1b[2m{text}\x1b[0m\n".encode()
        for ch in (self._channel(self.primary), self._all):
            ch.append((b"" if ch.at_line_start else b"\n") + line)
        self._wake()

    def _tag(self, data: bytes, source: str) -> bytes:
        # Prefix lines only when "all" mixes several channels. Attached sources count even
        # before they have produced output, so a board's first lines are tagged too.
        shown = {n for n in (*self.channels, *self.sources) if n not in (ALL, *NOT_IN_ALL, *BINARY)}
        if len(shown) <= 1:
            return data
        out = bytearray()
        for chunk in data.splitlines(keepends=True):
            if self._all.at_line_start:
                out += f"[{source}] ".encode()
            out += chunk
            self._all.at_line_start = chunk.endswith(b"\n")
        return bytes(out)

    def _wake(self) -> None:
        self._changed.set()
        self._changed = asyncio.Event()

    # --------------------------------------------------------------- reading
    def read(
        self, cursor: int | None, max_bytes: int = 4096, channel: str | None = None
    ) -> tuple[bytes, int, int]:
        """(data, next_cursor, dropped_bytes) from one channel; cursor=None reads the newest max_bytes."""
        name = self.resolve(channel)
        ch = self.channels.get(name)
        if ch is None:
            return b"", 0, 0
        return ch.read(cursor, max_bytes)

    # -------------------------------------------------------------- output
    async def write(self, data: bytes, who: str, channel: str | None = None) -> None:
        src = self._writable(channel)
        shown = data.decode(errors="replace").rstrip("\r\n")
        self.annotate(
            f"[{who}] > {shown}" + (f"  ({src.name})" if src.name != self.primary else "")
        )
        await src.write(data)

    def _writable(self, channel: str | None) -> ConsoleSource:
        if self.lent:
            raise ArbiterError("BOARD_BUSY", f"console is lent to {self.lent}")
        if channel not in (None, "", PRIMARY):
            name = self.resolve(channel)
            src = self.sources.get(name)
            if src is None or not getattr(src, "writable", True):
                raise ArbiterError("NOT_SUPPORTED", f"channel {name} cannot be written to")
            return src
        for name in (self.primary, *WRITE_ORDER):
            src = self.sources.get(name)
            if src is not None and getattr(src, "writable", True):
                return src
        for src in self.sources.values():
            if getattr(src, "writable", True):
                return src
        raise ArbiterError("NOT_SUPPORTED", "no writable console attached to this board")

    # --------------------------------------------------------------- expect
    async def expect(
        self,
        pattern: str,
        timeout_s: float,
        since: dict[str, int] | int,
        channels: list[str] | None = None,
    ) -> dict[str, Any]:
        """Wait until `pattern` matches on any of `channels` (default: primary), searching
        each from its cursor in `since`. Offsets map 1:1 to bytes (latin-1 view)."""
        try:
            rx = re.compile(pattern, re.MULTILINE)
        except re.error as e:
            raise ArbiterError("BAD_REQUEST", f"bad regex: {e}") from None
        names = channels or [self.primary]
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while True:
            ev = self._changed
            for name in names:
                ch = self.channels.get(name)
                if ch is None:
                    continue
                start = max(since.get(name, 0) if isinstance(since, dict) else since, ch.start)
                raw = ch.since(start)
                m = rx.search(raw.decode("latin-1"))
                if m:
                    return {
                        "matched": True,
                        "channel": name,
                        "match": _u(raw[m.start() : m.end()]),
                        "groups": [
                            _u(g.encode("latin-1")) if g is not None else None for g in m.groups()
                        ],
                        "context_before": _u(raw[: m.start()]).splitlines()[-5:],
                        "cursor": start + m.end(),
                        "match_start": start + m.start(),
                    }
            remaining = deadline - loop.time()
            if remaining <= 0:
                tails = {}
                for name in names:
                    ch = self.channels.get(name)
                    if ch is not None:
                        start = since.get(name, 0) if isinstance(since, dict) else since
                        tails[name] = _u(ch.since(start)).splitlines()[-15:]
                out: dict[str, Any] = {"matched": False, "timeout_s": timeout_s}
                if len(names) == 1:
                    out["tail"] = tails.get(names[0], [])
                else:
                    out["tails"] = tails
                return out
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(ev.wait(), remaining)

    # ---------------------------------------------------------- subscribers
    def subscribe(self, channel: str | None = ALL) -> asyncio.Queue[bytes]:
        q: asyncio.Queue[bytes] = asyncio.Queue()
        self._channel(self.resolve(channel) if channel != ALL else ALL).subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[bytes]) -> None:
        for ch in self.channels.values():
            ch.subs.discard(q)

    # -------------------------------------------------------------- sources
    async def attach(self, source: ConsoleSource) -> None:
        if source.name in self.sources:
            await self.detach(source.name)
        self.sources[source.name] = source
        self._channel(source.name)
        await source.start(self)

    async def detach(self, name: str) -> ConsoleSource | None:
        src = self.sources.pop(name, None)
        if src is not None:
            await src.stop()
        return src

    async def detach_all(self) -> None:
        for name in list(self.sources):
            await self.detach(name)

    def source_names(self) -> list[str]:
        return sorted(self.sources)

    async def close(self) -> None:
        await self.detach_all()
        for ch in self.channels.values():
            if ch.log is not None:
                ch.log.close()
                ch.log = None


_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _u(b: bytes) -> str:
    return _ANSI.sub("", b.decode(errors="replace"))
