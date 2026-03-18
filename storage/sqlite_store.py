"""SQLite-backed snapshot persistence for the storage layer."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from storage.engine import SnapshotEntry


class SQLiteSnapshotStore:
    """Persist full storage snapshots in a local SQLite database."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)

    @property
    def db_path(self) -> Path:
        return self._db_path

    def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS entries (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    expires_at REAL
                )
                """
            )
            conn.commit()

    def load_entries(self) -> list[SnapshotEntry]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT key, value, expires_at FROM entries"
            ).fetchall()
        return [(key, value, expires_at) for key, value, expires_at in rows]

    def save_entries(self, entries: list[SnapshotEntry]) -> None:
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM entries")
            conn.executemany(
                "INSERT INTO entries (key, value, expires_at) VALUES (?, ?, ?)",
                entries,
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)
