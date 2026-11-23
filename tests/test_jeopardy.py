"""Jeopardy: the clue import, the game rules, and the buzzers (SPEC §6).

Uses a small made-up clue file in the dataset's format, never real clues.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from gamemaster import clues, jeopardy
from gamemaster.app import create_app
from gamemaster.db import connect
from gamemaster.party import ActionError, current_party

HEADER = "round\tclue_value\tdaily_double_value\tcategory\tcomments\tanswer\tquestion\tair_date\tnotes\n"


def category_rows(rnd, name, date, values, notes="", comments="", first_answer=None):
    rows = []
    for i, value in enumerate(values):
        answer = first_answer if (i == 0 and first_answer) else f"{name} clue {i + 1}"
        rows.append(f"{rnd}\t{value}\t0\t{name}\t{comments}\t{answer}\t{name} response {i + 1}\t{date}\t{notes}\n")
    return rows


def write_dataset(path):
    lines = [HEADER]
    for n in range(12):
        lines += category_rows(1, f"SINGLE {n}", f"2020-01-{n + 1:02d}", [200, 400, 600, 800, 1000])
        lines += category_rows(2, f"DOUBLE {n}", f"2020-01-{n + 1:02d}", [400, 800, 1200, 1600, 2000])
    for n in range(4):
        lines.append(f"3\t0\t0\tFINAL {n}\t\tFinal clue {n}\tFinal response {n}\t2021-02-{n + 1:02d}\t\n")
    # Should all be dropped:
    lines += category_rows(1, "TOO OLD", "2010-05-05", [200, 400, 600, 800, 1000])
    lines += category_rows(1, "TOURNAMENT", "2020-03-03", [200, 400, 600, 800, 1000], notes="Teen Tournament game 1.")
    lines += category_rows(1, "MISSING ONE", "2020-03-04", [200, 400, 600, 800])
    lines += category_rows(1, "VIDEO", "2020-03-05", [200, 400, 600, 800, 1000],
                           first_answer="(Sam of the Clue Crew shows a map.) This river")
    # Kept, with its quirks cleaned up:
    lines += category_rows(1, '\\"O" SAY\\"', "2020-03-06", [200, 400, 600, 800, 1000],
                           comments="(Alex: Each response starts with O.)")
    path.write_text("".join(lines), encoding="utf-8")


@pytest.fixture
def data_dir(tmp_path):
    tsv = tmp_path / "set.tsv"
    write_dataset(tsv)
    clues.import_tsv(tsv, tmp_path, source="test")
    return tmp_path


@pytest.fixture
def game(data_dir):
    conn = connect(data_dir / "gamemaster.db")
    clue_db = clues.open_clues(data_dir)
    party_id = current_party(conn)["id"]
    return conn, clue_db, party_id


def first_clue(conn, party_id, row=0):
    view = jeopardy.view(conn, party_id)
    return view["categories"][0]["clues"][row]


# Import ----------------------------------------------------------------------


def test_import_keeps_only_full_recent_regular_categories(data_dir):
    db = sqlite3.connect(clues.db_path(data_dir))
    names = {r[0] for r in db.execute("SELECT name FROM category")}
    assert len([n for n in names if n.startswith("SINGLE")]) == 12
    assert not names & {"TOO OLD", "TOURNAMENT", "MISSING ONE", "VIDEO"}
    assert db.execute("SELECT COUNT(*) FROM final").fetchone()[0] == 4
    assert db.execute("SELECT COUNT(*) FROM clue").fetchone()[0] == 25 * 5


def test_import_cleans_escapes_and_host_notes(data_dir):
    db = sqlite3.connect(clues.db_path(data_dir))
    name, note = db.execute("SELECT name, note FROM category WHERE name LIKE '%SAY%'").fetchone()
    assert name == '"O" SAY"'
    assert note == "Each response starts with O."


# Board -----------------------------------------------------------------------


def test_mixed_board_has_three_of_each_and_board_values(game):
    conn, db, party_id = game
    jeopardy.new_game(conn, db, party_id)
    view = jeopardy.view(conn, party_id)
    names = [c["name"] for c in view["categories"]]
    assert len(names) == 6
    assert sum(n.startswith("DOUBLE") for n in names) == 3
    assert all([c["value"] for c in cat["clues"]] == [200, 400, 600, 800, 1000] for cat in view["categories"])


def test_setup_never_sends_clue_text(game):
    conn, db, party_id = game
    jeopardy.new_game(conn, db, party_id)
    view = jeopardy.view(conn, party_id)
    assert "clue 1" not in str(view)
    assert view["clue"] is None


def test_reroll_swaps_one_category_for_a_new_one_of_the_same_level(game):
    conn, db, party_id = game
    jeopardy.new_game(conn, db, party_id, "harder")
    before = [c["name"] for c in jeopardy.view(conn, party_id)["categories"]]
    jeopardy.reroll(conn, db, party_id, 2)
    after = [c["name"] for c in jeopardy.view(conn, party_id)["categories"]]
    assert after[2] != before[2] and after[2].startswith("DOUBLE")
    assert after[:2] == before[:2] and after[3:] == before[3:]
    assert len(set(after)) == 6


def test_categories_never_repeat_across_boards(game):
    conn, db, party_id = game
    seen = []
    for _ in range(2):
        jeopardy.new_game(conn, db, party_id, "easier")
        seen += [c["name"] for c in jeopardy.view(conn, party_id)["categories"]]
    assert len(seen) == len(set(seen)) == 12
    with pytest.raises(ActionError):  # only 13 single categories exist
        jeopardy.new_game(conn, db, party_id, "easier")


# Playing ---------------------------------------------------------------------


def started(game, left="Sharks", right="Jets"):
    conn, db, party_id = game
    jeopardy.new_game(conn, db, party_id)
    jeopardy.set_options(conn, db, party_id, left_name=left, right_name=right)
    jeopardy.start(conn, party_id)
    return conn, db, party_id


def test_first_buzz_wins_and_response_hidden_until_reveal(game):
    conn, _, party_id = started(game)
    clue = first_clue(conn, party_id, 2)
    jeopardy.open_clue(conn, party_id, clue["id"])
    view = jeopardy.view(conn, party_id)
    assert view["clue"]["text"].endswith("clue 3") and view["clue"]["response"] is None
    assert jeopardy.buzz(conn, party_id, "right") is True
    assert jeopardy.buzz(conn, party_id, "left") is False
    assert jeopardy.view(conn, party_id)["clue"]["buzzed"] == "right"
    with pytest.raises(ActionError):
        jeopardy.judge(conn, party_id, True)   # must reveal first
    jeopardy.reveal(conn, party_id)
    assert jeopardy.view(conn, party_id)["clue"]["response"].endswith("response 3")
    jeopardy.judge(conn, party_id, True)
    view = jeopardy.view(conn, party_id)
    assert {s["side"]: s["score"] for s in view["sides"]} == {"left": 0, "right": 600}
    assert view["clue"] is None and view["categories"][0]["clues"][2]["done"]
    assert view["clues_left"] == 29


def test_wrong_answer_costs_the_value(game):
    conn, _, party_id = started(game)
    jeopardy.open_clue(conn, party_id, first_clue(conn, party_id, 4)["id"])
    jeopardy.buzz(conn, party_id, "left")
    jeopardy.reveal(conn, party_id)
    jeopardy.judge(conn, party_id, False)
    assert jeopardy.scores(conn, jeopardy.current_game(conn, party_id)["id"])["left"] == -1000


def test_nobody_buzzes_no_points(game):
    conn, _, party_id = started(game)
    jeopardy.open_clue(conn, party_id, first_clue(conn, party_id)["id"])
    with pytest.raises(ActionError):
        jeopardy.no_points(conn, party_id)     # reveal first
    jeopardy.reveal(conn, party_id)
    assert jeopardy.buzz(conn, party_id, "left") is False   # too late
    jeopardy.no_points(conn, party_id)
    view = jeopardy.view(conn, party_id)
    assert view["clue"] is None and all(s["score"] == 0 for s in view["sides"])


def test_cancel_buzz_reopens(game):
    conn, _, party_id = started(game)
    jeopardy.open_clue(conn, party_id, first_clue(conn, party_id)["id"])
    jeopardy.buzz(conn, party_id, "left")
    jeopardy.clear_buzz(conn, party_id)
    assert jeopardy.buzz(conn, party_id, "right") is True


def test_one_clue_at_a_time_and_no_replays(game):
    conn, _, party_id = started(game)
    clue = first_clue(conn, party_id)
    jeopardy.open_clue(conn, party_id, clue["id"])
    with pytest.raises(ActionError):
        jeopardy.open_clue(conn, party_id, first_clue(conn, party_id, 1)["id"])
    jeopardy.reveal(conn, party_id)
    jeopardy.no_points(conn, party_id)
    with pytest.raises(ActionError):
        jeopardy.open_clue(conn, party_id, clue["id"])


def test_undo_brings_the_clue_back_to_be_marked_again(game):
    conn, _, party_id = started(game)
    jeopardy.open_clue(conn, party_id, first_clue(conn, party_id, 1)["id"])
    jeopardy.buzz(conn, party_id, "left")
    jeopardy.reveal(conn, party_id)
    jeopardy.judge(conn, party_id, False)
    jeopardy.undo(conn, party_id)
    view = jeopardy.view(conn, party_id)
    assert view["sides"][0]["score"] == 0
    assert view["clue"]["phase"] == "revealed" and view["clue"]["buzzed"] == "left"
    jeopardy.judge(conn, party_id, True)
    assert jeopardy.view(conn, party_id)["sides"][0]["score"] == 400


def test_final_jeopardy_wagers_and_winner(game):
    conn, db, party_id = started(game)
    jeopardy.open_clue(conn, party_id, first_clue(conn, party_id, 4)["id"])
    jeopardy.buzz(conn, party_id, "left")
    jeopardy.reveal(conn, party_id)
    jeopardy.judge(conn, party_id, True)              # left 1000, right 0

    jeopardy.start_final(conn, db, party_id)
    view = jeopardy.view(conn, party_id)
    assert view["status"] == "final" and view["final"]["text"] is None
    assert view["final"]["max_wager"] == {"left": 1000, "right": 0}
    jeopardy.show_final_clue(conn, party_id)
    assert jeopardy.view(conn, party_id)["final"]["seconds_left"] == jeopardy.FINAL_SECONDS
    assert jeopardy.view(conn, party_id)["final"]["response"] is None
    jeopardy.reveal_final(conn, party_id)

    with pytest.raises(ActionError):
        jeopardy.score_final(conn, party_id, "left", 1001, True)
    jeopardy.score_final(conn, party_id, "left", 700, False)
    with pytest.raises(ActionError):
        jeopardy.score_final(conn, party_id, "left", 100, True)   # once per side
    jeopardy.score_final(conn, party_id, "right", 0, True)
    view = jeopardy.view(conn, party_id)
    assert view["status"] == "done"
    assert [s["score"] for s in view["sides"]] == [300, 0]

    jeopardy.undo(conn, party_id)                     # right's final entry comes back
    view = jeopardy.view(conn, party_id)
    assert view["status"] == "final" and view["final"]["scored"] == {"left": True, "right": False}


def test_game_survives_a_restart(data_dir):
    conn = connect(data_dir / "gamemaster.db")
    db = clues.open_clues(data_dir)
    party_id = current_party(conn)["id"]
    jeopardy.new_game(conn, db, party_id)
    jeopardy.start(conn, party_id)
    jeopardy.open_clue(conn, party_id, first_clue(conn, party_id)["id"])
    jeopardy.buzz(conn, party_id, "right")
    conn.close()

    conn = connect(data_dir / "gamemaster.db")
    view = jeopardy.view(conn, current_party(conn)["id"])
    assert view["clue"]["buzzed"] == "right"


# Through the server ----------------------------------------------------------


def read_state(ws):
    while True:
        msg = ws.receive_json()
        if msg["type"] == "state":
            return msg["state"]


def test_pages_and_buzz_qr(data_dir):
    with TestClient(create_app(data_dir=data_dir, port=8765)) as client:
        assert client.get("/jeopardy").status_code == 200
        assert client.get("/buzz").status_code == 200
        assert client.get("/qr.svg?to=buzz").status_code == 200
        assert client.get("/api/info").json()["buzz_url"].endswith("/buzz")
        assert client.get("/api/jeopardy/clues").json() == {"ready": True}


def test_phone_buzz_over_websocket(data_dir):
    with TestClient(create_app(data_dir=data_dir, port=8765)) as client:
        post = lambda **body: client.post("/api/jeopardy", json=body)
        assert post(action="new").status_code == 200
        assert post(action="options", left_name="Sharks").status_code == 200
        assert post(action="start").status_code == 200
        with client.websocket_connect("/ws") as phone:
            state = read_state(phone)
            assert state["jeopardy"]["sides"][0]["name"] == "Sharks"
            clue_id = state["jeopardy"]["categories"][0]["clues"][0]["id"]
            assert post(action="open", clue_id=clue_id).status_code == 200
            assert read_state(phone)["jeopardy"]["clue"]["phase"] == "open"
            phone.send_json({"type": "buzz", "side": "left"})
            assert read_state(phone)["jeopardy"]["clue"]["buzzed"] == "left"
        res = post(action="judge", right=True)
        assert res.status_code == 409 and "Reveal" in res.json()["message"]
        assert post(action="nope").status_code == 400


def test_missing_clues_and_no_internet_gives_a_clear_message(tmp_path, monkeypatch):
    def offline(*_):
        raise OSError("no network")

    monkeypatch.setattr(clues.urllib.request, "urlretrieve", offline)
    with TestClient(create_app(data_dir=tmp_path, port=8765)) as client:
        assert client.get("/api/jeopardy/clues").json() == {"ready": False}
        res = client.post("/api/jeopardy", json={"action": "new"})
        assert res.status_code == 503 and "internet" in res.json()["message"]
