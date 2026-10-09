from __future__ import annotations

import asyncio
import sys
import textwrap
from pathlib import Path

from arbiter.coredump import Tools, analyze, complete, find_tools, parse_gdb

GDB_OUT = """\
Remote debugging using 127.0.0.1:40000
0x0000a3f2 in sensor_read (dev=0x0) at ../src/main.c:42
42\t\treturn *dev->data;
#0  0x0000a3f2 in sensor_read (dev=0x0) at ../src/main.c:42
#1  0x0000a41c in main () at ../src/main.c:77
#2  0x0000c001 in bg_thread_main (unused1=<optimized out>) at zephyr/kernel/init.c:550
r0             0x0                 0
pc             0xa3f2              0xa3f2 <sensor_read+10>
  Id   Target Id         Frame
* 1    Thread 1 (main)   0x0000a3f2 in sensor_read (dev=0x0) at ../src/main.c:42
  2    Thread 2 (idle)   arch_cpu_idle () at zephyr/arch/arm/core/cortex_m/cpu_idle.c:99

Thread 2 (Thread 2 (idle)):
#0  arch_cpu_idle () at zephyr/arch/arm/core/cortex_m/cpu_idle.c:99
"""

DUMP = ["#CD:BEGIN#", "#CD:5a4501000300050000000000", "#CD:END#"]


def test_parse_gdb_output():
    frames, threads = parse_gdb(GDB_OUT)
    assert [f["function"] for f in frames] == ["sensor_read", "main", "bg_thread_main"]
    assert frames[0]["file"] == "../src/main.c" and frames[0]["line"] == 42
    assert frames[0]["args"] == "dev=0x0" and frames[0]["address"] == "0x0000a3f2"
    assert len(threads) == 2 and threads[0].startswith("* 1")


def test_complete_dump_checks():
    assert complete(DUMP) is None
    assert "CONFIG_DEBUG_COREDUMP" in (complete([]) or "")
    assert "cut off" in (complete(DUMP[:2]) or "")
    assert "#CD:ERROR" in (complete([*DUMP[:2], "#CD:ERROR CANNOT DUMP#", "#CD:END#"]) or "")


def _script(path: Path, body: str) -> Path:
    path.write_text(textwrap.dedent(body))
    return path


def test_analyze_bridges_gdb_to_the_stdio_server(tmp_path):
    """The real tools are replaced by small scripts: the parser copies the log, the server
    answers one request over stdio, and "gdb" connects to the loopback port it is given."""
    parser = _script(
        tmp_path / "parser.py",
        """
        import shutil, sys
        shutil.copy(sys.argv[1], sys.argv[2])
        """,
    )
    server = _script(
        tmp_path / "server.py",
        """
        import sys
        assert sys.argv[1] == "--pipe"
        req = sys.stdin.buffer.read(4)
        sys.stdout.buffer.write(b"pong:" + req)
        sys.stdout.buffer.flush()
        """,
    )
    gdb = _script(
        tmp_path / "gdb.py",
        f"""
        import socket, sys
        args = sys.argv[1:]
        target = next(a for a in args if a.startswith("target remote "))
        host, port = target.split()[-1].rsplit(":", 1)
        s = socket.create_connection((host, int(port)))
        s.sendall(b"ping")
        reply = s.recv(64).decode()
        print("got", reply)
        print({GDB_OUT!r})
        """,
    )
    tools = Tools([sys.executable], parser, server, [sys.executable, str(gdb)])
    elf = tmp_path / "zephyr.elf"
    elf.write_bytes(b"\x7fELF")
    rep = analyze(DUMP, elf, tools, tmp_path / "work")
    assert rep.error is None, rep
    assert rep.ok and rep.backtrace[0]["function"] == "sensor_read"
    assert "got pong:ping" in rep.gdb_output
    assert Path(rep.files["bin"]).read_text().startswith("#CD:BEGIN#")


def test_analyze_reports_a_failing_parser(tmp_path):
    parser = _script(tmp_path / "parser.py", "import sys\nprint('bad dump'); sys.exit(1)\n")
    tools = Tools([sys.executable], parser, parser, [sys.executable])
    rep = analyze(DUMP, tmp_path / "zephyr.elf", tools, tmp_path / "work")
    assert not rep.ok and "bad dump" in (rep.error or "")


def test_find_tools_from_the_build(tmp_path):
    zephyr = tmp_path / "zephyr"
    scripts = zephyr / "scripts" / "coredump"
    scripts.mkdir(parents=True)
    for name in ("coredump_serial_log_parser.py", "coredump_gdbserver.py"):
        (scripts / name).write_text("")
    build = tmp_path / "build"
    (build / "zephyr").mkdir(parents=True)
    (build / "zephyr" / ".config").write_text("CONFIG_BOARD=x\n")
    gdb = tmp_path / "arm-zephyr-eabi-gdb"
    gdb.write_text("")
    (build / "CMakeCache.txt").write_text(f"ZEPHYR_BASE:PATH={zephyr}\nCMAKE_GDB:FILEPATH={gdb}\n")
    tools = find_tools(build, build)
    assert isinstance(tools, Tools), tools
    assert tools.gdb == [str(gdb)] and tools.python == [sys.executable]
    (build / "CMakeCache.txt").write_text(f"ZEPHYR_BASE:PATH={zephyr}\n")
    assert "CMAKE_GDB" in str(find_tools(build, build))


async def test_coredump_lines_after_halting_reach_the_report(arb, build_dir):
    from .test_service import done, lease_for

    s, tok = await lease_for(arb)
    await done(arb, await arb.flash(s, tok, str(build_dir)))
    await arb.write(s, tok, "sim coredump")
    for _ in range(50):
        info = arb.last_crash(s, tok)
        if info["crash"] and info["crash"].get("coredump_report"):
            break
        await asyncio.sleep(0.05)
    c = info["crash"]
    assert c["coredump"] == 3 and c["ended_by"] == "halted"
    # the sim build has no CMakeCache, so the tools can't be found; the report says why
    assert c["coredump_report"]["ok"] is False
    assert "ZEPHYR_BASE" in c["coredump_report"]["error"]
