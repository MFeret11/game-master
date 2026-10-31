"""SQLite connection and schema migrations.

The database is the source of truth (SPEC §7). Every action runs in one
transaction, so a crash or a restart never leaves half a change behind.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

MIGRATIONS = Path(__file__).parent / "migrations"


def connect(path: str | Path) -> sqlite3.Connection:
    """Open the database and bring the schema up to date."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    # FULL: a power cut or a closed lid right after a tap still keeps the tap.
    conn.execute("PRAGMA synchronous = FULL")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """Apply numbered .sql files in migrations/ that haven't run yet."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for file in sorted(MIGRATIONS.glob("*.sql")):
        number = int(file.name.split("_", 1)[0])
        if number <= current:
            continue
        with transaction(conn):
            for statement in _statements(file.read_text()):
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {number}")


def _statements(sql: str) -> list[str]:
    """Split a migration file into statements (no semicolons inside our SQL)."""
    lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE ... COMMIT, or ROLLBACK on any error."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
