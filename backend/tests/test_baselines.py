from __future__ import annotations

import pytest
from arbiter.baselines import check_limits, compare
from arbiter.errors import ArbiterError

from .test_service import done, lease_for


def test_check_limits():
    checks = check_limits({"avg_ua": 5.0, "peak_ua": 900.0}, {"max_avg_ua": 10, "max_peak_ua": 500})
    assert [(c["check"], c["ok"]) for c in checks] == [
        ("avg_ua <= 10", True),
        ("peak_ua <= 500", False),
    ]


def test_compare_fails_on_a_rise_in_average_not_peak():
    base = {"avg_ua": 10.0, "peak_ua": 100.0, "charge_uc": 50.0, "duration_ms": 1000}
    how = {"duration_ms": 1000}
    res = compare({"avg_ua": 10.5, "peak_ua": 300.0, "charge_uc": 52.0}, base, 10, how)
    assert res["ok"] is True and res["metrics"]["peak_ua"]["ok"] is False
    res = compare({"avg_ua": 15.0, "peak_ua": 100.0, "charge_uc": 75.0}, base, 10, how)
    assert res["ok"] is False and res["metrics"]["avg_ua"]["delta_pct"] == 50.0
    res = compare({"avg_ua": 10.0}, base, 10, {"duration_ms": 2000})
    assert "duration_ms" in res["warning"]


async def test_save_and_compare_a_baseline(arb):
    s, tok = await lease_for(arb)
    res = await done(arb, await arb.measure_current(s, tok, 100, save_baseline="idle"))
    assert res["baseline_saved"] == "idle" and "passed" not in res
    saved = arb.power_baselines("sim-1")["baselines"]["sim-1"]["idle"]
    assert saved["avg_ua"] == res["avg_ua"] and saved["duration_ms"] == 100

    res = await done(arb, await arb.measure_current(s, tok, 100, baseline="idle"))
    assert res["passed"] is True and res["baseline"]["ok"] is True

    saved["avg_ua"] = saved["charge_uc"] = 1.0  # pretend the old build slept far better
    res = await done(arb, await arb.measure_current(s, tok, 100, baseline="idle", max_avg_ua=1e6))
    assert res["passed"] is False and res["baseline"]["ok"] is False
    assert res["checks"][0]["ok"] is True

    res = await done(arb, await arb.measure_current(s, tok, 100, max_avg_ua=0.1))
    assert res["passed"] is False

    with pytest.raises(ArbiterError) as e:
        await arb.measure_current(s, tok, 100, baseline="nope")
    assert "idle" in (e.value.hint or "")
