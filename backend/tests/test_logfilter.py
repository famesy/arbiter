from __future__ import annotations

import pytest
from arbiter.errors import ArbiterError
from arbiter.logfilter import LogFilter, apply

from .test_service import done, lease_for

LOG = (
    b"[00:00:01.000,000] <dbg> bt_hci: noise\r\n"
    b"[00:00:01.100,000] <inf> app: started\r\n"
    b"\x1b[1;33m[00:00:01.200,000] <wrn> bt_conn: slow\x1b[0m\r\n"
    b"printk without a level\r\n"
    b"uart:~$ [00:00:01.300,000] <err> sensor: read failed\r\n"
    b"[00:00:01.400,000] <err> sensor: again\r\n"
    b"[00:00:01.5"
)


def kept(data: bytes, **kw: str) -> list[str]:
    f = LogFilter.make(**kw)
    assert f is not None
    return apply(data, f, final=True)[0].splitlines()


def test_level_keeps_that_level_and_worse():
    lines = kept(LOG, level="warning")
    assert len(lines) == 3 and "slow" in lines[0] and "again" in lines[2]


def test_module_globs_and_exclusions():
    assert [ln.split("> ")[1] for ln in kept(LOG, module="bt_*")] == [
        "bt_hci: noise",
        "bt_conn: slow\x1b[0m",
    ]
    lines = kept(LOG, module="-bt_*")
    assert len(lines) == 3 and all("bt_" not in ln for ln in lines)


def test_grep_alone_keeps_non_log_lines():
    assert kept(LOG, grep="printk|started") == [
        kept(LOG, module="app")[0],
        "printk without a level",
    ]


def test_partial_line_is_held_back_and_counts_are_reported():
    f = LogFilter.make(level="err")
    assert f is not None
    _text, used, stats = apply(LOG, f, final=False)
    assert used == LOG.rfind(b"\n") + 1
    assert stats["kept_lines"] == 2
    assert stats["errors_warnings_by_module"] == {"wrn": {"bt_conn": 1}, "err": {"sensor": 2}}
    # a single long line with no newline is not held back forever
    assert apply(b"no newline yet", f, final=False)[1] == len(b"no newline yet")


def test_bad_filters_are_refused():
    assert LogFilter.make() is None
    with pytest.raises(ValueError):
        LogFilter.make(level="loud")
    with pytest.raises(ValueError):
        LogFilter.make(grep="(")


async def test_console_read_filters_and_moves_the_cursor_on(arb, build_dir):
    s, tok = await lease_for(arb)
    await done(arb, await arb.flash(s, tok, str(build_dir)))
    await arb.expect(s, tok, r"uart:~\$ ", 5)
    await arb.write(s, tok, "sim fault", True)
    await arb.expect(s, tok, r"Resetting system", 5)
    res = arb.console_read(s, tok, level="err", module="-fatal_error")
    lines = res["untrusted_device_output"].splitlines()
    assert lines and all("<err> os:" in ln for ln in lines), lines
    assert res["filter"]["errors_warnings_by_module"]["err"]["fatal_error"] == 1
    again = arb.console_read(s, tok, level="err")
    assert "BUS FAULT" not in again["untrusted_device_output"]
    with pytest.raises(ArbiterError):
        arb.console_read(s, tok, level="loud")
