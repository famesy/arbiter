# arbiter backend

`arbiterd` is the broker that lets several AI coding agents (Claude Code, Codex) and
you share one or two physical dev boards. It is the only process that touches the
debug probes and serial ports. Agents ask it for a board, wait in a queue, then
flash, read the console, run tests and measure current through it. You can watch,
type into the console, reorder the queue, pause an agent or take the board at any
time.

See [docs/architecture.md](../docs/architecture.md) for the design.

## What's here

| Part | Module | What it does |
| --- | --- | --- |
| Daemon | `arbiter.daemon`, `arbiter.service` | Owns boards, consoles, power and running operations |
| Queue | `arbiter.scheduler` | Tickets, leases, priorities, pause and preemption |
| Consoles | `arbiter.console` | One named channel per output (`uart:app`, `uart:tfm`, `rtt`, ...), RTT/UART auto-detect |
| Drivers | `arbiter.drivers` | `nrf`, `stm32`, `west`, `native_sim`, `sim`, `command` |
| Power | `arbiter.power` | PPK2, simulated supply, native_sim, your own script |
| Plugins | `arbiter.plugins` | Command overrides, command-only boards, entry-point plugins |
| Agent API | `arbiter.mcp_server` | stdio MCP server agents launch (`arbiter mcp`) |
| Human API | `arbiter.api` | HTTP and WebSocket API for the dashboard |
| Dashboard | `arbiter/dashboard/` | Web page the daemon serves at `/` (plain HTML/JS, no build step) |
| CLI | `arbiter.cli` | Agent and human commands, hooks, twister console bridge |

Runs on Linux and Windows (Python 3.11+). macOS should work but isn't tested.
`native_sim` boards need Linux; on Windows run the daemon inside WSL.

## Install

```sh
pip install -e backend            # add [rtt] for RTT, [ppk2] for a Nordic PPK2
arbiter daemon                    # foreground; agents also start it on demand
arbiter status
```

With no config the daemon starts one simulated board (`sim-1`) so you can try
everything without hardware. For real boards, run `arbiter init`: it finds the probes
plugged in (and nRF Connect SDK in `C:\ncs` or `~/ncs`), prints a draft `config.toml` and
where it would go, and writes nothing. `arbiter init --write` saves it, and won't replace
an existing config without `--force`. Agents may run both (the `/arbiter:setup` skill
shows you the draft first); `--force` is for you only. The config lives in the state dir
(`~/.local/state/arbiter/` on Linux, `%LOCALAPPDATA%\arbiter\` on Windows, or
`$ARBITER_HOME`); [examples/arbiter.toml](examples/arbiter.toml) shows every setting.

On Windows with nRF Connect SDK, set `daemon.toolchain_env` to the toolchain bundle's
`environment.json`, because `west` and `nrfutil` are not on PATH outside nRF Connect's
own terminal. `arbiter doctor` checks the config, the tools each board needs, the probes
and the daemon, and exits 1 when something an agent needs is missing.

`west flash` runs in the west workspace the build was made with, which it finds from
`ZEPHYR_BASE` in the build's `CMakeCache.txt`, so apps outside the NCS folder flash
fine. Set `zephyr_base` on a board (or in `[daemon]`) only for builds that don't
record it.

## Dashboard

```sh
arbiter dashboard                 # opens http://127.0.0.1:7777/?token=... in your browser
```

The daemon serves the dashboard itself, so it works offline. The link carries the admin
token (from `admin.json` in the state dir); the page keeps it, so later visits to
`http://127.0.0.1:7777/` work until the daemon restarts with a new token. It shows each
board's status, holder, lease time, console source and last flash result, a live terminal
with a tab per console channel, the queue, power, test runs and an activity feed. You can
pause, take over, give back or revoke, reorder the queue and type into the console. Set
`ARBITER_DASHBOARD_DIR` to serve a different copy while working on it.

## Terminal UI

```sh
pip install -e "./backend[tui]"   # adds Textual
arbiter tui                       # or: arbiter tui nrf9161dk --channel uart:app
```

On Windows, run it in Windows Terminal (`wt arbiter tui`, the default terminal on
Windows 11). The classic console that `cmd.exe` opens on Windows 10 has a cramped font,
fewer colours and no dim or italic text, so the TUI looks flat there; it says so when it
starts in one.

The board console fills most of the terminal, in the dashboard's pastel colours. A
sidebar lists the boards with their state, holder and lease time, then the queue, power
and agents' requests; F1 hides it, and terminals narrower than 96 columns get a one-line
status bar instead. Type a line and press Enter to
send it, also while an agent holds the board (it shows as `[you]`, agents as
`[claude-xxxx]`). Tab completes the shell commands of the flashed image and Up/Down
recall earlier lines. Warnings stay yellow and errors red even with the firmware's log
colours off. The footer lists the keys that apply right now:

| Key | Does |
|---|---|
| F1 | show or hide the sidebar |
| F2 | next board |
| F3 | next console channel |
| F4 | queue: move (u/d), priority (p), cancel (x) |
| F5 | take the board, take over from an agent, or give it back |
| F6 | pause or resume the agent |
| F7 | view: fold boot output, timestamps, shell prompts (kept in `tui.json` in the state dir) |
| F8 | reset the board (when you can drive it) |
| F9 | answer agents' requests |
| PgUp/PgDn, Ctrl+L, Ctrl+Q | scroll, clear, quit |

Everything works with the mouse too: click a board or the queue in the sidebar (or the status line),
click a key in the footer (take over, give back, pause...), click a shell suggestion,
use the buttons in the queue and requests popups, click a folded "Booted ..." line to open
it, scroll with the wheel, and drag over the console to select text (Ctrl+C copies it;
in Windows Terminal Shift+drag still gives the terminal's own selection). Settings stay
in the web dashboard.

## Connect an agent

**Claude Code.** Register the MCP server and the hooks:

```sh
claude mcp add arbiter -- arbiter mcp
```

```json
{
  "hooks": {
    "SessionStart": [{"hooks": [{"type": "command", "command": "arbiter hook session-start"}]}],
    "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "arbiter hook pre-tool-use"}]}],
    "PostToolUse": [{"hooks": [{"type": "command", "command": "arbiter hook post-tool-use"}]}],
    "SessionEnd": [{"hooks": [{"type": "command", "command": "arbiter hook session-end"}]}]
  }
}
```

The pre-tool-use hook stops an agent from running `west flash`, `nrfutil device`,
J-Link tools, `openocd` or opening a serial port itself, and points it at the arbiter
tools instead. The post-tool-use hook passes on notices such as "you were paused".

**Codex.** Add to `~/.codex/config.toml`:

```toml
[mcp_servers.arbiter]
command = "arbiter"
args = ["mcp"]
env = { ARBITER_AGENT_KIND = "codex" }
```

and tell it in `AGENTS.md` to use the arbiter tools for anything that touches a board.

## How an agent uses a board

1. `acquire_board(selector, reason)` returns a lease, or a ticket and queue position.
   It never blocks for long: `wait_for_board(ticket)` waits up to 45 s at a time.
2. `flash(build_dir)` flashes and confirms the new image booted on the console.
   Long operations return `{"status": "running", "op_id": ...}`; follow up with `run_status`.
3. `console_read`, `serial_expect(regex)` and `serial_write(data)` work on the primary
   console by default. Pass `channel` for another one (`rtt`, `uart:tfm`), a list, `"all"`,
   or `"any"` for `serial_expect`.
4. `run(cmd=["west", "twister", ...])` runs a test command against the board. Twister gets
   a hardware map with only that board in it.
5. `shell_commands()` lists the shell commands of the flashed image, read from its ELF
   after every flash, so agents and the console know what can be typed even when the
   firmware has help or tab completion turned off.
6. `release_board()` when done. Leases expire if the agent stops heartbeating.

Erasing, recovering a board and raising the supply voltage need your approval
(`arbiter approve <id>` or the dashboard).

## Human controls

```sh
arbiter console nrf9161dk-1 --write    # live console; type to send
arbiter pause nrf9161dk-1              # let the agent's current step finish, then hold
arbiter take nrf9161dk-1               # revoke the lease and hold the board yourself
arbiter resume nrf9161dk-1
arbiter queue                          # show the queue
arbiter queue move <ticket> 1           # also: priority, pin, unpin, cancel
arbiter supply nrf9161dk-1 cycle
arbiter send nrf9161dk-1 "kernel uptime"   # type a line without taking the board
arbiter program nrf9161dk-1 build/      # flash a free board yourself
```

A board no agent holds is yours to use from the dashboard or the CLI, with no lease:
type, reset, flash, power. Using it holds it for you until you have been idle for
`timing.human_idle_s` (120 s), so an agent asking meanwhile waits in the queue and is
told who has the board and when it frees up. `arbiter take` holds it until you
`resume`. Once an agent holds a board you can still type into it, but flashing,
resetting and power need `pause` or `take` first.

Consoles come back by themselves after a reset, a power cycle or the probe
re-enumerating over USB, and the agent keeps its lease: UART reopens the port it
finds again by probe serial, and RTT reattaches with backoff.

You can type into a board's console while an agent holds it. Your lines show as
`[you] > ...` and the agent's as `[claude-1a2b] > ...`. Writes never interleave
mid-line. The agent gets an inbox note, and its `serial_expect` and `console_read`
results list your lines under `human_input`, so it can tell your command's reply from
its own.

## Customising

Three levels, lightest first (details in `arbiter/plugins.py`):

1. Override one action on any board with your own command, under `[board.commands]`.
2. `driver = "command"`: a board made only of your commands.
3. A Python plugin: subclass `arbiter.drivers.base.BoardDriver` (or
   `arbiter.power.PowerDevice`) and either name it as `driver = "my_module:MyDriver"`
   or publish it under the `arbiter.drivers` / `arbiter.power` entry-point group.

A supply you control with a script is `[board.power] kind = "command"` with `on`,
`off`, `set_voltage` and `measure` commands.

Each board's `[board.power]` sets its limits: `mv_min` and `mv_max` bound every voltage
change, agents need your approval to go above `default_mv`, and `ma_max` switches the supply
off when a measurement goes over it (only you can turn it back on). A script supply's
`set_current_limit` command gets `ma_max` at start so the supply enforces it too. The limits
appear under `power.limits` in `arbiter status` and the API.

## Development

From the repo root:

```sh
pip install -r requirements-dev.txt -e backend
pre-commit run --all-files     # ruff lint and format
mypy                           # strict
pytest backend/tests           # unit tests; hardware and native_sim tests are marked integration
pytest backend/tests -m integration   # needs ARBITER_NATIVE_SIM_BUILD or a board
```
