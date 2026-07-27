"""
DB connection and bootstrap.
Single-file SQLite. WAL mode. Foreign keys enforced.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def get_connection(db_path: str | Path = ":memory:") -> sqlite3.Connection:
    """
    Open (or create) a SQLite database.
    Returns a connection with:
    - WAL journal mode
    - foreign keys ON
    - row_factory = sqlite3.Row for named column access
    """
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def bootstrap(db_path: str | Path = ":memory:") -> sqlite3.Connection:
    """Open connection and run all pending migrations."""
    conn = get_connection(db_path)
    _run_migrations(conn)
    return conn


def _run_migrations(conn: sqlite3.Connection) -> None:
    migration_files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
    for mf in migration_files:
        sql = mf.read_text(encoding="utf-8")
        conn.executescript(sql)
    conn.commit()
