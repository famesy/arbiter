"""What is in a build, in one short answer: board, images, bootloader, partitions, the
Kconfig options that matter when debugging on hardware, memory use, and the git state
of the app and Zephyr. Agents call it instead of rediscovering this file by file.

Also the build's fingerprint (ELF hash, Kconfig hash, git commits), which the run
history (history.py) records with every flash and test run."""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Any

from .console.detect import image_dirs, parse_kconfig
from .elf import Elf, ElfError
from .workspace import cache_value, zephyr_base_from_build

# Options worth seeing at a glance, with what they mean for hardware debugging.
KEY_OPTIONS = [
    "CONFIG_BOARD_TARGET",
    "CONFIG_UART_CONSOLE",
    "CONFIG_RTT_CONSOLE",
    "CONFIG_LOG",
    "CONFIG_LOG_MODE_DEFERRED",
    "CONFIG_LOG_MODE_IMMEDIATE",
    "CONFIG_LOG_DEFAULT_LEVEL",
    "CONFIG_LOG_BACKEND_UART",
    "CONFIG_LOG_BACKEND_RTT",
    "CONFIG_LOG_DICTIONARY_SUPPORT",
    "CONFIG_SHELL",
    "CONFIG_ASSERT",
    "CONFIG_ASSERT_VERBOSE",
    "CONFIG_DEBUG_OPTIMIZATIONS",
    "CONFIG_DEBUG_THREAD_INFO",
    "CONFIG_THREAD_MONITOR",
    "CONFIG_THREAD_NAME",
    "CONFIG_THREAD_ANALYZER",
    "CONFIG_DEBUG_COREDUMP",
    "CONFIG_DEBUG_COREDUMP_BACKEND_LOGGING",
    "CONFIG_HW_STACK_PROTECTION",
    "CONFIG_MAIN_STACK_SIZE",
    "CONFIG_SYSTEM_WORKQUEUE_STACK_SIZE",
    "CONFIG_HEAP_MEM_POOL_SIZE",
    "CONFIG_BOOTLOADER_MCUBOOT",
    "CONFIG_BUILD_WITH_TFM",
    "CONFIG_NRF_MODEM_LIB",
    "CONFIG_NRF_MODEM_LIB_TRACE",
    "CONFIG_PM",
    "CONFIG_PM_DEVICE",
    "CONFIG_SERIAL",
]


def kconfig_hash(cfg_path: Path) -> str | None:
    try:
        lines = sorted(
            ln
            for ln in cfg_path.read_text(errors="replace").splitlines()
            if ln.startswith("CONFIG_")
        )
    except OSError:
        return None
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16]


def file_hash(path: Path) -> str | None:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()[:16]


def git_state(path: Path | None) -> dict[str, Any] | None:
    """Commit, branch and dirty flag of the repository holding `path`."""
    if path is None or not path.exists():
        return None

    def git(*args: str) -> str | None:
        try:
            p = subprocess.run(
                ["git", "-C", str(path), *args],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return p.stdout.strip() if p.returncode == 0 else None

    sha = git("rev-parse", "HEAD")
    if not sha:
        return None
    status = git("status", "--porcelain", "--untracked-files=no")
    return {
        "repo": git("rev-parse", "--show-toplevel"),
        "commit": sha,
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(status),
    }


def parse_partitions(path: Path) -> list[dict[str, Any]]:
    """NCS Partition Manager's partitions.yml: name, address, size, region (flat entries)."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z0-9_]+):\s*$", line)
        if m:
            cur = {"name": m.group(1)}
            out.append(cur)
            continue
        m = re.match(r"^\s{2}(address|size|end_address|region):\s*(\S+)", line)
        if m and cur is not None:
            key, value = m.groups()
            cur[key] = int(value, 0) if key != "region" else value
    keep = [p for p in out if "address" in p and "size" in p]
    keep.sort(key=lambda p: (str(p.get("region", "")), p["address"]))
    for p in keep:
        p["address"], p["size"] = hex(p["address"]), p["size"]
        p.pop("end_address", None)
    return keep


def fingerprint(build_dir: Path) -> dict[str, Any]:
    """Identity of a build: hashes of the default image's ELF and Kconfig, and git state."""
    build_dir = Path(build_dir).resolve()
    dirs = image_dirs(build_dir)
    out: dict[str, Any] = {"build_dir": str(build_dir)}
    if not dirs:
        return out
    name, d = dirs[0]
    out["image"] = name
    out["elf_sha"] = file_hash(d / "zephyr" / "zephyr.elf") or file_hash(
        d / "zephyr" / "zephyr.exe"
    )
    out["config_sha"] = kconfig_hash(d / "zephyr" / ".config")
    src = cache_value(d / "CMakeCache.txt", "APPLICATION_SOURCE_DIR")
    out["app_git"] = git_state(Path(src)) if src else None
    zb = zephyr_base_from_build(build_dir)
    zg = git_state(zb) if zb else None
    out["zephyr_git"] = {k: zg[k] for k in ("commit", "dirty")} if zg else None
    return out


def describe_build(build_dir: Path, top: int = 8) -> dict[str, Any]:
    build_dir = Path(build_dir).resolve()
    dirs = image_dirs(build_dir)
    if not dirs:
        raise FileNotFoundError(f"{build_dir} is not a Zephyr build (no zephyr/.config)")
    name, d = dirs[0]
    cfg = parse_kconfig(d / "zephyr" / ".config")
    sysbuild = (
        parse_kconfig(build_dir / "zephyr" / ".config")
        if len(dirs) > 1 or (build_dir / "domains.yaml").exists()
        else {}
    )
    out: dict[str, Any] = {
        "build_dir": str(build_dir),
        "board": cfg.get("CONFIG_BOARD_TARGET") or cfg.get("CONFIG_BOARD"),
        "default_image": name,
        "images": [{"name": n, "dir": str(p)} for n, p in dirs],
        "mcuboot": any(n == "mcuboot" for n, _ in dirs)
        or sysbuild.get("SB_CONFIG_BOOTLOADER_MCUBOOT") == "y"
        or cfg.get("CONFIG_BOOTLOADER_MCUBOOT") == "y",
        "tfm": cfg.get("CONFIG_BUILD_WITH_TFM") == "y",
        "kconfig": {k: cfg[k] for k in KEY_OPTIONS if k in cfg},
    }
    parts = parse_partitions(build_dir / "partitions.yml")
    if parts:
        out["partitions"] = parts
    try:
        out["memory"] = Elf.load(d / "zephyr" / "zephyr.elf").memory_use(top)
    except ElfError as e:
        out["memory"] = {"error": str(e)}
    for key in ("CONFIG_FLASH_SIZE", "CONFIG_SRAM_SIZE"):
        if key in cfg and out["memory"].get("flash_bytes") is not None:
            kib = int(cfg[key], 0)
            used = out["memory"]["flash_bytes" if "FLASH" in key else "ram_bytes"]
            out["memory"][key.lower().removeprefix("config_") + "_kib"] = kib
            out["memory"][("flash" if "FLASH" in key else "ram") + "_used_pct"] = (
                round(100 * used / (kib * 1024), 1) if kib else None
            )
    out.update({k: v for k, v in fingerprint(build_dir).items() if k != "build_dir"})
    out["warnings"] = warnings(cfg, out)
    return out


def warnings(cfg: dict[str, str], info: dict[str, Any]) -> list[str]:
    on = {k for k, v in cfg.items() if v == "y"}
    w = []
    if "CONFIG_LOG_MODE_DEFERRED" in on:
        w.append(
            "Logging is deferred: lines just before a crash can be lost. Use "
            "CONFIG_LOG_MODE_IMMEDIATE=y while debugging."
        )
    if "CONFIG_ASSERT" not in on:
        w.append("CONFIG_ASSERT is off: __ASSERT checks are compiled out.")
    if "CONFIG_RTT_CONSOLE" in on and "CONFIG_UART_CONSOLE" in on:
        w.append("Both RTT and UART console are on: output goes to the UART, RTT stays empty.")
    if "CONFIG_DEBUG_OPTIMIZATIONS" not in on and "CONFIG_DEBUG_THREAD_INFO" in on:
        w.append("Optimised build: gdb may show <optimized out> and jump around when stepping.")
    if info.get("app_git") and info["app_git"].get("dirty"):
        w.append("The app repository has uncommitted changes; the commit alone won't rebuild this.")
    if not info.get("mcuboot") and str(info.get("board") or "").endswith("/ns"):
        w.append(
            "Non-secure target without MCUboot: on nRF91/nRF53 DKs an older image at 0x0 can keep "
            "booting after a flash. arbiter's flash checks the boot banner."
        )
    return w
