"""Decode Zephyr dictionary logging (CONFIG_LOG_DICTIONARY_SUPPORT).

With dictionary logging the board sends compact binary records instead of text: the
format strings stay in the build's log_dictionary.json. Zephyr's
scripts/logging/dictionary/log_parser.py turns the captured output back into text. The
UART backend sends either raw binary (CONFIG_LOG_BACKEND_UART_OUTPUT_DICTIONARY_BIN) or
hex text (..._DICTIONARY_HEX); both are handled."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .workspace import build_python, zephyr_base_from_build

HEX_MARK = b"##ZLOGV1##"
HEX_LINE = re.compile(rb"^[0-9a-fA-F]+$")
MAX_LINES = 300


@dataclass
class Tools:
    python: list[str]
    parser: Path
    database: Path


def find_tools(image_dir: Path, build_dir: Path) -> Tools | str:
    """Zephyr's log parser, the build's Python and the build's log database, or why not."""
    db = image_dir / "zephyr" / "log_dictionary.json"
    if not db.exists():
        return (
            f"no {db.name} in {db.parent}: build with CONFIG_LOG_BACKEND_UART_OUTPUT_DICTIONARY=y "
            "and CONFIG_LOG_BACKEND_UART_OUTPUT_DICTIONARY_HEX=y (or _BIN)"
        )
    zephyr = zephyr_base_from_build(build_dir)
    if zephyr is None:
        return "cannot find ZEPHYR_BASE for this build (no CMakeCache.txt?)"
    parser = zephyr / "scripts" / "logging" / "dictionary" / "log_parser.py"
    if not parser.exists():
        return f"Zephyr's log parser is not at {parser}"
    return Tools(build_python(image_dir, build_dir), parser, db)


def prepare(data: bytes) -> tuple[bytes, list[str]]:
    """The bytes to hand the parser and its format flags. Hex output is cleaned of the
    text lines around it (boot banner, shell prompt)."""
    if HEX_MARK in data:
        return data, ["--hex"]
    lines = [ln.strip() for ln in data.splitlines()]
    hexes = [ln for ln in lines if len(ln) >= 2 and HEX_LINE.match(ln)]
    if hexes and sum(map(len, hexes)) * 2 >= sum(map(len, lines)):
        return b"\n".join(hexes) + b"\n", ["--hex", "--rawhex"]
    return data, []


def decode(data: bytes, tools: Tools, work_dir: Path, timeout_s: float = 60) -> dict[str, Any]:
    """Run the parser on captured output. Never raises."""
    if not data:
        return {"ok": False, "error": "nothing captured on this channel since the mark"}
    payload, flags = prepare(data)
    work_dir.mkdir(parents=True, exist_ok=True)
    log = work_dir / ("dictlog.hex" if flags else "dictlog.bin")
    log.write_bytes(payload)
    cmd = [*tools.python, str(tools.parser), *flags, str(tools.database), str(log)]
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout_s,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "error": str(e), "raw": str(log)}
    lines = p.stdout.splitlines()
    out: dict[str, Any] = {
        "ok": p.returncode == 0,
        "format": "hex" if flags else "binary",
        "raw": str(log),
        "untrusted_device_output": "\n".join(lines[-MAX_LINES:]),
    }
    if len(lines) > MAX_LINES:
        out["truncated_lines"] = len(lines) - MAX_LINES
    if p.returncode != 0:
        tail = p.stderr.strip().splitlines()[-3:]
        out["error"] = " | ".join(tail) or f"log_parser.py exited {p.returncode}"
    return out
