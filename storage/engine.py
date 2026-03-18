"""Storage engine contract."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import time
from typing import Callable

from storage.ttl import (
    compute_deadline,
    is_expired,
    normalize_expire_option,
    should_apply_expiry,
)


@dataclass(slots=True)
class Entry:
    value: str
    expires_at: float | None = None


@dataclass(slots=True)
class SeatStatus:
    state: str
    user_id: str | None
    ttl: int = -1


SEAT_AVAILABLE = "AVAILABLE"
SEAT_HELD = "HELD"
SEAT_CONFIRMED = "CONFIRMED"


class StorageEngine:
    """In-memory key-value storage owned by the single command worker."""

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._store: dict[str, Entry] = {}
        self._clock = clock or time.monotonic

    def set(self, key: str, value: str) -> None:
        self._store[key] = Entry(value=value)

    def get(self, key: str) -> str | None:
        self._purge_if_expired(key)
        entry = self._store.get(key)
        if entry is None:
            return None
        return entry.value

    def delete(self, key: str) -> bool:
        self._purge_if_expired(key)
        if key not in self._store:
            return False

        self._delete_key(key)
        return True

    def expire(self, key: str, seconds: int, option: str | None = None) -> bool:
        option = normalize_expire_option(option)
        now = self._clock()

        if self._purge_if_expired(key, now=now):
            return False

        entry = self._store.get(key)
        if entry is None:
            return False

        current_deadline = entry.expires_at
        new_deadline = compute_deadline(now, seconds)
        if not should_apply_expiry(option, current_deadline, new_deadline):
            return False

        if seconds <= 0:
            self._delete_key(key)
            return True

        entry.expires_at = new_deadline
        return True

    def ttl(self, key: str) -> int:
        now = self._clock()
        if self._purge_if_expired(key, now=now):
            return -2

        entry = self._store.get(key)
        if entry is None:
            return -2
        if entry.expires_at is None:
            return -1

        return max(0, math.ceil(entry.expires_at - now))

    def _purge_if_expired(self, key: str, now: float | None = None) -> bool:
        entry = self._store.get(key)
        if entry is None or entry.expires_at is None:
            return False

        current_time = self._clock() if now is None else now
        if not is_expired(entry.expires_at, current_time):
            return False

        self._delete_key(key)
        return True

    def _delete_key(self, key: str) -> None:
        self._store.pop(key, None)

    def reserve_seat(
        self,
        event_id: str,
        seat_id: str,
        user_id: str,
        hold_seconds: int,
    ) -> tuple[bool, SeatStatus]:
        if hold_seconds <= 0:
            raise ValueError("RESERVE_SEAT ttl_seconds must be a positive integer")

        key = self._seat_key(event_id, seat_id)
        now = self._clock()
        status = self._seat_status_by_key(key, now=now)

        if status.state == SEAT_AVAILABLE or (
            status.state == SEAT_HELD and status.user_id == user_id
        ):
            deadline = compute_deadline(now, hold_seconds)
            self._store[key] = Entry(
                value=self._serialize_seat_record(SEAT_HELD, user_id),
                expires_at=deadline,
            )
            return True, SeatStatus(SEAT_HELD, user_id, hold_seconds)

        return False, status

    def confirm_seat(
        self,
        event_id: str,
        seat_id: str,
        user_id: str,
    ) -> tuple[bool, SeatStatus]:
        key = self._seat_key(event_id, seat_id)
        now = self._clock()
        status = self._seat_status_by_key(key, now=now)

        if status.state == SEAT_CONFIRMED and status.user_id == user_id:
            return True, status

        if status.state != SEAT_HELD or status.user_id != user_id:
            return False, status

        self._store[key] = Entry(
            value=self._serialize_seat_record(SEAT_CONFIRMED, user_id),
            expires_at=None,
        )
        return True, SeatStatus(SEAT_CONFIRMED, user_id, -1)

    def release_seat(
        self,
        event_id: str,
        seat_id: str,
        user_id: str,
    ) -> tuple[bool, SeatStatus]:
        key = self._seat_key(event_id, seat_id)
        now = self._clock()
        status = self._seat_status_by_key(key, now=now)

        if status.state != SEAT_HELD or status.user_id != user_id:
            return False, status

        self._delete_key(key)
        return True, SeatStatus(SEAT_AVAILABLE, None, -1)

    def seat_status(self, event_id: str, seat_id: str) -> SeatStatus:
        return self._seat_status_by_key(
            self._seat_key(event_id, seat_id),
            now=self._clock(),
        )

    def join_queue(self, event_id: str, user_id: str) -> tuple[bool, int, int]:
        key = self._queue_key(event_id)
        queue = self._load_queue(key)

        if user_id in queue:
            position = queue.index(user_id) + 1
            return False, position, len(queue)

        queue.append(user_id)
        self._store_queue(key, queue)
        return True, len(queue), len(queue)

    def queue_position(self, event_id: str, user_id: str) -> tuple[int, int]:
        queue = self._load_queue(self._queue_key(event_id))

        if user_id not in queue:
            return -1, len(queue)

        return queue.index(user_id) + 1, len(queue)

    def pop_queue(self, event_id: str) -> tuple[str | None, int]:
        key = self._queue_key(event_id)
        queue = self._load_queue(key)

        if not queue:
            return None, 0

        user_id = queue.pop(0)
        self._store_queue(key, queue)
        return user_id, len(queue)

    def leave_queue(self, event_id: str, user_id: str) -> tuple[bool, int, int]:
        key = self._queue_key(event_id)
        queue = self._load_queue(key)

        if user_id not in queue:
            return False, -1, len(queue)

        position = queue.index(user_id) + 1
        queue.remove(user_id)
        self._store_queue(key, queue)
        return True, position, len(queue)

    def peek_queue(self, event_id: str) -> tuple[str | None, int]:
        queue = self._load_queue(self._queue_key(event_id))
        if not queue:
            return None, 0
        return queue[0], len(queue)

    def _seat_status_by_key(self, key: str, now: float) -> SeatStatus:
        if self._purge_if_expired(key, now=now):
            return SeatStatus(SEAT_AVAILABLE, None, -1)

        entry = self._store.get(key)
        if entry is None:
            return SeatStatus(SEAT_AVAILABLE, None, -1)

        state, user_id = self._deserialize_seat_record(entry.value)
        ttl = -1
        if entry.expires_at is not None:
            ttl = max(0, math.ceil(entry.expires_at - now))

        return SeatStatus(state, user_id, ttl)

    @staticmethod
    def _seat_key(event_id: str, seat_id: str) -> str:
        return f"seat:{event_id}:{seat_id}"

    @staticmethod
    def _serialize_seat_record(state: str, user_id: str | None) -> str:
        return json.dumps(
            {"state": state, "user_id": user_id},
            separators=(",", ":"),
        )

    @staticmethod
    def _deserialize_seat_record(raw_value: str) -> tuple[str, str | None]:
        payload = json.loads(raw_value)
        state = payload.get("state")
        user_id = payload.get("user_id")
        if not isinstance(state, str):
            raise ValueError("seat record state must be a string")
        if user_id is not None and not isinstance(user_id, str):
            raise ValueError("seat record user_id must be a string or null")
        return state, user_id

    @staticmethod
    def _queue_key(event_id: str) -> str:
        return f"queue:{event_id}"

    def _load_queue(self, key: str) -> list[str]:
        entry = self._store.get(key)
        if entry is None:
            return []
        return self._deserialize_queue(entry.value)

    def _store_queue(self, key: str, queue: list[str]) -> None:
        if not queue:
            self._delete_key(key)
            return

        self._store[key] = Entry(
            value=self._serialize_queue(queue),
            expires_at=None,
        )

    @staticmethod
    def _serialize_queue(queue: list[str]) -> str:
        return json.dumps(queue, separators=(",", ":"))

    @staticmethod
    def _deserialize_queue(raw_value: str) -> list[str]:
        payload = json.loads(raw_value)
        if not isinstance(payload, list):
            raise ValueError("queue record must be a list")
        if any(not isinstance(item, str) for item in payload):
            raise ValueError("queue entries must be strings")
        return payload
