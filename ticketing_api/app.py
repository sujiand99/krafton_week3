"""FastAPI application for ticketing DB service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ticketing_api.database import DEFAULT_DB_PATH, SQLiteDatabase
from ticketing_api.repository import TicketingRepository
from ticketing_api.router import router
from ticketing_api.service import ConflictError, NotFoundError, TicketingService


def create_app(db_path: str | Path = DEFAULT_DB_PATH) -> FastAPI:
    database = SQLiteDatabase(db_path)
    repository = TicketingRepository(database)
    service = TicketingService(repository)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        service.initialize()
        app.state.ticketing_service = service
        yield

    app = FastAPI(title="Ticketing DB Service", lifespan=lifespan)

    @app.exception_handler(NotFoundError)
    async def handle_not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ConflictError)
    async def handle_conflict(_: Request, exc: ConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    app.include_router(router)
    return app


app = create_app()
