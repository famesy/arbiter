"""Find the west workspace and ZEPHYR_BASE a build belongs to.

`west flash` is an extension command that only exists inside a west workspace. The
daemon runs west for builds anywhere on disk (a freestanding NCS app is the normal
layout), so it can't rely on its own working directory. The build itself records
which Zephyr it was made with, in CMakeCache.txt."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .console.detect import image_dirs


def cache_value(cache: Path, key: str) -> str | None:
    """A value from a CMakeCache.txt (`KEY:TYPE=value`)."""
    try:
        text = cache.read_text(errors="replace")
    except OSError:
        return None
    prefix = key + ":"
    for line in text.splitlines():
        if line.startswith(prefix) and "=" in line:
            return line.split("=", 1)[1].strip() or None
    return None


def build_python(image_dir: Path, build_dir: Path) -> list[str]:
    """The Python the build used, to run Zephyr's scripts. CMake records it as
    Python3_EXECUTABLE, or only as the internal _Python3_EXECUTABLE (NCS v3.4.1). Without
    one, arbiter's own Python with -E: an NCS toolchain environment.json sets PYTHONPATH to
    the bundle's standard library, which crashes a different Python build on Windows."""
    for cache in (Path(image_dir) / "CMakeCache.txt", Path(build_dir) / "CMakeCache.txt"):
        for key in ("Python3_EXECUTABLE", "_Python3_EXECUTABLE"):
            py = cache_value(cache, key)
            if py and Path(py).exists():
                return [py]
    return [sys.executable, "-E"]


def zephyr_base_from_build(build_dir: Path) -> Path | None:
    """ZEPHYR_BASE recorded by the build: the default image's cache, then the top-level
    (sysbuild) cache."""
    build_dir = Path(build_dir)
    dirs = [d for _name, d in image_dirs(build_dir)] + [build_dir]
    for d in dirs:
        value = cache_value(d / "CMakeCache.txt", "ZEPHYR_BASE")
        if value and Path(value).is_dir():
            return Path(value)
    return None


def west_topdir(start: Path | None) -> Path | None:
    """The workspace root (the folder holding .west) at or above `start`."""
    if start is None:
        return None
    p = Path(start).resolve()
    for d in (p, *p.parents):
        if (d / ".west").is_dir():
            return d
    return None


def west_context(
    build_dir: Path | None, configured: str | None, cwd: Path | None
) -> tuple[dict[str, str], Path | None]:
    """Environment and working directory to run west in, for this build.

    ZEPHYR_BASE comes from the build, then the board or daemon config, then the
    environment. West runs in the caller's directory if that is inside a workspace,
    otherwise in the workspace that holds ZEPHYR_BASE."""
    base = zephyr_base_from_build(build_dir) if build_dir else None
    if base is None and configured:
        base = Path(configured).expanduser()
    if base is None and os.environ.get("ZEPHYR_BASE"):
        base = Path(os.environ["ZEPHYR_BASE"])
    env = {"ZEPHYR_BASE": str(base)} if base else {}
    run_in = cwd if west_topdir(cwd) else west_topdir(base)
    return env, run_in or cwd


def zephyr_base_for_run(cmd: list[str], cwd: Path | None, known: str | None) -> str | None:
    """ZEPHYR_BASE for a test command (west twister, ...) run from `cwd`, when west can't
    find a workspace from `cwd` itself: the one the board last flashed with or is
    configured with, the daemon's environment, or the workspace holding a path named in
    the command (e.g. `-T C:/ncs/v3.4.1/zephyr/samples/hello_world`)."""
    if west_topdir(cwd):
        return None  # west finds its workspace on its own
    if known:
        return known
    if os.environ.get("ZEPHYR_BASE"):
        return os.environ["ZEPHYR_BASE"]
    for arg in cmd[1:]:
        value = arg.split("=", 1)[1] if arg.startswith("-") and "=" in arg else arg
        if value.startswith("-") or not value:
            continue
        p = Path(value)
        if not p.is_absolute() and cwd is not None:
            p = cwd / p
        try:
            top = west_topdir(p) if p.exists() else None
        except OSError:
            top = None
        if top and (top / "zephyr").is_dir():
            return str(top / "zephyr")
    return None
