from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from arbiter.errors import ArbiterError
from arbiter.nrf91 import check_at, convert_trace, response, summarize
from arbiter.service import Arbiter

from .test_service import done, lease_for


async def _ready(arb: Arbiter, build_dir: Path) -> tuple[str, str]:
    s, tok = await lease_for(arb)
    await done(arb, await arb.flash(s, tok, str(build_dir)))
    await arb.expect(s, tok, r"uart:~\$ ", 5)
    return s, tok


async def test_at_goes_through_the_at_shell_command(arb, build_dir):
    s, tok = await _ready(arb, build_dir)
    res = await arb.at(s, tok, "AT+CFUN?")
    assert res["ok"] is True, res
    assert res["lines"] == ["+CFUN: 1"]
    assert res["via"] == "at shell command"
    res = await arb.at(s, tok, "AT+NOPE")
    assert res["ok"] is False and res["final"] == "ERROR"


async def test_at_refuses_a_factory_reset_and_non_at_text(arb, build_dir):
    s, tok = await _ready(arb, build_dir)
    with pytest.raises(ArbiterError) as e:
        await arb.at(s, tok, "AT%XFACTORYRESET=0")
    assert e.value.code == "NOT_ALLOWED"
    with pytest.raises(ArbiterError) as e:
        await arb.at(s, tok, "kernel reboot")
    assert e.value.code == "BAD_REQUEST"


async def test_lte_status_summarises_the_modem(arb, build_dir):
    s, tok = await _ready(arb, build_dir)
    res = await arb.lte_status(s, tok)
    assert res["registration"]["meaning"] == "registered, home network"
    assert res["functional_mode"]["value"] == 1
    cell = res["cell"]
    assert cell["act"] == "LTE-M" and cell["band"] == 20
    assert cell["rsrp_dbm"] == -88 and cell["snr_db"] == -4
    assert res["system_mode"] == ["LTE-M", "GNSS"]
    assert res["pdn"][0]["apn"] == "iot.example"
    assert res["modem_firmware"] == "mfw_nrf91x1_2.0.2"
    assert "hints" not in res and "failed_commands" not in res


async def test_modem_trace_captures_bytes_to_a_file(arb, build_dir, monkeypatch):
    monkeypatch.setattr("arbiter.nrf91.shutil.which", lambda _name: None)
    s, tok = await _ready(arb, build_dir)
    res = await arb.modem_trace(s, tok, "start")
    assert res["status"] == "capturing"
    assert (await arb.modem_trace(s, tok, "start"))["status"] == "already_running"
    await asyncio.sleep(0.3)
    res = await arb.modem_trace(s, tok, "stop")
    assert res["status"] == "stopped" and res["bytes"] > 0
    assert await asyncio.to_thread(lambda: Path(res["raw"]).stat().st_size) == res["bytes"]
    assert res["converted"] is False and "nrfutil" in res["hint"]
    assert (await arb.modem_trace(s, tok, "status"))["status"] == "not_running"


def test_summary_hints_when_searching_with_a_weak_signal():
    def ok(*lines: str) -> dict[str, Any]:
        return {"ok": True, "final": "OK", "lines": list(lines)}

    res = summarize(
        {
            "AT+CFUN?": ok("+CFUN: 1"),
            "AT+CEREG?": ok("+CEREG: 0,2"),
            "AT%XMONITOR": ok("%XMONITOR: 2,,,,,9,08,,,,20,10"),
            "AT%XICCID": {"ok": False, "final": "ERROR", "lines": []},
        }
    )
    assert res["registration"]["value"] == 2
    assert res["cell"]["act"] == "NB-IoT" and res["cell"]["band"] == 8
    assert res["cell"]["rsrp_dbm"] == -120
    assert any("Searching" in h for h in res["hints"])
    assert any("Weak signal" in h for h in res["hints"])
    assert res["failed_commands"] == ["AT%XICCID"]


def test_response_and_check_at():
    assert response(["", "+CEREG: 0,1", "OK", "junk"]) == {
        "ok": True,
        "final": "OK",
        "lines": ["+CEREG: 0,1"],
    }
    assert response(["+CME ERROR: 513"])["final"] == "+CME ERROR: 513"
    assert check_at("  at+cfun? ") == "at+cfun?"
    with pytest.raises(PermissionError):
        check_at("AT%CMNG=3,16842753,0")


def test_convert_trace_without_nrfutil(tmp_path, monkeypatch):
    monkeypatch.setattr("arbiter.nrf91.shutil.which", lambda _name: None)
    raw = tmp_path / "t.bin"
    raw.write_bytes(b"\x00")
    assert convert_trace(raw)["converted"] is False
