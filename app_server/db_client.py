"""HTTP client wrapper for the ticketing DB API."""

from __future__ import annotations

from typing import Any, Protocol

import httpx

from app_server.exceptions import ConflictError, NotFoundError, UpstreamError


class HTTPResponseProtocol(Protocol):
    status_code: int
    text: str

    def json(self) -> Any: ...


class HTTPClientProtocol(Protocol):
    def request(self, method: str, url: str, **kwargs: Any) -> HTTPResponseProtocol: ...

    def close(self) -> None: ...


class TicketingDBClient:
    """Thin client that translates DB HTTP responses into app-server errors."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8001",
        http_client: HTTPClientProtocol | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._owns_client = http_client is None
        self._http_client = http_client or httpx.Client(base_url=base_url, timeout=timeout)

    def close(self) -> None:
        if self._owns_client:
            self._http_client.close()

    def list_events(self) -> list[dict[str, object]]:
        return self._request_json("GET", "/events")

    def list_event_seats(self, event_id: str) -> list[dict[str, object]]:
        return self._request_json("GET", f"/events/{event_id}/seats")

    def create_held_reservation(
        self,
        payload: dict[str, object],
    ) -> tuple[dict[str, object], bool]:
        response = self._request("POST", "/reservations/held", json=payload)
        return response.json(), response.status_code == 201

    def confirm_reservation(
        self,
        reservation_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        return self._request_json(
            "POST",
            f"/reservations/{reservation_id}/confirm",
            json=payload,
        )

    def cancel_reservation(
        self,
        reservation_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        return self._request_json(
            "POST",
            f"/reservations/{reservation_id}/cancel",
            json=payload,
        )

    def expire_reservation(self, reservation_id: str) -> dict[str, object]:
        return self._request_json(
            "POST",
            f"/reservations/{reservation_id}/expire",
        )

    def list_user_reservations(self, user_id: str) -> list[dict[str, object]]:
        return self._request_json("GET", f"/users/{user_id}/reservations")

    def _request_json(self, method: str, url: str, **kwargs: Any) -> Any:
        return self._request(method, url, **kwargs).json()

    def _request(self, method: str, url: str, **kwargs: Any) -> HTTPResponseProtocol:
        try:
            response = self._http_client.request(method, url, **kwargs)
        except Exception as exc:
            raise UpstreamError(f"DB request failed: {exc}") from exc

        if response.status_code in {200, 201}:
            return response

        detail = self._extract_detail(response)
        if response.status_code == 404:
            raise NotFoundError(detail)
        if response.status_code == 409:
            raise ConflictError(detail)
        raise UpstreamError(f"DB request failed with status {response.status_code}: {detail}")

    @staticmethod
    def _extract_detail(response: HTTPResponseProtocol) -> str:
        try:
            payload = response.json()
        except Exception:
            return response.text.strip() or "unknown DB error"

        if isinstance(payload, dict) and isinstance(payload.get("detail"), str):
            return payload["detail"]
        return response.text.strip() or "unknown DB error"
