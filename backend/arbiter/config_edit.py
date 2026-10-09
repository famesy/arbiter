"""Reading and editing config.toml from the dashboard's Settings page.

The page addresses settings with dotted paths over this view of the config:

    daemon.<key>                      [daemon]
    timing.<key>                      [timing]
    boards.<id>                       a whole [[board]] (a dict, or null to remove it)
    boards.<id>.<key>                 a board key; dict keys (options, commands, tools)
    boards.<id>.power.<key>             can be addressed one level deeper
    boards.<id>.ports                 every [[board.port]], replaced as one list

An edit is validated on the whole merged config, as strictly as daemon start-up,
before anything is written."""

from __future__ import annotations

import contextlib
import copy
import dataclasses
import hashlib
import re
import tomllib
import types
import typing
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

import tomlkit
import tomlkit.items

from .config import BoardConfig, PortConfig, PowerConfig, config_from_dict
from .scheduler import Timing

# Settings the daemon applies without a restart.
LIVE = (
    "boards.*.power.mv_min",
    "boards.*.power.mv_max",
    "boards.*.power.default_mv",
    "boards.*.power.ma_max",
    "boards.*.power.allow_agent_raise_voltage",
    "boards.*.allow_agent_erase",
    "boards.*.max_lease_min",
    "boards.*.tags",
    "boards.*.commands",
    "boards.*.commands.*",
    "timing.*",
)
DAEMON_KEYS: dict[str, Any] = {
    "host": str,
    "port": int,
    "human_name": str,
    "plugin_paths": list[str],
    "toolchain_env": str | None,
    "zephyr_base": str | None,
    "state_dir": str,
}
SECRET_RX = re.compile(r"pass(word|wd)?|token|secret|api_?key|credential", re.IGNORECASE)
REDACTED = "***"


class ConfigError(Exception):
    """An edit that can't be applied; `errors` are {"path", "message"} entries."""

    def __init__(self, errors: list[dict[str, str]]):
        super().__init__("; ".join(f"{e['path']}: {e['message']}" for e in errors))
        self.errors = errors


def version_of(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def is_live(path: str) -> bool:
    return any(fnmatchcase(path, pat) for pat in LIVE)


# ------------------------------------------------------------------ view
def _redact(d: dict[str, Any]) -> dict[str, Any]:
    return {k: REDACTED if SECRET_RX.search(k) and v not in (None, "") else v for k, v in d.items()}


def _defaults(cls: type[Any], raw: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for f in dataclasses.fields(cls):
        if f.name in raw:
            out[f.name] = raw[f.name]
        elif f.default is not dataclasses.MISSING:
            out[f.name] = f.default
        elif f.default_factory is not dataclasses.MISSING:
            out[f.name] = f.default_factory()
    return out


def board_view(raw: dict[str, Any]) -> dict[str, Any]:
    """A [[board]] with every key filled in, as the Settings page shows it."""
    b = _defaults(BoardConfig, {k: v for k, v in raw.items() if k not in ("port", "power")})
    b["ports"] = [_defaults(PortConfig, p) for p in raw.get("port", [])]
    power = _defaults(PowerConfig, raw.get("power", {}))
    power["options"] = _redact(power["options"])
    b["power"] = power
    b["options"] = _redact(b["options"])
    return b


def view(raw: dict[str, Any]) -> dict[str, Any]:
    """The Settings view of raw TOML data."""
    d = raw.get("daemon", {})
    daemon = {
        "host": d.get("host", "127.0.0.1"),
        "port": d.get("port", 7777),
        "human_name": d.get("human_name", "human"),
        "toolchain_env": d.get("toolchain_env"),
        "zephyr_base": d.get("zephyr_base"),
        "plugin_paths": d.get("plugin_paths", []),
    }
    if "state_dir" in d:
        daemon["state_dir"] = d["state_dir"]
    return {
        "daemon": daemon,
        "timing": _defaults(Timing, raw.get("timing", {})),
        "boards": [board_view(b) for b in raw.get("board", [])],
        "live": list(LIVE),
    }


def raw_from_config(cfg: Any) -> dict[str, Any]:
    """Raw TOML data for a running Config (used when there is no file yet)."""
    boards = []
    for bc in cfg.boards:
        b = {
            k: v
            for k, v in dataclasses.asdict(bc).items()
            if k not in ("ports", "power") and v not in (None, [], {})
        }
        if bc.ports:
            b["port"] = [
                {k: v for k, v in dataclasses.asdict(p).items() if v is not None} for p in bc.ports
            ]
        if bc.power.kind != "none":
            b["power"] = {
                k: v for k, v in dataclasses.asdict(bc.power).items() if v not in (None, [], {})
            }
        boards.append(b)
    raw: dict[str, Any] = {
        "daemon": {"host": cfg.host, "port": cfg.port, "human_name": cfg.human_name}
    }
    if boards:
        raw["board"] = boards
    return raw


# ------------------------------------------------------------------ edit
def _board_index(raw: dict[str, Any], board_id: str) -> int | None:
    for i, b in enumerate(raw.get("board", [])):
        if b.get("id") == board_id:
            return i
    return None


def apply_sets(raw: dict[str, Any], sets: dict[str, Any]) -> dict[str, Any]:
    """A copy of `raw` with the dotted-path edits applied. A null value removes the key
    (or the whole board), going back to the default."""
    new = copy.deepcopy(raw)
    errors: list[dict[str, str]] = []
    for path, value in sets.items():
        try:
            _apply_one(new, path, value)
        except ValueError as e:
            errors.append({"path": path, "message": str(e)})
    if errors:
        raise ConfigError(errors)
    return new


def _set(d: dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        d.pop(key, None)
    else:
        d[key] = value


def _apply_one(raw: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    head = parts[0]
    if head in ("daemon", "timing"):
        if len(parts) != 2:
            raise ValueError(f"use {head}.<key>")
        _set(raw.setdefault(head, {}), parts[1], value)
        if not raw[head]:
            del raw[head]
        return
    if head != "boards" or len(parts) < 2 or not parts[1]:
        raise ValueError("paths start with daemon., timing. or boards.<id>")
    board_id, rest = parts[1], parts[2:]
    boards = raw.setdefault("board", [])
    i = _board_index(raw, board_id)
    if not rest:  # the whole board
        if value is None:
            if i is None:
                raise ValueError(f"no board {board_id!r}")
            del boards[i]
            return
        if not isinstance(value, dict):
            raise ValueError("a board is an object")
        b = dict(value)
        if "ports" in b:
            b["port"] = b.pop("ports")
        if b.get("id", board_id) != board_id:
            raise ValueError(f"id {b['id']!r} does not match the path")
        b.pop("id", None)
        b = {"id": board_id, **b}
        if i is None:
            boards.append(b)
        else:
            boards[i] = b
        return
    if i is None:
        raise ValueError(f"no board {board_id!r}; add it with boards.{board_id}")
    board = boards[i]
    key = rest[0]
    if key == "id":
        raise ValueError("a board's id can't be changed; add a new board and remove this one")
    if key == "ports":
        if len(rest) != 1:
            raise ValueError("ports are replaced as a whole list")
        if value is not None and not isinstance(value, list):
            raise ValueError("ports is a list")
        _set(board, "port", value)
        return
    if len(rest) == 1:
        _set(board, key, value)
        return
    if key == "power" and len(rest) in (2, 3):
        power = board.setdefault("power", {})
        if len(rest) == 2:
            _set(power, rest[1], value)
        elif rest[1] in ("options", "commands"):
            _set(power.setdefault(rest[1], {}), rest[2], value)
        else:
            raise ValueError("too deep")
        return
    if key in ("options", "commands", "tools") and len(rest) == 2:
        _set(board.setdefault(key, {}), rest[1], value)
        return
    raise ValueError("unknown or too deep a path")


# ------------------------------------------------------------------ validate
def _type_ok(value: Any, tp: Any) -> bool:
    if tp is Any:
        return True
    origin = typing.get_origin(tp)
    if origin in (typing.Union, types.UnionType):
        return any(_type_ok(value, a) for a in typing.get_args(tp))
    if tp is type(None):
        return value is None
    if tp is bool:
        return isinstance(value, bool)
    if tp is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if tp is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if tp in (str, Path):
        return isinstance(value, str)
    if origin is list:
        (item,) = typing.get_args(tp) or (Any,)
        return isinstance(value, list) and all(_type_ok(v, item) for v in value)
    if origin is dict:
        return isinstance(value, dict)
    return True


def _type_name(tp: Any) -> str:
    return str(tp).replace("typing.", "").replace("<class '", "").replace("'>", "")


def _check_section(
    raw: dict[str, Any], types_: dict[str, Any], prefix: str, skip: tuple[str, ...] = ()
) -> list[dict[str, str]]:
    errors = []
    for k, v in raw.items():
        if k in skip:
            continue
        path = f"{prefix}.{k}"
        if k not in types_:
            errors.append({"path": path, "message": "unknown setting"})
        elif not _type_ok(v, types_[k]):
            errors.append({"path": path, "message": f"must be {_type_name(types_[k])}"})
    return errors


def _hints(cls: type[Any]) -> dict[str, Any]:
    return typing.get_type_hints(cls)


def validate(raw: dict[str, Any], extra_paths: list[str] | None = None) -> list[dict[str, str]]:
    """Every problem in raw TOML data, by Settings path. Empty when the daemon would start."""
    from .plugins import resolve_driver, resolve_power

    errors = _check_section(raw.get("daemon", {}), DAEMON_KEYS, "daemon")
    errors += _check_section(raw.get("timing", {}), _hints(Timing), "timing")
    for k in raw:
        if k not in ("daemon", "timing", "board"):
            errors.append({"path": k, "message": "unknown section"})
    seen: set[str] = set()
    paths = (
        extra_paths if extra_paths is not None else raw.get("daemon", {}).get("plugin_paths", [])
    )
    for b in raw.get("board", []):
        bid = b.get("id")
        if not isinstance(bid, str) or not bid or "." in bid:
            errors.append({"path": f"boards.{bid}.id", "message": "needs an id without dots"})
            continue
        pre = f"boards.{bid}"
        if bid in seen:
            errors.append({"path": pre, "message": "board ids must be unique"})
        seen.add(bid)
        errors += _check_section(b, _hints(BoardConfig), pre, skip=("port", "power", "ports"))
        for n, p in enumerate(b.get("port", [])):
            if not isinstance(p, dict):
                errors.append({"path": f"{pre}.ports", "message": f"port {n} is not an object"})
                continue
            errors += [
                {
                    "path": f"{pre}.ports",
                    "message": f"port {n}: {e['path'].split('.')[-1]} {e['message']}",
                }
                for e in _check_section(p, _hints(PortConfig), "port")
            ]
        power = b.get("power", {})
        errors += _check_section(power, _hints(PowerConfig), f"{pre}.power")
        errors += _check_limits(pre, power)
        try:
            resolve_driver(str(b.get("driver", "sim")), paths)
        except Exception as e:
            errors.append({"path": f"{pre}.driver", "message": str(e)})
        kind = str(power.get("kind", "none"))
        if kind not in ("none", ""):
            try:
                resolve_power(kind, paths)
            except Exception as e:
                errors.append({"path": f"{pre}.power.kind", "message": str(e)})
    if not errors:
        try:
            config_from_dict(raw)
        except (TypeError, ValueError) as e:
            errors.append({"path": "", "message": str(e)})
    return errors


def _check_limits(pre: str, power: dict[str, Any]) -> list[dict[str, str]]:
    d = PowerConfig()
    try:
        lo = int(power.get("mv_min", d.mv_min))
        hi = int(power.get("mv_max", d.mv_max))
        mid = int(power.get("default_mv", d.default_mv))
    except (TypeError, ValueError):
        return []  # the type check already reported it
    errors = []
    if lo > hi:
        errors.append({"path": f"{pre}.power.mv_max", "message": f"must be ≥ mv_min ({lo})"})
    elif mid > hi:
        errors.append({"path": f"{pre}.power.mv_max", "message": f"must be ≥ default_mv ({mid})"})
    elif mid < lo:
        errors.append({"path": f"{pre}.power.mv_min", "message": f"must be ≤ default_mv ({mid})"})
    ma = power.get("ma_max")
    if isinstance(ma, (int, float)) and not isinstance(ma, bool) and ma <= 0:
        errors.append({"path": f"{pre}.power.ma_max", "message": "must be above 0 mA"})
    return errors


def load_raw(text: str) -> dict[str, Any]:
    try:
        return tomllib.loads(text) if text.strip() else {}
    except tomllib.TOMLDecodeError as e:
        raise ConfigError([{"path": "", "message": f"config.toml does not parse: {e}"}]) from None


# ------------------------------------------------------------------ write
def write_atomic(path: Path, text: str, keep_backup: bool) -> None:
    """Write via a temp file and rename, keeping the previous file as <name>.bak."""
    import os

    path.parent.mkdir(parents=True, exist_ok=True)
    if keep_backup and path.exists():
        bak = path.with_name(path.name + ".bak")
        bak.write_bytes(path.read_bytes())
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def render(old_text: str, old_raw: dict[str, Any], new_raw: dict[str, Any]) -> str:
    """New file text for `new_raw`, made by editing the existing document with tomlkit so
    comments, key order and blank lines stay. Only the keys that changed are touched."""
    doc = tomlkit.parse(old_text) if old_text.strip() else tomlkit.document()
    _sync(doc, old_raw if old_text.strip() else {}, new_raw)
    text = tomlkit.dumps(doc)
    if tomllib.loads(text) != new_raw:  # never write something that reads back differently
        text = tomlkit.dumps(_item(new_raw))
    return text


def _item(v: Any) -> Any:
    """A tomlkit item for a plain value: dicts become tables, lists of dicts arrays of
    tables, so new boards and ports look like hand-written ones."""
    if isinstance(v, dict):
        t = tomlkit.table()
        for k, x in v.items():
            if x is not None:
                t.add(k, _item(x))
        return t
    if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
        aot = tomlkit.aot()
        for x in v:
            aot.append(_item(x))
        return aot
    if isinstance(v, str) and "\\" in v and "'" not in v and "\n" not in v:
        return tomlkit.string(v, literal=True)  # Windows paths read as typed
    return tomlkit.item(v)


def _sync(container: Any, old: dict[str, Any], new: dict[str, Any]) -> None:
    for k in [k for k in old if k not in new]:
        del container[k]
    for k, nv in new.items():
        ov = old.get(k)
        if k not in old:
            _add(container, k, _item(nv))
        elif ov == nv:
            continue
        elif k == "board" and isinstance(ov, list) and isinstance(nv, list):
            _sync_boards(container[k], ov, nv)
        elif isinstance(ov, dict) and isinstance(nv, dict) and isinstance(container[k], dict):
            _sync(container[k], ov, nv)
        elif isinstance(container[k], tomlkit.items.AoT) and _all_dicts(ov) and _all_dicts(nv):
            _sync_aot(container[k], list(ov or []), nv)
        else:
            container[k] = _item(nv)


def _all_dicts(v: Any) -> bool:
    return isinstance(v, list) and all(isinstance(x, dict) for x in v)


def _sync_aot(aot: Any, old: list[dict[str, Any]], new: list[dict[str, Any]]) -> None:
    """Ports: edit the ones both lists have in place, so the comments around them stay
    (tomlkit keeps a table's trailing comments, often the next section's heading, inside
    it), then drop or add at the end."""
    for i in range(min(len(old), len(new))):
        if old[i] != new[i]:
            _sync(aot[i], old[i], new[i])
    for i in reversed(range(len(new), len(old))):
        if i > 0:
            _carry_trailing(aot[i], aot[i - 1])
        del aot[i]
    for x in new[len(old) :]:
        aot.append(_item(x))


def _last_table(t: Any) -> Any:
    """The table whose end is the end of `t` in the file: its last sub-table, if any."""
    body = t.value.body
    for k, v in reversed(body):
        if k is None:
            continue
        if isinstance(v, tomlkit.items.Table):
            return _last_table(v)
        if isinstance(v, tomlkit.items.AoT) and len(v):
            return _last_table(v[-1])
        break
    return t


def _carry_trailing(src: Any, dst: Any) -> None:
    """Before deleting `src`, move the comments that end it (the next section's heading)
    to the end of `dst`, so they survive."""
    body = _last_table(src).value.body
    tail: list[Any] = []
    for k, v in reversed(body):
        if k is not None:
            break
        tail.insert(0, v)
    while tail and not isinstance(tail[0], tomlkit.items.Comment):
        tail.pop(0)  # keep only from the first comment on
    if tail:
        target = _last_table(dst)
        target.add(tomlkit.nl())
        for item in tail:
            target.add(item)


def _add(container: Any, key: str, item: Any) -> None:
    """Add a key after the table's last value, not after the comments trailing it (in
    tomlkit those comments belong to the end of the table, though they head the next)."""
    body = getattr(getattr(container, "value", container), "body", None)
    plain = not isinstance(item, (tomlkit.items.Table, tomlkit.items.AoT))
    last = None
    for k, v in body or []:
        if k is not None and not isinstance(v, (tomlkit.items.Table, tomlkit.items.AoT)):
            last = k
    if plain and last is not None:
        with contextlib.suppress(Exception):
            getattr(container, "value", container)._insert_after(last, key, item)
            return
    container.add(key, item)


def _sync_boards(aot: Any, old: list[dict[str, Any]], new: list[dict[str, Any]]) -> None:
    """Boards are matched by id, so editing one leaves the others' text alone."""
    new_ids = [b.get("id") for b in new]
    for i in reversed(range(len(old))):
        if old[i].get("id") not in new_ids:
            if i > 0:
                _carry_trailing(aot[i], aot[i - 1])
            del aot[i]
    kept = [b for b in old if b.get("id") in new_ids]
    for nb in new:
        ob = next((b for b in kept if b.get("id") == nb.get("id")), None)
        if ob is None:
            aot.append(_item(nb))
        else:
            _sync(aot[kept.index(ob)], ob, nb)
