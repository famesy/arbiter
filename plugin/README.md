# arbiter plugin for Claude Code

Lets Claude Code share the dev boards on this machine through `arbiterd`. It bundles:

| Part | What it does |
|---|---|
| `.mcp.json` | Starts `arbiter mcp`, which gives the agent `acquire_board`, `wait_for_board`, `flash`, `console_read`, `serial_expect`, `serial_write`, `run`, `release_board` and the rest. It starts the daemon if it isn't running. |
| `skills/board-etiquette` | Teaches the queue rules: acquire only when ready, wait without blocking, release early, stop when paused, prefer `native_sim`, use console channels, and run hardware tests through arbiter. |
| `skills/setup` | `/arbiter:setup`: installs `arbiter` if missing (after asking), drafts the board config with `arbiter init` and writes it only after you approve, runs `arbiter doctor`, and tells you how to open the dashboard. |
| `hooks/hooks.json` | `SessionStart` starts the daemon in the background if needed and registers the session. `PreToolUse` blocks raw `west flash`, `nrfutil device`, J-Link tools, `openocd`, `pyocd` and direct serial access, and says what to use instead. `PostToolUse` (on shell and arbiter tools) passes on notices such as "granted", "paused" or "lease expiring". `SessionEnd` releases the session's boards. |

Every part calls the `arbiter` executable, so it works the same on Linux and Windows.

## Install

1. In Claude Code:

   ```text
   /plugin marketplace add famesy/arbiter
   /plugin install arbiter@arbiter
   ```

   While developing the plugin, load it straight from the checkout instead:
   `claude --plugin-dir ./plugin`.

2. Run `/arbiter:setup`. Claude installs the `arbiter` command if it's missing (after
   asking), finds your boards, shows you the config it would write and writes it only when
   you say yes, then checks everything with `arbiter doctor`. Restart Claude Code if it had
   to install `arbiter`, so the MCP server and hooks pick it up.

From then on, every session starts the arbiter daemon in the background if it isn't
running. Open the dashboard with `arbiter dashboard` in your own terminal.

Don't also add the MCP server or hooks by hand (`claude mcp add arbiter ...`); the plugin
already does both.

## Codex

Codex uses the same MCP server. Copy [`../codex/config.toml`](../codex/config.toml) into
`~/.codex/config.toml` and paste [`../codex/AGENTS.md`](../codex/AGENTS.md) into the
firmware repo's `AGENTS.md`. To give Codex the full skill too, copy
`skills/board-etiquette/SKILL.md` to `.agents/skills/board-etiquette/SKILL.md` in that repo.
