import {
  DEFAULT_HOLD_SECONDS,
  DEMO_EVENT_ID,
  DEMO_USERS,
  createSeatIds,
} from "../demo/constants";
import * as mockApi from "./mockApi";

export const apiMode =
  (import.meta.env.VITE_API_MODE ?? "mock").toLowerCase() === "real"
    ? "real"
    : "mock";

export const apiCapabilities = {
  supportsPopQueue: apiMode === "mock",
  supportsResetDemo: apiMode === "mock",
};

const APP_SERVER_BASE_URL = import.meta.env.VITE_APP_SERVER_BASE_URL ?? "/api";
const DB_API_BASE_URL = import.meta.env.VITE_DB_API_BASE_URL ?? "/db-api";

function normalizeSeat(rawSeat) {
  const derivedSeatId = rawSeat.seatId ?? rawSeat.seat_id ?? "A1";
  const derivedSeatNumber = Number.parseInt(String(derivedSeatId).slice(1), 10);

  return {
    eventId: rawSeat.eventId ?? rawSeat.event_id ?? DEMO_EVENT_ID,
    seatId: derivedSeatId,
    seatLabel: rawSeat.seatLabel ?? rawSeat.seat_label ?? derivedSeatId,
    section: rawSeat.section ?? "FLOOR",
    rowLabel: rawSeat.rowLabel ?? rawSeat.row_label ?? derivedSeatId[0] ?? "A",
    seatNumber:
      rawSeat.seatNumber ??
      rawSeat.seat_number ??
      (Number.isNaN(derivedSeatNumber) ? 0 : derivedSeatNumber),
    price: rawSeat.price ?? 120000,
    status: String(rawSeat.status ?? "AVAILABLE").toLowerCase(),
    userId: rawSeat.userId ?? rawSeat.user_id ?? rawSeat.held_by_user_id ?? null,
    ttl: rawSeat.ttl ?? rawSeat.hold_ttl ?? null,
    createdAt: rawSeat.createdAt ?? rawSeat.created_at ?? new Date().toISOString(),
  };
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers ?? {}),
    },
    ...options,
  });

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;

    try {
      const payload = await response.json();
      if (payload?.detail) {
        detail = payload.detail;
      }
    } catch {
      const fallbackText = await response.text();
      if (fallbackText) {
        detail = fallbackText;
      }
    }

    throw new Error(detail);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

async function fetchHeldReservation(eventId, seatId, userId) {
  // TODO: replace this lookup when backend exposes a direct held-reservation query endpoint.
  const reservations = await requestJson(
    `${APP_SERVER_BASE_URL}/users/${encodeURIComponent(userId)}/reservations`,
  );

  const match = reservations.find(
    (item) =>
      item.event_id === eventId &&
      item.seat_id === seatId &&
      item.status === "HELD",
  );

  if (!match) {
    throw new Error(`no HELD reservation for ${userId} on ${seatId}`);
  }

  return match;
}

async function reserveSeatReal(eventId, seatId, userId, ttlSeconds) {
  // TODO: update payload here if the hold endpoint contract changes.
  const payload = await requestJson(`${APP_SERVER_BASE_URL}/reservations/hold`, {
    method: "POST",
    body: JSON.stringify({
      event_id: eventId,
      seat_id: seatId,
      user_id: userId,
      hold_seconds: ttlSeconds || DEFAULT_HOLD_SECONDS,
    }),
  });

  return {
    success: true,
    seat: normalizeSeat(payload.seat),
    reservationId: payload.reservation?.reservation_id ?? null,
    created: payload.created ?? true,
  };
}

async function confirmSeatReal(eventId, seatId, userId) {
  const reservation = await fetchHeldReservation(eventId, seatId, userId);

  // TODO: update this body if confirm starts requiring explicit payment fields.
  const payload = await requestJson(
    `${APP_SERVER_BASE_URL}/reservations/${reservation.reservation_id}/confirm`,
    {
      method: "POST",
      body: JSON.stringify({
        event_id: eventId,
        seat_id: seatId,
        user_id: userId,
      }),
    },
  );

  return {
    success: true,
    seat: normalizeSeat(payload.seat),
    reservationId:
      payload.reservation?.reservation_id ?? reservation.reservation_id,
    payment: payload.payment ?? null,
  };
}

async function releaseSeatReal(eventId, seatId, userId) {
  const reservation = await fetchHeldReservation(eventId, seatId, userId);

  // TODO: switch to a dedicated release endpoint when backend adds one.
  const payload = await requestJson(
    `${APP_SERVER_BASE_URL}/reservations/${reservation.reservation_id}/cancel`,
    {
      method: "POST",
      body: JSON.stringify({
        event_id: eventId,
        seat_id: seatId,
        user_id: userId,
      }),
    },
  );

  return {
    success: true,
    seat: normalizeSeat(payload.seat),
    reservationId:
      payload.reservation?.reservation_id ?? reservation.reservation_id,
  };
}

async function seatStatusReal(eventId, seatId) {
  const payload = await requestJson(
    `${APP_SERVER_BASE_URL}/events/${eventId}/seats/${seatId}`,
  );
  return normalizeSeat(payload);
}

async function joinQueueReal(eventId, userId) {
  const payload = await requestJson(`${APP_SERVER_BASE_URL}/queue/join`, {
    method: "POST",
    body: JSON.stringify({
      event_id: eventId,
      user_id: userId,
    }),
  });

  return {
    joined: payload.joined,
    position: payload.position,
    queueLength: payload.queue_length,
  };
}

async function queuePositionReal(eventId, userId) {
  const payload = await requestJson(
    `${APP_SERVER_BASE_URL}/queue/${eventId}/users/${userId}/position`,
  );

  return {
    position: payload.position,
    queueLength: payload.queue_length,
  };
}

async function popQueueReal() {
  // TODO: wire this once app_server exposes a POP_QUEUE HTTP endpoint.
  throw new Error("real API mode does not expose POP_QUEUE yet");
}

async function leaveQueueReal(eventId, userId) {
  const payload = await requestJson(`${APP_SERVER_BASE_URL}/queue/leave`, {
    method: "POST",
    body: JSON.stringify({
      event_id: eventId,
      user_id: userId,
    }),
  });

  return {
    removed: payload.removed,
    previousPosition: payload.previous_position,
    queueLength: payload.queue_length,
  };
}

async function peekQueueReal(eventId) {
  const payload = await requestJson(
    `${APP_SERVER_BASE_URL}/queue/${eventId}/peek`,
  );

  return {
    userId: payload.user_id,
    queueLength: payload.queue_length,
  };
}

async function fetchSeatsReal(eventId) {
  const payload = await requestJson(`${APP_SERVER_BASE_URL}/events/${eventId}/seats`);
  return payload.map(normalizeSeat);
}

async function fetchConfirmedSeatsReal(eventId) {
  // TODO: move this behind app_server when confirmed-seat lookup is unified there.
  const payload = await requestJson(
    `${DB_API_BASE_URL}/events/${eventId}/confirmed-seats`,
  );

  return payload.map((item) =>
    normalizeSeat({
      event_id: item.event_id,
      seat_id: item.seat_id,
      status: "CONFIRMED",
      user_id: item.user_id,
    }),
  );
}

async function fetchOrchestrationLogsReal(limit = 40) {
  return requestJson(
    `${APP_SERVER_BASE_URL}/orchestration/logs?limit=${encodeURIComponent(limit)}`,
  );
}

async function clearOrchestrationLogsReal() {
  return requestJson(`${APP_SERVER_BASE_URL}/orchestration/logs`, {
    method: "DELETE",
  });
}

export async function resetDemo(eventId = DEMO_EVENT_ID) {
  if (apiMode === "mock") {
    return mockApi.resetDemo(eventId);
  }

  return Promise.resolve(null);
}

export async function reserveSeat(
  eventId,
  seatId,
  userId,
  ttlSeconds = DEFAULT_HOLD_SECONDS,
) {
  return apiMode === "mock"
    ? mockApi.reserveSeat(eventId, seatId, userId, ttlSeconds)
    : reserveSeatReal(eventId, seatId, userId, ttlSeconds);
}

export async function confirmSeat(eventId, seatId, userId) {
  return apiMode === "mock"
    ? mockApi.confirmSeat(eventId, seatId, userId)
    : confirmSeatReal(eventId, seatId, userId);
}

export async function releaseSeat(eventId, seatId, userId) {
  return apiMode === "mock"
    ? mockApi.releaseSeat(eventId, seatId, userId)
    : releaseSeatReal(eventId, seatId, userId);
}

export async function seatStatus(eventId, seatId) {
  return apiMode === "mock"
    ? mockApi.seatStatus(eventId, seatId)
    : seatStatusReal(eventId, seatId);
}

export async function joinQueue(eventId, userId) {
  return apiMode === "mock"
    ? mockApi.joinQueue(eventId, userId)
    : joinQueueReal(eventId, userId);
}

export async function queuePosition(eventId, userId) {
  return apiMode === "mock"
    ? mockApi.queuePosition(eventId, userId)
    : queuePositionReal(eventId, userId);
}

export async function popQueue(eventId) {
  return apiMode === "mock" ? mockApi.popQueue(eventId) : popQueueReal(eventId);
}

export async function leaveQueue(eventId, userId) {
  return apiMode === "mock"
    ? mockApi.leaveQueue(eventId, userId)
    : leaveQueueReal(eventId, userId);
}

export async function peekQueue(eventId) {
  return apiMode === "mock"
    ? mockApi.peekQueue(eventId)
    : peekQueueReal(eventId);
}

export async function fetchSeats(eventId) {
  return apiMode === "mock"
    ? mockApi.fetchSeats(eventId)
    : fetchSeatsReal(eventId);
}

export async function fetchConfirmedSeats(eventId) {
  return apiMode === "mock"
    ? mockApi.fetchConfirmedSeats(eventId)
    : fetchConfirmedSeatsReal(eventId);
}

export async function fetchOrchestrationLogs(limit = 40) {
  return apiMode === "mock"
    ? mockApi.fetchOrchestrationLogs(limit)
    : fetchOrchestrationLogsReal(limit);
}

export async function clearOrchestrationLogs() {
  return apiMode === "mock"
    ? mockApi.clearOrchestrationLogs()
    : clearOrchestrationLogsReal();
}

export async function fetchQueueSnapshot(eventId) {
  const [peek, ...positions] = await Promise.all([
    peekQueue(eventId),
    ...DEMO_USERS.map(async (userId) => ({
      userId,
      ...(await queuePosition(eventId, userId)),
    })),
  ]);

  return {
    frontUserId: peek.userId,
    queueLength: peek.queueLength,
    queue: positions
      .filter((item) => item.position > 0)
      .sort((left, right) => left.position - right.position),
  };
}

export function getSeatIdPool() {
  return createSeatIds();
}
