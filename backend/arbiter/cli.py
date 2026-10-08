"""`arbiter` command line: the daemon, agent commands (mirroring the MCP tools,
with exit codes 0 / 75 queued / 76 paused / 77 revoked) and human commands."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import subprocess
import sys
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .client import Client
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
    and remember it in the state dir, keyed by the parent shell."""
    if c.session:
        return c.session
    from .config import state_dir

    cache = state_dir() / "cli-sessions.json"
    key = os.environ.get("ARBITER_EXTERNAL_ID") or f"ppid-{os.getppid()}"
    try:
        known = json.loads(cache.read_text())
    except (OSError, ValueError):
        known = {}
    s = c.post(
        "/api/sessions",
        {
            "agent_kind": "cli",
            "external_id": key,
            "label": args.label or f"cli {Path.cwd().name}",
            "cwd": str(Path.cwd()),
        },
    )
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
    tokens = [le["lease_token"] for le in info.get("leases", []) if "lease_token" in le]
    if len(tokens) == 1:
        return str(tokens[0])
    if not tokens:
        raise ArbiterError(
            "LEASE_UNKNOWN", "you hold no board", hint="Run `arbiter acquire <board>` first."
        )
    raise ArbiterError("BAD_REQUEST", "you hold several boards; pass --lease")


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
    _print(c.post("/api/release", {"lease_token": _lease(c, args)}), args.json)
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


def cmd_read(args: argparse.Namespace) -> int:
    c = Client()
    res = c.post("/api/console/read", {"lease_token": _lease(c, args), "cursor": args.cursor})
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
    if args.board and not (args.lease or os.environ.get("ARBITER_LEASE")):
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
            c.post("/api/release", {"lease_token": args.lease})
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


def cmd_hook(args: argparse.Namespace) -> int:
    from .hooks import run_hook

    return run_hook(args.event)


def cmd_discover(args: argparse.Namespace) -> int:
    from .drivers import discovery

    probes = discovery.probes()
    try:
        out = subprocess.run(
            ["nrfutil", "device", "list", "--json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
            stdin=subprocess.DEVNULL,
        ).stdout
        nrf = {d["serial"]: d for d in discovery.parse_nrfutil_list(out)}
    except (OSError, subprocess.SubprocessError):
        nrf = {}
    if args.json:
        _print({"probes": probes, "nrfutil": list(nrf.values())}, True)
        return 0
    if not probes:
        print("no debug probes found")
    for i, p in enumerate(probes, 1):
        board = (nrf.get(p["serial"]) or {}).get("board_version") or "?"
        print(f"# {p['kind']} {p['serial']} board={board}")
        for port in p["ports"]:
            print(f"#   {port['device']} interface={port['interface']} {port['description']}")
        driver = "nrf" if p["kind"] == "jlink" else ("stm32" if p["kind"] == "stlink" else "west")
        print(
            f'[[board]]\nid = "board-{i}"\ndriver = "{driver}"\nplatform = "{(board or "").lower()}"\n'
            f'probe_serial = "{p["serial"]}"\n'
        )
    return 0


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
    sp = add("shell-cmds", cmd_shell, "shell commands of a board's flashed image")
    sp.add_argument("board", nargs="?")
    sp.add_argument("--build", help="read them from this build dir instead (no daemon needed)")
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
        if name == "read":
            sp.add_argument("--cursor", type=int)
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
    sp = add("dashboard", cmd_dashboard, "open the dashboard")
    sp.add_argument("--no-open", action="store_true")
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.fn(args) or 0)
    except ArbiterError as e:
        print(json.dumps(e.to_dict(), indent=2), file=sys.stderr)
        return e.exit_code


if __name__ == "__main__":
    sys.exit(main())
