"""UART vs RTT console auto-detection (design doc §7).

Order: the default sysbuild image's build config (authoritative), then the
`_SEGGER_RTT` ELF symbol, then a runtime probe that the service runs when
nothing else knows. The primary console is RTT only when CONFIG_RTT_CONSOLE=y
and CONFIG_UART_CONSOLE is not set; otherwise it is the UART.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..elf import elf_symbol

RTT_KEYS = (
    "CONFIG_USE_SEGGER_RTT",
    "CONFIG_RTT_CONSOLE",
    "CONFIG_LOG_BACKEND_RTT",
    "CONFIG_SHELL_BACKEND_RTT",
)
UART_CONSOLE_KEYS = (
    "CONFIG_UART_CONSOLE",
    "CONFIG_LOG_BACKEND_UART",
    "CONFIG_SHELL_BACKEND_SERIAL",
)


@dataclass
class ImageConsole:
    name: str
    console: str = "none"  # uart | rtt | none
    logs: list[str] = field(default_factory=list)
    shell: str | None = None
    console_uart: str | None = None
    shell_uart: str | None = None
    rtt_address: int | None = None
    board: str | None = None


@dataclass
class ConsoleMap:
    images: list[ImageConsole] = field(default_factory=list)
    default_image: str | None = None
    resolved: str = "unknown"  # uart | rtt | both | unknown
    method: str = "none"  # config | elf | runtime | none
    rtt_address: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.rtt_address is not None:
            d["rtt_address"] = hex(self.rtt_address)
        for img in d["images"]:
            if img["rtt_address"] is not None:
                img["rtt_address"] = hex(img["rtt_address"])
        return d


def parse_kconfig(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("CONFIG_") and "=" in line:
            k, v = line.split("=", 1)
            out[k] = v.strip().strip('"')
    return out


_CHOSEN = re.compile(r"chosen\s*\{(.*?)\};", re.S)


def parse_chosen(dts: Path) -> dict[str, str]:
    """Return chosen-node properties from a generated zephyr.dts (values are node paths)."""
    if not dts.exists():
        return {}
    text = dts.read_text(errors="replace")
    out = {}
    for block in _CHOSEN.findall(text):
        for m in re.finditer(r"([\w,-]+)\s*=\s*&?([^;]+);", block):
            out[m.group(1)] = m.group(2).strip().strip('"')
    return out


def read_domains(build_dir: Path) -> tuple[str | None, list[tuple[str, Path]]]:
    """Parse a sysbuild domains.yaml: (default image name, [(name, build_dir)])."""
    text = (build_dir / "domains.yaml").read_text()
    default = None
    m = re.search(r"^default:\s*(\S+)", text, re.M)
    if m:
        default = m.group(1).strip("'\"")
    images: list[tuple[str, Path]] = []
    name = None
    for line in text.splitlines():
        m = re.match(r"\s*-?\s*name:\s*(\S+)", line)
        if m:
            name = m.group(1).strip("'\"")
        m = re.match(r"\s+build_dir:\s*(.+)", line)
        if m and name:
            p = Path(m.group(1).strip().strip("'\""))
            images.append((name, p if p.is_absolute() else build_dir / p))
            name = None
    return default, images


def image_dirs(build_dir: Path) -> list[tuple[str, Path]]:
    """Images of a build, default image first. With sysbuild, <build>/zephyr/.config is the
    sysbuild config (SB_CONFIG_* only), so the images come from domains.yaml."""
    build_dir = Path(build_dir)
    if (build_dir / "domains.yaml").exists():
        default, images = read_domains(build_dir)
        if not images:
            images = [
                (sub.name, sub)
                for sub in sorted(build_dir.iterdir())
                if (sub / "zephyr" / ".config").exists()
            ]
        images.sort(key=lambda im: im[0] != default)
        return images
    if (build_dir / "zephyr" / ".config").exists():
        return [(build_dir.name, build_dir)]
    return []


def detect_image(name: str, img_dir: Path) -> ImageConsole:
    ic = ImageConsole(name=name)
    cfg = parse_kconfig(img_dir / "zephyr" / ".config")
    ic.board = cfg.get("CONFIG_BOARD")

    def on(key: str) -> bool:
        return cfg.get(key) == "y"

    chosen = parse_chosen(img_dir / "zephyr" / "zephyr.dts")
    ic.console_uart = chosen.get("zephyr,console")
    ic.shell_uart = chosen.get("zephyr,shell-uart")
    # Verified on an nRF9161 DK: with both RTT_CONSOLE and UART_CONSOLE set (NCS's rtt-console
    # snippet), output goes to the UART and RTT stays empty. RTT is the console only on its own.
    if on("CONFIG_RTT_CONSOLE") and not on("CONFIG_UART_CONSOLE"):
        ic.console = "rtt"
    elif on("CONFIG_UART_CONSOLE"):
        ic.console = "uart"
    if on("CONFIG_LOG_BACKEND_RTT"):
        ic.logs.append("rtt")
    if on("CONFIG_LOG_BACKEND_UART"):
        ic.logs.append("uart")
    if on("CONFIG_SHELL_BACKEND_RTT"):
        ic.shell = "rtt"
    elif on("CONFIG_SHELL_BACKEND_SERIAL"):
        ic.shell = "uart"
    elf = img_dir / "zephyr" / "zephyr.elf"
    if elf.exists() and (
        ic.console == "rtt" or "rtt" in ic.logs or ic.shell == "rtt" or on("CONFIG_USE_SEGGER_RTT")
    ):
        ic.rtt_address = elf_symbol(elf, "_SEGGER_RTT")
    return ic


def detect_from_build(build_dir: Path) -> ConsoleMap:
    """The console is decided by the default image; other images (MCUboot, TF-M) are listed
    for information, since snippets such as rtt-console apply to every sysbuild image."""
    cmap = ConsoleMap()
    for name, d in image_dirs(Path(build_dir)):
        try:
            cmap.images.append(detect_image(name, d))
        except OSError:
            continue
    if cmap.images:
        cmap.method = "config"
        img = cmap.images[0]
        cmap.default_image = img.name
        used = {x for x in [img.console, img.shell, *img.logs] if x in ("uart", "rtt")}
        cmap.rtt_address = img.rtt_address
        cmap.resolved = "both" if used == {"uart", "rtt"} else (used.pop() if used else "unknown")
    return cmap


def detect_from_elf(elf: Path) -> ConsoleMap:
    addr = elf_symbol(Path(elf), "_SEGGER_RTT")
    if addr is None:
        return ConsoleMap(method="elf", resolved="uart")
    return ConsoleMap(method="elf", resolved="rtt", rtt_address=addr)


# --------------------------------------------------------------- tiny ELF reader
