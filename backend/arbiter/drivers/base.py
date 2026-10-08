"""Board driver interface. A driver knows how to flash, reset, recover and
attach the console for one kind of board. It never decides *who* may do that;
the service checks the lease before calling it."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..config import BoardConfig
from ..console.detect import ConsoleMap
from ..console.hub import ConsoleHub
from ..errors import ArbiterError
from ..zephyr_shell import ShellCommands, from_build

LineFn = Callable[[str], None]


class BoardDriver:
    kind = "base"
    #: what the driver can do: flash, reset, halt, recover, console, rtt, run, power
    capabilities: frozenset[str] = frozenset()

    def __init__(self, cfg: BoardConfig, hub: ConsoleHub, state_dir: Path | None = None):
        self.cfg = cfg
        self.hub = hub
        self.state_dir = state_dir
        self.console_map: ConsoleMap | None = None
        self.health: str = "unknown"  # ok | unknown | missing | error
        self.health_note: str | None = None

    # ---------------------------------------------------------------- platform
    @staticmethod
    def platform_support() -> tuple[bool, str]:
        return True, ""

    # ---------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        """Attach console sources. Called once when the daemon starts."""

    async def stop(self) -> None:
        await self.hub.detach_all()

    async def present(self) -> bool:
        """Is the board physically reachable? Polled about once a second."""
        return True

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
        raise ArbiterError("NOT_SUPPORTED", f"{self.kind} boards cannot flash")

    async def reset(self, *, halt: bool, log_path: Path) -> dict[str, Any]:
        raise ArbiterError("NOT_SUPPORTED", f"{self.kind} boards cannot reset")

    async def recover(self, *, log_path: Path) -> dict[str, Any]:
        raise ArbiterError("NOT_SUPPORTED", f"{self.kind} boards cannot recover")

    async def check_alive(self) -> bool:
        return True

    # ---------------------------------------------------------------- console
    async def set_console(self, cmap: ConsoleMap) -> None:
        """Re-attach console sources to match a detected console map."""
        self.console_map = cmap

    async def detach_debug(self) -> list[str]:
        """Detach anything holding the debug interface (RTT); return what was detached."""
        return []

    async def reattach_debug(self, what: list[str]) -> None:
        pass

    # ---------------------------------------------------------------- shell
    def shell_commands(self, build_dir: Path) -> ShellCommands:
        """Shell commands the flashed image registers, for console completion.
        Runs in a worker thread after a successful flash."""
        return from_build(build_dir)

    # ---------------------------------------------------------------- tests
    def dev_id(self) -> str | None:
        return self.cfg.probe_serial

    def run_env(self) -> dict[str, str]:
        env = {"ARBITER_BOARD": self.cfg.id, "ARBITER_PLATFORM": self.cfg.platform}
        if self.dev_id():
            env["ARBITER_DEV_ID"] = self.dev_id() or ""
        return env

    def hardware_map_entry(
        self, serial: str | None = None, serial_pty: str | None = None
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "connected": True,
            "available": True,
            "platform": self.cfg.platform,
            "id": self.dev_id() or self.cfg.id,
            "product": self.kind,
            "runner": self.cfg.runner or "jlink",
        }
        if serial_pty:
            entry["serial_pty"] = serial_pty
        elif serial:
            entry["serial"] = serial
            entry["baud"] = self.cfg.ports[0].baud if self.cfg.ports else 115200
        return entry

    def describe(self) -> dict[str, Any]:
        return {
            "driver": self.kind,
            "capabilities": sorted(self.capabilities),
            "health": self.health,
            "health_note": self.health_note,
            "console": {
                "mode": self.cfg.console,
                "sources": self.hub.source_names(),
                "map": self.console_map.to_dict() if self.console_map else None,
            },
        }


def is_linux() -> bool:
    return sys.platform.startswith("linux")
