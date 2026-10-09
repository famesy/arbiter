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

# Tools that run a shell command from tool_input["command"]: Claude Code (Bash, and
# PowerShell on Windows) and Codex (shell, exec_command, local_shell).
SHELL_TOOLS = {"Bash", "PowerShell", "shell", "exec_command", "local_shell"}

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
# CLI commands only the human may run: they act with the admin token, and `dashboard`
# prints it. Agents use the MCP tools or the agent commands (acquire, flash, read, ...).
HUMAN_ONLY = {
    "dashboard",
    "console",
    "pause",
    "resume",
    "take",
    "revoke",
    "hold-release",
    "maintenance",
    "send",
    "supply",
    "extend",
    "program",
    "approve",
    "deny",
}
QUEUE_EDITS = {"move", "priority", "pin", "unpin", "cancel"}
SEGMENT_SPLIT = re.compile(r"&&|\|\||[;|&\n]|\$\(|`")
FILE_TOOLS = {"Read", "Edit", "Write", "MultiEdit", "Grep", "Glob", "NotebookEdit"}


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
    """Return a deny reason for a shell command, or None to allow it. Each part of a
    chained command (`a && b; c | d`) is checked on its own."""
    for seg in SEGMENT_SPLIT.split(cmd):
        why = _check_segment(seg.strip())
        if why:
            return why
    return None


def _check_segment(seg: str) -> str | None:
    if ALLOW_PREFIX.match(seg):
        return _check_arbiter(seg)
    for pat, why in DENY:
        if re.search(pat, seg):
            return why
    return None


def _check_arbiter(seg: str) -> str | None:
    import shlex

    try:
        words = shlex.split(seg, posix=os.name != "nt")
    except ValueError:
        words = seg.split()
    words = words[3:] if len(words) > 2 and words[1] == "-m" else words[1:]
    args = []
    skip = False
    for w in words:  # drop global flags: --json, --label X
        if skip:
            skip = False
        elif w == "--label":
            skip = True
        elif not w.startswith("-"):
            args.append(w)
    if not args:
        return None
    sub = args[0]
    if sub in HUMAN_ONLY or (sub == "queue" and len(args) > 1 and args[1] in QUEUE_EDITS):
        return f"`arbiter {sub}` is for the human only; ask them, or use the agent tools"
    if sub == "init" and "--force" in words:
        return "replacing an existing arbiter config is for the human only; ask them to run it"
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


def check_file_tool(ti: dict[str, Any]) -> str | None:
    """Deny reading or editing arbiter's admin token file with the agent's file tools."""
    for k in ("file_path", "path", "pattern", "notebook_path"):
        v = ti.get(k)
        if isinstance(v, str) and re.search(r"admin\.json\b", v):
            return "the admin token is for the human only"
    return None


def pre_tool_use(p: dict[str, Any]) -> None:
    tool = p.get("tool_name") or p.get("tool") or ""
    ti = p.get("tool_input") or {}
    if not isinstance(ti, dict):
        return
    cmd = ti.get("command")
    if tool in FILE_TOOLS:
        why = check_file_tool(ti)
    elif tool in SHELL_TOOLS and isinstance(cmd, str):
        why = check_command(cmd)
    else:
        return
    if not why:
        return
    if "human only" in why:
        reason = f"arbiter: {why}."
    else:
        reason = (
            f"arbiter: hardware is shared and brokered; {why}. Acquire a board first with "
            "acquire_board." + _queue_hint(p.get("session_id"))
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
            "systemMessage": _startup_note(c),
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "Shared dev boards are brokered by arbiter. Use its MCP tools "
                "(acquire_board, flash, serial_expect, release_board) or the "
                "`arbiter` CLI; never touch probes or serial ports directly.",
            },
        }
    )


def _startup_note(c: Client) -> str:
    """One line for the human: where the dashboard is (no token in it), or how to set up."""
    from .config import load_config

    try:
        configured = load_config().path is not None
    except Exception:
        configured = True  # a broken config is reported by the daemon and `arbiter doctor`
    if not configured:
        return "arbiter: no boards configured yet; run /arbiter:setup"
    return f"arbiter: dashboard at {c.base} (open with `arbiter dashboard`)"


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
