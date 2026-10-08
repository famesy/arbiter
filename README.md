# arbiter

A hardware-in-the-loop board broker that lets several AI coding agents (Claude Code, Codex) share one or two physical dev boards, such as Nordic nRF and STM32 boards running Zephyr RTOS.

Agents queue for a board, then flash, debug and run integration tests on it. A person watches from a local dashboard, with a live terminal, can send commands to the board, reorder the queue, and pause an agent to take the board themselves.

## How it fits together

- **`arbiterd`**, a Python asyncio daemon on the machine the boards are plugged into, is the only process that touches probes and serial ports.
- **Agents** connect through an MCP server (packaged as a Claude Code plugin; Codex uses the same server via `config.toml` and `AGENTS.md`). Tools include `acquire_board`, `flash`, `serial_expect`, `run` and `release_board`.
- **Queueing** is non-blocking: `acquire_board` returns a lease or a ticket. Leases have a TTL kept alive by heartbeats.
- **Console** is UART or RTT, picked automatically from the build config, the ELF or a runtime probe.
- **Power** control is optional, through a Nordic PPK2 or an external supply.
- **People** use a web dashboard at `127.0.0.1:7777`, a tray icon and a CLI.
- Linux and Windows are first-class; macOS is best-effort.

## Layout

| Path | What's there |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | The design doc |
| [`backend/`](backend/) | The `arbiterd` service (coming in its own pull request) |

## Status

Early design. The backend is in progress; the dashboard design is on hold.
