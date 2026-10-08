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
| [`docs/hw-validation-nrf9161dk.md`](docs/hw-validation-nrf9161dk.md) | What a real nRF9161 DK showed about the design's assumptions |
| [`backend/`](backend/) | The `arbiterd` service, the `arbiter` CLI and the MCP server |
| [`plugin/`](plugin/) | The Claude Code plugin: MCP server config, the board etiquette skill and hooks |
| [`codex/`](codex/) | The same setup for Codex: a `config.toml` snippet and `AGENTS.md` rules |

## Use it from Claude Code

```text
/plugin marketplace add famesy/arbiter
/plugin install arbiter@arbiter
```

The plugin needs `arbiter` on PATH (`pip install -e backend`). See [`plugin/README.md`](plugin/README.md), and [`codex/`](codex/) for Codex.

## Status

Early design. The dashboard prototype is simulated; the backend is in progress.

## Development

Style and type checks run on every pull request (`.github/workflows/ci.yml`). Run the same checks locally:

```sh
pip install -r requirements-dev.txt
pre-commit install          # ruff lint + format and file hygiene on each commit
pre-commit run --all-files  # what the CI "Style" job runs
mypy                        # what the CI "Types" step runs (strict)
pytest backend/tests -m "not integration"
```

Tool settings live at the repo root: `ruff.toml`, `mypy.ini`, `.pre-commit-config.yaml`. Keep `[tool.ruff]` and `[tool.mypy]` out of `backend/pyproject.toml`, so there is one source of truth.

Integration tests (`@pytest.mark.integration`) never run by default. Start them from **Actions > Integration > Run workflow**, choosing `simulated` or `hardware` (a self-hosted runner labelled `arbiter-hw` with the boards attached), or add the `run-integration` label to a pull request.
