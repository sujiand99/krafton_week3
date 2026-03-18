from __future__ import annotations

from contextlib import closing
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from ticketing_api.app import create_app
from ticketing_api.database import SQLiteDatabase
from ticketing_api.demo_layout import DEMO_EVENT_ID, DEMO_SEAT_COUNT
from ticketing_api.repository import TicketingRepository
from ticketing_api.seed_demo import seed_demo_data


def make_db_path() -> Path:
    return Path(".test_tmp") / f"{uuid4().hex}.db"


def cleanup_db_path(db_path: Path) -> None:
    db_path.unlink(missing_ok=True)


def test_schema_initialization_creates_expected_tables() -> None:
    db_path = make_db_path()
    database = SQLiteDatabase(db_path)

    try:
        database.initialize()
        with closing(database.connect()) as conn:
            rows = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                ORDER BY name
                """
            ).fetchall()

        assert {row["name"] for row in rows} >= {
            "events",
            "payments",
            "reservations",
            "seats",
            "users",
        }
    finally:
        cleanup_db_path(db_path)


def test_seed_demo_data_populates_events_and_seats() -> None:
    db_path = make_db_path()

    try:
        seed_demo_data(db_path)
        repository = TicketingRepository(SQLiteDatabase(db_path))

        events = repository.list_events()
        seats = repository.list_seats(DEMO_EVENT_ID)

        assert len(events) == 1
        assert len(seats) == DEMO_SEAT_COUNT
        assert seats[0]["status"] == "AVAILABLE"
    finally:
        cleanup_db_path(db_path)


def test_create_held_reservation_and_idempotent_retry() -> None:
    db_path = make_db_path()
    seed_demo_data(db_path)

    try:
        with TestClient(create_app(db_path)) as client:
            payload = {
                "reservation_id": "res-1",
                "event_id": "concert-seoul-2026",
                "seat_id": "A1",
                "user_id": "user-1",
                "hold_token": "hold-1",
                "expires_at": "2026-03-19T11:05:00Z",
            }

            first = client.post("/reservations/held", json=payload)
            second = client.post("/reservations/held", json=payload)

        assert first.status_code == 201
        assert second.status_code == 200
        assert first.json()["status"] == "HELD"
        assert second.json()["reservation_id"] == "res-1"
    finally:
        cleanup_db_path(db_path)


def test_create_held_reservation_auto_creates_load_user() -> None:
    db_path = make_db_path()
    seed_demo_data(db_path)

    try:
        with TestClient(create_app(db_path)) as client:
            response = client.post(
                "/reservations/held",
                json={
                    "reservation_id": "res-load-1",
                    "event_id": "concert-seoul-2026",
                    "seat_id": "A1",
                    "user_id": "load-user-00001",
                    "hold_token": "hold-load-1",
                    "expires_at": "2026-03-19T11:05:00Z",
                },
            )
            reservations = client.get("/users/load-user-00001/reservations")

        assert response.status_code == 201
        assert response.json()["user_id"] == "load-user-00001"
        assert reservations.status_code == 200
        assert reservations.json()[0]["reservation_id"] == "res-load-1"
    finally:
        cleanup_db_path(db_path)


def test_create_held_reservation_rejects_payload_mismatch() -> None:
    db_path = make_db_path()
    seed_demo_data(db_path)

    try:
        with TestClient(create_app(db_path)) as client:
            payload = {
                "reservation_id": "res-1",
                "event_id": "concert-seoul-2026",
                "seat_id": "A1",
                "user_id": "user-1",
                "hold_token": "hold-1",
                "expires_at": "2026-03-19T11:05:00Z",
            }
            client.post("/reservations/held", json=payload)
            payload["seat_id"] = "A2"
            response = client.post("/reservations/held", json=payload)

        assert response.status_code == 409
    finally:
        cleanup_db_path(db_path)


def test_confirm_reservation_transitions_held_to_confirmed() -> None:
    db_path = make_db_path()
    seed_demo_data(db_path)

    try:
        with TestClient(create_app(db_path)) as client:
            held = {
                "reservation_id": "res-2",
                "event_id": "concert-seoul-2026",
                "seat_id": "A2",
                "user_id": "user-1",
                "hold_token": "hold-2",
                "expires_at": "2026-03-19T11:10:00Z",
            }
            client.post("/reservations/held", json=held)
            response = client.post(
                "/reservations/res-2/confirm",
                json={
                    "payment_id": "pay-1",
                    "amount": 120000,
                    "provider": "demo-pay",
                    "provider_ref": "demo-pay-1",
                },
            )

        body = response.json()
        assert response.status_code == 200
        assert body["status"] == "CONFIRMED"
        assert body["payment_status"] == "SUCCEEDED"
    finally:
        cleanup_db_path(db_path)


def test_confirm_reservation_is_idempotent_for_same_payment_payload() -> None:
    db_path = make_db_path()
    seed_demo_data(db_path)

    try:
        with TestClient(create_app(db_path)) as client:
            client.post(
                "/reservations/held",
                json={
                    "reservation_id": "res-3",
                    "event_id": "concert-seoul-2026",
                    "seat_id": "A3",
                    "user_id": "user-1",
                    "hold_token": "hold-3",
                    "expires_at": "2026-03-19T11:15:00Z",
                },
            )
            payload = {
                "payment_id": "pay-3",
                "amount": 120000,
                "provider": "demo-pay",
                "provider_ref": "demo-pay-3",
            }
            first = client.post("/reservations/res-3/confirm", json=payload)
            second = client.post("/reservations/res-3/confirm", json=payload)

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["status"] == "CONFIRMED"
    finally:
        cleanup_db_path(db_path)


def test_confirm_reservation_rejects_duplicate_confirmed_seat() -> None:
    db_path = make_db_path()
    seed_demo_data(db_path)

    try:
        with TestClient(create_app(db_path)) as client:
            client.post(
                "/reservations/held",
                json={
                    "reservation_id": "res-4a",
                    "event_id": "concert-seoul-2026",
                    "seat_id": "A4",
                    "user_id": "user-1",
                    "hold_token": "hold-4a",
                    "expires_at": "2026-03-19T11:20:00Z",
                },
            )
            client.post(
                "/reservations/held",
                json={
                    "reservation_id": "res-4b",
                    "event_id": "concert-seoul-2026",
                    "seat_id": "A4",
                    "user_id": "user-2",
                    "hold_token": "hold-4b",
                    "expires_at": "2026-03-19T11:20:30Z",
                },
            )
            first = client.post(
                "/reservations/res-4a/confirm",
                json={
                    "payment_id": "pay-4a",
                    "amount": 120000,
                    "provider": "demo-pay",
                    "provider_ref": "demo-pay-4a",
                },
            )
            second = client.post(
                "/reservations/res-4b/confirm",
                json={
                    "payment_id": "pay-4b",
                    "amount": 120000,
                    "provider": "demo-pay",
                    "provider_ref": "demo-pay-4b",
                },
            )

        assert first.status_code == 200
        assert second.status_code == 409
    finally:
        cleanup_db_path(db_path)


def test_cancel_reservation_transitions_held_to_cancelled() -> None:
    db_path = make_db_path()
    seed_demo_data(db_path)

    try:
        with TestClient(create_app(db_path)) as client:
            client.post(
                "/reservations/held",
                json={
                    "reservation_id": "res-5",
                    "event_id": "concert-seoul-2026",
                    "seat_id": "A5",
                    "user_id": "user-1",
                    "hold_token": "hold-5",
                    "expires_at": "2026-03-19T11:25:00Z",
                },
            )
            response = client.post(
                "/reservations/res-5/cancel",
                json={
                    "payment_id": "pay-5",
                    "payment_status": "FAILED",
                    "amount": 120000,
                    "provider": "demo-pay",
                    "provider_ref": "demo-pay-5",
                },
            )

        assert response.status_code == 200
        assert response.json()["status"] == "CANCELLED"
        assert response.json()["payment_status"] == "FAILED"
    finally:
        cleanup_db_path(db_path)


def test_expire_reservation_transitions_held_to_expired() -> None:
    db_path = make_db_path()
    seed_demo_data(db_path)

    try:
        with TestClient(create_app(db_path)) as client:
            client.post(
                "/reservations/held",
                json={
                    "reservation_id": "res-6",
                    "event_id": "concert-seoul-2026",
                    "seat_id": "A6",
                    "user_id": "user-1",
                    "hold_token": "hold-6",
                    "expires_at": "2026-03-19T11:30:00Z",
                },
            )
            response = client.post("/reservations/res-6/expire")

        assert response.status_code == 200
        assert response.json()["status"] == "EXPIRED"
    finally:
        cleanup_db_path(db_path)


def test_confirmed_reservation_cannot_be_cancelled_or_expired() -> None:
    db_path = make_db_path()
    seed_demo_data(db_path)

    try:
        with TestClient(create_app(db_path)) as client:
            client.post(
                "/reservations/held",
                json={
                    "reservation_id": "res-7",
                    "event_id": "concert-seoul-2026",
                    "seat_id": "A7",
                    "user_id": "user-1",
                    "hold_token": "hold-7",
                    "expires_at": "2026-03-19T11:35:00Z",
                },
            )
            client.post(
                "/reservations/res-7/confirm",
                json={
                    "payment_id": "pay-7",
                    "amount": 120000,
                    "provider": "demo-pay",
                    "provider_ref": "demo-pay-7",
                },
            )
            cancel_response = client.post("/reservations/res-7/cancel", json={})
            expire_response = client.post("/reservations/res-7/expire")

        assert cancel_response.status_code == 409
        assert expire_response.status_code == 409
    finally:
        cleanup_db_path(db_path)


def test_list_user_reservations_and_confirmed_seats() -> None:
    db_path = make_db_path()
    seed_demo_data(db_path)

    try:
        with TestClient(create_app(db_path)) as client:
            client.post(
                "/reservations/held",
                json={
                    "reservation_id": "res-8",
                    "event_id": "concert-seoul-2026",
                    "seat_id": "A8",
                    "user_id": "user-2",
                    "hold_token": "hold-8",
                    "expires_at": "2026-03-19T11:40:00Z",
                },
            )
            client.post(
                "/reservations/res-8/confirm",
                json={
                    "payment_id": "pay-8",
                    "amount": 120000,
                    "provider": "demo-pay",
                    "provider_ref": "demo-pay-8",
                },
            )
            reservations = client.get("/users/user-2/reservations")
            confirmed = client.get("/events/concert-seoul-2026/confirmed-seats")

        assert reservations.status_code == 200
        assert reservations.json()[0]["reservation_id"] == "res-8"
        assert confirmed.status_code == 200
        assert confirmed.json()[0]["seat_id"] == "A8"
    finally:
        cleanup_db_path(db_path)


def test_list_event_seats_marks_confirmed_seats_from_db_truth() -> None:
    db_path = make_db_path()
    seed_demo_data(db_path)

    try:
        with TestClient(create_app(db_path)) as client:
            client.post(
                "/reservations/held",
                json={
                    "reservation_id": "res-9",
                    "event_id": "concert-seoul-2026",
                    "seat_id": "B1",
                    "user_id": "user-3",
                    "hold_token": "hold-9",
                    "expires_at": "2026-03-19T11:45:00Z",
                },
            )
            client.post(
                "/reservations/res-9/confirm",
                json={
                    "payment_id": "pay-9",
                    "amount": 120000,
                    "provider": "demo-pay",
                    "provider_ref": "demo-pay-9",
                },
            )
            response = client.get("/events/concert-seoul-2026/seats")

        assert response.status_code == 200
        seats = {seat["seat_id"]: seat for seat in response.json()}
        assert seats["B1"]["status"] == "CONFIRMED"
        assert seats["B2"]["status"] == "AVAILABLE"
    finally:
        cleanup_db_path(db_path)
