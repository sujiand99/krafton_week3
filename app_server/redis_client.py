"""RESP client used by the orchestration API."""

from __future__ import annotations

from dataclasses import dataclass
import socket
from typing import TypeAlias

from app_server.exceptions import ConflictError, UpstreamError

RESP_LINE_ENDING = b"\r\n"
RESPReply: TypeAlias = str | int | None | list["RESPReply"]


class RESPReplyError(ValueError):
    """Raised when a RESP reply is malformed."""


class IncompleteRESPReplyError(RESPReplyError):
    """Raised when more data is required to parse a reply."""


@dataclass(slots=True)
class SeatStatus:
    state: str
    user_id: str | None
    ttl: int


@dataclass(slots=True)
class SeatCommandResult:
    success: bool
    state: str
    user_id: str | None
    ttl: int


@dataclass(slots=True)
class QueueJoinResult:
    joined: bool
    position: int
    queue_length: int


@dataclass(slots=True)
class QueuePositionResult:
    position: int
    queue_length: int


@dataclass(slots=True)
class QueueFrontResult:
    user_id: str | None
    queue_length: int


@dataclass(slots=True)
class QueueLeaveResult:
    removed: bool
    previous_position: int
    queue_length: int


def _read_line(message: bytes | bytearray, start: int) -> tuple[bytes, int]:
    end = message.find(RESP_LINE_ENDING, start)
    if end == -1:
        raise IncompleteRESPReplyError("incomplete RESP reply line")
    return bytes(message[start:end]), end + len(RESP_LINE_ENDING)


def parse_resp_reply(message: bytes | bytearray, start: int = 0) -> tuple[RESPReply, int]:
    if start >= len(message):
        raise IncompleteRESPReplyError("missing RESP reply type")

    prefix = message[start : start + 1]
    if prefix == b"+":
        payload, next_index = _read_line(message, start + 1)
        return payload.decode("utf-8"), next_index

    if prefix == b"-":
        payload, _ = _read_line(message, start + 1)
        raise ConflictError(payload.decode("utf-8"))

    if prefix == b":":
        payload, next_index = _read_line(message, start + 1)
        try:
            return int(payload), next_index
        except ValueError as exc:
            raise RESPReplyError("invalid RESP integer reply") from exc

    if prefix == b"$":
        raw_length, next_index = _read_line(message, start + 1)
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise RESPReplyError("invalid RESP bulk string length") from exc

        if length == -1:
            return None, next_index
        if length < -1:
            raise RESPReplyError("invalid RESP bulk string length")

        data_end = next_index + length
        trailer_end = data_end + len(RESP_LINE_ENDING)
        if trailer_end > len(message):
            raise IncompleteRESPReplyError("incomplete RESP bulk string reply")
        if message[data_end:trailer_end] != RESP_LINE_ENDING:
            raise RESPReplyError("RESP bulk string reply must end with CRLF")

        payload = bytes(message[next_index:data_end])
        return payload.decode("utf-8"), trailer_end

    if prefix == b"*":
        raw_count, next_index = _read_line(message, start + 1)
        try:
            count = int(raw_count)
        except ValueError as exc:
            raise RESPReplyError("invalid RESP array length") from exc
        if count < 0:
            raise RESPReplyError("negative RESP arrays are not supported")

        values: list[RESPReply] = []
        for _ in range(count):
            value, next_index = parse_resp_reply(message, next_index)
            values.append(value)
        return values, next_index

    raise RESPReplyError("unsupported RESP reply type")


class RedisRESPClient:
    """Small RESP socket client for the orchestration API."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 6379,
        timeout: float = 2.0,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout

    def execute(self, *tokens: str) -> RESPReply:
        request = self._encode_command(tokens)

        try:
            with socket.create_connection((self._host, self._port), timeout=self._timeout) as conn:
                conn.sendall(request)
                return self._read_reply(conn)
        except ConflictError:
            raise
        except OSError as exc:
            raise UpstreamError(f"Redis connection failed: {exc}") from exc
        except UnicodeDecodeError as exc:
            raise UpstreamError("Redis returned non-UTF8 data") from exc
        except RESPReplyError as exc:
            raise UpstreamError(f"Invalid Redis reply: {exc}") from exc

    def seat_status(self, event_id: str, seat_id: str) -> SeatStatus:
        values = self._expect_array(self.execute("SEAT_STATUS", event_id, seat_id), 3)
        state = self._expect_string(values[0], "seat state")
        user_id = self._expect_optional_string(values[1], "seat user_id")
        ttl = self._expect_int(values[2], "seat ttl")
        return SeatStatus(state=state, user_id=user_id, ttl=ttl)

    def reserve_seat(
        self,
        event_id: str,
        seat_id: str,
        user_id: str,
        hold_seconds: int,
    ) -> SeatCommandResult:
        values = self._expect_array(
            self.execute("RESERVE_SEAT", event_id, seat_id, user_id, str(hold_seconds)),
            4,
        )
        return self._decode_seat_command(values)

    def confirm_seat(
        self,
        event_id: str,
        seat_id: str,
        user_id: str,
    ) -> SeatCommandResult:
        values = self._expect_array(
            self.execute("CONFIRM_SEAT", event_id, seat_id, user_id),
            4,
        )
        return self._decode_seat_command(values)

    def force_confirm_seat(
        self,
        event_id: str,
        seat_id: str,
        user_id: str,
    ) -> SeatCommandResult:
        values = self._expect_array(
            self.execute("FORCE_CONFIRM_SEAT", event_id, seat_id, user_id),
            4,
        )
        return self._decode_seat_command(values)

    def release_seat(
        self,
        event_id: str,
        seat_id: str,
        user_id: str,
    ) -> SeatCommandResult:
        values = self._expect_array(
            self.execute("RELEASE_SEAT", event_id, seat_id, user_id),
            4,
        )
        return self._decode_seat_command(values)

    def join_queue(self, event_id: str, user_id: str) -> QueueJoinResult:
        values = self._expect_array(self.execute("JOIN_QUEUE", event_id, user_id), 3)
        return QueueJoinResult(
            joined=bool(self._expect_int(values[0], "joined flag")),
            position=self._expect_int(values[1], "queue position"),
            queue_length=self._expect_int(values[2], "queue length"),
        )

    def queue_position(self, event_id: str, user_id: str) -> QueuePositionResult:
        values = self._expect_array(self.execute("QUEUE_POSITION", event_id, user_id), 2)
        return QueuePositionResult(
            position=self._expect_int(values[0], "queue position"),
            queue_length=self._expect_int(values[1], "queue length"),
        )

    def leave_queue(self, event_id: str, user_id: str) -> QueueLeaveResult:
        values = self._expect_array(self.execute("LEAVE_QUEUE", event_id, user_id), 3)
        return QueueLeaveResult(
            removed=bool(self._expect_int(values[0], "removed flag")),
            previous_position=self._expect_int(values[1], "previous position"),
            queue_length=self._expect_int(values[2], "queue length"),
        )

    def peek_queue(self, event_id: str) -> QueueFrontResult:
        values = self._expect_array(self.execute("PEEK_QUEUE", event_id), 2)
        return QueueFrontResult(
            user_id=self._expect_optional_string(values[0], "queue user_id"),
            queue_length=self._expect_int(values[1], "queue length"),
        )

    @staticmethod
    def _encode_command(tokens: tuple[str, ...]) -> bytes:
        parts = [f"*{len(tokens)}\r\n".encode("utf-8")]
        for token in tokens:
            encoded = token.encode("utf-8")
            parts.append(f"${len(encoded)}\r\n".encode("utf-8"))
            parts.append(encoded + RESP_LINE_ENDING)
        return b"".join(parts)

    def _read_reply(self, conn: socket.socket) -> RESPReply:
        buffer = bytearray()
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                raise UpstreamError("Redis closed the connection before replying")

            buffer.extend(chunk)
            try:
                value, consumed = parse_resp_reply(buffer)
            except IncompleteRESPReplyError:
                continue

            if consumed != len(buffer):
                raise UpstreamError("Redis reply contained unexpected trailing data")
            return value

    @staticmethod
    def _expect_array(value: RESPReply, length: int) -> list[RESPReply]:
        if not isinstance(value, list):
            raise UpstreamError("Redis reply must be an array")
        if len(value) != length:
            raise UpstreamError(f"Redis array reply must contain {length} items")
        return value

    @staticmethod
    def _expect_string(value: RESPReply, label: str) -> str:
        if not isinstance(value, str):
            raise UpstreamError(f"Redis {label} must be a string")
        return value

    @staticmethod
    def _expect_optional_string(value: RESPReply, label: str) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise UpstreamError(f"Redis {label} must be a string or null")
        return value

    @staticmethod
    def _expect_int(value: RESPReply, label: str) -> int:
        if not isinstance(value, int):
            raise UpstreamError(f"Redis {label} must be an integer")
        return value

    def _decode_seat_command(self, values: list[RESPReply]) -> SeatCommandResult:
        return SeatCommandResult(
            success=bool(self._expect_int(values[0], "seat success flag")),
            state=self._expect_string(values[1], "seat state"),
            user_id=self._expect_optional_string(values[2], "seat user_id"),
            ttl=self._expect_int(values[3], "seat ttl"),
        )
