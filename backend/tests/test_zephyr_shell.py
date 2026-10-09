"""Shell command extraction from Zephyr ELF images. The fixtures in data/zephyr_shell are
built from shell.c there, which lays the tables out as Zephyr's shell.h does."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
from arbiter.config import BoardConfig
from arbiter.service import Arbiter
from arbiter.zephyr_shell import ShellCommand, from_build, from_elf, normalize

from .conftest import make_config
from .test_detect_and_hooks import write_elf32
from .test_service import done, lease_for

DATA = Path(__file__).parent / "data" / "zephyr_shell"


Node = tuple[str, int, int, bool, list[Any]]


def tree(cmds: list[ShellCommand]) -> list[Node]:
    return [(c.name, c.mandatory, c.optional, c.dynamic, tree(c.subcommands)) for c in cmds]


EXPECTED: list[Node] = [
    ("app", 1, 0, False, [("start", 1, 0, False, []), ("stop", 1, 0, False, [])]),
    ("device", 2, 0, True, []),
    ("help", 1, 0, False, []),
    (
        "kernel",
        1,
        0,
        False,
        [
            ("version", 1, 0, False, []),
            ("uptime", 1, 1, False, []),
            ("thread", 1, 0, False, []),
        ],
    ),
]


@pytest.mark.parametrize(
    "fixture",
    ["shell_arm.elf", "shell_armbe.elf", "shell_a64.elf", "shell32.elf", "shell64pad.elf"],
)
def test_reads_static_section_and_dynamic_commands(fixture):
    res = from_elf(DATA / fixture)
    assert res.available, res.reason
    assert tree(res.commands) == EXPECTED
    kernel = res.commands[3]
    assert kernel.help == "Kernel commands" and kernel.subcommands[1].help == "Kernel uptime."
    assert res.commands[2].help is None  # built without help text
    assert res.count() == 9


def test_image_without_shell_or_not_an_elf(tmp_path):
    write_elf32(tmp_path / "noshell.elf", {"_SEGGER_RTT": 0x20000400})
    res = from_elf(tmp_path / "noshell.elf")
    assert not res.available and res.reason == "the image has no shell"
    (tmp_path / "junk.elf").write_bytes(b"not an elf")
    assert "cannot read" in from_elf(tmp_path / "junk.elf").reason
    assert not from_build(tmp_path / "missing").available


def test_empty_command_table_is_no_shell(tmp_path):
    # Zephyr's linker script defines the section bounds even without CONFIG_SHELL.
    z = tmp_path / "zephyr"
    z.mkdir()
    bounds = {"_shell_root_cmds_list_start": 0x8000, "_shell_root_cmds_list_end": 0x8000}
    write_elf32(z / "zephyr.elf", bounds)
    res = from_elf(z / "zephyr.elf")
    assert not res.available and res.reason == "the image has no shell"
    (z / ".config").write_text("CONFIG_UART_CONSOLE=y\n# CONFIG_SHELL is not set\n")
    res = from_build(tmp_path)
    assert not res.available and res.reason == "the image was built without CONFIG_SHELL"
    (z / "zephyr.elf").unlink()
    assert from_build(tmp_path).reason == f"no zephyr.elf in {z}"


def test_stored_empty_record_reads_as_no_shell():
    old = {"board": "b", "available": True, "reason": "", "count": 0, "commands": []}
    assert normalize(old) == {**old, "available": False, "reason": "the image has no shell"}
    good = {"available": True, "count": 1, "commands": [{"name": "help"}]}
    assert normalize(good) is good and normalize(None) is None


def sysbuild_with_shell(root: Path) -> Path:
    b = root / "build"
    for img in ("mcuboot", "app"):
        (b / img / "zephyr").mkdir(parents=True)
        (b / img / "zephyr" / ".config").write_text("CONFIG_UART_CONSOLE=y\n")
    (b / "zephyr").mkdir()
    (b / "zephyr" / ".config").write_text("SB_CONFIG_BOOTLOADER_MCUBOOT=y\n")
    (b / "domains.yaml").write_text(
        f"default: app\nbuild_dir: {b}\ndomains:\n"
        f"  - name: mcuboot\n    build_dir: {b / 'mcuboot'}\n"
        f"  - name: app\n    build_dir: {b / 'app'}\n"
    )
    write_elf32(b / "mcuboot" / "zephyr" / "zephyr.elf", {"_SEGGER_RTT": 0x20000400})
    shutil.copy(DATA / "shell_arm.elf", b / "app" / "zephyr" / "zephyr.elf")
    return b


def test_sysbuild_reads_the_default_image(tmp_path):
    res = from_build(sysbuild_with_shell(tmp_path))
    assert res.available and res.image == "app" and res.count() == 9


async def test_flash_records_commands_for_the_board(tmp_path):
    build = sysbuild_with_shell(tmp_path)
    board = BoardConfig(
        id="cmd-1",
        driver="command",
        platform="custom",
        commands={"flash": [sys.executable, "-c", "pass"]},
    )
    arb = Arbiter(make_config(tmp_path, [board]))
    await arb.start()
    try:
        assert not arb.shell_commands("cmd-1")["available"]
        assert (
            arb.snapshot()["boards"][0]["shell_reason"]
            == "nothing has been flashed through arbiter yet"
        )
        check = [c for c in (await arb.doctor())["checks"] if c["name"].endswith("shell commands")]
        assert check[0]["status"] == "WARN" and "nothing has been flashed" in check[0]["detail"]
        q = arb.bus.subscribe()
        s, tok = await lease_for(arb, board="cmd-1")
        res = await done(arb, await arb.flash(s, tok, str(build)))
        assert res["status"] == "done" and res["shell_commands"] == 9
        info = arb.shell_commands("cmd-1")
        assert info["available"] and info["image"] == "app" and info["build_dir"] == str(build)
        assert [c["name"] for c in info["commands"]] == ["app", "device", "help", "kernel"]
        assert arb.snapshot()["boards"][0]["shell_commands"] == 9
        assert arb.snapshot()["boards"][0]["shell_reason"] is None
        check = [c for c in (await arb.doctor())["checks"] if c["name"].endswith("shell commands")]
        assert check[0] == {
            "status": "OK",
            "name": "board cmd-1: shell commands",
            "detail": "9 from app",
            "board": "cmd-1",
        }
        kinds = []
        while not q.empty():
            kinds.append(q.get_nowait()["kind"])
        assert "board.shell" in kinds
    finally:
        await arb.stop()
    again = Arbiter(make_config(tmp_path, [board]))  # remembered across restarts
    await again.start()
    try:
        assert again.shell_commands("cmd-1")["count"] == 9
    finally:
        await again.stop()


async def test_sim_board_offers_its_own_shell(arb, build_dir):
    s, tok = await lease_for(arb)
    res = await done(arb, await arb.flash(s, tok, str(build_dir)))
    assert res["shell_commands"] == 11
    names = [c["name"] for c in arb.shell_commands("sim-1")["commands"]]
    assert names == ["device", "help", "kernel", "sim", "test"]
