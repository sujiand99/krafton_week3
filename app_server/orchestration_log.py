"""In-memory orchestration log for app-server Redis/DB flow visibility."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from threading import Lock


@dataclass(slots=True)
class OrchestrationLogEntry:
    timestamp: str
    source: str
    target: str
    action: str
    status: str
    event_id: str | None = None
    seat_id: str | None = None
    user_id: str | None = None
    detail: str | None = None


class OrchestrationLogStore:
    """Thread-safe ring buffer used for the demo flow panel."""

    def __init__(self, limit: int = 200) -> None:
        self._entries: deque[OrchestrationLogEntry] = deque(maxlen=limit)
        self._lock = Lock()

    def record(
        self,
        *,
        source: str,
        target: str,
        action: str,
        status: str,
        event_id: str | None = None,
        seat_id: str | None = None,
        user_id: str | None = None,
        detail: str | None = None,
    ) -> None:
        entry = OrchestrationLogEntry(
            timestamp=datetime.now(UTC).isoformat(),
            source=source,
            target=target,
            action=action,
            status=status,
            event_id=event_id,
            seat_id=seat_id,
            user_id=user_id,
            detail=detail,
        )
        with self._lock:
            self._entries.appendleft(entry)

    def list_entries(self, limit: int = 40) -> list[dict[str, object]]:
        with self._lock:
            return [asdict(entry) for entry in list(self._entries)[:limit]]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
