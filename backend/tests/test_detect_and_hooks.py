from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest
from arbiter.console.detect import detect_from_build, detect_from_elf
from arbiter.elf import elf_symbol
from arbiter.hooks import check_command
from arbiter.plugins import render


def write_elf32(path: Path, symbols: dict[str, int]) -> None:
    """A minimal little-endian ELF32 with a .symtab and .strtab, enough for elf_symbol()."""
    strtab = b"\x00"
    offsets = {}
    for name in symbols:
        offsets[name] = len(strtab)
        strtab += name.encode() + b"\x00"
    symtab = b"\x00" * 16
    for name, value in symbols.items():
        symtab += struct.pack("<IIIBBH", offsets[name], value, 4, 0x11, 0, 1)
    header_size, sh_size = 52, 40
    sym_off = header_size
    str_off = sym_off + len(symtab)
    sh_off = str_off + len(strtab)
    hdr = b"\x7fELF" + bytes([1, 1, 1]) + b"\x00" * 9
    hdr += struct.pack(
        "<HHIIIIIHHHHHH", 2, 40, 1, 0, 0, sh_off, 0, header_size, 0, 0, sh_size, 3, 0
    )
    null = b"\x00" * sh_size
    sh_sym = struct.pack("<IIIIIIIIII", 0, 2, 0, 0, sym_off, len(symtab), 2, 1, 4, 16)
    sh_str = struct.pack("<IIIIIIIIII", 0, 3, 0, 0, str_off, len(strtab), 0, 0, 1, 0)
    path.write_bytes(hdr + symtab + strtab + null + sh_sym + sh_str)


def make_image(d: Path, config: str, rtt_addr: int | None = None, dts: str = "") -> None:
    (d / "zephyr").mkdir(parents=True)
    (d / "zephyr" / ".config").write_text(config)
    if dts:
        (d / "zephyr" / "zephyr.dts").write_text(dts)
    if rtt_addr is not None:
        write_elf32(d / "zephyr" / "zephyr.elf", {"main": 0x1000, "_SEGGER_RTT": rtt_addr})


def test_rtt_only_console(tmp_path):
    make_image(tmp_path / "b", "CONFIG_USE_SEGGER_RTT=y\nCONFIG_RTT_CONSOLE=y\n", 0x20020410)
    cmap = detect_from_build(tmp_path / "b")
    assert cmap.images[0].console == "rtt"
    assert cmap.resolved == "rtt" and cmap.rtt_address == 0x20020410


def test_rtt_snippet_with_uart_console_still_prints_on_uart(tmp_path):
    # NCS rtt-console snippet leaves CONFIG_UART_CONSOLE=y; on a real nRF9161 DK the output went to the UART.
    make_image(
        tmp_path / "b",
        "CONFIG_USE_SEGGER_RTT=y\nCONFIG_RTT_CONSOLE=y\nCONFIG_UART_CONSOLE=y\n",
        0x20020410,
    )
    assert detect_from_build(tmp_path / "b").images[0].console == "uart"


def test_uart_with_chosen_and_sysbuild(tmp_path):
    b = tmp_path / "build"
    b.mkdir()
    (b / "domains.yaml").write_text(
        "default: app\nbuild_dir: x\ndomains:\n  - name: mcuboot\n    build_dir: "
        f"{b / 'mcuboot'}\n  - name: app\n    build_dir: {b / 'app'}\n"
    )
    make_image(
        b, "SB_CONFIG_BOOTLOADER_MCUBOOT=y\n"
    )  # the sysbuild-level config has no console symbols
    make_image(
        b / "app",
        "CONFIG_UART_CONSOLE=y\nCONFIG_LOG_BACKEND_RTT=y\nCONFIG_USE_SEGGER_RTT=y\n",
        0x20000010,
        dts="/ { chosen { zephyr,console = &uart0; zephyr,shell-uart = &uart0; }; };",
    )
    make_image(b / "mcuboot", "CONFIG_RTT_CONSOLE=y\n")
    cmap = detect_from_build(b)
    assert [i.name for i in cmap.images] == ["app", "mcuboot"]
    assert cmap.default_image == "app"
    assert cmap.images[0].console_uart == "uart0"
    assert cmap.resolved == "both"


def test_elf_fallback(tmp_path):
    write_elf32(tmp_path / "a.elf", {"_SEGGER_RTT": 0x20000400})
    write_elf32(tmp_path / "b.elf", {"main": 1})
    assert elf_symbol(tmp_path / "a.elf", "_SEGGER_RTT") == 0x20000400
    assert detect_from_elf(tmp_path / "a.elf").resolved == "rtt"
    assert detect_from_elf(tmp_path / "b.elf").resolved == "uart"
    assert elf_symbol(tmp_path / "missing.elf", "x") is None


@pytest.mark.parametrize(
    "cmd",
    [
        "west flash -d build",
        "cd fw && west  flash",
        "nrfutil device reset --serial-number 1050978819",
        "JLinkExe -device nRF9160_xxAA",
        "cat /dev/ttyACM0",
        "picocom -b 115200 /dev/ttyACM0",
        "west twister -p nrf9161dk/nrf9161/ns --device-testing -T tests",
        "cat ~/.local/state/arbiter/admin.json",
        "pyocd flash x.hex",
        "STM32_Programmer_CLI -c port=SWD",
    ],
)
def test_hooks_deny_raw_hardware(cmd):
    assert check_command(cmd)


@pytest.mark.parametrize(
    "cmd",
    [
        "west build -b nrf9161dk/nrf9161/ns app",
        "arbiter flash build",
        "python -m arbiter run -- west twister -T x",
        "west twister -p native_sim -T tests",
        "git status",
        "ls /dev",
    ],
)
def test_hooks_allow_normal_work(cmd):
    assert check_command(cmd) is None


def test_render_drops_empty_args_and_keeps_literal_braces():
    argv = render("tool --sn {serial} {erase} --json {{x}}", {"serial": "123", "erase": ""})
    assert argv == ["tool", "--sn", "123", "--json", "{x}"]


def test_split_command_on_windows(monkeypatch):
    from arbiter import plugins

    monkeypatch.setattr(plugins, "IS_WINDOWS", True)
    cmd = r'"C:\Program Files\tool.exe" -c "import sys; print(1)" C:\fw\build {serial}'
    assert plugins.render(cmd, {"serial": "42"}) == [
        r"C:\Program Files\tool.exe",
        "-c",
        "import sys; print(1)",
        r"C:\fw\build",
        "42",
    ]


@pytest.mark.parametrize("tool", ["Bash", "PowerShell"])
def test_pre_tool_use_denies_on_each_shell_tool(tool, capsys, tmp_path, monkeypatch):
    from arbiter.hooks import pre_tool_use

    monkeypatch.setenv("ARBITER_HOME", str(tmp_path))  # no daemon: no queue hint

    pre_tool_use({"tool_name": tool, "tool_input": {"command": "nrfjprog --program fw.hex"}})
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
