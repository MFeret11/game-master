"""Real Jeopardy clues for the Jeopardy round (SPEC §6.1).

The clues come from a public dataset (jwolle1/jeopardy_clue_dataset). They are
never committed: the first time they're needed, the app downloads the file,
keeps only what a party board can use, and saves that in data/clues.db.

Get them ahead of time (at home, with internet):

    python -m gamemaster.clues

What's kept:
- Regular episodes only (no tournaments), from FIRST_YEAR on.
- Full categories: all 5 clues of one category from one episode, so every
  column on our board is a real, tested set that gets harder row by row.
- No clue that depends on video or a person on stage (starts with "(").
- Final Jeopardy clues, for the finale.
"""

from __future__ import annotations

import csv
import os
import re
import sqlite3
import sys
import tempfile
import urllib.request
from pathlib import Path

# Pinned to a release tag, so the file never changes under us.
SOURCE_URL = (
    "https://raw.githubusercontent.com/jwolle1/jeopardy_clue_dataset/v42/combined_season1-42.tsv"
)
SOURCE_NAME = "jwolle1/jeopardy_clue_dataset v42"

FIRST_YEAR = 2015          # older clues lean on dated pop culture
CLUES_PER_CATEGORY = 5

# The dataset's round numbers.
ROUND_LEVEL = {"1": "single", "2": "double"}
FINAL_ROUND = "3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS category (
    id        INTEGER PRIMARY KEY,
    key       TEXT NOT NULL UNIQUE,   -- air date | round | name: one real category
    level     TEXT NOT NULL CHECK (level IN ('single', 'double')),
    name      TEXT NOT NULL,
    note      TEXT NOT NULL DEFAULT '',
    air_date  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clue (
    category_id  INTEGER NOT NULL REFERENCES category(id),
    row          INTEGER NOT NULL,    -- 1 (easiest) to 5 (hardest)
    text         TEXT NOT NULL,
    response     TEXT NOT NULL,
    PRIMARY KEY (category_id, row)
);
CREATE TABLE IF NOT EXISTS final (
    id        INTEGER PRIMARY KEY,
    key       TEXT NOT NULL UNIQUE,
    category  TEXT NOT NULL,
    text      TEXT NOT NULL,
    response  TEXT NOT NULL,
    air_date  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    name   TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
"""


class CluesMissing(Exception):
    """The clues haven't been downloaded and the download failed."""


def db_path(data_dir: Path) -> Path:
    return Path(data_dir) / "clues.db"


def is_ready(data_dir: Path) -> bool:
    path = db_path(data_dir)
    if not path.exists():
        return False
    with sqlite3.connect(path) as conn:
        try:
            return conn.execute("SELECT value FROM meta WHERE name = 'source'").fetchone() is not None
        except sqlite3.DatabaseError:
            return False


def open_clues(data_dir: Path) -> sqlite3.Connection:
    """The clue database, downloading it first if needed."""
    if not is_ready(data_dir):
        download(data_dir)
    conn = sqlite3.connect(db_path(data_dir), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def download(data_dir: Path, url: str = SOURCE_URL) -> None:
    """Fetch the dataset and import it. The raw file is deleted afterwards."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=data_dir, suffix=".tsv", delete=False) as tmp:
        raw = Path(tmp.name)
    try:
        try:
            urllib.request.urlretrieve(url, raw)
        except OSError as err:
            raise CluesMissing(
                "Couldn't download the Jeopardy clues. Check the internet connection and try again."
            ) from err
        import_tsv(raw, data_dir)
    finally:
        raw.unlink(missing_ok=True)


def import_tsv(tsv: Path, data_dir: Path, source: str = SOURCE_NAME) -> dict:
    """Build data/clues.db from a dataset file. Returns counts, for the log."""
    groups: dict[tuple[str, str, str], list[dict]] = {}
    finals: list[dict] = []
    with open(tsv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            if not _usable(row):
                continue
            if row["round"] == FINAL_ROUND:
                finals.append(row)
            elif row["round"] in ROUND_LEVEL:
                groups.setdefault((row["air_date"], row["round"], row["category"]), []).append(row)

    # Write to a new file and swap it in, so a failed import never leaves half a database.
    final_path = db_path(data_dir)
    temp_path = final_path.with_suffix(".db.new")
    temp_path.unlink(missing_ok=True)
    conn = sqlite3.connect(temp_path)
    counts = {"single": 0, "double": 0, "final": 0}
    try:
        conn.executescript(SCHEMA)
        for (air_date, rnd, name), rows in groups.items():
            if not _full_category(rows):
                continue
            level = ROUND_LEVEL[rnd]
            category_id = conn.execute(
                "INSERT INTO category (key, level, name, note, air_date) VALUES (?, ?, ?, ?, ?)",
                (f"{air_date}|{rnd}|{name}", level, clean(name), clean_note(rows[0]["comments"]), air_date),
            ).lastrowid
            for number, row in enumerate(sorted(rows, key=lambda r: int(r["clue_value"])), start=1):
                conn.execute(
                    "INSERT INTO clue (category_id, row, text, response) VALUES (?, ?, ?, ?)",
                    (category_id, number, clean(row["answer"]), clean(row["question"])),
                )
            counts[level] += 1
        for row in finals:
            conn.execute(
                "INSERT OR IGNORE INTO final (key, category, text, response, air_date) VALUES (?, ?, ?, ?, ?)",
                (f"{row['air_date']}|3|{row['category']}", clean(row["category"]),
                 clean(row["answer"]), clean(row["question"]), row["air_date"]),
            )
            counts["final"] += 1
        conn.execute("INSERT INTO meta (name, value) VALUES ('source', ?)", (source,))
        conn.commit()
    finally:
        conn.close()
    temp_path.replace(final_path)
    return counts


def _usable(row: dict) -> bool:
    return (
        row["air_date"] >= str(FIRST_YEAR)
        and not row["notes"]                       # notes mark tournaments and special games
        and row["answer"].strip() and row["question"].strip()
        and not row["answer"].lstrip().startswith("(")  # "(Sarah of the Clue Crew shows ...)"
    )


def _full_category(rows: list[dict]) -> bool:
    """Exactly five clues with five different values, so nothing is missing."""
    return len(rows) == CLUES_PER_CATEGORY and len({r["clue_value"] for r in rows}) == CLUES_PER_CATEGORY


def clean(text: str) -> str:
    """The dataset escapes quotes as \\" and \\'."""
    return text.replace('\\"', '"').replace("\\'", "'").strip()


def clean_note(comment: str) -> str:
    """'(Alex: Each response starts with "O".)' becomes 'Each response starts with "O".'"""
    return re.sub(r"\(\w+: ([^)]*)\)", r"\1", clean(comment)).strip()


def main() -> None:
    default = os.environ.get("GM_DATA") or Path(__file__).resolve().parent.parent / "data"
    data_dir = Path(sys.argv[1] if len(sys.argv) > 1 else default)
    print("Downloading the Jeopardy clues (about 80 MB, first time only)...")
    download(data_dir)
    with sqlite3.connect(db_path(data_dir)) as conn:
        for level in ("single", "double"):
            n = conn.execute("SELECT COUNT(*) FROM category WHERE level = ?", (level,)).fetchone()[0]
            print(f"  {level.title()} Jeopardy categories: {n:,}")
        print(f"  Final Jeopardy clues: {conn.execute('SELECT COUNT(*) FROM final').fetchone()[0]:,}")
    print(f"Saved to {db_path(data_dir)}")


if __name__ == "__main__":
    main()
