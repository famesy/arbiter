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


_DTS_NODE = re.compile(r"^\s*((?:[\w-]+:\s*)*)([\w,.+-]+)(?:@([0-9a-fA-F]+))?\s*\{")
_DTS_REG = re.compile(r"^\s*reg\s*=\s*<\s*(0x[0-9a-fA-F]+|\d+)\s+(0x[0-9a-fA-F]+|\d+)")
_DTS_LABEL = re.compile(r'^\s*label\s*=\s*"([^"]*)"')
_DTS_CODE = re.compile(r"zephyr,code-partition\s*=\s*&([\w-]+)")


def parse_dts_partitions(path: Path) -> tuple[list[dict[str, Any]], str | None]:
    """Flash partitions from a build's zephyr.dts (`partition@...` nodes; nested ones are
    offset by their parent's address), and the label of the zephyr,code-partition. NCS
    v3.x builds without Partition Manager keep their layout here instead of partitions.yml."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return [], None
    code = m.group(1) if (m := _DTS_CODE.search(text)) else None
    out: list[dict[str, Any]] = []
    stack: list[dict[str, Any] | None] = []  # one entry per open node; None if not a partition
    for raw in text.splitlines():
        line = re.sub(r"/\*.*?\*/", "", raw).rstrip()
        if line.endswith("{"):
            node: dict[str, Any] | None = None
            m = _DTS_NODE.match(line)
            if m and m.group(2) == "partition":
                labels = [x.strip() for x in m.group(1).split(":") if x.strip()]
                parent = next((n for n in reversed(stack) if n is not None), None)
                node = {"name": labels[-1] if labels else f"partition@{m.group(3)}",
                        "_base": parent["_abs"] if parent and "_abs" in parent else 0}  # fmt: skip
                out.append(node)
            stack.append(node)
        elif line.strip() == "};":
            if stack:
                stack.pop()
        elif stack and (cur := stack[-1]) is not None:
            if (r := _DTS_REG.match(line)) and "_abs" not in cur:
                cur["_abs"] = cur["_base"] + int(r.group(1), 0)
                cur["size"] = int(r.group(2), 0)
            elif lb := _DTS_LABEL.match(line):
                cur["label"] = lb.group(1)
    keep = [p for p in out if "_abs" in p]
    for p in keep:
        p["address"] = p.pop("_abs")
        p.pop("_base", None)
    keep.sort(key=lambda p: (p["address"], -p["size"]))
    for p in keep:
        p["address"] = hex(p["address"])
    return [{k: p[k] for k in ("name", "label", "address", "size") if k in p} for p in keep], code


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
    code = None
    if not parts:
        parts, code_label = parse_dts_partitions(d / "zephyr" / "zephyr.dts")
        code = next((p for p in parts if p["name"] == code_label), None)
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
    if code and code.get("size") and out["memory"].get("flash_bytes") is not None:
        # The image must fit its code partition (e.g. the non-secure slot), not all flash.
        out["memory"]["code_partition"] = code["name"]
        out["memory"]["code_partition_kib"] = code["size"] // 1024
        out["memory"]["flash_used_pct"] = round(
            100 * out["memory"]["flash_bytes"] / code["size"], 1
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
    if "CONFIG_LOG_DICTIONARY_SUPPORT" in on:
        w.append("Dictionary logging is on: log lines arrive encoded. Read them with decode_log.")
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
