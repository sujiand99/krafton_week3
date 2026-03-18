"""Storage engine contract."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Iterable
from typing import Callable, TypeAlias

from storage.ttl import compute_deadline, is_expired, normalize_expire_option, should_apply_expiry

SnapshotEntry: TypeAlias = tuple[str, str, float | None]


class StorageEngine:
    """In-memory key-value storage."""

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._store: dict[str, str] = {}
        self._expires_at: dict[str, float] = {}
        self._clock = clock or time.time
        self._lock = threading.RLock()

    def set(self, key: str, value: str) -> None:
        with self._lock:
            self._store[key] = value
            self._expires_at.pop(key, None)

    def get(self, key: str) -> str | None:
        with self._lock:
            self._purge_if_expired(key)
            return self._store.get(key)

    def delete(self, key: str) -> bool:
        with self._lock:
            self._purge_if_expired(key)
            if key not in self._store:
                return False

            self._delete_key(key)
            return True

    def expire(self, key: str, seconds: int, option: str | None = None) -> bool:
        with self._lock:
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
        with self._lock:
            now = self._clock()
            if self._purge_if_expired(key, now=now):
                return -2
            if key not in self._store:
                return -2

            deadline = self._expires_at.get(key)
            if deadline is None:
                return -1

            return max(0, math.ceil(deadline - now))

    def snapshot(self, now: float | None = None) -> list[SnapshotEntry]:
        with self._lock:
            current_time = self._clock() if now is None else now
            self._purge_expired_keys(current_time)
            return [
                (key, value, self._expires_at.get(key))
                for key, value in self._store.items()
            ]

    def load_snapshot(
        self,
        entries: Iterable[SnapshotEntry],
        now: float | None = None,
    ) -> None:
        with self._lock:
            current_time = self._clock() if now is None else now
            self._store.clear()
            self._expires_at.clear()

            for key, value, deadline in entries:
                if deadline is not None and is_expired(deadline, current_time):
                    continue

                self._store[key] = value
                if deadline is not None:
                    self._expires_at[key] = deadline

    def _purge_if_expired(self, key: str, now: float | None = None) -> bool:
        deadline = self._expires_at.get(key)
        if deadline is None:
            return False

        current_time = self._clock() if now is None else now
        if not is_expired(deadline, current_time):
            return False

        self._delete_key(key)
        return True

    def _purge_expired_keys(self, now: float) -> None:
        expired_keys = [
            key for key, deadline in self._expires_at.items() if is_expired(deadline, now)
        ]
        for key in expired_keys:
            self._delete_key(key)

    def _delete_key(self, key: str) -> None:
        self._store.pop(key, None)
        self._expires_at.pop(key, None)
