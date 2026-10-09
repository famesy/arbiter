"""Extensibility: driver registry, plugin discovery, and command-template drivers.

Three ways to customise a board, from lightest to heaviest:

1. **Override one action** on any driver with your own command:

       [board.commands]
       reset = "nrfutil device reset --serial-number {serial} --reset-kind RESET_PIN"
       flash = ["my-flash-tool", "--sn", "{serial}", "{hex}"]

2. **A board made only of commands** (`driver = "command"`): every action is a
   command template; the console is a UART port and/or a command's stdout.

3. **A full driver as a plugin**: a Python class subclassing
   `arbiter.drivers.base.BoardDriver`, found through the `arbiter.drivers`
   entry-point group (`pip install` a package that declares it), or named
   directly as `driver = "my_module:MyDriver"` (with `daemon.plugin_paths` to
   add a folder to the import path). Power devices work the same way with the
   `arbiter.power` group, `kind = "command"`, or `kind = "my_module:MyPower"`.

Command templates are an argv list or a string (split like a shell would, but
never run through a shell). `{placeholders}` are filled from the action's
context; an argument that renders to an empty string is dropped, so optional
flags can be written as e.g. "{erase}". Literal braces are written doubled
("{{" and "}}"), as in Python's str.format. Available placeholders:

    board platform serial port build_dir domain hex elf bin erase halt
    mv ma on duration_ms duration_s trace state_dir

A command's exit code decides success. `present` and `check_alive` commands
signal "yes" with exit code 0. A `measure` command prints JSON on its last
line: either a summary (`avg_ua`, `min_ua`, `max_ua`, ...) or raw samples
(`{"samples_ua": [...], "rate_hz": 1000}`).
"""

from __future__ import annotations

import asyncio
import importlib
import json
import shlex
import sys
from collections.abc import Callable
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, cast

from .config import BoardConfig, PowerConfig
from .console.hub import ConsoleHub
from .console.sources import UartSource
from .errors import ArbiterError
from .power import Measurement, NativePower, PowerDevice, Ppk2Power, SimPower, summarize
from .procs import IS_WINDOWS, run_proc

DriverFactory = Callable[..., Any]  # (cfg, hub, state_dir) -> BoardDriver
PowerFactory = Callable[..., Any]  # (cfg, driver) -> PowerDevice

ACTIONS = ("flash", "reset", "reset_halt", "recover", "check_alive", "present")
POWER_ACTIONS = ("on", "off", "set_voltage", "set_current_limit", "measure")


# ------------------------------------------------------------------ registry
def _builtin_drivers() -> dict[str, DriverFactory]:
    from .drivers.emulator import EmulatorDriver
    from .drivers.native_sim import NativeSimDriver
    from .drivers.sim import SimDriver
    from .drivers.west import NrfDriver, Stm32Driver, WestDriver

    return {
        "sim": SimDriver,
        "native_sim": NativeSimDriver,
        "emulator": EmulatorDriver,
        "qemu": EmulatorDriver,
        "renode": EmulatorDriver,
        "west": WestDriver,
        "nrf": NrfDriver,
        "stm32": Stm32Driver,
        "command": CommandDriver,
    }


def _builtin_power() -> dict[str, PowerFactory]:
    return {
        "sim": lambda cfg, drv: SimPower(
            cfg, board=drv if hasattr(drv, "set_power") else None, speed=getattr(drv, "speed", 1.0)
        ),
        "native": NativePower,
        "ppk2": lambda cfg, drv: Ppk2Power(cfg),
        "command": CommandPower,
    }


def _entry_points(group: str) -> dict[str, Any]:
    return {ep.name: ep for ep in entry_points(group=group)}


def _load_dotted(spec: str, extra_paths: list[str]) -> Any:
    mod_name, _, attr = spec.partition(":")
    for p in extra_paths:
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        obj = importlib.import_module(mod_name)
        for part in attr.split("."):
            obj = getattr(obj, part)
    except (ImportError, AttributeError) as e:
        raise ValueError(f"cannot load plugin {spec!r}: {e}") from e
    return obj


def resolve_driver(name: str, extra_paths: list[str] | None = None) -> DriverFactory:
    builtins = _builtin_drivers()
    if name in builtins:
        return builtins[name]
    factory: DriverFactory
    if ":" in name:
        factory = _load_dotted(name, extra_paths or [])
        return factory
    eps = _entry_points("arbiter.drivers")
    if name in eps:
        factory = eps[name].load()
        return factory
    raise ValueError(
        f"unknown driver {name!r}; built-in: {sorted(builtins)}, plugins: {sorted(eps)}"
    )


def resolve_power(kind: str, extra_paths: list[str] | None = None) -> PowerFactory:
    builtins = _builtin_power()
    if kind in builtins:
        return builtins[kind]
    if ":" in kind:
        cls = _load_dotted(kind, extra_paths or [])
    else:
        eps = _entry_points("arbiter.power")
        if kind not in eps:
            raise ValueError(
                f"unknown power kind {kind!r}; built-in: {sorted(builtins)}, plugins: {sorted(eps)}"
            )
        cls = eps[kind].load()
    return lambda cfg, drv: cls(cfg, drv) if _takes_two(cls) else cls(cfg)


def _takes_two(cls: Any) -> bool:
    import inspect

    try:
        params = [
            p
            for p in inspect.signature(cls).parameters.values()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        ]
    except (TypeError, ValueError):
        return False
    return len(params) >= 2


def available() -> dict[str, list[str]]:
    return {
        "drivers": sorted(set(_builtin_drivers()) | set(_entry_points("arbiter.drivers"))),
        "power": sorted(set(_builtin_power()) | set(_entry_points("arbiter.power"))),
    }


def loaded(boards: list[BoardConfig], extra_paths: list[str] | None = None) -> list[dict[str, Any]]:
    """Every driver and power plugin arbiter can see, whether it imports, and which boards
    use it. Built-ins, installed entry points, and `module:Class` names boards refer to."""
    from . import __version__

    out: list[dict[str, Any]] = []

    def used(kind: str, name: str) -> list[str]:
        if kind == "driver":
            return [b.id for b in boards if b.driver == name]
        return [b.id for b in boards if b.power.kind == name]

    def row(name: str, kind: str, source: str, module: str, version: str | None) -> dict[str, Any]:
        return {
            "name": name,
            "kind": kind,
            "source": source,
            "module": module,
            "version": version,
            "ok": True,
            "error": None,
            "used_by": used(kind, name),
        }

    for kind, builtins, group in (
        ("driver", _builtin_drivers(), "arbiter.drivers"),
        ("power", _builtin_power(), "arbiter.power"),
    ):
        for name, factory in sorted(builtins.items()):
            module = getattr(factory, "__module__", "arbiter.plugins")
            if module == __name__ and getattr(factory, "__name__", "") == "<lambda>":
                module = "arbiter.power"
            out.append(row(name, kind, "builtin", module, __version__))
        for name, ep in sorted(_entry_points(group).items()):
            if name in builtins:
                continue
            dist = getattr(ep, "dist", None)
            r = row(
                name, kind, "entry_point", ep.value.split(":")[0], dist.version if dist else None
            )
            try:
                ep.load()
            except Exception as e:
                r["ok"], r["error"] = False, f"{type(e).__name__}: {e}"
            out.append(r)
        names = {b.driver for b in boards} if kind == "driver" else {b.power.kind for b in boards}
        for name in sorted(n for n in names if ":" in n):
            r = row(name, kind, "path", name.split(":")[0], None)
            try:
                _load_dotted(name, extra_paths or [])
            except Exception as e:
                r["ok"], r["error"] = False, f"{type(e).__name__}: {e}"
            out.append(r)
    return out


def make_driver(
    cfg: BoardConfig, hub: ConsoleHub, state_dir: Path, extra_paths: list[str] | None = None
) -> BoardDriver:
    factory = resolve_driver(cfg.driver, extra_paths)
    driver = factory(cfg, hub, state_dir)
    if not isinstance(driver, BoardDriver):
        raise TypeError(f"driver {cfg.driver!r} did not produce a BoardDriver")
    overrides = (
        {k: v for k, v in cfg.commands.items() if k in ACTIONS} if cfg.driver != "command" else {}
    )
    unknown = set(cfg.commands) - set(ACTIONS)
    if unknown:
        raise ValueError(
            f"board {cfg.id}: unknown command actions {sorted(unknown)}; allowed: {ACTIONS}"
        )
    # The overlay delegates everything it does not override, so it stands in for a BoardDriver.
    return cast("BoardDriver", CommandOverlay(driver, overrides)) if overrides else driver


def make_power_device(
    cfg: PowerConfig, driver: Any, extra_paths: list[str] | None = None
) -> PowerDevice | None:
    if cfg.kind in ("none", "", None):
        return None
    device = resolve_power(cfg.kind, extra_paths)(cfg, driver)
    if not isinstance(device, PowerDevice):
        raise TypeError(f"power kind {cfg.kind!r} did not produce a PowerDevice")
    return device


# ------------------------------------------------------------------ templates
def split_command(template: str) -> list[str]:
    """Split a command string into argv. On Windows, backslashes in paths stay as they are
    and double quotes only group words (they are removed, as the C runtime does)."""
    if not IS_WINDOWS:
        return shlex.split(template)
    parts = shlex.split(template, posix=False)
    return [p[1:-1] if len(p) >= 2 and p[0] == p[-1] == '"' else p for p in parts]


def render(template: Any, ctx: dict[str, Any]) -> list[str]:
    if isinstance(template, str):
        parts = split_command(template)
    elif isinstance(template, list):
        parts = [str(p) for p in template]
    else:
        raise ArbiterError("BAD_REQUEST", f"command must be a string or a list, got {template!r}")
    out = []
    for p in parts:
        try:
            s = p.format_map(_Ctx(ctx))
        except (KeyError, ValueError, IndexError) as e:
            raise ArbiterError("OP_FAILED", f"bad placeholder in command {p!r}: {e}") from None
        if s != "":
            out.append(s)
    return out


class _Ctx(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        raise KeyError(key)


def build_paths(build_dir: Path | None) -> dict[str, str]:
    if not build_dir:
        return {"build_dir": "", "hex": "", "elf": "", "bin": ""}
    b = Path(build_dir)

    def first(*cands: Path) -> str:
        for c in cands:
            if c.exists():
                return str(c)
        return str(cands[-1])

    return {
        "build_dir": str(b),
        "hex": first(b / "merged.hex", b / "zephyr" / "merged.hex", b / "zephyr" / "zephyr.hex"),
        "elf": first(b / "zephyr" / "zephyr.elf"),
        "bin": first(b / "zephyr" / "zephyr.bin"),
    }


def board_ctx(driver: Any, **extra: Any) -> dict[str, Any]:
    cfg: BoardConfig = driver.cfg
    port = ""
    resolver = getattr(driver, "resolve_app_port", None)
    if resolver:
        try:
            port = resolver() or ""
        except Exception:
            port = ""
    ctx = {
        "board": cfg.id,
        "platform": cfg.platform,
        "serial": cfg.probe_serial or "",
        "port": port,
        "domain": "",
        "erase": "",
        "halt": "",
        "mv": "",
        "ma": "",
        "on": "",
        "duration_ms": "",
        "duration_s": "",
        "trace": "",
        "state_dir": str(getattr(driver, "state_dir", "") or ""),
    }
    ctx.update(build_paths(None))
    ctx.update({k: ("" if v is None else v) for k, v in extra.items()})
    return ctx


async def run_template(
    template: Any,
    ctx: dict[str, Any],
    log_path: Path,
    timeout_s: float = 300,
    cwd: Path | None = None,
) -> dict[str, Any]:
    argv = render(template, ctx)
    if not argv:
        raise ArbiterError("OP_FAILED", "command rendered to nothing")
    res = await run_proc(argv, cwd=cwd, timeout_s=timeout_s, log_path=log_path)
    return res.summary()


# ------------------------------------------------------------------ command driver
from .drivers.base import (  # noqa: E402  (after helpers to avoid an import cycle)
    BoardDriver,
    LineFn,
)


class CommandDriver(BoardDriver):
    """A board defined entirely by command templates in `[board.commands]`.

    Console: `[[board.port]]` entries (a port name or probe serial + interface)
    attach a UART reader, like the west drivers."""

    kind = "command"

    def __init__(self, cfg: BoardConfig, hub: ConsoleHub, state_dir: Path | None = None):
        super().__init__(cfg, hub, state_dir)
        self.cmds = dict(cfg.commands)
        caps = {"run"}
        if "flash" in self.cmds:
            caps.add("flash")
        if "reset" in self.cmds:
            caps.add("reset")
        if "reset_halt" in self.cmds:
            caps.add("halt")
        if "recover" in self.cmds:
            caps.add("recover")
        if cfg.ports:
            caps.add("console")
        self.capabilities = frozenset(caps)

    def resolve_app_port(self) -> str | None:
        from .drivers import discovery

        p = next(
            (p for p in self.cfg.ports if p.role == "app"),
            self.cfg.ports[0] if self.cfg.ports else None,
        )
        if p is None:
            return None
        if p.port:
            return p.port
        return (
            discovery.resolve_port(self.cfg.probe_serial, p.interface)
            if self.cfg.probe_serial
            else None
        )

    async def start(self) -> None:
        if self.cfg.ports:
            await self.hub.attach(UartSource(self.resolve_app_port, self.cfg.ports[0].baud))

    async def present(self) -> bool:
        if "present" in self.cmds:
            res = await run_proc(render(self.cmds["present"], board_ctx(self)), timeout_s=10)
            return res.ok
        if self.cfg.probe_serial:
            from .drivers import discovery

            return discovery.present(self.cfg.probe_serial)
        return True

    async def flash(
        self,
        build_dir: Path,
        *,
        domain: str | None,
        erase: bool,
        cwd: Path | None,
        log_path: Path,
        on_line: LineFn,
    ) -> dict[str, Any]:
        return await command_flash(
            self, self.cmds["flash"], build_dir, domain, erase, cwd, log_path
        )

    async def reset(self, *, halt: bool, log_path: Path) -> dict[str, Any]:
        key = "reset_halt" if halt else "reset"
        if key not in self.cmds:
            raise ArbiterError("NOT_SUPPORTED", f"no {key} command configured for {self.cfg.id}")
        return await run_template(
            self.cmds[key], board_ctx(self, halt="1" if halt else ""), log_path, 60
        )

    async def recover(self, *, log_path: Path) -> dict[str, Any]:
        if "recover" not in self.cmds:
            raise ArbiterError("NOT_SUPPORTED", f"no recover command configured for {self.cfg.id}")
        return await run_template(self.cmds["recover"], board_ctx(self), log_path, 300)

    async def check_alive(self) -> bool:
        if "check_alive" in self.cmds:
            return (
                await run_proc(render(self.cmds["check_alive"], board_ctx(self)), timeout_s=30)
            ).ok
        return await self.present()


async def command_flash(
    driver: Any,
    template: Any,
    build_dir: Path,
    domain: str | None,
    erase: bool,
    cwd: Path | None,
    log_path: Path,
) -> dict[str, Any]:
    from .console.detect import detect_from_build

    if not await asyncio.to_thread(Path(build_dir).exists):
        raise ArbiterError("OP_FAILED", f"build dir not found: {build_dir}")
    ctx = board_ctx(driver, domain=domain or "", erase="--erase" if erase else "")
    ctx.update(build_paths(Path(build_dir)))
    res = await run_template(template, ctx, log_path, 300, cwd=cwd or Path(build_dir).parent)
    if res.get("ok"):
        cmap = detect_from_build(Path(build_dir))
        await driver.set_console(cmap)
        res["console"] = cmap.to_dict()
    return res


class CommandOverlay:
    """Wraps any driver and replaces selected actions with command templates."""

    def __init__(self, inner: BoardDriver, commands: dict[str, Any]):
        self._inner = inner
        self._cmds = commands
        caps = set(inner.capabilities)
        caps.update({"flash"} if "flash" in commands else set())
        caps.update({"reset"} if "reset" in commands else set())
        caps.update({"halt"} if "reset_halt" in commands else set())
        caps.update({"recover"} if "recover" in commands else set())
        self.capabilities = frozenset(caps)

    def update_commands(self, commands: dict[str, Any]) -> None:
        """New templates for the actions already overridden (Settings page edits)."""
        for k in self._cmds:
            if k in commands:
                self._cmds[k] = commands[k]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def describe(self) -> dict[str, Any]:
        d = self._inner.describe()
        d["capabilities"] = sorted(self.capabilities)
        d["overrides"] = sorted(self._cmds)
        return d

    async def flash(
        self,
        build_dir: Path,
        *,
        domain: str | None,
        erase: bool,
        cwd: Path | None,
        log_path: Path,
        on_line: LineFn,
    ) -> dict[str, Any]:
        if "flash" not in self._cmds:
            return await self._inner.flash(
                build_dir, domain=domain, erase=erase, cwd=cwd, log_path=log_path, on_line=on_line
            )
        return await command_flash(
            self._inner, self._cmds["flash"], build_dir, domain, erase, cwd, log_path
        )

    async def reset(self, *, halt: bool, log_path: Path) -> dict[str, Any]:
        key = "reset_halt" if halt else "reset"
        if key not in self._cmds:
            return await self._inner.reset(halt=halt, log_path=log_path)
        return await run_template(
            self._cmds[key], board_ctx(self._inner, halt="1" if halt else ""), log_path, 60
        )

    async def recover(self, *, log_path: Path) -> dict[str, Any]:
        if "recover" not in self._cmds:
            return await self._inner.recover(log_path=log_path)
        return await run_template(self._cmds["recover"], board_ctx(self._inner), log_path, 300)

    async def check_alive(self) -> bool:
        if "check_alive" not in self._cmds:
            return await self._inner.check_alive()
        return (
            await run_proc(render(self._cmds["check_alive"], board_ctx(self._inner)), timeout_s=30)
        ).ok

    async def present(self) -> bool:
        if "present" not in self._cmds:
            return await self._inner.present()
        return (
            await run_proc(render(self._cmds["present"], board_ctx(self._inner)), timeout_s=10)
        ).ok


# ------------------------------------------------------------------ command power
class CommandPower(PowerDevice):
    """A power supply driven by your own scripts:

    [board.power]
    kind = "command"
    mv_min = 3000
    mv_max = 5000
    default_mv = 3700
    ma_max = 200
    [board.power.commands]
    on = "psu-ctl --addr 192.168.1.50 output on"
    off = "psu-ctl --addr 192.168.1.50 output off"
    set_voltage = "psu-ctl --addr 192.168.1.50 volt {mv}"
    set_current_limit = "psu-ctl --addr 192.168.1.50 ilim {ma}"
    measure = "my-meter --ms {duration_ms} --json"

    `set_current_limit` runs once at start with `ma_max`, so the supply itself cuts
    off on over-current, not only arbiter after a measurement.
    """

    kind = "command"

    def __init__(self, cfg: PowerConfig, driver: Any = None):
        super().__init__(cfg)
        self.driver = driver
        unknown = set(cfg.commands) - set(POWER_ACTIONS)
        if unknown:
            raise ValueError(
                f"unknown power command actions {sorted(unknown)}; allowed: {POWER_ACTIONS}"
            )
        sup = set()
        if "on" in cfg.commands and "off" in cfg.commands:
            sup.add("switch")
        if "set_voltage" in cfg.commands:
            sup.add("voltage")
        if "measure" in cfg.commands:
            sup.add("measure")
        self.supports = frozenset(sup)
        self.log_dir: Path | None = None

    async def start(self) -> None:
        if self.cfg.ma_max and "set_current_limit" in self.cfg.commands:
            await self._run("set_current_limit", ma=_num(self.cfg.ma_max))

    def _ctx(self, **kw: Any) -> dict[str, Any]:
        base = board_ctx(self.driver) if self.driver is not None else {}
        return {**base, **{k: str(v) for k, v in kw.items()}}

    def _log(self) -> Path:
        d = (getattr(self.driver, "state_dir", None) or Path.cwd()) / "logs" / "power"
        return d / f"{self.driver.cfg.id if self.driver else 'power'}.log"

    async def _run(self, action: str, **kw: Any) -> dict[str, Any]:
        res = await run_template(self.cfg.commands[action], self._ctx(**kw), self._log(), 120)
        if not res["ok"]:
            raise ArbiterError(
                "OP_FAILED",
                f"power {action} command failed (exit {res['exit_code']})",
                tail=res["tail"][-5:],
            )
        return res

    async def set_output(self, on: bool) -> None:
        if "switch" not in self.supports:
            raise ArbiterError("NOT_SUPPORTED", "no on/off commands configured")
        await self._run("on" if on else "off", on="on" if on else "off")
        self.on, self.state = on, "ON" if on else "OFF"

    async def set_voltage(self, mv: int) -> None:
        if "voltage" not in self.supports:
            raise ArbiterError("NOT_SUPPORTED", "no set_voltage command configured")
        await self._run("set_voltage", mv=mv)
        self.mv = mv

    async def measure(
        self,
        duration_ms: int,
        trace_path: Path,
        threshold_ua: float | None = None,
        debug_attached: bool = False,
    ) -> Measurement:
        if "measure" not in self.supports:
            raise ArbiterError("NOT_SUPPORTED", "no measure command configured")
        self.state = "MEASURING"
        try:
            res = await run_template(
                self.cfg.commands["measure"],
                self._ctx(duration_ms=duration_ms, duration_s=duration_ms / 1000, trace=trace_path),
                self._log(),
                duration_ms / 1000 + 60,
            )
        finally:
            self.state = "ON" if self.on else "OFF"
        if not res["ok"]:
            raise ArbiterError(
                "OP_FAILED",
                f"measure command failed (exit {res['exit_code']})",
                tail=res["tail"][-5:],
            )
        data = None
        for raw in reversed(res["tail"]):
            line = raw.strip()
            if line.startswith("{"):
                try:
                    data = json.loads(line)
                    break
                except ValueError:
                    continue
        if data is None:
            raise ArbiterError("OP_FAILED", "measure command printed no JSON line")
        if "samples_ua" in data:
            m = summarize(
                [float(x) for x in data["samples_ua"]],
                float(data.get("rate_hz", 1000)),
                threshold_ua,
                trace_path,
            )
        else:
            m = Measurement(
                duration_ms=float(data.get("duration_ms", duration_ms)),
                samples=int(data.get("samples", 0)),
                avg_ua=float(data["avg_ua"]),
                min_ua=float(data.get("min_ua", data["avg_ua"])),
                max_ua=float(data.get("max_ua", data["avg_ua"])),
                peak_ua=float(data.get("peak_ua", data.get("max_ua", data["avg_ua"]))),
                charge_uc=float(data.get("charge_uc", data["avg_ua"] * duration_ms / 1000)),
                trace_path=data.get("trace_path")
                or (str(trace_path) if await asyncio.to_thread(trace_path.exists) else None),
            )
        if debug_attached:
            m.valid, m.invalid_reason = False, "debugger or RTT was attached during the measurement"
        self.last = m
        return m


def _num(x: float) -> str:
    """200.0 -> "200", 0.5 -> "0.5": what a command line expects."""
    return f"{x:g}"
