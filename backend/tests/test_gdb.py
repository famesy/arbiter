from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from arbiter.errors import ArbiterError
from arbiter.gdb import _cstring, check_command, mi_field, mi_unquote

from .test_service import done, lease_for


def test_allowlist():
    for ok in (
        "bt",
        "bt full",
        "p/x counter",
        "x/16xw 0x20000000",
        "break main.c:42",
        "watch buf[3]",
        "set var counter = 0",
        "thread apply all bt",
        "monitor reset",
        "info registers",
        "finish",
    ):
        check_command(ok)
    for bad in (
        "shell ls",
        "python print(1)",
        "dump memory /tmp/x 0 1",
        "set logging file /tmp/x",
        "source evil.gdb",
        "thread apply all shell id",
        "monitor exec SetRTTAddr",
        "call abort()",
        "",
    ):
        with pytest.raises(ArbiterError):
            check_command(bad)


def test_mi_strings():
    assert mi_unquote(r"line\n\"q\"\t\\") == 'line\n"q"\t\\'
    assert mi_unquote(r"caf\303\251") == "café"
    rec = r'*stopped,reason="breakpoint-hit",frame={func="spin",file="main.c",line="7"}'
    assert mi_field(rec, "reason") == "breakpoint-hit" and mi_field(rec, "line") == "7"
    assert _cstring(r'"main", \'\\000\' <repeats 27 times>') == "main"


# A host program with the few kernel structures inspect_hung reads, shaped like Zephyr's.
PROGRAM = """\
#include <unistd.h>
struct k_sem { int count; } my_sem;
struct _thread_base { unsigned char thread_state; signed char prio; void *pended_on; };
struct k_thread { struct _thread_base base; struct k_thread *next_thread; char name[32]; };
struct _cpu { struct k_thread *current; };
struct z_kernel { struct _cpu cpus[1]; struct k_thread *threads; } _kernel;
struct k_thread main_thread = { { 0, 0, 0 }, 0, "main" };
struct k_thread sensor = { { 0x02, 5, &my_sem }, &main_thread, "sensor" };
volatile int counter;
void spin(void) {
  counter++;
  usleep(10000);
}
int main(void) {
  _kernel.threads = &sensor;
  _kernel.cpus[0].current = &main_thread;
  for (int i = 0; i < 3000; i++) spin();
  return 0;
}
"""


@pytest.mark.skipif(
    sys.platform != "linux" or not all(shutil.which(t) for t in ("gcc", "gdb", "gdbserver")),
    reason="needs gcc, gdb and gdbserver on Linux",
)
async def test_gdb_session_against_gdbserver(arb, build_dir):
    src = build_dir / "main.c"
    src.write_text(PROGRAM)
    exe = build_dir / "zephyr" / "zephyr.exe"
    await asyncio.to_thread(
        subprocess.run, ["gcc", "-g", "-O0", "-o", str(exe), str(src)], check=True
    )
    rt = arb.boards["sim-1"]
    rt.driver.capabilities = rt.driver.capabilities | {"debug"}

    async def debugserver(build: Path, port: int, log_path: Path):
        return await asyncio.create_subprocess_exec(
            "gdbserver",
            f"127.0.0.1:{port}",
            str(exe),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

    rt.driver.debugserver = debugserver
    s, tok = await lease_for(arb)
    await done(arb, await arb.flash(s, tok, str(build_dir)))
    try:
        res = await arb.gdb_start(s, tok)
        assert res["status"] == "attached", res
        res = await arb.gdb_batch(s, tok, ["break spin"])
        assert "Breakpoint 1" in res["results"][0]["output"], res
        res = await arb.gdb_continue(s, tok, 10)
        assert res["stopped"]["reason"] == "breakpoint-hit", res
        assert res["stopped"]["func"] == "spin"
        assert res["backtrace"][0]["function"] == "spin"
        assert res["backtrace"][1]["function"] == "main"
        res = await arb.gdb_batch(s, tok, ["next", "print counter"])
        assert res["results"][0].get("stopped", {}).get("reason") == "end-stepping-range", res
        assert "= " in res["results"][1]["output"]
        with pytest.raises(ArbiterError) as e:
            await arb.gdb_batch(s, tok, ["shell id"])
        assert e.value.code == "NOT_ALLOWED"
        await arb.gdb_batch(s, tok, ["delete"])
        await arb.gdb_continue(s, tok, 0.5)  # runs on, then gets halted after the timeout
        hung = await arb.inspect_hung(s, tok)
        names = [f["function"] for f in hung["backtrace"]]
        assert "main" in names, hung
        assert hung["threads"] == [
            {
                "address": hung["threads"][0]["address"],
                "name": "sensor",
                "priority": 5,
                "state": ["pending"],
                "pended_on": "my_sem",
            },
            {
                "address": hung["threads"][1]["address"],
                "name": "main",
                "priority": 0,
                "state": ["ready"],
                "current": True,
            },
        ], hung
        assert hung["resumed"] is True
    finally:
        res = await arb.gdb_stop(s, tok)
    assert res["detached"] is True and rt.debug is None


async def test_gdb_on_a_board_without_debugger(arb):
    s, tok = await lease_for(arb)
    with pytest.raises(ArbiterError) as e:
        await arb.gdb_start(s, tok)
    assert e.value.code == "NOT_SUPPORTED"
