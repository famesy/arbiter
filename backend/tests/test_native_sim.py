"""native_sim driver. The unit tests use a stand-in zephyr.exe (a Python script) so they
run anywhere Linux is; the integration test uses a real native_sim build."""

from __future__ import annotations

import asyncio
import os
import sys
import textwrap
from pathlib import Path

import pytest
from arbiter.config import BoardConfig
from arbiter.drivers.native_sim import NativeSimDriver
from arbiter.service import Arbiter

from .conftest import make_config

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="native_sim is Linux-only"
)

FAKE_EXE = textwrap.dedent("""\
    #!{python}
    import sys, os
    assert "-uart_stdinout" in sys.argv
    sys.stdout.write("*** Booting Zephyr OS build v4.0.0 ***\\r\\nHello World! native_sim\\r\\nuart:~$ ")
    sys.stdout.flush()
    for line in sys.stdin:
        cmd = line.strip()
        if cmd == "exit":
            sys.exit(3)
        sys.stdout.write(cmd + "\\r\\nyou said " + cmd + "\\r\\nuart:~$ ")
        sys.stdout.flush()
""")


def fake_build(root: Path) -> Path:
    b = root / "hello" / "build"
    (b / "zephyr").mkdir(parents=True)
    (b / "zephyr" / ".config").write_text("CONFIG_UART_CONSOLE=y\n")
    exe = b / "zephyr" / "zephyr.exe"
    exe.write_text(FAKE_EXE.format(python=sys.executable))
    exe.chmod(0o755)
    return b


async def until(cond, limit_s: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + limit_s
    while not cond():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met")
        await asyncio.sleep(0.02)


async def run_board(tmp_path: Path, build: Path) -> None:
    arb = Arbiter(
        make_config(tmp_path, [BoardConfig(id="ns-1", driver="native_sim", platform="native_sim")])
    )
    await arb.start()
    try:
        s = arb.register_session(agent_kind="claude", label="t")["id"]
        tok = (await arb.acquire(s, "ns-1"))["lease_token"]
        res = await arb.flash(s, tok, str(build))
        while res.get("status") == "running":
            res = await arb.op_status(res["op_id"], 5)
        assert res["status"] == "done" and res["boot_confirmed"], res
        assert (await arb.expect(s, tok, r"Hello World! (\S+)", 5))["groups"] == ["native_sim"]
        await arb.write(s, tok, "ping")
        assert (await arb.expect(s, tok, "you said ping", 5))["matched"]
        drv = arb.boards["ns-1"].driver
        assert isinstance(drv, NativeSimDriver)
        pid = drv.proc.pid if drv.proc else None
        await arb.power(s, tok, "cycle", off_ms=10)
        await until(lambda: drv.running and drv.proc is not None and drv.proc.pid != pid)
        await arb.power(s, tok, "off")
        assert not drv.running
        await arb.power(s, tok, "on")
        await until(lambda: drv.running)
        await arb.write(s, tok, "exit")
        await until(lambda: drv.last_exit == 3)
        # The note waits briefly for the unfinished prompt line before it is written.
        await until(
            lambda: "native_sim exited with code 3"
            in arb.boards["ns-1"].hub.read(0, 1 << 16)[0].decode()
        )
    finally:
        await arb.stop()


async def test_native_sim_with_stand_in_exe(tmp_path):
    await run_board(tmp_path, fake_build(tmp_path))


async def test_native_sim_reported_unsupported_off_linux(tmp_path, monkeypatch):
    from arbiter.drivers import native_sim

    monkeypatch.setattr(native_sim, "is_linux", lambda: False)
    monkeypatch.setattr(sys, "platform", "win32")
    arb = Arbiter(
        make_config(tmp_path, [BoardConfig(id="ns-1", driver="native_sim", platform="native_sim")])
    )
    await arb.start()
    try:
        b = arb.snapshot()["boards"][0]
        assert b["supported"] is False and "WSL" in b["support_note"] and b["state"] == "OFFLINE"
    finally:
        await arb.stop()


@pytest.mark.integration
async def test_real_native_sim_build(tmp_path):
    """Set ARBITER_NATIVE_SIM_BUILD to a build dir of a Zephyr shell sample built with -b native_sim."""
    build = os.environ.get("ARBITER_NATIVE_SIM_BUILD")
    if not build:
        pytest.skip("ARBITER_NATIVE_SIM_BUILD not set")
    arb = Arbiter(
        make_config(tmp_path, [BoardConfig(id="ns-1", driver="native_sim", platform="native_sim")])
    )
    await arb.start()
    try:
        s = arb.register_session(agent_kind="claude", label="t")["id"]
        tok = (await arb.acquire(s, "ns-1"))["lease_token"]
        res = await arb.flash(s, tok, build)
        assert res.get("boot_confirmed"), res
    finally:
        await arb.stop()
