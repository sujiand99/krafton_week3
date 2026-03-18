"""Presentation-oriented ticketing demo service for Mini Redis."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import random
import socket
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Protocol


SEAT_STATUSES = {"AVAILABLE", "HELD", "CONFIRMED", "CANCELLED", "EXPIRED"}
DEFAULT_EVENT_ID = "concert1"
DEFAULT_EVENT_TITLE = "Midnight Echo Live"
DEFAULT_TOTAL_SEATS = 1000
DEFAULT_USERS_ONLINE = 10000
DEFAULT_HOLD_SECONDS = 10


class RedisProtocol(Protocol):
    """Minimal command interface needed by the demo service."""

    def execute(self, command: list[str]) -> Any: ...


class MiniRedisError(RuntimeError):
    """Raised when the Mini Redis server returns a RESP error."""


class MiniRedisTcpClient:
    """Simple RESP client that talks to the Mini Redis TCP server."""

    def __init__(self, host: str, port: int, timeout: float = 2.0) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout

    def execute(self, command: list[str]) -> Any:
        if not command:
            raise ValueError("command must not be empty")

        payload = self._encode_command(command)
        with socket.create_connection(
            (self._host, self._port),
            timeout=self._timeout,
        ) as conn:
            conn.sendall(payload)
            reader = conn.makefile("rb")
            return self._read_response(reader)

    @staticmethod
    def _encode_command(command: list[str]) -> bytes:
        parts = [f"*{len(command)}\r\n".encode("utf-8")]
        for token in command:
            encoded = token.encode("utf-8")
            parts.append(f"${len(encoded)}\r\n".encode("utf-8"))
            parts.append(encoded + b"\r\n")
        return b"".join(parts)

    def _read_response(self, reader: Any) -> Any:
        prefix = reader.read(1)
        if not prefix:
            raise MiniRedisError("Mini Redis closed the connection unexpectedly")

        if prefix == b"+":
            return self._readline(reader).decode("utf-8")
        if prefix == b"-":
            raise MiniRedisError(self._readline(reader).decode("utf-8"))
        if prefix == b":":
            return int(self._readline(reader))
        if prefix == b"$":
            length = int(self._readline(reader))
            if length == -1:
                return None
            payload = reader.read(length)
            line_end = reader.read(2)
            if line_end != b"\r\n":
                raise MiniRedisError("Malformed bulk string response")
            return payload.decode("utf-8")
        if prefix == b"*":
            item_count = int(self._readline(reader))
            if item_count == -1:
                return None
            return [self._read_response(reader) for _ in range(item_count)]

        raise MiniRedisError(f"Unsupported RESP response prefix: {prefix!r}")

    @staticmethod
    def _readline(reader: Any) -> bytes:
        line = reader.readline()
        if not line.endswith(b"\r\n"):
            raise MiniRedisError("Malformed RESP line")
        return line[:-2]


@dataclass(slots=True)
class SeatSnapshot:
    seat_id: str
    status: str
    user_id: str | None
    ttl_seconds: int | None
    section: str
    row_label: str
    seat_number: int
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "seat_id": self.seat_id,
            "status": self.status,
            "user_id": self.user_id,
            "ttl_seconds": self.ttl_seconds,
            "section": self.section,
            "row_label": self.row_label,
            "seat_number": self.seat_number,
            "source": self.source,
        }


class TicketingDemoService:
    """Coordinates the ticketing demo flow between Redis and SQLite."""

    def __init__(
        self,
        redis_client: RedisProtocol,
        db_path: Path,
        *,
        event_id: str = DEFAULT_EVENT_ID,
        event_title: str = DEFAULT_EVENT_TITLE,
        total_seats: int = DEFAULT_TOTAL_SEATS,
        users_online: int = DEFAULT_USERS_ONLINE,
        featured_seat_count: int = 180,
        default_hold_seconds: int = DEFAULT_HOLD_SECONDS,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self._redis = redis_client
        self._db_path = Path(db_path)
        self._event_id = event_id
        self._event_title = event_title
        self._total_seats = total_seats
        self._users_online = users_online
        self._featured_seat_ids = self._build_featured_seat_ids(featured_seat_count)
        self._default_hold_seconds = default_hold_seconds
        self._now_factory = now_factory or (lambda: datetime.now(UTC))
        self._lock = threading.RLock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self._db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._logs: list[dict[str, str]] = []
        self._held_seats: dict[str, str] = {}
        self._confirmed_seats: dict[str, str] = {}
        self._expired_holds = 0
        self._cancelled_holds = 0
        self._surge_runs = 0
        self._last_surge: dict[str, Any] = {
            "contenders": 0,
            "focus_seats": 0,
            "held": 0,
            "rejected": 0,
            "duration_ms": 0,
            "sample_winners": [],
            "sample_rejections": [],
        }
        self._ensure_schema()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def bootstrap(self) -> None:
        with self._lock:
            self._reset_database_locked()
            self._reset_redis_locked()
            self._logs.clear()
            self._held_seats.clear()
            self._confirmed_seats.clear()
            self._expired_holds = 0
            self._cancelled_holds = 0
            self._surge_runs = 0
            self._last_surge = {
                "contenders": 0,
                "focus_seats": 0,
                "held": 0,
                "rejected": 0,
                "duration_ms": 0,
                "sample_winners": [],
                "sample_rejections": [],
            }
            self._log_locked(
                "system",
                f"Prepared demo state for {self._event_title} ({self._total_seats} seats).",
            )

    def dashboard_state(self) -> dict[str, Any]:
        with self._lock:
            self._sync_expired_holds_locked()
            featured_seats = [
                self._get_seat_snapshot_locked(seat_id).to_dict()
                for seat_id in self._featured_seat_ids
            ]
            held_count = len(self._held_seats)
            confirmed_count = len(self._confirmed_seats)
            available_count = self._total_seats - held_count - confirmed_count
            reservations = self._load_recent_reservations_locked()

            return {
                "event": {
                    "event_id": self._event_id,
                    "title": self._event_title,
                },
                "summary": {
                    "total_seats": self._total_seats,
                    "users_online": self._users_online,
                    "available": available_count,
                    "held": held_count,
                    "confirmed": confirmed_count,
                    "expired_holds": self._expired_holds,
                    "cancelled_holds": self._cancelled_holds,
                    "surge_runs": self._surge_runs,
                },
                "featured_seats": featured_seats,
                "logs": list(reversed(self._logs[-18:])),
                "reservations": reservations,
                "surge": dict(self._last_surge),
                "supported_flow": {
                    "live": [
                        "AVAILABLE -> HELD",
                        "HELD -> EXPIRED",
                    ],
                    "mocked": [
                        "DB confirm -> CONFIRMED",
                        "Queue / idempotency token",
                    ],
                },
            }

    def reserve_seat(
        self,
        *,
        seat_id: str,
        user_id: str,
        ttl_seconds: int | None = None,
    ) -> dict[str, Any]:
        hold_seconds = ttl_seconds or self._default_hold_seconds
        if hold_seconds <= 0:
            raise ValueError("hold seconds must be positive")

        with self._lock:
            self._sync_expired_holds_locked()
            return self._reserve_seat_locked(
                seat_id=seat_id,
                user_id=user_id,
                ttl_seconds=hold_seconds,
                log_events=True,
            )

    def confirm_seat(self, *, seat_id: str, user_id: str) -> dict[str, Any]:
        with self._lock:
            self._sync_expired_holds_locked()
            current = self._get_seat_snapshot_locked(seat_id)
            if current.status != "HELD" or current.user_id != user_id:
                self._log_locked(
                    "db",
                    f"DB confirm blocked for {seat_id}; expected HELD by {user_id}.",
                    level="warning",
                )
                return {
                    "ok": False,
                    "message": f"{seat_id} must be HELD by {user_id} before confirm.",
                    "seat": current.to_dict(),
                }

            reservation_id = f"res-{uuid.uuid4().hex[:10]}"
            hold_token = f"hold-{uuid.uuid4().hex[:8]}"
            timestamp = self._timestamp()

            try:
                self._connection.execute(
                    """
                    INSERT INTO reservations (
                        reservation_id,
                        event_id,
                        seat_id,
                        user_id,
                        status,
                        created_at,
                        confirmed_at,
                        hold_token
                    )
                    VALUES (?, ?, ?, ?, 'CONFIRMED', ?, ?, ?)
                    """,
                    (
                        reservation_id,
                        self._event_id,
                        seat_id,
                        user_id,
                        timestamp,
                        timestamp,
                        hold_token,
                    ),
                )
                self._connection.execute(
                    """
                    INSERT INTO payments (
                        payment_id,
                        reservation_id,
                        status,
                        created_at
                    )
                    VALUES (?, ?, 'SUCCESS', ?)
                    """,
                    (f"pay-{uuid.uuid4().hex[:10]}", reservation_id, timestamp),
                )
                self._connection.commit()
            except sqlite3.IntegrityError:
                self._log_locked(
                    "db",
                    f"DB confirm blocked for {seat_id}; reservation already exists.",
                    level="warning",
                )
                return {
                    "ok": False,
                    "message": f"{seat_id} is already confirmed in DB.",
                    "seat": current.to_dict(),
                }

            self._redis.execute(["SET", self._seat_key(seat_id), f"CONFIRMED:{user_id}"])
            self._held_seats.pop(seat_id, None)
            self._confirmed_seats[seat_id] = user_id
            self._log_locked(
                "db",
                f"DB confirmed {seat_id} for {user_id}; Redis mirrored CONFIRMED.",
            )
            seat = self._get_seat_snapshot_locked(seat_id)
            return {
                "ok": True,
                "message": f"{seat_id} is CONFIRMED for {user_id}.",
                "seat": seat.to_dict(),
            }

    def release_seat(self, *, seat_id: str, user_id: str) -> dict[str, Any]:
        with self._lock:
            self._sync_expired_holds_locked()
            current = self._get_seat_snapshot_locked(seat_id)
            if current.status != "HELD" or current.user_id != user_id:
                self._log_locked(
                    "redis",
                    f"Release blocked for {seat_id}; expected HELD by {user_id}.",
                    level="warning",
                )
                return {
                    "ok": False,
                    "message": f"{seat_id} must be HELD by {user_id} before release.",
                    "seat": current.to_dict(),
                }

            self._redis.execute(["DEL", self._seat_key(seat_id)])
            self._held_seats.pop(seat_id, None)
            self._cancelled_holds += 1
            self._log_locked(
                "redis",
                f"{user_id} released {seat_id}; seat returned to AVAILABLE.",
            )
            seat = self._get_seat_snapshot_locked(seat_id)
            return {
                "ok": True,
                "message": f"{seat_id} is AVAILABLE again.",
                "seat": seat.to_dict(),
            }

    def seat_status(self, *, seat_id: str) -> dict[str, Any]:
        with self._lock:
            self._sync_expired_holds_locked()
            seat = self._get_seat_snapshot_locked(seat_id)
            return {"ok": True, "seat": seat.to_dict()}

    def simulate_surge(
        self,
        *,
        contenders: int = 120,
        focus_seats: int = 12,
        ttl_seconds: int | None = None,
    ) -> dict[str, Any]:
        hold_seconds = ttl_seconds or self._default_hold_seconds
        with self._lock:
            self._sync_expired_holds_locked()
            rng = random.Random(11 + self._surge_runs)
            target_seats = [self._seat_id(index) for index in range(1, focus_seats + 1)]
            success = 0
            failure = 0
            sample_winners: list[str] = []
            sample_rejections: list[str] = []
            started = time.perf_counter()

            for index in range(1, contenders + 1):
                seat_id = rng.choice(target_seats)
                user_id = f"user{index:05d}"
                reserved = self._reserve_seat_locked(
                    seat_id=seat_id,
                    user_id=user_id,
                    ttl_seconds=hold_seconds,
                    log_events=False,
                )
                if reserved["ok"]:
                    success += 1
                    if len(sample_winners) < 4:
                        sample_winners.append(f"{user_id}->{seat_id}")
                else:
                    failure += 1
                    if len(sample_rejections) < 4:
                        sample_rejections.append(f"{user_id}->{seat_id}")

            duration_ms = max(1, round((time.perf_counter() - started) * 1000, 2))
            self._surge_runs += 1
            self._last_surge = {
                "contenders": contenders,
                "focus_seats": focus_seats,
                "held": success,
                "rejected": failure,
                "duration_ms": duration_ms,
                "sample_winners": sample_winners,
                "sample_rejections": sample_rejections,
            }
            self._log_locked(
                "scenario",
                "Ticket-open surge simulated: "
                f"{contenders} users raced for {focus_seats} hot seats "
                f"({success} held / {failure} rejected / {duration_ms} ms).",
            )
            return {
                "ok": True,
                "message": (
                    f"Simulated {contenders} users for {focus_seats} hot seats: "
                    f"{success} held, {failure} rejected in {duration_ms} ms."
                ),
                "result": dict(self._last_surge),
            }

    def _reserve_seat_locked(
        self,
        *,
        seat_id: str,
        user_id: str,
        ttl_seconds: int,
        log_events: bool,
    ) -> dict[str, Any]:
        current = self._get_seat_snapshot_locked(seat_id)
        if current.status != "AVAILABLE":
            if log_events:
                self._log_locked(
                    "redis",
                    f"{user_id} failed to reserve {seat_id}; seat is {current.status}.",
                    level="warning",
                )
            return {
                "ok": False,
                "message": f"{seat_id} is already {current.status}.",
                "seat": current.to_dict(),
            }

        key = self._seat_key(seat_id)
        self._redis.execute(["SET", key, f"HELD:{user_id}"])
        applied = self._redis.execute(["EXPIRE", key, str(ttl_seconds)])
        if applied != 1:
            self._redis.execute(["DEL", key])
            raise MiniRedisError("Failed to apply seat hold TTL")

        self._held_seats[seat_id] = user_id
        if log_events:
            self._log_locked(
                "redis",
                f"{user_id} reserved {seat_id}; seat is now HELD for {ttl_seconds}s.",
            )
        seat = self._get_seat_snapshot_locked(seat_id)
        return {
            "ok": True,
            "message": f"{seat_id} is HELD for {user_id}.",
            "seat": seat.to_dict(),
        }

    def _ensure_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                title TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS seats (
                event_id TEXT NOT NULL,
                seat_id TEXT NOT NULL,
                section TEXT NOT NULL,
                row_label TEXT NOT NULL,
                seat_number INTEGER NOT NULL,
                PRIMARY KEY (event_id, seat_id)
            );

            CREATE TABLE IF NOT EXISTS reservations (
                reservation_id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                seat_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                confirmed_at TEXT,
                hold_token TEXT,
                UNIQUE (event_id, seat_id)
            );

            CREATE TABLE IF NOT EXISTS payments (
                payment_id TEXT PRIMARY KEY,
                reservation_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        self._connection.commit()

    def _reset_database_locked(self) -> None:
        self._connection.execute("DELETE FROM payments")
        self._connection.execute("DELETE FROM reservations")
        self._connection.execute("DELETE FROM seats")
        self._connection.execute("DELETE FROM events")
        self._connection.execute(
            "INSERT INTO events (event_id, title) VALUES (?, ?)",
            (self._event_id, self._event_title),
        )

        seat_rows = [
            (
                self._event_id,
                seat_id,
                self._seat_section(index),
                self._seat_row(index),
                ((index - 1) % 20) + 1,
            )
            for index, seat_id in enumerate(self._all_seat_ids(), start=1)
        ]
        self._connection.executemany(
            """
            INSERT INTO seats (event_id, seat_id, section, row_label, seat_number)
            VALUES (?, ?, ?, ?, ?)
            """,
            seat_rows,
        )
        self._connection.commit()

    def _reset_redis_locked(self) -> None:
        for seat_id in self._all_seat_ids():
            self._redis.execute(["DEL", self._seat_key(seat_id)])

    def _get_seat_snapshot_locked(self, seat_id: str) -> SeatSnapshot:
        section, row_label, seat_number = self._seat_metadata(seat_id)
        redis_value = self._redis.execute(["GET", self._seat_key(seat_id)])
        if redis_value is None:
            confirmed_user = self._confirmed_seats.get(seat_id)
            if confirmed_user is not None:
                return SeatSnapshot(
                    seat_id=seat_id,
                    status="CONFIRMED",
                    user_id=confirmed_user,
                    ttl_seconds=None,
                    section=section,
                    row_label=row_label,
                    seat_number=seat_number,
                    source="db",
                )
            return SeatSnapshot(
                seat_id=seat_id,
                status="AVAILABLE",
                user_id=None,
                ttl_seconds=None,
                section=section,
                row_label=row_label,
                seat_number=seat_number,
                source="catalog",
            )

        ttl = self._redis.execute(["TTL", self._seat_key(seat_id)])
        status, user_id = self._parse_seat_value(str(redis_value))
        source = "redis" if status in SEAT_STATUSES else "unknown"
        ttl_value = ttl if isinstance(ttl, int) and ttl >= 0 else None
        if status == "CONFIRMED":
            self._confirmed_seats[seat_id] = user_id or "unknown"
            self._held_seats.pop(seat_id, None)
        elif status == "HELD" and user_id is not None:
            self._held_seats[seat_id] = user_id

        return SeatSnapshot(
            seat_id=seat_id,
            status=status,
            user_id=user_id,
            ttl_seconds=ttl_value,
            section=section,
            row_label=row_label,
            seat_number=seat_number,
            source=source,
        )

    def _sync_expired_holds_locked(self) -> None:
        for seat_id, user_id in list(self._held_seats.items()):
            redis_value = self._redis.execute(["GET", self._seat_key(seat_id)])
            if redis_value is not None:
                continue

            self._held_seats.pop(seat_id, None)
            self._expired_holds += 1
            self._log_locked(
                "redis",
                f"TTL expired on {seat_id}; {user_id}'s hold returned to AVAILABLE.",
            )

    def _load_recent_reservations_locked(self, limit: int = 8) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT reservation_id, seat_id, user_id, status, confirmed_at, created_at
            FROM reservations
            ORDER BY confirmed_at DESC, created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        return [
            {
                "reservation_id": row["reservation_id"],
                "seat_id": row["seat_id"],
                "user_id": row["user_id"],
                "status": row["status"],
                "confirmed_at": row["confirmed_at"],
            }
            for row in rows
        ]

    def _log_locked(self, source: str, message: str, *, level: str = "info") -> None:
        self._logs.append(
            {
                "time": self._timestamp(),
                "source": source.upper(),
                "level": level.upper(),
                "message": message,
            }
        )
        if len(self._logs) > 200:
            self._logs = self._logs[-200:]

    def _timestamp(self) -> str:
        return self._now_factory().strftime("%H:%M:%S")

    def _all_seat_ids(self) -> list[str]:
        return [self._seat_id(index) for index in range(1, self._total_seats + 1)]

    def _build_featured_seat_ids(self, count: int) -> list[str]:
        if count >= self._total_seats:
            return self._all_seat_ids()

        sampled_ids: list[str] = []
        seen: set[str] = set()

        anchor_count = min(20, count)
        for index in range(1, anchor_count + 1):
            seat_id = self._seat_id(index)
            sampled_ids.append(seat_id)
            seen.add(seat_id)

        remaining = count - anchor_count
        if remaining > 0:
            denominator = max(1, remaining - 1)
            for offset in range(remaining):
                index = anchor_count + 1 + round(offset * (self._total_seats - anchor_count - 1) / denominator)
                seat_id = self._seat_id(index)
                if seat_id not in seen:
                    sampled_ids.append(seat_id)
                    seen.add(seat_id)

        if len(sampled_ids) < count:
            for seat_id in self._all_seat_ids():
                if seat_id in seen:
                    continue
                sampled_ids.append(seat_id)
                if len(sampled_ids) == count:
                    break

        return sampled_ids

    @staticmethod
    def _seat_id(index: int) -> str:
        return f"S{index:04d}"

    @staticmethod
    def _seat_index(seat_id: str) -> int:
        return int(seat_id[1:])

    def _seat_metadata(self, seat_id: str) -> tuple[str, str, int]:
        index = self._seat_index(seat_id)
        return (
            self._seat_section(index),
            self._seat_row(index),
            ((index - 1) % 20) + 1,
        )

    @staticmethod
    def _seat_row(index: int) -> str:
        row_index = ((index - 1) // 20) % 26
        return chr(ord("A") + row_index)

    @staticmethod
    def _seat_section(index: int) -> str:
        if index <= 120:
            return "VIP"
        if index <= 420:
            return "R"
        if index <= 760:
            return "S"
        return "A"

    def _seat_key(self, seat_id: str) -> str:
        return f"seat:{self._event_id}:{seat_id}"

    @staticmethod
    def _parse_seat_value(value: str) -> tuple[str, str | None]:
        if ":" not in value:
            return value, None
        status, user_id = value.split(":", 1)
        return status, user_id or None



