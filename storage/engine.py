"""Storage engine contract."""

from __future__ import annotations

import math
import time
from typing import Callable

from storage.ttl import compute_deadline, is_expired, normalize_expire_option, should_apply_expiry


class StorageEngine:
    """In-memory key-value storage."""

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._store: dict[str, str] = {}
        self._expires_at: dict[str, float] = {}
        self._clock = clock or time.monotonic

    def set(self, key: str, value: str) -> None:
        self._store[key] = value
        self._expires_at.pop(key, None)

    def get(self, key: str) -> str | None:
        self._purge_if_expired(key)
        return self._store.get(key)

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
        if key not in self._store:
            return False

        current_deadline = self._expires_at.get(key)
        new_deadline = compute_deadline(now, seconds)
        if not should_apply_expiry(option, current_deadline, new_deadline):
            return False

        if seconds <= 0:
            self._delete_key(key)
            return True

        self._expires_at[key] = new_deadline
        return True

    def ttl(self, key: str) -> int:
        now = self._clock()
        if self._purge_if_expired(key, now=now):
            return -2
        if key not in self._store:
            return -2

        deadline = self._expires_at.get(key)
        if deadline is None:
            return -1

        return max(0, math.ceil(deadline - now))

    def _purge_if_expired(self, key: str, now: float | None = None) -> bool:
        deadline = self._expires_at.get(key)
        if deadline is None:
            return False

        current_time = self._clock() if now is None else now
        if not is_expired(deadline, current_time):
            return False

        self._delete_key(key)
        return True

    def _delete_key(self, key: str) -> None:
        self._store.pop(key, None)
        self._expires_at.pop(key, None)
