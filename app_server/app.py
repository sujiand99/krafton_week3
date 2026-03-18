"""FastAPI app that exposes a single ticketing API to the frontend."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse

from app_server.db_client import TicketingDBClient
from app_server.exceptions import ConflictError, NotFoundError, UpstreamError
from app_server.orchestration_log import OrchestrationLogStore
from app_server.redis_client import RedisRESPClient
from app_server.schemas import (
    CancelReservationRequest,
    CancelReservationResponse,
    ConfirmReservationRequest,
    ConfirmReservationResponse,
    EventResponse,
    HoldReservationRequest,
    HoldReservationResponse,
    OrchestrationLogEntryResponse,
    PurchaseReservationRequest,
    PurchaseReservationResponse,
    QueueFrontResponse,
    QueueJoinRequest,
    QueueJoinResponse,
    QueueLeaveRequest,
    QueueLeaveResponse,
    QueuePositionResponse,
    ReservationResponse,
    SeatViewResponse,
)
from app_server.service import TicketingOrchestratorService


def create_app(
    redis_client: RedisRESPClient | None = None,
    db_client: TicketingDBClient | None = None,
    redis_host: str = "127.0.0.1",
    redis_port: int = 6379,
    db_base_url: str = "http://127.0.0.1:8001",
) -> FastAPI:
    owns_db_client = db_client is None
    owns_redis_client = redis_client is None

    redis_gateway = redis_client or RedisRESPClient(host=redis_host, port=redis_port)
    db_gateway = db_client or TicketingDBClient(base_url=db_base_url)
    orchestration_log = OrchestrationLogStore()
    service = TicketingOrchestratorService(
        redis_gateway,
        db_gateway,
        orchestration_log=orchestration_log,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.ticketing_service = service
        try:
            yield
        finally:
            if owns_redis_client:
                redis_gateway.close()
            if owns_db_client:
                db_gateway.close()

    app = FastAPI(title="Ticketing App Server", lifespan=lifespan)

    @app.exception_handler(NotFoundError)
    async def handle_not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ConflictError)
    async def handle_conflict(_: Request, exc: ConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(UpstreamError)
    async def handle_upstream(_: Request, exc: UpstreamError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    def get_service(request: Request) -> TicketingOrchestratorService:
        return request.app.state.ticketing_service  # type: ignore[return-value]

    @app.get("/events", response_model=list[EventResponse])
    def list_events(request: Request) -> list[dict[str, object]]:
        return get_service(request).list_events()

    @app.get("/events/{event_id}/seats", response_model=list[SeatViewResponse])
    def list_event_seats(event_id: str, request: Request) -> list[dict[str, object]]:
        return get_service(request).list_event_seats(event_id)

    @app.get("/events/{event_id}/seats/{seat_id}", response_model=SeatViewResponse)
    def get_event_seat(event_id: str, seat_id: str, request: Request) -> dict[str, object]:
        return get_service(request).get_event_seat(event_id, seat_id)

    @app.get(
        "/users/{user_id}/reservations",
        response_model=list[ReservationResponse],
    )
    def list_user_reservations(user_id: str, request: Request) -> list[dict[str, object]]:
        return get_service(request).list_user_reservations(user_id)

    @app.get(
        "/orchestration/logs",
        response_model=list[OrchestrationLogEntryResponse],
    )
    def list_orchestration_logs(
        request: Request,
        limit: int = 40,
    ) -> list[dict[str, object]]:
        bounded_limit = max(1, min(limit, 120))
        return get_service(request).list_orchestration_logs(bounded_limit)

    @app.delete(
        "/orchestration/logs",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def clear_orchestration_logs(request: Request) -> Response:
        get_service(request).clear_orchestration_logs()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/queue/join", response_model=QueueJoinResponse, status_code=status.HTTP_201_CREATED)
    def join_queue(payload: QueueJoinRequest, request: Request) -> dict[str, object]:
        return get_service(request).join_queue(payload.event_id, payload.user_id)

    @app.get(
        "/queue/{event_id}/users/{user_id}/position",
        response_model=QueuePositionResponse,
    )
    def queue_position(event_id: str, user_id: str, request: Request) -> dict[str, object]:
        return get_service(request).queue_position(event_id, user_id)

    @app.post("/queue/leave", response_model=QueueLeaveResponse)
    def leave_queue(payload: QueueLeaveRequest, request: Request) -> dict[str, object]:
        return get_service(request).leave_queue(payload.event_id, payload.user_id)

    @app.get("/queue/{event_id}/peek", response_model=QueueFrontResponse)
    def peek_queue(event_id: str, request: Request) -> dict[str, object]:
        return get_service(request).peek_queue(event_id)

    @app.post(
        "/reservations/hold",
        response_model=HoldReservationResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def hold_reservation(
        payload: HoldReservationRequest,
        request: Request,
        response: Response,
    ) -> dict[str, object]:
        result, created = get_service(request).hold_reservation(
            payload.event_id,
            payload.seat_id,
            payload.user_id,
            payload.hold_seconds,
        )
        if not created:
            response.status_code = status.HTTP_200_OK
        return result

    @app.post(
        "/reservations/{reservation_id}/confirm",
        response_model=ConfirmReservationResponse,
    )
    def confirm_reservation(
        reservation_id: str,
        payload: ConfirmReservationRequest,
        request: Request,
    ) -> dict[str, object]:
        return get_service(request).confirm_reservation(
            reservation_id,
            payload.event_id,
            payload.seat_id,
            payload.user_id,
        )

    @app.post(
        "/reservations/{reservation_id}/cancel",
        response_model=CancelReservationResponse,
    )
    def cancel_reservation(
        reservation_id: str,
        payload: CancelReservationRequest,
        request: Request,
    ) -> dict[str, object]:
        return get_service(request).cancel_reservation(
            reservation_id,
            payload.event_id,
            payload.seat_id,
            payload.user_id,
        )

    @app.post(
        "/reservations/purchase",
        response_model=PurchaseReservationResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def purchase_reservation(
        payload: PurchaseReservationRequest,
        request: Request,
    ) -> dict[str, object]:
        return get_service(request).purchase_seat(
            payload.event_id,
            payload.seat_id,
            payload.user_id,
            payload.hold_seconds,
        )

    return app


app = create_app()
