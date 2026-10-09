"""`arbiter` command line: the daemon, agent commands (mirroring the MCP tools,
with exit codes 0 / 75 queued / 76 paused / 77 revoked) and human commands."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .client import Client, agent_kind, external_id, only_lease
from .errors import EXIT_QUEUED, ArbiterError

Command = Callable[[argparse.Namespace], int]


def _print(obj: Any, as_json: bool) -> None:
    if as_json or not isinstance(obj, dict):
        print(json.dumps(obj, indent=2))
        return
    for k, v in obj.items():
        shown = json.dumps(v) if isinstance(v, (dict, list)) else v
        print(f"{k}: {shown}")


def _session(c: Client, args: argparse.Namespace) -> str:
    """Use ARBITER_SESSION (set by the SessionStart hook) or register a CLI session once
    and remember it in the state dir. The key is the agent's own session id when there is
    one: Claude Code runs every Bash call in a new shell, so the parent pid changes."""
    if c.session:
        return c.session
    from .config import state_dir

    cache = state_dir() / "cli-sessions.json"
    key = external_id() or f"ppid-{os.getppid()}"
    try:
        known = json.loads(cache.read_text())
    except (OSError, ValueError):
        known = {}
    body = {"agent_kind": agent_kind(), "external_id": key, "cwd": str(Path.cwd())}
    if args.label or key not in known:
        # name the session once, so `cd` between commands doesn't rename it
        body["label"] = args.label or f"cli {Path.cwd().name}"
    s = c.post("/api/sessions", body)
    known[key] = s["id"]
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(known))
    except OSError:
        pass
    c.session = str(s["id"])
    return c.session


def _lease(c: Client, args: argparse.Namespace) -> str:
    tok = getattr(args, "lease", None) or os.environ.get("ARBITER_LEASE")
    if tok:
        return tok
    sid = _session(c, args)
    info = c.get(f"/api/sessions/{sid}")
    return only_lease(info, "Run `arbiter acquire <board>`", "Run `arbiter wait {ticket}`")


def _wait_op(c: Client, res: dict[str, Any]) -> dict[str, Any]:
    while res.get("status") == "running":
        res = c.get(f"/api/ops/{res['op_id']}", wait_s=45)
    return res


# ------------------------------------------------------------------ commands
def cmd_daemon(args: argparse.Namespace) -> int:
    from .daemon import run_daemon

    return run_daemon(Path(args.config) if args.config else None, args.port, args.host)


def cmd_status(args: argparse.Namespace) -> int:
    st = Client().get("/api/state")
    if args.json:
        _print(st, True)
        return 0
    for b in st["boards"]:
        line = f"{b['id']:<16} {b['state']:<13} {b['platform']}"
        if b.get("lease"):
            le = b["lease"]
            line += f"  held by {le['holder']} ({le['expires_in_s']} s left)"
            if le.get("reason"):
                line += f": {le['reason']}"
        if b.get("op"):
            line += f"  [{b['op']['kind']} {b['op']['elapsed_s']} s]"
        if b.get("note"):
            line += f"  ! {b['note']}"
        print(line)
    if st["queue"]:
        print("\nqueue:")
        for i, e in enumerate(st["queue"], 1):
            pin = " (pinned)" if e["pinned"] else ""
            print(
                f"  {i}. {e['ticket']}  {e['who']} wants {e['wants']}  prio {e['priority']}{pin}  "
                f"waiting {e['waiting_s']} s  {e['reason']}"
            )
    for a in st.get("approvals", []):
        print(
            f"\napproval {a['id']}: {a['action']} on {a['board']} (session {a['session']}) "
            f"-> arbiter approve {a['id']}"
        )
    for p in st.get("unassigned_probes", []):
        print(
            f"\nnew probe {p['kind']} {p['serial']} ({len(p['ports'])} ports) is not in the config"
        )
    return 0


def cmd_acquire(args: argparse.Namespace) -> int:
    c = Client(autostart=True)
    _session(c, args)
    res = c.post(
        "/api/acquire",
        {
            "selector": args.selector,
            "reason": args.reason,
            "priority": args.priority,
            "wait_s": args.wait,
        },
    )
    deadline = time.monotonic() + (args.block or 0)
    while res["status"] == "queued" and time.monotonic() < deadline:
        res = c.post(
            "/api/wait", {"ticket": res["ticket"], "wait_s": min(45, deadline - time.monotonic())}
        )
    _print(res, args.json)
    return 0 if res["status"] == "granted" else EXIT_QUEUED


def cmd_wait(args: argparse.Namespace) -> int:
    c = Client()
    _session(c, args)
    res = c.post("/api/wait", {"ticket": args.ticket, "wait_s": args.wait})
    _print(res, args.json)
    return 0 if res["status"] == "granted" else EXIT_QUEUED


def cmd_release(args: argparse.Namespace) -> int:
    c = Client()
    if not (args.lease or os.environ.get("ARBITER_LEASE")):
        info = c.get(f"/api/sessions/{_session(c, args)}")
        if not info.get("leases") and info.get("tickets"):
            for t in info["tickets"]:
                c.post("/api/cancel", {"ticket": t})
            _print({"ok": True, "cancelled_tickets": info["tickets"]}, args.json)
            return 0
    body = {"lease_token": _lease(c, args), "force": bool(getattr(args, "force", False))}
    _print(c.post("/api/release", body), args.json)
    return 0


def cmd_flash(args: argparse.Namespace) -> int:
    c = Client()
    res = c.post(
        "/api/flash",
        {
            "lease_token": _lease(c, args),
            "build_dir": str(Path(args.build_dir).resolve()),
            "domain": args.domain,
            "erase": args.erase,
            "cwd": str(Path.cwd()),
        },
    )
    res = _wait_op(c, res)
    _print(res, args.json)
    return 0 if res.get("status") == "done" else 1


def cmd_reset(args: argparse.Namespace) -> int:
    c = Client()
    _print(c.post("/api/reset", {"lease_token": _lease(c, args), "halt": args.halt}), args.json)
    return 0


def cmd_expect(args: argparse.Namespace) -> int:
    c = Client()
    res = c.post(
        "/api/console/expect",
        {
            "lease_token": _lease(c, args),
            "regex": args.regex,
            "timeout_s": args.timeout,
            "since": args.since,
        },
    )
    _print(res, args.json)
    return 0 if res.get("matched") else 1


def cmd_write(args: argparse.Namespace) -> int:
    c = Client()
    _print(
        c.post("/api/console/write", {"lease_token": _lease(c, args), "data": args.data}), args.json
    )
    return 0


def cmd_exec(args: argparse.Namespace) -> int:
    c = Client()
    res = c.post(
        "/api/console/shell",
        {"lease_token": _lease(c, args), "cmd": args.cmd, "timeout_s": args.timeout},
    )
    if args.json:
        _print(res, True)
    else:
        if res.get("untrusted_device_output"):
            print(res["untrusted_device_output"])
        for key in ("error", "hint"):
            if res.get(key):
                print(f"{key}: {res[key]}", file=sys.stderr)
    return 0 if res.get("prompt_seen") and not res.get("error") else 1


def cmd_gdb(args: argparse.Namespace) -> int:
    c = Client()
    body: dict[str, Any] = {"lease_token": _lease(c, args)}
    if args.stop:
        res = c.post("/api/gdb/stop", body)
    else:
        res = c.post("/api/gdb/batch", {**body, "cmds": args.cmds, "timeout_s": args.timeout})
    if args.json or args.stop:
        _print(res, True)
        return 0
    for r in res["results"]:
        print(f"(gdb) {r['cmd']}")
        if r.get("output"):
            print(r["output"])
        if r.get("error"):
            print(f"error: {r['error']}", file=sys.stderr)
            return 1
    return 0


def cmd_hung(args: argparse.Namespace) -> int:
    c = Client()
    res = c.post("/api/gdb/inspect", {"lease_token": _lease(c, args), "build_dir": args.build})
    if args.json:
        _print(res, True)
        return 0
    for f in res.get("backtrace") or []:
        where = f" at {f['file']}:{f['line']}" if f.get("file") else ""
        print(f"#{f['frame']:<2} {f.get('function') or '??'}{where}")
    for t in res.get("threads") or []:
        mark = "*" if t.get("current") else " "
        pend = f"  waits on {t['pended_on']}" if t.get("pended_on") else ""
        print(
            f"{mark} {t.get('name') or t['address']:<20} prio {t['priority']:<4} "
            f"{','.join(t['state'])}{pend}"
        )
    for h in res.get("hints") or []:
        print(f"hint: {h}")
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    c = Client()
    res = c.post(
        "/api/console/read",
        {"lease_token": _lease(c, args), "cursor": args.cursor, "channel": args.channel},
    )
    if args.json:
        _print(res, True)
    else:
        sys.stdout.write(res["untrusted_device_output"])
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    cmd = args.cmd[1:] if args.cmd and args.cmd[0] == "--" else args.cmd
    if not cmd:
        print("usage: arbiter run [--board SEL] -- <command ...>", file=sys.stderr)
        return 2
    c = Client(autostart=True)
    _session(c, args)
    acquired = False
    held = []
    if args.board and not (args.lease or os.environ.get("ARBITER_LEASE")):
        info = c.get(f"/api/sessions/{c.session}")
        held = [le["lease_token"] for le in info.get("leases", []) if "lease_token" in le]
    if len(held) == 1:
        args.lease = held[0]  # keep the board you already hold; don't release it afterwards
    elif args.board and not (args.lease or os.environ.get("ARBITER_LEASE")):
        res = c.post(
            "/api/acquire", {"selector": args.board, "reason": args.reason or " ".join(cmd)[:80]}
        )
        while res["status"] == "queued":
            print(f"queued at position {res['position']} (ticket {res['ticket']})", file=sys.stderr)
            res = c.post("/api/wait", {"ticket": res["ticket"], "wait_s": 45})
        args.lease, acquired = res["lease_token"], True
    try:
        res = c.post(
            "/api/run",
            {
                "lease_token": _lease(c, args),
                "cmd": cmd,
                "cwd": str(Path.cwd()),
                "timeout_s": args.timeout,
            },
        )
        res = _wait_op(c, res)
    finally:
        if acquired:
            try:
                c.post("/api/release", {"lease_token": args.lease})
            except ArbiterError as e:  # e.g. the run left the board unbootable: keep it
                print(f"board kept: {e.message}. {e.hint}", file=sys.stderr)
    for line in res.get("tail", []):
        print(line)
    print(f"\nverdict: {res.get('verdict')}  log: {res.get('log_path')}", file=sys.stderr)
    code = res.get("exit_code")
    return code if isinstance(code, int) else 1


def cmd_console(args: argparse.Namespace) -> int:
    """Live console in the terminal (human). Ctrl-C to quit; --write lets you type."""
    import websockets

    c = Client(admin=True)

    async def main() -> None:
        url = f"{c.ws_base}/api/boards/{args.board}/console?token={c.token}&channel={args.channel}"
        async with websockets.connect(url) as ws:

            async def reader() -> None:
                async for msg in ws:
                    if isinstance(msg, bytes):
                        sys.stdout.buffer.write(msg)
                        sys.stdout.flush()
                    else:
                        print(f"\n[arbiter] {msg}", file=sys.stderr)

            rt = asyncio.create_task(reader())
            if args.write:
                loop = asyncio.get_running_loop()
                while True:
                    line = await loop.run_in_executor(None, sys.stdin.readline)
                    if not line:
                        break
                    await ws.send(line.rstrip("\n").encode() + b"\r\n")
            await rt

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
    return 0


def cmd_bridge(args: argparse.Namespace) -> int:
    """console-bridge: stdin/stdout <-> a board's console. Used as twister's serial_pty."""
    import websockets

    lease = args.lease or os.environ.get("ARBITER_LEASE")
    c = Client()
    if not lease:
        print("console-bridge needs ARBITER_LEASE", file=sys.stderr)
        return 2
    board = args.board or c.post("/api/lease", {"lease_token": lease})["board_id"]

    async def main() -> None:
        url = f"{c.ws_base}/api/boards/{board}/console?token={c.token}&lease={lease}&scrollback=0&channel=console"
        async with websockets.connect(url) as ws:
            loop = asyncio.get_running_loop()

            async def up() -> None:
                while True:
                    data = await loop.run_in_executor(None, os.read, 0, 1024)
                    if not data:
                        return
                    await ws.send(data)

            async def down() -> None:
                async for msg in ws:
                    if isinstance(msg, bytes):
                        os.write(1, msg)

            await asyncio.wait(
                [asyncio.create_task(up()), asyncio.create_task(down())],
                return_when=asyncio.FIRST_COMPLETED,
            )

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
    return 0


def _admin_board(action: str, **extra: Any) -> Command:
    def fn(args: argparse.Namespace) -> int:
        body = dict(extra.items())
        for k in ("reason", "force", "requeue", "on", "data", "action", "mv", "minutes"):
            if hasattr(args, k) and getattr(args, k) is not None:
                body[k] = getattr(args, k)
        _print(Client(admin=True).post(f"/api/admin/boards/{args.board}/{action}", body), args.json)
        return 0

    return fn


def cmd_queue(args: argparse.Namespace) -> int:
    c = Client(admin=True)
    if args.op == "list":
        _print(c.get("/api/state")["queue"], True)
        return 0
    body: dict[str, Any] = {}
    if args.op == "move":
        body["index"] = int(args.value)
    elif args.op == "priority":
        body["priority"] = int(args.value) if str(args.value).isdigit() else args.value
    elif args.op == "unpin":
        args.op, body["pinned"] = "pin", False
    _print(c.post(f"/api/admin/queue/{args.ticket}/{args.op}", body), args.json)
    return 0


def cmd_decide(approve: bool) -> Command:
    def fn(args: argparse.Namespace) -> int:
        _print(
            Client(admin=True).post(f"/api/admin/approvals/{args.id}", {"approve": approve}),
            args.json,
        )
        return 0

    return fn


def cmd_dashboard(args: argparse.Namespace) -> int:
    c = Client(admin=True, autostart=True)
    url = f"{c.base}/?token={c.token}"
    print(url)
    if not args.no_open:
        webbrowser.open(url)
    return 0


def cmd_tui(args: argparse.Namespace) -> int:
    """The board console in this terminal, with keys to take over, pause and see the queue."""
    try:
        import textual  # noqa: F401
    except ImportError:
        raise ArbiterError(
            "NOT_SUPPORTED",
            "the terminal UI needs Textual",
            hint="Install it with: pip install 'arbiter[tui]' (or pip install textual).",
        ) from None
    from .client import ensure_daemon
    from .tui import run

    ensure_daemon()
    return run(args.board, args.channel)


def cmd_hook(args: argparse.Namespace) -> int:
    from .hooks import run_hook

    return run_hook(args.event)


def cmd_discover(args: argparse.Namespace) -> int:
    from .config import load_config, load_toolchain_env
    from .drivers import discovery
    from .starter import nrfutil_devices

    with contextlib.suppress(Exception):
        cfg = load_config()
        if cfg.toolchain_env:
            load_toolchain_env(cfg.toolchain_env)  # nrfutil lives in the NCS toolchain bundle
    probes = discovery.probes()
    nrf = nrfutil_devices()
    if args.json:
        _print({"probes": probes, "nrfutil": nrf}, True)
        return 0
    if not probes:
        print("no debug probes found")
    for i, p in enumerate(probes, 1):
        dev = next((d for d in nrf if discovery.same_serial(d["serial"], p["serial"])), {})
        board = dev.get("board_version")
        platform = discovery.nordic_platform(board) or (board or "").lower() or "?"
        print(f"# {p['kind']} {p['serial']} board={board or '?'}")
        vcoms = {str(x["port"]): x.get("vcom") for x in dev.get("ports", [])}
        for port in p["ports"]:
            vcom = vcoms.get(port["device"])
            where = f"vcom={vcom}" if vcom is not None else f"interface={port['interface']}"
            print(f"#   {port['device']} {where} {port['description']}")
        driver = "nrf" if p["kind"] == "jlink" else ("stm32" if p["kind"] == "stlink" else "west")
        print(
            f'[[board]]\nid = "board-{i}"\ndriver = "{driver}"\nplatform = "{platform}"\n'
            f'probe_serial = "{p["serial"].lstrip("0") or p["serial"]}"'
        )
        for vcom in sorted(v for v in vcoms.values() if v is not None):
            if vcom == 0:
                print('\n[[board.port]]\nrole = "app"\nvcom = 0')
            else:
                name = "tfm" if platform.startswith("nrf91") and vcom == 1 else f"vcom{vcom}"
                print(f'\n[[board.port]]\nrole = "aux"\nname = "{name}"\nvcom = {vcom}')
        print()
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    from . import starter
    from .config_edit import write_atomic

    path = Path(args.config) if args.config else starter.default_path()
    raw, found = starter.detect()
    text = starter.render(raw, found)
    exists = path.exists()
    if args.json:
        _print(
            {"path": str(path), "exists": exists, "probes": found, "config": raw, "toml": text},
            True,
        )
    else:
        print(f"# target: {path}" + (" (exists)" if exists else ""))
        print(text)
    if not args.write:
        if not args.json:
            print(f"# Nothing written. Run `arbiter init --write` to save it to {path}.")
        return 0
    if exists and not args.force:
        print(f"{path} already exists; add --force to replace it (a .bak is kept)", file=sys.stderr)
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, text, keep_backup=exists)
    if not args.json:
        print(f"# Wrote {path}. Start the daemon with `arbiter daemon`.")
    return 0


def cmd_program(args: argparse.Namespace) -> int:
    build = Path(args.build_dir).expanduser().resolve()
    body: dict[str, Any] = {"build_dir": str(build)}
    if args.domain:
        body["domain"] = args.domain
    c = Client(admin=True)
    _print(c.post(f"/api/admin/boards/{args.board}/flash", body), args.json)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from .doctor import FAIL, run_checks

    checks = run_checks(Path(args.config) if args.config else None)
    if args.json:
        _print([c.to_dict() for c in checks], True)
    else:
        for c in checks:
            print(f"{c.status:<4}  {c.name}" + (f": {c.detail}" if c.detail else ""))
    return 1 if any(c.status == FAIL for c in checks) else 0


def cmd_plugins(args: argparse.Namespace) -> int:
    from .plugins import available

    _print(available(), True)
    return 0


def cmd_shell(args: argparse.Namespace) -> int:
    """Shell commands of a board's flashed image, or of a build dir (read locally)."""
    if args.build:
        from .zephyr_shell import from_build

        info = from_build(Path(args.build)).to_dict()
    else:
        if not args.board:
            print("give a board, or --build DIR", file=sys.stderr)
            return 2
        info = Client().get(f"/api/boards/{args.board}/shell")
    if args.json:
        _print(info, True)
        return 0
    if not info.get("available"):
        print(f"no shell commands: {info.get('reason')}")
        return 1

    def show(cmds: list[dict[str, Any]], depth: int) -> None:
        for c in cmds:
            name = "  " * depth + c["name"] + (" <dynamic>" if c.get("dynamic") else "")
            first_line = (c.get("help") or "").strip().splitlines()[:1]
            print(f"{name:<28} {first_line[0] if first_line else ''}".rstrip())
            show(c.get("subcommands") or [], depth + 1)

    show(info.get("commands") or [], 0)
    return 0


def cmd_crash(args: argparse.Namespace) -> int:
    """The last crash seen on a board, symbolised."""
    c = Client()
    board = args.board
    if not board:
        boards = c.get("/api/boards")["boards"]
        if len(boards) != 1:
            print("give a board: " + ", ".join(b["id"] for b in boards), file=sys.stderr)
            return 2
        board = boards[0]["id"]
    info = c.get(f"/api/boards/{board}/crash", history="1" if args.history else "")
    if args.json:
        _print(info, True)
        return 0
    crash = info.get("crash")
    if not crash:
        print(info.get("hint") or "no crash")
        return 0
    print(f"{board}: {crash['summary']}")
    for reg in ("pc", "lr"):
        sym = crash["symbols"].get(reg)
        if sym:
            print(f"  {reg:<3} {sym['address']}  {sym['text']}")
        elif reg in crash["registers"]:
            print(f"  {reg:<3} {crash['registers'][reg]}")
    for i, sym in enumerate(crash["symbols"].get("call_trace") or []):
        print(f"  #{i:<2} {sym['address']}  {sym['text']}")
    core = crash.get("coredump_report") or {}
    for f in core.get("backtrace") or []:
        where = f" at {f['file']}:{f['line']}" if f.get("file") else ""
        print(f"  bt#{f['frame']:<2} {f.get('function') or '??'}({f.get('args') or ''}){where}")
    if core.get("error"):
        print(f"  coredump: {core['error']}")
    for line in crash.get("details") or []:
        print(f"  {line}")
    for hint in crash.get("hints") or []:
        print(f"hint: {hint}")
    for e in info.get("earlier") or []:
        print(f"earlier: {e['summary']}")
    return 1


def cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp_server import main

    main()
    return 0


# ------------------------------------------------------------------ parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="arbiter", description="Share Zephyr dev boards between AI agents and you."
    )
    p.add_argument("--json", action="store_true", help="print JSON")
    p.add_argument("--label", help="label for this CLI session")
    sub = p.add_subparsers(dest="command", required=True)

    def add(name: str, fn: Command, help_text: str) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help_text)
        sp.set_defaults(fn=fn)
        sp.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        return sp

    sp = add("daemon", cmd_daemon, "run arbiterd in the foreground")
    sp.add_argument("--config")
    sp.add_argument("--port", type=int)
    sp.add_argument("--host")
    add("mcp", cmd_mcp, "run the stdio MCP server (what agents launch)")
    add("status", cmd_status, "boards, queue and approvals")
    add("discover", cmd_discover, "list probes and print config snippets")
    add("plugins", cmd_plugins, "list available drivers and power devices")
    sp = add("doctor", cmd_doctor, "check the config, tools, probes and daemon")
    sp.add_argument("--config")
    sp = add("shell-cmds", cmd_shell, "shell commands of a board's flashed image")
    sp.add_argument("board", nargs="?")
    sp.add_argument("--build", help="read them from this build dir instead (no daemon needed)")
    sp = add("crash", cmd_crash, "the last crash seen on a board, with file:line")
    sp.add_argument("board", nargs="?")
    sp.add_argument("--history", action="store_true", help="also list earlier crashes")
    sp = add("acquire", cmd_acquire, "ask for a board (exit 75 while queued)")
    sp.add_argument("selector")
    sp.add_argument("--reason", default="")
    sp.add_argument("--priority")
    sp.add_argument("--wait", type=float, default=0, help="seconds to wait (max 45)")
    sp.add_argument("--block", type=float, help="keep waiting up to this many seconds")
    sp = add("wait", cmd_wait, "wait for a queued ticket")
    sp.add_argument("ticket")
    sp.add_argument("--wait", type=float, default=45)
    for name, fn, h in (
        ("release", cmd_release, "release your board"),
        ("read", cmd_read, "read console output"),
    ):
        sp = add(name, fn, h)
        sp.add_argument("--lease")
        if name == "release":
            sp.add_argument(
                "--force", action="store_true", help="release a board left unbootable anyway"
            )
        if name == "read":
            sp.add_argument("--cursor", type=int)
            sp.add_argument("--channel", help="console (default), all, rtt, uart:app, ...")
    sp = add("flash", cmd_flash, "flash a build dir to your board")
    sp.add_argument("build_dir")
    sp.add_argument("--domain")
    sp.add_argument("--erase", action="store_true")
    sp.add_argument("--lease")
    sp = add("reset", cmd_reset, "reset your board")
    sp.add_argument("--halt", action="store_true")
    sp.add_argument("--lease")
    sp = add("expect", cmd_expect, "wait for a regex on the console")
    sp.add_argument("regex")
    sp.add_argument("--timeout", type=float, default=10)
    sp.add_argument("--since", default="mark")
    sp.add_argument("--lease")
    sp = add("exec", cmd_exec, "run one shell command on your board and print its output")
    sp.add_argument("cmd")
    sp.add_argument("--timeout", type=float, default=10)
    sp.add_argument("--lease")
    sp = add("gdb", cmd_gdb, "run gdb commands on your board: arbiter gdb bt 'print x'")
    sp.add_argument("cmds", nargs="*")
    sp.add_argument("--timeout", type=float, default=10)
    sp.add_argument("--stop", action="store_true", help="detach gdb and let the board run")
    sp.add_argument("--lease")
    sp = add("hung", cmd_hung, "halt your board, show where it is stuck, and let it run on")
    sp.add_argument("--build", help="the flashed build dir, if arbiter didn't flash it")
    sp.add_argument("--lease")
    sp = add("write", cmd_write, "send a line to the console")
    sp.add_argument("data")
    sp.add_argument("--lease")
    sp = add(
        "run",
        cmd_run,
        "run a test command against a board: arbiter run --board nrf9161dk -- west twister ...",
    )
    sp.add_argument("--board", help="acquire this board (or platform) for the run")
    sp.add_argument("--reason")
    sp.add_argument("--lease")
    sp.add_argument("--timeout", type=float, default=1800)
    sp.add_argument("cmd", nargs=argparse.REMAINDER)
    sp = add("console", cmd_console, "live console of a board (human)")
    sp.add_argument("board")
    sp.add_argument("--write", action="store_true", help="type lines to the board")
    sp.add_argument("--channel", default="all", help="all, console, rtt, uart:app, uart:tfm, ...")
    sp = add(
        "console-bridge", cmd_bridge, "stdin/stdout bridge to a board console (twister serial_pty)"
    )
    sp.add_argument("--board")
    sp.add_argument("--lease")
    sp = add("hook", cmd_hook, "agent hook entry point")
    sp.add_argument(
        "event", choices=["session-start", "pre-tool-use", "post-tool-use", "session-end"]
    )
    sp = add("init", cmd_init, "detect boards and draft a config.toml")
    sp.add_argument("--write", action="store_true", help="save the draft")
    sp.add_argument("--force", action="store_true", help="replace an existing config")
    sp.add_argument("--config", help="where to write (default: the daemon's config path)")
    sp = add("program", cmd_program, "flash a free board as the human")
    sp.add_argument("board")
    sp.add_argument("build_dir")
    sp.add_argument("--domain")
    sp = add("dashboard", cmd_dashboard, "open the dashboard")
    sp.add_argument("--no-open", action="store_true")
    sp = add("tui", cmd_tui, "the board console in this terminal (needs the tui extra)")
    sp.add_argument("board", nargs="?", help="board to show first")
    sp.add_argument("--channel", default="all", help="console channel (default: all)")
    # human controls
    for action, h in (
        ("pause", "pause the agent on a board"),
        ("resume", "give the board back"),
        ("take", "take the board (revokes the lease)"),
        ("revoke", "end the lease"),
        ("hold-release", "release a board you hold"),
        ("maintenance", "take a board out of service"),
        ("send", "type a line to a board as the human"),
        ("supply", "power on/off/cycle as the human"),
        ("extend", "extend the lease on a board"),
    ):
        api_action = {"hold-release": "release", "send": "write", "supply": "power"}.get(
            action, action
        )
        sp = add(action, _admin_board(api_action), h)
        sp.add_argument("board")
        if action in ("pause", "take", "revoke"):
            sp.add_argument("--reason")
        if action == "pause":
            sp.add_argument("--force", action="store_true", default=None)
        if action == "revoke":
            sp.add_argument("--no-requeue", dest="requeue", action="store_false", default=None)
        if action == "maintenance":
            sp.add_argument("--off", dest="on", action="store_false", default=True)
        if action == "send":
            sp.add_argument("data")
        if action == "supply":
            sp.add_argument("action", choices=["on", "off", "cycle", "set_voltage"])
            sp.add_argument("--mv", type=int)
        if action == "extend":
            sp.add_argument("--minutes", type=float, default=15)
    sp = add("queue", cmd_queue, "show or edit the queue")
    sp.add_argument(
        "op",
        choices=["list", "move", "priority", "pin", "unpin", "cancel"],
        nargs="?",
        default="list",
    )
    sp.add_argument("ticket", nargs="?")
    sp.add_argument("value", nargs="?")
    sp = add("approve", cmd_decide(True), "approve an agent's request")
    sp.add_argument("id")
    sp = add("deny", cmd_decide(False), "decline an agent's request")
    sp.add_argument("id")
    return p


def _utf8_stdio() -> None:
    # Windows consoles default to a legacy code page that can't print U+FFFD, which is what
    # a garbage UART byte at reset decodes to.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(Exception):
                reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _utf8_stdio()
    args = build_parser().parse_args(argv)
    try:
        return int(args.fn(args) or 0)
    except ArbiterError as e:
        print(json.dumps(e.to_dict(), indent=2), file=sys.stderr)
        return e.exit_code


if __name__ == "__main__":
    sys.exit(main())
