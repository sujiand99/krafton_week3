"""Service layer for the ticketing DB API."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from ticketing_api.repository import TicketingRepository
from ticketing_api.schemas import (
    CancelReservationRequest,
    ConfirmReservationRequest,
    HeldReservationCreate,
)


class TicketingServiceError(Exception):
    """Base service-layer error."""


class NotFoundError(TicketingServiceError):
    """Raised when a requested resource does not exist."""


class ConflictError(TicketingServiceError):
    """Raised when a request conflicts with current state."""


def normalize_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def current_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class TicketingService:
    """Application service for ticketing persistence workflows."""

    def __init__(self, repository: TicketingRepository) -> None:
        self._repository = repository

    def initialize(self) -> None:
        self._repository.initialize()

    def seed_demo_data(self) -> None:
        self._repository.seed_demo_data()

    def list_events(self) -> list[dict[str, object]]:
        return self._repository.list_events()

    def list_event_seats(self, event_id: str) -> list[dict[str, object]]:
        self._expire_stale_reservations()
        self._require_event(event_id)
        return self._repository.list_seats(event_id)

    def create_held_reservation(
        self,
        request: HeldReservationCreate,
    ) -> tuple[dict[str, object], bool]:
        self._expire_stale_reservations()
        self._require_event(request.event_id)
        self._require_seat(request.event_id, request.seat_id)
        self._ensure_user(request.user_id)

        existing = self._repository.get_reservation(request.reservation_id)
        request_expires_at = normalize_timestamp(request.expires_at)
        if existing is not None:
            if self._held_request_matches(existing, request, request_expires_at):
                return existing, False
            raise ConflictError(
                f"reservation_id '{request.reservation_id}' already exists with different payload"
            )

        if self._repository.has_confirmed_reservation(request.event_id, request.seat_id):
            raise ConflictError(
                f"seat '{request.seat_id}' for event '{request.event_id}' is already confirmed"
            )

        try:
            created = self._repository.create_held_reservation(
                reservation_id=request.reservation_id,
                event_id=request.event_id,
                seat_id=request.seat_id,
                user_id=request.user_id,
                hold_token=request.hold_token,
                expires_at=request_expires_at,
                now=current_timestamp(),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError("hold_token is already in use") from exc

        return created, True

    def confirm_reservation(
        self,
        reservation_id: str,
        request: ConfirmReservationRequest,
    ) -> dict[str, object]:
        reservation = self._require_reservation(reservation_id)
        if reservation["status"] == "CONFIRMED":
            if self._confirm_request_matches(reservation, request):
                return reservation
            raise ConflictError(
                f"reservation '{reservation_id}' is already confirmed with different payment payload"
            )

        if reservation["status"] != "HELD":
            raise ConflictError(
                f"reservation '{reservation_id}' cannot transition from {reservation['status']} to CONFIRMED"
            )

        try:
            return self._repository.confirm_reservation(
                reservation_id=reservation_id,
                payment_id=request.payment_id,
                amount=request.amount,
                provider=request.provider,
                provider_ref=request.provider_ref,
                now=current_timestamp(),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(
                f"seat '{reservation['seat_id']}' for event '{reservation['event_id']}' is already confirmed"
            ) from exc

    def cancel_reservation(
        self,
        reservation_id: str,
        request: CancelReservationRequest,
    ) -> dict[str, object]:
        reservation = self._require_reservation(reservation_id)
        if reservation["status"] == "CANCELLED":
            return reservation

        if reservation["status"] != "HELD":
            raise ConflictError(
                f"reservation '{reservation_id}' cannot transition from {reservation['status']} to CANCELLED"
            )

        payment_payload = self._validate_cancel_payment_payload(request)
        return self._repository.cancel_reservation(
            reservation_id=reservation_id,
            now=current_timestamp(),
            payment_payload=payment_payload,
        )

    def expire_reservation(self, reservation_id: str) -> dict[str, object]:
        reservation = self._require_reservation(reservation_id)
        if reservation["status"] == "EXPIRED":
            return reservation

        if reservation["status"] != "HELD":
            raise ConflictError(
                f"reservation '{reservation_id}' cannot transition from {reservation['status']} to EXPIRED"
            )

        return self._repository.expire_reservation(
            reservation_id=reservation_id,
            now=current_timestamp(),
        )

    def list_user_reservations(self, user_id: str) -> list[dict[str, object]]:
        self._expire_stale_reservations()
        self._require_user(user_id)
        return self._repository.list_user_reservations(user_id)

    def list_confirmed_seats(self, event_id: str) -> list[dict[str, object]]:
        self._expire_stale_reservations()
        self._require_event(event_id)
        return self._repository.list_confirmed_seats(event_id)

    def _expire_stale_reservations(self) -> None:
        self._repository.expire_stale_reservations(current_timestamp())

    def _require_event(self, event_id: str) -> dict[str, object]:
        event = self._repository.get_event(event_id)
        if event is None:
            raise NotFoundError(f"event '{event_id}' was not found")
        return event

    def _require_user(self, user_id: str) -> dict[str, object]:
        user = self._repository.get_user(user_id)
        if user is None:
            raise NotFoundError(f"user '{user_id}' was not found")
        return user

    def _ensure_user(self, user_id: str) -> dict[str, object]:
        user = self._repository.get_user(user_id)
        if user is not None:
            return user

        if user_id.startswith("load-user-"):
            alias = user_id.removeprefix("load-user-") or "crowd"
            display_name = f"Load User {alias}"
            email = f"{user_id}@demo.local"
            return self._repository.create_user(
                user_id=user_id,
                display_name=display_name,
                email=email,
                created_at=current_timestamp(),
            )

        raise NotFoundError(f"user '{user_id}' was not found")

    def _require_seat(self, event_id: str, seat_id: str) -> dict[str, object]:
        seat = self._repository.get_seat(event_id, seat_id)
        if seat is None:
            raise NotFoundError(
                f"seat '{seat_id}' for event '{event_id}' was not found"
            )
        return seat

    def _require_reservation(self, reservation_id: str) -> dict[str, object]:
        self._expire_stale_reservations()
        reservation = self._repository.get_reservation(reservation_id)
        if reservation is None:
            raise NotFoundError(f"reservation '{reservation_id}' was not found")
        return reservation

    def _held_request_matches(
        self,
        existing: dict[str, object],
        request: HeldReservationCreate,
        expires_at: str,
    ) -> bool:
        return (
            existing["event_id"] == request.event_id
            and existing["seat_id"] == request.seat_id
            and existing["user_id"] == request.user_id
            and existing["hold_token"] == request.hold_token
            and existing["expires_at"] == expires_at
        )

    def _confirm_request_matches(
        self,
        reservation: dict[str, object],
        request: ConfirmReservationRequest,
    ) -> bool:
        return (
            reservation["payment_id"] == request.payment_id
            and reservation["payment_amount"] == request.amount
            and reservation["payment_provider"] == request.provider
            and reservation["payment_provider_ref"] == request.provider_ref
            and reservation["payment_status"] == "SUCCEEDED"
        )

    def _validate_cancel_payment_payload(
        self,
        request: CancelReservationRequest,
    ) -> dict[str, object] | None:
        provided = [
            request.payment_id,
            request.payment_status,
            request.amount,
            request.provider,
            request.provider_ref,
        ]
        if all(value is None for value in provided):
            return None

        if any(value is None for value in provided):
            raise ConflictError(
                "cancel payment payload must include payment_id, payment_status, amount, provider, and provider_ref together"
            )

        return {
            "payment_id": request.payment_id,
            "payment_status": request.payment_status,
            "amount": request.amount,
            "provider": request.provider,
            "provider_ref": request.provider_ref,
        }
