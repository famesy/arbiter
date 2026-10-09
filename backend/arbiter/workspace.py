"""Find the west workspace and ZEPHYR_BASE a build belongs to.

`west flash` is an extension command that only exists inside a west workspace. The
daemon runs west for builds anywhere on disk (a freestanding NCS app is the normal
layout), so it can't rely on its own working directory. The build itself records
which Zephyr it was made with, in CMakeCache.txt."""

from __future__ import annotations

import os
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
