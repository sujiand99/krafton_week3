from __future__ import annotations

from pathlib import Path
import threading
from uuid import uuid4

from fastapi.testclient import TestClient

from app_server.app import create_app
from app_server.db_client import TicketingDBClient
from app_server.redis_client import RedisRESPClient, SeatCommandResult, SeatStatus
from server.server import MiniRedisServer
from ticketing_api.app import create_app as create_db_app
from ticketing_api.seed_demo import seed_demo_data


def make_db_path() -> Path:
    return Path(".test_tmp") / f"{uuid4().hex}.db"


def test_app_server_lists_seats_with_redis_hold_overlay() -> None:
    db_path = make_db_path()
    seed_demo_data(db_path)
    redis_server = MiniRedisServer(port=0, db_path=None)
    redis_thread = threading.Thread(target=redis_server.serve_forever, daemon=True)
    redis_thread.start()
    host, port = redis_server.wait_until_started()

    try:
        redis_client = RedisRESPClient(host=host, port=port)
        redis_client.reserve_seat("concert-seoul-2026", "A1", "user-1", 30)

        with TestClient(create_db_app(db_path)) as db_http:
            app = create_app(
                redis_client=redis_client,
                db_client=TicketingDBClient(http_client=db_http),
            )
            with TestClient(app) as client:
                response = client.get("/events/concert-seoul-2026/seats")

        assert response.status_code == 200
        seats = {seat["seat_id"]: seat for seat in response.json()}
        assert seats["A1"]["status"] == "HELD"
        assert seats["A1"]["held_by_user_id"] == "user-1"
        assert seats["A1"]["hold_ttl"] == 30
    finally:
        redis_server.shutdown()
        redis_thread.join(timeout=2)
        db_path.unlink(missing_ok=True)


def test_app_server_hold_confirm_and_cancel_flow() -> None:
    db_path = make_db_path()
    seed_demo_data(db_path)
    redis_server = MiniRedisServer(port=0, db_path=None)
    redis_thread = threading.Thread(target=redis_server.serve_forever, daemon=True)
    redis_thread.start()
    host, port = redis_server.wait_until_started()

    try:
        with TestClient(create_db_app(db_path)) as db_http:
            app = create_app(
                redis_client=RedisRESPClient(host=host, port=port),
                db_client=TicketingDBClient(http_client=db_http),
            )
            with TestClient(app) as client:
                hold = client.post(
                    "/reservations/hold",
                    json={
                        "event_id": "concert-seoul-2026",
                        "seat_id": "A2",
                        "user_id": "user-1",
                        "hold_seconds": 45,
                    },
                )
                assert hold.status_code == 201
                reservation_id = hold.json()["reservation"]["reservation_id"]
                assert hold.json()["reservation"]["status"] == "HELD"
                assert hold.json()["seat"]["status"] == "HELD"

                confirm = client.post(
                    f"/reservations/{reservation_id}/confirm",
                    json={
                        "event_id": "concert-seoul-2026",
                        "seat_id": "A2",
                        "user_id": "user-1",
                    },
                )
                assert confirm.status_code == 200
                assert confirm.json()["reservation"]["status"] == "CONFIRMED"
                assert confirm.json()["seat"]["status"] == "CONFIRMED"
                assert confirm.json()["payment"]["status"] == "SUCCEEDED"

                reservations = client.get("/users/user-1/reservations")
                assert reservations.status_code == 200
                assert reservations.json()[0]["reservation_id"] == reservation_id

                cancel = client.post(
                    f"/reservations/{reservation_id}/cancel",
                    json={
                        "event_id": "concert-seoul-2026",
                        "seat_id": "A2",
                        "user_id": "user-1",
                    },
                )
                assert cancel.status_code == 409
    finally:
        redis_server.shutdown()
        redis_thread.join(timeout=2)
        db_path.unlink(missing_ok=True)


def test_app_server_accepts_synthetic_load_users() -> None:
    db_path = make_db_path()
    seed_demo_data(db_path)
    redis_server = MiniRedisServer(port=0, db_path=None)
    redis_thread = threading.Thread(target=redis_server.serve_forever, daemon=True)
    redis_thread.start()
    host, port = redis_server.wait_until_started()

    try:
        with TestClient(create_db_app(db_path)) as db_http:
            app = create_app(
                redis_client=RedisRESPClient(host=host, port=port),
                db_client=TicketingDBClient(http_client=db_http),
            )
            with TestClient(app) as client:
                response = client.post(
                    "/reservations/hold",
                    json={
                        "event_id": "concert-seoul-2026",
                        "seat_id": "A5",
                        "user_id": "load-user-00001",
                        "hold_seconds": 45,
                    },
                )

        assert response.status_code == 201
        assert response.json()["reservation"]["user_id"] == "load-user-00001"
        assert response.json()["seat"]["held_by_user_id"] == "load-user-00001"
    finally:
        redis_server.shutdown()
        redis_thread.join(timeout=2)
        db_path.unlink(missing_ok=True)


def test_app_server_rejects_holding_a_busy_seat() -> None:
    db_path = make_db_path()
    seed_demo_data(db_path)
    redis_server = MiniRedisServer(port=0, db_path=None)
    redis_thread = threading.Thread(target=redis_server.serve_forever, daemon=True)
    redis_thread.start()
    host, port = redis_server.wait_until_started()

    try:
        with TestClient(create_db_app(db_path)) as db_http:
            app = create_app(
                redis_client=RedisRESPClient(host=host, port=port),
                db_client=TicketingDBClient(http_client=db_http),
            )
            with TestClient(app) as client:
                first = client.post(
                    "/reservations/hold",
                    json={
                        "event_id": "concert-seoul-2026",
                        "seat_id": "A3",
                        "user_id": "user-1",
                        "hold_seconds": 30,
                    },
                )
                second = client.post(
                    "/reservations/hold",
                    json={
                        "event_id": "concert-seoul-2026",
                        "seat_id": "A3",
                        "user_id": "user-2",
                        "hold_seconds": 30,
                    },
                )

        assert first.status_code == 201
        assert second.status_code == 409
        assert "already held" in second.json()["detail"]
    finally:
        redis_server.shutdown()
        redis_thread.join(timeout=2)
        db_path.unlink(missing_ok=True)


def test_app_server_purchase_endpoint_confirms_with_mock_payment() -> None:
    db_path = make_db_path()
    seed_demo_data(db_path)
    redis_server = MiniRedisServer(port=0, db_path=None)
    redis_thread = threading.Thread(target=redis_server.serve_forever, daemon=True)
    redis_thread.start()
    host, port = redis_server.wait_until_started()

    try:
        with TestClient(create_db_app(db_path)) as db_http:
            app = create_app(
                redis_client=RedisRESPClient(host=host, port=port),
                db_client=TicketingDBClient(http_client=db_http),
            )
            with TestClient(app) as client:
                response = client.post(
                    "/reservations/purchase",
                    json={
                        "event_id": "concert-seoul-2026",
                        "seat_id": "A4",
                        "user_id": "user-2",
                        "hold_seconds": 30,
                    },
                )

        assert response.status_code == 201
        body = response.json()
        assert body["reservation"]["status"] == "CONFIRMED"
        assert body["seat"]["status"] == "CONFIRMED"
        assert body["payment"]["provider"] == "mock-pay"
    finally:
        redis_server.shutdown()
        redis_thread.join(timeout=2)
        db_path.unlink(missing_ok=True)


def test_app_server_exposes_queue_endpoints() -> None:
    db_path = make_db_path()
    seed_demo_data(db_path)
    redis_server = MiniRedisServer(port=0, db_path=None)
    redis_thread = threading.Thread(target=redis_server.serve_forever, daemon=True)
    redis_thread.start()
    host, port = redis_server.wait_until_started()

    try:
        with TestClient(create_db_app(db_path)) as db_http:
            app = create_app(
                redis_client=RedisRESPClient(host=host, port=port),
                db_client=TicketingDBClient(http_client=db_http),
            )
            with TestClient(app) as client:
                first = client.post(
                    "/queue/join",
                    json={"event_id": "concert-seoul-2026", "user_id": "user-1"},
                )
                second = client.post(
                    "/queue/join",
                    json={"event_id": "concert-seoul-2026", "user_id": "user-2"},
                )
                position = client.get("/queue/concert-seoul-2026/users/user-2/position")
                peek = client.get("/queue/concert-seoul-2026/peek")
                leave = client.post(
                    "/queue/leave",
                    json={"event_id": "concert-seoul-2026", "user_id": "user-1"},
                )

        assert first.status_code == 201
        assert second.status_code == 201
        assert position.json() == {"position": 2, "queue_length": 2}
        assert peek.json() == {"user_id": "user-1", "queue_length": 2}
        assert leave.json() == {
            "removed": True,
            "previous_position": 1,
            "queue_length": 1,
        }
    finally:
        redis_server.shutdown()
        redis_thread.join(timeout=2)
        db_path.unlink(missing_ok=True)


def test_app_server_uses_force_confirm_after_db_commit() -> None:
    class ForceOnlyRedis:
        def __init__(self) -> None:
            self._status = SeatStatus("AVAILABLE", None, -1)

        def seat_status(self, event_id: str, seat_id: str) -> SeatStatus:
            return self._status

        def reserve_seat(
            self,
            event_id: str,
            seat_id: str,
            user_id: str,
            hold_seconds: int,
        ) -> SeatCommandResult:
            self._status = SeatStatus("HELD", user_id, hold_seconds)
            return SeatCommandResult(True, "HELD", user_id, hold_seconds)

        def confirm_seat(self, event_id: str, seat_id: str, user_id: str) -> SeatCommandResult:
            raise AssertionError("confirm_seat should not be used for DB-truth finalization")

        def force_confirm_seat(
            self,
            event_id: str,
            seat_id: str,
            user_id: str,
        ) -> SeatCommandResult:
            self._status = SeatStatus("CONFIRMED", user_id, -1)
            return SeatCommandResult(True, "CONFIRMED", user_id, -1)

        def release_seat(self, event_id: str, seat_id: str, user_id: str) -> SeatCommandResult:
            self._status = SeatStatus("AVAILABLE", None, -1)
            return SeatCommandResult(True, "AVAILABLE", None, -1)

        def join_queue(self, event_id: str, user_id: str) -> tuple[bool, int, int]:
            raise NotImplementedError

        def queue_position(self, event_id: str, user_id: str) -> tuple[int, int]:
            raise NotImplementedError

        def leave_queue(self, event_id: str, user_id: str) -> tuple[bool, int, int]:
            raise NotImplementedError

        def peek_queue(self, event_id: str) -> tuple[str | None, int]:
            raise NotImplementedError

    db_path = make_db_path()
    seed_demo_data(db_path)

    try:
        with TestClient(create_db_app(db_path)) as db_http:
            app = create_app(
                redis_client=ForceOnlyRedis(),
                db_client=TicketingDBClient(http_client=db_http),
            )
            with TestClient(app) as client:
                hold = client.post(
                    "/reservations/hold",
                    json={
                        "event_id": "concert-seoul-2026",
                        "seat_id": "A6",
                        "user_id": "user-1",
                        "hold_seconds": 45,
                    },
                )
                reservation_id = hold.json()["reservation"]["reservation_id"]
                confirm = client.post(
                    f"/reservations/{reservation_id}/confirm",
                    json={
                        "event_id": "concert-seoul-2026",
                        "seat_id": "A6",
                        "user_id": "user-1",
                    },
                )

        assert hold.status_code == 201
        assert confirm.status_code == 200
        assert confirm.json()["seat"]["status"] == "CONFIRMED"
    finally:
        db_path.unlink(missing_ok=True)
