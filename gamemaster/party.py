"""Party state and actions.

Every action is one database transaction that also bumps party.version and
writes an event (SPEC §7, §7.1). Screens never hold state of their own: they
draw whatever snapshot() returns, so a refresh or a reconnect can't lose
anything.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
from dataclasses import dataclass

from .db import transaction

# No I, L, O or 0/1 lookalikes, so a code read off the TV is hard to mistype.
ROOM_CODE_LETTERS = "ABCDEFGHJKMNPQRSTUVWXYZ"
NAME_MAX = 20
TICKER_LENGTH = 8


class ActionError(Exception):
    """A refused action, with a message a phone can show as is."""

    def __init__(self, message: str, code: str = "refused", **extra):
        super().__init__(message)
        self.message = message
        self.code = code
        self.extra = extra


@dataclass
class Joined:
    player_id: int
    token: str


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def clean_name(raw: str) -> str:
    name = re.sub(r"\s+", " ", raw or "").strip()
    if not name:
        raise ActionError("Type your name first.", "bad_name")
    if len(name) > NAME_MAX:
        raise ActionError(f"Keep it to {NAME_MAX} characters.", "bad_name")
    return name


# Party ----------------------------------------------------------------------


def current_party(conn: sqlite3.Connection) -> sqlite3.Row:
    """The party in progress, created on first start."""
    row = conn.execute(
        "SELECT * FROM party WHERE status != 'finished' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row:
        return row
    code = "".join(secrets.choice(ROOM_CODE_LETTERS) for _ in range(4))
    with transaction(conn):
        party_id = conn.execute("INSERT INTO party (room_code) VALUES (?)", (code,)).lastrowid
        _event(conn, party_id, None, "party_started", "The party is open. Scan the code to join!")
    return conn.execute("SELECT * FROM party WHERE id = ?", (party_id,)).fetchone()


def check_code(party: sqlite3.Row, code: str) -> None:
    if (code or "").strip().upper() != party["room_code"]:
        raise ActionError("That room code doesn't match the TV.", "bad_code")


# Players --------------------------------------------------------------------


def player_for_token(conn: sqlite3.Connection, party_id: int, token: str | None) -> sqlite3.Row | None:
    if not token:
        return None
    return conn.execute(
        "SELECT player.*, person.name FROM player JOIN person ON person.id = player.person_id"
        " WHERE player.party_id = ? AND token_hash = ?",
        (party_id, hash_token(token)),
    ).fetchone()


def join(conn: sqlite3.Connection, party_id: int, raw_name: str) -> Joined:
    """A new player joins. A name already in the party is refused with its id,
    so the phone can offer "Is this you? Rejoin" instead."""
    name = clean_name(raw_name)
    token = secrets.token_urlsafe(24)
    with transaction(conn):
        person = conn.execute("SELECT id, name FROM person WHERE name = ?", (name,)).fetchone()
        if person:
            taken = conn.execute(
                "SELECT id FROM player WHERE party_id = ? AND person_id = ?",
                (party_id, person["id"]),
            ).fetchone()
            if taken:
                raise ActionError(
                    f"{person['name']} is already here.", "name_taken", player_id=taken["id"]
                )
            person_id = person["id"]
            name = person["name"]  # keep last year's spelling
        else:
            person_id = conn.execute("INSERT INTO person (name) VALUES (?)", (name,)).lastrowid
        player_id = conn.execute(
            "INSERT INTO player (party_id, person_id, token_hash) VALUES (?, ?, ?)",
            (party_id, person_id, hash_token(token)),
        ).lastrowid
        _event(conn, party_id, player_id, "joined", f"{name} joined", {"player_id": player_id})
    return Joined(player_id, token)


def rejoin(conn: sqlite3.Connection, party_id: int, player_id: int) -> Joined:
    """Claim an existing player from a new phone or browser (SPEC §5.1).

    The old token stops working, and the TV says so, so a mix-up is visible.
    """
    token = secrets.token_urlsafe(24)
    with transaction(conn):
        row = conn.execute(
            "SELECT person.name FROM player JOIN person ON person.id = player.person_id"
            " WHERE player.id = ? AND player.party_id = ?",
            (player_id, party_id),
        ).fetchone()
        if not row:
            raise ActionError("That player isn't in this party.", "no_player")
        conn.execute("UPDATE player SET token_hash = ? WHERE id = ?", (hash_token(token), player_id))
        _event(conn, party_id, player_id, "rejoined", f"{row['name']} rejoined from another phone",
               {"player_id": player_id})
    return Joined(player_id, token)


# Snapshot -------------------------------------------------------------------


def snapshot(conn: sqlite3.Connection, party_id: int) -> dict:
    """Everything a screen needs to draw itself. Never includes tokens."""
    party = conn.execute("SELECT * FROM party WHERE id = ?", (party_id,)).fetchone()
    players = conn.execute(
        "SELECT player.id, person.name, player.team_id, player.status"
        " FROM player JOIN person ON person.id = player.person_id"
        " WHERE player.party_id = ? ORDER BY player.id",
        (party_id,),
    ).fetchall()
    teams = conn.execute(
        "SELECT id, name, color, captain_id FROM team WHERE party_id = ? ORDER BY id", (party_id,)
    ).fetchall()
    events = conn.execute(
        "SELECT id, at, kind, text FROM event WHERE party_id = ? AND undone = 0"
        " ORDER BY id DESC LIMIT ?",
        (party_id, TICKER_LENGTH),
    ).fetchall()
    games = conn.execute("SELECT COUNT(*) FROM game WHERE active = 1").fetchone()[0]
    return {
        "version": party["version"],
        "party": {
            "room_code": party["room_code"],
            "theme": party["theme"],
            "status": party["status"],
            "rounds_planned": party["rounds_planned"],
        },
        "players": [dict(p) for p in players],
        "teams": [dict(t) for t in teams],
        "events": [dict(e) for e in events],
        "library_size": games,
    }


# Internals ------------------------------------------------------------------


def _event(conn, party_id, player_id, kind, text, data=None) -> None:
    """Log an action and bump the party version. Call inside a transaction."""
    conn.execute(
        "INSERT INTO event (party_id, player_id, kind, text, data) VALUES (?, ?, ?, ?, ?)",
        (party_id, player_id, kind, text, json.dumps(data or {})),
    )
    conn.execute("UPDATE party SET version = version + 1 WHERE id = ?", (party_id,))
