from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from storage.sqlite_store import SQLiteSnapshotStore


def make_db_path() -> Path:
    return Path(".test_tmp") / f"{uuid4().hex}.db"


def test_sqlite_snapshot_store_round_trip() -> None:
    db_path = make_db_path()
    store = SQLiteSnapshotStore(db_path)

    try:
        store.initialize()
        store.save_entries(
            [
                ("a", "1", None),
                ("b", "2", 123.5),
            ]
        )

        assert sorted(store.load_entries()) == [
            ("a", "1", None),
            ("b", "2", 123.5),
        ]
    finally:
        db_path.unlink(missing_ok=True)


def test_sqlite_snapshot_store_replaces_previous_snapshot() -> None:
    db_path = make_db_path()
    store = SQLiteSnapshotStore(db_path)

    try:
        store.initialize()
        store.save_entries([("a", "1", None)])
        store.save_entries([("b", "2", 200.0)])

        assert store.load_entries() == [("b", "2", 200.0)]
    finally:
        db_path.unlink(missing_ok=True)
