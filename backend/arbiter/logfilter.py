"""Filter Zephyr log output by level, module and regex, so an agent reads the lines that
matter instead of pages of <dbg> noise.

Zephyr's log subsystem prints `[00:00:05.000,000] <err> module: message`; the level tag is
there even with colours off. Lines without a level tag (printk, shell output, crash dumps)
are not log lines: a level or module filter drops them, a regex filter alone keeps them
when they match."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from typing import Any

LEVELS = {"err": 1, "wrn": 2, "inf": 3, "dbg": 4}
ALIASES = {"error": "err", "warn": "wrn", "warning": "wrn", "info": "inf", "debug": "dbg"}
LOG_RX = re.compile(r"<(err|wrn|inf|dbg)> ([^\s:]+):")
ANSI_RX = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


@dataclass
class LogFilter:
    level: int | None = None
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    grep: re.Pattern[str] | None = None

    @classmethod
    def make(
        cls, level: str | None = None, module: str | None = None, grep: str | None = None
    ) -> LogFilter | None:
        """None when nothing is filtered. Raises ValueError on a bad level or regex."""
        if not (level or module or grep):
            return None
        f = cls()
        if level:
            key = ALIASES.get(level.lower(), level.lower())
            if key not in LEVELS:
                raise ValueError(f"level is one of {', '.join(LEVELS)}, not {level!r}")
            f.level = LEVELS[key]
        for raw in (module or "").split(","):
            part = raw.strip()
            if part.startswith(("-", "!")):
                f.exclude.append(part[1:])
            elif part:
                f.include.append(part)
        if grep:
            try:
                f.grep = re.compile(grep)
            except re.error as e:
                raise ValueError(f"bad regex: {e}") from None
        return f

    def keep(self, line: str) -> bool:
        plain = ANSI_RX.sub("", line)
        m = LOG_RX.search(plain)
        if self.level is not None or self.include or self.exclude:
            if not m:
                return False
            if self.level is not None and LEVELS[m.group(1)] > self.level:
                return False
            mod = m.group(2)
            if self.include and not any(fnmatch.fnmatchcase(mod, p) for p in self.include):
                return False
            if any(fnmatch.fnmatchcase(mod, p) for p in self.exclude):
                return False
        return not (self.grep and not self.grep.search(plain))


def apply(data: bytes, f: LogFilter, final: bool) -> tuple[str, int, dict[str, Any]]:
    """(kept text, bytes consumed, stats). A trailing partial line is held back (not
    consumed) unless `final` or it is all there is, so a line is never judged on half
    its text."""
    consumed = len(data)
    cut = data.rfind(b"\n") + 1
    if not final and 0 < cut < len(data):
        consumed, data = cut, data[:cut]
    kept: list[str] = []
    counts: dict[str, dict[str, int]] = {}
    dropped = 0
    for line in data.decode(errors="replace").splitlines(keepends=True):
        m = LOG_RX.search(ANSI_RX.sub("", line))
        if m and m.group(1) in ("err", "wrn"):
            per = counts.setdefault(m.group(1), {})
            per[m.group(2)] = per.get(m.group(2), 0) + 1
        if f.keep(line.rstrip("\r\n")):
            kept.append(line)
        elif line.strip():
            dropped += 1
    stats: dict[str, Any] = {"kept_lines": len(kept), "dropped_lines": dropped}
    if counts:
        stats["errors_warnings_by_module"] = counts
    return "".join(kept), consumed, stats
