"""Configuration and per-user state paths.

The config is TOML (stdlib `tomllib`). Example in `examples/arbiter.toml`."""

from __future__ import annotations

import contextlib
import dataclasses
import json
import os
import secrets
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

from .scheduler import Timing


def state_dir() -> Path:
    env = os.environ.get("ARBITER_HOME")
    if env:
        return Path(env)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "arbiter"


@dataclass
class PortConfig:
    role: str = "app"  # app | aux
    # Channel name suffix (uart:<name>). App ports are always uart:app. Aux ports, such as
    # TF-M's VCOM1, are read and tagged but never written.
    name: str | None = None
    interface: int | None = None  # USB interface number (J-Link OB: VCOM0 = 0, VCOM1 = 2)
    vcom: int | None = None  # Nordic VCOM index as nrfutil reports it; preferred over interface
    port: str | None = None  # explicit override, e.g. COM7 or /dev/serial/by-id/...
    baud: int = 115200


@dataclass
class PowerConfig:
    kind: str = "none"  # none | sim | ppk2 | native | command | <plugin name> | module:Class
    serial: str | None = None
    port: str | None = None
    # Limits arbiter enforces for every supply kind. Voltages outside mv_min..mv_max are
    # refused for agents and humans alike; agents need approval to go above default_mv.
    mv_min: int = 3000
    mv_max: int = 5000
    default_mv: int = 3700
    # Current limit in mA. A measurement that goes over it switches the supply off until a
    # human turns it back on. Script supplies also get it at start via set_current_limit.
    ma_max: float | None = None
    allow_agent_raise_voltage: bool = False
    options: dict[str, Any] = field(default_factory=dict)  # for plugin power drivers
    # kind = "command": templates for on, off, set_voltage, set_current_limit and measure
    commands: dict[str, Any] = field(default_factory=dict)


@dataclass
class BoardConfig:
    id: str
    # sim | nrf | stm32 | west | native_sim | command | <plugin name> | module:Class
    driver: str = "sim"
    platform: str = "nrf9161dk/nrf9161/ns"
    probe_serial: str | None = None
    device: str | None = None  # J-Link device name for RTT, e.g. nRF9160_xxAA
    tags: list[str] = field(default_factory=list)
    console: str = "auto"  # auto | uart | rtt
    ports: list[PortConfig] = field(default_factory=list)
    power: PowerConfig = field(default_factory=PowerConfig)
    allow_agent_erase: bool = False
    max_lease_min: float | None = None
    runner: str | None = None  # west runner override (jlink, nrfutil, openocd, ...)
    # Zephyr tree west uses for this board, when the build doesn't record one
    # (it normally does, in CMakeCache.txt). Defaults to [daemon] zephyr_base.
    zephyr_base: str | None = None
    flash_args: list[str] = field(default_factory=list)
    tools: dict[str, str] = field(default_factory=dict)  # tool name -> path override
    # Driver-specific options (sim, native_sim, plugins)
    options: dict[str, Any] = field(default_factory=dict)
    # Per-action command overrides, see plugins.py
    commands: dict[str, Any] = field(default_factory=dict)


@dataclass
class Config:
    host: str = "127.0.0.1"
    port: int = 7777
    boards: list[BoardConfig] = field(default_factory=list)
    timing: Timing = field(default_factory=Timing)
    state: Path = field(default_factory=state_dir)
    human_name: str = "human"
    # Extra dirs added to sys.path for module:Class drivers
    plugin_paths: list[str] = field(default_factory=list)
    # NCS toolchain bundle environment.json, loaded before running tools
    toolchain_env: str | None = None
    # Default Zephyr tree for west boards whose builds don't name one
    zephyr_base: str | None = None
    path: Path | None = None

    @property
    def log_dir(self) -> Path:
        return self.state / "logs"


_T = TypeVar("_T", bound="DataclassInstance")


def _mk(cls: type[_T], d: dict[str, Any]) -> _T:
    names = {f.name for f in dataclasses.fields(cls)}
    unknown = set(d) - set(names)
    if unknown:
        raise ValueError(f"unknown {cls.__name__} keys: {sorted(unknown)}")
    return cls(**d)


def load_config(path: Path | None = None) -> Config:
    path = path or Path(os.environ.get("ARBITER_CONFIG", state_dir() / "config.toml"))
    cfg = Config()
    if path and Path(path).exists():
        data = tomllib.loads(Path(path).read_text())
        cfg = config_from_dict(data)
        cfg.path = Path(path)
    return cfg


def _check_power_limits(board: str, p: PowerConfig) -> None:
    if not p.mv_min <= p.default_mv <= p.mv_max:
        raise ValueError(
            f"board {board}: power needs mv_min <= default_mv <= mv_max, "
            f"got {p.mv_min} <= {p.default_mv} <= {p.mv_max}"
        )
    if p.ma_max is not None and p.ma_max <= 0:
        raise ValueError(f"board {board}: power ma_max must be above 0 mA, got {p.ma_max}")


def config_from_dict(data: dict[str, Any]) -> Config:
    cfg = Config()
    d = data.get("daemon", {})
    cfg.host = d.get("host", cfg.host)
    cfg.port = int(d.get("port", cfg.port))
    cfg.human_name = d.get("human_name", cfg.human_name)
    cfg.plugin_paths = [str(Path(p).expanduser()) for p in d.get("plugin_paths", [])]
    cfg.toolchain_env = d.get("toolchain_env")
    cfg.zephyr_base = d.get("zephyr_base")
    if "state_dir" in d:
        cfg.state = Path(d["state_dir"]).expanduser()
    if "timing" in data:
        cfg.timing = _mk(Timing, data["timing"])
    for raw in data.get("board", []):
        b = dict(raw)
        ports = [_mk(PortConfig, p) for p in b.pop("port", [])]
        power = _mk(PowerConfig, b.pop("power", {})) if "power" in b else PowerConfig()
        bc = _mk(BoardConfig, b)
        bc.ports, bc.power = ports, power
        bc.zephyr_base = bc.zephyr_base or cfg.zephyr_base
        _check_power_limits(bc.id, power)
        cfg.boards.append(bc)
    ids = [b.id for b in cfg.boards]
    if len(ids) != len(set(ids)):
        raise ValueError("board ids must be unique")
    return cfg


# ------------------------------------------------------------------ token files
def daemon_file(state: Path | None = None) -> Path:
    return (state or state_dir()) / "daemon.json"


def admin_file(state: Path | None = None) -> Path:
    return (state or state_dir()) / "admin.json"


def _write_private(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    with contextlib.suppress(OSError):
        tmp.chmod(0o600)
    tmp.replace(path)


def write_daemon_files(state: Path, host: str, port: int) -> tuple[str, str]:
    """Agent token (daemon.json, used by the MCP shim/CLI) and admin token (admin.json,
    used by the dashboard and human CLI commands). Both readable only by this user."""
    agent_token = secrets.token_urlsafe(24)
    admin_token = secrets.token_urlsafe(24)
    _write_private(
        daemon_file(state), {"host": host, "port": port, "token": agent_token, "pid": os.getpid()}
    )
    _write_private(
        admin_file(state), {"host": host, "port": port, "token": admin_token, "pid": os.getpid()}
    )
    return agent_token, admin_token


def read_daemon_file(admin: bool = False, state: Path | None = None) -> dict[str, Any] | None:
    p = admin_file(state) if admin else daemon_file(state)
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_toolchain_env(path: str | Path, environ: dict[str, str] | None = None) -> dict[str, str]:
    """Apply an nRF Connect SDK toolchain bundle's environment.json (PATH, PYTHONPATH,
    NRFUTIL_HOME, ZEPHYR_SDK_INSTALL_DIR, ...) so west and nrfutil resolve from the bundle,
    not from whatever is on the system PATH. Returns the variables it set.

    Entries look like {"key": "PATH", "type": "relative_paths", "values": [...],
    "existing_value_treatment": "prepend_to"}; unknown shapes are skipped."""
    env = os.environ if environ is None else environ
    p = Path(path).expanduser()
    data = json.loads(p.read_text())
    root = p.parent
    entries = data.get("env_vars", data if isinstance(data, list) else [])
    applied: dict[str, str] = {}
    for e in entries:
        if not isinstance(e, dict) or "key" not in e:
            continue
        key, typ = e["key"], e.get("type", "string")
        if typ == "relative_paths":
            val = os.pathsep.join(str(root / v) for v in e.get("values", []))
        elif typ == "relative_path":
            val = str(root / e.get("value", ""))
        else:
            val = str(e.get("value", ""))
        if e.get("existing_value_treatment") == "prepend_to" and env.get(key):
            val = val + os.pathsep + env[key]
        env[key] = val
        applied[key] = val
    return applied
