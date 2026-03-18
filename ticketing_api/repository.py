"""Repository layer for ticketing DB service."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone

from ticketing_api.database import SQLiteDatabase
from ticketing_api.demo_layout import DEMO_EVENT_ID, build_demo_seat_rows


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TicketingRepository:
    """sqlite3-backed repository for ticketing domain data."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def initialize(self) -> None:
        self._database.initialize()

    def expire_stale_reservations(self, now: str) -> int:
        with closing(self._database.connect()) as conn:
            cursor = conn.execute(
                """
                UPDATE reservations
                SET status = 'EXPIRED',
                    updated_at = ?
                WHERE status = 'HELD'
                  AND expires_at IS NOT NULL
                  AND expires_at <= ?
                """,
                (now, now),
            )
            conn.commit()
        return int(cursor.rowcount)

    def list_events(self) -> list[dict[str, object]]:
        with closing(self._database.connect()) as conn:
            rows = conn.execute(
                """
                SELECT event_id, title, venue, starts_at, booking_opens_at, created_at
                FROM events
                ORDER BY starts_at, event_id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_event(self, event_id: str) -> dict[str, object] | None:
        with closing(self._database.connect()) as conn:
            row = conn.execute(
                """
                SELECT event_id, title, venue, starts_at, booking_opens_at, created_at
                FROM events
                WHERE event_id = ?
                """,
                (event_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def get_user(self, user_id: str) -> dict[str, object] | None:
        with closing(self._database.connect()) as conn:
            row = conn.execute(
                """
                SELECT user_id, display_name, email, created_at
                FROM users
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def create_user(
        self,
        user_id: str,
        display_name: str,
        email: str,
        created_at: str,
    ) -> dict[str, object]:
        with closing(self._database.connect()) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO users (
                    user_id,
                    display_name,
                    email,
                    created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (user_id, display_name, email, created_at),
            )
            conn.commit()
        return self.get_user(user_id)  # type: ignore[return-value]

    def get_seat(self, event_id: str, seat_id: str) -> dict[str, object] | None:
        with closing(self._database.connect()) as conn:
            row = conn.execute(
                """
                SELECT event_id, seat_id, seat_label, section, row_label, seat_number, price, created_at
                FROM seats
                WHERE event_id = ? AND seat_id = ?
                """,
                (event_id, seat_id),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_seats(self, event_id: str) -> list[dict[str, object]]:
        with closing(self._database.connect()) as conn:
            rows = conn.execute(
                """
                SELECT
                    s.event_id,
                    s.seat_id,
                    s.seat_label,
                    s.section,
                    s.row_label,
                    s.seat_number,
                    s.price,
                    s.created_at,
                    CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM reservations AS r
                            WHERE r.event_id = s.event_id
                              AND r.seat_id = s.seat_id
                              AND r.status = 'CONFIRMED'
                        )
                        THEN 'CONFIRMED'
                        ELSE 'AVAILABLE'
                    END AS status
                FROM seats AS s
                WHERE s.event_id = ?
                ORDER BY s.section, s.row_label, s.seat_number
                """,
                (event_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_user_reservations(self, user_id: str) -> list[dict[str, object]]:
        with closing(self._database.connect()) as conn:
            rows = conn.execute(
                """
                SELECT
                    r.reservation_id,
                    r.event_id,
                    r.seat_id,
                    r.user_id,
                    r.status,
                    r.hold_token,
                    r.expires_at,
                    r.created_at,
                    r.updated_at,
                    r.confirmed_at,
                    r.cancelled_at,
                    p.payment_id,
                    p.status AS payment_status,
                    p.amount AS payment_amount,
                    p.provider AS payment_provider,
                    p.provider_ref AS payment_provider_ref
                FROM reservations AS r
                LEFT JOIN payments AS p
                    ON p.reservation_id = r.reservation_id
                WHERE r.user_id = ?
                ORDER BY r.created_at DESC, r.reservation_id DESC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_confirmed_seats(self, event_id: str) -> list[dict[str, object]]:
        with closing(self._database.connect()) as conn:
            rows = conn.execute(
                """
                SELECT event_id, seat_id, reservation_id, user_id, confirmed_at
                FROM reservations
                WHERE event_id = ? AND status = 'CONFIRMED'
                ORDER BY seat_id
                """,
                (event_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_reservation(self, reservation_id: str) -> dict[str, object] | None:
        with closing(self._database.connect()) as conn:
            row = conn.execute(
                """
                SELECT
                    r.reservation_id,
                    r.event_id,
                    r.seat_id,
                    r.user_id,
                    r.status,
                    r.hold_token,
                    r.expires_at,
                    r.created_at,
                    r.updated_at,
                    r.confirmed_at,
                    r.cancelled_at,
                    p.payment_id,
                    p.status AS payment_status,
                    p.amount AS payment_amount,
                    p.provider AS payment_provider,
                    p.provider_ref AS payment_provider_ref
                FROM reservations AS r
                LEFT JOIN payments AS p
                    ON p.reservation_id = r.reservation_id
                WHERE r.reservation_id = ?
                """,
                (reservation_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def has_confirmed_reservation(self, event_id: str, seat_id: str) -> bool:
        with closing(self._database.connect()) as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM reservations
                WHERE event_id = ? AND seat_id = ? AND status = 'CONFIRMED'
                """,
                (event_id, seat_id),
            ).fetchone()
        return row is not None

    def create_held_reservation(
        self,
        reservation_id: str,
        event_id: str,
        seat_id: str,
        user_id: str,
        hold_token: str,
        expires_at: str,
        now: str,
    ) -> dict[str, object]:
        with closing(self._database.connect()) as conn:
            conn.execute(
                """
                INSERT INTO reservations (
                    reservation_id,
                    event_id,
                    seat_id,
                    user_id,
                    status,
                    hold_token,
                    expires_at,
                    created_at,
                    updated_at,
                    confirmed_at,
                    cancelled_at
                ) VALUES (?, ?, ?, ?, 'HELD', ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    reservation_id,
                    event_id,
                    seat_id,
                    user_id,
                    hold_token,
                    expires_at,
                    now,
                    now,
                ),
            )
            conn.commit()
        return self.get_reservation(reservation_id)  # type: ignore[return-value]

    def confirm_reservation(
        self,
        reservation_id: str,
        payment_id: str,
        amount: int,
        provider: str,
        provider_ref: str,
        now: str,
    ) -> dict[str, object]:
        with closing(self._database.connect()) as conn:
            conn.execute(
                """
                INSERT INTO payments (
                    payment_id,
                    reservation_id,
                    status,
                    amount,
                    provider,
                    provider_ref,
                    created_at,
                    updated_at
                ) VALUES (?, ?, 'SUCCEEDED', ?, ?, ?, ?, ?)
                ON CONFLICT(reservation_id) DO UPDATE SET
                    payment_id = excluded.payment_id,
                    status = excluded.status,
                    amount = excluded.amount,
                    provider = excluded.provider,
                    provider_ref = excluded.provider_ref,
                    updated_at = excluded.updated_at
                """,
                (
                    payment_id,
                    reservation_id,
                    amount,
                    provider,
                    provider_ref,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE reservations
                SET status = 'CONFIRMED',
                    updated_at = ?,
                    confirmed_at = ?
                WHERE reservation_id = ?
                """,
                (now, now, reservation_id),
            )
            conn.commit()
        return self.get_reservation(reservation_id)  # type: ignore[return-value]

    def cancel_reservation(
        self,
        reservation_id: str,
        now: str,
        payment_payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        with closing(self._database.connect()) as conn:
            if payment_payload is not None:
                conn.execute(
                    """
                    INSERT INTO payments (
                        payment_id,
                        reservation_id,
                        status,
                        amount,
                        provider,
                        provider_ref,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(reservation_id) DO UPDATE SET
                        payment_id = excluded.payment_id,
                        status = excluded.status,
                        amount = excluded.amount,
                        provider = excluded.provider,
                        provider_ref = excluded.provider_ref,
                        updated_at = excluded.updated_at
                    """,
                    (
                        payment_payload["payment_id"],
                        reservation_id,
                        payment_payload["payment_status"],
                        payment_payload["amount"],
                        payment_payload["provider"],
                        payment_payload["provider_ref"],
                        now,
                        now,
                    ),
                )

            conn.execute(
                """
                UPDATE reservations
                SET status = 'CANCELLED',
                    updated_at = ?,
                    cancelled_at = ?
                WHERE reservation_id = ?
                """,
                (now, now, reservation_id),
            )
            conn.commit()
        return self.get_reservation(reservation_id)  # type: ignore[return-value]

    def expire_reservation(self, reservation_id: str, now: str) -> dict[str, object]:
        with closing(self._database.connect()) as conn:
            conn.execute(
                """
                UPDATE reservations
                SET status = 'EXPIRED',
                    updated_at = ?
                WHERE reservation_id = ?
                """,
                (now, reservation_id),
            )
            conn.commit()
        return self.get_reservation(reservation_id)  # type: ignore[return-value]

    def seed_demo_data(self) -> None:
        created_at = utc_now_iso()
        event_rows = [
            (
                DEMO_EVENT_ID,
                "Open Air Countdown Live",
                "Seoul Olympic Hall",
                "2026-03-19T20:00:00+09:00",
                "2026-03-19T19:00:00+09:00",
                created_at,
            )
        ]
        user_rows = [
            ("user-1", "Mina", "mina@example.com", created_at),
            ("user-2", "Jisoo", "jisoo@example.com", created_at),
            ("user-3", "Alex", "alex@example.com", created_at),
        ]
        seat_rows = build_demo_seat_rows(created_at)

        with closing(self._database.connect()) as conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO events (
                    event_id,
                    title,
                    venue,
                    starts_at,
                    booking_opens_at,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                event_rows,
            )
            conn.executemany(
                """
                INSERT OR IGNORE INTO users (
                    user_id,
                    display_name,
                    email,
                    created_at
                ) VALUES (?, ?, ?, ?)
                """,
                user_rows,
            )
            conn.executemany(
                """
                INSERT OR IGNORE INTO seats (
                    event_id,
                    seat_id,
                    seat_label,
                    section,
                    row_label,
                    seat_number,
                    price,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                seat_rows,
            )
            conn.commit()


