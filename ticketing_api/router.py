"""Route handlers for the ticketing DB API."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from ticketing_api.schemas import (
    CancelReservationRequest,
    ConfirmReservationRequest,
    ConfirmedSeatResponse,
    EventResponse,
    HeldReservationCreate,
    ReservationResponse,
    SeatResponse,
)
from ticketing_api.service import TicketingService

router = APIRouter()


def get_service(request: Request) -> TicketingService:
    return request.app.state.ticketing_service  # type: ignore[return-value]


@router.get("/events", response_model=list[EventResponse])
def list_events(request: Request) -> list[dict[str, object]]:
    return get_service(request).list_events()


@router.get("/events/{event_id}/seats", response_model=list[SeatResponse])
def list_event_seats(event_id: str, request: Request) -> list[dict[str, object]]:
    return get_service(request).list_event_seats(event_id)


@router.get(
    "/events/{event_id}/confirmed-seats",
    response_model=list[ConfirmedSeatResponse],
)
def list_confirmed_seats(
    event_id: str,
    request: Request,
) -> list[dict[str, object]]:
    return get_service(request).list_confirmed_seats(event_id)


@router.post(
    "/reservations/held",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_held_reservation(
    payload: HeldReservationCreate,
    request: Request,
    response: Response,
) -> dict[str, object]:
    reservation, created = get_service(request).create_held_reservation(payload)
    if not created:
        response.status_code = status.HTTP_200_OK
    return reservation


@router.post(
    "/reservations/{reservation_id}/confirm",
    response_model=ReservationResponse,
)
def confirm_reservation(
    reservation_id: str,
    payload: ConfirmReservationRequest,
    request: Request,
) -> dict[str, object]:
    return get_service(request).confirm_reservation(reservation_id, payload)


@router.post(
    "/reservations/{reservation_id}/cancel",
    response_model=ReservationResponse,
)
def cancel_reservation(
    reservation_id: str,
    payload: CancelReservationRequest,
    request: Request,
) -> dict[str, object]:
    return get_service(request).cancel_reservation(reservation_id, payload)


@router.post(
    "/reservations/{reservation_id}/expire",
    response_model=ReservationResponse,
)
def expire_reservation(
    reservation_id: str,
    request: Request,
) -> dict[str, object]:
    return get_service(request).expire_reservation(reservation_id)


@router.get(
    "/users/{user_id}/reservations",
    response_model=list[ReservationResponse],
)
def list_user_reservations(
    user_id: str,
    request: Request,
) -> list[dict[str, object]]:
    return get_service(request).list_user_reservations(user_id)
