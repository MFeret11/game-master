"""The web server: pages, a small HTTP API, and one WebSocket per screen.

Screens connect to /ws. The server sends a full snapshot on connect and after
every change; screens just redraw. A phone sends its token on connect, so a
refresh, a locked phone or a dropped Wi-Fi comes back exactly where it was.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import segno
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import library, party
from .db import connect
from .netinfo import lan_ip

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
STARTER = ROOT / "games" / "starter.yaml"


@dataclass(eq=False)
class Screen:
    ws: WebSocket
    player_id: int | None = None


@dataclass
class Hub:
    """Every open screen, so a change can be sent to all of them."""

    screens: set[Screen] = field(default_factory=set)

    async def send(self, screen: Screen, message: dict) -> bool:
        try:
            await screen.ws.send_text(json.dumps(message))
            return True
        except Exception:
            self.screens.discard(screen)
            return False

    async def broadcast(self, message: dict) -> None:
        await asyncio.gather(*(self.send(s, message) for s in list(self.screens)))

    async def sign_out(self, player_id: int, message: dict) -> None:
        """Tell a player's other phones their token no longer works, then close them."""
        for screen in [s for s in self.screens if s.player_id == player_id]:
            await self.send(screen, message)
            self.screens.discard(screen)
            with contextlib.suppress(Exception):
                await screen.ws.close(code=4001)


class JoinBody(BaseModel):
    name: str
    code: str


class RejoinBody(BaseModel):
    player_id: int
    code: str


def create_app(data_dir: str | Path | None = None, port: int | None = None) -> FastAPI:
    data_dir = Path(data_dir or os.environ.get("GM_DATA", ROOT / "data"))
    port = port or int(os.environ.get("GM_PORT", "8000"))
    conn = connect(data_dir / "gamemaster.db")
    library.seed_if_empty(conn, data_dir, STARTER)
    hub = Hub()

    app = FastAPI(title="Game Master", docs_url=None, redoc_url=None)
    app.state.conn = conn
    app.state.hub = hub

    def the_party():
        return party.current_party(conn)

    def join_url() -> str:
        base = os.environ.get("GM_PUBLIC_URL") or f"http://{lan_ip()}:{port}"
        return f"{base.rstrip('/')}/?code={the_party()['room_code']}"

    async def changed() -> None:
        await hub.broadcast({"type": "state", "state": party.snapshot(conn, the_party()["id"])})

    def refused(err: party.ActionError, status: int = 409) -> JSONResponse:
        return JSONResponse({"error": err.code, "message": err.message, **err.extra}, status)

    # Pages ------------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    def phone_page():
        return FileResponse(STATIC / "phone.html", headers={"Cache-Control": "no-cache"})

    @app.get("/tv", include_in_schema=False)
    def tv_page():
        return FileResponse(STATIC / "tv.html", headers={"Cache-Control": "no-cache"})

    @app.get("/qr.svg", include_in_schema=False)
    def qr_code():
        # Made locally: the party has no internet.
        buf = io.BytesIO()
        segno.make(join_url(), error="m").save(buf, kind="svg", scale=10, border=2, dark="#000", light="#fff")
        return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})

    # API ------------------------------------------------------------------------

    @app.get("/api/info")
    def info():
        p = the_party()
        return {"room_code": p["room_code"], "join_url": join_url()}

    @app.post("/api/join")
    async def join(body: JoinBody):
        p = the_party()
        try:
            party.check_code(p, body.code)
            joined = party.join(conn, p["id"], body.name)
        except party.ActionError as err:
            return refused(err, 400 if err.code in ("bad_name", "bad_code") else 409)
        await changed()
        return {"player_id": joined.player_id, "token": joined.token}

    @app.post("/api/rejoin")
    async def rejoin(body: RejoinBody):
        p = the_party()
        try:
            party.check_code(p, body.code)
            joined = party.rejoin(conn, p["id"], body.player_id)
        except party.ActionError as err:
            return refused(err, 400 if err.code == "bad_code" else 404)
        await hub.sign_out(joined.player_id, {"type": "signed_out"})
        await changed()
        return {"player_id": joined.player_id, "token": joined.token}

    # Live updates -----------------------------------------------------------------

    @app.websocket("/ws")
    async def live(ws: WebSocket, token: str | None = None):
        await ws.accept()
        p = the_party()
        screen = Screen(ws)
        if token:
            me = party.player_for_token(conn, p["id"], token)
            if me is None:
                # Old token: a new party, or someone rejoined as this player.
                await hub.send(screen, {"type": "unknown_token"})
            else:
                screen.player_id = me["id"]
        hub.screens.add(screen)
        await hub.send(screen, {"type": "hello", "you": screen.player_id})
        await hub.send(screen, {"type": "state", "state": party.snapshot(conn, p["id"])})
        try:
            while True:
                message = json.loads(await ws.receive_text())
                if message.get("type") == "ping":
                    await hub.send(screen, {"type": "pong"})
                elif message.get("type") == "sync":
                    await hub.send(screen, {"type": "state", "state": party.snapshot(conn, p["id"])})
        except (WebSocketDisconnect, json.JSONDecodeError, RuntimeError):
            pass
        finally:
            hub.screens.discard(screen)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
