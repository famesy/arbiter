"""Zephyr CTF tracing (CONFIG_TRACING_CTF): turn a captured trace stream into a short
summary an agent can read.

The board streams binary CTF events (thread switches, ISRs, semaphores, ...) on the
tracing UART. arbiter records them, pairs the stream with Zephyr's CTF metadata
(subsys/tracing/ctf/tsdl/metadata) in a trace directory, and, when babeltrace2 is
installed, decodes it and counts what happened. The directory also opens in Trace
Compass for the timeline."""

from __future__ import annotations

import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from .workspace import zephyr_base_from_build

EVENT_RX = re.compile(r"^\[([\d:.]+)\]\s+\([^)]*\)\s+(?:\S+\s+)?([\w.]+):\s*\{(.*)\}\s*$")
NAME_RX = re.compile(r'\bname = "([^"]*)"')
MAX_LINES = 200_000


def metadata_for(build_dir: Path) -> Path | str:
    zephyr = zephyr_base_from_build(build_dir)
    if zephyr is None:
        return "cannot find ZEPHYR_BASE for this build (no CMakeCache.txt?)"
    meta = zephyr / "subsys" / "tracing" / "ctf" / "tsdl" / "metadata"
    return meta if meta.exists() else f"no CTF metadata at {meta}"


def trace_dir(raw: Path, metadata: Path) -> Path:
    """A CTF trace directory: the metadata and the captured stream as channel0_0."""
    out = raw.with_suffix("")
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(metadata, out / "metadata")
    shutil.copyfile(raw, out / "channel0_0")
    return out


def babeltrace(directory: Path, timeout_s: float = 120) -> tuple[str | None, str | None]:
    """(text, error) from babeltrace2, or (None, why) when it isn't installed or fails."""
    exe = shutil.which("babeltrace2") or shutil.which("babeltrace")
    if not exe:
        return None, "babeltrace2 is not installed"
    try:
        p = subprocess.run(
            [exe, str(directory)],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout_s,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return None, str(e)
    if p.returncode != 0:
        return p.stdout or None, " | ".join(p.stderr.strip().splitlines()[-3:]) or "failed"
    return p.stdout, None


def _seconds(ts: str) -> float:
    parts = [float(x) for x in ts.split(":")]
    total = 0.0
    for part in parts:
        total = total * 60 + part
    return total


def summarize(text: str, top: int = 10) -> dict[str, Any]:
    events: Counter[str] = Counter()
    switched_in: Counter[str] = Counter()
    first = last = None
    for line in text.splitlines()[:MAX_LINES]:
        m = EVENT_RX.match(line)
        if not m:
            continue
        ts, name, fields = m.groups()
        events[name] += 1
        first = first if first is not None else ts
        last = ts
        if name == "thread_switched_in":
            n = NAME_RX.search(fields)
            switched_in[n.group(1) if n else "?"] += 1
    out: dict[str, Any] = {"events": sum(events.values())}
    if first and last:
        out["span_s"] = round(_seconds(last) - _seconds(first), 6)
    out["by_event"] = dict(events.most_common(top))
    if switched_in:
        out["thread_switches"] = dict(switched_in.most_common(top))
    isr = events.get("isr_enter", 0)
    if isr and out.get("span_s"):
        out["isr_per_s"] = round(isr / out["span_s"], 1)
    return out
