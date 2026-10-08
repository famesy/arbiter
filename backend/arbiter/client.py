"""Clients of the daemon's HTTP API, used by the MCP shim, the CLI and hooks."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Any

import httpx

from .config import read_daemon_file, state_dir
from .errors import ArbiterError

LONG_TIMEOUT = 60.0  # bounded long-polls are at most 45 s


def _conn(admin: bool) -> tuple[str, str] | None:
    url = os.environ.get("ARBITER_URL")
    token = os.environ.get("ARBITER_ADMIN_TOKEN" if admin else "ARBITER_TOKEN")
    if url and token:
        return url.rstrip("/"), token
    info = read_daemon_file(admin=admin)
    if not info:
        return None
    return f"http://{info['host']}:{info['port']}", info["token"]


def daemon_running() -> bool:
    c = _conn(False)
    if not c:
        return False
    try:
        r = httpx.get(c[0] + "/api/health", headers={"Authorization": f"Bearer {c[1]}"}, timeout=2)
    except httpx.HTTPError:
        return False
    return r.status_code == 200


def ensure_daemon(timeout: float = 15.0) -> None:
    """Start arbiterd in the background if it isn't running (MCP shim and hooks call this)."""
    if daemon_running():
        return
    log_dir = state_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "daemon.out").open("ab") as out:
        kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": out, "stderr": out}
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                0x00000008 | 0x00000200
            )  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen([sys.executable, "-m", "arbiter", "daemon"], **kwargs)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if daemon_running():
            return
        time.sleep(0.25)
    raise ArbiterError(
        "OP_FAILED", "arbiterd did not start", hint=f"See {log_dir / 'daemon.out'}. Tell the human."
    )


def _raise(r: httpx.Response) -> dict[str, Any]:
    try:
        data = r.json()
    except ValueError:
        raise ArbiterError("OP_FAILED", f"HTTP {r.status_code}: {r.text[:200]}") from None
    if not isinstance(data, dict):
        raise ArbiterError("OP_FAILED", f"HTTP {r.status_code}: expected a JSON object")
    if r.status_code >= 400:
        raise ArbiterError.from_dict(data)
    return data


class Client:
    """Synchronous client (CLI, hooks)."""

    def __init__(self, admin: bool = False, session: str | None = None, autostart: bool = False):
        if autostart:
            ensure_daemon()
        c = _conn(admin)
        if not c:
            raise ArbiterError(
                "OP_FAILED",
                "arbiterd is not running",
                hint="Start it with `arbiter daemon` (or let the MCP server start it).",
            )
        self.base, self.token = c
        self.session = session or os.environ.get("ARBITER_SESSION")
        self.http = httpx.Client(timeout=LONG_TIMEOUT)

    def _h(self) -> dict[str, Any]:
        h = {"Authorization": f"Bearer {self.token}"}
        if self.session:
            h["X-Arbiter-Session"] = self.session
        return h

    def get(self, path: str, **params: Any) -> dict[str, Any]:
        try:
            return _raise(self.http.get(self.base + path, headers=self._h(), params=params))
        except httpx.HTTPError as e:
            raise ArbiterError("OP_FAILED", f"cannot reach arbiterd: {e}") from None

    def post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            return _raise(self.http.post(self.base + path, headers=self._h(), json=body or {}))
        except httpx.HTTPError as e:
            raise ArbiterError("OP_FAILED", f"cannot reach arbiterd: {e}") from None

    @property
    def ws_base(self) -> str:
        return "ws" + self.base[4:]


class AsyncClient:
    """Async client (MCP shim)."""

    def __init__(self, admin: bool = False):
        c = _conn(admin)
        if not c:
            raise ArbiterError("OP_FAILED", "arbiterd is not running")
        self.base, self.token = c
        self.session: str | None = None
        self.http = httpx.AsyncClient(timeout=LONG_TIMEOUT)

    def _h(self) -> dict[str, Any]:
        h = {"Authorization": f"Bearer {self.token}"}
        if self.session:
            h["X-Arbiter-Session"] = self.session
        return h

    async def get(self, path: str, **params: Any) -> dict[str, Any]:
        try:
            return _raise(await self.http.get(self.base + path, headers=self._h(), params=params))
        except httpx.HTTPError as e:
            raise ArbiterError("OP_FAILED", f"cannot reach arbiterd: {e}") from None

    async def post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            return _raise(
                await self.http.post(self.base + path, headers=self._h(), json=body or {})
            )
        except httpx.HTTPError as e:
            raise ArbiterError("OP_FAILED", f"cannot reach arbiterd: {e}") from None

    async def aclose(self) -> None:
        await self.http.aclose()
