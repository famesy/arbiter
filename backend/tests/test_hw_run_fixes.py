"""Fixes from the first run on a real nRF9161 DK (2026-10-09)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from arbiter import client
from arbiter.config import config_from_dict
from arbiter.console.hub import ConsoleHub, Sender
from arbiter.console.sources import CallbackSource
from arbiter.doctor import FAIL, check_board
from arbiter.drivers.discovery import nordic_platform
from arbiter.errors import ArbiterError
from arbiter.scheduler import Scheduler, Timing
from arbiter.service import await_boot
from arbiter.workspace import west_context, zephyr_base_from_build

from .conftest import FakeClock
from .test_service import lease_for


async def _noop(data: bytes) -> None:
    pass


# ------------------------------------------------------------------ west workspace
def _workspace(tmp: Path) -> tuple[Path, Path]:
    ws = tmp / "ncs" / "v3.4.1"
    (ws / ".west").mkdir(parents=True)
    zephyr = ws / "zephyr"
    zephyr.mkdir()
    build = tmp / "apps" / "hello" / "build"
    (build / "hello" / "zephyr").mkdir(parents=True)
    (build / "hello" / "zephyr" / ".config").write_text('CONFIG_BOARD="nrf9161dk"\n')
    (build / "domains.yaml").write_text(
        f"default: hello\nbuild_dir: {build}\ndomains:\n  - name: hello\n    build_dir: {build / 'hello'}\n"
    )
    (build / "hello" / "CMakeCache.txt").write_text(
        f"CMAKE_BUILD_TYPE:STRING=\nZEPHYR_BASE:PATH={zephyr}\n"
    )
    return ws, build


def test_west_runs_in_the_builds_workspace(tmp_path, monkeypatch):
    monkeypatch.delenv("ZEPHYR_BASE", raising=False)
    ws, build = _workspace(tmp_path)
    assert zephyr_base_from_build(build) == ws / "zephyr"
    elsewhere = tmp_path / "arbiter-repo"
    elsewhere.mkdir()
    env, run_in = west_context(build, None, elsewhere)
    assert env == {"ZEPHYR_BASE": str(ws / "zephyr")}
    assert run_in is not None and run_in.resolve() == ws.resolve()


def test_west_context_falls_back_to_configured_base(tmp_path, monkeypatch):
    monkeypatch.delenv("ZEPHYR_BASE", raising=False)
    ws, _build = _workspace(tmp_path)
    bare = tmp_path / "bare-build"
    bare.mkdir()
    env, run_in = west_context(bare, str(ws / "zephyr"), bare)
    assert env["ZEPHYR_BASE"] == str(ws / "zephyr")
    assert run_in is not None and run_in.resolve() == ws.resolve()


def test_config_zephyr_base_defaults_from_daemon():
    cfg = config_from_dict(
        {
            "daemon": {"zephyr_base": "/ncs/zephyr"},
            "board": [
                {"id": "a", "driver": "sim"},
                {"id": "b", "driver": "sim", "zephyr_base": "/other/zephyr"},
            ],
        }
    )
    assert [b.zephyr_base for b in cfg.boards] == ["/ncs/zephyr", "/other/zephyr"]


# ------------------------------------------------------------------ boot banner
async def _hub() -> ConsoleHub:
    hub = ConsoleHub("b")
    await hub.attach(CallbackSource("uart:app", _noop))
    return hub


async def test_mcuboot_banner_alone_is_not_a_boot():
    hub = await _hub()
    hub.feed(
        b"*** Booting MCUboot v2.1.0 ***\r\n*** Using nRF Connect SDK v3.4.1 ***\r\n", "uart:app"
    )
    hub.feed(b"I: Starting bootloader\r\nE: Unable to find bootable image\r\n", "uart:app")
    res = await await_boot(hub, 0.5, {}, ["uart:app"])
    assert res["booted"] is False and res["failed"] == "Unable to find bootable image"


async def test_app_banner_after_mcuboot_confirms():
    hub = await _hub()
    hub.feed(
        b"*** Booting MCUboot v2.1.0 ***\r\nI: Jumping to the first image slot\r\n", "uart:app"
    )
    text = b"*** Booting nRF Connect SDK v3.4.1 ***\r\nHello World! nrf9161dk\r\n"
    start = hub.end("uart:app")
    hub.feed(text, "uart:app")
    res = await await_boot(hub, 0.5, {}, ["uart:app"])
    assert res["booted"] is True and res["match_start"] == start


async def test_old_mcuboot_with_plain_zephyr_banner_is_skipped():
    hub = await _hub()
    hub.feed(b"*** Booting Zephyr OS build v3.5.99 ***\r\nI: Starting bootloader\r\n", "uart:app")
    res = await await_boot(hub, 0.3, {}, ["uart:app"])
    assert res["booted"] is False and "failed" not in res
    hub.feed(b"I: Jumping to the first image slot\r\n", "uart:app")
    start = hub.end("uart:app")
    hub.feed(b"*** Booting Zephyr OS build v3.5.99 ***\r\nhello\r\n", "uart:app")
    res = await await_boot(hub, 2, {}, ["uart:app"])
    assert res["booted"] is True and res["match_start"] == start


# ------------------------------------------------------------------ console notes and writes
async def test_note_waits_for_the_device_line():
    hub = await _hub()
    hub.feed(b"I: Bootloader cha", "uart:app")
    hub.annotate("[arbiter] flash ok")
    hub.feed(b"inload address offset: 0x10000\r\n", "uart:app")
    text = hub.read(0, 4096, "uart:app")[0].decode()
    assert "I: Bootloader chainload address offset: 0x10000\r\n" in text
    assert text.index("flash ok") > text.index("0x10000")


async def test_note_is_written_after_a_short_wait_on_a_prompt():
    hub = await _hub()
    hub.feed(b"uart:~$ ", "uart:app")
    hub.annotate("[arbiter] reset")
    assert b"reset" not in hub.read(0, 4096, "uart:app")[0]
    await asyncio.sleep(0.5)
    assert b"[arbiter] reset" in hub.read(0, 4096, "uart:app")[0]


async def test_writes_do_not_interleave_mid_line():
    sent: list[bytes] = []

    async def record(data: bytes) -> None:
        sent.append(data)

    hub = ConsoleHub("b")
    await hub.attach(CallbackSource("uart:app", record))
    agent = Sender("agent", "claude-1a2b", "claude fw", "s-1a2b3c4d")
    await hub.write(b"kernel ", agent)
    human = asyncio.create_task(hub.write(b"help\r\n", Sender.human("Fame")))
    await asyncio.sleep(0.05)
    assert sent == [b"kernel "]  # the human waits for the agent's line
    await hub.write(b"uptime\r\n", agent)
    await human
    assert sent == [b"kernel ", b"uptime\r\n", b"help\r\n"]
    assert [w.sender.tag for w in hub.writes] == ["claude-1a2b", "claude-1a2b", "you"]


async def test_human_typing_is_tagged_and_the_agent_is_told(arb):
    s, tok = await lease_for(arb)
    events = arb.bus.subscribe()
    await arb.human_write("sim-1", "kernel version", "Fame")
    m = await arb.expect(s, tok, r"Zephyr version", 5)
    assert m["matched"]
    assert m["human_input"][0]["data"].startswith("kernel version")
    inbox = arb.inbox(s)
    assert inbox[-1]["kind"] == "human_input" and "Fame typed" in inbox[-1]["text"]
    kinds = []
    while not events.empty():
        ev = events.get_nowait()
        kinds.append(ev["kind"])
        if ev["kind"] == "console.write":
            assert ev["sender"] == {"kind": "human", "tag": "you", "name": "Fame"}
    assert "console.write" in kinds
    text = arb.console_read(s, tok, cursor=0)["untrusted_device_output"]
    assert "[you] > kernel version" in text


async def test_agent_writes_carry_the_session_tag(arb):
    s, tok = await lease_for(arb)
    res = await arb.write(s, tok, "kernel uptime")
    assert res["ok"]
    rec = arb.boards["sim-1"].hub.writes[-1]
    assert rec.sender.kind == "agent" and rec.sender.tag == f"claude-{s[2:6]}"


# ------------------------------------------------------------------ sessions and leases
def test_explicit_external_id_wins(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "cc-1")
    monkeypatch.delenv("ARBITER_EXTERNAL_ID", raising=False)
    assert client.external_id() == "cc-1"
    assert client.agent_kind() == "claude"
    monkeypatch.setenv("ARBITER_EXTERNAL_ID", "agent-b")
    assert client.external_id() == "agent-b"


def test_no_lease_hint_names_the_ticket():
    with pytest.raises(ArbiterError) as e:
        client.only_lease(
            {"leases": [], "tickets": ["t-1"]}, "Call acquire_board", "Call wait({ticket})"
        )
    assert "t-1" in e.value.message and "wait(t-1)" in e.value.hint
    with pytest.raises(ArbiterError) as e:
        client.only_lease({"leases": []}, "Call acquire_board", "x")
    assert e.value.hint == "Call acquire_board first."
    assert client.only_lease({"leases": [{"lease_token": "L"}]}, "a", "w") == "L"


def test_stale_sessions_are_dropped():
    clock = FakeClock()
    s = Scheduler(Timing(heartbeat_timeout_s=25, grace_s=30, idle_session_s=3600), clock)
    s.add_board("b1", "p", [])
    killed = s.register_session("claude", "a", heartbeat=True)
    idle_cli = s.register_session("cli", "b")
    holder = s.register_session("cli", "c")
    s.acquire(holder.id, "b1")
    def ended() -> list[bool]:
        return [x.ended for x in (killed, idle_cli, holder)]

    clock.advance(60)
    s.tick()
    assert ended() == [True, False, False]
    clock.advance(3600)
    s.tick()
    assert ended() == [True, True, False]
    s.heartbeat(killed.id)
    assert ended() == [False, True, False]


# ------------------------------------------------------------------ discover and doctor
def test_nordic_board_numbers_map_to_targets():
    assert nordic_platform("PCA10153") == "nrf9161dk/nrf9161/ns"
    assert nordic_platform("pca10056") == "nrf52840dk/nrf52840"
    assert nordic_platform("PCA99999") is None


def test_doctor_flags_a_missing_zephyr_base(tmp_path):
    cfg = config_from_dict(
        {
            "daemon": {"state_dir": str(tmp_path)},
            "board": [
                {
                    "id": "dk",
                    "driver": "west",
                    "probe_serial": "123",
                    "zephyr_base": str(tmp_path / "nope"),
                }
            ],
        }
    )
    checks = check_board(cfg.boards[0], cfg)
    zb = next(c for c in checks if c.name.endswith("zephyr_base"))
    assert zb.status == FAIL
