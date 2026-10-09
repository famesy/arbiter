"""Zephyr `native_sim` as a board.

"Flashing" copies the built `zephyr.exe` into arbiter's state dir (so the agent
can keep rebuilding without disturbing the running image) and starts it as a
managed process. The console is the process's UART:

* `uart = "stdio"` (default): run with `-uart_stdinout`, stdin/stdout on a
  pseudo-terminal that arbiter owns (so libc doesn't block-buffer the output);
* `uart = "pty"`: let Zephyr create its own pty, parse "connected to
  pseudotty: /dev/pts/N" from stdout and open that.

Power maps onto the process: off kills it, on starts it, cycle restarts it.
Reset restarts it; reset with halt stops it (SIGSTOP). Recover deletes the
flashed copy.

native_sim only runs on Linux. On Windows run arbiterd inside WSL and plug the
board's USB into WSL with usbipd if you also need real boards there.

Options under `[board.options]` for this driver:

    uart = "stdio"      # stdio | pty
    args = ["-rt"]      # extra command-line options for zephyr.exe
    autostart = true    # start the last flashed image when the daemon starts
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import shutil
import signal
import sys
from pathlib import Path
from typing import Any

from ..config import BoardConfig
from ..console.detect import detect_from_build, image_dirs
from ..console.hub import ConsoleHub
from ..console.sources import CallbackSource, UartSource
from ..errors import ArbiterError
from ..procs import kill_tree
from .base import BoardDriver, LineFn, is_linux


def unsupported_note() -> str:
    if sys.platform == "win32":
        note = "native_sim runs only on Linux; on Windows run arbiterd inside WSL"
    else:
        note = "native_sim runs only on Linux"
    return note


if sys.platform == "win32":

    def _open_pty() -> tuple[int, int]:
        raise ArbiterError("NOT_SUPPORTED", unsupported_note())

    def _stop(pid: int) -> None:
        raise ArbiterError("NOT_SUPPORTED", unsupported_note())

    def _continue(pid: int) -> None:
        raise ArbiterError("NOT_SUPPORTED", unsupported_note())

else:
    import pty
    import termios
    import tty

    def _open_pty() -> tuple[int, int]:
        """A raw, no-echo pty pair; the master end is non-blocking."""
        master, slave = pty.openpty()
        tty.setraw(slave)
        attrs = termios.tcgetattr(slave)
        attrs[3] &= ~termios.ECHO
        termios.tcsetattr(slave, termios.TCSANOW, attrs)
        os.set_blocking(master, False)
        return master, slave

    def _stop(pid: int) -> None:
        os.kill(pid, signal.SIGSTOP)

    def _continue(pid: int) -> None:
        os.kill(pid, signal.SIGCONT)


PTY_LINE = re.compile(rb"connected to pseudotty: (/dev/pts/\d+)")


class NativeSimDriver(BoardDriver):
    kind = "native_sim"
    is_process = True
    capabilities = frozenset({"flash", "reset", "halt", "recover", "console", "run", "power"})

    def __init__(self, cfg: BoardConfig, hub: ConsoleHub, state_dir: Path | None = None):
        super().__init__(cfg, hub, state_dir)
        o = cfg.options
        self.uart_mode = o.get("uart", "stdio")
        self.extra_args = list(o.get("args", []))
        self.autostart = bool(o.get("autostart", True))
        self.dir = (state_dir or Path.cwd()) / "native" / cfg.id
        self.image = self.dir / "zephyr.exe"
        self.proc: asyncio.subprocess.Process | None = None
        self._master: int | None = None
        self._watch: asyncio.Task[Any] | None = None
        self.last_exit: int | None = None
        self._pty_task: asyncio.Future[None] | None = None
        self.powered = True

    @staticmethod
    def platform_support() -> tuple[bool, str]:
        if is_linux():
            return True, ""
        return False, unsupported_note()

    # ---------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        ok, why = self.platform_support()
        if not ok:
            self.health, self.health_note = "error", why
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        if self._has_image() and self.autostart:
            await self._launch()
        else:
            self.health, self.health_note = "ok", "no image flashed yet"

    async def stop(self) -> None:
        await self._kill()
        await super().stop()

    async def present(self) -> bool:
        return self.platform_support()[0]

    # ---------------------------------------------------------------- process
    def _has_image(self) -> bool:
        return self.image.exists()

    def _argv(self) -> list[str]:
        argv = [str(self.image), *self.extra_args]
        if (
            self.uart_mode == "stdio"
            and "-uart_stdinout" not in argv
            and "--uart_stdinout" not in argv
        ):
            argv.append("-uart_stdinout")
        return argv

    async def _launch(self) -> None:
        await self._kill()
        if not self._has_image():
            raise ArbiterError(
                "OP_FAILED",
                "nothing flashed yet",
                hint=f"Call flash with a {self.cfg.platform} build dir first.",
            )
        argv = self._argv()
        master, slave = _open_pty()
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                cwd=str(self.dir),
                start_new_session=True,
            )
        finally:
            os.close(slave)
        self._master = master
        self.hub.annotate(f"[arbiter] {self.kind} started (pid {self.proc.pid})")
        await self.hub.detach_all()
        if self.uart_mode == "stdio":
            await self.hub.attach(CallbackSource("uart:app", self._write_master))
        asyncio.get_running_loop().add_reader(master, self._on_master)
        self._watch = asyncio.create_task(self._wait_exit(self.proc))
        self.health, self.health_note, self.last_exit = "ok", None, None

    def _on_master(self) -> None:
        try:
            data = os.read(self._master, 4096)  # type: ignore[arg-type]
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if not data:
            self._close_master()
            return
        if self.uart_mode == "pty":
            m = PTY_LINE.search(data)
            if m:
                path = m.group(1).decode()
                self._pty_task = asyncio.ensure_future(self.hub.attach(UartSource(lambda: path)))
        self.hub.feed(data, "uart:app" if self.uart_mode == "stdio" else "stdout")

    async def _write_master(self, data: bytes) -> None:
        if self._master is None:
            raise ArbiterError(
                "BOARD_OFFLINE", f"{self.kind} is not running", hint="Flash or power it on first."
            )
        os.write(self._master, data)

    def _close_master(self) -> None:
        if self._master is not None:
            with contextlib.suppress(Exception):
                asyncio.get_running_loop().remove_reader(self._master)
            with contextlib.suppress(OSError):
                os.close(self._master)
            self._master = None

    async def _wait_exit(self, proc: asyncio.subprocess.Process) -> None:
        code = await proc.wait()
        if proc is self.proc:
            await asyncio.sleep(0.1)  # let the last output drain
            self._close_master()
            self.hub.annotate(f"[arbiter] {self.kind} exited with code {code}")
            self.last_exit = code
            self.proc = None

    async def _kill(self) -> None:
        proc, self.proc = self.proc, None
        if self._watch:
            self._watch.cancel()
            self._watch = None
        if proc and proc.returncode is None:
            with contextlib.suppress(OSError):
                _continue(proc.pid)
            await asyncio.to_thread(kill_tree, proc.pid, True, 1.0)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(proc.wait(), 3)
        self._close_master()

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    # ---------------------------------------------------------------- operations
    @staticmethod
    def find_exe(build_dir: Path, domain: str | None = None) -> Path | None:
        build_dir = Path(build_dir)
        if build_dir.is_file():
            return build_dir
        for name, d in image_dirs(build_dir):
            if domain and name != domain:
                continue
            exe = d / "zephyr" / "zephyr.exe"
            if exe.exists():
                return exe
        exe = build_dir / "zephyr" / "zephyr.exe"
        return exe if exe.exists() else None

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
        exe = self.find_exe(Path(build_dir), domain)
        if exe is None:
            raise ArbiterError(
                "OP_FAILED",
                f"no zephyr.exe under {build_dir}",
                hint="Build for native_sim first, e.g. west build -b native_sim.",
            )
        await self._kill()
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.image.with_suffix(".tmp")
        await asyncio.to_thread(shutil.copy2, exe, tmp)
        tmp.chmod(0o700)
        tmp.replace(self.image)
        msg = f"-- native_sim: installed {exe} ({exe.stat().st_size // 1024} kB)"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.open("a").write(msg + "\n")
        on_line(msg)
        is_dir = await asyncio.to_thread(Path(build_dir).is_dir)
        self.console_map = detect_from_build(Path(build_dir)) if is_dir else None
        if self.powered:
            await self._launch()
        return {
            "ok": True,
            "exit_code": 0,
            "tail": [msg],
            "log_path": str(log_path),
            "image": str(exe),
        }

    async def reset(self, *, halt: bool, log_path: Path) -> dict[str, Any]:
        if halt:
            if self.running and self.proc:
                _stop(self.proc.pid)
            return {"ok": True, "halted": True}
        await self._launch()
        return {"ok": True, "halted": False}

    async def recover(self, *, log_path: Path) -> dict[str, Any]:
        await self._kill()
        with contextlib.suppress(FileNotFoundError):
            self.image.unlink()
        self.hub.annotate("[arbiter] native_sim image erased")
        return {"ok": True, "erased": True}

    async def check_alive(self) -> bool:
        return self.platform_support()[0]

    def describe(self) -> dict[str, Any]:
        d = super().describe()
        d["native_sim"] = {
            "running": self.running,
            "pid": self.proc.pid if self.running and self.proc else None,
            "image": str(self.image) if self.image.exists() else None,
            "last_exit": self.last_exit,
            "uart": self.uart_mode,
        }
        return d

    # ---------------------------------------------------------------- power (used by NativePower)
    async def set_power(self, on: bool) -> None:
        self.powered = on
        if on and not self.running and self._has_image():
            await self._launch()
        elif not on:
            await self._kill()
            self.hub.annotate(f"[arbiter] {self.kind} powered off")
