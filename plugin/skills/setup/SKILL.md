---
name: setup
description: Set up arbiter on this machine - install the arbiter command, create its board config with `arbiter init`, check everything with `arbiter doctor`, and start the daemon. Use when the user asks to set up, install, configure or fix arbiter, or when arbiter reports it is not installed, has no config, or has no boards.
---

# Set up arbiter

Get this machine from nothing to a working board broker: install `arbiter`, create its
board config with the human's approval, check it, and start the daemon.

**Never write or edit arbiter's config file yourself** (`config.toml` in arbiter's state
directory, or the file `ARBITER_CONFIG` points to). It is only written by
`arbiter init --write`, after the human has seen the draft and said yes. If something in the
draft is wrong, tell the human what to change and let them edit it, or run `arbiter init`
again.

## 1. Is `arbiter` installed?

```sh
arbiter --help
```

If the command is missing, ask the human before installing anything, then run:

```sh
pipx install "git+https://github.com/famesy/arbiter#subdirectory=backend"
```

Without pipx, use `python -m pip install --user "git+https://github.com/famesy/arbiter#subdirectory=backend"`
and make sure the scripts folder is on PATH. From a checkout of the arbiter repo,
`pip install -e backend` works too. On Windows, open a new terminal afterwards if
`arbiter` still isn't found, and tell the human to restart Claude Code so the plugin's
MCP server and hooks can find it.

For RTT consoles add the `rtt` extra, and for a Nordic PPK2 the `ppk2` extra, e.g.
`pipx install "arbiter[rtt,ppk2] @ git+https://github.com/famesy/arbiter#subdirectory=backend"`.

## 2. Create the board config

Plug in the boards first. Then run, without `--write`:

```sh
arbiter init
```

It detects the connected probes (J-Link, ST-Link, ...) and prints a draft config and the
path it would write to. It writes nothing.

Show the human the draft: which boards it found, their probe serials, platforms, console
ports, and any power device. Ask whether it looks right. Only after they say yes:

```sh
arbiter init --write
```

If a config already exists, `init --write` refuses. Ask the human whether to replace it
before adding `--force`. If no probe is found, say so: with no config arbiter still starts
with a simulated board, and a `native_sim` board works on Linux and in WSL.

## 3. Check it

```sh
arbiter doctor
```

Each line is `OK`, `WARN` or `FAIL` with a reason: the config, the tools (`west`,
`nrfutil`, J-Link), each board's probe and ports, and whether the daemon runs. Explain any
`FAIL` to the human in plain words with the fix, for example "nrfutil is not on PATH" or
"no probe with serial 1050... is connected". Re-run `arbiter doctor` after each fix.

## 4. Start it and hand over

The daemon starts on its own when a session starts or the first arbiter tool is used.
Check it with:

```sh
arbiter status
```

Then tell the human:
- The boards arbiter now manages, and that agents queue for them through arbiter.
- They can open the dashboard with `arbiter dashboard` in their own terminal. Don't run it
  yourself: it prints a URL with the human's admin token.
- When no agent holds a board, they can use it from the dashboard's terminal, or take it
  any time, even while an agent holds it.

After setup, follow the `board-etiquette` skill for using the boards.
