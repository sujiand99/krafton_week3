"""SQLite database helpers for the ticketing DB service."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "ticketing.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    venue TEXT NOT NULL,
    starts_at TEXT NOT NULL,
    booking_opens_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    email TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seats (
    event_id TEXT NOT NULL,
    seat_id TEXT NOT NULL,
    seat_label TEXT NOT NULL,
    section TEXT NOT NULL,
    row_label TEXT NOT NULL,
    seat_number INTEGER NOT NULL,
    price INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (event_id, seat_id),
    FOREIGN KEY (event_id) REFERENCES events(event_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reservations (
    reservation_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    seat_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('HELD', 'CONFIRMED', 'CANCELLED', 'EXPIRED')),
    hold_token TEXT UNIQUE,
    expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    confirmed_at TEXT,
    cancelled_at TEXT,
    FOREIGN KEY (event_id, seat_id) REFERENCES seats(event_id, seat_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS payments (
    payment_id TEXT PRIMARY KEY,
    reservation_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('SUCCEEDED', 'FAILED', 'CANCELLED')),
    amount INTEGER NOT NULL,
    provider TEXT NOT NULL,
    provider_ref TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (reservation_id) REFERENCES reservations(reservation_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_reservations_confirmed_seat
ON reservations(event_id, seat_id)
WHERE status = 'CONFIRMED';

CREATE INDEX IF NOT EXISTS idx_reservations_user_created
ON reservations(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_payments_reservation
ON payments(reservation_id);

CREATE INDEX IF NOT EXISTS idx_reservations_event_status
ON reservations(event_id, status);
"""


class SQLiteDatabase:
    """Thin SQLite wrapper used by the repository layer."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self._db_path = Path(db_path)

    @property
    def db_path(self) -> Path:
        return self._db_path

    def connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize(self) -> None:
        with closing(self.connect()) as conn:
            conn.executescript(SCHEMA)
            conn.commit()
