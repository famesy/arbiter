"""`arbiter doctor`: check the setup before an agent trips over it.

Each check is OK, WARN (works, with a gap) or FAIL (an agent will hit an error).
It reads the config and the machine; it never touches a board."""

from __future__ import annotations

import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import BoardConfig, Config, load_config, load_toolchain_env, state_dir
from .procs import which
from .workspace import west_topdir

OK, WARN, FAIL = "OK", "WARN", "FAIL"
WEST_DRIVERS = {"west", "nrf", "stm32"}


@dataclass
class Check:
    status: str
    name: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "name": self.name, "detail": self.detail}


def jlink_exe() -> str:
    # On Windows `jlink` on PATH is often Java's linker, so look for SEGGER's own name.
    return "JLink.exe" if sys.platform == "win32" else "JLinkExe"


def _tool(bc: BoardConfig, name: str) -> str | None:
    return which(name, bc.tools.get(name))


def _module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def check_python() -> Check:
    v = sys.version_info
    shown = f"{v.major}.{v.minor}.{v.micro} ({sys.executable})"
    return Check(OK if v >= (3, 11) else FAIL, "python", shown)


def check_config(path: Path | None = None) -> tuple[list[Check], Config | None]:
    where = path or Path(os.environ.get("ARBITER_CONFIG", state_dir() / "config.toml"))
    try:
        cfg = load_config(path)
    except Exception as e:
        return [Check(FAIL, "config", f"{where}: {e}")], None
    if cfg.path is None:
        return [Check(WARN, "config", f"no config at {where}; only defaults")], cfg
    return [Check(OK, "config", f"{cfg.path}, {len(cfg.boards)} board(s)")], cfg


def check_toolchain(cfg: Config) -> list[Check]:
    if not cfg.toolchain_env:
        return []
    try:
        applied = load_toolchain_env(cfg.toolchain_env)
    except (OSError, ValueError) as e:
        return [Check(FAIL, "toolchain_env", f"{cfg.toolchain_env}: {e}")]
    return [Check(OK, "toolchain_env", f"{cfg.toolchain_env} ({len(applied)} variables)")]


def check_board(bc: BoardConfig, cfg: Config) -> list[Check]:
    from .console.hub import ConsoleHub
    from .drivers import discovery
    from .plugins import make_driver

    name = f"board {bc.id}"
    out: list[Check] = []
    try:
        driver = make_driver(bc, ConsoleHub(bc.id), cfg.state, cfg.plugin_paths)
    except Exception as e:
        return [Check(FAIL, name, f"driver {bc.driver!r}: {e}")]
    ok, why = driver.platform_support()
    if not ok:
        out.append(Check(FAIL, name, why))

    if bc.driver in WEST_DRIVERS:
        west = _tool(bc, "west")
        out.append(
            Check(OK, f"{name}: west", west)
            if west
            else Check(FAIL, f"{name}: west", "not found; set toolchain_env or tools.west")
        )
        out.append(_check_zephyr_base(bc, name))
    if bc.driver == "nrf":
        nrfutil = _tool(bc, "nrfutil")
        out.append(
            Check(OK, f"{name}: nrfutil", nrfutil)
            if nrfutil
            else Check(WARN, f"{name}: nrfutil", "not found; reset and VCOM mapping won't work")
        )
        if bc.console in ("auto", "rtt"):
            jl = _tool(bc, jlink_exe())
            if not jl:
                out.append(Check(WARN, f"{name}: J-Link", f"{jlink_exe()} not found on PATH"))
            if not _module("pylink"):
                out.append(
                    Check(
                        FAIL if bc.console == "rtt" else WARN,
                        f"{name}: RTT",
                        "pylink-square is not installed (pip install arbiter[rtt])",
                    )
                )
    if bc.driver == "stm32" and not _tool(bc, "STM32_Programmer_CLI"):
        out.append(Check(FAIL, f"{name}: STM32_Programmer_CLI", "not found"))

    if bc.probe_serial:
        ports = discovery.ports_for(bc.probe_serial)
        if not ports:
            out.append(Check(WARN, f"{name}: probe", f"{bc.probe_serial} is not connected"))
        else:
            shown = ", ".join(p.device for p in ports)
            status = OK if len(ports) >= len(bc.ports) else WARN
            out.append(Check(status, f"{name}: probe", f"{bc.probe_serial}: {shown}"))

    if bc.power.kind == "ppk2" and not _module("ppk2_api"):
        out.append(
            Check(FAIL, f"{name}: power", "ppk2-api is not installed (pip install ppk2-api)")
        )
    if not out or all(c.status == OK for c in out):
        out.insert(0, Check(OK, name, f"{bc.driver}, {bc.platform}"))
    return out


def _check_zephyr_base(bc: BoardConfig, name: str) -> Check:
    if bc.zephyr_base:
        base = Path(bc.zephyr_base).expanduser()
        if not base.is_dir():
            return Check(FAIL, f"{name}: zephyr_base", f"{base} does not exist")
        if west_topdir(base) is None:
            return Check(FAIL, f"{name}: zephyr_base", f"{base} is not inside a west workspace")
        return Check(OK, f"{name}: zephyr_base", str(base))
    if os.environ.get("ZEPHYR_BASE"):
        return Check(OK, f"{name}: zephyr_base", f"$ZEPHYR_BASE={os.environ['ZEPHYR_BASE']}")
    return Check(OK, f"{name}: zephyr_base", "taken from each build's CMakeCache.txt")


def check_daemon() -> Check:
    from .client import _conn, daemon_running

    conn = _conn(False)
    if conn is None:
        return Check(WARN, "daemon", "not running (agents start it on first use)")
    if daemon_running():
        return Check(OK, "daemon", f"running at {conn[0]}")
    return Check(WARN, "daemon", f"not answering at {conn[0]}; a stale daemon file?")


def run_checks(path: Path | None = None) -> list[Check]:
    checks = [check_python()]
    cfg_checks, cfg = check_config(path)
    checks += cfg_checks
    if cfg is not None:
        checks += check_toolchain(cfg)
        for bc in cfg.boards:
            checks += check_board(bc, cfg)
    checks.append(check_daemon())
    return checks
