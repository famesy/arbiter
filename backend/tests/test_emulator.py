"""Emulated boards (QEMU, Renode) with a stand-in `cmake` that plays the emulator."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest
from arbiter.config import BoardConfig
from arbiter.drivers.emulator import EmulatorDriver
from arbiter.service import Arbiter

from .conftest import make_config
from .test_native_sim import until

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="emulators need a pty")

FAKE_CMAKE = textwrap.dedent("""\
    #!{python}
    import sys
    build, target = sys.argv[2], sys.argv[4]
    sys.stdout.write("*** Booting Zephyr OS build v4.0.0 ***\\r\\n")
    sys.stdout.write("emulated by " + target + " from " + build + "\\r\\nuart:~$ ")
    sys.stdout.flush()
    for line in sys.stdin:
        sys.stdout.write(line.strip() + "\\r\\nyou said " + line.strip() + "\\r\\nuart:~$ ")
        sys.stdout.flush()
""")


def setup(tmp_path: Path, **options: str) -> tuple[Arbiter, Path]:
    cmake = tmp_path / "cmake"
    cmake.write_text(FAKE_CMAKE.format(python=sys.executable))
    cmake.chmod(0o755)
    build = tmp_path / "app" / "build"
    (build / "zephyr").mkdir(parents=True)
    (build / "zephyr" / ".config").write_text("CONFIG_UART_CONSOLE=y\n")
    (build / "CMakeCache.txt").write_text("CMAKE_PROJECT_NAME:STATIC=app\n")
    bc = BoardConfig(id="qemu-1", driver="qemu", platform="qemu_cortex_m3", options=options)
    bc.tools["cmake"] = str(cmake)
    return Arbiter(make_config(tmp_path, [bc])), build


@pytest.mark.parametrize(
    ("options", "target"), [({}, "run"), ({"emulator": "renode"}, "run_renode")]
)
async def test_emulator_runs_the_build_target(tmp_path, options, target):
    arb, build = setup(tmp_path, **options)
    await arb.start()
    try:
        s = arb.register_session(agent_kind="claude", label="t")["id"]
        tok = (await arb.acquire(s, "qemu-1"))["lease_token"]
        res = await arb.flash(s, tok, str(build))
        while res.get("status") == "running":
            res = await arb.op_status(res["op_id"], 5)
        assert res["status"] == "done" and res["boot_confirmed"], res
        m = await arb.expect(s, tok, r"emulated by (\S+) from (\S+)", 5)
        assert m["groups"] == [target, str(build)]
        out = await arb.shell_exec(s, tok, "ping")
        assert out["untrusted_device_output"] == "you said ping"
        drv = arb.boards["qemu-1"].driver
        assert isinstance(drv, EmulatorDriver)
        assert drv.describe()["emulator"]["build_dir"] == str(build)
        await arb.power(s, tok, "off")
        assert not drv.running
        await arb.power(s, tok, "on")
        await until(lambda: drv.running)
    finally:
        await arb.stop()


async def test_emulator_needs_a_cmake_build(tmp_path):
    arb, build = setup(tmp_path)
    (build / "CMakeCache.txt").unlink()
    await arb.start()
    try:
        s = arb.register_session(agent_kind="claude", label="t")["id"]
        tok = (await arb.acquire(s, "qemu-1"))["lease_token"]
        res = await arb.flash(s, tok, str(build))
        while res.get("status") == "running":
            res = await arb.op_status(res["op_id"], 5)
        assert res["status"] == "failed" and "west build -b qemu_cortex_m3" in str(res)
    finally:
        await arb.stop()
