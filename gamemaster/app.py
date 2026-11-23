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

from . import clues, jeopardy, library, party
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


class JeopardyBody(BaseModel):
    action: str
    col: int | None = None
    clue_id: int | None = None
    side: str | None = None
    right: bool | None = None
    wager: int | None = None
    difficulty: str | None = None
    left_name: str | None = None
    right_name: str | None = None


def create_app(data_dir: str | Path | None = None, port: int | None = None) -> FastAPI:
    data_dir = Path(data_dir or os.environ.get("GM_DATA", ROOT / "data"))
    port = port or int(os.environ.get("GM_PORT", "8000"))
    conn = connect(data_dir / "gamemaster.db")
    library.seed_if_empty(conn, data_dir, STARTER)
    hub = Hub()
    clue_db: dict = {}               # opened on first use; may download the clues first
    clue_lock = asyncio.Lock()

    app = FastAPI(title="Game Master", docs_url=None, redoc_url=None)
    app.state.conn = conn
    app.state.hub = hub

    def the_party():
        return party.current_party(conn)

    def base_url() -> str:
        return (os.environ.get("GM_PUBLIC_URL") or f"http://{lan_ip()}:{port}").rstrip("/")

    def join_url() -> str:
        return f"{base_url()}/?code={the_party()['room_code']}"

    def state() -> dict:
        party_id = the_party()["id"]
        return {**party.snapshot(conn, party_id), "jeopardy": jeopardy.view(conn, party_id)}

    async def changed() -> None:
        await hub.broadcast({"type": "state", "state": state()})

    async def clue_conn():
        async with clue_lock:
            if "conn" not in clue_db:
                clue_db["conn"] = await asyncio.to_thread(clues.open_clues, data_dir)
            return clue_db["conn"]

    def refused(err: party.ActionError, status: int = 409) -> JSONResponse:
        return JSONResponse({"error": err.code, "message": err.message, **err.extra}, status)

    # Pages ------------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    def phone_page():
        return FileResponse(STATIC / "phone.html", headers={"Cache-Control": "no-cache"})

    @app.get("/tv", include_in_schema=False)
    def tv_page():
        return FileResponse(STATIC / "tv.html", headers={"Cache-Control": "no-cache"})

    @app.get("/jeopardy", include_in_schema=False)
    def jeopardy_page():
        return FileResponse(STATIC / "jeopardy.html", headers={"Cache-Control": "no-cache"})

    @app.get("/buzz", include_in_schema=False)
    def buzz_page():
        return FileResponse(STATIC / "buzz.html", headers={"Cache-Control": "no-cache"})

    @app.get("/qr.svg", include_in_schema=False)
    def qr_code(to: str = "join"):
        # Made locally, no web service.
        url = f"{base_url()}/buzz" if to == "buzz" else join_url()
        buf = io.BytesIO()
        segno.make(url, error="m").save(buf, kind="svg", scale=10, border=2, dark="#000", light="#fff")
        return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})

    # API ------------------------------------------------------------------------

    @app.get("/api/info")
    def info():
        p = the_party()
        return {"room_code": p["room_code"], "join_url": join_url(), "buzz_url": f"{base_url()}/buzz"}

    @app.get("/api/jeopardy/clues")
    def clues_ready():
        return {"ready": clues.is_ready(data_dir)}

    @app.post("/api/jeopardy")
    async def jeopardy_action(body: JeopardyBody):
        """Every Jeopardy control on the laptop goes through here (SPEC §6.3)."""
        party_id = the_party()["id"]
        b = body
        try:
            needs_clues = b.action in ("new", "reroll", "options", "final")
            db = await clue_conn() if needs_clues else None
            actions = {
                "new": lambda: jeopardy.new_game(conn, db, party_id, b.difficulty or jeopardy.DEFAULT_DIFFICULTY),
                "options": lambda: jeopardy.set_options(conn, db, party_id, b.left_name, b.right_name, b.difficulty),
                "reroll": lambda: jeopardy.reroll(conn, db, party_id, b.col),
                "start": lambda: jeopardy.start(conn, party_id),
                "open": lambda: jeopardy.open_clue(conn, party_id, b.clue_id),
                "buzz": lambda: jeopardy.buzz(conn, party_id, b.side),
                "clear_buzz": lambda: jeopardy.clear_buzz(conn, party_id),
                "reveal": lambda: jeopardy.reveal(conn, party_id),
                "judge": lambda: jeopardy.judge(conn, party_id, bool(b.right)),
                "no_points": lambda: jeopardy.no_points(conn, party_id),
                "undo": lambda: jeopardy.undo(conn, party_id),
                "final": lambda: jeopardy.start_final(conn, db, party_id),
                "final_clue": lambda: jeopardy.show_final_clue(conn, party_id),
                "final_reveal": lambda: jeopardy.reveal_final(conn, party_id),
                "final_score": lambda: jeopardy.score_final(conn, party_id, b.side, b.wager, bool(b.right)),
            }
            if b.action not in actions:
                return JSONResponse({"error": "bad_action", "message": f"Unknown action {b.action}."}, 400)
            actions[b.action]()
        except clues.CluesMissing as err:
            return JSONResponse({"error": "no_clues", "message": str(err)}, 503)
        except party.ActionError as err:
            return refused(err)
        await changed()
        return {"ok": True}

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
        await hub.send(screen, {"type": "state", "state": state()})
        try:
            while True:
                message = json.loads(await ws.receive_text())
                if message.get("type") == "ping":
                    await hub.send(screen, {"type": "pong"})
                elif message.get("type") == "sync":
                    await hub.send(screen, {"type": "state", "state": state()})
                elif message.get("type") == "buzz":
                    # Over the open socket, not HTTP: the fastest path from a phone.
                    try:
                        if jeopardy.buzz(conn, p["id"], message.get("side")):
                            await changed()
                    except party.ActionError:
                        pass
        except (WebSocketDisconnect, json.JSONDecodeError, RuntimeError):
            pass
        finally:
            hub.screens.discard(screen)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
