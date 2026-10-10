from __future__ import annotations

from pathlib import Path

import pytest
from arbiter.dfu import find_update_image, parse_image_list, verdict
from arbiter.errors import ArbiterError

from .test_service import done, lease_for

LIST = """\
Images:
 image=0 slot=0
    version: 1.1.0
    bootable: true
    flags: active
    hash: bbbb
 image=0 slot=1
    version: 1.0.0
    bootable: true
    flags: confirmed
    hash: aaaa
Split status: N/A (0)
"""


def signed(build_dir: Path) -> Path:
    f = build_dir / "zephyr" / "zephyr.signed.bin"
    f.write_bytes(b"\x3d\xb8\xf3\x96" + b"app" * 100)
    return f


def test_parse_image_list_and_verdict():
    slots = parse_image_list(LIST)
    assert [(s["slot"], s["version"], s["flags"]) for s in slots] == [
        (0, "1.1.0", ["active"]),
        (1, "1.0.0", ["confirmed"]),
    ]
    assert verdict(slots, "bbbb") == {
        "running_new_image": True,
        "confirmed": False,
        "active_version": "1.1.0",
    }
    assert verdict(slots, "cccc")["running_new_image"] is False


def test_find_update_image(build_dir):
    assert find_update_image(build_dir) is None
    f = signed(build_dir)
    assert find_update_image(build_dir) == f


async def test_dfu_uploads_tests_and_confirms(arb, build_dir):
    signed(build_dir)
    s, tok = await lease_for(arb)
    res = await done(arb, await arb.dfu(s, tok, str(build_dir)))
    assert res["ok"] is True, res
    assert res["boot_confirmed"] is True
    assert res["running_new_image"] and res["confirmed"]
    assert res["active_version"] == "1.1.0"
    assert [st["cmd"] for st in res["steps"]] == [
        "image upload",
        "image list",
        "image test",
        "reset",
        "image list",
        "image confirm",
        "image list",
    ]
    status = await arb.dfu_status(s, tok)
    assert [sl["flags"] for sl in status["slots"]] == [["active", "confirmed"], []]


async def test_unconfirmed_image_reverts_on_reset(arb, build_dir, tmp_path):
    signed(build_dir)
    s, tok = await lease_for(arb)
    res = await done(arb, await arb.dfu(s, tok, str(build_dir), confirm=False))
    assert res["ok"] and not res["confirmed"]
    assert "reverts" in res["note"]
    await arb.boards["sim-1"].driver.smp(["reset"], log_path=tmp_path / "smp.log")
    status = await arb.dfu_status(s, tok)
    assert status["slots"][0]["version"] == "1.0.0"


async def test_dfu_needs_a_signed_image(arb, build_dir):
    s, tok = await lease_for(arb)
    with pytest.raises(ArbiterError) as e:
        await arb.dfu(s, tok, str(build_dir))
    assert "MCUboot" in (e.value.hint or "")
