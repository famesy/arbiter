"""Persistence (SQLite, WAL) and the in-process event bus."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from collections import deque
from pathlib import Path
from typing import Any


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS audit (seq INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, "
            "kind TEXT, data TEXT)"
        )
        self.db.execute("CREATE TABLE IF NOT EXISTS ops (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        self.db.commit()

    def put(self, key: str, value: Any) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, json.dumps(value))
        )
        self.db.commit()

    def get(self, key: str, default: Any = None) -> Any:
        row = self.db.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def audit(self, kind: str, data: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT INTO audit (ts, kind, data) VALUES (?, ?, ?)",
            (time.time(), kind, json.dumps(data, default=str)),
        )
        self.db.commit()

    def recent_audit(self, limit: int = 200, board: str | None = None) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT seq, ts, kind, data FROM audit ORDER BY seq DESC LIMIT ?",
            (limit * 4 if board else limit,),
        ).fetchall()
        out = []
        for seq, ts, kind, data in rows:
            d = json.loads(data)
            if board and d.get("board") != board:
                continue
            out.append({"seq": seq, "ts": ts, "kind": kind, **d})
            if len(out) >= limit:
                break
        return out

    def save_op(self, op_id: str, data: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO ops (id, data) VALUES (?, ?)",
            (op_id, json.dumps(data, default=str)),
        )
        self.db.commit()

    def running_ops(self) -> list[dict[str, Any]]:
        out = []
        for (data,) in self.db.execute("SELECT data FROM ops").fetchall():
            d = json.loads(data)
            if d.get("ended") is None and d.get("pid"):
                out.append(d)
        return out

    def close(self) -> None:
        self.db.close()


class EventBus:
    """Fan-out of daemon events to WebSocket clients, with a short replay buffer."""

    def __init__(self, keep: int = 500):
        self.seq = 0
        self.recent: deque[dict[str, Any]] = deque(maxlen=keep)
        self._subs: set[asyncio.Queue[dict[str, Any]]] = set()

    def publish(self, kind: str, data: dict[str, Any]) -> dict[str, Any]:
        self.seq += 1
        ev = {"seq": self.seq, "ts": time.time(), "kind": kind, **data}
        self.recent.append(ev)
        for q in list(self._subs):
            if q.qsize() < 2000:
                q.put_nowait(ev)
        return ev

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subs.discard(q)

    def since(self, seq: int) -> list[dict[str, Any]]:
        return [e for e in self.recent if e["seq"] > seq]
