"""Power devices (design doc §14): a Nordic PPK2, a simulator, and the native_sim
process. Each says what it supports; the service enforces limits and leases."""

from __future__ import annotations

import asyncio
import math
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import PowerConfig
from .errors import ArbiterError


@dataclass
class Measurement:
    duration_ms: float
    samples: int
    avg_ua: float
    min_ua: float
    max_ua: float
    peak_ua: float
    charge_uc: float
    above_threshold_ms: float | None = None
    threshold_ua: float | None = None
    trace_path: str | None = None
    valid: bool = True
    invalid_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("avg_ua", "min_ua", "max_ua", "peak_ua", "charge_uc", "above_threshold_ms"):
            if d[k] is not None:
                d[k] = round(d[k], 2)
        return d


def summarize(
    samples_ua: list[float], rate_hz: float, threshold_ua: float | None, trace_path: Path
) -> Measurement:
    if not samples_ua:
        raise ArbiterError("OP_FAILED", "no samples recorded")
    dt = 1.0 / rate_hz
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    with trace_path.open("w") as f:
        f.write("t_s,current_ua\n")
        for i, v in enumerate(samples_ua):
            f.write(f"{i * dt:.6f},{v:.3f}\n")
    above = None
    if threshold_ua is not None:
        above = sum(1 for v in samples_ua if v > threshold_ua) * dt * 1000
    s = sorted(samples_ua)
    peak = s[min(len(s) - 1, int(len(s) * 0.999))]
    return Measurement(
        duration_ms=len(samples_ua) * dt * 1000,
        samples=len(samples_ua),
        avg_ua=sum(samples_ua) / len(samples_ua),
        min_ua=s[0],
        max_ua=s[-1],
        peak_ua=peak,
        charge_uc=sum(samples_ua) * dt,
        above_threshold_ms=above,
        threshold_ua=threshold_ua,
        trace_path=str(trace_path),
    )


class PowerDevice:
    kind = "none"
    supports: frozenset[str] = frozenset()  # switch | voltage | measure

    def __init__(self, cfg: PowerConfig):
        self.cfg = cfg
        self.on = True
        self.mv = cfg.default_mv
        self.state = "ON"  # OFF | ON | MEASURING | FAULT
        self.fault: str | None = None
        self.last: Measurement | None = None

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def set_output(self, on: bool) -> None:
        raise ArbiterError("NOT_SUPPORTED", f"{self.kind} cannot switch power")

    async def set_voltage(self, mv: int) -> None:
        raise ArbiterError("NOT_SUPPORTED", f"{self.kind} cannot set a voltage")

    async def measure(
        self,
        duration_ms: int,
        trace_path: Path,
        threshold_ua: float | None = None,
        debug_attached: bool = False,
    ) -> Measurement:
        raise ArbiterError("NOT_SUPPORTED", f"{self.kind} cannot measure current")

    def describe(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "supports": sorted(self.supports),
            "on": self.on,
            "mv": self.mv,
            "state": self.state,
            "fault": self.fault,
            "limits": {
                "mv_min": self.cfg.mv_min,
                "mv_max": self.cfg.mv_max,
                "default_mv": self.cfg.default_mv,
                "ma_max": self.cfg.ma_max,
            },
            "last": self.last.to_dict() if self.last else None,
        }


class SimPower(PowerDevice):
    """Simulated supply + meter wired to a SimDriver board."""

    kind = "sim"
    supports = frozenset({"switch", "voltage", "measure"})
    rate_hz = 10_000

    def __init__(self, cfg: PowerConfig, board: Any = None, speed: float = 1.0):
        super().__init__(cfg)
        self.board = board
        self.speed = speed

    async def set_output(self, on: bool) -> None:
        self.on = on
        self.state = "ON" if on else "OFF"
        if self.board is not None:
            self.board.set_power(on)

    async def set_voltage(self, mv: int) -> None:
        self.mv = mv

    async def measure(
        self,
        duration_ms: int,
        trace_path: Path,
        threshold_ua: float | None = None,
        debug_attached: bool = False,
    ) -> Measurement:
        self.state = "MEASURING"
        try:
            await asyncio.sleep(duration_ms / 1000 / self.speed)
            n = max(10, int(self.rate_hz * duration_ms / 1000))
            base = 650.0 if debug_attached else 3.2  # µA; an attached debugger keeps the SoC awake
            rnd = random.Random(42)  # noqa: S311 - simulated measurement noise, not cryptography
            samples = []
            for i in range(n):
                t = i / self.rate_hz
                v = base + rnd.gauss(0, base * 0.05)
                if self.on and (t % 1.0) < 0.004:  # periodic radio wakeups
                    v += 18_000 + 2_000 * math.sin(i)
                samples.append(max(0.0, v) if self.on else 0.0)
            m = summarize(samples, self.rate_hz, threshold_ua, trace_path)
            if debug_attached:
                m.valid, m.invalid_reason = (
                    False,
                    "debugger or RTT was attached during the measurement",
                )
            self.last = m
            return m
        finally:
            self.state = "ON" if self.on else "OFF"


class NativePower(PowerDevice):
    """native_sim: power is the process. No voltage, no meter."""

    kind = "native"
    supports = frozenset({"switch"})

    def __init__(self, cfg: PowerConfig, board: Any):
        super().__init__(cfg)
        self.board = board

    async def set_output(self, on: bool) -> None:
        await self.board.set_power(on)
        self.on = on
        self.state = "ON" if on else "OFF"


class Ppk2Power(PowerDevice):
    """Nordic Power Profiler Kit II via IRNAS ppk2-api-python (`pip install ppk2-api`).

    Written against the library's documented API (PPK2_API, use_source_meter,
    set_source_voltage, toggle_DUT_power, start/stop_measuring, get_data,
    get_samples); not yet verified against hardware. Source mode only for now."""

    kind = "ppk2"
    supports = frozenset({"switch", "voltage", "measure"})
    rate_hz = 100_000

    def __init__(self, cfg: PowerConfig):
        super().__init__(cfg)
        self.ppk: Any = None
        self._lock = asyncio.Lock()

    def _port(self) -> str:
        from .drivers import discovery

        if self.cfg.port:
            return self.cfg.port
        if self.cfg.serial:
            port = discovery.resolve_port(self.cfg.serial)
            if port:
                return port
        for info in discovery.list_ports():
            if info.vid == 0x1915 and ("PPK2" in (info.description or "") or info.pid == 0xC00A):
                return info.device
        raise ArbiterError("BOARD_OFFLINE", "PPK2 not found")

    async def start(self) -> None:
        try:
            from ppk2_api.ppk2_api import PPK2_API
        except ImportError:
            self.state, self.fault = "FAULT", "ppk2-api is not installed (pip install ppk2-api)"
            return

        def open_ppk() -> Any:
            ppk = PPK2_API(self._port(), timeout=1, write_timeout=1, exclusive=True)
            ppk.get_modifiers()
            ppk.use_source_meter()
            ppk.set_source_voltage(self.cfg.default_mv)
            ppk.toggle_DUT_power("ON")
            return ppk

        try:
            self.ppk = await asyncio.to_thread(open_ppk)
            self.state, self.on, self.fault = "ON", True, None
        except Exception as e:
            self.state, self.fault = "FAULT", f"PPK2 open failed: {e}"

    def _need(self) -> Any:
        if self.ppk is None:
            raise ArbiterError("BOARD_OFFLINE", self.fault or "PPK2 not connected")
        return self.ppk

    async def set_output(self, on: bool) -> None:
        ppk = self._need()
        async with self._lock:
            await asyncio.to_thread(ppk.toggle_DUT_power, "ON" if on else "OFF")
        self.on, self.state = on, "ON" if on else "OFF"

    async def set_voltage(self, mv: int) -> None:
        ppk = self._need()
        async with self._lock:
            await asyncio.to_thread(ppk.set_source_voltage, mv)
        self.mv = mv

    async def measure(
        self,
        duration_ms: int,
        trace_path: Path,
        threshold_ua: float | None = None,
        debug_attached: bool = False,
    ) -> Measurement:
        ppk = self._need()
        async with self._lock:
            self.state = "MEASURING"
            try:
                samples: list[float] = []
                await asyncio.to_thread(ppk.start_measuring)
                t_end = time.monotonic() + duration_ms / 1000
                while time.monotonic() < t_end:
                    data = await asyncio.to_thread(ppk.get_data)
                    if data:
                        s, _digital = ppk.get_samples(data)
                        samples.extend(s)
                    await asyncio.sleep(0.01)
                await asyncio.to_thread(ppk.stop_measuring)
                m = summarize(samples, self.rate_hz, threshold_ua, trace_path)
                if self.cfg.ma_max and m.max_ua > self.cfg.ma_max * 1000:
                    await asyncio.to_thread(ppk.toggle_DUT_power, "OFF")
                    self.on, self.fault = False, f"over-current: {m.max_ua / 1000:.1f} mA"
                    self.state = "FAULT"
                if debug_attached:
                    m.valid, m.invalid_reason = (
                        False,
                        "debugger or RTT was attached during the measurement",
                    )
                self.last = m
                return m
            finally:
                if self.state == "MEASURING":
                    self.state = "ON" if self.on else "OFF"
