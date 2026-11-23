"""Jeopardy: two sides, one board, buzzers (SPEC §6).

The night's other games run by hand this year, so this works on its own: no
teams or players needed, just a Left and a Right side.

How a clue goes:
    open      the clue is on the TV, both buzzers are live
    buzzed    one side rang in first and gives ONE answer out loud
    revealed  the correct response is on the TV; the laptop marks it
              right (+value) or wrong (-value), or "no points" if nobody buzzed

Every action is one transaction that bumps the party version (via party._event),
so every screen redraws and a restart loses nothing.
"""

from __future__ import annotations

import random
import sqlite3

from .db import transaction
from .party import ActionError, _event

SIDES = ("left", "right")
COLUMNS = 6
ROW_VALUES = (200, 400, 600, 800, 1000)   # what the board shows, whatever it was on air
WRONG_LOSES_POINTS = True                 # real Jeopardy rule: a wrong answer costs the value
NAME_MAX = 16
FINAL_SECONDS = 30                        # think music length

# Which real rounds each difficulty draws its columns from.
DIFFICULTY_LEVELS = {
    "easier": ["single"] * 6,
    "mixed": ["single"] * 3 + ["double"] * 3,   # the default: relatively hard
    "harder": ["double"] * 6,
}
DEFAULT_DIFFICULTY = "mixed"


# Making a board ---------------------------------------------------------------


def new_game(conn, clues, party_id: int, difficulty: str = DEFAULT_DIFFICULTY) -> int:
    """Start a fresh game in setup, with a random board. Keeps the last game's side names."""
    _check_difficulty(difficulty)
    last = current_game(conn, party_id)
    names = (last["left_name"], last["right_name"]) if last else ("Left", "Right")
    with transaction(conn):
        game_id = conn.execute(
            "INSERT INTO jeopardy_game (party_id, difficulty, left_name, right_name) VALUES (?, ?, ?, ?)",
            (party_id, difficulty, *names),
        ).lastrowid
        levels = DIFFICULTY_LEVELS[difficulty][:]
        random.shuffle(levels)   # so the harder columns aren't always on the right
        for col, level in enumerate(levels):
            _fill_column(conn, clues, game_id, col, level)
        _event(conn, party_id, None, "jeopardy_new", "Jeopardy! A new board is ready")
    return game_id


def reroll(conn, clues, party_id: int, col: int) -> None:
    """Swap one category for another of the same difficulty (setup only)."""
    game = _game(conn, party_id, "setup")
    category = conn.execute(
        "SELECT * FROM jeopardy_category WHERE game_id = ? AND col = ?", (game["id"], col)
    ).fetchone()
    if not category:
        raise ActionError("There's no such column.", "bad_column")
    with transaction(conn):
        # skip: deleting the old category frees its key, and we don't want it straight back.
        conn.execute("DELETE FROM jeopardy_category WHERE id = ?", (category["id"],))
        _fill_column(conn, clues, game["id"], col, category["level"], skip=category["source_key"])
        _event(conn, party_id, None, "jeopardy_reroll", f"New category: column {col + 1}")


def set_options(conn, clues, party_id: int, left_name=None, right_name=None, difficulty=None) -> None:
    """Rename the sides (any time), or change difficulty (setup only: makes a new board)."""
    game = _game(conn, party_id)
    if difficulty and difficulty != game["difficulty"]:
        if game["status"] != "setup":
            raise ActionError("Difficulty can only change before the board starts.", "wrong_step")
        _check_difficulty(difficulty)
        new_game(conn, clues, party_id, difficulty)
        game = _game(conn, party_id)
    names = {}
    for side, raw in (("left", left_name), ("right", right_name)):
        if raw is not None:
            names[side] = _clean_side_name(raw)
    if names:
        with transaction(conn):
            for side, name in names.items():
                conn.execute(f"UPDATE jeopardy_game SET {side}_name = ? WHERE id = ?", (name, game["id"]))
            _event(conn, party_id, None, "jeopardy_names", "Jeopardy sides renamed")


def start(conn, party_id: int) -> None:
    game = _game(conn, party_id, "setup")
    with transaction(conn):
        conn.execute("UPDATE jeopardy_game SET status = 'board' WHERE id = ?", (game["id"],))
        _event(conn, party_id, None, "jeopardy_start",
               f"Jeopardy: {game['left_name']} vs {game['right_name']}")


# Playing a clue ---------------------------------------------------------------


def open_clue(conn, party_id: int, clue_id: int) -> None:
    game = _game(conn, party_id, "board")
    if game["clue_id"] is not None:
        raise ActionError("Finish the clue on screen first.", "clue_open")
    clue = conn.execute(
        "SELECT jeopardy_clue.* FROM jeopardy_clue JOIN jeopardy_category c ON c.id = category_id"
        " WHERE jeopardy_clue.id = ? AND c.game_id = ?",
        (clue_id, game["id"]),
    ).fetchone()
    if not clue:
        raise ActionError("That clue isn't on this board.", "bad_clue")
    if clue["done"]:
        raise ActionError("That clue was already played.", "clue_done")
    with transaction(conn):
        conn.execute(
            "UPDATE jeopardy_game SET clue_id = ?, clue_phase = 'open', buzzed_side = NULL WHERE id = ?",
            (clue_id, game["id"]),
        )
        _event(conn, party_id, None, "jeopardy_clue", f"Jeopardy: ${clue['value']} clue")


def buzz(conn, party_id: int, side: str) -> bool:
    """First side in gets it. Returns False (and changes nothing) for any later buzz."""
    _check_side(side)
    with transaction(conn):
        game = current_game(conn, party_id)
        if not game or game["status"] != "board" or game["clue_phase"] != "open":
            return False
        conn.execute(
            "UPDATE jeopardy_game SET clue_phase = 'buzzed', buzzed_side = ? WHERE id = ?",
            (side, game["id"]),
        )
        _event(conn, party_id, None, "jeopardy_buzz", f"{game[side + '_name']} buzzed in")
    return True


def clear_buzz(conn, party_id: int) -> None:
    """An accidental buzz: open the buzzers again."""
    game = _game(conn, party_id, "board")
    if game["clue_phase"] != "buzzed":
        raise ActionError("Nobody has buzzed.", "wrong_step")
    with transaction(conn):
        conn.execute(
            "UPDATE jeopardy_game SET clue_phase = 'open', buzzed_side = NULL WHERE id = ?", (game["id"],)
        )
        _event(conn, party_id, None, "jeopardy_unbuzz", "Buzzers open again")


def reveal(conn, party_id: int) -> None:
    game = _game(conn, party_id, "board")
    if game["clue_phase"] not in ("open", "buzzed"):
        raise ActionError("There's no clue to reveal.", "wrong_step")
    with transaction(conn):
        conn.execute("UPDATE jeopardy_game SET clue_phase = 'revealed' WHERE id = ?", (game["id"],))
        _event(conn, party_id, None, "jeopardy_reveal", "Jeopardy: the answer is up")


def judge(conn, party_id: int, right: bool) -> None:
    """Mark the side that buzzed right or wrong, after the reveal."""
    game = _game(conn, party_id, "board")
    if game["clue_phase"] != "revealed" or not game["buzzed_side"]:
        raise ActionError("Reveal the answer first, after someone buzzes.", "wrong_step")
    clue = conn.execute("SELECT * FROM jeopardy_clue WHERE id = ?", (game["clue_id"],)).fetchone()
    side = game["buzzed_side"]
    delta = clue["value"] if right else (-clue["value"] if WRONG_LOSES_POINTS else 0)
    with transaction(conn):
        if delta:
            conn.execute(
                "INSERT INTO jeopardy_score (game_id, side, delta, clue_id) VALUES (?, ?, ?, ?)",
                (game["id"], side, delta, clue["id"]),
            )
        _finish_clue(conn, game["id"], clue["id"])
        sign = "+" if delta >= 0 else "−"
        _event(conn, party_id, None, "jeopardy_score", f"{game[side + '_name']} {sign}${abs(delta)}")


def no_points(conn, party_id: int) -> None:
    """Nobody buzzed (or nobody knew): back to the board."""
    game = _game(conn, party_id, "board")
    if game["clue_phase"] != "revealed" or game["buzzed_side"]:
        raise ActionError("Reveal the answer first. If someone buzzed, mark them right or wrong.",
                          "wrong_step")
    with transaction(conn):
        _finish_clue(conn, game["id"], game["clue_id"])
        _event(conn, party_id, None, "jeopardy_pass", "Nobody got that one")


def undo(conn, party_id: int) -> None:
    """Take back the last score: the clue (or Final Jeopardy) comes back to be marked again."""
    game = _game(conn, party_id)
    last = conn.execute(
        "SELECT * FROM jeopardy_score WHERE game_id = ? AND undone = 0 ORDER BY id DESC LIMIT 1",
        (game["id"],),
    ).fetchone()
    if not last:
        raise ActionError("Nothing to undo.", "nothing_to_undo")
    if last["clue_id"] is not None and (game["status"] != "board" or game["clue_id"] is not None):
        raise ActionError("Undo works from the board, with no clue open.", "wrong_step")
    with transaction(conn):
        conn.execute("UPDATE jeopardy_score SET undone = 1 WHERE id = ?", (last["id"],))
        if last["clue_id"] is not None:
            conn.execute("UPDATE jeopardy_clue SET done = 0 WHERE id = ?", (last["clue_id"],))
            conn.execute(
                "UPDATE jeopardy_game SET clue_id = ?, clue_phase = 'revealed', buzzed_side = ? WHERE id = ?",
                (last["clue_id"], last["side"], game["id"]),
            )
        else:
            conn.execute(
                "UPDATE jeopardy_game SET status = 'final', final_phase = 'revealed' WHERE id = ?",
                (game["id"],),
            )
        _event(conn, party_id, None, "jeopardy_undo", f"Undid {game[last['side'] + '_name']}'s last score")


# Final Jeopardy -----------------------------------------------------------------


def start_final(conn, clues, party_id: int) -> None:
    """Show the Final Jeopardy category. Allowed any time on the board (parties run late)."""
    game = _game(conn, party_id, "board")
    if game["clue_id"] is not None:
        raise ActionError("Finish the clue on screen first.", "clue_open")
    used = {r[0] for r in conn.execute("SELECT final_key FROM jeopardy_game WHERE final_key IS NOT NULL")}
    rows = clues.execute("SELECT * FROM final ORDER BY random() LIMIT 20").fetchall()
    final = next((r for r in rows if r["key"] not in used), None)
    if not final:
        raise ActionError("Couldn't find a Final Jeopardy clue.", "no_final")
    with transaction(conn):
        conn.execute(
            "UPDATE jeopardy_game SET status = 'final', final_phase = 'category', final_key = ?,"
            " final_category = ?, final_text = ?, final_response = ? WHERE id = ?",
            (final["key"], final["category"], final["text"], final["response"], game["id"]),
        )
        _event(conn, party_id, None, "jeopardy_final", "Final Jeopardy! Write down your wagers")


def show_final_clue(conn, party_id: int) -> None:
    game = _game(conn, party_id, "final")
    if game["final_phase"] != "category":
        raise ActionError("The clue is already up.", "wrong_step")
    with transaction(conn):
        conn.execute(
            "UPDATE jeopardy_game SET final_phase = 'clue', final_clue_at = datetime('now') WHERE id = ?",
            (game["id"],),
        )
        _event(conn, party_id, None, "jeopardy_final_clue", "Final Jeopardy: write your answers")


def reveal_final(conn, party_id: int) -> None:
    game = _game(conn, party_id, "final")
    if game["final_phase"] != "clue":
        raise ActionError("Show the clue first.", "wrong_step")
    with transaction(conn):
        conn.execute("UPDATE jeopardy_game SET final_phase = 'revealed' WHERE id = ?", (game["id"],))
        _event(conn, party_id, None, "jeopardy_final_reveal", "Final Jeopardy: the answer is up")


def score_final(conn, party_id: int, side: str, wager: int, right: bool) -> None:
    """Enter one side's written wager and whether their written answer was right."""
    _check_side(side)
    game = _game(conn, party_id, "final")
    if game["final_phase"] != "revealed":
        raise ActionError("Reveal the answer first.", "wrong_step")
    if _final_scored(conn, game["id"], side):
        raise ActionError("That side is already scored. Undo to change it.", "already_scored")
    most = max(scores(conn, game["id"])[side], 0)
    if not isinstance(wager, int) or wager < 0 or wager > most:
        raise ActionError(f"{game[side + '_name']} can wager $0 to ${most}.", "bad_wager", most=most)
    delta = wager if right else -wager
    with transaction(conn):
        conn.execute(
            "INSERT INTO jeopardy_score (game_id, side, delta) VALUES (?, ?, ?)", (game["id"], side, delta)
        )
        if all(_final_scored(conn, game["id"], s) for s in SIDES):
            conn.execute("UPDATE jeopardy_game SET status = 'done' WHERE id = ?", (game["id"],))
        sign = "+" if delta >= 0 else "−"
        _event(conn, party_id, None, "jeopardy_final_score",
               f"Final Jeopardy: {game[side + '_name']} {sign}${abs(delta)}")


# Reading state ------------------------------------------------------------------


def current_game(conn, party_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM jeopardy_game WHERE party_id = ? ORDER BY id DESC LIMIT 1", (party_id,)
    ).fetchone()


def scores(conn, game_id: int) -> dict[str, int]:
    totals = dict.fromkeys(SIDES, 0)
    for row in conn.execute(
        "SELECT side, SUM(delta) AS total FROM jeopardy_score WHERE game_id = ? AND undone = 0 GROUP BY side",
        (game_id,),
    ):
        totals[row["side"]] = row["total"]
    return totals


def view(conn, party_id: int) -> dict | None:
    """What the screens draw. Responses are only included once revealed."""
    game = current_game(conn, party_id)
    if not game:
        return None
    totals = scores(conn, game["id"])
    categories = []
    for cat in conn.execute(
        "SELECT * FROM jeopardy_category WHERE game_id = ? ORDER BY col", (game["id"],)
    ):
        clues = conn.execute(
            "SELECT id, row, value, done FROM jeopardy_clue WHERE category_id = ? ORDER BY row", (cat["id"],)
        ).fetchall()
        categories.append({
            "col": cat["col"], "name": cat["name"], "note": cat["note"],
            "clues": [{"id": c["id"], "value": c["value"], "done": bool(c["done"])} for c in clues],
        })
    clue = None
    if game["clue_id"] is not None:
        row = conn.execute(
            "SELECT jeopardy_clue.*, c.name AS category, c.note FROM jeopardy_clue"
            " JOIN jeopardy_category c ON c.id = category_id WHERE jeopardy_clue.id = ?",
            (game["clue_id"],),
        ).fetchone()
        clue = {
            "id": row["id"], "category": row["category"], "note": row["note"], "value": row["value"],
            "text": row["text"], "phase": game["clue_phase"], "buzzed": game["buzzed_side"],
            "response": row["response"] if game["clue_phase"] == "revealed" else None,
        }
    final = None
    if game["final_phase"]:
        phase = game["final_phase"]
        final = {
            "phase": phase,
            "category": game["final_category"],
            "text": game["final_text"] if phase in ("clue", "revealed") else None,
            "response": game["final_response"] if phase == "revealed" else None,
            "seconds": FINAL_SECONDS,
            # Counted on the server, so a refreshed TV shows the same countdown.
            "seconds_left": _seconds_left(conn, game["final_clue_at"]) if phase == "clue" else None,
            "scored": {s: _final_scored(conn, game["id"], s) for s in SIDES},
            "max_wager": {s: max(totals[s], 0) for s in SIDES},
        }
    left_to_play = conn.execute(
        "SELECT COUNT(*) FROM jeopardy_clue JOIN jeopardy_category c ON c.id = category_id"
        " WHERE c.game_id = ? AND done = 0",
        (game["id"],),
    ).fetchone()[0]
    can_undo = conn.execute(
        "SELECT 1 FROM jeopardy_score WHERE game_id = ? AND undone = 0 LIMIT 1", (game["id"],)
    ).fetchone() is not None
    return {
        "id": game["id"],
        "status": game["status"],
        "difficulty": game["difficulty"],
        "sides": [{"side": s, "name": game[s + "_name"], "score": totals[s]} for s in SIDES],
        "categories": categories,
        "clue": clue,
        "final": final,
        "clues_left": left_to_play,
        "can_undo": can_undo,
    }


# Internals ----------------------------------------------------------------------


def _game(conn, party_id: int, *statuses: str) -> sqlite3.Row:
    game = current_game(conn, party_id)
    if not game:
        raise ActionError("Start a Jeopardy board first.", "no_game")
    if statuses and game["status"] not in statuses:
        raise ActionError("That doesn't work right now.", "wrong_step", status=game["status"])
    return game


def _fill_column(conn, clues, game_id: int, col: int, level: str, skip: str | None = None) -> None:
    """Copy one random real category (never used before, no repeated name) into the board."""
    used = {r[0] for r in conn.execute("SELECT source_key FROM jeopardy_category")}
    if skip:
        used.add(skip)
    names = {r[0].casefold() for r in conn.execute(
        "SELECT name FROM jeopardy_category WHERE game_id = ?", (game_id,))}
    candidates = clues.execute(
        "SELECT * FROM category WHERE level = ? ORDER BY random() LIMIT 50", (level,)
    ).fetchall()
    pick = next((c for c in candidates if c["key"] not in used and c["name"].casefold() not in names), None)
    if not pick:
        raise ActionError("Ran out of new categories. Try another difficulty.", "no_categories")
    category_id = conn.execute(
        "INSERT INTO jeopardy_category (game_id, col, source_key, level, name, note) VALUES (?, ?, ?, ?, ?, ?)",
        (game_id, col, pick["key"], level, pick["name"], pick["note"]),
    ).lastrowid
    for clue in clues.execute("SELECT * FROM clue WHERE category_id = ? ORDER BY row", (pick["id"],)):
        conn.execute(
            "INSERT INTO jeopardy_clue (category_id, row, value, text, response) VALUES (?, ?, ?, ?, ?)",
            (category_id, clue["row"], ROW_VALUES[clue["row"] - 1], clue["text"], clue["response"]),
        )


def _finish_clue(conn, game_id: int, clue_id: int) -> None:
    conn.execute("UPDATE jeopardy_clue SET done = 1 WHERE id = ?", (clue_id,))
    conn.execute(
        "UPDATE jeopardy_game SET clue_id = NULL, clue_phase = NULL, buzzed_side = NULL WHERE id = ?",
        (game_id,),
    )


def _seconds_left(conn, started_at: str | None) -> int:
    if not started_at:
        return FINAL_SECONDS
    elapsed = conn.execute("SELECT strftime('%s', 'now') - strftime('%s', ?)", (started_at,)).fetchone()[0]
    return max(FINAL_SECONDS - int(elapsed), 0)


def _final_scored(conn, game_id: int, side: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM jeopardy_score WHERE game_id = ? AND side = ? AND clue_id IS NULL AND undone = 0",
        (game_id, side),
    ).fetchone() is not None


def _check_side(side: str) -> None:
    if side not in SIDES:
        raise ActionError("Side must be left or right.", "bad_side")


def _check_difficulty(difficulty: str) -> None:
    if difficulty not in DIFFICULTY_LEVELS:
        raise ActionError("Difficulty must be easier, mixed or harder.", "bad_difficulty")


def _clean_side_name(raw: str) -> str:
    name = " ".join((raw or "").split())
    if not name:
        raise ActionError("Give the side a name.", "bad_name")
    if len(name) > NAME_MAX:
        raise ActionError(f"Keep side names to {NAME_MAX} characters.", "bad_name")
    return name
