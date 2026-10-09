"""Current baselines and power assertions.

A measurement can be saved under a name ("idle", "lte_psm", "adv_1s") per board, with
how it was taken and which build was running. Later measurements compare against it,
so a change that doubles the sleep current fails like a test instead of going unnoticed.
Plain limits (max average, max peak, max charge) work without a baseline."""

from __future__ import annotations

import time
from typing import Any

from .store import Store

KEY = "power_baselines"
METRICS = ("avg_ua", "peak_ua", "charge_uc")


class Baselines:
    def __init__(self, store: Store | None):
        self.store = store
        loaded = store.get(KEY) if store else None
        self.data: dict[str, dict[str, dict[str, Any]]] = loaded if isinstance(loaded, dict) else {}

    def save(self, board: str, name: str, m: dict[str, Any], how: dict[str, Any]) -> dict[str, Any]:
        entry = {
            **{k: m[k] for k in (*METRICS, "duration_ms", "samples") if k in m},
            **how,
            "at": time.time(),
        }
        self.data.setdefault(board, {})[name] = entry
        if self.store:
            self.store.put(KEY, self.data)
        return entry

    def get(self, board: str, name: str) -> dict[str, Any] | None:
        return self.data.get(board, {}).get(name)

    def list(self, board: str | None = None) -> dict[str, dict[str, Any]]:
        if board:
            return {board: self.data.get(board, {})}
        return self.data


def check_limits(m: dict[str, Any], limits: dict[str, float | None]) -> list[dict[str, Any]]:
    """One check per limit given: {"max_avg_ua": 10} -> avg_ua <= 10."""
    checks = []
    for key, limit in limits.items():
        if limit is None:
            continue
        metric = key.removeprefix("max_")
        value = m.get(metric)
        checks.append(
            {
                "check": f"{metric} <= {limit:g}",
                "value": value,
                "ok": value is not None and value <= limit,
            }
        )
    return checks


def compare(
    m: dict[str, Any], base: dict[str, Any], tolerance_pct: float, how: dict[str, Any]
) -> dict[str, Any]:
    """Each metric against the baseline. Higher by more than tolerance_pct fails; lower is
    reported but passes (a regression is what matters)."""
    out: dict[str, Any] = {"metrics": {}, "ok": True}
    for metric in METRICS:
        then, now = base.get(metric), m.get(metric)
        if then is None or now is None:
            continue
        delta = round(100 * (now - then) / then, 1) if then else None
        ok = delta is None or delta <= tolerance_pct
        out["metrics"][metric] = {"baseline": then, "now": now, "delta_pct": delta, "ok": ok}
        # Peaks are noisy: a radio burst lands or not. Only average and charge decide.
        if not ok and metric != "peak_ua":
            out["ok"] = False
    differs = [k for k in ("duration_ms", "trigger", "power_cycle") if base.get(k) != how.get(k)]
    if differs:
        out["warning"] = (
            "Measured differently from the baseline (" + ", ".join(differs) + "): the "
            "comparison may not mean much."
        )
    if base.get("elf_sha") and how.get("elf_sha") and base["elf_sha"] != how["elf_sha"]:
        out["build_changed"] = True
    return out
