from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest
from arbiter import crash as cr
from arbiter.crash import Crash, CrashWatcher, symbolize
from arbiter.elf import Elf

from .test_service import done, lease_for

DATA = Path(__file__).parent / "data" / "zephyr_shell"

MPU_FAULT = """\
[00:00:01.000,000] <inf> app: sending
[00:00:01.100,000] <err> os: ***** MPU FAULT *****
[00:00:01.100,000] <err> os:   Data Access Violation
[00:00:01.100,000] <err> os:   MMFAR Address: 0x0
[00:00:01.100,000] <err> os: r0/a1:  0x00000000  r1/a2:  0x00000001  r2/a3:  0x00000000
[00:00:01.100,000] <err> os: r3/a4:  0x00000000 r12/ip:  0x00000000 r14/lr:  0x0000041b
[00:00:01.100,000] <err> os:  xpsr:  0x61000000
[00:00:01.100,000] <err> os: Faulting instruction address (r15/pc): 0x00000420
[00:00:01.100,000] <err> os: >>> ZEPHYR FATAL ERROR 19: Unknown error on CPU 0
[00:00:01.100,000] <err> os: Current thread: 0x20000c08 (main)
[00:00:01.200,000] <err> os: Halting system
"""


def feed_all(w: CrashWatcher, text: str, channel: str = "uart:app", chunk: int = 7) -> None:
    data = text.encode()
    end = 0
    for i in range(0, len(data), chunk):
        piece = data[i : i + chunk]
        end += len(piece)
        w.feed(channel, piece, end)


def collect(text: str, **kw) -> list[Crash]:
    out: list[Crash] = []
    w = CrashWatcher("b", out.append)
    feed_all(w, text, **kw)
    w.flush()
    return out


def test_mpu_fault_block_is_parsed():
    (c,) = collect(MPU_FAULT)
    assert c.kind == "fault" and c.title == "MPU FAULT"
    assert c.registers["pc"] == "0x00000420" and c.registers["lr"] == "0x0000041b"
    assert c.registers["r1"] == "0x00000001"
    assert c.thread == "main" and c.thread_addr == "0x20000c08"
    assert c.reason_code == 19 and c.fault_address == {"MMFAR": "0x00000000"}
    assert "Data Access Violation" in c.details
    assert c.ended_by == "halted"
    assert c.context == ["[00:00:01.000,000] <inf> app: sending"]
    # the block starts at the banner line's byte offset in the channel
    assert c.cursor == MPU_FAULT.index("[00:00:01.100,000] <err> os: *****")
    assert c.summary() == "MPU FAULT (Unknown error) in thread main at pc 0x00000420"


def test_assert_and_message():
    text = (
        "ASSERTION FAIL [buf != NULL] @ WEST_TOPDIR/app/src/main.c:42\r\n"
        "\tbuffer pool exhausted\r\n"
        "[00:00:02.000,000] <err> os: >>> ZEPHYR FATAL ERROR 4: Kernel panic on CPU 0\r\n"
        "[00:00:02.000,000] <err> os: Current thread: 0x20000c08 (main)\r\n"
        "[00:00:02.000,000] <err> os: Halting system\r\n"
    )
    (c,) = collect(text)
    assert c.kind == "assert"
    assert c.assertion == {
        "expr": "buf != NULL",
        "file": "WEST_TOPDIR/app/src/main.c",
        "line": 42,
        "message": "buffer pool exhausted",
    }
    assert c.where() == "WEST_TOPDIR/app/src/main.c:42"
    assert c.reason == "Kernel panic"


def test_stack_overflow_and_reboot_ends_block():
    text = (
        "<err> os: ***** USAGE FAULT *****\n"
        "<err> os:   Stack overflow (context area not valid)\n"
        "<err> os: >>> ZEPHYR FATAL ERROR 2: Stack overflow on CPU 0\n"
        "<err> os: Current thread: 0x20001000 (sensor_thread)\n"
        "*** Booting nRF Connect SDK v3.4.1 ***\n"
        "<inf> app: started\n"
    )
    (c,) = collect(text)
    assert c.kind == "stack_overflow" and c.thread == "sensor_thread"
    assert c.ended_by == "reboot"
    assert not any("Booting" in ln for ln in c.lines)


def test_tfm_secure_fault():
    text = (
        "FATAL ERROR: SecureFault\n"
        "Here is some context for the exception:\n"
        "    EXC_RETURN (LR): 0xFFFFFFAD\n"
        "    Exception frame at: 0x20001BE0\n"
        "        PC:  0x00012345\n"
        "        LR:  0x00011111\n"
    )
    (c,) = collect(text, channel="uart:tfm")
    assert c.kind == "secure_fault" and c.title == "TF-M SecureFault"
    assert c.registers["pc"] == "0x00012345" and c.registers["lr"] == "0x00011111"
    assert c.channel == "uart:tfm" and c.ended_by == "quiet"


def test_call_trace_addresses():
    text = (
        ">>> ZEPHYR FATAL ERROR 0: CPU exception on CPU 0\n"
        "call trace:\n"
        "     0: sp: 0x80001234 ra: 0x80000100\n"
        "     1: sp: 0x80001240 ra: 0x80000200\n"
        "Halting system\n"
    )
    (c,) = collect(text)
    assert c.call_trace == ["0x80000100", "0x80000200"]


def test_coredump_lines_are_kept_apart():
    text = MPU_FAULT.replace(
        "[00:00:01.200,000] <err> os: Halting system\n",
        "[00:00:01.100,000] <err> os: #CD:BEGIN#\n"
        "[00:00:01.100,000] <err> os: #CD:5a4501000300050000000000\n"
        "[00:00:01.100,000] <err> os: #CD:END#\n"
        "[00:00:01.200,000] <err> os: Halting system\n",
    )
    (c,) = collect(text)
    assert c.coredump == ["#CD:BEGIN#", "#CD:5a4501000300050000000000", "#CD:END#"]
    assert not any("#CD:" in ln for ln in c.lines)


async def test_quiet_timer_ends_a_block():
    got: list[Crash] = []
    w = CrashWatcher("b", got.append, quiet_s=0.05)
    w.feed("uart:app", b"<err> os: ***** HARD FAULT *****\n", None)
    assert not got
    await asyncio.sleep(0.15)
    assert len(got) == 1 and got[0].ended_by == "quiet"


def test_function_at_uses_symbol_sizes():
    elf = Elf.load(DATA / "shell_arm.elf")
    assert elf.function_at(0x202C6) == ("dyn_get", 6)
    assert elf.function_at(0x10) is None


def test_symbolize_falls_back_to_symtab(tmp_path, monkeypatch):
    build = tmp_path / "build"
    (build / "zephyr").mkdir(parents=True)
    (build / "zephyr" / ".config").write_text("CONFIG_LOG_MODE_DEFERRED=y\n")
    shutil.copy(DATA / "shell_arm.elf", build / "zephyr" / "zephyr.elf")
    monkeypatch.setattr(cr, "find_addr2line", lambda *_: None)
    c = Crash("cr-1", "b", "uart:app", 0.0, 0, registers={"pc": "0x000202c6", "lr": "0x000202d5"})
    symbolize(c, cr.image_info(build))
    assert c.symbolized_with == "symtab"
    assert c.symbols["pc"]["text"] == "dyn_get+0x6"
    assert c.symbols["lr"]["text"] == "h+0x3"  # (lr & ~1) - 1 = 0x202d3, inside h
    assert any("deferred" in h for h in c.hints)
    assert c.where() == "dyn_get+0x6"


def test_symbolize_without_image_says_why():
    c = Crash("cr-1", "b", "uart:app", 0.0, 0, registers={"pc": "0x1"})
    symbolize(c, None)
    assert c.symbols == {} and "not symbolised" in c.hints[0]


def test_addr2line_from_cmake_cache(tmp_path):
    img = tmp_path / "build"
    img.mkdir()
    tool = img / "arm-zephyr-eabi-addr2line"
    tool.write_text("")
    gdb = img / "arm-zephyr-eabi-gdb"
    (img / "CMakeCache.txt").write_text(f"CMAKE_GDB:FILEPATH={gdb}\n")
    assert cr.find_addr2line(img, 40) == str(tool)


@pytest.mark.skipif(
    not (shutil.which("gcc") and shutil.which("addr2line")), reason="needs gcc and addr2line"
)
def test_symbolize_with_real_addr2line(tmp_path):
    src = tmp_path / "main.c"
    src.write_text("int crash_me(int *p) {\n  return *p + 1;\n}\nint main(void) { return 0; }\n")
    build = tmp_path / "build"
    (build / "zephyr").mkdir(parents=True)
    (build / "zephyr" / ".config").write_text('CONFIG_BOARD="native_sim"\n')
    elf = build / "zephyr" / "zephyr.exe"
    subprocess.run(["gcc", "-g", "-O0", "-o", str(elf), str(src)], check=True)
    addr = Elf.load(elf).symbol("crash_me")
    assert addr is not None
    c = Crash("cr-1", "b", "stdout", 0.0, 0, registers={"pc": f"0x{addr + 8:08x}"})
    symbolize(c, cr.image_info(build))
    assert c.symbolized_with == "addr2line"
    assert c.symbols["pc"]["function"] == "crash_me"
    assert c.symbols["pc"]["file"].endswith("main.c")
    assert c.symbols["pc"]["line"] in (1, 2)


# ---------------------------------------------------------------- through the daemon
async def test_crash_reported_to_agent(arb, build_dir):
    s, tok = await lease_for(arb)
    res = await done(arb, await arb.flash(s, tok, str(build_dir)))
    assert res["status"] == "done"
    await arb.write(s, tok, "sim fault")
    m = await arb.expect(s, tok, "never-printed", 0.5)
    assert m["matched"] is False
    assert m["crash"]["kind"] == "fault" and "BUS FAULT" in m["crash"]["summary"]
    assert "last_crash" in m["hint"]
    await asyncio.sleep(0.05)  # the report is symbolised off the event loop
    info = arb.last_crash(s, tok)
    c = info["crash"]
    assert c["thread"] == "main" and c["registers"]["pc"] == "0x0000a3f2"
    assert c["fault_address"] == {"BFAR": "0x50008120"}
    assert c["ended_by"] == "reset"
    assert c["image"]["build_dir"] == str(build_dir.resolve())  # flashed through arbiter
    inbox = arb.inbox(s)
    assert any(n["kind"] == "crash" for n in inbox)
    assert arb.list_boards()[0]["last_crash"]["id"] == c["id"]
    read = arb.console_read(s, tok, cursor=0, max_bytes=65536)
    assert read["crashes"][0]["id"] == c["id"]


async def test_same_crash_again_counts_as_repeat(arb, build_dir):
    s, tok = await lease_for(arb)
    await done(arb, await arb.flash(s, tok, str(build_dir)))
    for _ in range(2):
        await arb.write(s, tok, "sim fault")
        await arb.expect(s, tok, r"Booting", 2, since="now")
    await asyncio.sleep(0.05)
    info = arb.last_crash(None, board_id="sim-1", history=True)
    assert info["crash"]["repeats"] == 2 and info["earlier"] == []
    assert info["crash"]["summary"].endswith("[2 times]")


async def test_no_crash_yet(arb):
    assert arb.last_crash(None, board_id="sim-1")["crash"] is None
