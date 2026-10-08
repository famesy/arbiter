from __future__ import annotations

import asyncio
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest
from arbiter.config import BoardConfig, PowerConfig
from arbiter.errors import ArbiterError
from arbiter.service import Arbiter

from .conftest import make_config, sim_board


async def lease_for(
    arb: Arbiter, name: str = "claude fw-sensor@main", board: str = "sim-1"
) -> tuple[str, str]:
    s = arb.register_session(agent_kind="claude", label=name)["id"]
    res = await arb.acquire(s, board, "integration test")
    assert res["status"] == "granted"
    return s, res["lease_token"]


async def done(arb: Arbiter, res: dict[str, Any]) -> dict[str, Any]:
    while res.get("status") == "running":
        res = await arb.op_status(res["op_id"], 5)
    return res


async def test_flash_expect_and_shell(arb, build_dir):
    s, tok = await lease_for(arb)
    res = await done(arb, await arb.flash(s, tok, str(build_dir)))
    assert res["status"] == "done", res
    assert res["boot_confirmed"] is True
    assert res["console"]["resolved"] == "uart"
    m = await arb.expect(s, tok, r"<inf> ([\w-]+): started", 5)
    assert m["matched"] and m["groups"] == ["fw-sensor"]
    await arb.write(s, tok, "kernel uptime")
    m = await arb.expect(s, tok, r"Uptime: (\d+) ms", 5)
    assert m["matched"]
    out = arb.console_read(s, tok)
    assert "untrusted_device_output" in out and "[claude-" in out["untrusted_device_output"]


async def test_expect_timeout_returns_tail(arb):
    s, tok = await lease_for(arb)
    m = await arb.expect(s, tok, "never-printed", 0.2, since="now")
    assert m["matched"] is False and "tail" in m


async def test_other_session_cannot_use_lease(arb):
    _, tok = await lease_for(arb)
    other = arb.register_session(agent_kind="codex", label="codex")["id"]
    with pytest.raises(ArbiterError) as e:
        await arb.reset(other, tok)
    assert e.value.code == "LEASE_UNKNOWN"


async def test_pause_interrupts_expect_and_blocks_tools(arb):
    s, tok = await lease_for(arb)
    waiting = asyncio.create_task(arb.expect(s, tok, "never", 10, since="now"))
    await asyncio.sleep(0.05)
    await arb.pause("sim-1", "human:Fame", "scope")
    with pytest.raises(ArbiterError) as e:
        await waiting
    assert e.value.code == "LEASE_PAUSED"
    with pytest.raises(ArbiterError) as e:
        await arb.write(s, tok, "help")
    assert e.value.code == "LEASE_PAUSED"
    await arb.human_write("sim-1", "help", "Fame")  # human may type while paused
    await arb.resume("sim-1", "human:Fame")
    assert (await arb.write(s, tok, "help"))["ok"]


async def test_pause_lets_flash_finish(arb, build_dir):
    s, tok = await lease_for(arb)
    res = await arb.flash(s, tok, str(build_dir), wait_s=0)
    assert res["status"] == "running"
    await arb.pause("sim-1", "human:Fame")
    res = await done(arb, res)
    assert res["status"] == "done" and "notice" in res
    await asyncio.sleep(0.05)
    assert arb.sched.boards["sim-1"].state == "PAUSED"


async def test_force_pause_interrupts_flash_and_marks_recover(arb, build_dir):
    s, tok = await lease_for(arb)
    res = await arb.flash(s, tok, str(build_dir), wait_s=0)
    await arb.pause("sim-1", "human:Fame", force=True)
    res = await done(arb, res)
    assert res["status"] == "failed" and res["error"] == "LEASE_PAUSED"
    assert arb.sched.boards["sim-1"].note


async def test_take_board_and_requeue(arb):
    s, tok = await lease_for(arb)
    await arb.take("sim-1", "human:Fame", "need it")
    with pytest.raises(ArbiterError) as e:
        await arb.reset(s, tok)
    assert e.value.code == "LEASE_REVOKED" and e.value.extra.get("ticket")
    st = arb.snapshot()
    assert st["boards"][0]["state"] == "HUMAN" and st["queue"][0]["pinned"]
    arb.release_hold("sim-1", "human:Fame")
    got = await arb.wait(s, e.value.extra["ticket"], 1)
    assert got["status"] == "granted" and got["lease_token"] != tok


async def test_recover_needs_approval(arb):
    s, tok = await lease_for(arb)
    with pytest.raises(ArbiterError) as e:
        await arb.recover(s, tok)
    assert e.value.code == "NEEDS_APPROVAL"
    ap = e.value.extra["approval_id"]
    assert arb.snapshot()["approvals"][0]["id"] == ap
    with pytest.raises(ArbiterError):
        await arb.recover(s, tok)  # still pending, no duplicate
    assert len(arb.approvals) == 1
    await arb.decide(ap, True, "human:Fame")
    res = await arb.recover(s, tok)
    assert res["status"] == "approved"
    final = await done(arb, await arb.op_status(res["op_id"], 5))
    assert final["status"] == "done" and final["erased"]


async def test_erase_flash_denied(arb, build_dir):
    s, tok = await lease_for(arb)
    with pytest.raises(ArbiterError) as e:
        await arb.flash(s, tok, str(build_dir), erase=True)
    await arb.decide(e.value.extra["approval_id"], False, "human:Fame")
    with pytest.raises(ArbiterError) as e2:
        await arb.flash(s, tok, str(build_dir), erase=True)
    assert e2.value.code == "APPROVAL_DENIED"


async def test_power_cycle_and_measure(arb):
    s, tok = await lease_for(arb)
    r = await arb.power(s, tok, "cycle", off_ms=10)
    assert r["on"] is True
    m = await arb.expect(s, tok, r"\*\*\* Booting", 5)
    assert m["matched"]
    res = await done(arb, await arb.measure_current(s, tok, 200, threshold_ua=1000))
    assert res["status"] == "done" and res["avg_ua"] > 0
    assert await asyncio.to_thread(Path(res["trace_path"]).exists)
    assert "samples_ua" not in res
    with pytest.raises(ArbiterError) as e:
        await arb.power_set_voltage(s, tok, 9000)
    assert e.value.code == "OUT_OF_RANGE"
    with pytest.raises(ArbiterError) as e:
        await arb.power_set_voltage(s, tok, 4500)  # above default needs approval
    assert e.value.code == "NEEDS_APPROVAL"
    assert (await arb.power_set_voltage(s, tok, 3300))["mv"] == 3300


async def test_release_restores_power(arb):
    s, tok = await lease_for(arb)
    await arb.power(s, tok, "off")
    arb.release(s, tok)
    await asyncio.sleep(0.1)
    assert arb.boards["sim-1"].power.on is True


async def test_run_command_with_board_env(arb, tmp_path):
    s, tok = await lease_for(arb)
    script = tmp_path / "t.py"
    script.write_text(
        "import os\nprint('board', os.environ['ARBITER_BOARD'])\nprint('PROJECT EXECUTION SUCCESSFUL')\n"
    )
    res = await done(arb, await arb.run(s, tok, [sys.executable, str(script)], cwd=str(tmp_path)))
    assert (
        res["ok"]
        and "board sim-1" in res["tail"]
        and res["verdict"] == "PROJECT EXECUTION SUCCESSFUL"
    )
    assert await asyncio.to_thread(Path(res["log_path"]).exists)


async def test_pause_interrupts_test_run(arb, tmp_path):
    s, tok = await lease_for(arb)
    res = await arb.run(s, tok, [sys.executable, "-c", "import time; time.sleep(30)"], wait_s=0)
    await asyncio.sleep(0.3)
    await arb.pause("sim-1", "human:Fame")
    res = await done(arb, res)
    assert res["status"] == "failed"


async def test_board_busy_during_op(arb, build_dir):
    s, tok = await lease_for(arb)
    await arb.flash(s, tok, str(build_dir), wait_s=0)
    with pytest.raises(ArbiterError) as e:
        await arb.flash(s, tok, str(build_dir), wait_s=0)
    assert e.value.code == "BOARD_BUSY"


async def test_persistence_across_restart(tmp_path):
    a = Arbiter(make_config(tmp_path))
    await a.start()
    s, tok = await lease_for(a)
    a._dirty = True
    a._persist()
    await a.stop()
    b = Arbiter(make_config(tmp_path))
    await b.start()
    try:
        assert b.sched.leases[tok].state == "EXPIRING"
        assert (await b.reset(s, tok))["status"] == "done"  # check() reclaims automatically
        assert b.sched.leases[tok].state == "ACTIVE"
    finally:
        await b.stop()


async def test_command_overrides_and_command_power(tmp_path, build_dir):
    log = tmp_path / "calls.txt"
    py = sys.executable
    rec = f"{py} -c \"import sys; open(sys.argv[1], 'a').write(' '.join(sys.argv[2:]) + chr(10))\" {log}"
    board = sim_board(
        commands={"reset": f"{rec} reset {{board}}"},
        power=PowerConfig(
            kind="command",
            commands={
                "on": f"{rec} on",
                "off": f"{rec} off",
                "set_voltage": f"{rec} volt {{mv}}",
                "measure": [
                    py,
                    "-c",
                    "import json; print(json.dumps({{'samples_ua': [1, 2, 3, 4], 'rate_hz': 1000}}))",
                ],
            },
        ),
    )
    arb = Arbiter(make_config(tmp_path, [board]))
    await arb.start()
    try:
        s, tok = await lease_for(arb)
        assert (await arb.reset(s, tok))["ok"]
        await arb.power(s, tok, "cycle", off_ms=0)
        await arb.power_set_voltage(s, tok, 3300)
        m = await done(arb, await arb.measure_current(s, tok, 100))
        assert m.get("avg_ua") == 2.5, m
        assert log.read_text().splitlines() == ["reset sim-1", "off", "on", "volt 3300"]
        assert "reset" in arb.snapshot()["boards"][0]["overrides"]
    finally:
        await arb.stop()


async def test_command_driver_and_plugin_driver(tmp_path, build_dir):
    plug = tmp_path / "plugs"
    plug.mkdir()
    (plug / "mykit.py").write_text(
        textwrap.dedent("""
        from arbiter.drivers.base import BoardDriver
        class MyKit(BoardDriver):
            kind = "mykit"
            capabilities = frozenset({"reset"})
            async def reset(self, *, halt, log_path):
                return {"ok": True, "by": "plugin"}
    """)
    )
    py = sys.executable
    cmd_board = BoardConfig(
        id="cmd-1",
        driver="command",
        platform="custom",
        commands={"flash": [py, "-c", "import sys; print('flashing', sys.argv[1])", "{hex}"]},
    )
    plug_board = BoardConfig(id="plug-1", driver="mykit:MyKit", platform="custom")
    cfg = make_config(tmp_path, [cmd_board, plug_board])
    cfg.plugin_paths = [str(plug)]
    arb = Arbiter(cfg)
    await arb.start()
    try:
        s, tok = await lease_for(arb, board="cmd-1")
        res = await done(arb, await arb.flash(s, tok, str(build_dir)))
        assert res["status"] == "done" and any("zephyr.hex" in line for line in res["tail"])
        s2, tok2 = await lease_for(arb, "other", board="plug-1")
        assert (await arb.reset(s2, tok2))["by"] == "plugin"
        with pytest.raises(ArbiterError) as e:
            await arb.recover(s2, tok2)
        assert e.value.code == "NOT_SUPPORTED"
    finally:
        await arb.stop()


async def test_current_limit_trips_power_until_the_human_clears_it(tmp_path):
    # The simulated radio wakeups peak near 20 mA, so a 5 mA limit trips.
    board = sim_board(power=PowerConfig(kind="sim", ma_max=5))
    arb = Arbiter(make_config(tmp_path, [board]))
    await arb.start()
    try:
        assert arb.list_boards()[0]["power"]["limits"]["ma_max"] == 5
        s, tok = await lease_for(arb)
        res = await done(arb, await arb.measure_current(s, tok, 1100))
        assert res["tripped"] and "over-current" in res["warning"]
        p = arb.boards["sim-1"].power
        assert p is not None and not p.on and p.state == "FAULT"
        assert arb.snapshot()["boards"][0]["power"]["fault"].startswith("over-current")
        with pytest.raises(ArbiterError) as e:
            await arb.power(s, tok, "on")
        assert e.value.code == "POWER_FAULT"
        await arb.take("sim-1", "Fame")
        await arb.human_power("sim-1", "on", "Fame")
        after = p.describe()  # read afresh: the asserts above narrowed p's fields
        assert after["on"] and after["state"] == "ON" and after["fault"] is None
    finally:
        await arb.stop()


async def test_command_supply_gets_its_current_limit_at_start(tmp_path):
    log = tmp_path / "psu.txt"
    py = sys.executable
    rec = [py, "-c", "import sys; open(sys.argv[1], 'a').write(sys.argv[2])", str(log)]
    board = sim_board(
        power=PowerConfig(
            kind="command", ma_max=250, commands={"set_current_limit": [*rec, "ilim {ma}"]}
        )
    )
    arb = Arbiter(make_config(tmp_path, [board]))
    await arb.start()
    try:
        assert log.read_text() == "ilim 250"
    finally:
        await arb.stop()


def test_power_limits_are_checked_when_loading_config():
    from arbiter.config import config_from_dict

    bad = {"board": [{"id": "b", "power": {"kind": "sim", "mv_max": 3300, "default_mv": 3700}}]}
    with pytest.raises(ValueError, match="mv_min <= default_mv <= mv_max"):
        config_from_dict(bad)
    with pytest.raises(ValueError, match="ma_max"):
        config_from_dict({"board": [{"id": "b", "power": {"kind": "sim", "ma_max": 0}}]})
