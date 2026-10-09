"""Zephyr's emulated boards (QEMU, Renode) as boards.

"Flashing" remembers the build dir and starts the build's own emulator target, the way
`west build -t run` does: `cmake --build <build> --target run` for QEMU boards
(qemu_x86, qemu_cortex_m3, mps2/an385, ...) and `--target run_renode` for Renode. The
emulated UART is the process's stdio, on a pseudo-terminal arbiter owns, so the console,
shell_exec, crash triage and the rest work as on hardware.

Power and reset restart the emulator; reset with halt stops it (SIGSTOP); recover forgets
the build. Linux and macOS only (on Windows run arbiterd inside WSL).

Options under `[board.options]`:

    emulator = "qemu"   # qemu | renode
    target = "run"      # override the CMake target
    autostart = true    # start the last flashed build when the daemon starts
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

from ..config import BoardConfig
from ..console.detect import detect_from_build, image_dirs
from ..console.hub import ConsoleHub
from ..errors import ArbiterError
from ..procs import IS_WINDOWS, which
from .base import LineFn
from .native_sim import NativeSimDriver

TARGETS = {"qemu": "run", "renode": "run_renode"}


class EmulatorDriver(NativeSimDriver):
    kind = "emulator"

    def __init__(self, cfg: BoardConfig, hub: ConsoleHub, state_dir: Path | None = None):
        super().__init__(cfg, hub, state_dir)
        o = cfg.options
        default = cfg.driver if cfg.driver in TARGETS else "qemu"  # driver = "renode" works too
        self.emulator = str(o.get("emulator", default))
        if self.emulator not in TARGETS and not o.get("target"):
            raise ValueError(f"board {cfg.id}: emulator is qemu or renode, not {self.emulator!r}")
        self.target = str(o.get("target") or TARGETS[self.emulator])
        self.uart_mode = "stdio"
        self.saved = self.dir / "build_dir.txt"

    @staticmethod
    def platform_support() -> tuple[bool, str]:
        ok = not IS_WINDOWS
        return ok, "" if ok else "emulated boards need Linux or macOS; run arbiterd in WSL"

    @property
    def build_dir(self) -> Path | None:
        try:
            return Path(self.saved.read_text().strip())
        except OSError:
            return None

    def _has_image(self) -> bool:
        b = self.build_dir
        return b is not None and (b / "CMakeCache.txt").exists()

    def _argv(self) -> list[str]:
        cmake = which("cmake", self.cfg.tools.get("cmake"))
        if not cmake:
            raise ArbiterError(
                "NOT_SUPPORTED",
                "cmake not found on PATH",
                hint="Install cmake (it comes with the Zephyr toolchain) or set tools.cmake.",
            )
        assert self.build_dir is not None
        return [cmake, "--build", str(self.build_dir), "--target", self.target]

    @staticmethod
    def run_dir(build_dir: Path) -> Path | None:
        """The CMake build that has the emulator target: the default image's under sysbuild."""
        dirs = [d for _n, d in image_dirs(build_dir)] + [build_dir]
        return next((d for d in dirs if (d / "CMakeCache.txt").exists()), None)

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
        ok, why = self.platform_support()
        if not ok:
            raise ArbiterError("NOT_SUPPORTED", why)
        build_dir = await asyncio.to_thread(Path(build_dir).resolve)
        run_in = await asyncio.to_thread(self.run_dir, build_dir)
        if run_in is None:
            raise ArbiterError(
                "OP_FAILED",
                f"no CMake build in {build_dir}",
                hint=f"Build for an emulated board first, e.g. west build -b {self.cfg.platform}.",
            )
        await self._kill()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.saved.write_text(str(run_in))
        msg = f"-- {self.emulator}: cmake --build {run_in} --target {self.target}"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a") as f:
            f.write(msg + "\n")
        on_line(msg)
        self.console_map = await asyncio.to_thread(detect_from_build, build_dir)
        if self.powered:
            await self._launch()
        return {"ok": True, "exit_code": 0, "tail": [msg], "log_path": str(log_path)}

    async def recover(self, *, log_path: Path) -> dict[str, Any]:
        await self._kill()
        with contextlib.suppress(FileNotFoundError):
            self.saved.unlink()
        self.hub.annotate(f"[arbiter] {self.kind} build forgotten")
        return {"ok": True, "erased": True}

    def describe(self) -> dict[str, Any]:
        d = super().describe()
        d.pop("native_sim", None)
        d["emulator"] = {
            "emulator": self.emulator,
            "target": self.target,
            "running": self.running,
            "pid": self.proc.pid if self.running and self.proc else None,
            "build_dir": str(self.build_dir) if self._has_image() else None,
            "last_exit": self.last_exit,
        }
        return d
