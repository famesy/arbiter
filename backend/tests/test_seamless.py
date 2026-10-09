"""Setup with `arbiter init`, humans using a free board, and consoles that come back."""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from arbiter import cli, starter
from arbiter import scheduler as sch
from arbiter.config import BoardConfig, PortConfig, load_config
from arbiter.config_edit import validate
from arbiter.console.hub import ConsoleHub
from arbiter.console.sources import RttSource
from arbiter.drivers import discovery
from arbiter.drivers.west import NrfDriver
from arbiter.errors import ArbiterError
from arbiter.hooks import check_command

from .conftest import FakeClock
from .test_service import lease_for


# ------------------------------------------------------------------ the idle board
def test_using_a_free_board_holds_it_until_the_human_goes_idle(clock: FakeClock):
    s = sch.Scheduler(sch.Timing(), clock)
    s.add_board("b1", "nrf9161dk/nrf9161/ns", [])
    s.human_activity("b1", "human:Fame")
    assert s.boards["b1"].state == sch.HUMAN and s.boards["b1"].human_auto
    a = s.register_session("claude", "A").id
    e = s.acquire(a, "b1", "test")
    st = s.ticket_status(e.ticket)
    assert st["status"] == "queued"
    assert st["boards"][0]["holder"] == "human:Fame" and st["boards"][0]["free_in_s"] == 120
    clock.advance(60)
    s.ticket_status(e.ticket)  # the agent keeps polling
    s.human_activity("b1", "human:Fame")  # still typing: the clock restarts
    clock.advance(70)
    s.tick()
    assert s.ticket_status(e.ticket)["status"] == "queued"
    clock.advance(60)
    s.tick()
    assert s.ticket_status(e.ticket)["status"] == "granted"


def test_an_explicit_take_is_not_released_by_idling(clock: FakeClock):
    s = sch.Scheduler(sch.Timing(), clock)
    s.add_board("b1", "nrf9161dk/nrf9161/ns", [])
    s.human_activity("b1", "human:Fame")
    s.take("b1", "human:Fame")
    clock.advance(10_000)
    s.tick()
    assert s.boards["b1"].state == sch.HUMAN
    s.resume("b1")
    assert s.boards["b1"].state == sch.AVAILABLE and not s.boards["b1"].human_auto


async def test_human_flashes_a_free_board_and_agents_wait(arb, build_dir):
    res = await arb.human_flash("sim-1", "Fame", str(build_dir))
    assert res["ok"] and res["boot_confirmed"] is True
    assert arb.sched.boards["sim-1"].state == sch.HUMAN
    s = arb.register_session(agent_kind="claude", label="claude fw")["id"]
    got = await arb.acquire(s, "sim-1", "test", wait_s=0)
    assert got["status"] == "queued" and got["boards"][0]["holder"] == "human:Fame"
    arb.release_hold("sim-1", "human:Fame")
    assert (await arb.wait(s, got["ticket"], 1))["status"] == "granted"


async def test_human_cannot_flash_over_an_agent(arb, build_dir):
    await lease_for(arb)
    with pytest.raises(ArbiterError) as e:
        await arb.human_flash("sim-1", "Fame", str(build_dir))
    assert e.value.code == "BOARD_BUSY"


# ------------------------------------------------------------------ arbiter init
JLINK = {
    "serial": "001050978819",
    "kind": "jlink",
    "vid": "1366",
    "pid": "1069",
    "ports": [
        {"device": "/dev/ttyACM0", "interface": 0, "description": "J-Link"},
        {"device": "/dev/ttyACM1", "interface": 2, "description": "J-Link"},
    ],
}
NRF = [
    {
        "serial": "1050978819",
        "board_version": "PCA10153",
        "ports": [{"port": "/dev/ttyACM0", "vcom": 0}, {"port": "/dev/ttyACM1", "vcom": 1}],
    }
]


def test_draft_from_a_nordic_dk():
    raw = starter.draft([JLINK], NRF, {"toolchain_env": "C:\\ncs\\toolchains\\x\\environment.json"})
    b = raw["board"][0]
    assert b["id"] == "nrf9161dk-1" and b["driver"] == "nrf"
    assert b["platform"] == "nrf9161dk/nrf9161/ns" and b["device"] == "nRF9161_xxCA"
    assert b["probe_serial"] == "1050978819"
    assert b["port"] == [{"role": "app", "vcom": 0}, {"role": "aux", "name": "tfm", "vcom": 1}]
    assert validate(raw) == []
    text = starter.render(raw, 1)
    assert "toolchain_env = 'C:\\ncs\\toolchains\\x\\environment.json'" in text
    assert "\n\n[[board]]\n" in text and "\n\n[[board.port]]\n" in text


def test_draft_without_nrfutil_or_probes():
    b = starter.draft([JLINK], [], {})["board"][0]
    assert b["id"] == "jlink-1" and "platform" not in b
    assert b["port"] == [
        {"role": "app", "interface": 0},
        {"role": "aux", "name": "if2", "interface": 2},
    ]
    raw = starter.draft([], [], {})
    assert raw["board"] == [{"id": "sim-1", "driver": "sim", "platform": "native_sim"}]
    assert "No debug probes found" in starter.render(raw, 0)


def test_find_ncs(tmp_path: Path):
    for v in ("v2.9.0", "v3.4.1", "v3.10.0"):
        (tmp_path / v / "zephyr").mkdir(parents=True)
    env = tmp_path / "toolchains" / "abc" / "environment.json"
    env.parent.mkdir(parents=True)
    env.write_text("{}")
    found = starter.find_ncs([tmp_path])
    assert found == {"toolchain_env": str(env), "zephyr_base": str(tmp_path / "v3.10.0" / "zephyr")}


def test_init_prints_then_writes_only_when_asked(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(discovery, "probes", lambda: [JLINK])
    monkeypatch.setattr(starter, "nrfutil_devices", lambda: NRF)
    monkeypatch.setattr(starter, "find_ncs", dict)
    path = tmp_path / "arb" / "config.toml"
    assert cli.main(["init", "--config", str(path)]) == 0
    out = capsys.readouterr().out
    assert f"# target: {path}" in out and 'id = "nrf9161dk-1"' in out and not path.exists()
    assert cli.main(["init", "--write", "--config", str(path)]) == 0
    assert load_config(path).boards[0].device == "nRF9161_xxCA"
    path.write_text(path.read_text() + "# mine\n")
    assert cli.main(["init", "--write", "--config", str(path)]) == 1
    assert "already exists" in capsys.readouterr().err
    assert cli.main(["init", "--write", "--force", "--config", str(path)]) == 0
    assert "# mine" not in path.read_text()
    assert path.with_name("config.toml.bak").read_text().endswith("# mine\n")


def test_agents_may_draft_and_write_but_not_replace_a_config():
    assert check_command("arbiter init") is None
    assert check_command("arbiter --json init --write") is None
    assert "human only" in (check_command("arbiter init --write --force") or "")
    assert "human only" in (check_command("arbiter program nrf9161dk-1 build") or "")


# ------------------------------------------------------------------ reconnecting
class FakeHub:
    def __init__(self) -> None:
        self.notes: list[str] = []
        self.data = b""

    def annotate(self, note: str) -> None:
        self.notes.append(note)

    def feed(self, data: bytes, name: str) -> None:
        self.data += data


class FakeJLink:
    def __init__(self, chunks: list[Any]) -> None:
        self.chunks = chunks
        self.closed = False

    def rtt_read(self, _buf: int, _n: int) -> list[int]:
        if not self.chunks:
            return []
        c = self.chunks.pop(0)
        if isinstance(c, Exception):
            raise c
        return list(c)

    def target_connected(self) -> bool:
        return True

    def close(self) -> None:
        self.closed = True

    def rtt_stop(self) -> None:
        pass


async def test_rtt_reattaches_after_the_probe_drops_out(monkeypatch):
    monkeypatch.setitem(sys.modules, "pylink", types.ModuleType("pylink"))
    first = FakeJLink([b"boot 1\n", OSError("USB gone")])
    second = FakeJLink([b"boot 2\n"])
    attempts: list[Any] = [OSError("no probe"), first, OSError("enumerating"), second]

    def fake_open() -> Any:
        a = attempts.pop(0)
        if isinstance(a, Exception):
            raise a
        return a

    src = RttSource("1050978819", "nRF9161_xxCA")
    src.retry_s = 0.01
    monkeypatch.setattr(src, "_open", fake_open)
    hub = FakeHub()
    await src.start(hub)  # type: ignore[arg-type]
    for _ in range(200):
        if b"boot 2" in hub.data:
            break
        await asyncio.sleep(0.01)
    assert hub.data == b"boot 1\nboot 2\n"
    assert first.closed and src.connected
    assert any("rtt lost (USB gone)" in n for n in hub.notes)
    assert sum("attach failed" in n for n in hub.notes) == 2
    await src.stop()
    assert not src.connected


def test_nrf_driver_forgets_vcom_ports_after_re_enumeration(tmp_path, monkeypatch):
    cfg = BoardConfig(id="dk", driver="nrf", probe_serial="1050978819", ports=[PortConfig(vcom=0)])
    drv = NrfDriver(cfg, ConsoleHub("dk"), tmp_path)
    drv._vcoms = {0: "COM9"}
    now = [discovery.PortInfo("COM9", 0x1366, 0x1069, "001050978819", 0, None, "", "")]
    monkeypatch.setattr(discovery, "ports_for", lambda _sn: now)
    monkeypatch.setattr(discovery, "resolve_port", lambda _sn, iface: f"iface{iface}")
    assert drv.resolve_app_port() == "COM9"
    now[0] = discovery.PortInfo("COM12", 0x1366, 0x1069, "001050978819", 0, None, "", "")
    assert drv.resolve_app_port() == "iface0"
    assert drv._vcoms == {} and drv._vcoms_at == 0.0


def test_session_start_note_has_no_token(tmp_path, monkeypatch):
    from arbiter import hooks

    c = types.SimpleNamespace(base="http://127.0.0.1:7777", token="secret")
    monkeypatch.setenv("ARBITER_CONFIG", str(tmp_path / "config.toml"))
    assert hooks._startup_note(c) == "arbiter: no boards configured yet; run /arbiter:setup"  # type: ignore[arg-type]
    (tmp_path / "config.toml").write_text('[[board]]\nid = "sim-1"\n')
    note = hooks._startup_note(c)  # type: ignore[arg-type]
    assert note == "arbiter: dashboard at http://127.0.0.1:7777 (open with `arbiter dashboard`)"
