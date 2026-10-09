"""Firmware update over MCUmgr (SMP) the way a device in the field gets one: upload the
signed image to the secondary slot, mark it for test, reset, check the new image boots,
then confirm it so MCUboot keeps it (or leave it unconfirmed so the next reset reverts).

The board's driver runs the `mcumgr` CLI over the app UART (or a port with role "smp"),
taking the port from the console while it does. The image needs MCUboot and the MCUmgr
image management group over UART (CONFIG_MCUMGR_TRANSPORT_UART or the shell transport)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .console.detect import image_dirs

# Newest first: plain Zephyr's signed binary, NCS's update binary.
UPDATE_FILES = ["zephyr/zephyr.signed.bin", "zephyr/app_update.bin"]


def find_update_image(build_dir: Path) -> Path | None:
    """The signed application image of a build, for upload to the secondary slot."""
    build_dir = Path(build_dir)
    dirs = [d for _n, d in image_dirs(build_dir)] + [build_dir]
    for d in dirs:
        for rel in UPDATE_FILES:
            if (d / rel).exists():
                return d / rel
    return None


def mcumgr_conn(port: str, baud: int) -> list[str]:
    return ["--conntype", "serial", "--connstring", f"dev={port},baud={baud},mtu=512"]


def parse_image_list(text: str) -> list[dict[str, Any]]:
    """`mcumgr image list` (also `smpmgr image state-read`-style "image=0 slot=1" blocks)."""
    slots: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for line in text.splitlines():
        m = re.search(r"image=(\d+)\s+slot=(\d+)", line)
        if m:
            cur = {"image": int(m.group(1)), "slot": int(m.group(2)), "flags": []}
            slots.append(cur)
            continue
        if cur is None:
            continue
        m = re.match(r"\s*(version|bootable|flags|hash):\s*(.*?)\s*$", line)
        if not m:
            continue
        key, value = m.groups()
        if key == "flags":
            cur["flags"] = value.split()
        elif key == "bootable":
            cur["bootable"] = value == "true"
        else:
            cur[key] = value
    return slots


def slot(slots: list[dict[str, Any]], image: int, number: int) -> dict[str, Any] | None:
    return next((s for s in slots if s["image"] == image and s["slot"] == number), None)


def verdict(slots: list[dict[str, Any]], new_hash: str | None) -> dict[str, Any]:
    """Is the new image running, and is it confirmed?"""
    active = next((s for s in slots if "active" in s["flags"]), None)
    running_new = bool(active and new_hash and active.get("hash") == new_hash)
    return {
        "running_new_image": running_new,
        "confirmed": bool(running_new and active and "confirmed" in active["flags"]),
        "active_version": (active or {}).get("version"),
    }
