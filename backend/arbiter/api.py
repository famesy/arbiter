"""HTTP + WebSocket API (loopback only by default). The MCP shim, the CLI and
the web dashboard are all clients of this. See API.md for the full list."""

from __future__ import annotations

import asyncio
import hmac
import json
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from . import __version__
from .console.hub import Sender
from .errors import ArbiterError
from .plugins import available as available_plugins
from .service import Arbiter

Handler = Callable[..., Awaitable[Any]]
Endpoint = Callable[[Request], Awaitable[Response]]
Ctx = dict[str, Any]
Body = dict[str, Any]


class Auth:
    def __init__(self, agent_token: str, admin_token: str):
        self.agent_token, self.admin_token = agent_token, admin_token

    def level(self, token: str | None) -> str | None:
        if not token:
            return None
        if hmac.compare_digest(token, self.admin_token):
            return "admin"
        if hmac.compare_digest(token, self.agent_token):
            return "agent"
        return None


def _token_from(req: Request | WebSocket) -> str | None:
    h = req.headers.get("authorization", "")
    if h.lower().startswith("bearer "):
        return h[7:].strip()
    return req.query_params.get("token") or req.cookies.get("arbiter_token")


def create_app(arb: Arbiter, auth: Auth, dashboard_dir: Path | None = None) -> Starlette:
    def endpoint(fn: Handler, admin: bool = False) -> Endpoint:
        async def handler(req: Request) -> Response:
            lvl = auth.level(_token_from(req))
            if lvl is None or (admin and lvl != "admin"):
                return JSONResponse(
                    ArbiterError(
                        "UNAUTHORIZED", "admin token required" if lvl else "bad token"
                    ).to_dict(),
                    status_code=401,
                )
            body: dict[str, Any] = {}
            if req.method in ("POST", "PUT", "DELETE"):
                raw = await req.body()
                if raw:
                    try:
                        parsed = json.loads(raw)
                    except ValueError:
                        return JSONResponse(
                            ArbiterError("BAD_REQUEST", "body is not JSON").to_dict(), 400
                        )
                    if not isinstance(parsed, dict):
                        return JSONResponse(
                            ArbiterError("BAD_REQUEST", "body must be an object").to_dict(), 400
                        )
                    body = parsed
            ctx = {
                "session": req.headers.get("x-arbiter-session") or body.pop("session_id", None),
                "level": lvl,
                "path": dict(req.path_params),
                "query": dict(req.query_params),
            }
            try:
                result = await fn(ctx, body)
            except ArbiterError as e:
                return JSONResponse(e.to_dict(), status_code=e.http_status)
            except (TypeError, ValueError, KeyError) as e:
                return JSONResponse(
                    ArbiterError("BAD_REQUEST", f"{type(e).__name__}: {e}").to_dict(), 400
                )
            return JSONResponse(result)

        return handler

    human = arb.cfg.human_name

    def by(ctx: dict[str, Any], body: dict[str, Any]) -> str:
        return f"human:{body.get('by') or human}"

    def a(fn: Handler) -> Endpoint:
        return endpoint(fn, admin=False)

    def adm(fn: Handler) -> Endpoint:
        return endpoint(fn, admin=True)

    def sid(ctx: dict[str, Any]) -> str | None:
        # Admin callers act as the human and may operate on any lease token.
        return None if ctx["level"] == "admin" else ctx["session"]

    # ------------------------------------------------------------ agent routes
    async def health(ctx: Ctx, body: Body) -> Any:
        return {"ok": True, "version": __version__, "pid": os.getpid()}

    async def state(ctx: Ctx, body: Body) -> Any:
        return arb.snapshot()

    async def boards(ctx: Ctx, body: Body) -> Any:
        return {"boards": arb.list_boards()}

    async def register(ctx: Ctx, body: Body) -> Any:
        allowed = {
            "agent_kind",
            "label",
            "external_id",
            "heartbeat",
            "repo",
            "branch",
            "head",
            "cwd",
            "pid",
        }
        kw = {k: v for k, v in body.items() if k in allowed}
        if kw.get("agent_kind") == "human" and ctx["level"] != "admin":
            kw["agent_kind"] = "cli"
        return arb.register_session(**kw)

    async def heartbeat(ctx: Ctx, body: Body) -> Any:
        return arb.heartbeat(ctx["path"]["sid"])

    async def end(ctx: Ctx, body: Body) -> Any:
        return arb.end_session(ctx["path"]["sid"], bool(body.get("release", True)))

    async def inbox(ctx: Ctx, body: Body) -> Any:
        return {"items": arb.inbox(ctx["path"]["sid"])}

    async def inbox_ext(ctx: Ctx, body: Body) -> Any:
        s = arb.sched.session_by_external(ctx["path"]["ext"])
        if not s:
            return {"items": [], "session": None}
        return {
            "items": arb.inbox(s.id),
            "session": s.id,
            "leases": [
                {"board": le.board_id, "state": le.state, "lease_id": le.id}
                for le in arb.sched.leases_of(s.id)
            ],
        }

    async def session_info(ctx: Ctx, body: Body) -> Any:
        s = arb.sched.session(ctx["path"]["sid"])
        d = s.public()
        live = arb.sched.leases_of(s.id)
        d["leases"] = [
            {
                **le.public(),
                **(
                    {"lease_token": le.token}
                    if ctx["session"] == s.id or ctx["level"] == "admin"
                    else {}
                ),
            }
            for le in live
        ]
        d["tickets"] = [e.ticket for e in arb.sched.queue if e.session_id == s.id]
        return d

    def need_session(ctx: Ctx) -> str:
        session = ctx["session"]
        if not isinstance(session, str) or not session:
            raise ArbiterError("SESSION_UNKNOWN", "send X-Arbiter-Session (register first)")
        arb.sched.session(session)
        return session

    async def acquire(ctx: Ctx, body: Body) -> Any:
        s = need_session(ctx)
        return await arb.acquire(
            s,
            body.get("selector"),
            body.get("reason", ""),
            body.get("priority"),
            float(body.get("wait_s", 0)),
        )

    async def wait(ctx: Ctx, body: Body) -> Any:
        return await arb.wait(need_session(ctx), body["ticket"], float(body.get("wait_s", 45)))

    async def cancel(ctx: Ctx, body: Body) -> Any:
        return arb.cancel(sid(ctx), body["ticket"])

    async def release(ctx: Ctx, body: Body) -> Any:
        return arb.release(sid(ctx), body["lease_token"])

    async def extend(ctx: Ctx, body: Body) -> Any:
        return arb.extend(sid(ctx), body["lease_token"], float(body.get("minutes", 10)))

    async def reclaim(ctx: Ctx, body: Body) -> Any:
        return arb.reclaim(ctx["session"], body["lease_token"])

    async def lease_info(ctx: Ctx, body: Body) -> Any:
        return arb.lease_info(sid(ctx), body["lease_token"])

    async def flash(ctx: Ctx, body: Body) -> Any:
        return await arb.flash(
            sid(ctx),
            body["lease_token"],
            body["build_dir"],
            body.get("domain"),
            bool(body.get("erase", False)),
            body.get("cwd"),
            float(body.get("wait_s", 45)),
        )

    async def reset(ctx: Ctx, body: Body) -> Any:
        return await arb.reset(sid(ctx), body["lease_token"], bool(body.get("halt", False)))

    async def recover(ctx: Ctx, body: Body) -> Any:
        return await arb.recover(sid(ctx), body["lease_token"], float(body.get("wait_s", 45)))

    async def console_read(ctx: Ctx, body: Body) -> Any:
        return arb.console_read(
            sid(ctx),
            body["lease_token"],
            body.get("cursor"),
            int(body.get("max_bytes", 8192)),
            body.get("channel"),
        )

    async def console_expect(ctx: Ctx, body: Body) -> Any:
        return await arb.expect(
            sid(ctx),
            body["lease_token"],
            body["regex"],
            float(body.get("timeout_s", 10)),
            body.get("since", "mark"),
            body.get("channel"),
        )

    async def console_write(ctx: Ctx, body: Body) -> Any:
        return await arb.write(
            sid(ctx),
            body["lease_token"],
            body["data"],
            bool(body.get("newline", True)),
            body.get("channel"),
        )

    async def console_detect(ctx: Ctx, body: Body) -> Any:
        return await arb.detect_console(
            sid(ctx), body["lease_token"], body.get("build_dir"), body.get("elf")
        )

    async def run(ctx: Ctx, body: Body) -> Any:
        cmd = body["cmd"]
        if isinstance(cmd, str):
            raise ArbiterError("BAD_REQUEST", "cmd must be a list of arguments")
        return await arb.run(
            sid(ctx),
            body["lease_token"],
            cmd,
            body.get("cwd"),
            float(body.get("timeout_s", 1800)),
            float(body.get("wait_s", 45)),
            body.get("env"),
            bool(body.get("inject_twister", True)),
        )

    async def op_status(ctx: Ctx, body: Body) -> Any:
        return await arb.op_status(
            ctx["path"]["op"], float(ctx["query"].get("wait_s", 0)), sid(ctx)
        )

    async def power(ctx: Ctx, body: Body) -> Any:
        return await arb.power(
            sid(ctx), body["lease_token"], body["action"], int(body.get("off_ms", 500))
        )

    async def power_voltage(ctx: Ctx, body: Body) -> Any:
        return await arb.power_set_voltage(
            sid(ctx), body["lease_token"], int(body["mv"]), human=ctx["level"] == "admin"
        )

    async def power_measure(ctx: Ctx, body: Body) -> Any:
        return await arb.measure_current(
            sid(ctx),
            body["lease_token"],
            int(body.get("duration_ms", 5000)),
            body.get("trigger"),
            body.get("threshold_ua"),
            bool(body.get("allow_debug_attached", False)),
            bool(body.get("power_cycle", False)),
            float(body.get("wait_s", 45)),
        )

    # ------------------------------------------------------------ admin routes
    async def board_action(ctx: Ctx, body: Body) -> Any:
        bid, action = ctx["path"]["board"], ctx["path"]["action"]
        who = by(ctx, body)
        if action == "pause":
            return await arb.pause(bid, who, body.get("reason", ""), bool(body.get("force", False)))
        if action == "resume":
            return await arb.resume(bid, who)
        if action == "take":
            return await arb.take(bid, who, body.get("reason", ""))
        if action == "revoke":
            return await arb.revoke(
                bid, who, body.get("reason", ""), bool(body.get("requeue", True))
            )
        if action == "release":
            return arb.release_hold(bid, who)
        if action == "maintenance":
            return arb.maintenance(bid, bool(body.get("on", True)), who)
        if action == "write":
            return await arb.human_write(
                bid,
                body["data"],
                body.get("by") or human,
                bool(body.get("newline", True)),
                body.get("channel"),
            )
        if action == "power":
            return await arb.human_power(
                bid, body["action"], body.get("by") or human, body.get("mv")
            )
        if action == "reset":
            return await arb.human_reset(
                bid, body.get("by") or human, bool(body.get("halt", False))
            )
        if action == "recover":
            return await arb.human_recover(bid, body.get("by") or human)
        if action == "extend":
            b = arb.sched.board(bid)
            if not b.lease_token:
                raise ArbiterError("BAD_REQUEST", f"{bid} has no lease")
            return arb.extend(None, b.lease_token, float(body.get("minutes", 15)))
        raise ArbiterError("BAD_REQUEST", f"unknown action {action!r}")

    async def queue_action(ctx: Ctx, body: Body) -> Any:
        t, action = ctx["path"]["ticket"], ctx["path"]["action"]
        if action == "move":
            arb.sched.move(t, int(body["index"]))
        elif action == "priority":
            arb.sched.set_priority(t, body["priority"])
        elif action == "pin":
            arb.sched.pin(t, bool(body.get("pinned", True)))
        elif action == "cancel":
            arb.sched.cancel(t)
        else:
            raise ArbiterError("BAD_REQUEST", f"unknown action {action!r}")
        return {"ok": True, "queue": arb.sched.snapshot()["queue"]}

    async def bump(ctx: Ctx, body: Body) -> Any:
        arb.sched.bump_session(ctx["path"]["sid"], body.get("priority", "high"))
        return {"ok": True}

    async def decide(ctx: Ctx, body: Body) -> Any:
        return await arb.decide(ctx["path"]["id"], bool(body["approve"]), by(ctx, body))

    async def audit(ctx: Ctx, body: Body) -> Any:
        if not arb.store:
            return {"items": []}
        return {
            "items": arb.store.recent_audit(
                int(ctx["query"].get("limit", 200)), ctx["query"].get("board")
            )
        }

    async def plugins(ctx: Ctx, body: Body) -> Any:
        return available_plugins()

    # ------------------------------------------------------------ websockets
    async def ws_events(ws: WebSocket) -> None:
        lvl = auth.level(_token_from(ws))
        if lvl is None:
            await ws.close(code=4401)
            return
        await ws.accept()
        q = arb.bus.subscribe()

        async def pump() -> None:
            since = int(ws.query_params.get("since", "0") or 0)
            await ws.send_json({"kind": "snapshot", "seq": arb.bus.seq, "state": arb.snapshot()})
            for ev in arb.bus.since(since):
                await ws.send_json(ev)
            while True:
                await ws.send_json(await q.get())

        out = asyncio.create_task(pump())
        try:
            while True:  # notice the client going away even when no events flow
                if (await ws.receive())["type"] == "websocket.disconnect":
                    break
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            out.cancel()
            arb.bus.unsubscribe(q)

    async def ws_console(ws: WebSocket) -> None:
        """Binary console stream of one channel (?channel=, default "all"; the bridge uses
        "console"). Admin: reads, and writes as the human. Agent: needs ?lease=<token>;
        writes need the lease to be ACTIVE (used by console-bridge)."""
        lvl = auth.level(_token_from(ws))
        bid = ws.path_params["board"]
        if lvl is None or bid not in arb.boards:
            await ws.close(code=4401 if lvl is None else 4404)
            return
        lease_token = ws.query_params.get("lease")
        if lvl == "agent":
            lease = arb.sched.leases.get(lease_token or "")
            if lease is None or lease.board_id != bid:
                await ws.close(code=4403)
                return
        rt = arb.boards[bid]
        channel = ws.query_params.get("channel") or "all"
        try:
            channel = rt.hub.resolve(channel)
        except ArbiterError:
            await ws.close(code=4404)
            return
        write_to = None if channel == "all" else channel
        await ws.accept()
        q = rt.hub.subscribe(channel)
        scrollback = int(ws.query_params.get("scrollback", "16384"))
        if scrollback > 0:
            data, _, _ = rt.hub.read(None, scrollback, channel)
            if data:
                await ws.send_bytes(data)

        async def pump_out() -> None:
            while True:
                await ws.send_bytes(await q.get())

        out_task = asyncio.create_task(pump_out())
        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                data = msg.get("bytes") or (msg.get("text") or "").encode()
                if not data:
                    continue
                try:
                    if lvl == "admin":
                        sender = Sender.human(ws.query_params.get("by") or human)
                    else:
                        lease = arb.sched.check(lease_token or "")
                        sender = arb._sender(lease.session_id)
                    await arb.console_send(rt, data, sender, write_to)
                except ArbiterError as e:
                    await ws.send_text(json.dumps(e.to_dict()))
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            out_task.cancel()
            rt.hub.unsubscribe(q)

    # ------------------------------------------------------------ dashboard
    async def index(req: Request) -> Response:
        if dashboard_dir and (dashboard_dir / "index.html").exists():
            return HTMLResponse((dashboard_dir / "index.html").read_text())
        return HTMLResponse(PLACEHOLDER)

    routes = [
        Route("/api/health", a(health), methods=["GET"]),
        Route("/api/state", a(state), methods=["GET"]),
        Route("/api/boards", a(boards), methods=["GET"]),
        Route("/api/plugins", a(plugins), methods=["GET"]),
        Route("/api/sessions", a(register), methods=["POST"]),
        Route("/api/sessions/by-external/{ext}/inbox", a(inbox_ext), methods=["GET", "POST"]),
        Route("/api/sessions/{sid}", a(session_info), methods=["GET"]),
        Route("/api/sessions/{sid}/heartbeat", a(heartbeat), methods=["POST"]),
        Route("/api/sessions/{sid}/end", a(end), methods=["POST"]),
        Route("/api/sessions/{sid}/inbox", a(inbox), methods=["GET", "POST"]),
        Route("/api/acquire", a(acquire), methods=["POST"]),
        Route("/api/wait", a(wait), methods=["POST"]),
        Route("/api/cancel", a(cancel), methods=["POST"]),
        Route("/api/release", a(release), methods=["POST"]),
        Route("/api/extend", a(extend), methods=["POST"]),
        Route("/api/reclaim", a(reclaim), methods=["POST"]),
        Route("/api/lease", a(lease_info), methods=["POST"]),
        Route("/api/flash", a(flash), methods=["POST"]),
        Route("/api/reset", a(reset), methods=["POST"]),
        Route("/api/recover", a(recover), methods=["POST"]),
        Route("/api/console/read", a(console_read), methods=["POST"]),
        Route("/api/console/expect", a(console_expect), methods=["POST"]),
        Route("/api/console/write", a(console_write), methods=["POST"]),
        Route("/api/console/detect", a(console_detect), methods=["POST"]),
        Route("/api/run", a(run), methods=["POST"]),
        Route("/api/ops/{op}", a(op_status), methods=["GET"]),
        Route("/api/power", a(power), methods=["POST"]),
        Route("/api/power/voltage", a(power_voltage), methods=["POST"]),
        Route("/api/power/measure", a(power_measure), methods=["POST"]),
        Route("/api/admin/boards/{board}/{action}", adm(board_action), methods=["POST"]),
        Route("/api/admin/queue/{ticket}/{action}", adm(queue_action), methods=["POST"]),
        Route("/api/admin/sessions/{sid}/bump", adm(bump), methods=["POST"]),
        Route("/api/admin/approvals/{id}", adm(decide), methods=["POST"]),
        Route("/api/admin/audit", adm(audit), methods=["GET"]),
        WebSocketRoute("/api/events", ws_events),
        WebSocketRoute("/api/boards/{board}/console", ws_console),
        Route("/", index, methods=["GET"]),
    ]
    if dashboard_dir and dashboard_dir.exists():
        routes.append(Mount("/static", StaticFiles(directory=str(dashboard_dir)), name="static"))
    return Starlette(routes=routes)


PLACEHOLDER = """<!doctype html><meta charset=utf-8><title>arbiter</title>
<style>body{font:15px system-ui;margin:40px;color:#222;background:#fafafa}code{background:#eee;padding:2px 4px}</style>
<h1>arbiter is running</h1><p>The dashboard is not installed yet. The API is at <code>/api</code>;
live events at <code>/api/events</code>. Set <code>ARBITER_DASHBOARD_DIR</code> to serve a dashboard build.</p>"""
