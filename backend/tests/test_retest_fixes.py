"""Fixes from the real-board retest of #20 on the nRF9161 DK."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest
from arbiter import mcp_server, service
from arbiter.errors import ArbiterError
from arbiter.service import _twister_mode
from arbiter.workspace import zephyr_base_for_run

from .test_run_fixes import twister
from .test_service import done, lease_for


# ------------------------------------------------------------------ 1. twister queries
def test_twister_modes():
    assert _twister_mode(["pytest", "tests"]) is None
    assert _twister_mode(["west", "twister", "--list-platforms"]) == "query"
    assert _twister_mode(["west", "twister", "-T", "x", "--list-tests"]) == "query"
    assert _twister_mode(["west", "twister", "-h"]) == "query"
    assert _twister_mode(["west", "twister", "-b", "-T", "x"]) == "build"
    assert _twister_mode(["west", "twister", "-T", "x"]) == "test"


async def test_twister_queries_run_untouched(arb, tmp_path, monkeypatch):
    monkeypatch.setattr(service, "IS_WINDOWS", True)
    s, tok = await lease_for(arb)
    cmd = [sys.executable, str(twister(tmp_path)), "--list-platforms"]
    res = await done(arb, await arb.run(s, tok, cmd, cwd=str(tmp_path)))
    assert "ARGS --list-platforms" in res["tail"]


# ------------------------------------------------------------------ 2. west outside a workspace
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "ncs" / ".west").mkdir(parents=True)
    sample = tmp_path / "ncs" / "zephyr" / "samples" / "hello_world"
    sample.mkdir(parents=True)
    return sample


def test_zephyr_base_comes_from_a_path_in_the_command(tmp_path, monkeypatch):
    monkeypatch.delenv("ZEPHYR_BASE", raising=False)
    sample = workspace(tmp_path)
    away = tmp_path / "agent"
    away.mkdir()
    cmd = ["west", "twister", "-T", str(sample)]
    assert zephyr_base_for_run(cmd, away, None) == str(tmp_path / "ncs" / "zephyr")
    assert zephyr_base_for_run(["west", "twister", f"--testsuite-root={sample}"], away, None)
    assert zephyr_base_for_run(cmd, sample, None) is None  # inside: west finds it itself
    assert zephyr_base_for_run(["west", "twister"], away, "/z") == "/z"
    assert zephyr_base_for_run(["west", "twister", "-T", "nope"], away, None) is None


async def test_west_run_gets_zephyr_base_from_anywhere(arb, tmp_path, monkeypatch):
    monkeypatch.delenv("ZEPHYR_BASE", raising=False)
    sample = workspace(tmp_path)
    west = tmp_path / "west.py"
    west.write_text("import os\nprint('ZB', os.environ.get('ZEPHYR_BASE'))\n")
    s, tok = await lease_for(arb)
    cmd = [sys.executable, str(west), "twister", "-T", str(sample)]
    res = await done(arb, await arb.run(s, tok, cmd, cwd=str(tmp_path)))
    assert f"ZB {tmp_path / 'ncs' / 'zephyr'}" in res["tail"]


async def test_west_workspace_failure_gets_a_hint(arb, tmp_path):
    s, tok = await lease_for(arb)
    script = tmp_path / "w.py"
    script.write_text(
        "print('west: unknown command \"twister\"; do you need to run this inside a workspace?')\n"
        "raise SystemExit(1)\n"
    )
    res = await done(arb, await arb.run(s, tok, [sys.executable, str(script)], cwd=str(tmp_path)))
    assert "workspace" in res["hint"]


# ------------------------------------------------------------------ 3. release an unbootable board
async def test_release_refuses_while_the_board_does_not_boot(arb, tmp_path, build_dir):
    s, tok = await lease_for(arb)
    script = twister(tmp_path, "print('E: Unable to find bootable image')\nsys.exit(1)\n")
    res = await done(arb, await arb.run(s, tok, [sys.executable, str(script)], cwd=str(tmp_path)))
    assert res["boot_failed"]
    with pytest.raises(ArbiterError) as e:
        arb.release(s, tok)
    assert e.value.code == "BOARD_UNBOOTABLE" and e.value.http_status == 409
    assert "flash" in e.value.message.lower()
    res = await done(arb, await arb.flash(s, tok, str(build_dir)))
    assert res["boot_confirmed"] is True
    assert arb.release(s, tok)["status"] == "released"


async def test_force_release_and_human_take_still_work(arb, tmp_path):
    s, tok = await lease_for(arb)
    script = twister(tmp_path, "print('E: Unable to find bootable image')\n")
    await done(arb, await arb.run(s, tok, [sys.executable, str(script)], cwd=str(tmp_path)))
    assert arb.release(s, tok, force=True)["status"] == "released"
    await lease_for(arb, "codex other")
    await arb.take("sim-1", "human:Fame")  # the human is never blocked
    assert arb.sched.boards["sim-1"].state == "HUMAN"


# ------------------------------------------------------------------ 4. MCP argument forms
def test_string_commands_are_split(monkeypatch):
    assert mcp_server.split_cmd("west twister -T 'my tests'") == [
        "west",
        "twister",
        "-T",
        "my tests",
    ]
    assert mcp_server.split_cmd(["a", "b c"]) == ["a", "b c"]
    monkeypatch.setattr(os, "name", "nt")
    assert mcp_server.split_cmd('west flash -d "C:\\b\\my app"') == [
        "west",
        "flash",
        "-d",
        "C:\\b\\my app",
    ]


async def test_mcp_accepts_board_and_a_string_cmd(monkeypatch):
    sent: list[tuple[str, dict[str, Any]]] = []

    async def call(path: str, body: dict[str, Any], need_lease: bool = False) -> dict[str, Any]:
        sent.append((path, body))
        return {"ok": True}

    monkeypatch.setattr(mcp_server.shim, "call", call)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/work/app")
    await mcp_server.acquire_board(board="nrf9161dk", reason="test")
    await mcp_server.run(cmd="west twister -T tests")
    assert sent[0][1]["selector"] == "nrf9161dk"
    assert sent[1][1]["cmd"] == ["west", "twister", "-T", "tests"]
    assert sent[1][1]["cwd"] == "/work/app"
    err = await mcp_server.acquire_board(reason="no board")
    assert err["error"] == "BAD_REQUEST" or err.get("code") == "BAD_REQUEST"
