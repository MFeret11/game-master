"""The game library: load games from YAML into the database (SPEC §5.2).

The repo ships a generic starter list in games/starter.yaml. A group's own
list goes in data/games.yaml, which is never committed. On first start the
app imports data/games.yaml if it exists, otherwise the starter list.

Check a file without importing it:

    uv run python -m gamemaster.library check data/games.yaml
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

from .db import transaction

FormatKind = Literal["nvn", "split", "team", "all_teams", "ffa", "creative"]


class Format(BaseModel, extra="forbid"):
    kind: FormatKind
    # [min, max] players per side, for NvN. [1, 1] is a 1v1 only.
    per_side: tuple[int, int] | None = None
    # [min, max] players in the whole game (e.g. only 8 balloons).
    players: tuple[int, int] | None = None

    @model_validator(mode="after")
    def _ranges(self) -> "Format":
        for label, pair in (("per_side", self.per_side), ("players", self.players)):
            if pair and not (1 <= pair[0] <= pair[1]):
                raise ValueError(f"{label} must be [min, max] with 1 <= min <= max")
        if self.per_side and self.kind != "nvn":
            raise ValueError("per_side only applies to the nvn format")
        return self


class Version(BaseModel, extra="forbid"):
    name: str
    rules: str = ""
    default: bool = False


class Game(BaseModel, extra="forbid"):
    name: str = Field(min_length=1)
    rules: str = ""
    decided_by: Literal["played", "judged", "room"] = "played"
    energy: Literal["hype", "medium", "chill"]
    size: Literal["big", "small"]
    showdown: bool = False
    formats: list[Format] = Field(min_length=1)
    versions: list[Version] = []
    notes: str = ""

    @model_validator(mode="after")
    def _consistent(self) -> "Game":
        kinds = [f.kind for f in self.formats]
        if len(kinds) != len(set(kinds)):
            raise ValueError("each format kind can only be listed once")
        if "creative" in kinds and self.decided_by == "played":
            raise ValueError("a creative game must be decided_by judged or room")
        if sum(v.default for v in self.versions) > 1:
            raise ValueError("only one version can be the default")
        names = [v.name.lower() for v in self.versions]
        if len(names) != len(set(names)):
            raise ValueError("version names must be different")
        return self


def read_file(path: str | Path) -> list[Game]:
    """Parse and check a games file. Raises ValueError with readable messages."""
    raw = yaml.safe_load(Path(path).read_text()) or []
    if not isinstance(raw, list):
        raise ValueError(f"{path}: expected a list of games")
    games, problems = [], []
    for i, item in enumerate(raw, start=1):
        label = item.get("name", f"game #{i}") if isinstance(item, dict) else f"game #{i}"
        try:
            games.append(Game.model_validate(item))
        except ValidationError as err:
            for e in err.errors():
                where = ".".join(str(p) for p in e["loc"]) or "game"
                problems.append(f"{label}: {where}: {e['msg']}")
    seen: set[str] = set()
    for g in games:
        if g.name.lower() in seen:
            problems.append(f"{g.name}: listed twice")
        seen.add(g.name.lower())
    if problems:
        raise ValueError(f"{path}:\n  " + "\n  ".join(problems))
    return games


def import_games(conn: sqlite3.Connection, games: list[Game]) -> int:
    """Insert or update games by name. Returns how many were written."""
    with transaction(conn):
        for g in games:
            row = conn.execute("SELECT id FROM game WHERE name = ?", (g.name,)).fetchone()
            if row:
                game_id = row["id"]
                conn.execute(
                    "UPDATE game SET rules = ?, decided_by = ?, notes = ?, active = 1 WHERE id = ?",
                    (g.rules, g.decided_by, g.notes, game_id),
                )
                for table in ("game_format", "game_version", "game_tag"):
                    conn.execute(f"DELETE FROM {table} WHERE game_id = ?", (game_id,))
            else:
                game_id = conn.execute(
                    "INSERT INTO game (name, rules, decided_by, notes) VALUES (?, ?, ?, ?)",
                    (g.name, g.rules, g.decided_by, g.notes),
                ).lastrowid
            conn.execute(
                "INSERT INTO game_tag (game_id, energy, size, showdown) VALUES (?, ?, ?, ?)",
                (game_id, g.energy, g.size, int(g.showdown)),
            )
            for f in g.formats:
                side = f.per_side or (None, None)
                total = f.players or (None, None)
                conn.execute(
                    "INSERT INTO game_format (game_id, kind, min_per_side, max_per_side,"
                    " min_players, max_players) VALUES (?, ?, ?, ?, ?, ?)",
                    (game_id, f.kind, side[0], side[1], total[0], total[1]),
                )
            # The first version is the default unless one says otherwise.
            has_default = any(v.default for v in g.versions)
            for i, v in enumerate(g.versions):
                is_default = v.default or (not has_default and i == 0)
                conn.execute(
                    "INSERT INTO game_version (game_id, name, rules, is_default) VALUES (?, ?, ?, ?)",
                    (game_id, v.name, v.rules, int(is_default)),
                )
    return len(games)


def seed_if_empty(conn: sqlite3.Connection, data_dir: Path, starter: Path) -> int:
    """First start: fill an empty library from data/games.yaml or the starter list."""
    if conn.execute("SELECT 1 FROM game LIMIT 1").fetchone():
        return 0
    own = data_dir / "games.yaml"
    return import_games(conn, read_file(own if own.exists() else starter))


def _main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "check":
        print("usage: python -m gamemaster.library check FILE", file=sys.stderr)
        return 2
    try:
        games = read_file(argv[1])
    except ValueError as err:
        print(err, file=sys.stderr)
        return 1
    print(f"{argv[1]}: {len(games)} games, all fine")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
