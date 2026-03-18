from __future__ import annotations

import pytest

from storage.engine import StorageEngine


class FakeClock:
    def __init__(self, start: float = 100.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def test_set_then_get_returns_value() -> None:
    storage = StorageEngine()

    storage.set("a", "1")

    assert storage.get("a") == "1"


def test_set_overwrites_existing_value_and_clears_existing_ttl() -> None:
    clock = FakeClock()
    storage = StorageEngine(clock=clock)

    storage.set("a", "1")
    assert storage.expire("a", 5) is True

    clock.advance(2)
    storage.set("a", "2")
    clock.advance(10)

    assert storage.get("a") == "2"


def test_delete_existing_key_returns_true_and_removes_value_and_ttl() -> None:
    clock = FakeClock()
    storage = StorageEngine(clock=clock)

    storage.set("a", "1")
    assert storage.expire("a", 5) is True

    assert storage.delete("a") is True
    assert storage.get("a") is None

    storage.set("a", "2")
    clock.advance(10)

    assert storage.get("a") == "2"


def test_missing_key_lookup_and_delete_behave_as_expected() -> None:
    storage = StorageEngine()

    assert storage.get("missing") is None
    assert storage.delete("missing") is False


def test_expire_existing_key_returns_true_and_removes_value_after_deadline() -> None:
    clock = FakeClock()
    storage = StorageEngine(clock=clock)

    storage.set("a", "1")

    assert storage.expire("a", 5) is True
    assert storage.get("a") == "1"

    clock.advance(5)

    assert storage.get("a") is None


def test_ttl_returns_remaining_seconds_for_volatile_key() -> None:
    clock = FakeClock()
    storage = StorageEngine(clock=clock)

    storage.set("a", "1")
    assert storage.expire("a", 5) is True

    assert storage.ttl("a") == 5

    clock.advance(2)

    assert storage.ttl("a") == 3


def test_ttl_returns_minus_one_for_persistent_key() -> None:
    storage = StorageEngine()

    storage.set("a", "1")

    assert storage.ttl("a") == -1


def test_ttl_returns_minus_two_for_missing_or_expired_key() -> None:
    clock = FakeClock()
    storage = StorageEngine(clock=clock)

    assert storage.ttl("missing") == -2

    storage.set("a", "1")
    assert storage.expire("a", 1) is True

    clock.advance(1)

    assert storage.ttl("a") == -2
    assert storage.get("a") is None


def test_expire_missing_or_expired_key_returns_false() -> None:
    clock = FakeClock()
    storage = StorageEngine(clock=clock)

    assert storage.expire("missing", 5) is False

    storage.set("a", "1")
    assert storage.expire("a", 1) is True

    clock.advance(1)

    assert storage.expire("a", 5) is False
    assert storage.delete("a") is False


def test_reapplying_expire_refreshes_deadline() -> None:
    clock = FakeClock()
    storage = StorageEngine(clock=clock)

    storage.set("a", "1")
    assert storage.expire("a", 5) is True

    clock.advance(4)
    assert storage.expire("a", 5) is True

    clock.advance(2)
    assert storage.get("a") == "1"

    clock.advance(4)
    assert storage.get("a") is None


def test_expire_nx_only_applies_to_persistent_keys() -> None:
    storage = StorageEngine()

    storage.set("a", "1")

    assert storage.expire("a", 5, "NX") is True
    assert storage.expire("a", 10, "NX") is False


def test_expire_xx_only_applies_to_volatile_keys() -> None:
    storage = StorageEngine()

    storage.set("a", "1")

    assert storage.expire("a", 5, "XX") is False
    assert storage.expire("a", 5) is True
    assert storage.expire("a", 10, "XX") is True


def test_expire_gt_and_lt_compare_against_existing_deadline() -> None:
    storage = StorageEngine()

    storage.set("a", "1")
    assert storage.expire("a", 10) is True

    assert storage.expire("a", 5, "GT") is False
    assert storage.expire("a", 20, "GT") is True
    assert storage.expire("a", 25, "LT") is False
    assert storage.expire("a", 15, "LT") is True


def test_persistent_key_is_treated_as_infinite_ttl_for_gt_and_lt() -> None:
    storage = StorageEngine()

    storage.set("a", "1")

    assert storage.expire("a", 10, "GT") is False
    assert storage.expire("a", 10, "LT") is True


@pytest.mark.parametrize("seconds", [0, -5])
def test_expire_with_non_positive_seconds_deletes_immediately(seconds: int) -> None:
    storage = StorageEngine()

    storage.set("a", "1")

    assert storage.expire("a", seconds) is True
    assert storage.get("a") is None
