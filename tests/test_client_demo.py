"""Tests for the ticketing demo client service."""

from __future__ import annotations

from pathlib import Path

from client.demo_service import TicketingDemoService


class FakeRedisClient:
    def __init__(self) -> None:
        self.now = 1000.0
        self.store: dict[str, tuple[str, float | None]] = {}

    def execute(self, command: list[str]):
        name = command[0].upper()
        if name == "SET":
            _, key, value = command
            self.store[key] = (value, None)
            return "OK"
        if name == "GET":
            _, key = command
            self._purge(key)
            row = self.store.get(key)
            return None if row is None else row[0]
        if name == "DEL":
            _, key = command
            self._purge(key)
            return 1 if self.store.pop(key, None) is not None else 0
        if name == "EXPIRE":
            _, key, raw_seconds, *rest = command
            self._purge(key)
            if key not in self.store:
                return 0
            if rest:
                raise AssertionError("Fake redis only expects plain EXPIRE in demo tests")
            seconds = int(raw_seconds)
            if seconds <= 0:
                self.store.pop(key, None)
                return 1
            value, _ = self.store[key]
            self.store[key] = (value, self.now + seconds)
            return 1
        if name == "TTL":
            _, key = command
            self._purge(key)
            row = self.store.get(key)
            if row is None:
                return -2
            _, expires_at = row
            if expires_at is None:
                return -1
            remaining = int(expires_at - self.now)
            return max(0, remaining)
        raise AssertionError(f"Unsupported command in fake redis: {command}")

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def _purge(self, key: str) -> None:
        row = self.store.get(key)
        if row is None:
            return
        _, expires_at = row
        if expires_at is not None and expires_at <= self.now:
            self.store.pop(key, None)


def create_service(tmp_path: Path) -> tuple[TicketingDemoService, FakeRedisClient]:
    redis = FakeRedisClient()
    service = TicketingDemoService(
        redis_client=redis,
        db_path=tmp_path / "demo.sqlite3",
        featured_seat_count=8,
    )
    service.bootstrap()
    return service, redis


def test_reserve_and_confirm_flow_updates_redis_and_db(tmp_path: Path) -> None:
    service, redis = create_service(tmp_path)

    reserve_result = service.reserve_seat(seat_id="S0001", user_id="user0001", ttl_seconds=10)
    assert reserve_result["ok"] is True
    assert reserve_result["seat"]["status"] == "HELD"
    assert reserve_result["seat"]["ttl_seconds"] == 10

    confirm_result = service.confirm_seat(seat_id="S0001", user_id="user0001")
    assert confirm_result["ok"] is True
    assert confirm_result["seat"]["status"] == "CONFIRMED"

    state = service.dashboard_state()
    assert state["summary"]["held"] == 0
    assert state["summary"]["confirmed"] == 1
    assert state["reservations"][0]["seat_id"] == "S0001"
    assert redis.execute(["GET", "seat:concert1:S0001"]) == "CONFIRMED:user0001"

    service.close()


def test_second_user_is_rejected_for_same_held_seat(tmp_path: Path) -> None:
    service, _ = create_service(tmp_path)

    first = service.reserve_seat(seat_id="S0001", user_id="user0001", ttl_seconds=10)
    second = service.reserve_seat(seat_id="S0001", user_id="user0002", ttl_seconds=10)

    assert first["ok"] is True
    assert second["ok"] is False
    assert second["seat"]["status"] == "HELD"
    assert second["seat"]["user_id"] == "user0001"

    service.close()


def test_expired_hold_returns_seat_to_available_and_logs_event(tmp_path: Path) -> None:
    service, redis = create_service(tmp_path)

    service.reserve_seat(seat_id="S0002", user_id="user0099", ttl_seconds=5)
    redis.advance(6)

    seat = service.seat_status(seat_id="S0002")
    state = service.dashboard_state()

    assert seat["seat"]["status"] == "AVAILABLE"
    assert state["summary"]["expired_holds"] == 1
    assert any("TTL expired on S0002" in entry["message"] for entry in state["logs"])

    service.close()


def test_release_flow_clears_hold_without_db_reservation(tmp_path: Path) -> None:
    service, _ = create_service(tmp_path)

    service.reserve_seat(seat_id="S0003", user_id="user0100", ttl_seconds=8)
    release = service.release_seat(seat_id="S0003", user_id="user0100")
    state = service.dashboard_state()

    assert release["ok"] is True
    assert release["seat"]["status"] == "AVAILABLE"
    assert state["summary"]["held"] == 0
    assert state["summary"]["cancelled_holds"] == 1

    service.close()


def test_simulate_surge_generates_held_and_rejected_counts(tmp_path: Path) -> None:
    service, _ = create_service(tmp_path)

    result = service.simulate_surge(contenders=24, focus_seats=4, ttl_seconds=9)
    state = service.dashboard_state()

    assert result["ok"] is True
    assert result["result"]["held"] <= 4
    assert result["result"]["rejected"] >= 20
    assert result["result"]["duration_ms"] >= 1
    assert state["summary"]["held"] == result["result"]["held"]
    assert state["summary"]["surge_runs"] == 1
    assert state["surge"]["contenders"] == 24
    assert len(state["surge"]["sample_winners"]) <= 4

    service.close()


def test_large_surge_summary_handles_ticket_open_scale(tmp_path: Path) -> None:
    service, _ = create_service(tmp_path)

    result = service.simulate_surge(contenders=10000, focus_seats=20, ttl_seconds=10)
    state = service.dashboard_state()

    assert result["ok"] is True
    assert result["result"]["held"] <= 20
    assert result["result"]["rejected"] >= 9980
    assert result["result"]["duration_ms"] >= 1
    assert state["surge"]["contenders"] == 10000
    assert state["surge"]["focus_seats"] == 20
    assert state["summary"]["held"] == result["result"]["held"]

    service.close()

def test_featured_seat_map_includes_metadata_and_spans_sections(tmp_path: Path) -> None:
    redis = FakeRedisClient()
    service = TicketingDemoService(
        redis_client=redis,
        db_path=tmp_path / "demo.sqlite3",
        featured_seat_count=40,
    )
    service.bootstrap()

    state = service.dashboard_state()
    featured = state["featured_seats"]

    assert featured[0]["seat_id"] == "S0001"
    assert {seat["section"] for seat in featured} >= {"VIP", "R", "S", "A"}
    assert all("row_label" in seat and "seat_number" in seat for seat in featured)

    service.close()
