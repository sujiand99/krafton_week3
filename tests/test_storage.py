from __future__ import annotations

import pytest

from storage.engine import (
    Entry,
    SEAT_AVAILABLE,
    SEAT_CONFIRMED,
    SEAT_HELD,
    SeatStatus,
    StorageEngine,
)


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


def test_storage_uses_entry_objects_for_values_and_ttl_metadata() -> None:
    storage = StorageEngine()

    storage.set("a", "1")

    assert storage._store["a"] == Entry(value="1", expires_at=None)


def test_set_overwrites_existing_value_and_clears_existing_ttl() -> None:
    clock = FakeClock()
    storage = StorageEngine(clock=clock)

    storage.set("a", "1")
    assert storage.expire("a", 5) is True

    clock.advance(2)
    storage.set("a", "2")
    clock.advance(10)

    assert storage.get("a") == "2"
    assert storage._store["a"] == Entry(value="2", expires_at=None)


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


def test_snapshot_excludes_expired_keys() -> None:
    clock = FakeClock()
    storage = StorageEngine(clock=clock)

    storage.set("a", "1")
    storage.set("b", "2")
    assert storage.expire("b", 5) is True

    clock.advance(5)

    assert storage.snapshot(now=clock()) == [("a", "1", None)]


def test_load_snapshot_restores_unexpired_entries_only() -> None:
    clock = FakeClock(start=200.0)
    storage = StorageEngine(clock=clock)

    storage.load_snapshot(
        [
            ("persistent", "1", None),
            ("volatile", "2", 210.0),
            ("expired", "3", 150.0),
        ],
        now=clock(),
    )

    assert storage.get("persistent") == "1"
    assert storage.get("volatile") == "2"
    assert storage.get("expired") is None
    assert storage.ttl("volatile") == 10


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


def test_reserve_seat_holds_available_seat_with_ttl() -> None:
    clock = FakeClock()
    storage = StorageEngine(clock=clock)

    success, status = storage.reserve_seat("concert", "A-1", "user-1", 30)

    assert success is True
    assert status == SeatStatus(SEAT_HELD, "user-1", 30)
    assert storage.seat_status("concert", "A-1") == SeatStatus(SEAT_HELD, "user-1", 30)


def test_reserve_seat_returns_existing_hold_for_different_user() -> None:
    clock = FakeClock()
    storage = StorageEngine(clock=clock)
    storage.reserve_seat("concert", "A-1", "user-1", 30)
    clock.advance(5)

    success, status = storage.reserve_seat("concert", "A-1", "user-2", 30)

    assert success is False
    assert status == SeatStatus(SEAT_HELD, "user-1", 25)


def test_reserve_seat_refreshes_ttl_for_same_user() -> None:
    clock = FakeClock()
    storage = StorageEngine(clock=clock)
    storage.reserve_seat("concert", "A-1", "user-1", 30)
    clock.advance(12)

    success, status = storage.reserve_seat("concert", "A-1", "user-1", 20)

    assert success is True
    assert status == SeatStatus(SEAT_HELD, "user-1", 20)


def test_confirm_seat_marks_held_seat_as_confirmed() -> None:
    storage = StorageEngine()
    storage.reserve_seat("concert", "A-1", "user-1", 30)

    success, status = storage.confirm_seat("concert", "A-1", "user-1")

    assert success is True
    assert status == SeatStatus(SEAT_CONFIRMED, "user-1", -1)
    assert storage.seat_status("concert", "A-1") == SeatStatus(
        SEAT_CONFIRMED,
        "user-1",
        -1,
    )


def test_confirm_seat_is_idempotent_for_same_user() -> None:
    storage = StorageEngine()
    storage.reserve_seat("concert", "A-1", "user-1", 30)
    storage.confirm_seat("concert", "A-1", "user-1")

    success, status = storage.confirm_seat("concert", "A-1", "user-1")

    assert success is True
    assert status == SeatStatus(SEAT_CONFIRMED, "user-1", -1)


def test_force_confirm_seat_marks_any_state_as_confirmed_db_truth() -> None:
    storage = StorageEngine()
    storage.reserve_seat("concert", "A-1", "user-1", 30)

    success, status = storage.force_confirm_seat("concert", "A-1", "user-2")

    assert success is True
    assert status == SeatStatus(SEAT_CONFIRMED, "user-2", -1)
    assert storage.seat_status("concert", "A-1") == SeatStatus(
        SEAT_CONFIRMED,
        "user-2",
        -1,
    )


def test_release_seat_returns_available_after_matching_hold() -> None:
    storage = StorageEngine()
    storage.reserve_seat("concert", "A-1", "user-1", 30)

    success, status = storage.release_seat("concert", "A-1", "user-1")

    assert success is True
    assert status == SeatStatus(SEAT_AVAILABLE, None, -1)
    assert storage.seat_status("concert", "A-1") == SeatStatus(SEAT_AVAILABLE, None, -1)


def test_release_seat_fails_for_different_user() -> None:
    storage = StorageEngine()
    storage.reserve_seat("concert", "A-1", "user-1", 30)

    success, status = storage.release_seat("concert", "A-1", "user-2")

    assert success is False
    assert status == SeatStatus(SEAT_HELD, "user-1", 30)


def test_seat_status_returns_available_after_hold_expiration() -> None:
    clock = FakeClock()
    storage = StorageEngine(clock=clock)
    storage.reserve_seat("concert", "A-1", "user-1", 5)

    clock.advance(5)

    assert storage.seat_status("concert", "A-1") == SeatStatus(SEAT_AVAILABLE, None, -1)


def test_join_queue_returns_position_and_prevents_duplicates() -> None:
    storage = StorageEngine()

    assert storage.join_queue("concert", "user-1") == (True, 1, 1)
    assert storage.join_queue("concert", "user-2") == (True, 2, 2)
    assert storage.join_queue("concert", "user-1") == (False, 1, 2)


def test_queue_position_reports_position_and_queue_length() -> None:
    storage = StorageEngine()
    storage.join_queue("concert", "user-1")
    storage.join_queue("concert", "user-2")

    assert storage.queue_position("concert", "user-2") == (2, 2)
    assert storage.queue_position("concert", "user-3") == (-1, 2)


def test_pop_queue_is_fifo_and_returns_remaining_length() -> None:
    storage = StorageEngine()
    storage.join_queue("concert", "user-1")
    storage.join_queue("concert", "user-2")

    assert storage.pop_queue("concert") == ("user-1", 1)
    assert storage.pop_queue("concert") == ("user-2", 0)
    assert storage.pop_queue("concert") == (None, 0)


def test_leave_queue_removes_user_and_reports_previous_position() -> None:
    storage = StorageEngine()
    storage.join_queue("concert", "user-1")
    storage.join_queue("concert", "user-2")
    storage.join_queue("concert", "user-3")

    assert storage.leave_queue("concert", "user-2") == (True, 2, 2)
    assert storage.queue_position("concert", "user-3") == (2, 2)
    assert storage.leave_queue("concert", "missing") == (False, -1, 2)


def test_peek_queue_returns_front_user_without_removing() -> None:
    storage = StorageEngine()
    storage.join_queue("concert", "user-1")
    storage.join_queue("concert", "user-2")

    assert storage.peek_queue("concert") == ("user-1", 2)
    assert storage.queue_position("concert", "user-1") == (1, 2)
    assert storage.peek_queue("empty-event") == (None, 0)
