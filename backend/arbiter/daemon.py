"""arbiterd: load config, write the token files, serve the API."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from pathlib import Path

from .api import Auth, create_app
from .config import BoardConfig, PowerConfig, load_config, write_daemon_files
from .service import Arbiter

log = logging.getLogger("arbiter")


def _port_free(host: str, port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind((host, port))
        except OSError:
            return False
        return True


def run_daemon(config: Path | None = None, port: int | None = None, host: str | None = None) -> int:
    import uvicorn

    logging.basicConfig(
        level=os.environ.get("ARBITER_LOG", "INFO"), format="%(asctime)s %(name)s %(message)s"
    )
    cfg = load_config(config)
    cfg.host = host or cfg.host
    cfg.port = port or cfg.port
    if not cfg.boards:
        log.info(
            "no boards configured (%s); starting with one simulated board",
            cfg.path or "no config file",
        )
        cfg.boards.append(
            BoardConfig(
                id="sim-1",
                driver="sim",
                platform="nrf9161dk/nrf9161/ns",
                tags=["sim"],
                options={"heartbeat_s": 5},
                power=PowerConfig(kind="sim"),
            )
        )
    if not _port_free(cfg.host, cfg.port):
        log.error("port %s:%s is busy (is arbiterd already running?)", cfg.host, cfg.port)
        return 1
    agent_token, admin_token = write_daemon_files(cfg.state, cfg.host, cfg.port)
    arb = Arbiter(cfg)
    dash = os.environ.get("ARBITER_DASHBOARD_DIR")
    app = create_app(arb, Auth(agent_token, admin_token), Path(dash) if dash else None)

    async def main() -> None:
        await arb.start()
        server = uvicorn.Server(
            uvicorn.Config(app, host=cfg.host, port=cfg.port, log_level="warning", ws="websockets")
        )
        log.info(
            "arbiterd on http://%s:%s with %d board(s); state in %s",
            cfg.host,
            cfg.port,
            len(arb.boards),
            cfg.state,
        )
        try:
            await server.serve()
        finally:
            await arb.stop()

    asyncio.run(main())
    return 0
