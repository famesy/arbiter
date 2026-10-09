"""The TUI's console model and status text (no Textual needed)."""

from __future__ import annotations

from arbiter.tui.model import (
    BootBlock,
    ConsoleModel,
    Line,
    ShellTree,
    board_status,
    channel_names,
    lease_left,
    queue_for,
)


def lines(m: ConsoleModel) -> list[Line]:
    out: list[Line] = []
    for e in m.entries:
        out += e.lines if isinstance(e, BootBlock) else [e]
    return out


def test_levels_tags_and_parts():
    m = ConsoleModel(names=["all", "uart:app"], me="Fame")
    m.feed(
        "[00:00:01.000,000] <wrn> lte: PSM not granted\r\n"
        "\x1b[1;31m[00:00:02.000,000] <err> lte: link lost\x1b[0m\r\n"
        "\x1b[2m[you] > kernel uptime\x1b[0m\r\n"
        "\x1b[2m[claude-1a2b] > device list\x1b[0m\r\n"
        "\x1b[2m[human:Fame] > help\x1b[0m\r\n"
        "\x1b[2m[arbiter] flash ok\x1b[0m\r\n"
        "[uart:app] uart:~$ [00:00:03.120,000] <inf> app: hi\r\n"
        "uart:~$ "
    )
    ls = lines(m)
    assert (ls[0].level, ls[0].ts, ls[0].text) == (
        "w",
        "[00:00:01.000,000] ",
        "<wrn> lte: PSM not granted",
    )
    assert ls[1].level == "e"
    assert (ls[2].kind, ls[2].tag, ls[2].text) == ("you", "[you]", "> kernel uptime")
    assert (ls[3].kind, ls[3].tag) == ("agent", "[claude-1a2b]")
    assert (ls[4].kind, ls[4].tag) == ("you", "[you]")
    assert ls[5].kind == "note" and ls[5].tag is None
    assert (ls[6].src, ls[6].prompt, ls[6].ts) == ("[uart:app] ", "uart:~$ ", "[00:00:03.120,000] ")
    assert m.partial is not None and m.partial.bare_prompt


def test_firmware_text_is_not_a_tag_unless_dim():
    m = ConsoleModel()
    m.feed("[sensor] > 42\n")
    assert lines(m)[0].tag is None


def test_boot_output_folds_into_one_block():
    m = ConsoleModel()
    m.feed(
        "*** Booting MCUboot v2.1.0 ***\r\n"
        "I: Starting bootloader\r\n"
        "W: no image in secondary slot\r\n"
        "*** Booting nRF Connect SDK v2.7.0 ***\r\n"
        "*** Using Zephyr OS v3.6.99 ***\r\n"
        "<inf> app: started\r\n"
    )
    assert len(m.entries) == 2
    block = m.entries[0]
    assert isinstance(block, BootBlock)
    assert block.summary() == "Booted nRF Connect SDK v2.7.0 (5 lines, has warnings)"
    assert isinstance(m.entries[1], Line)


def test_dirty_tracking_and_trim():
    m = ConsoleModel()
    m.feed("a\nb\n")
    assert m.take_dirty() == 0
    assert m.take_dirty() == 2
    m.feed("c\n")
    assert m.take_dirty() == 2
    m.MAX_LINES, m.TRIM_SLACK = 10, 2
    m.feed("x\n" * 20)
    assert len(m.entries) == 10 and m.take_dirty() == 0


SHELL = {
    "available": True,
    "count": 3,
    "commands": [
        {"name": "help", "help": "Prints the help message."},
        {
            "name": "kernel",
            "help": "Kernel commands",
            "subcommands": [
                {"name": "uptime", "help": "Kernel uptime."},
                {"name": "version", "help": "Kernel version."},
            ],
        },
        {"name": "log", "dynamic": True},
    ],
}


def test_shell_completion():
    t = ShellTree(SHELL)
    assert t.options("") == []
    assert [c["name"] for c in t.options("", forced=True)] == ["help", "kernel", "log"]
    assert [c["name"] for c in t.options("ke")] == ["kernel"]
    assert t.accept("ke", "kernel") == "kernel "
    assert [c["name"] for c in t.options("kernel ")] == ["uptime", "version"]
    assert t.accept("kernel v", "version") == "kernel version "
    assert t.help_for("kernel up") == "kernel  Kernel commands"
    assert t.help_for("kernel uptime") == "uptime  Kernel uptime."
    assert t.options("log foo ") == []
    assert "type them freely" in t.help_for("log x y")
    assert ShellTree(None).options("k") == []


def test_status_text():
    b = {
        "id": "dk",
        "platform": "nrf9161dk/nrf9161/ns",
        "state": "LEASED",
        "lease": {"holder": "agent:claude-1", "state": "ACTIVE", "expires_at": 1090.0},
        "op": {"kind": "flash", "running": True},
        "console": {"sources": ["uart:app"]},
        "console_channels": {"ends": {"all": 1, "uart:app": 1, "rtt:app": 0}},
    }
    assert board_status(b) == ("flashing", "")
    assert lease_left(b, 1000.0) == "1m 30s left"
    assert channel_names(b) == ["all", "uart:app", "rtt:app"]
    assert board_status({"state": "OFFLINE"}) == ("offline", "err")
    assert board_status({"state": "HUMAN", "held_by": "human:Fame"}) == ("held by Fame", "")
    state = {
        "queue": [
            {"ticket": "t1", "selector": {"platform": "nrf9161dk"}},
            {"ticket": "t2", "selector": {"board_id": "other"}},
            {"ticket": "t3", "selector": {"tags": ["ppk2"]}},
        ]
    }
    assert [e["ticket"] for e in queue_for(state, b)] == ["t1"]
