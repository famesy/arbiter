from __future__ import annotations

from pathlib import Path

from arbiter.config import load_config


def test_example_config_loads():
    cfg = load_config(Path(__file__).resolve().parents[1] / "examples" / "arbiter.toml")
    boards = {b.id: b for b in cfg.boards}
    assert set(boards) == {"nrf9161dk-1", "native-1", "sim-1"}
    assert [p.vcom for p in boards["nrf9161dk-1"].ports] == [0, 1]
    assert boards["sim-1"].power.kind == "sim"
