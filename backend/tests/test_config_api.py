"""The Settings page's config API: view, validate, write with comments kept, apply live."""

from __future__ import annotations

import tomllib
from pathlib import Path

import httpx
import pytest
from arbiter import config_edit as ce
from arbiter.errors import ArbiterError
from arbiter.service import Arbiter

from .conftest import make_config
from .test_api import hdr, server  # noqa: F401  (fixture)

SAMPLE = """\
# My bench
[daemon]
port = 7777               # the dashboard port
human_name = "Fame"
toolchain_env = 'C:\\ncs\\toolchains\\abc\\environment.json'

# ---- the DK on the left
[[board]]
id = "dk"
driver = "sim"
tags = ["lte"]

[[board.port]]
role = "app"
vcom = 0

[board.power]
kind = "sim"
mv_max = 4200   # the module's limit
default_mv = 3700

# ---- the simulator
[[board]]
id = "sim-2"
driver = "sim"
"""


def edit(sets: dict[str, object], text: str = SAMPLE) -> str:
    old = tomllib.loads(text)
    new = ce.apply_sets(old, sets)
    assert ce.validate(new) == []
    out = ce.render(text, old, new)
    assert tomllib.loads(out) == new
    return out


# ------------------------------------------------------------------ writing
def test_scalar_edit_keeps_comments_and_layout():
    out = edit({"boards.dk.power.mv_max": 4000, "daemon.port": 7788})
    assert "mv_max = 4000   # the module's limit" in out
    assert "port = 7788               # the dashboard port" in out
    assert out.replace("4000", "4200").replace("7788", "7777") == SAMPLE


def test_add_and_remove_keys():
    out = edit(
        {"boards.dk.power.ma_max": 80, "boards.dk.tags": None, "boards.sim-2.console": "uart"}
    )
    assert "ma_max = 80" in out and "tags" not in out
    assert out.index("ma_max = 80") < out.index("# ---- the simulator")
    assert 'console = "uart"' in out
    assert "# My bench" in out and "# the module's limit" in out


def test_boards_ports_and_new_tables():
    out = edit(
        {
            "boards.sim-2": None,
            "boards.new-1": {"driver": "sim", "power": {"kind": "sim", "ma_max": 50}},
            "boards.dk.ports": [
                {"role": "app", "vcom": 0},
                {"role": "aux", "name": "tfm", "vcom": 1},
            ],
            "boards.dk.commands.reset": "my-reset {serial}",
            "timing.lease_ttl_s": 1200,
        }
    )
    data = tomllib.loads(out)
    assert [b["id"] for b in data["board"]] == ["dk", "new-1"]
    assert data["board"][0]["port"][1]["name"] == "tfm"
    assert data["board"][0]["commands"] == {"reset": "my-reset {serial}"}
    assert data["timing"]["lease_ttl_s"] == 1200
    assert "# the module's limit" in out and "# ---- the DK on the left" in out


def test_inline_tables_are_edited_in_place():
    text = '[[board]]\nid = "dk"  # mine\npower = {kind = "sim", mv_max = 4200}\n'
    out = edit({"boards.dk.power.mv_max": 4000}, text)
    assert out == '[[board]]\nid = "dk"  # mine\npower = {kind = "sim", mv_max = 4000}\n'


def test_windows_paths_stay_readable():
    out = edit({"daemon.zephyr_base": "C:\\ncs\\v3.4.1\\zephyr"})
    assert "zephyr_base = 'C:\\ncs\\v3.4.1\\zephyr'" in out


# ------------------------------------------------------------------ validation
def test_validation_names_the_setting():
    raw = tomllib.loads(SAMPLE)
    bad = ce.apply_sets(
        raw,
        {
            "boards.dk.power.mv_max": 3000,
            "timing.lease_ttl_s": "long",
            "boards.dk.colour": "red",
            "boards.sim-2.driver": "nope",
        },
    )
    errors = {e["path"]: e["message"] for e in ce.validate(bad)}
    assert errors["boards.dk.power.mv_max"] == "must be ≥ default_mv (3700)"
    assert errors["timing.lease_ttl_s"].startswith("must be")
    assert errors["boards.dk.colour"] == "unknown setting"
    assert "unknown driver" in errors["boards.sim-2.driver"]


def test_bad_paths_are_reported():
    with pytest.raises(ce.ConfigError) as e:
        ce.apply_sets(tomllib.loads(SAMPLE), {"boards.ghost.tags": [], "boards.dk.id": "x"})
    assert {x["path"] for x in e.value.errors} == {"boards.ghost.tags", "boards.dk.id"}


def test_view_fills_defaults_and_hides_secrets():
    raw = tomllib.loads(SAMPLE)
    raw["board"][0]["options"] = {"api_token": "abc", "speed": 2}
    v = ce.view(raw)
    dk = v["boards"][0]
    assert dk["power"]["mv_min"] == 3000 and dk["ports"][0]["baud"] == 115200
    assert dk["options"] == {"api_token": "***", "speed": 2}
    assert v["timing"]["lease_ttl_s"] == 900 and "timing.*" in v["live"]


# ------------------------------------------------------------------ the daemon
@pytest.fixture
async def arb_file(tmp_path: Path):
    cfg = make_config(tmp_path)
    cfg.path = tmp_path / "config.toml"
    cfg.path.write_text(
        '# bench\n[[board]]\nid = "sim-1"\ndriver = "sim"\n'
        '[board.options]\nspeed = 50.0\n\n[board.power]\nkind = "sim"\n'
    )
    a = Arbiter(cfg)
    await a.start(persist=False)
    try:
        yield a
    finally:
        await a.stop()


async def test_update_applies_live_limits_and_keeps_a_backup(arb_file: Arbiter):
    v = arb_file.config_view()
    events = arb_file.bus.subscribe()
    res = await arb_file.update_config(
        v["version"],
        {"boards.sim-1.power.mv_max": 4000, "boards.sim-1.platform": "nrf52840dk/nrf52840"},
        "human:Fame",
    )
    assert res["applied"] == ["boards.sim-1.power.mv_max"]
    assert res["restart_needed"] == ["boards.sim-1.platform"]
    rt = arb_file.boards["sim-1"]
    assert rt.cfg.power.mv_max == 4000 and rt.power is not None and rt.power.cfg.mv_max == 4000
    assert rt.cfg.platform == "nrf9161dk/nrf9161/ns"  # needs a restart
    path = arb_file.config_path()
    assert path.read_text().startswith("# bench")
    assert path.with_name("config.toml.bak").read_text().startswith("# bench")
    assert arb_file.config_view()["restart_needed"] == ["boards.sim-1.platform"]
    kinds = []
    while not events.empty():
        kinds.append(events.get_nowait()["kind"])
    assert "config.changed" in kinds
    with pytest.raises(ArbiterError) as e:  # the old version is stale now
        await arb_file.update_config(v["version"], {"timing.grace_s": 10}, "human:Fame")
    assert e.value.code == "CONFIG_CHANGED" and e.value.http_status == 409


async def test_dry_run_and_invalid_edits_write_nothing(arb_file: Arbiter):
    before = arb_file.config_path().read_text()
    v = arb_file.config_view()["version"]
    res = await arb_file.update_config(v, {"timing.grace_s": 10}, "human:Fame", dry_run=True)
    assert res["dry_run"] and res["applied"] == ["timing.grace_s"]
    with pytest.raises(ArbiterError) as e:
        await arb_file.update_config(v, {"boards.sim-1.power.default_mv": 9000}, "human:Fame")
    assert e.value.http_status == 422
    assert e.value.extra["errors"][0]["path"] == "boards.sim-1.power.mv_max"
    assert arb_file.config_path().read_text() == before
    assert arb_file.sched.t.grace_s == 30


async def test_live_timing_and_tags(arb_file: Arbiter):
    v = arb_file.config_view()["version"]
    await arb_file.update_config(
        v, {"timing.lease_ttl_s": 60, "boards.sim-1.tags": ["lte", "bench"]}, "human:Fame"
    )
    assert arb_file.sched.t.lease_ttl_s == 60
    assert arb_file.sched.boards["sim-1"].tags == ["lte", "bench"]


# ------------------------------------------------------------------ HTTP
async def test_config_routes_are_admin_only(server):  # noqa: F811
    async with httpx.AsyncClient(base_url=server["base"]) as c:
        for method, path in (
            ("GET", "/api/admin/config"),
            ("POST", "/api/admin/config"),
            ("GET", "/api/admin/doctor"),
        ):
            r = await c.request(method, path, headers=hdr(server["agent"]), json={})
            assert r.status_code == 403
        r = await c.get("/api/admin/config", headers=hdr(server["admin"]))
        assert r.status_code == 200
        version = r.json()["version"]
        assert r.json()["boards"][0]["id"] == "sim-1"
        r = await c.post(
            "/api/admin/config",
            headers=hdr(server["admin"]),
            json={"version": version, "set": {"boards.sim-1.power.mv_max": 1000}},
        )
        assert r.status_code == 422 and r.json()["errors"][0]["path"].endswith("mv_max")
        r = await c.post(
            "/api/admin/config",
            headers=hdr(server["admin"]),
            json={"version": "sha256:old", "set": {"timing.grace_s": 10}},
        )
        assert r.status_code == 409 and r.json()["version"] == version
        r = await c.get("/api/admin/doctor", headers=hdr(server["admin"]))
        assert r.status_code == 200
        assert any(ch["board"] == "sim-1" for ch in r.json()["checks"])
        r = await c.get("/api/plugins", headers=hdr(server["agent"]))
        loaded = {(p["kind"], p["name"]): p for p in r.json()["loaded"]}
        assert loaded[("driver", "sim")]["used_by"] == ["sim-1"]
        assert loaded[("power", "ppk2")]["source"] == "builtin"
