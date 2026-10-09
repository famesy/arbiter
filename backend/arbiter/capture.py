"""Record one console channel's raw bytes to a file while it runs (modem traces, CTF
tracing). The hub calls the listener on its own loop, so writes stay in order."""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path
from typing import IO, Any

from .console.hub import ConsoleHub


class Capture:
    def __init__(self, hub: ConsoleHub, channel: str, path: Path, fh: IO[bytes]):
        self.hub, self.channel, self.path, self.fh = hub, channel, path, fh
        self.bytes = 0
        self.started = time.time()
        hub.listeners.append(self._on_data)

    @classmethod
    async def open(cls, hub: ConsoleHub, channel: str, path: Path) -> Capture:
        path.parent.mkdir(parents=True, exist_ok=True)
        return cls(hub, channel, path, await asyncio.to_thread(path.open, "wb"))

    def _on_data(self, channel: str, data: bytes, _end: int) -> None:
        if channel == self.channel:
            self.fh.write(data)
            self.bytes += len(data)

    def view(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "raw": str(self.path),
            "bytes": self.bytes,
            "seconds": round(time.time() - self.started, 1),
        }

    async def close(self) -> dict[str, Any]:
        view = self.view()
        with contextlib.suppress(ValueError):
            self.hub.listeners.remove(self._on_data)
        await asyncio.to_thread(self.fh.close)
        return view
