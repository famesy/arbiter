"""nRF91 modem helpers: AT commands through the app's console, an LTE status summary,
and turning a raw modem trace into a PcapNG file.

AT commands reach the modem through the app, in one of two ways:
* the AT shell (`CONFIG_AT_SHELL=y`, or NCS samples that add an `at` shell command):
  arbiter runs `at <command>` with shell_exec;
* a raw AT console (the at_client sample, Serial LTE Modem): arbiter writes the command
  line and waits for OK / ERROR / +CME ERROR.

Modem traces (snippet `nrf91-modem-trace-uart`) come out of UART1 at 1 Mbaud with flow
control, which is VCOM1 on the nRF91 DKs. arbiter captures the raw bytes to a file and
converts them with `nrfutil trace lte` when it is installed."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

FINAL_RX = r"(?m)^(OK|ERROR|\+CME ERROR: ?\d+|\+CMS ERROR: ?\d+)\s*$"
# Commands that would wipe the modem's settings or credentials: the human decides.
REFUSED = re.compile(r"^AT%XFACTORYRESET|^AT%CMNG=3|^AT%XMODEMUUID=", re.IGNORECASE)

CFUN = {
    0: "power off (modem off)",
    1: "normal (LTE and GNSS on)",
    2: "receive only",
    4: "flight mode (radio off)",
    20: "LTE off",
    21: "LTE on",
    30: "GNSS off",
    31: "GNSS on",
    40: "SIM off",
    41: "SIM on",
}
CEREG = {
    0: "not registered, not searching",
    1: "registered, home network",
    2: "not registered, searching",
    3: "registration denied",
    4: "unknown (out of coverage?)",
    5: "registered, roaming",
    90: "not registered, SIM failure",
}
ACT = {7: "LTE-M", 9: "NB-IoT"}

STATUS_COMMANDS = [
    "AT+CFUN?",
    "AT+CEREG?",
    "AT%XMONITOR",
    "AT%XSYSTEMMODE?",
    "AT+CGDCONT?",
    "AT%XICCID",
    "AT+CGMR",
]


def check_at(cmd: str) -> str:
    cmd = cmd.strip()
    if not re.match(r"(?i)^AT", cmd) or "\n" in cmd or "\r" in cmd:
        raise ValueError("an AT command is one line starting with AT")
    if REFUSED.match(cmd):
        raise PermissionError(f"{cmd.split('=')[0]} changes the modem's identity or wipes it")
    return cmd


def response(lines: list[str]) -> dict[str, Any]:
    """Split modem output into result lines and the final OK / ERROR."""
    body, final = [], None
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if re.fullmatch(r"OK|ERROR|\+CM[ES] ERROR: ?\d+", line):
            final = line
            break
        body.append(line)
    return {"ok": final == "OK", "final": final, "lines": body}


def _fields(line: str, prefix: str) -> list[str] | None:
    if not line.startswith(prefix):
        return None
    out, cur, quoted = [], "", False
    for ch in line[len(prefix) :].strip():
        if ch == '"':
            quoted = not quoted
        elif ch == "," and not quoted:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    out.append(cur.strip())
    return out


def _int(s: str | None) -> int | None:
    if not s:
        return None
    for base in (0, 10):  # base 10 for zero-padded numbers like "08"
        try:
            return int(s, base)
        except ValueError:
            pass
    return None


def summarize(replies: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Turn the STATUS_COMMANDS replies into a short LTE status, with hints."""
    out: dict[str, Any] = {}
    hints: list[str] = []

    def first(cmd: str, prefix: str) -> list[str] | None:
        for line in replies.get(cmd, {}).get("lines", []):
            f = _fields(line, prefix)
            if f is not None:
                return f
        return None

    if f := first("AT+CFUN?", "+CFUN:"):
        mode = _int(f[0])
        out["functional_mode"] = {"value": mode, "meaning": CFUN.get(mode or -1, "other")}
        if mode in (0, 4, 20):
            hints.append("The radio is off: the app hasn't connected (lte_lc_connect / AT+CFUN=1).")
    if f := first("AT+CEREG?", "+CEREG:"):
        stat = _int(f[1]) if len(f) > 1 else None
        out["registration"] = {"value": stat, "meaning": CEREG.get(stat or -1, "other")}
        if stat == 2:
            hints.append(
                "Searching: check the antenna, SIM, coverage and that the system mode (LTE-M / "
                "NB-IoT) and bands match the network."
            )
        elif stat == 3:
            hints.append("Registration denied: the SIM may be inactive or not allowed here.")
        elif stat == 90:
            hints.append("SIM failure: is a SIM inserted and the right SIM slot selected?")
    if f := first("AT%XMONITOR", "%XMONITOR:"):
        # reg_status,full_name,short_name,plmn,tac,AcT,band,cell_id,phys_cell_id,EARFCN,rsrp,snr,...
        names = ["reg_status", "operator", "operator_short", "plmn", "tac", "act", "band",
                 "cell_id", "phys_cell_id", "earfcn", "rsrp", "snr"]  # fmt: skip
        mon = dict(zip(names, f, strict=False))
        cell: dict[str, Any] = {
            k: mon[k] for k in ("operator", "plmn", "tac", "cell_id") if mon.get(k)
        }
        act = _int(mon.get("act"))
        if act is not None:
            cell["act"] = ACT.get(act, str(act))
        for key in ("band", "earfcn", "phys_cell_id"):
            if _int(mon.get(key)) is not None:
                cell[key] = _int(mon.get(key))
        rsrp, snr = _int(mon.get("rsrp")), _int(mon.get("snr"))
        if rsrp is not None and rsrp != 255:
            cell["rsrp_dbm"] = rsrp - 140
            if rsrp - 140 < -115:
                hints.append(f"Weak signal (RSRP {rsrp - 140} dBm): expect retries and high power.")
        if snr is not None and snr != 127:
            cell["snr_db"] = snr - 24
        if cell:
            out["cell"] = cell
    if f := first("AT%XSYSTEMMODE?", "%XSYSTEMMODE:"):
        bits = [_int(x) for x in f[:4]]
        modes = [n for n, b in zip(("LTE-M", "NB-IoT", "GNSS"), bits[:3], strict=False) if b]
        out["system_mode"] = modes
    pdn = []
    for line in replies.get("AT+CGDCONT?", {}).get("lines", []):
        f = _fields(line, "+CGDCONT:")
        if f and len(f) >= 3:
            pdn.append(
                {"cid": _int(f[0]), "type": f[1], "apn": f[2], "ip": f[3] if len(f) > 3 else ""}
            )
    if pdn:
        out["pdn"] = pdn
    if f := first("AT%XICCID", "%XICCID:"):
        out["iccid"] = f[0]
    if fw := replies.get("AT+CGMR", {}).get("lines"):
        out["modem_firmware"] = fw[0]
    failed = [c for c, r in replies.items() if not r.get("ok")]
    if failed:
        out["failed_commands"] = failed
    if hints:
        out["hints"] = hints
    return out


def convert_trace(raw: Path) -> dict[str, Any]:
    """raw modem trace -> PcapNG with nrfutil trace lte, when nrfutil has the trace command."""
    nrfutil = shutil.which("nrfutil")
    if not nrfutil:
        return {"converted": False, "hint": "Install nrfutil (and `nrfutil install trace`)."}
    out = raw.with_suffix(".pcapng")
    try:
        p = subprocess.run(
            [nrfutil, "trace", "lte", "--input-file", str(raw), "--output-pcapng", str(out)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return {"converted": False, "error": str(e)}
    if p.returncode != 0 or not out.exists():
        tail = (p.stderr or p.stdout).strip().splitlines()[-3:]
        return {"converted": False, "error": " | ".join(tail) or f"exit {p.returncode}"}
    return {"converted": True, "pcapng": str(out)}
