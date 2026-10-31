from pathlib import Path

import pytest

from gamemaster import library
from gamemaster.db import connect

STARTER = Path(__file__).resolve().parent.parent / "games" / "starter.yaml"


def write(tmp_path, text):
    path = tmp_path / "games.yaml"
    path.write_text(text)
    return path


def test_starter_list_is_valid():
    games = library.read_file(STARTER)
    assert len(games) >= 10
    assert any(g.name == "Flip Cup" for g in games)


@pytest.mark.parametrize(
    "body, problem",
    [
        ("formats: [{kind: creative}]", "creative game must be decided_by"),
        ("formats: [{kind: nvn}, {kind: nvn}]", "only be listed once"),
        ("formats: [{kind: team, per_side: [1, 2]}]", "per_side only applies"),
        ("formats: [{kind: nvn, per_side: [3, 1]}]", "min <= max"),
        ("formats: []", "at least 1"),
        ("formats: [{kind: dance_off}]", "kind"),
    ],
)
def test_bad_games_are_explained(tmp_path, body, problem):
    path = write(tmp_path, f"- name: Thing\n  energy: hype\n  size: small\n  {body}\n")
    with pytest.raises(ValueError) as err:
        library.read_file(path)
    assert problem in str(err.value)
    assert "Thing" in str(err.value)


def test_import_stores_formats_tags_and_default_version(tmp_path):
    conn = connect(tmp_path / "gm.db")
    library.import_games(conn, library.read_file(STARTER))
    flip = conn.execute("SELECT id FROM game WHERE name = 'flip cup'").fetchone()["id"]
    kinds = {r["kind"] for r in conn.execute("SELECT kind FROM game_format WHERE game_id = ?", (flip,))}
    assert kinds == {"team", "split", "nvn"}
    default = conn.execute(
        "SELECT name FROM game_version WHERE game_id = ? AND is_default = 1", (flip,)
    ).fetchall()
    assert [r["name"] for r in default] == ["Water"]
    tag = conn.execute("SELECT * FROM game_tag WHERE game_id = ?", (flip,)).fetchone()
    assert (tag["energy"], tag["size"], tag["showdown"]) == ("hype", "big", 1)


def test_reimport_updates_instead_of_duplicating(tmp_path):
    conn = connect(tmp_path / "gm.db")
    games = library.read_file(STARTER)
    library.import_games(conn, games)
    library.import_games(conn, games)
    assert conn.execute("SELECT COUNT(*) FROM game").fetchone()[0] == len(games)


def test_first_version_is_default_when_none_is_marked(tmp_path):
    conn = connect(tmp_path / "gm.db")
    path = write(tmp_path, """
- name: Duel
  energy: hype
  size: small
  formats: [{kind: nvn, per_side: [1, 1]}]
  versions: [{name: No beer}, {name: Classic}]
""")
    library.import_games(conn, library.read_file(path))
    rows = conn.execute("SELECT name, is_default FROM game_version ORDER BY id").fetchall()
    assert [(r["name"], r["is_default"]) for r in rows] == [("No beer", 1), ("Classic", 0)]


def test_seed_prefers_the_groups_own_list(tmp_path):
    conn = connect(tmp_path / "gm.db")
    write(tmp_path, "- name: Our Game\n  energy: chill\n  size: small\n  formats: [{kind: ffa}]\n")
    assert library.seed_if_empty(conn, tmp_path, STARTER) == 1
    assert library.seed_if_empty(conn, tmp_path, STARTER) == 0  # only when empty
    names = [r["name"] for r in conn.execute("SELECT name FROM game")]
    assert names == ["Our Game"]
