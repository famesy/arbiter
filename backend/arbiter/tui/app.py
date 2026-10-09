"""`arbiter tui`: the board console in the terminal, with a one-line status bar and
function keys for taking the board, pausing an agent, the queue and the view.

It talks to arbiterd exactly like the web dashboard: GET /api/state, the admin routes and
two WebSockets (/api/events and /api/boards/{id}/console). Settings stay in the dashboard."""

from __future__ import annotations

import asyncio
import codecs
import contextlib
import json
import time
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import quote

import websockets
from rich.console import RenderableType
from rich.style import Style
from rich.table import Table
from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.geometry import Size
from textual.screen import ModalScreen
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import DataTable, Footer, Input, OptionList, Static
from textual.widgets.option_list import Option

from ..client import AsyncClient
from ..config import state_dir
from ..errors import ArbiterError
from .model import (
    BootBlock,
    ConsoleModel,
    Entry,
    Line,
    ShellTree,
    board_status,
    channel_names,
    dur,
    lease_left,
    queue_for,
    who,
)

VIEW_OPTS = [
    ("fold", "Fold boot output", True),
    ("ts", "Show log timestamps", False),
    ("prompt", "Show shell prompts", False),
]

# Yellow warnings and red errors stay on even when the firmware's log colours are off.
LEVEL_STYLE = {"e": Style(color="red"), "w": Style(color="yellow")}
KIND_STYLE = {"note": Style(dim=True), "agent": Style(dim=True)}
TAG_STYLE = {"you": Style(color="cyan", bold=True), "agent": Style(color="magenta", bold=True)}
DIM = Style(dim=True)


def _prefs_path() -> Path:
    return state_dir() / "tui.json"


def load_view() -> dict[str, bool]:
    view = {k: d for k, _, d in VIEW_OPTS}
    with contextlib.suppress(OSError, ValueError, TypeError):
        saved = json.loads(_prefs_path().read_text())
        view.update({k: bool(v) for k, v in saved.items() if k in view})
    return view


def save_view(view: dict[str, bool]) -> None:
    with contextlib.suppress(OSError):
        _prefs_path().parent.mkdir(parents=True, exist_ok=True)
        _prefs_path().write_text(json.dumps(view))


def line_text(line: Line, view: dict[str, bool]) -> Text | None:
    """How one console line looks, or None when the view hides it (a bare prompt)."""
    if line.bare_prompt and not view["prompt"]:
        return None
    t = Text(end="")
    if line.tag:
        t.append(line.tag + " ", TAG_STYLE.get(line.kind))
    if line.src:
        t.append(line.src, Style(color="blue", dim=True))
    if line.ts and view["ts"]:
        t.append(line.ts, DIM)
    if line.prompt and view["prompt"]:
        t.append(line.prompt, Style(color="green", dim=True))
    style = LEVEL_STYLE.get(line.level) or KIND_STYLE.get(line.kind) or Style()
    t.append(line.text, style)
    return t


class ConsoleView(ScrollView, can_focus=False):
    """The live console: wrapped lines drawn on demand, boot blocks folded to one line
    (click one to open it). Only the changed tail is laid out again as text arrives."""

    DEFAULT_CSS = """
    ConsoleView { height: 1fr; overflow-x: hidden; scrollbar-size-vertical: 1; }
    """

    def __init__(self, view: dict[str, bool], **kw: Any):
        super().__init__(**kw)
        self.view = view
        self.model = ConsoleModel()
        self._rows: list[Strip] = []
        self._row_entry: list[int] = []  # entry index per row (-1: the unfinished line)
        self._entry_start: list[int] = []
        self._entry_rows = 0
        self._width = 0
        self._pending = False

    def set_model(self, model: ConsoleModel) -> None:
        self.model = model
        self._width = 0  # lay everything out again
        self.update_rows()

    def schedule(self) -> None:
        """Coalesce bursts of console chunks into one layout pass."""
        if not self._pending:
            self._pending = True
            self.set_timer(0.03, self.update_rows)

    def relayout(self) -> None:
        self._width = 0
        self.update_rows()

    def _render_text(self, text: Text, width: int) -> list[Strip]:
        console = self.app.console
        opts = console.options.update(width=width, no_wrap=False, overflow="fold")
        lines = console.render_lines(text, opts, pad=False)
        return [Strip(segs) for segs in lines] or [Strip.blank(0)]

    def _entry_rows_for(self, entry: Entry, width: int) -> list[Strip]:
        out: list[Strip] = []
        lines: list[Line]
        if isinstance(entry, BootBlock):
            if self.view["fold"]:
                mark = "▾ " if entry.open else "▸ "
                style = LEVEL_STYLE.get(entry.level) or Style(dim=True, italic=True)
                out += self._render_text(Text(mark + entry.summary(), style, end=""), width)
            lines = entry.lines if (entry.open or not self.view["fold"]) else []
        else:
            lines = [entry]
        for line in lines:
            t = line_text(line, self.view)
            if t is not None:
                out += self._render_text(t, width)
        return out

    def update_rows(self) -> None:
        self._pending = False
        width = self.scrollable_content_region.width
        if width <= 0:
            return
        stick = self.scroll_offset.y >= self.max_scroll_y
        dirty = self.model.take_dirty()
        if width != self._width:
            self._width, dirty = width, 0
        cut = self._entry_start[dirty] if dirty < len(self._entry_start) else self._entry_rows
        del self._rows[cut:]
        del self._row_entry[cut:]
        del self._entry_start[dirty:]
        for i in range(dirty, len(self.model.entries)):
            self._entry_start.append(len(self._rows))
            rows = self._entry_rows_for(self.model.entries[i], width)
            self._rows += rows
            self._row_entry += [i] * len(rows)
        self._entry_rows = len(self._rows)
        partial = self.model.partial
        t = line_text(partial, self.view) if partial else None
        if t is not None:
            rows = self._render_text(t, width)
            self._rows += rows
            self._row_entry += [-1] * len(rows)
        self.virtual_size = Size(width, len(self._rows))
        if stick:
            self.scroll_end(animate=False, immediate=True)
        self.refresh()

    def render_line(self, y: int) -> Strip:
        row = self.scroll_offset.y + y
        width = self.scrollable_content_region.width
        if row >= len(self._rows):
            return Strip.blank(width, self.rich_style)
        return self._rows[row].crop_extend(0, width, None).apply_style(self.rich_style)

    def on_resize(self, event: events.Resize) -> None:
        self.update_rows()

    def on_click(self, event: events.Click) -> None:
        row = self.scroll_offset.y + event.y
        if not self.view["fold"] or not 0 <= row < len(self._row_entry):
            return
        i = self._row_entry[row]
        entry = self.model.entries[i] if i >= 0 else None
        if isinstance(entry, BootBlock):
            entry.open = not entry.open
            self.model.mark_dirty(i)
            self.update_rows()


class Suggest(OptionList, can_focus=False):
    """Shell commands that complete the typed word."""


class ShellInput(Input):
    """The command line. Tab and the arrow keys drive the suggestions first, then history."""

    async def _on_key(self, event: events.Key) -> None:
        app = self.app
        if isinstance(app, ArbiterTui) and app.shell_key(event.key):
            event.prevent_default()
            event.stop()
            return
        await super()._on_key(event)


# ------------------------------------------------------------------------ popups
class Popup(ModalScreen[None]):
    DEFAULT_CSS = """
    Popup { align: center middle; }
    Popup > Vertical {
        width: 76; max-width: 100%; height: auto; max-height: 80%;
        border: round $accent; background: $surface; padding: 0 1;
    }
    Popup .title { text-style: bold; margin-bottom: 1; }
    Popup .keys { color: $text-muted; margin-top: 1; }
    Popup DataTable { height: auto; max-height: 16; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape,q", "dismiss", "Close")]

    @property
    def tui(self) -> ArbiterTui:
        app = self.app
        assert isinstance(app, ArbiterTui)
        return app

    def refresh_data(self) -> None:
        """Called when the daemon's state changes."""


class QueuePopup(Popup):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape,q,f4", "dismiss", "Close"),
        Binding("shift+up,u", "move(-1)", "Move up"),
        Binding("shift+down,d", "move(1)", "Move down"),
        Binding("p", "priority", "Priority"),
        Binding("x,delete", "cancel", "Cancel ticket"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("", classes="title")
            yield DataTable(cursor_type="row", zebra_stripes=False)
            yield Static("", classes="empty")
            yield Static("↑↓ select · u/d move · p priority · x cancel · Esc close", classes="keys")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("#", "Agent", "Priority", "Waiting", "Wants")
        self.refresh_data()

    def entries(self) -> list[dict[str, Any]]:
        b = self.tui.board
        return queue_for(self.tui.state, b) if b else []

    def refresh_data(self) -> None:
        b = self.tui.board
        q = self.entries()
        self.query_one(".title", Static).update(
            f"Queue for {b['id'] if b else '-'}" + (f" ({len(q)} waiting)" if q else "")
        )
        empty = self.query_one(".empty", Static)
        empty.update("Nobody is waiting for this board.")
        empty.display = not q
        self.query_one(DataTable).display = bool(q)
        table = self.query_one(DataTable)
        row = table.cursor_row
        table.clear()
        for i, e in enumerate(q, 1):
            prio = PRIO_NAMES.get(e.get("priority"), str(e.get("priority", "")))
            table.add_row(
                str(i),
                who(e.get("who")) + (" (pinned)" if e.get("pinned") else ""),
                prio,
                dur(e.get("waiting_s") or 0),
                str(e.get("wants") or ""),
                key=str(e["ticket"]),
            )
        if q:
            table.move_cursor(row=min(row, len(q) - 1))

    def _current(self) -> tuple[int, list[dict[str, Any]]] | None:
        q = self.entries()
        row = self.query_one(DataTable).cursor_row
        return (row, q) if 0 <= row < len(q) else None

    async def action_move(self, step: int) -> None:
        cur = self._current()
        if not cur:
            return
        i, q = cur
        j = i + step
        if not 0 <= j < len(q):
            return
        # move takes an index in the whole queue without this entry
        e = q[i]
        others = [x for x in self.tui.state.get("queue") or [] if x["ticket"] != e["ticket"]]
        index = others.index(q[j]) + (1 if step > 0 else 0)
        if await self.tui.call("Move", f"/api/admin/queue/{e['ticket']}/move", {"index": index}):
            self.query_one(DataTable).move_cursor(row=j)
            await self.tui.refresh_state()

    async def action_priority(self) -> None:
        cur = self._current()
        if not cur:
            return
        e = cur[1][cur[0]]
        names = list(PRIO_VALUES)
        now = PRIO_NAMES.get(e.get("priority"), "normal")
        nxt = names[(names.index(now) + 1) % len(names)] if now in names else "high"
        await self.tui.call(
            "Priority", f"/api/admin/queue/{e['ticket']}/priority", {"priority": nxt}
        )
        await self.tui.refresh_state()

    async def action_cancel(self) -> None:
        cur = self._current()
        if not cur:
            return
        e = cur[1][cur[0]]
        await self.tui.call("Cancel", f"/api/admin/queue/{e['ticket']}/cancel", {})
        await self.tui.refresh_state()


PRIO_VALUES = {"low": 0, "normal": 50, "high": 80, "urgent": 100}
PRIO_NAMES: dict[Any, str] = {v: k for k, v in PRIO_VALUES.items()} | {k: k for k in PRIO_VALUES}


class ViewPopup(Popup):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape,q,f7,enter", "dismiss", "Close"),
        Binding("1", "flip('fold')", show=False),
        Binding("2", "flip('ts')", show=False),
        Binding("3", "flip('prompt')", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Console view", classes="title")
            yield Static("", id="opts")
            yield Static("Press 1, 2 or 3 to switch · Esc close", classes="keys")

    def on_mount(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        view = self.tui.view
        t = Text()
        for n, (k, label, _) in enumerate(VIEW_OPTS, 1):
            t.append(f" {n} ", Style(bold=True))
            t.append("[x] " if view[k] else "[ ] ", Style(color="green" if view[k] else None))
            t.append(label + ("\n" if n < len(VIEW_OPTS) else ""))
        self.query_one("#opts", Static).update(t)

    def action_flip(self, key: str) -> None:
        self.tui.set_view(key, not self.tui.view[key])
        self.refresh_data()


class RequestsPopup(Popup):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape,q,f9", "dismiss", "Close"),
        Binding("a,y", "decide(True)", "Approve"),
        Binding("d,n", "decide(False)", "Deny"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Requests from agents", classes="title")
            yield DataTable(cursor_type="row")
            yield Static("↑↓ select · a approve · d deny · Esc close", classes="keys")

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns("Agent", "Wants to", "Board")
        self.refresh_data()

    def refresh_data(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        sessions = {s["id"]: s for s in self.tui.state.get("sessions") or []}
        for a in self.tui.state.get("approvals") or []:
            s = sessions.get(a.get("session"))
            table.add_row(
                s["label"] if s else str(a.get("session", "")),
                str(a.get("action", "")).replace("_", " "),
                str(a.get("board", "")),
                key=str(a["id"]),
            )
        if not table.row_count:
            self.dismiss()

    async def action_decide(self, approve: bool) -> None:
        approvals = self.tui.state.get("approvals") or []
        row = self.query_one(DataTable).cursor_row
        if 0 <= row < len(approvals):
            a = approvals[row]
            await self.tui.call(
                "Approve" if approve else "Deny",
                f"/api/admin/approvals/{a['id']}",
                {"approve": approve},
            )
            await self.tui.refresh_state()


# ------------------------------------------------------------------------ the app
DONE = {
    "take": "You hold {bid}. Agents wait until you give it back (F5).",
    "release": "Gave {bid} back to the queue.",
    "pause": "Paused the agent on {bid}.",
    "resume": "The agent has {bid} again.",
    "reset": "Reset {bid}.",
}


class ArbiterTui(App[int]):
    TITLE = "arbiter"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { layout: vertical; }
    #status { height: 1; background: $panel; padding: 0 1; }
    #suggest {
        height: auto; max-height: 8; border: none; padding: 0;
        background: $surface; display: none;
    }
    #suggest.open { display: block; }
    #hint { height: 1; padding: 0 1; color: $text-muted; display: none; }
    #hint.on { display: block; }
    #prompt { height: 1; }
    #mark { width: 3; color: $accent; padding-left: 1; }
    #input { height: 1; border: none; padding: 0; background: $background; }
    #input:focus { border: none; }
    """
    # One key, several bindings: the footer shows the one that fits the board's state.
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("f2", "next_board", "Board", priority=True),
        Binding("f3", "next_channel", "Channel", priority=True),
        Binding("f4", "queue", "Queue", priority=True),
        Binding("f5", "take", "Take board", priority=True),
        Binding("f5", "take_over", "Take over", priority=True),
        Binding("f5", "give_back", "Give back", priority=True),
        Binding("f6", "pause", "Pause agent", priority=True),
        Binding("f6", "resume", "Resume agent", priority=True),
        Binding("f7", "view", "View", priority=True),
        Binding("f8", "reset", "Reset", priority=True),
        Binding("f9", "requests", "Requests", priority=True),
        Binding("ctrl+l", "clear", "Clear", show=False, priority=True),
        Binding("pageup", "page(-1)", show=False, priority=True),
        Binding("pagedown", "page(1)", show=False, priority=True),
        Binding("ctrl+end", "bottom", show=False, priority=True),
        Binding("ctrl+q", "quit", "Quit", priority=True),
    ]

    def __init__(self, board: str | None = None, channel: str = "all"):
        super().__init__()
        self.state: dict[str, Any] = {"boards": [], "queue": [], "approvals": []}
        self.selected = board
        self.channel = channel
        self.view = load_view()
        self.connected = False
        self.skew = 0.0
        self.last_seq = 0
        self.shell = ShellTree()
        self.shell_board: str | None = None
        self.history: list[str] = []
        self.hist_pos = -1
        self.forced = False
        self.api: AsyncClient | None = None
        self._refresh_pending = False
        self._console_key: tuple[str, str] | None = None

    # -------------------------------------------------------------- layout
    def compose(self) -> ComposeResult:
        yield Static(id="status")
        yield ConsoleView(self.view, id="console")
        yield Suggest(id="suggest")
        yield Static(id="hint")
        with Horizontal(id="prompt"):
            yield Static(">", id="mark")
            yield ShellInput(id="input", placeholder="Type a command, Enter to send")
        yield Footer(compact=True, show_command_palette=False)

    @property
    def console_view(self) -> ConsoleView:
        return self.query_one(ConsoleView)

    @property
    def input(self) -> ShellInput:
        return self.query_one(ShellInput)

    @property
    def board(self) -> dict[str, Any] | None:
        return next((b for b in self.state["boards"] if b["id"] == self.selected), None)

    def now(self) -> float:
        return time.time() + self.skew

    async def on_mount(self) -> None:
        self.input.focus()
        self.render_status()
        self.set_interval(1.0, self.render_status)
        self.events_loop()

    # -------------------------------------------------------------- daemon
    def _client(self) -> AsyncClient:
        """A client with the current admin token (arbiterd makes a new one at each start)."""
        if self.api is None:
            self.api = AsyncClient(admin=True)
        return self.api

    def _ws_url(self, path: str) -> str:
        c = self._client()
        sep = "&" if "?" in path else "?"
        return f"ws{c.base[4:]}{path}{sep}token={quote(c.token)}"

    def _reconnect(self) -> None:
        if self.api is not None:
            api = self.api
            self.api = None
            self.run_worker(api.aclose(), exit_on_error=False)

    async def call(self, label: str, path: str, body: dict[str, Any] | None = None) -> Any:
        """POST and report a failure as a toast. Returns the reply, or None on failure."""
        try:
            return await self._client().post(path, body or {})
        except ArbiterError as e:
            self.notify(f"{label}: {e.message}", severity="error")
            if e.code == "UNAUTHORIZED":
                self._reconnect()
            return None

    async def refresh_state(self) -> None:
        try:
            s = await self._client().get("/api/state")
        except ArbiterError:
            self._reconnect()
            return
        self.set_state(s)

    def refresh_soon(self) -> None:
        if self._refresh_pending:
            return
        self._refresh_pending = True

        async def go() -> None:
            self._refresh_pending = False
            await self.refresh_state()

        self.set_timer(0.15, go)

    def set_state(self, s: dict[str, Any]) -> None:
        self.state = s
        self.skew = float(s.get("now", time.time())) - time.time()
        ids = [b["id"] for b in s.get("boards") or []]
        if self.selected not in ids:
            self.selected = ids[0] if ids else None
        self.open_console()
        self.load_shell()
        self.render_status()
        self.update_hint()
        self.refresh_bindings()
        if isinstance(self.screen, Popup):
            self.screen.refresh_data()

    @work(exclusive=True, group="events")
    async def events_loop(self) -> None:
        backoff = 1.0
        while True:
            try:
                url = self._ws_url(f"/api/events?since={self.last_seq}")
                async with websockets.connect(url, max_size=None) as ws:
                    self.set_connected(True)
                    backoff = 1.0
                    async for msg in ws:
                        self.handle_event(json.loads(msg))
            except (OSError, ArbiterError, websockets.WebSocketException, ValueError):
                self._reconnect()
            self.set_connected(False)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 10.0)

    def set_connected(self, up: bool) -> None:
        if up != self.connected:
            self.connected = up
            self.render_status()

    def handle_event(self, ev: dict[str, Any]) -> None:
        kind = ev.get("kind")
        if kind == "snapshot":
            self.set_state(ev["state"])
            return
        seq = int(ev.get("seq") or 0)
        if seq and seq <= self.last_seq:
            return
        self.last_seq = max(self.last_seq, seq)
        if kind == "board.shell" and ev.get("board") == self.shell_board:
            self.shell_board = None  # load again
        # Replayed history does not toast; only events from the last few seconds do.
        if float(ev.get("ts") or 0) > self.now() - 5:
            self.toast_event(ev)
        self.refresh_soon()

    def toast_event(self, ev: dict[str, Any]) -> None:
        kind = ev.get("kind")
        sessions = {s["id"]: s.get("label") for s in self.state.get("sessions") or []}
        if kind == "notify":
            self.notify(who(ev.get("text")), severity="warning")
        elif kind == "session.lost":
            name = sessions.get(ev.get("session")) or ev.get("session")
            self.notify(f"{name} stopped responding", severity="warning")
        elif kind == "approval.requested":
            a = ev.get("approval") or {}
            name = who(ev.get("who")) or sessions.get(a.get("session")) or "An agent"
            action = str(a.get("action", "")).replace("_", " ")
            self.notify(
                f"{name} asks to {action} {a.get('board')}. F9 to answer.", severity="warning"
            )
        elif kind == "op.finished":
            op = ev.get("op") or {}
            r = op.get("result") or {}
            if op.get("error") or r.get("ok") is False:
                msg = (op.get("error") or {}).get("message") or "failed"
                self.notify(f"{op.get('kind')} on {op.get('board')}: {msg}", severity="error")

    # -------------------------------------------------------------- console
    def open_console(self, force: bool = False) -> None:
        b = self.board
        if b is None:
            return
        if self.channel not in channel_names(b):
            self.channel = "all"
        key = (b["id"], self.channel)
        if key == self._console_key and not force:
            return
        self._console_key = key
        self.console_loop(b["id"], self.channel)

    @work(exclusive=True, group="console")
    async def console_loop(self, board: str, channel: str) -> None:
        human = (self.state.get("daemon") or {}).get("human")
        while True:
            b = self.board or {}
            model = ConsoleModel(names=channel_names(b) if b else [], me=human)
            self.console_view.set_model(model)
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            code: int | None = None
            try:
                url = self._ws_url(
                    f"/api/boards/{quote(board)}/console?channel={quote(channel)}&scrollback=65536"
                )
                async with websockets.connect(url, max_size=None) as ws:
                    async for msg in ws:
                        if isinstance(msg, bytes):
                            model.feed(decoder.decode(msg))
                            self.console_view.schedule()
                        else:  # an error from the daemon
                            self.notify(_error_text(msg), severity="error")
                    code = ws.close_code
            except (OSError, ArbiterError, websockets.WebSocketException):
                pass
            if code == 4404:
                model.note(f"[tui] {board} has no console channel {channel!r}")
                self.console_view.update_rows()
                return
            model.note("[tui] console disconnected, reconnecting")
            self.console_view.update_rows()
            await asyncio.sleep(2)

    # -------------------------------------------------------------- shell input
    def load_shell(self) -> None:
        b = self.board
        if b is None or self.shell_board == b["id"]:
            return
        # Not an exclusive worker: state updates arrive in bursts and would cancel it.
        self.shell_board = b["id"]
        self.run_worker(self._fetch_shell(b["id"]), group="shell")

    async def _fetch_shell(self, board: str) -> None:
        try:
            data: dict[str, Any] | None = await self._client().get(
                f"/api/boards/{quote(board)}/shell"
            )
        except ArbiterError:
            data = None  # older daemons have no endpoint
        if self.shell_board == board:
            self.shell = ShellTree(data)
            self.update_suggest()

    def on_input_changed(self, event: Input.Changed) -> None:
        self.forced = False
        self.update_suggest()

    def update_suggest(self) -> None:
        box = self.query_one(Suggest)
        opts = self.shell.options(self.input.value, self.forced)
        if not opts:
            self.forced = False
        box.clear_options()
        for c in opts:
            t = Text(str(c["name"]), Style(bold=True))
            if c.get("subcommands"):
                t.append(" …", DIM)
            helptext = str(c.get("help") or "").splitlines()
            if helptext:
                t.append("  " + helptext[0], DIM)
            box.add_option(Option(t, id=str(c["name"])))
        box.highlighted = None
        box.set_class(bool(opts), "open")
        self.update_hint()

    def shell_key(self, key: str) -> bool:
        """Keys for the suggestions and history. True when handled."""
        box = self.query_one(Suggest)
        n = box.option_count
        value = self.input.value
        if key == "tab":
            if not n and not value.strip() and self.shell.available:
                self.forced = True
                self.update_suggest()
            elif n == 1 or (n and box.highlighted is not None):
                self.accept(box.highlighted or 0)
            elif n:
                box.highlighted = 0
            return True  # Tab never leaves the input
        if key in ("up", "down") and n:
            cur = box.highlighted
            if cur is None:
                box.highlighted = 0 if key == "down" else n - 1
            else:
                box.highlighted = (cur + (1 if key == "down" else -1)) % n
            return True
        if key == "enter" and n and box.highlighted is not None:
            self.accept(box.highlighted)
            return True
        if key == "escape" and n:
            box.clear_options()
            box.set_class(False, "open")
            return True
        if key in ("up", "down") and self.history:
            # Command history, like a shell.
            h = len(self.history)
            if key == "up":
                self.hist_pos = max(0, (h if self.hist_pos < 0 else self.hist_pos) - 1)
            else:
                self.hist_pos = (
                    -1 if self.hist_pos < 0 or self.hist_pos + 1 >= h else self.hist_pos + 1
                )
            self.input.value = "" if self.hist_pos < 0 else self.history[self.hist_pos]
            self.input.cursor_position = len(self.input.value)
            return True
        return False

    def accept(self, index: int) -> None:
        box = self.query_one(Suggest)
        opt = box.get_option_at_index(index)
        if opt.id is None:
            return
        self.input.value = self.shell.accept(self.input.value, opt.id)
        self.input.cursor_position = len(self.input.value)
        self.update_suggest()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        data = event.value.rstrip()
        b = self.board
        if not data.strip() or b is None:
            return
        body: dict[str, Any] = {"data": data}
        if self.channel != "all":
            body["channel"] = self.channel
        if await self.call("Send", f"/api/admin/boards/{quote(b['id'])}/write", body) is not None:
            line = data.strip()
            if not self.history or self.history[-1] != line:
                self.history.append(line)
                del self.history[:-100]
            self.hist_pos = -1
            self.input.value = ""

    def update_hint(self) -> None:
        hint = self.query_one("#hint", Static)
        b = self.board
        text = self.shell.help_for(self.input.value)
        if not text and b and b["state"] == "LEASED" and b.get("lease"):
            # You can type while an agent holds the board: the line goes to the console,
            # marked as yours, and the agent keeps its lease.
            text = f"{who(b['lease'].get('holder'))} holds this board. Lines you send are marked [you]; the agent keeps the board."
        hint.update(Text(text))  # plain text: "[you]" is not markup
        hint.set_class(bool(text), "on")
        holder = who((b.get("lease") or {}).get("holder")) if b else ""
        self.input.placeholder = (
            f"Type alongside {holder}, Enter to send"
            if b and b["state"] == "LEASED" and holder
            else "Type a command, Enter to send"
        )
        self.input.disabled = bool(b and b["state"] == "OFFLINE")

    # -------------------------------------------------------------- status bar
    def render_status(self) -> None:
        self.query_one("#status", Static).update(self.status_text())

    def status_text(self) -> RenderableType:
        left = Text(no_wrap=True, overflow="ellipsis")
        boards = self.state.get("boards") or []
        b = self.board
        if len(boards) > 1:  # the board switcher only shows when there is a choice
            for x in boards:
                on = x["id"] == self.selected
                left.append(f" {x['id']} ", Style(bold=True, reverse=True) if on else DIM)
            left.append(" ")
        elif b:
            left.append(b["id"] + "  ", Style(bold=True))
        if b is None:
            left.append(
                "no boards configured" if self.connected else "connecting to arbiterd…", DIM
            )
        else:
            text, level = board_status(b)
            colour = {"err": "red", "warn": "yellow"}.get(level) or (
                "green" if b["state"] == "AVAILABLE" else "yellow"
            )
            left.append("● ", Style(color=colour))
            left.append(text, Style(color=colour) if level else Style())
            lease = b.get("lease")
            if lease and b["state"] != "HUMAN":
                left.append(f" · {who(lease.get('holder'))}")
                left_s = lease_left(b, self.now())
                if left_s:
                    left.append(f" · {left_s}", DIM)
            q = queue_for(self.state, b)
            left.append("  │  ", DIM)
            left.append(f"queue {len(q)}", Style(color="yellow") if q else DIM)
            p = b.get("power")
            if p:
                left.append("  │  ", DIM)
                if p.get("fault"):
                    left.append(f"power fault: {p['fault']}", Style(color="red"))
                elif p.get("on"):
                    left.append(f"{(p.get('mv') or 0) / 1000:.2f} V")
                else:
                    left.append("power off", Style(color="yellow"))
            if self.channel != "all":
                left.append("  │  ", DIM)
                left.append(self.channel)
            n = len(self.state.get("approvals") or [])
            if n:
                left.append("  │  ", DIM)
                left.append(
                    f"{n} request{'' if n == 1 else 's'} (F9)", Style(color="yellow", bold=True)
                )
        right = (
            Text("● live", Style(color="green"))
            if self.connected
            else Text("○ reconnecting", Style(color="red"))
        )
        grid = Table.grid(expand=True)
        grid.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
        grid.add_column(justify="right", no_wrap=True)
        grid.add_row(left, right)
        return grid

    # -------------------------------------------------------------- actions
    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        b = self.board
        st = b["state"] if b else None
        visible = {
            "next_board": len(self.state.get("boards") or []) > 1,
            "take": st == "AVAILABLE",
            "take_over": st in ("LEASED", "PAUSED"),
            "give_back": st == "HUMAN",
            "pause": st == "LEASED",
            "resume": st == "PAUSED",
            "reset": bool(b and "reset" in (b.get("capabilities") or []))
            and st not in ("LEASED", "OFFLINE"),
            "requests": bool(self.state.get("approvals")),
            "queue": b is not None,
            "next_channel": b is not None,
        }
        return visible.get(action, True)

    async def board_action(self, action: str, label: str) -> None:
        b = self.board
        if b is None:
            return
        res = await self.call(label, f"/api/admin/boards/{quote(b['id'])}/{action}", {})
        if res is not None and action in DONE:
            self.notify(DONE[action].format(bid=b["id"]))
        await self.refresh_state()

    async def action_take(self) -> None:
        await self.board_action("take", "Take")

    async def action_take_over(self) -> None:
        await self.board_action("take", "Take over")

    async def action_give_back(self) -> None:
        await self.board_action("release", "Give back")

    async def action_pause(self) -> None:
        await self.board_action("pause", "Pause")

    async def action_resume(self) -> None:
        await self.board_action("resume", "Resume")

    async def action_reset(self) -> None:
        await self.board_action("reset", "Reset")

    def action_next_board(self) -> None:
        ids = [b["id"] for b in self.state.get("boards") or []]
        if len(ids) > 1 and self.selected in ids:
            self.selected = ids[(ids.index(self.selected) + 1) % len(ids)]
            self.channel = "all"
            self.set_state(self.state)

    def action_next_channel(self) -> None:
        b = self.board
        if b is None:
            return
        names = channel_names(b)
        self.channel = (
            names[(names.index(self.channel) + 1) % len(names)] if self.channel in names else "all"
        )
        self.open_console()
        self.render_status()
        self.notify(f"Channel: {self.channel}", timeout=1.5)

    def action_queue(self) -> None:
        if self.board is not None:
            self.push_screen(QueuePopup())

    def action_view(self) -> None:
        self.push_screen(ViewPopup())

    def action_requests(self) -> None:
        if self.state.get("approvals"):
            self.push_screen(RequestsPopup())

    def action_clear(self) -> None:
        self.console_view.model.clear()
        self.console_view.update_rows()

    def action_page(self, step: int) -> None:
        cv = self.console_view
        cv.scroll_to(y=cv.scroll_offset.y + step * max(1, cv.size.height - 1), animate=False)

    def action_bottom(self) -> None:
        self.console_view.scroll_end(animate=False)

    def set_view(self, key: str, on: bool) -> None:
        self.view[key] = on
        save_view(self.view)
        self.console_view.relayout()


def _error_text(msg: str) -> str:
    try:
        data = json.loads(msg)
    except ValueError:
        return msg
    return str(data.get("message") or msg) if isinstance(data, dict) else msg
