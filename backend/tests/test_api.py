"""The HTTP/WebSocket API and the MCP server, against a real uvicorn server."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
import websockets
from arbiter.api import Auth, create_app
from arbiter.config import write_daemon_files
from arbiter.service import Arbiter

from .conftest import make_config

BACKEND_DIR = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
async def server(tmp_path: Path):
    cfg = make_config(tmp_path)
    cfg.port = free_port()
    agent, admin = write_daemon_files(cfg.state, cfg.host, cfg.port)
    arb = Arbiter(cfg)
    await arb.start()
    srv = uvicorn.Server(
        uvicorn.Config(
            create_app(arb, Auth(agent, admin)),
            host=cfg.host,
            port=cfg.port,
            log_level="warning",
            ws="websockets",
        )
    )
    task = asyncio.create_task(srv.serve())
    for _ in range(500):
        if srv.started:
            break
        await asyncio.sleep(0.02)
    base = f"http://{cfg.host}:{cfg.port}"
    try:
        yield {"base": base, "agent": agent, "admin": admin, "arb": arb, "state": cfg.state}
    finally:
        srv.should_exit = True
        await asyncio.wait_for(task, 10)
        await asyncio.wait_for(arb.stop(), 10)


def hdr(token: str, session: str | None = None) -> dict[str, Any]:
    h = {"Authorization": f"Bearer {token}"}
    if session:
        h["X-Arbiter-Session"] = session
    return h


async def test_auth_levels(server):
    async with httpx.AsyncClient(base_url=server["base"]) as c:
        assert (await c.get("/api/state")).status_code == 401
        assert (await c.get("/api/state", headers=hdr(server["agent"]))).status_code == 200
        r = await c.post("/api/admin/boards/sim-1/take", headers=hdr(server["agent"]), json={})
        assert r.status_code == 401 and r.json()["error"] == "UNAUTHORIZED"
        assert (
            await c.post("/api/admin/boards/sim-1/take", headers=hdr(server["admin"]), json={})
        ).status_code == 200


async def test_agent_flow_and_human_pause(server, build_dir):
    async with httpx.AsyncClient(base_url=server["base"], timeout=30) as c:
        s = (
            await c.post(
                "/api/sessions",
                headers=hdr(server["agent"]),
                json={"agent_kind": "codex", "label": "codex fw@main"},
            )
        ).json()["id"]
        h = hdr(server["agent"], s)
        g = (
            await c.post(
                "/api/acquire", headers=h, json={"selector": "nrf9161dk", "reason": "smoke"}
            )
        ).json()
        assert g["status"] == "granted"
        tok = g["lease_token"]
        r = (
            await c.post(
                "/api/flash", headers=h, json={"lease_token": tok, "build_dir": str(build_dir)}
            )
        ).json()
        while r["status"] == "running":
            r = (await c.get(f"/api/ops/{r['op_id']}", headers=h, params={"wait_s": 5})).json()
        assert r["status"] == "done"
        r = await c.post(
            "/api/admin/boards/sim-1/pause", headers=hdr(server["admin"]), json={"reason": "scope"}
        )
        assert r.status_code == 200
        r = await c.post("/api/console/write", headers=h, json={"lease_token": tok, "data": "help"})
        assert r.status_code == 409 and r.json()["error"] == "LEASE_PAUSED" and "hint" in r.json()
        inbox = (await c.get(f"/api/sessions/{s}/inbox", headers=h)).json()["items"]
        assert any(i["kind"] == "paused" for i in inbox)
        st = (await c.get("/api/state", headers=hdr(server["admin"]))).json()
        assert (
            st["boards"][0]["state"] == "PAUSED"
            and st["boards"][0]["lease"]["holder"] == "agent:codex fw@main"
        )
        assert "token" not in json.dumps(st["boards"][0]["lease"]).replace("lease_token", "")


async def test_events_and_console_websockets(server):
    ws_base = server["base"].replace("http", "ws")
    async with websockets.connect(f"{ws_base}/api/events?token={server['admin']}") as ev:
        first = json.loads(await ev.recv())
        assert first["kind"] == "snapshot"
        async with websockets.connect(
            f"{ws_base}/api/boards/sim-1/console?token={server['admin']}&by=Fame"
        ) as con:
            await con.send(b"kernel version\r")
            seen = b""
            while b"Zephyr version" not in seen:
                msg = await asyncio.wait_for(con.recv(), 5)
                assert isinstance(msg, bytes)
                seen += msg
            assert b"[human:Fame] > kernel version" in seen
        async with httpx.AsyncClient(base_url=server["base"]) as c:
            await c.post(
                "/api/admin/boards/sim-1/maintenance",
                headers=hdr(server["admin"]),
                json={"on": True},
            )
        kinds = set()
        while "board.state" not in kinds:
            kinds.add(json.loads(await asyncio.wait_for(ev.recv(), 5))["kind"])


async def test_agent_console_ws_needs_its_lease(server):
    ws_base = server["base"].replace("http", "ws")
    with pytest.raises(websockets.exceptions.InvalidStatus):
        async with websockets.connect(
            f"{ws_base}/api/boards/sim-1/console?token={server['agent']}"
        ):
            pass


@pytest.mark.skipif(
    sys.platform == "win32", reason="stdio subprocess plumbing is POSIX-tested here"
)
async def test_mcp_server_end_to_end(server, build_dir):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.types import TextContent

    env = {
        **os.environ,
        "ARBITER_HOME": str(server["state"]),
        "CLAUDE_CODE_SESSION_ID": "cc-123",
        "PYTHONPATH": str(BACKEND_DIR),
    }
    params = StdioServerParameters(command=sys.executable, args=["-m", "arbiter", "mcp"], env=env)
    async with stdio_client(params) as (r, w), ClientSession(r, w) as session:
        await session.initialize()
        names = {t.name for t in (await session.list_tools()).tools}
        assert {
            "acquire_board",
            "wait_for_board",
            "flash",
            "serial_expect",
            "serial_write",
            "release_board",
            "run",
            "run_status",
            "power",
            "measure_current",
            "recover_board",
        } <= names

        async def call(name: str, **args):
            res = await session.call_tool(name, args)
            content = res.content[0]
            assert isinstance(content, TextContent)
            return json.loads(content.text)

        g = await call("acquire_board", selector="sim-1", reason="mcp smoke")
        assert g["status"] == "granted"
        f = await call(
            "flash", build_dir=str(build_dir)
        )  # lease_token omitted: the only lease is used
        while f.get("status") == "running":
            f = await call("run_status", op_id=f["op_id"])
        assert f["status"] == "done", f
        sh = await call("shell_commands")  # board omitted: the one this session holds
        assert sh["available"] and "kernel" in [c["name"] for c in sh["commands"]]
        await call("serial_write", data="kernel uptime")
        m = await call("serial_expect", regex=r"Uptime: \d+ ms", timeout_s=5)
        assert m["matched"]
        assert (await call("recover_board"))["error"] == "NEEDS_APPROVAL"
        assert (await call("release_board"))["status"] == "released"
        sess = server["arb"].sched.session_by_external("cc-123")
        assert sess is not None and sess.agent_kind == "claude"
