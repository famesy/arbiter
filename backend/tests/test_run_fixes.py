"""Fixes from the real-agent twister run on the nRF9161 DK (2026-10-09 report, N1-N4)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from arbiter import cli, service
from arbiter.procs import run_proc
from arbiter.service import RUN_NOTE

from .test_service import done, lease_for

TWISTER = "import sys\nprint('ARGS', ' '.join(sys.argv[1:]))\n{extra}"


def twister(tmp_path: Path, extra: str = "") -> Path:
    script = tmp_path / "twister.py"
    script.write_text(TWISTER.format(extra=extra))
    return script


async def test_twister_gets_a_short_build_path_on_windows(arb, tmp_path, monkeypatch):
    monkeypatch.setattr(service, "IS_WINDOWS", True)
    s, tok = await lease_for(arb)
    cmd = [sys.executable, str(twister(tmp_path)), "--device-testing", "-T", "app"]
    res = await done(arb, await arb.run(s, tok, cmd, cwd=str(tmp_path)))
    args = next(line for line in res["tail"] if line.startswith("ARGS"))
    assert args.count("--device-testing") == 1
    assert "--hardware-map" in args and args.endswith("--short-build-path")


async def test_long_build_path_failure_gets_a_hint(arb, tmp_path):
    s, tok = await lease_for(arb)
    script = twister(
        tmp_path,
        "print('CMake Error: CMAKE_BINARY_DIR path length (120) exceeds 90 characters')\n"
        "sys.exit(1)\n",
    )
    res = await done(arb, await arb.run(s, tok, [sys.executable, str(script)], cwd=str(tmp_path)))
    assert "--short-build-path" in res["hint"]


async def test_a_run_that_leaves_the_board_unbootable_is_flagged(arb, tmp_path, build_dir):
    s, tok = await lease_for(arb)
    # twister keeps the device output in its own logs, not on stdout
    log = tmp_path / "out" / "nrf9161dk" / "hello_world" / "handler.log"
    log.parent.mkdir(parents=True)
    script = twister(
        tmp_path,
        f"open({str(log)!r}, 'w').write('E: Unable to find bootable image\\n')\n"
        "print('FAILED: Unknown Error')\nsys.exit(1)\n",
    )
    cmd = [sys.executable, str(script), "--outdir", "out"]
    res = await done(arb, await arb.run(s, tok, cmd, cwd=str(tmp_path)))
    assert res["boot_failed"] == "Unable to find bootable image"
    assert "SB_CONFIG_BOOTLOADER_MCUBOOT" in res["warning"]
    board = next(b for b in arb.list_boards() if b["id"] == "sim-1")
    assert board["note"].startswith(RUN_NOTE)
    # flashing an image that boots clears the note
    res = await done(arb, await arb.flash(s, tok, str(build_dir)))
    assert res["boot_confirmed"] is True
    assert "note" not in next(b for b in arb.list_boards() if b["id"] == "sim-1")


async def test_resume_reports_who_got_the_board(arb):
    s, _tok = await lease_for(arb)
    await arb.take("sim-1", "human:Fame", "check")
    res = await arb.resume("sim-1", "human:Fame")
    assert res["state"] == "LEASED" and res["holder"] and res["lease"]
    assert arb.sched.leases[arb.sched.boards["sim-1"].lease_token or ""].session_id == s


async def test_child_python_prints_utf8():
    res = await run_proc(
        [sys.executable, "-c", "import os; print(os.environ.get('PYTHONIOENCODING'))"]
    )
    assert res.tail == ["utf-8"]


class FakeClient:
    def __init__(self, **_kw: Any) -> None:
        self.session = "s-1"
        self.posts: list[str] = []

    def get(self, path: str, **_kw: Any) -> dict[str, Any]:
        return {"leases": [{"lease_token": "L-held"}]}

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        self.posts.append(path)
        if path == "/api/run":
            assert body["lease_token"] == "L-held"
        return {"status": "done", "tail": [], "exit_code": 0, "verdict": "passed"}


def test_run_with_board_keeps_a_lease_you_already_hold(monkeypatch, capsys):
    made: list[FakeClient] = []

    def client(**kw: Any) -> FakeClient:
        made.append(FakeClient(**kw))
        return made[-1]

    monkeypatch.setattr(cli, "Client", client)
    monkeypatch.delenv("ARBITER_LEASE", raising=False)
    args = argparse.Namespace(
        cmd=["--", "west", "twister"], board="nrf9161dk", lease=None, reason=None, timeout=60
    )
    assert cli.cmd_run(args) == 0
    assert made[0].posts == ["/api/run"]
