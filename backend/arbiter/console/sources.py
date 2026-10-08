"""Console sources: UART (pyserial), RTT (pylink, optional) and a generic
callback source used by the simulator."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .hub import ConsoleHub

log = logging.getLogger("arbiter.console")


class UartSource:
    """Reads a serial port in a thread (portable across Linux/Windows/macOS).

    The port is resolved by `resolve()` every time it (re)opens, so a board whose
    USB CDC port re-enumerates after a reset or flash is picked up again."""

    def __init__(
        self,
        resolve: Callable[[], str | None],
        baud: int = 115200,
        name: str = "uart:app",
        writable: bool = True,
    ):
        self.name = name
        self.writable = writable
        self.resolve = resolve
        self.baud = baud
        self.port_name: str | None = None
        self._ser: Any = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._hub: ConsoleHub | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.connected = False

    async def start(self, hub: ConsoleHub) -> None:
        self._hub, self._loop = hub, asyncio.get_running_loop()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"uart-{hub.board_id}", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        import serial  # pyserial

        loop, hub = self._loop, self._hub
        assert loop is not None and hub is not None, "start() sets the loop and hub"
        backoff = 0.2
        while not self._stop.is_set():
            port = self.resolve()
            if not port:
                self._set_connected(False)
                time.sleep(min(backoff, 2.0))
                backoff *= 1.5
                continue
            try:
                self._ser = (
                    serial.Serial(port, self.baud, timeout=0.1, exclusive=True)
                    if hasattr(serial.Serial, "exclusive")
                    else serial.Serial(port, self.baud, timeout=0.1)
                )
            except (OSError, ValueError, serial.SerialException) as e:
                log.debug("open %s failed: %s", port, e)
                time.sleep(min(backoff, 2.0))
                backoff *= 1.5
                continue
            self.port_name, backoff = port, 0.2
            self._set_connected(True)
            try:
                while not self._stop.is_set():
                    data = self._ser.read(4096)
                    if data:
                        loop.call_soon_threadsafe(hub.feed, data, self.name)
            except (OSError, serial.SerialException) as e:
                log.info("%s lost: %s", port, e)
            finally:
                with contextlib.suppress(Exception):
                    self._ser.close()
                self._ser = None
                self._set_connected(False)

    def _set_connected(self, on: bool) -> None:
        if on != self.connected:
            self.connected = on
            if self._loop and self._hub:
                note = f"[arbiter] uart {'connected ' + (self.port_name or '') if on else 'disconnected'}"
                self._loop.call_soon_threadsafe(self._hub.annotate, note)

    async def stop(self) -> None:
        self._stop.set()
        if self._thread:
            await asyncio.to_thread(self._thread.join, 2.0)
        self._thread = None

    async def write(self, data: bytes) -> None:
        ser = self._ser
        if ser is None:
            from ..errors import ArbiterError

            raise ArbiterError("BOARD_OFFLINE", "serial port is not open")
        await asyncio.to_thread(ser.write, data)


class RttSource:
    """SEGGER RTT through pylink (`pip install pylink-square`). Optional: when pylink
    or the J-Link DLL is missing, start() annotates the console and stays idle.

    Not verified on hardware yet."""

    name = "rtt"
    writable = True

    def __init__(self, probe_serial: str, device: str, block_address: int | None = None):
        self.probe_serial = probe_serial
        self.device = device
        self.block_address = block_address
        self._jl: Any = None
        self._task: asyncio.Task[Any] | None = None
        self.connected = False

    async def start(self, hub: ConsoleHub) -> None:
        try:
            import pylink
        except ImportError:
            hub.annotate(
                "[arbiter] RTT needs pylink-square (pip install pylink-square); RTT console is off"
            )
            return

        def open_jlink() -> Any:
            jl = pylink.JLink()
            jl.open(serial_no=int(self.probe_serial))
            jl.set_tif(pylink.enums.JLinkInterfaces.SWD)
            jl.connect(self.device)
            jl.rtt_start(self.block_address)
            return jl

        try:
            self._jl = await asyncio.to_thread(open_jlink)
        except Exception as e:  # pylink raises many types
            hub.annotate(f"[arbiter] RTT attach failed: {e}")
            return
        self.connected = True
        hub.annotate("[arbiter] rtt attached")
        self._task = asyncio.create_task(self._pump(hub))

    async def _pump(self, hub: ConsoleHub) -> None:
        while True:
            try:
                data = await asyncio.to_thread(self._jl.rtt_read, 0, 4096)
            except Exception as e:
                hub.annotate(f"[arbiter] RTT read failed: {e}")
                return
            if data:
                hub.feed(bytes(data), self.name)
            else:
                await asyncio.sleep(0.05)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None
        if self._jl is not None:
            jl, self._jl = self._jl, None

            def close() -> None:
                try:
                    jl.rtt_stop()
                finally:
                    jl.close()

            with contextlib.suppress(Exception):
                await asyncio.to_thread(close)
        self.connected = False

    async def write(self, data: bytes) -> None:
        if self._jl is None:
            from ..errors import ArbiterError

            raise ArbiterError("BOARD_OFFLINE", "RTT is not attached")
        await asyncio.to_thread(self._jl.rtt_write, 0, list(data))


class CallbackSource:
    """A source whose writes go to a coroutine; output is fed by the owner."""

    def __init__(
        self,
        name: str,
        on_write: Callable[[bytes], Awaitable[None]],
        on_start: Callable[[ConsoleHub], Awaitable[None]] | None = None,
        on_stop: Callable[[], Awaitable[None]] | None = None,
    ):
        self.name = name
        self.writable = True
        self._on_write, self._on_start, self._on_stop = on_write, on_start, on_stop

    async def start(self, hub: ConsoleHub) -> None:
        if self._on_start:
            await self._on_start(hub)

    async def stop(self) -> None:
        if self._on_stop:
            await self._on_stop()

    async def write(self, data: bytes) -> None:
        await self._on_write(data)
