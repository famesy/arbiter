"""Run history: every flash and test run through arbiter, with the build's fingerprint
and the verdict, so an agent can ask "when did this last pass, and what changed since?".

Entries live in the daemon's store (newest last, capped). Each flashed build's .config is
copied once (by hash) under <state>/history/configs, so a later build can be diffed
against the one that last passed."""

from __future__ import annotations

import re
import secrets
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .console.detect import image_dirs, parse_kconfig
from .imageinfo import git_state
from .store import Store

KEEP = 400
KEY = "history"


class History:
    def __init__(self, store: Store | None, state: Path, keep: int = KEEP):
        self.store = store
        self.dir = state / "history" / "configs"
        self.keep = keep
        loaded = store.get(KEY) if store else None
        self.entries: list[dict[str, Any]] = loaded if isinstance(loaded, list) else []

    def record(self, entry: dict[str, Any]) -> dict[str, Any]:
        entry = {"id": "h-" + secrets.token_hex(4), "at": time.time(), **entry}
        self.entries.append(entry)
        del self.entries[: -self.keep]
        if self.store:
            self.store.put(KEY, self.entries)
        return entry

    def save_config(self, build_dir: Path, config_sha: str | None) -> str | None:
        """Keep a copy of the default image's .config, once per hash."""
        dirs = image_dirs(build_dir)
        if not dirs or not config_sha:
            return None
        src = dirs[0][1] / "zephyr" / ".config"
        dst = self.dir / f"{config_sha}.config"
        try:
            if not dst.exists():
                self.dir.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
        except OSError:
            return None
        return str(dst)

    def query(
        self,
        board: str | None = None,
        test: str | None = None,
        kind: str | None = None,
        ok: bool | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        out = []
        for e in reversed(self.entries):
            if board and e.get("board") != board:
                continue
            if kind and e.get("kind") != kind:
                continue
            if ok is not None and bool(e.get("ok")) != ok:
                continue
            if test and not _matches(e, test):
                continue
            out.append(e)
            if len(out) >= limit:
                break
        return out

    def last_good(self, test: str | None, board: str | None = None) -> dict[str, Any] | None:
        kind = "test" if test else None
        found = self.query(board=board, test=test, kind=kind, ok=True, limit=1)
        return found[0] if found else None


def _matches(entry: dict[str, Any], test: str) -> bool:
    hay = " ".join(
        [*(entry.get("tests") or []), entry.get("cmd") or "", entry.get("build_dir") or ""]
    )
    return test.lower() in hay.lower()


def named_tests(cmd: list[str]) -> list[str]:
    """The tests a command names: twister -T/-s/--test arguments, else pytest paths."""
    out = []
    for i, arg in enumerate(cmd):
        for flag in ("-T", "-s", "--testsuite-root", "--test", "--scenario"):
            if arg == flag and i + 1 < len(cmd):
                out.append(cmd[i + 1])
            elif arg.startswith(flag + "="):
                out.append(arg.split("=", 1)[1])
    if not out and any(Path(c).stem in ("pytest", "py.test") for c in cmd[:3]):
        out = [c for c in cmd[1:] if not c.startswith("-") and c not in ("-m", "pytest")]
    return out


def compare(
    entry: dict[str, Any], build_dir: Path | None = None, cwd: Path | None = None
) -> dict[str, Any]:
    """What changed between a history entry and the current build or working tree."""
    out: dict[str, Any] = {}
    saved = entry.get("config_path")
    if build_dir is not None and saved:
        dirs = image_dirs(build_dir)
        if dirs:
            out["kconfig"] = kconfig_diff(Path(saved), dirs[0][1] / "zephyr" / ".config")
    old = (entry.get("app_git") or {}).get("commit")
    repo = (entry.get("app_git") or {}).get("repo")
    here = cwd or (Path(repo) if repo else None)
    if old and here is not None:
        now = git_state(here)
        if now:
            out["git"] = git_changes(Path(now["repo"] or here), old, now)
    return out


def kconfig_diff(old_path: Path, new_path: Path, limit: int = 40) -> dict[str, Any]:
    try:
        old, new = parse_kconfig(old_path), parse_kconfig(new_path)
    except OSError as e:
        return {"error": str(e)}
    changed = {k: [old[k], new[k]] for k in sorted(old.keys() & new.keys()) if old[k] != new[k]}
    added = {k: new[k] for k in sorted(new.keys() - old.keys())}
    removed = {k: old[k] for k in sorted(old.keys() - new.keys())}
    total = len(changed) + len(added) + len(removed)
    out: dict[str, Any] = {"same": total == 0}
    if changed:
        out["changed"] = dict(list(changed.items())[:limit])
    if added:
        out["added"] = dict(list(added.items())[:limit])
    if removed:
        out["removed"] = dict(list(removed.items())[:limit])
    if total > limit:
        out["truncated"] = True
    return out


def git_changes(repo: Path, old: str, now: dict[str, Any], limit: int = 30) -> dict[str, Any]:
    def git(*args: str) -> str | None:
        try:
            p = subprocess.run(
                ["git", "-C", str(repo), *args],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return p.stdout if p.returncode == 0 else None

    out: dict[str, Any] = {"from": old[:12], "to": now["commit"][:12], "dirty_now": now["dirty"]}
    log = git("log", "--oneline", "--no-decorate", f"{old}..HEAD")
    if log is None:
        out["error"] = f"commit {old[:12]} is not in this repository (rebased or another clone?)"
        return out
    commits = [ln for ln in log.splitlines() if ln.strip()]
    out["commits"] = len(commits)
    out["log"] = commits[:10]
    stat = git("diff", "--numstat", old) or ""
    files = []
    for line in stat.splitlines():
        m = re.match(r"(\S+)\s+(\S+)\s+(.+)", line)
        if m:
            files.append({"file": m.group(3), "added": m.group(1), "removed": m.group(2)})
    out["files_changed"] = files[:limit]
    if len(files) > limit:
        out["more_files"] = len(files) - limit
    return out
