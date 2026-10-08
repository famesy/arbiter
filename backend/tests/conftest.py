from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from arbiter.config import BoardConfig, Config, PowerConfig
from arbiter.scheduler import Timing
from arbiter.service import Arbiter


class FakeClock:
    def __init__(self, t: float = 1_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


def sim_board(board_id: str = "sim-1", **kw) -> BoardConfig:
    opts = {"speed": 50.0, **kw.pop("options", {})}
    power = kw.pop("power", PowerConfig(kind="sim"))
    return BoardConfig(
        id=board_id,
        driver="sim",
        platform=kw.pop("platform", "nrf9161dk/nrf9161/ns"),
        options=opts,
        power=power,
        **kw,
    )


def make_config(tmp_path: Path, boards: list[BoardConfig] | None = None) -> Config:
    cfg = Config(state=tmp_path / "state", human_name="Fame")
    cfg.boards = boards if boards is not None else [sim_board()]
    cfg.timing = Timing()
    return cfg


@pytest.fixture
def build_dir(tmp_path: Path) -> Path:
    d = tmp_path / "fw-sensor" / "build"
    (d / "zephyr").mkdir(parents=True)
    (d / "zephyr" / ".config").write_text('CONFIG_BOARD="nrf9161dk"\nCONFIG_UART_CONSOLE=y\n')
    return d


@pytest.fixture
async def arb(tmp_path: Path):
    a = Arbiter(make_config(tmp_path))
    await a.start()
    await asyncio.sleep(0.05)  # let the simulated board finish its first boot
    try:
        yield a
    finally:
        await a.stop()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()
