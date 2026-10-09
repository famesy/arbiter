"""`arbiter init`: detect the boards plugged in and draft a starter config.toml.

Safe for an agent to run: it only reads USB and nrfutil, and writes nothing unless
asked to. The caller shows the draft to a human before writing it."""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import tomlkit

from .config import load_toolchain_env, state_dir
from .config_edit import _item, validate
from .drivers import discovery
from .drivers.west import JLINK_DEVICES
from .procs import which


def default_path() -> Path:
    env = os.environ.get("ARBITER_CONFIG")
    return Path(env) if env else state_dir() / "config.toml"


def _ncs_roots() -> list[Path]:
    env = os.environ.get("NCS_ROOT")
    if env:
        return [Path(env)]
    if sys.platform == "win32":
        roots = [Path("C:/ncs")]
    else:
        roots = [Path.home() / "ncs", Path("/opt/nordic/ncs")]
    return roots


def _version_key(p: Path) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", p.name))


def find_ncs(roots: list[Path] | None = None) -> dict[str, str]:
    """The newest nRF Connect SDK toolchain bundle and Zephyr tree, if installed in the
    usual place (C:\\ncs on Windows, ~/ncs elsewhere)."""
    out: dict[str, str] = {}
    for root in roots if roots is not None else _ncs_roots():
        envs = sorted(root.glob("toolchains/*/environment.json"), key=lambda p: p.stat().st_mtime)
        if envs and "toolchain_env" not in out:
            out["toolchain_env"] = str(envs[-1])
        trees = sorted(
            (p for p in root.glob("v*/zephyr") if p.is_dir()), key=lambda p: _version_key(p.parent)
        )
        if trees and "zephyr_base" not in out:
            out["zephyr_base"] = str(trees[-1])
    return out


def nrfutil_devices() -> list[dict[str, Any]]:
    nrfutil = which("nrfutil")
    if not nrfutil:
        return []
    try:
        out = subprocess.run(
            [nrfutil, "device", "list", "--json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
            stdin=subprocess.DEVNULL,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return discovery.parse_nrfutil_list(out)


def _board(i: int, probe: dict[str, Any], nrf: list[dict[str, Any]]) -> dict[str, Any]:
    dev = next((d for d in nrf if discovery.same_serial(d["serial"], probe["serial"])), {})
    platform = discovery.nordic_platform(dev.get("board_version"))
    kind = probe["kind"]
    driver = "nrf" if kind == "jlink" else ("stm32" if kind == "stlink" else "west")
    name = platform.split("/")[0] if platform else kind
    b: dict[str, Any] = {"id": f"{name}-{i}", "driver": driver}
    if platform:
        b["platform"] = platform
    b["probe_serial"] = probe["serial"].lstrip("0") or probe["serial"]
    if platform and platform.split("/")[0] in JLINK_DEVICES:
        b["device"] = JLINK_DEVICES[platform.split("/")[0]]
    vcoms = sorted({p["vcom"] for p in dev.get("ports", []) if p.get("vcom") is not None})
    ports: list[dict[str, Any]] = []
    if vcoms:
        for v in vcoms:
            if v == 0:
                ports.append({"role": "app", "vcom": 0})
            else:
                aux = "tfm" if (platform or "").startswith("nrf91") and v == 1 else f"vcom{v}"
                ports.append({"role": "aux", "name": aux, "vcom": v})
    else:  # no nrfutil: the probe's first serial interface is the app console
        ifaces = sorted({p["interface"] for p in probe["ports"] if p["interface"] is not None})
        if ifaces:
            ports.append({"role": "app", "interface": ifaces[0]})
            ports += [{"role": "aux", "name": f"if{n}", "interface": n} for n in ifaces[1:]]
    if ports:
        b["port"] = ports
    return b


def draft(
    probes: list[dict[str, Any]], nrf: list[dict[str, Any]], ncs: dict[str, str]
) -> dict[str, Any]:
    """A raw config (the TOML's shape) for the probes found. With none, a simulated
    board so the agent tools and the dashboard work straight away."""
    raw: dict[str, Any] = {"daemon": {"port": 7777, **ncs}}
    boards = [_board(i, p, nrf) for i, p in enumerate(probes, 1)]
    raw["board"] = boards or [{"id": "sim-1", "driver": "sim", "platform": "native_sim"}]
    return raw


def render(raw: dict[str, Any], found: int) -> str:
    doc = tomlkit.document()
    doc.add(tomlkit.comment("arbiter config, drafted by `arbiter init`."))
    if found:
        doc.add(tomlkit.comment(f"Found {found} debug probe(s). Check ids, ports and tags."))
    else:
        doc.add(tomlkit.comment("No debug probes found: this is a simulated board to try with."))
    doc.add(tomlkit.comment("Power supplies are off until you add [board.power]."))
    doc.add(tomlkit.nl())
    for k, v in raw.items():
        doc.add(k, _item(v))
    return tomlkit.dumps(doc)


def detect() -> tuple[dict[str, Any], int]:
    ncs = find_ncs()
    if ncs.get("toolchain_env"):  # nrfutil lives in the toolchain bundle
        with contextlib.suppress(OSError, ValueError):
            load_toolchain_env(ncs["toolchain_env"])
    probes = discovery.probes()
    nrf = nrfutil_devices() if probes else []
    raw = draft(probes, nrf, ncs)
    errors = validate(raw)
    if errors:
        raise ValueError("; ".join(f"{e['path']}: {e['message']}" for e in errors))
    return raw, len(probes)
