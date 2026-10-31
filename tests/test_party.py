import json

import pytest

from gamemaster import party
from gamemaster.db import connect


@pytest.fixture
def conn(tmp_path):
    return connect(tmp_path / "gm.db")


def test_first_start_creates_one_party_with_a_room_code(conn):
    p = party.current_party(conn)
    assert len(p["room_code"]) == 4
    assert set(p["room_code"]) <= set(party.ROOM_CODE_LETTERS)
    assert party.current_party(conn)["id"] == p["id"]


def test_join_returns_a_working_token_that_is_stored_hashed(conn):
    pid = party.current_party(conn)["id"]
    joined = party.join(conn, pid, "  Sam   Rivera ")
    me = party.player_for_token(conn, pid, joined.token)
    assert me["name"] == "Sam Rivera"
    stored = conn.execute("SELECT token_hash FROM player").fetchone()[0]
    assert stored != joined.token and stored == party.hash_token(joined.token)


def test_same_name_is_refused_with_the_player_id(conn):
    pid = party.current_party(conn)["id"]
    first = party.join(conn, pid, "Jordan")
    with pytest.raises(party.ActionError) as err:
        party.join(conn, pid, "jordan")
    assert err.value.code == "name_taken"
    assert err.value.extra["player_id"] == first.player_id


@pytest.mark.parametrize("name", ["", "   ", "x" * 21])
def test_bad_names_are_refused(conn, name):
    pid = party.current_party(conn)["id"]
    with pytest.raises(party.ActionError) as err:
        party.join(conn, pid, name)
    assert err.value.code == "bad_name"


def test_rejoin_replaces_the_token_and_tells_the_tv(conn):
    pid = party.current_party(conn)["id"]
    old = party.join(conn, pid, "Casey")
    new = party.rejoin(conn, pid, old.player_id)
    assert new.player_id == old.player_id
    assert party.player_for_token(conn, pid, old.token) is None
    assert party.player_for_token(conn, pid, new.token)["id"] == old.player_id
    assert party.snapshot(conn, pid)["events"][0]["text"] == "Casey rejoined from another phone"


def test_rejoin_unknown_player_is_refused(conn):
    pid = party.current_party(conn)["id"]
    with pytest.raises(party.ActionError):
        party.rejoin(conn, pid, 999)


def test_every_action_bumps_the_version(conn):
    pid = party.current_party(conn)["id"]
    v0 = party.snapshot(conn, pid)["version"]
    party.join(conn, pid, "Riley")
    v1 = party.snapshot(conn, pid)["version"]
    party.join(conn, pid, "Taylor")
    assert v0 < v1 < party.snapshot(conn, pid)["version"]


def test_snapshot_never_contains_tokens(conn):
    pid = party.current_party(conn)["id"]
    joined = party.join(conn, pid, "Drew")
    text = json.dumps(party.snapshot(conn, pid))
    assert joined.token not in text
    assert party.hash_token(joined.token) not in text


def test_everything_survives_a_restart(tmp_path):
    conn = connect(tmp_path / "gm.db")
    p = party.current_party(conn)
    joined = party.join(conn, p["id"], "Morgan")
    conn.close()

    again = connect(tmp_path / "gm.db")
    p2 = party.current_party(again)
    assert (p2["id"], p2["room_code"]) == (p["id"], p["room_code"])
    assert party.player_for_token(again, p2["id"], joined.token)["name"] == "Morgan"


def test_a_returning_name_keeps_its_first_spelling(conn):
    # People are kept across years; next year "sam" is still "Sam".
    pid = party.current_party(conn)["id"]
    party.join(conn, pid, "Sam")
    conn.execute("UPDATE party SET status = 'finished'")
    next_year = party.current_party(conn)["id"]
    party.join(conn, next_year, "sam")
    names = [p["name"] for p in party.snapshot(conn, next_year)["players"]]
    assert names == ["Sam"]
