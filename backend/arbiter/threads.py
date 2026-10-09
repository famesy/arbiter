"""Thread and stack health from what Zephyr prints: the kernel shell's `kernel thread list`
(older Zephyr: `kernel threads`) and the thread analyzer's "Thread analyze:" report
(CONFIG_THREAD_ANALYZER). Flags threads close to overflowing their stack and names the
Kconfig option that sizes the well-known ones."""

from __future__ import annotations

import re
from typing import Any

WARN_PCT = 80

# Kernel and subsystem threads whose stack size is a Kconfig option.
STACK_OPTIONS = {
    "main": "CONFIG_MAIN_STACK_SIZE",
    "sysworkq": "CONFIG_SYSTEM_WORKQUEUE_STACK_SIZE",
    "idle": "CONFIG_IDLE_STACK_SIZE",
    "logging": "CONFIG_LOG_PROCESS_THREAD_STACK_SIZE",
    "shell_uart": "CONFIG_SHELL_STACK_SIZE",
    "shell_rtt": "CONFIG_SHELL_STACK_SIZE",
    "ISR0": "CONFIG_ISR_STACK_SIZE",
    "BT RX": "CONFIG_BT_RX_STACK_SIZE",
    "BT RX WQ": "CONFIG_BT_RX_STACK_SIZE",
    "BT HCI RX": "CONFIG_BT_RX_STACK_SIZE",
    "BT TX": "CONFIG_BT_HCI_TX_STACK_SIZE",
    "thread_analyzer": "CONFIG_THREAD_ANALYZER_AUTO_STACK_SIZE",
    "net_mgmt": "CONFIG_NET_MGMT_EVENT_STACK_SIZE",
    "rx_q[0]": "CONFIG_NET_RX_STACK_SIZE",
    "tx_q[0]": "CONFIG_NET_TX_STACK_SIZE",
}

_HEAD = re.compile(r"^\s*(\*?)\s*(0x[0-9a-fA-F]+)\s+(.*?)\s*$")
_PRIO = re.compile(r"priority:\s*(-?\d+)")
_STATE = re.compile(r"state:\s*([^,]*)")
_USAGE = re.compile(r"stack size (\d+), unused (\d+), usage (\d+) / (\d+) \((\d+) ?%\)")
_NO_INFO = re.compile(r"[Uu]nable to determine unused stack size")
_ANALYZE = re.compile(
    r"^\s*(.+?)\s*:\s*STACK: unused (\d+) usage (\d+) / (\d+) \((\d+) ?%\)(?:; CPU: (\d+) ?%)?"
)


def parse_thread_list(text: str) -> tuple[list[dict[str, Any]], bool]:
    """Threads from `kernel thread list` / `kernel threads`, and whether stack use was
    unknown (CONFIG_INIT_STACKS off)."""
    threads: list[dict[str, Any]] = []
    unknown = False
    cur: dict[str, Any] | None = None
    for line in text.splitlines():
        m = _HEAD.match(line)
        if m and not line.startswith((" " * 4, "\t")):
            cur = {"name": m.group(3) or "", "addr": m.group(2)}
            if m.group(1):
                cur["current"] = True
            threads.append(cur)
            continue
        if cur is None:
            continue
        if p := _PRIO.search(line):
            cur["priority"] = int(p.group(1))
        if (s := _STATE.search(line)) and "state" not in cur:
            cur["state"] = s.group(1).strip() or "ready"
        if u := _USAGE.search(line):
            cur.update(_stack(int(u.group(1)), int(u.group(3))))
        elif _NO_INFO.search(line):
            unknown = True
    return threads, unknown


def parse_analyzer(text: str) -> list[dict[str, Any]]:
    """Threads from the last "Thread analyze:" report in `text`."""
    idx = text.rfind("Thread analyze:")
    if idx < 0:
        return []
    threads = []
    for raw in text[idx:].splitlines()[1:]:
        line = re.sub(r"^\[[\d:.,]+\]\s*(<\w+>\s*\w+:\s*)?", "", raw)  # log prefix
        m = _ANALYZE.match(line)
        if m:
            t: dict[str, Any] = {"name": m.group(1)}
            t.update(_stack(int(m.group(4)), int(m.group(3))))
            if m.group(6) is not None:
                t["cpu_pct"] = int(m.group(6))
            threads.append(t)
        elif threads and line.strip() and not re.search(r"CPU cycles|^\s*:", line):
            break
    return threads


def _stack(size: int, used: int) -> dict[str, Any]:
    return {
        "stack_size": size,
        "stack_used": used,
        "stack_pct": round(100 * used / size) if size else None,
    }


def assess(threads: list[dict[str, Any]], warn_pct: int = WARN_PCT) -> list[str]:
    """Warnings for threads near their stack limit."""
    out = []
    for t in sorted(threads, key=lambda t: -(t.get("stack_pct") or 0)):
        pct = t.get("stack_pct")
        if pct is None or pct < warn_pct:
            continue
        name = t["name"] or t.get("addr", "?")
        opt = STACK_OPTIONS.get(name)
        fix = f"raise {opt}" if opt else "give it a bigger K_THREAD_STACK_DEFINE / stack size"
        level = "has used all of" if pct >= 100 else f"has used {pct} % of"
        out.append(f"{name} {level} its {t['stack_size']} B stack (peak so far): {fix}.")
    return out
