"""`arbiter tui` against a real daemon with a simulated board."""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path

import pytest
import uvicorn
from arbiter.api import Auth, create_app
from arbiter.config import write_daemon_files
from arbiter.service import Arbiter

from .conftest import make_config, sim_board

pytest.importorskip("textual")

from arbiter.tui.app import ArbiterTui
from arbiter.tui.model import BootBlock


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
async def daemon(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = make_config(tmp_path, [sim_board("sim-1"), sim_board("sim-2")])
    cfg.port = free_port()
    monkeypatch.setenv("ARBITER_HOME", str(cfg.state))
    monkeypatch.delenv("ARBITER_URL", raising=False)
    agent, admin = write_daemon_files(cfg.state, cfg.host, cfg.port)
    arb = Arbiter(cfg)
    await arb.start()
    srv = uvicorn.Server(
        uvicorn.Config(
            create_app(arb, Auth(agent, admin)), host=cfg.host, port=cfg.port, log_level="warning"
        )
    )
    task = asyncio.create_task(srv.serve())
    for _ in range(500):
        if srv.started:
            break
        await asyncio.sleep(0.02)
    try:
        yield arb
    finally:
        srv.should_exit = True
        await asyncio.wait_for(task, 10)
        await asyncio.wait_for(arb.stop(), 10)


async def until(pilot, cond, wait_s: float = 5.0) -> None:
    for _ in range(int(wait_s / 0.05)):
        if cond():
            return
        await pilot.pause(0.05)
    raise AssertionError("condition not met")


def console_text(app: ArbiterTui) -> str:
    out = []
    for e in app.console_view.model.entries:
        for line in e.lines if isinstance(e, BootBlock) else [e]:
            out.append(f"{line.tag or ''} {line.text}")
    return "\n".join(out)


async def test_console_typing_take_and_give_back(daemon):
    app = ArbiterTui()
    async with app.run_test(size=(100, 30)) as pilot:
        await until(pilot, lambda: app.connected and app.board is not None)
        assert app.selected == "sim-1"
        await until(pilot, lambda: "started on" in console_text(app))

        # Typing sends a line to the board, tagged as yours.
        await pilot.press(*"kernel version", "enter")
        await until(pilot, lambda: "Zephyr version" in console_text(app))
        assert "[you] > kernel version" in console_text(app)
        assert app.history == ["kernel version"]

        # F5 takes the free board, then gives it back.
        await pilot.press("f5")
        await until(pilot, lambda: app.board is not None and app.board["state"] == "HUMAN")
        assert app.check_action("give_back", ()) and not app.check_action("take", ())
        await pilot.press("f5")
        await until(pilot, lambda: app.board is not None and app.board["state"] == "AVAILABLE")

        # F2 switches boards; the switcher shows because there are two.
        await pilot.press("f2")
        await until(pilot, lambda: app.selected == "sim-2")


async def test_shell_suggestions_and_view(daemon, build_dir):
    await daemon._read_shell(daemon.boards["sim-1"], build_dir)
    app = ArbiterTui()
    async with app.run_test(size=(100, 30)) as pilot:
        await until(pilot, lambda: app.shell.available)
        await pilot.press("k", "e", "r")
        box = app.query_one("#suggest")
        assert box.has_class("open")
        await pilot.press("tab")
        assert app.input.value == "kernel "
        await pilot.press("tab", "tab")
        assert app.input.value == "kernel uptime "

        await pilot.press("f7", "2")
        assert app.view["ts"] is True
        await pilot.press("escape")
        assert not app.screen.is_modal
