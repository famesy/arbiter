from __future__ import annotations

from arbiter.config import load_config
from arbiter.service import _shell_lines, _yaml_list

from .test_service import done, lease_for


async def test_shell_exec_returns_clean_output(arb, build_dir):
    s, tok = await lease_for(arb)
    await done(arb, await arb.flash(s, tok, str(build_dir)))
    await arb.expect(s, tok, r"uart:~\$ ", 5)
    res = await arb.shell_exec(s, tok, "kernel uptime")
    assert res["prompt_seen"] is True, res
    lines = res["untrusted_device_output"].splitlines()
    assert len(lines) == 1 and lines[0].startswith("Uptime: "), res
    res = await arb.shell_exec(s, tok, "device list")
    assert res["untrusted_device_output"].splitlines() == [
        "devices:",
        "- uart@8000 (READY)",
        "- gpio@842500 (READY)",
    ]


async def test_shell_exec_unknown_command_never_reaches_the_board(arb, build_dir):
    s, tok = await lease_for(arb)
    await done(arb, await arb.flash(s, tok, str(build_dir)))
    end = arb.boards["sim-1"].hub.end()
    res = await arb.shell_exec(s, tok, "kernal uptime")
    assert res["error"].startswith("kernal: not a shell command")
    assert res["did_you_mean"] == ["kernel"]
    assert arb.boards["sim-1"].hub.end() == end


async def test_shell_exec_reports_a_crash(arb, build_dir):
    s, tok = await lease_for(arb)
    await done(arb, await arb.flash(s, tok, str(build_dir)))
    await arb.expect(s, tok, r"uart:~\$ ", 5)
    res = await arb.shell_exec(s, tok, "sim assert", timeout_s=1)
    assert res["prompt_seen"] is False
    assert res["crash"]["kind"] == "assert"


def test_shell_lines_strip_vt100_and_notes():
    raw = "kernel uptime\r\n\x1b[2m[claude-1a] > kernel uptime\x1b[0m\nUptime: 5 ms\r\n\x1b[1;32m"
    assert _shell_lines(raw) == ["kernel uptime", "Uptime: 5 ms"]


def test_hardware_map_carries_fixtures_and_twister_keys(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
[[board]]
id = "dk"
driver = "sim"
fixtures = ["gpio_loopback"]
runner_params = ["--tool-opt=-SelectEmuBySN 123"]
[board.twister]
flash_timeout = 120
"""
    )
    bc = load_config(cfg).boards[0]
    assert bc.fixtures == ["gpio_loopback"] and bc.twister == {"flash_timeout": 120}
    text = _yaml_list([{"id": "x", "fixtures": bc.fixtures, "flash_timeout": 120, "ok": True}])
    assert text == (
        '- id: "x"\n  fixtures:\n    - "gpio_loopback"\n  flash_timeout: 120\n  ok: true\n'
    )


def test_unknown_twister_key_is_refused(tmp_path):
    import pytest

    cfg = tmp_path / "config.toml"
    cfg.write_text('[[board]]\nid = "dk"\n[board.twister]\nflash_timout = 1\n')
    with pytest.raises(ValueError, match="flash_timout"):
        load_config(cfg)


async def test_fixtures_select_boards(tmp_path):
    from arbiter.service import Arbiter

    from .conftest import make_config, sim_board

    a = Arbiter(make_config(tmp_path, [sim_board("a"), sim_board("b", fixtures=["loopback"])]))
    await a.start()
    try:
        s = a.register_session(agent_kind="claude", label="t")["id"]
        res = await a.acquire(s, {"platform": "nrf9161dk", "fixtures": ["loopback"]}, "fixture")
        assert res["status"] == "granted" and res["board"] == "b"
    finally:
        await a.stop()
