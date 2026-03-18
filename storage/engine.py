"""Storage engine contract."""

from __future__ import annotations

from dataclasses import dataclass
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
