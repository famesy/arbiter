"""Real boards driven through west and the vendor tools.

* `WestDriver` (driver = "west"): any board `west flash --dev-id` supports.
* `NrfDriver` (driver = "nrf"): Nordic DKs (nRF9161 DK first). Reset, recover and
  health checks through `nrfutil device`, RTT through pylink.
* `Stm32Driver` (driver = "stm32"): ST-Link boards; reset and mass erase through
  STM32_Programmer_CLI.

Not yet verified on hardware: exact nrfutil sub-command output, the nRF9161 DK's
VCOM numbering, and RTT through pylink. Everything takes the probe serial so
two probes never trigger an interactive "select emulator" prompt.
"""

from __future__ import annotations

import functools
import time
from pathlib import Path
from typing import Any

from ..config import BoardConfig, PortConfig
from ..console.detect import ConsoleMap, detect_from_build
from ..console.hub import ConsoleHub
from ..console.sources import RttSource, UartSource
from ..errors import ArbiterError
from ..procs import run_proc, which
from ..workspace import west_context
from . import discovery
from .base import BoardDriver, LineFn

JLINK_DEVICES = {
    "nrf9161dk": "nRF9161_xxCA",
    "nrf9160dk": "nRF9160_xxAA",
    "nrf9151dk": "nRF9151_xxAA",
    "nrf52840dk": "nRF52840_xxAA",
    "nrf52dk": "nRF52832_xxAA",
    "nrf5340dk": "nRF5340_xxAA_APP",
    "nrf54l15dk": "nRF54L15_M33",
}


class WestDriver(BoardDriver):
    kind = "west"
    capabilities = frozenset({"flash", "console", "run"})
    flash_timeout = 300.0

    def __init__(self, cfg: BoardConfig, hub: ConsoleHub, state_dir: Path | None = None):
        super().__init__(cfg, hub, state_dir)
        self.zephyr_base: str | None = cfg.zephyr_base  # last one west ran with
        if not cfg.probe_serial:
            raise ValueError(f"board {cfg.id}: probe_serial is required for driver {cfg.driver!r}")

    def tool(self, name: str) -> str:
        path = which(name, self.cfg.tools.get(name))
        if not path:
            raise ArbiterError(
                "NOT_SUPPORTED",
                f"{name} not found on PATH",
                hint=f"Install {name} or set tools.{name} in arbiter's config. Tell the human.",
            )
        return path

    # ---------------------------------------------------------------- console
    def app_port(self) -> PortConfig | None:
        ports = [p for p in self.cfg.ports if p.role == "app"] or self.cfg.ports
        return ports[0] if ports else None

    def resolve(self, port: PortConfig | None) -> str | None:
        if port is not None and port.port:
            return port.port
        return discovery.resolve_port(self.cfg.probe_serial or "", port.interface if port else None)

    def resolve_app_port(self) -> str | None:
        return self.resolve(self.app_port())

    async def start(self) -> None:
        if self.cfg.console in ("auto", "uart"):
            p = self.app_port()
            await self.hub.attach(UartSource(self.resolve_app_port, p.baud if p else 115200))
            for aux in (x for x in self.cfg.ports if x.role == "aux"):
                await self.hub.attach(
                    UartSource(
                        functools.partial(self.resolve, aux),
                        aux.baud,
                        name=f"uart:{aux.name or 'aux'}",
                        writable=False,
                    )
                )
        if self.cfg.console == "rtt":
            await self._attach_rtt(None)
            self.hub.set_primary("rtt")

    async def _attach_rtt(self, address: int | None) -> None:
        if "rtt" not in self.capabilities:
            return
        device = self.cfg.device or JLINK_DEVICES.get(self.cfg.platform.split("/")[0], "Cortex-M33")
        await self.hub.attach(RttSource(self.cfg.probe_serial or "", device, address))

    async def set_console(self, cmap: ConsoleMap) -> None:
        self.console_map = cmap
        if self.cfg.console != "auto":
            return
        if cmap.resolved in ("rtt", "both"):
            await self._attach_rtt(cmap.rtt_address)
        elif "rtt" in self.hub.sources:
            await self.hub.detach("rtt")
        img = cmap.images[0] if cmap.images else None
        self.hub.set_primary("rtt" if img is not None and img.console == "rtt" else "uart:app")

    async def detach_debug(self) -> list[str]:
        if "rtt" in self.hub.sources:
            await self.hub.detach("rtt")
            return ["rtt"]
        return []

    async def reattach_debug(self, what: list[str]) -> None:
        if "rtt" in what:
            await self._attach_rtt(self.console_map.rtt_address if self.console_map else None)

    async def present(self) -> bool:
        return discovery.present(self.cfg.probe_serial)

    # ---------------------------------------------------------------- operations
    def flash_argv(self, build_dir: Path, domain: str | None, erase: bool) -> list[str]:
        argv = [
            self.tool("west"),
            "flash",
            "-d",
            str(build_dir),
            "--dev-id",
            self.cfg.probe_serial or "",
        ]
        if self.cfg.runner:
            argv += ["-r", self.cfg.runner]
        if domain:
            argv += ["--domain", domain]
        if erase:
            argv.append("--erase")
        return argv + list(self.cfg.flash_args)

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
        build_dir = Path(build_dir)
        if not build_dir.exists():
            raise ArbiterError("OP_FAILED", f"build dir not found: {build_dir}")
        argv = self.flash_argv(build_dir, domain, erase)
        # `west flash` only exists inside a west workspace, so run it in the one the build
        # was made with (from its CMakeCache.txt), not wherever the agent happens to be.
        env, run_in = west_context(build_dir, self.cfg.zephyr_base, cwd or build_dir.parent)
        if env.get("ZEPHYR_BASE"):
            self.zephyr_base = env["ZEPHYR_BASE"]
        res = await run_proc(
            argv,
            cwd=run_in,
            env=env,
            timeout_s=self.flash_timeout,
            log_path=log_path,
            on_line=on_line,
        )
        out = res.summary()
        if not res.ok and any("unknown command" in line for line in res.tail):
            out["hint"] = (
                "west could not find its workspace. Set zephyr_base for this board (or "
                "[daemon] zephyr_base) to the Zephyr tree, e.g. C:/ncs/v3.4.1/zephyr."
            )
        if res.ok:
            out["console"] = (await self._after_flash(build_dir)).to_dict()
        return out

    def run_env(self) -> dict[str, str]:
        env = super().run_env()
        if self.zephyr_base:
            env["ZEPHYR_BASE"] = self.zephyr_base  # twister and west in tests need it too
        return env

    async def _after_flash(self, build_dir: Path) -> ConsoleMap:
        cmap = detect_from_build(build_dir)
        await self.set_console(cmap)
        return cmap

    async def reset(self, *, halt: bool, log_path: Path) -> dict[str, Any]:
        raise ArbiterError("NOT_SUPPORTED", "reset is not configured for generic west boards")

    async def check_alive(self) -> bool:
        return await self.present()


class NrfDriver(WestDriver):
    kind = "nrf"
    capabilities = frozenset({"flash", "reset", "recover", "console", "rtt", "run"})

    def __init__(self, cfg: BoardConfig, hub: ConsoleHub, state_dir: Path | None = None):
        super().__init__(cfg, hub, state_dir)
        self._vcoms: dict[int, str] = {}  # VCOM index -> port, from `nrfutil device list`
        self._vcoms_at = 0.0

    async def start(self) -> None:
        await self.refresh_vcoms()
        await super().start()

    async def refresh_vcoms(self) -> None:
        """Windows names every J-Link VCOM "JLink CDC UART Port", so the reliable VCOM -> COM
        mapping comes from nrfutil. Best effort: without nrfutil, interface numbers are used."""
        self._vcoms_at = time.monotonic()
        try:
            argv = [self.tool("nrfutil"), "device", "list", "--json"]
        except ArbiterError:
            return
        res = await run_proc(argv, timeout_s=30, tail_lines=500)
        for dev in discovery.parse_nrfutil_list("\n".join(res.tail)):
            if discovery.same_serial(dev["serial"], self.cfg.probe_serial):
                self._vcoms = {
                    int(p["vcom"]): p["port"]
                    for p in dev.get("ports", [])
                    if p.get("vcom") is not None
                }

    def resolve(self, port: PortConfig | None) -> str | None:
        if port is not None and port.port:
            return port.port
        vcom = (
            port.vcom
            if port is not None and port.vcom is not None
            else (0 if port is None or port.role == "app" else None)
        )
        if vcom is not None and vcom in self._vcoms:
            cached = self._vcoms[vcom]
            if any(x.device == cached for x in discovery.ports_for(self.cfg.probe_serial or "")):
                return cached
            # the probe re-enumerated under new port names: use interface numbers until
            # present() reads the map from nrfutil again
            self._vcoms, self._vcoms_at = {}, 0.0
        iface = (
            port.interface
            if port is not None and port.interface is not None
            else (vcom * 2 if vcom is not None else None)
        )
        return discovery.resolve_port(self.cfg.probe_serial or "", iface)

    async def present(self) -> bool:
        here = discovery.present(self.cfg.probe_serial)
        if here and not self._vcoms and time.monotonic() - self._vcoms_at > 30:
            await self.refresh_vcoms()  # enumeration can be incomplete right after plug-in
        return here

    def _sn(self) -> list[str]:
        return ["--serial-number", self.cfg.probe_serial or ""]

    async def reset(self, *, halt: bool, log_path: Path) -> dict[str, Any]:
        if halt:
            raise ArbiterError("NOT_SUPPORTED", "reset with halt needs the debugger (phase 2)")
        res = await run_proc(
            [self.tool("nrfutil"), "device", "reset", *self._sn()], timeout_s=60, log_path=log_path
        )
        return res.summary()

    async def recover(self, *, log_path: Path) -> dict[str, Any]:
        rtt = await self.detach_debug()
        res = await run_proc(
            [self.tool("nrfutil"), "device", "recover", *self._sn()],
            timeout_s=180,
            log_path=log_path,
        )
        await self.reattach_debug(rtt)
        return res.summary()

    async def check_alive(self) -> bool:
        if not await self.present():
            return False
        try:
            argv = [self.tool("nrfutil"), "device", "device-info", *self._sn()]
        except ArbiterError:
            return True  # can't check without nrfutil; presence will do
        res = await run_proc(argv, timeout_s=30)
        return res.ok


class Stm32Driver(WestDriver):
    kind = "stm32"
    capabilities = frozenset({"flash", "reset", "recover", "console", "run"})

    def _conn(self) -> list[str]:
        return ["-c", "port=SWD", f"sn={self.cfg.probe_serial}"]

    async def reset(self, *, halt: bool, log_path: Path) -> dict[str, Any]:
        argv = [self.tool("STM32_Programmer_CLI"), *self._conn(), "-halt" if halt else "-rst"]
        return (await run_proc(argv, timeout_s=60, log_path=log_path)).summary()

    async def recover(self, *, log_path: Path) -> dict[str, Any]:
        argv = [self.tool("STM32_Programmer_CLI"), *self._conn(), "-e", "all"]
        return (await run_proc(argv, timeout_s=180, log_path=log_path)).summary()
