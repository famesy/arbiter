"""`arbiter tui`: the board console in a terminal. Needs the `tui` extra (Textual)."""

from __future__ import annotations


def run(board: str | None = None, channel: str = "all") -> int:
    from .app import ArbiterTui

    return ArbiterTui(board, channel).run() or 0
