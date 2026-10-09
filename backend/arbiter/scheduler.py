"""Queue, leases, priority and human preemption (design doc §5).

The scheduler is pure bookkeeping: it never touches hardware. The service layer
(`arbiter.service`) listens to its events to stop operations, reset boards and
so on. Everything here runs on the daemon's event loop, so no locking is needed.
"""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from .errors import ArbiterError

PRIORITIES = {"low": 0, "normal": 50, "high": 80, "urgent": 100}
AGENT_MAX_PRIORITY = PRIORITIES["normal"]

# Board states
AVAILABLE = "AVAILABLE"
LEASED = "LEASED"
PAUSED = "PAUSED"
HUMAN = "HUMAN"
MAINTENANCE = "MAINTENANCE"
OFFLINE = "OFFLINE"
NEEDS_RECOVER = "NEEDS_RECOVER"

# Lease states
ACTIVE = "ACTIVE"
PAUSING = "PAUSING"
L_PAUSED = "PAUSED"
EXPIRING = "EXPIRING"
RELEASED = "RELEASED"
REVOKED = "REVOKED"
EXPIRED = "EXPIRED"
LIVE_LEASE_STATES = {ACTIVE, PAUSING, L_PAUSED, EXPIRING}


@dataclass
class Timing:
    lease_ttl_s: float = 15 * 60
    max_hold_s: float = 60 * 60
    heartbeat_timeout_s: float = 25
    grace_s: float = 30
    ticket_ttl_s: float = 90
    claim_timeout_s: float = 120
    max_wait_s: float = 45
    # A session holding nothing is dropped after this long without hearing from it.
    idle_session_s: float = 60 * 60
    # Using a free board (typing, reset, flash, power) holds it for the human until they
    # have been idle this long; agents asking meanwhile wait in the queue.
    human_idle_s: float = 120


@dataclass
class Selector:
    board_id: str | None = None
    platform: str | None = None
    tags: list[str] = field(default_factory=list)

    @classmethod
    def parse(cls, obj: Any, known_ids: set[str]) -> Selector:
        if isinstance(obj, Selector):
            return obj
        if obj is None or (isinstance(obj, str) and obj in {"", "any"}):
            return cls()
        if isinstance(obj, str):
            if obj in known_ids:
                return cls(board_id=obj)
            return cls(platform=obj)
        if isinstance(obj, dict):
            tags: list[str] = []
            for key in ("tags", "fixtures"):  # fixtures are tags too (see BoardConfig)
                value = obj.get(key) or []
                tags += [t for t in value.split(",") if t] if isinstance(value, str) else value
            return cls(
                board_id=obj.get("board_id") or obj.get("board"),
                platform=obj.get("platform"),
                tags=list(tags),
            )
        raise ArbiterError("BAD_REQUEST", f"cannot parse selector {obj!r}")

    def matches(self, board: BoardSlot) -> bool:
        if self.board_id and board.id != self.board_id:
            return False
        if self.platform and not (
            board.platform == self.platform or board.platform.split("/")[0] == self.platform
        ):
            return False
        return all(t in board.tags for t in self.tags)

    def describe(self) -> str:
        if self.board_id:
            return self.board_id
        parts = [self.platform or "any board"] + [f"#{t}" for t in self.tags]
        return " ".join(parts)


@dataclass
class Session:
    id: str
    agent_kind: str = "cli"  # claude | codex | human | cli
    label: str = ""
    external_id: str | None = None
    repo: str | None = None
    branch: str | None = None
    head: str | None = None
    cwd: str | None = None
    pid: int | None = None
    heartbeat: bool = False  # True when a shim keeps a heartbeat going
    created_at: float = 0.0
    last_heartbeat: float = 0.0
    alive: bool = True
    ended: bool = False
    inbox: list[dict[str, Any]] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("inbox")
        d["inbox_pending"] = len(self.inbox)
        return d


@dataclass
class QueueEntry:
    ticket: str
    session_id: str
    selector: Selector
    priority: int
    seq: float
    enqueued_at: float
    reason: str = ""
    last_poll: float = 0.0
    pinned: bool = False
    state: str = "queued"  # queued | granted | cancelled | expired
    lease_token: str | None = None


@dataclass
class Lease:
    token: str
    id: str
    board_id: str
    session_id: str
    ticket: str
    reason: str
    state: str
    granted_at: float
    ttl_s: float
    expires_at: float
    claimed: bool = False
    paused_by: str | None = None
    pause_reason: str | None = None
    grace_until: float | None = None
    op: str | None = None
    ended_at: float | None = None
    end_reason: str | None = None
    history: list[list[Any]] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("token")
        return d


@dataclass
class BoardSlot:
    id: str
    platform: str
    tags: list[str] = field(default_factory=list)
    state: str = AVAILABLE
    present: bool = True
    lease_token: str | None = None
    held_by: str | None = None
    note: str | None = None
    human_auto: bool = False  # HUMAN because they used it, not `take`: ends when idle
    human_seen: float = 0.0


Listener = Callable[[str, dict[str, Any]], None]


class Scheduler:
    def __init__(self, timing: Timing | None = None, clock: Callable[[], float] = time.time):
        self.t = timing or Timing()
        self.clock = clock
        self.boards: dict[str, BoardSlot] = {}
        self.sessions: dict[str, Session] = {}
        self.queue: list[QueueEntry] = []  # live (queued) entries only
        self.tickets: dict[str, QueueEntry] = {}
        self.leases: dict[str, Lease] = {}
        self.listeners: list[Listener] = []
        self._seq = 0.0
        self._changed = asyncio.Event()

    # ----------------------------------------------------------------- plumbing
    def emit(self, kind: str, **data: Any) -> None:
        for fn in list(self.listeners):
            fn(kind, data)
        self._changed.set()
        self._changed = asyncio.Event()

    def notify(self, session_id: str, kind: str, text: str, **data: Any) -> None:
        """Put a note in a session's inbox."""
        self._notify(session_id, kind, text, **data)

    def _notify(self, session_id: str, kind: str, text: str, **data: Any) -> None:
        s = self.sessions.get(session_id)
        if not s:
            return
        s.inbox.append({"ts": self.clock(), "kind": kind, "text": text, **data})
        del s.inbox[:-50]

    def _next_seq(self) -> float:
        self._seq += 1.0
        return self._seq

    def _hist(self, lease: Lease, event: str, detail: str = "") -> None:
        lease.history.append([self.clock(), event, detail])
        del lease.history[:-100]

    # ------------------------------------------------------------------- boards
    def add_board(self, board_id: str, platform: str, tags: list[str] | None = None) -> BoardSlot:
        slot = self.boards.get(board_id)
        if slot is None:
            slot = BoardSlot(board_id, platform, list(tags or []))
            self.boards[board_id] = slot
        else:
            slot.platform, slot.tags = platform, list(tags or [])
        return slot

    def board(self, board_id: str) -> BoardSlot:
        try:
            return self.boards[board_id]
        except KeyError:
            raise ArbiterError("BOARD_UNKNOWN", f"no board {board_id!r}") from None

    def board_status(self, b: BoardSlot) -> str:
        if not b.present and b.state == AVAILABLE:
            return OFFLINE
        return b.state

    def set_present(self, board_id: str, present: bool) -> None:
        b = self.board(board_id)
        if b.present != present:
            b.present = present
            self.emit("board.presence", board=board_id, present=present)
            if present:
                self.dispatch()

    def set_maintenance(self, board_id: str, on: bool, by: str = "human") -> None:
        b = self.board(board_id)
        if on:
            if b.lease_token:
                self.revoke(board_id, by=by, reason="board put into maintenance", requeue=True)
            b.state, b.held_by = MAINTENANCE, None
        elif b.state == MAINTENANCE:
            b.state = AVAILABLE
        self.emit("board.state", board=board_id, state=b.state)
        self.dispatch()

    def mark_needs_recover(self, board_id: str, note: str) -> None:
        b = self.board(board_id)
        if b.lease_token is None and b.state in (AVAILABLE, HUMAN):
            b.state = NEEDS_RECOVER
        b.note = note
        self.emit("board.state", board=board_id, state=b.state, note=note)

    def set_note(self, board_id: str, note: str | None) -> None:
        """A note shown with the board (dashboard, status, the next holder), state unchanged."""
        b = self.board(board_id)
        if b.note != note:
            b.note = note
            self.emit("board.state", board=board_id, state=b.state, note=note)

    def clear_needs_recover(self, board_id: str) -> None:
        b = self.board(board_id)
        b.note = None
        if b.state == NEEDS_RECOVER:
            b.state = AVAILABLE
        self.emit("board.state", board=board_id, state=b.state)
        self.dispatch()

    # ----------------------------------------------------------------- sessions
    def register_session(
        self,
        agent_kind: str = "cli",
        label: str = "",
        external_id: str | None = None,
        heartbeat: bool = False,
        **info: Any,
    ) -> Session:
        now = self.clock()
        if external_id:
            for s in self.sessions.values():
                if s.external_id == external_id and not s.ended:
                    s.last_heartbeat, s.alive = now, True
                    s.heartbeat = s.heartbeat or heartbeat
                    for k, v in info.items():
                        if v is not None and hasattr(s, k):
                            setattr(s, k, v)
                    if label:
                        s.label = label
                    self._revive(s)
                    return s
        sid = "s-" + secrets.token_hex(4)
        s = Session(
            id=sid,
            agent_kind=agent_kind,
            label=label or f"{agent_kind}-{sid[2:6]}",
            external_id=external_id,
            heartbeat=heartbeat,
            created_at=now,
            last_heartbeat=now,
            **{k: v for k, v in info.items() if k in Session.__dataclass_fields__},
        )
        self.sessions[sid] = s
        self.emit("session.registered", session=s.public())
        return s

    def session(self, session_id: str) -> Session:
        try:
            return self.sessions[session_id]
        except KeyError:
            raise ArbiterError("SESSION_UNKNOWN", f"no session {session_id!r}") from None

    def session_by_external(self, external_id: str) -> Session | None:
        for s in self.sessions.values():
            if s.external_id == external_id and not s.ended:
                return s
        return None

    def heartbeat(self, session_id: str) -> Session:
        s = self.session(session_id)
        s.last_heartbeat = self.clock()
        s.heartbeat = True
        s.ended = False  # dropped as stale while asleep, and now back
        if not s.alive:
            s.alive = True
            self._revive(s)
        return s

    def _revive(self, s: Session) -> None:
        for lease in self.leases_of(s.id):
            if lease.state == EXPIRING:
                lease.state, lease.grace_until = ACTIVE, None
                self.boards[lease.board_id].state = LEASED
                self._hist(lease, "revived")
                self.emit("lease.state", lease=lease.public())

    def end_session(self, session_id: str, release: bool = True) -> None:
        s = self.session(session_id)
        for e in list(self.queue):
            if e.session_id == session_id:
                self._drop_entry(e, "cancelled")
        for lease in self.leases_of(session_id):
            if release:
                self._end_lease(lease, RELEASED, "session ended")
            elif lease.state == ACTIVE:
                self._start_grace(lease)
        s.ended, s.alive = True, False
        self.emit("session.ended", session=session_id)
        self.dispatch()

    def pop_inbox(self, session_id: str) -> list[dict[str, Any]]:
        s = self.session(session_id)
        items, s.inbox = s.inbox, []
        return items

    def leases_of(self, session_id: str) -> list[Lease]:
        return [
            le
            for le in self.leases.values()
            if le.session_id == session_id and le.state in LIVE_LEASE_STATES
        ]

    # -------------------------------------------------------------- acquiring
    def acquire(
        self,
        session_id: str,
        selector: Any,
        reason: str = "",
        priority: int | str | None = None,
        human: bool = False,
    ) -> QueueEntry:
        s = self.session(session_id)
        sel = Selector.parse(selector, set(self.boards))
        if sel.board_id and sel.board_id not in self.boards:
            raise ArbiterError("BOARD_UNKNOWN", f"no board {sel.board_id!r}")
        if not any(sel.matches(b) for b in self.boards.values()):
            raise ArbiterError("BOARD_UNKNOWN", f"no board matches {sel.describe()!r}")
        # Idempotent: an existing live lease or queued ticket for the same selector is reused.
        for lease in self.leases_of(s.id):
            if sel.matches(self.boards[lease.board_id]):
                return self.tickets[lease.ticket]
        for e in self.queue:
            if e.session_id == s.id and e.selector == sel:
                e.last_poll = self.clock()
                if reason:
                    e.reason = reason
                return e
        prio = self._priority(priority, human or s.agent_kind == "human")
        now = self.clock()
        e = QueueEntry(
            ticket="t-" + secrets.token_hex(4),
            session_id=s.id,
            selector=sel,
            priority=prio,
            seq=self._next_seq(),
            enqueued_at=now,
            reason=reason,
            last_poll=now,
        )
        self.tickets[e.ticket] = e
        self.queue.append(e)
        self._sort()
        self.emit("queue.changed", reason="enqueued", ticket=e.ticket)
        self.dispatch()
        return e

    def _priority(self, p: int | str | None, human: bool) -> int:
        if p is None:
            val = PRIORITIES["normal"]
        elif isinstance(p, str):
            if p not in PRIORITIES:
                raise ArbiterError("BAD_REQUEST", f"priority must be one of {list(PRIORITIES)}")
            val = PRIORITIES[p]
        else:
            val = int(p)
        return val if human else min(val, AGENT_MAX_PRIORITY)

    def _sort(self) -> None:
        self.queue.sort(key=lambda e: (not e.pinned, -e.priority, e.seq))

    def dispatch(self) -> list[Lease]:
        granted = []
        for e in list(self.queue):
            for b in self.boards.values():
                if (
                    b.state == AVAILABLE
                    and b.present
                    and b.lease_token is None
                    and e.selector.matches(b)
                ):
                    granted.append(self._grant(e, b))
                    break
        return granted

    def _grant(self, e: QueueEntry, b: BoardSlot) -> Lease:
        now = self.clock()
        token = "lease-" + secrets.token_urlsafe(18)
        lease = Lease(
            token=token,
            id="l-" + secrets.token_hex(3),
            board_id=b.id,
            session_id=e.session_id,
            ticket=e.ticket,
            reason=e.reason,
            state=ACTIVE,
            granted_at=now,
            ttl_s=self.t.lease_ttl_s,
            expires_at=now + self.t.lease_ttl_s,
        )
        self._hist(lease, "granted", e.reason)
        self.leases[token] = lease
        self.queue.remove(e)
        e.state, e.lease_token = "granted", token
        b.state, b.lease_token, b.held_by = LEASED, token, None
        self._notify(
            e.session_id,
            "granted",
            f"Board {b.id} is yours (ticket {e.ticket}).",
            board=b.id,
            ticket=e.ticket,
        )
        self.emit("lease.granted", lease=lease.public(), board=b.id)
        self.emit("queue.changed", reason="granted", ticket=e.ticket)
        return lease

    def ticket_status(
        self, ticket: str, session_id: str | None = None, poll: bool = True
    ) -> dict[str, Any]:
        e = self.tickets.get(ticket)
        if e is None:
            raise ArbiterError("TICKET_UNKNOWN", f"no ticket {ticket!r}")
        if session_id and e.session_id != session_id:
            raise ArbiterError("TICKET_UNKNOWN", "ticket belongs to another session")
        if poll:
            e.last_poll = self.clock()
        if e.state == "queued":
            return self._queued_view(e)
        if e.state in ("cancelled", "expired"):
            raise ArbiterError(
                "TICKET_EXPIRED" if e.state == "expired" else "TICKET_UNKNOWN",
                f"ticket {ticket} was {e.state}",
            )
        lease = self.leases[e.lease_token]  # type: ignore[index]
        if lease.state in (ACTIVE, EXPIRING):
            if poll:
                lease.claimed = True
            return self._granted_view(lease)
        if lease.state in (PAUSING, L_PAUSED):
            return {
                "status": "paused",
                "ticket": ticket,
                "board": lease.board_id,
                "paused_by": lease.paused_by,
                "reason": lease.pause_reason,
                "hint": "Your board is paused by a human. Keep working on code; call wait_for_board again.",
            }
        raise self._lease_error(lease)

    def _granted_view(self, lease: Lease) -> dict[str, Any]:
        return {
            "status": "granted",
            "lease_token": lease.token,
            "lease_id": lease.id,
            "ticket": lease.ticket,
            "board": lease.board_id,
            "expires_at": lease.expires_at,
            "expires_in_s": round(lease.expires_at - self.clock()),
        }

    def _queued_view(self, e: QueueEntry) -> dict[str, Any]:
        boards = {b.id for b in self.boards.values() if e.selector.matches(b)}
        ahead = []
        for other in self.queue:
            if other is e:
                break
            if boards & {b.id for b in self.boards.values() if other.selector.matches(b)}:
                s = self.sessions.get(other.session_id)
                ahead.append(
                    {
                        "who": s.label if s else other.session_id,
                        "reason": other.reason,
                        "priority": other.priority,
                    }
                )
        holders = []
        for bid in sorted(boards):
            b = self.boards[bid]
            h: dict[str, Any] = {"board": bid, "state": self.board_status(b)}
            if b.lease_token:
                le = self.leases[b.lease_token]
                s = self.sessions.get(le.session_id)
                h.update(holder=s.label if s else le.session_id, reason=le.reason)
            elif b.state == HUMAN:
                h["holder"] = b.held_by or "human"
                if b.human_auto:
                    idle = max(0.0, self.t.human_idle_s - (self.clock() - b.human_seen))
                    h["free_in_s"] = round(idle)
            holders.append(h)
        return {
            "status": "queued",
            "ticket": e.ticket,
            "position": len(ahead) + 1,
            "ahead": ahead,
            "boards": holders,
            "hint": "You keep your place. Call wait_for_board(ticket) or keep coding and check back.",
        }

    async def wait(
        self, ticket: str, wait_s: float, session_id: str | None = None
    ) -> dict[str, Any]:
        wait_s = max(0.0, min(float(wait_s), self.t.max_wait_s))
        deadline = asyncio.get_running_loop().time() + wait_s
        while True:
            ev = self._changed
            st = self.ticket_status(ticket, session_id)
            remaining = deadline - asyncio.get_running_loop().time()
            if st["status"] == "granted" or remaining <= 0:
                return st
            try:
                await asyncio.wait_for(ev.wait(), remaining)
            except TimeoutError:
                return self.ticket_status(ticket, session_id)

    def cancel(self, ticket: str, session_id: str | None = None) -> None:
        e = self.tickets.get(ticket)
        if e is None:
            raise ArbiterError("TICKET_UNKNOWN", f"no ticket {ticket!r}")
        if session_id and e.session_id != session_id:
            raise ArbiterError("TICKET_UNKNOWN", "ticket belongs to another session")
        if e.state == "queued":
            self._drop_entry(e, "cancelled")
        elif e.state == "granted" and e.lease_token in self.leases:
            lease = self.leases[e.lease_token]
            if lease.state in LIVE_LEASE_STATES:
                self._end_lease(lease, RELEASED, "ticket cancelled")
        self.dispatch()

    def _drop_entry(self, e: QueueEntry, state: str) -> None:
        if e in self.queue:
            self.queue.remove(e)
        e.state = state
        self.emit("queue.changed", reason=state, ticket=e.ticket)

    # ------------------------------------------------------------------ leases
    def lease(self, token: str) -> Lease:
        try:
            return self.leases[token]
        except KeyError:
            raise ArbiterError("LEASE_UNKNOWN", "unknown lease token") from None

    def lease_by_id(self, lease_id: str) -> Lease:
        for le in self.leases.values():
            if le.id == lease_id:
                return le
        raise ArbiterError("LEASE_UNKNOWN", f"no lease {lease_id!r}")

    def _lease_error(self, lease: Lease) -> ArbiterError:
        if lease.state in (PAUSING, L_PAUSED):
            return ArbiterError(
                "LEASE_PAUSED",
                f"board {lease.board_id} is paused",
                by=lease.paused_by,
                reason=lease.pause_reason,
                ticket=lease.ticket,
            )
        if lease.state == EXPIRED:
            return ArbiterError(
                "LEASE_EXPIRED", f"lease on {lease.board_id} expired", reason=lease.end_reason
            )
        if lease.state == RELEASED:
            return ArbiterError(
                "LEASE_REVOKED",
                f"lease on {lease.board_id} was released",
                reason=lease.end_reason,
                hint="This lease is already released. Call acquire_board if you need the board again.",
            )
        e = self.tickets.get(lease.ticket)
        requeued = e is not None and e.state == "queued"
        return ArbiterError(
            "LEASE_REVOKED",
            f"lease on {lease.board_id} was revoked",
            reason=lease.end_reason,
            ticket=lease.ticket if requeued else None,
        )

    def check(self, token: str, session_id: str | None = None, touch: bool = True) -> Lease:
        """Validate a lease for a hardware operation; raise a structured error otherwise."""
        lease = self.lease(token)
        if session_id and lease.session_id != session_id:
            s = self.sessions.get(session_id)
            # A restarted shim may present an old token from the same external session.
            owner = self.sessions.get(lease.session_id)
            if not (s and owner and s.external_id and s.external_id == owner.external_id):
                raise ArbiterError("LEASE_UNKNOWN", "lease belongs to another session")
        if lease.state == EXPIRING:
            self.reclaim(token, session_id)
        if lease.state != ACTIVE:
            raise self._lease_error(lease)
        lease.claimed = True
        if touch:
            self.touch(lease)
        return lease

    def touch(self, lease: Lease) -> None:
        now = self.clock()
        cap = lease.granted_at + self.t.max_hold_s
        lease.expires_at = max(lease.expires_at, min(now + lease.ttl_s, max(cap, lease.expires_at)))

    def extend(self, token: str, minutes: float, session_id: str | None = None) -> Lease:
        lease = self.check(token, session_id, touch=False)
        now = self.clock()
        limit = now + self.t.max_hold_s
        lease.expires_at = min(lease.expires_at + minutes * 60, limit)
        self._hist(lease, "extended", f"+{minutes}m")
        self.emit("lease.state", lease=lease.public())
        return lease

    def reclaim(self, token: str, session_id: str | None = None) -> Lease:
        lease = self.lease(token)
        if lease.state == EXPIRING:
            lease.state, lease.grace_until = ACTIVE, None
            if session_id and session_id in self.sessions:
                lease.session_id = session_id
            self.boards[lease.board_id].state = LEASED
            self.touch(lease)
            self._hist(lease, "reclaimed")
            self.emit("lease.state", lease=lease.public())
        elif lease.state not in (ACTIVE,):
            raise self._lease_error(lease)
        return lease

    def release(self, token: str, session_id: str | None = None) -> dict[str, Any]:
        lease = self.lease(token)
        if lease.state not in LIVE_LEASE_STATES:
            return {"status": "released", "board": lease.board_id, "already": True}
        if lease.state in (PAUSING, L_PAUSED):
            # The human holds the board; releasing just drops the agent's claim on it.
            lease.state = RELEASED
            lease.ended_at, lease.end_reason = self.clock(), "released while paused"
            b = self.boards[lease.board_id]
            b.lease_token, b.state, b.held_by = None, HUMAN, lease.paused_by
            self._hist(lease, "released")
            self.emit("lease.ended", lease=lease.public(), board=b.id, reason="released")
            return {"status": "released", "board": lease.board_id}
        self._end_lease(lease, RELEASED, "released by holder")
        self.dispatch()
        return {"status": "released", "board": lease.board_id}

    def _end_lease(
        self,
        lease: Lease,
        state: str,
        reason: str,
        board_state: str = AVAILABLE,
        held_by: str | None = None,
    ) -> None:
        lease.state, lease.ended_at, lease.end_reason = state, self.clock(), reason
        lease.grace_until = None
        self._hist(lease, state.lower(), reason)
        b = self.boards[lease.board_id]
        if b.lease_token == lease.token:
            b.lease_token = None
            if b.state != NEEDS_RECOVER:
                b.state = board_state
            b.held_by = held_by
        self.emit("lease.ended", lease=lease.public(), board=b.id, reason=reason, state=state)

    def _start_grace(self, lease: Lease) -> None:
        lease.state, lease.grace_until = EXPIRING, self.clock() + self.t.grace_s
        self._hist(lease, "expiring", "heartbeat lost")
        self.emit("lease.state", lease=lease.public())

    def set_op(self, token: str, op: str | None) -> None:
        lease = self.leases.get(token)
        if lease:
            lease.op = op
            self.emit("lease.op", lease=lease.id, board=lease.board_id, op=op)

    # ------------------------------------------------------- human preemption
    def pause(
        self, board_id: str, by: str, reason: str = "", draining: bool = False
    ) -> Lease | None:
        """Suspend the lease on a board. With draining=True the lease goes to PAUSING
        first; the service calls finish_pause() once the in-flight op has stopped."""
        b = self.board(board_id)
        if not b.lease_token:
            raise ArbiterError("BAD_REQUEST", f"{board_id} has no lease to pause")
        lease = self.leases[b.lease_token]
        if lease.state in (PAUSING, L_PAUSED):
            return lease
        lease.paused_by, lease.pause_reason = by, reason
        lease.state = PAUSING if draining else L_PAUSED
        if not draining:
            b.state = PAUSED
        self._hist(lease, "paused", f"{by}: {reason}")
        self._notify(
            lease.session_id,
            "paused",
            f"Your board {board_id} was paused by {by}"
            + (f" ({reason})" if reason else "")
            + ". Stop hardware work; your place is kept.",
            board=board_id,
            ticket=lease.ticket,
        )
        self.emit("lease.state", lease=lease.public())
        self.emit("board.state", board=board_id, state=b.state)
        return lease

    def finish_pause(self, token: str) -> None:
        lease = self.leases.get(token)
        if lease and lease.state == PAUSING:
            lease.state = L_PAUSED
            self.boards[lease.board_id].state = PAUSED
            self.emit("lease.state", lease=lease.public())
            self.emit("board.state", board=lease.board_id, state=PAUSED)

    def resume(self, board_id: str, by: str = "human") -> Lease | None:
        b = self.board(board_id)
        if b.state == HUMAN:
            b.state, b.held_by, b.human_auto = AVAILABLE, None, False
            self.emit("board.state", board=board_id, state=b.state)
            self.dispatch()
            return None
        if not b.lease_token:
            raise ArbiterError("BAD_REQUEST", f"{board_id} is not paused")
        lease = self.leases[b.lease_token]
        if lease.state not in (PAUSING, L_PAUSED):
            return lease
        lease.state, lease.paused_by, lease.pause_reason = ACTIVE, None, None
        b.state = LEASED
        # Give back the time the human held it.
        lease.expires_at = max(lease.expires_at, self.clock() + lease.ttl_s)
        self._hist(lease, "resumed", by)
        self._notify(
            lease.session_id,
            "resumed",
            f"Board {board_id} is yours again; you may continue.",
            board=board_id,
            ticket=lease.ticket,
        )
        self.emit("lease.state", lease=lease.public())
        self.emit("board.state", board=board_id, state=b.state)
        return lease

    def revoke(
        self, board_id: str, by: str, reason: str = "", requeue: bool = True, to_human: bool = False
    ) -> Lease | None:
        b = self.board(board_id)
        if not b.lease_token:
            if to_human and b.state == AVAILABLE:
                b.state, b.held_by = HUMAN, by
                self.emit("board.state", board=board_id, state=HUMAN, held_by=by)
            return None
        lease = self.leases[b.lease_token]
        self._end_lease(
            lease,
            REVOKED,
            f"{by}: {reason}" if reason else by,
            board_state=HUMAN if to_human else AVAILABLE,
            held_by=by if to_human else None,
        )
        msg = (
            f"Your lease on {board_id} was revoked by {by}"
            + (f" ({reason})" if reason else "")
            + "."
        )
        if requeue:
            e = self.tickets[lease.ticket]
            e.state, e.lease_token, e.pinned = "queued", None, True
            e.last_poll = self.clock()
            self.queue.append(e)
            self._sort()
            msg += f" You were re-queued at the head with ticket {e.ticket}."
            self.emit("queue.changed", reason="requeued", ticket=e.ticket)
        self._notify(
            lease.session_id,
            "revoked",
            msg,
            board=board_id,
            ticket=lease.ticket if requeue else None,
        )
        self.emit("board.state", board=board_id, state=b.state)
        self.dispatch()
        return lease

    def human_activity(self, board_id: str, by: str) -> None:
        """The human used a board directly. A free board becomes theirs until they have been
        idle for human_idle_s, so an agent doesn't grab it mid-session. Explicit holds
        (`take`) are kept until given back."""
        b = self.board(board_id)
        b.human_seen = self.clock()
        if b.state == AVAILABLE and b.lease_token is None:
            b.state, b.held_by, b.human_auto = HUMAN, by, True
            self.emit("board.state", board=board_id, state=HUMAN, held_by=by, auto=True)

    def take(self, board_id: str, by: str, reason: str = "") -> Lease | None:
        """Human takes the board outright: an idle board goes to HUMAN, a leased one is revoked."""
        self.board(board_id).human_auto = False
        return self.revoke(
            board_id, by=by, reason=reason or "human took the board", requeue=True, to_human=True
        )

    # ------------------------------------------------------------ queue editing
    def move(self, ticket: str, index: int) -> None:
        e = self._queued(ticket)
        others = [x for x in self.queue if x is not e]
        index = max(0, min(index, len(others)))
        e.pinned = False
        if not others:
            return
        if index == 0:
            ref = others[0]
            e.pinned = ref.pinned
            e.priority, e.seq = ref.priority, ref.seq - 1.0
        elif index >= len(others):
            ref = others[-1]
            e.priority, e.seq = ref.priority, ref.seq + 1.0
            e.pinned = False
        else:
            before, after = others[index - 1], others[index]
            e.pinned = before.pinned and after.pinned
            e.priority = after.priority
            if before.priority == after.priority:
                e.seq = (before.seq + after.seq) / 2
            else:
                e.seq = after.seq - 0.5 if after.seq - 0.5 > -1e9 else after.seq
        self._sort()
        self.emit("queue.changed", reason="moved", ticket=ticket)
        self.dispatch()

    def set_priority(self, ticket: str, priority: int | str) -> None:
        e = self._queued(ticket)
        e.priority = self._priority(priority, human=True)
        self._sort()
        self.emit("queue.changed", reason="priority", ticket=ticket)
        self.dispatch()

    def pin(self, ticket: str, pinned: bool = True) -> None:
        e = self._queued(ticket)
        e.pinned = pinned
        e.seq = (min((x.seq for x in self.queue), default=0) - 1.0) if pinned else e.seq
        self._sort()
        self.emit("queue.changed", reason="pinned", ticket=ticket)
        self.dispatch()

    def bump_session(self, session_id: str, priority: int | str = "high") -> None:
        self.session(session_id)
        prio = self._priority(priority, human=True)
        for e in self.queue:
            if e.session_id == session_id:
                e.priority = prio
        self._sort()
        self.emit("queue.changed", reason="bumped", session=session_id)
        self.dispatch()

    def _queued(self, ticket: str) -> QueueEntry:
        e = self.tickets.get(ticket)
        if e is None or e.state != "queued":
            raise ArbiterError("TICKET_UNKNOWN", f"{ticket} is not in the queue")
        return e

    # --------------------------------------------------------------- the clock
    def _drop_stale_sessions(self, now: float) -> None:
        """End sessions that are gone and hold nothing, so they leave the agents list: a
        killed agent once its grace has passed, a CLI session after idle_session_s."""
        for s in list(self.sessions.values()):
            if s.ended or s.agent_kind == "human":
                continue
            if self.leases_of(s.id) or any(e.session_id == s.id for e in self.queue):
                continue
            idle = now - s.last_heartbeat
            gone = (
                s.heartbeat and not s.alive and idle > self.t.heartbeat_timeout_s + self.t.grace_s
            )
            if gone or idle > self.t.idle_session_s:
                s.ended, s.alive = True, False
                self.emit("session.ended", session=s.id, reason="stale")

    def tick(self) -> None:
        now = self.clock()
        for s in self.sessions.values():
            if (
                s.heartbeat
                and s.alive
                and not s.ended
                and now - s.last_heartbeat > self.t.heartbeat_timeout_s
            ):
                s.alive = False
                self.emit("session.lost", session=s.id)
                for lease in self.leases_of(s.id):
                    if lease.state == ACTIVE:
                        self._start_grace(lease)
        self._drop_stale_sessions(now)
        for b in self.boards.values():
            if (
                b.state == HUMAN
                and b.human_auto
                and b.lease_token is None
                and now - b.human_seen > self.t.human_idle_s
            ):
                b.state, b.held_by, b.human_auto = AVAILABLE, None, False
                self.emit("board.state", board=b.id, state=AVAILABLE, reason="human idle")
                self.dispatch()
        changed = False
        for lease in list(self.leases.values()):
            if lease.state == EXPIRING and lease.grace_until and now >= lease.grace_until:
                self._end_lease(lease, REVOKED, "agent disconnected (heartbeat lost)")
                self.tickets[lease.ticket].state = "expired"
                changed = True
            elif lease.state == ACTIVE and lease.op:
                self.touch(lease)
            elif (
                lease.state == ACTIVE
                and not lease.claimed
                and now - lease.granted_at > self.t.claim_timeout_s
            ):
                self._end_lease(lease, EXPIRED, "granted but never picked up")
                self.tickets[lease.ticket].state = "expired"
                changed = True
            elif lease.state == ACTIVE and now >= lease.expires_at:
                self._end_lease(lease, EXPIRED, "lease TTL ran out")
                self._notify(
                    lease.session_id,
                    "expired",
                    f"Your lease on {lease.board_id} expired.",
                    board=lease.board_id,
                )
                changed = True
            elif (
                lease.state == ACTIVE
                and 0 < lease.expires_at - now <= 60
                and not any(h[1] == "warned" for h in lease.history[-3:])
            ):
                self._hist(lease, "warned")
                self._notify(
                    lease.session_id,
                    "expiring",
                    f"Your lease on {lease.board_id} expires in {int(lease.expires_at - now)} s. "
                    "Call extend_lease if you still need it, or release_board.",
                    board=lease.board_id,
                )
        for e in list(self.queue):
            es = self.sessions.get(e.session_id)
            kept_alive = es is not None and es.heartbeat and es.alive
            if not kept_alive and now - e.last_poll > self.t.ticket_ttl_s:
                self._drop_entry(e, "expired")
                changed = True
        if changed:
            self.dispatch()

    # ------------------------------------------------------------ persistence
    def snapshot(self) -> dict[str, Any]:
        now = self.clock()
        return {
            "now": now,
            "boards": [
                {
                    **asdict(b),
                    "state": self.board_status(b),
                    "lease": self.leases[b.lease_token].public() if b.lease_token else None,
                }
                for b in self.boards.values()
            ],
            "queue": [
                {
                    "ticket": e.ticket,
                    "session": e.session_id,
                    "who": self.sessions[e.session_id].label
                    if e.session_id in self.sessions
                    else "?",
                    "selector": asdict(e.selector),
                    "wants": e.selector.describe(),
                    "priority": e.priority,
                    "pinned": e.pinned,
                    "reason": e.reason,
                    "enqueued_at": e.enqueued_at,
                    "waiting_s": round(now - e.enqueued_at),
                }
                for e in self.queue
            ],
            "leases": [le.public() for le in self.leases.values() if le.state in LIVE_LEASE_STATES],
            "sessions": [s.public() for s in self.sessions.values() if not s.ended],
        }

    def dump(self) -> dict[str, Any]:
        return {
            "seq": self._seq,
            "boards": {k: asdict(v) for k, v in self.boards.items()},
            "sessions": {k: asdict(v) for k, v in self.sessions.items() if not v.ended},
            "tickets": {
                k: {**asdict(v), "selector": asdict(v.selector)}
                for k, v in self.tickets.items()
                if v.state in ("queued", "granted")
            },
            "leases": {
                k: asdict(v) for k, v in self.leases.items() if v.state in LIVE_LEASE_STATES
            },
        }

    def restore(self, data: dict[str, Any]) -> None:
        """Restore after a daemon restart. Active leases come back as EXPIRING so their
        agents can reclaim them with their token during the grace window."""
        now = self.clock()
        self._seq = data.get("seq", 0.0)
        for k, v in data.get("sessions", {}).items():
            s = Session(**_known(Session, v))
            s.last_heartbeat, s.alive = now, True
            self.sessions[k] = s
        for k, v in data.get("leases", {}).items():
            if v["board_id"] not in self.boards or v["session_id"] not in self.sessions:
                continue
            lease = Lease(**_known(Lease, v))
            lease.op = None
            if lease.state in (ACTIVE, EXPIRING):
                lease.state, lease.grace_until = EXPIRING, now + max(self.t.grace_s, 60)
                lease.expires_at = max(lease.expires_at, now + 120)
            elif lease.state == PAUSING:
                lease.state = L_PAUSED
            self.leases[k] = lease
            b = self.boards[lease.board_id]
            b.lease_token = k
            b.state = PAUSED if lease.state == L_PAUSED else LEASED
        for k, v in data.get("boards", {}).items():
            if k in self.boards:
                b = self.boards[k]
                if v["state"] in (MAINTENANCE, NEEDS_RECOVER, HUMAN) and not b.lease_token:
                    b.state, b.held_by, b.note = v["state"], v.get("held_by"), v.get("note")
                    b.human_auto, b.human_seen = bool(v.get("human_auto")), now
        for k, v in data.get("tickets", {}).items():
            if v["session_id"] not in self.sessions:
                continue
            fields = {**v, "selector": Selector(**v["selector"])}
            e = QueueEntry(**_known(QueueEntry, fields))
            if e.state == "granted" and e.lease_token not in self.leases:
                continue
            self.tickets[k] = e
            if e.state == "queued":
                e.last_poll = now
                self.queue.append(e)
        self._sort()


def _known(cls: Any, d: dict[str, Any]) -> dict[str, Any]:
    """Drop keys a newer or older version persisted that this dataclass doesn't have."""
    return {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
