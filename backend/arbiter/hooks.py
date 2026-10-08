"""`arbiter hook <event>`: one executable for Claude Code and Codex hooks.

Reads the hook's JSON payload on stdin and prints the hook's JSON answer.
Events: session-start, pre-tool-use, post-tool-use, session-end. Hooks are
guardrails for cooperative agents; the daemon's ownership of the ports is the
real exclusivity (design doc §11)."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from .client import Client, ensure_daemon
from .errors import ArbiterError

DENY = [
    (
        r"\bwest\s+(flash|debug|debugserver|attach|rtt)\b",
        "use the arbiter `flash` tool (or `arbiter flash`)",
    ),
    (
        r"\bwest\s+twister\b.*--device-testing|\btwister\b.*--device-testing",
        "run hardware tests through the arbiter `run` tool (or `arbiter run -- ...`)",
    ),
    (r"\bnrfutil\s+device\b", "use the arbiter tools; nrfutil device would grab the shared probe"),
    (r"\bnrfjprog\b", "use the arbiter tools instead of nrfjprog"),
    (
        r"\bJLink(Exe|GDBServer\w*|RTTLogger\w*|RTTClient\w*)?(\.exe)?\b",
        "use the arbiter tools instead of J-Link tools",
    ),
    (r"\bopenocd\b", "use the arbiter tools instead of openocd"),
    (r"\bpyocd\b", "use the arbiter tools instead of pyocd"),
    (r"\bSTM32_Programmer_CLI\b", "use the arbiter tools instead of STM32_Programmer_CLI"),
    (r"\bprobe-rs\b", "use the arbiter tools instead of probe-rs"),
    (
        r"/dev/tty(ACM|USB)\d*|/dev/serial/by-id|/dev/cu\.usbmodem",
        "read the console with console_read/serial_expect",
    ),
    (
        r"\b(minicom|picocom|screen\s+/dev|putty|plink)\b",
        "read the console with console_read/serial_expect",
    ),
    (r"\barbiter[/\\]admin\.json\b|ARBITER_ADMIN_TOKEN", "the admin token is for the human only"),
]
ALLOW_PREFIX = re.compile(r"^\s*(arbiter|python3?\s+-m\s+arbiter)\b")


def _out(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj))
    sys.stdout.flush()


def _payload() -> dict[str, Any]:
    try:
        data = sys.stdin.read()
        return json.loads(data) if data.strip() else {}
    except ValueError:
        return {}


def check_command(cmd: str) -> str | None:
    """Return a deny reason for a shell command, or None to allow it."""
    if ALLOW_PREFIX.match(cmd):
        return None
    for pat, why in DENY:
        if re.search(pat, cmd):
            return why
    return None


def _queue_hint(ext: str | None) -> str:
    try:
        c = Client()
        st = c.get("/api/state")
    except ArbiterError:
        return ""
    lines = []
    for b in st["boards"]:
        holder = b["lease"]["holder"] if b.get("lease") else None
        lines.append(f"{b['id']}: {b['state']}" + (f" (held by {holder})" if holder else ""))
    q = len(st["queue"])
    return " Boards: " + "; ".join(lines) + f". Queue length {q}."


def pre_tool_use(p: dict[str, Any]) -> None:
    tool = p.get("tool_name") or p.get("tool") or ""
    ti = p.get("tool_input") or {}
    cmd = ti.get("command") if isinstance(ti, dict) else None
    if tool not in ("Bash", "shell", "exec_command", "local_shell") or not isinstance(cmd, str):
        return
    why = check_command(cmd)
    if not why:
        return
    reason = (
        f"arbiter: hardware is shared and brokered; {why}. Acquire a board first with acquire_board."
        + _queue_hint(p.get("session_id"))
    )
    _out(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            },
            "decision": "block",
            "reason": reason,
        }
    )


def session_start(p: dict[str, Any]) -> None:
    ext = p.get("session_id")
    try:
        ensure_daemon()
        c = Client()
        cwd = p.get("cwd") or str(Path.cwd())
        s = c.post(
            "/api/sessions",
            {
                "agent_kind": os.environ.get("ARBITER_AGENT_KIND", "claude"),
                "external_id": ext,
                "cwd": cwd,
                "label": f"{os.environ.get('ARBITER_AGENT_KIND', 'claude')} {Path(cwd).name}",
            },
        )
    except ArbiterError as e:
        _out(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": f"arbiter is unavailable: {e.message}",
                }
            }
        )
        return
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if env_file:
        try:
            with Path(env_file).open("a") as f:
                f.write(f"export ARBITER_SESSION={s['id']}\n")
        except OSError:
            pass
    _out(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "Shared dev boards are brokered by arbiter. Use its MCP tools "
                "(acquire_board, flash, serial_expect, release_board) or the "
                "`arbiter` CLI; never touch probes or serial ports directly.",
            }
        }
    )


def post_tool_use(p: dict[str, Any]) -> None:
    ext = p.get("session_id")
    if not ext:
        return
    try:
        res = Client().get(f"/api/sessions/by-external/{ext}/inbox")
    except ArbiterError:
        return
    items = res.get("items", [])
    if not items:
        return
    text = "arbiter notices: " + " ".join(i["text"] for i in items)
    _out({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}})


def session_end(p: dict[str, Any]) -> None:
    ext = p.get("session_id")
    if not ext:
        return
    try:
        c = Client()
        res = c.get(f"/api/sessions/by-external/{ext}/inbox")
        if res.get("session"):
            c.post(f"/api/sessions/{res['session']}/end", {"release": True})
    except ArbiterError:
        pass


HOOKS = {
    "pre-tool-use": pre_tool_use,
    "session-start": session_start,
    "post-tool-use": post_tool_use,
    "session-end": session_end,
}


def run_hook(event: str) -> int:
    fn = HOOKS.get(event)
    if fn is None:
        sys.stderr.write(f"unknown hook event {event!r}; one of {sorted(HOOKS)}\n")
        return 2
    p: dict[str, Any] = _payload()
    try:
        fn(p)
    except Exception as e:  # a hook must never break the agent
        sys.stderr.write(f"arbiter hook {event}: {e}\n")
    return 0
