"""Probe and serial-port discovery. Boards are identified by their probe's USB
serial number and the interface number, never by port name (design doc §6)."""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SEGGER_VID = 0x1366
STLINK_VID = 0x0483
KNOWN_PROBE_VIDS = {
    SEGGER_VID: "jlink",
    STLINK_VID: "stlink",
    0x0D28: "cmsis-dap",
    0x1915: "nordic",
}


@dataclass
class PortInfo:
    device: str
    vid: int | None
    pid: int | None
    serial_number: str | None
    interface: int | None
    location: str | None
    description: str
    hwid: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["vid"] = f"{self.vid:04x}" if self.vid is not None else None
        d["pid"] = f"{self.pid:04x}" if self.pid is not None else None
        return d


_cache: dict[str, Any] = {"at": 0.0, "ports": []}


def _iface(location: str | None) -> int | None:
    if not location:
        return None
    m = re.search(r"[:.](\d+)$", location)
    return int(m.group(1)) if m else None


def list_ports(max_age: float = 0.8) -> list[PortInfo]:
    """pyserial's list_ports, cached briefly (the registry polls it about once a second)."""
    if time.monotonic() - _cache["at"] < max_age:
        return list(_cache["ports"])
    try:
        from serial.tools import list_ports as lp

        raw = lp.comports()
    except Exception:
        raw = []
    out = [
        PortInfo(
            p.device,
            p.vid,
            p.pid,
            p.serial_number,
            _iface(p.location),
            p.location,
            p.description or "",
            p.hwid or "",
        )
        for p in raw
    ]
    _cache.update(at=time.monotonic(), ports=out)
    return out


def _norm(sn: str | None) -> str:
    return (sn or "").lstrip("0").upper()


# Nordic DK board numbers (nrfutil's boardVersion) -> Zephyr board target.
NORDIC_BOARDS = {
    "PCA10153": "nrf9161dk/nrf9161/ns",
    "PCA10090": "nrf9160dk/nrf9160/ns",
    "PCA10171": "nrf9151dk/nrf9151/ns",
    "PCA10056": "nrf52840dk/nrf52840",
    "PCA10040": "nrf52dk/nrf52832",
    "PCA10095": "nrf5340dk/nrf5340/cpuapp",
    "PCA10143": "nrf7002dk/nrf5340/cpuapp",
    "PCA10156": "nrf54l15dk/nrf54l15/cpuapp",
}


def nordic_platform(board_version: str | None) -> str | None:
    if not board_version:
        return None
    return NORDIC_BOARDS.get(board_version.upper().split("_")[0])


def same_serial(a: str | None, b: str | None) -> bool:
    """USB reports 001050978819 where J-Link and nrfutil say 1050978819."""
    return bool(a) and bool(b) and _norm(a) == _norm(b)


def ports_for(serial: str) -> list[PortInfo]:
    want = _norm(serial)
    ports = [p for p in list_ports() if p.serial_number and _norm(p.serial_number) == want]
    return sorted(ports, key=lambda p: (p.interface if p.interface is not None else 99, p.device))


def resolve_port(
    serial: str, interface: int | None = None, override: str | None = None
) -> str | None:
    """Find the current device path for a probe's VCOM. On Linux prefer the stable
    /dev/serial/by-id link; elsewhere match the USB serial (and interface)."""
    if override:
        return override
    if sys.platform.startswith("linux"):
        pat = (
            f"/dev/serial/by-id/*{serial}*-if{interface:02d}*"
            if interface is not None
            else f"/dev/serial/by-id/*{serial}*"
        )
        hits = sorted(str(p) for p in Path("/dev/serial/by-id").glob(Path(pat).name))
        if hits:
            return hits[0]
    ports = ports_for(serial)
    if not ports:
        return None
    if interface is None:
        return ports[0].device
    for p in ports:
        if p.interface == interface:
            return p.device
    # Interface numbers aren't reported on every OS (notably some Windows setups):
    # fall back to the n-th port of this probe, and let config override if wrong.
    idx = [0, 2, 4].index(interface) if interface in (0, 2, 4) else interface
    return ports[idx].device if idx < len(ports) else None


def probes() -> list[dict[str, Any]]:
    """Debug probes visible as USB serial devices, grouped by serial number."""
    seen: dict[str, dict[str, Any]] = {}
    for p in list_ports():
        kind = KNOWN_PROBE_VIDS.get(p.vid or -1)
        if not kind or not p.serial_number:
            continue
        d = seen.setdefault(
            p.serial_number,
            {
                "serial": p.serial_number,
                "kind": kind,
                "vid": f"{p.vid:04x}",
                "pid": f"{p.pid:04x}",
                "ports": [],
            },
        )
        d["ports"].append(
            {"device": p.device, "interface": p.interface, "description": p.description}
        )
    return list(seen.values())


def present(serial: str | None) -> bool:
    return bool(serial) and bool(ports_for(serial))  # type: ignore[arg-type]


def parse_nrfutil_list(text: str) -> list[dict[str, Any]]:
    """Parse `nrfutil device list --json` output (JSON lines). The exact schema is
    not pinned here, so this looks for serial numbers and board versions defensively."""
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        devices = (
            (obj.get("data") or {}).get("devices") if isinstance(obj.get("data"), dict) else None
        )
        for dev in devices or []:
            sn = dev.get("serialNumber") or (dev.get("devkit") or {}).get("serialNumber")
            board = (dev.get("devkit") or {}).get("boardVersion")
            ports = []
            for sp in dev.get("serialPorts") or []:
                if isinstance(sp, dict):
                    ports.append(
                        {"port": sp.get("comName") or sp.get("path"), "vcom": sp.get("vcom")}
                    )
            if sn:
                out.append(
                    {
                        "serial": sn,
                        "board_version": board,
                        "traits": dev.get("traits"),
                        "ports": ports,
                    }
                )
    return out
