import {
  DEFAULT_HOLD_SECONDS,
  DEMO_EVENT_ID,
  DEMO_USERS,
  createSeatSkeletons,
} from "../demo/constants";

const MOCK_MIN_DELAY_MS = 100;
const MOCK_MAX_DELAY_MS = 260;

let demoState = createInitialState();

function createId(prefix) {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `${prefix}-${crypto.randomUUID()}`;
  }

  return `${prefix}-${Math.random().toString(16).slice(2)}-${Date.now()}`;
}

function createInitialState() {
  return {
    seats: createSeatSkeletons().map((seat) => ({
      ...seat,
      expiresAt: null,
      reservationId: null,
    })),
    queue: [],
    reservations: [],
    orchestrationLogs: [],
  };
}

function randomDelay() {
  const gap = MOCK_MAX_DELAY_MS - MOCK_MIN_DELAY_MS;
  return MOCK_MIN_DELAY_MS + Math.floor(Math.random() * gap);
}

function waitForDelay() {
  return new Promise((resolve) => {
    window.setTimeout(resolve, randomDelay());
  });
}

function ensureEvent(eventId) {
  if (eventId !== DEMO_EVENT_ID) {
    throw new Error(`unsupported event: ${eventId}`);
  }
}

function isSupportedUser(userId) {
  return DEMO_USERS.includes(userId) || userId.startsWith("load-user-");
}

function syncExpirations() {
  const now = Date.now();

  demoState.seats.forEach((seat) => {
    if (seat.status !== "held" || seat.expiresAt === null) {
      return;
    }

    const ttl = Math.ceil((seat.expiresAt - now) / 1000);
    if (ttl <= 0) {
      expireSeatHold(seat);
      return;
    }

    seat.ttl = ttl;
  });
}

function expireSeatHold(seat) {
  const reservation = demoState.reservations.find(
    (item) =>
      item.eventId === seat.eventId &&
      item.seatId === seat.seatId &&
      item.userId === seat.userId &&
      item.status === "HELD",
  );

  if (reservation) {
    reservation.status = "EXPIRED";
    reservation.updatedAt = new Date().toISOString();
  }

  seat.status = "available";
  seat.userId = null;
  seat.ttl = null;
  seat.expiresAt = null;
  seat.reservationId = null;
}

function findSeatOrThrow(eventId, seatId) {
  const seat = demoState.seats.find(
    (item) => item.eventId === eventId && item.seatId === seatId,
  );

  if (!seat) {
    throw new Error(`seat not found: ${seatId}`);
  }

  return seat;
}

function cloneSeat(seat) {
  syncExpirations();
  return {
    eventId: seat.eventId,
    seatId: seat.seatId,
    seatLabel: seat.seatLabel,
    section: seat.section,
    rowLabel: seat.rowLabel,
    seatNumber: seat.seatNumber,
    price: seat.price,
    status: seat.status,
    userId: seat.userId,
    ttl: seat.status === "held" ? seat.ttl : null,
    createdAt: seat.createdAt,
  };
}

function cloneReservation(reservation) {
  return {
    reservationId: reservation.reservationId,
    eventId: reservation.eventId,
    seatId: reservation.seatId,
    userId: reservation.userId,
    status: reservation.status,
    holdToken: reservation.holdToken,
    expiresAt: reservation.expiresAt,
    createdAt: reservation.createdAt,
    updatedAt: reservation.updatedAt,
  };
}

function getHeldReservation(eventId, seatId, userId) {
  return demoState.reservations.find(
    (item) =>
      item.eventId === eventId &&
      item.seatId === seatId &&
      item.userId === userId &&
      item.status === "HELD",
  );
}

function getNowIso() {
  return new Date().toISOString();
}

function recordOrchestrationLog({
  source,
  target,
  action,
  status,
  eventId = null,
  seatId = null,
  userId = null,
  detail = null,
}) {
  demoState.orchestrationLogs.unshift({
    timestamp: getNowIso(),
    source,
    target,
    action,
    status,
    eventId,
    seatId,
    userId,
    detail,
  });
  demoState.orchestrationLogs = demoState.orchestrationLogs.slice(0, 80);
}

function createReservation(eventId, seatId, userId, holdSeconds) {
  const now = getNowIso();
  const expiresAt = new Date(Date.now() + holdSeconds * 1000).toISOString();

  const reservation = {
    reservationId: createId("mock-res"),
    eventId,
    seatId,
    userId,
    status: "HELD",
    holdToken: createId("mock-hold"),
    expiresAt,
    createdAt: now,
    updatedAt: now,
  };

  demoState.reservations.unshift(reservation);
  return reservation;
}

export async function resetDemo(eventId = DEMO_EVENT_ID) {
  ensureEvent(eventId);
  demoState = createInitialState();
  await waitForDelay();
  return fetchSeats(eventId);
}

export async function fetchSeats(eventId) {
  ensureEvent(eventId);
  await waitForDelay();
  syncExpirations();
  return demoState.seats.map(cloneSeat);
}

export async function fetchConfirmedSeats(eventId) {
  ensureEvent(eventId);
  await waitForDelay();
  syncExpirations();
  return demoState.seats
    .filter((seat) => seat.status === "confirmed")
    .map(cloneSeat);
}

export async function fetchOrchestrationLogs(limit = 40) {
  await waitForDelay();
  return demoState.orchestrationLogs.slice(0, limit);
}

export async function clearOrchestrationLogs() {
  await waitForDelay();
  demoState.orchestrationLogs = [];
  return null;
}

export async function seatStatus(eventId, seatId) {
  ensureEvent(eventId);
  await waitForDelay();
  syncExpirations();
  return cloneSeat(findSeatOrThrow(eventId, seatId));
}

export async function reserveSeat(
  eventId,
  seatId,
  userId,
  ttlSeconds = DEFAULT_HOLD_SECONDS,
) {
  ensureEvent(eventId);
  await waitForDelay();
  syncExpirations();

  if (!isSupportedUser(userId)) {
    throw new Error(`unknown user: ${userId}`);
  }

  const seat = findSeatOrThrow(eventId, seatId);
  const holdSeconds = Number(ttlSeconds || DEFAULT_HOLD_SECONDS);
  recordOrchestrationLog({
    source: "APP",
    target: "REDIS",
    action: "RESERVE_SEAT",
    status: "START",
    eventId,
    seatId,
    userId,
  });

  if (seat.status === "confirmed") {
    recordOrchestrationLog({
      source: "APP",
      target: "REDIS",
      action: "RESERVE_SEAT",
      status: "FAIL",
      eventId,
      seatId,
      userId,
      detail: `${seatId} is already confirmed`,
    });
    throw new Error(`${seatId} is already confirmed`);
  }

  if (seat.status === "held" && seat.userId !== userId) {
    recordOrchestrationLog({
      source: "APP",
      target: "REDIS",
      action: "RESERVE_SEAT",
      status: "FAIL",
      eventId,
      seatId,
      userId,
      detail: `${seatId} is already held by ${seat.userId}`,
    });
    throw new Error(`${seatId} is already held by ${seat.userId}`);
  }

  let reservation = getHeldReservation(eventId, seatId, userId);
  if (!reservation) {
    reservation = createReservation(eventId, seatId, userId, holdSeconds);
  } else {
    reservation.expiresAt = new Date(
      Date.now() + holdSeconds * 1000,
    ).toISOString();
    reservation.updatedAt = getNowIso();
  }

  seat.status = "held";
  seat.userId = userId;
  seat.expiresAt = Date.now() + holdSeconds * 1000;
  seat.ttl = holdSeconds;
  seat.reservationId = reservation.reservationId;
  recordOrchestrationLog({
    source: "APP",
    target: "REDIS",
    action: "RESERVE_SEAT",
    status: "SUCCESS",
    eventId,
    seatId,
    userId,
    detail: `ttl=${holdSeconds}`,
  });
  recordOrchestrationLog({
    source: "APP",
    target: "DB",
    action: "CREATE_HELD",
    status: "SUCCESS",
    eventId,
    seatId,
    userId,
    detail: reservation.reservationId,
  });

  return {
    success: true,
    seat: cloneSeat(seat),
    reservation: cloneReservation(reservation),
    created: true,
  };
}

export async function confirmSeat(eventId, seatId, userId) {
  ensureEvent(eventId);
  await waitForDelay();
  syncExpirations();

  const seat = findSeatOrThrow(eventId, seatId);
  recordOrchestrationLog({
    source: "APP",
    target: "REDIS",
    action: "SEAT_STATUS",
    status: "SUCCESS",
    eventId,
    seatId,
    userId,
    detail: `state=${seat.status.toUpperCase()}`,
  });
  if (seat.status === "confirmed" && seat.userId === userId) {
    return { success: true, seat: cloneSeat(seat) };
  }

  if (seat.status !== "held" || seat.userId !== userId) {
    recordOrchestrationLog({
      source: "APP",
      target: "REDIS",
      action: "SEAT_STATUS",
      status: "FAIL",
      eventId,
      seatId,
      userId,
      detail: `${seatId} cannot be confirmed by ${userId}`,
    });
    throw new Error(`${seatId} cannot be confirmed by ${userId}`);
  }

  const reservation = getHeldReservation(eventId, seatId, userId);
  if (reservation) {
    reservation.status = "CONFIRMED";
    reservation.updatedAt = getNowIso();
  }
  recordOrchestrationLog({
    source: "APP",
    target: "PAYMENT",
    action: "MOCK_APPROVE",
    status: "SUCCESS",
    eventId,
    seatId,
    userId,
  });
  recordOrchestrationLog({
    source: "APP",
    target: "DB",
    action: "CONFIRM_RESERVATION",
    status: "SUCCESS",
    eventId,
    seatId,
    userId,
    detail: reservation?.reservationId ?? null,
  });

  seat.status = "confirmed";
  seat.ttl = null;
  seat.expiresAt = null;
  recordOrchestrationLog({
    source: "APP",
    target: "REDIS",
    action: "FORCE_CONFIRM_SEAT",
    status: "SUCCESS",
    eventId,
    seatId,
    userId,
  });

  return {
    success: true,
    seat: cloneSeat(seat),
    reservation: reservation ? cloneReservation(reservation) : null,
    payment: {
      paymentId: createId("mock-pay"),
      status: "SUCCEEDED",
      amount: seat.price,
      provider: "mock-pay",
      providerRef: createId("mock-pay-ref"),
    },
  };
}

export async function releaseSeat(eventId, seatId, userId) {
  ensureEvent(eventId);
  await waitForDelay();
  syncExpirations();

  const seat = findSeatOrThrow(eventId, seatId);
  recordOrchestrationLog({
    source: "APP",
    target: "DB",
    action: "CANCEL_RESERVATION",
    status: "START",
    eventId,
    seatId,
    userId,
  });
  if (seat.status !== "held" || seat.userId !== userId) {
    recordOrchestrationLog({
      source: "APP",
      target: "REDIS",
      action: "RELEASE_SEAT",
      status: "FAIL",
      eventId,
      seatId,
      userId,
      detail: `${seatId} cannot be released by ${userId}`,
    });
    throw new Error(`${seatId} cannot be released by ${userId}`);
  }

  const reservation = getHeldReservation(eventId, seatId, userId);
  if (reservation) {
    reservation.status = "CANCELLED";
    reservation.updatedAt = getNowIso();
  }
  recordOrchestrationLog({
    source: "APP",
    target: "DB",
    action: "CANCEL_RESERVATION",
    status: "SUCCESS",
    eventId,
    seatId,
    userId,
    detail: reservation?.reservationId ?? null,
  });

  seat.status = "available";
  seat.userId = null;
  seat.ttl = null;
  seat.expiresAt = null;
  seat.reservationId = null;
  recordOrchestrationLog({
    source: "APP",
    target: "REDIS",
    action: "RELEASE_SEAT",
    status: "SUCCESS",
    eventId,
    seatId,
    userId,
  });

  return {
    success: true,
    seat: cloneSeat(seat),
    reservation: reservation ? cloneReservation(reservation) : null,
  };
}

export async function joinQueue(eventId, userId) {
  ensureEvent(eventId);
  await waitForDelay();

  if (!isSupportedUser(userId)) {
    throw new Error(`unknown user: ${userId}`);
  }

  const alreadyJoined = demoState.queue.includes(userId);
  if (!alreadyJoined) {
    demoState.queue.push(userId);
  }

  return {
    joined: !alreadyJoined,
    position: demoState.queue.indexOf(userId) + 1,
    queueLength: demoState.queue.length,
    queue: [...demoState.queue],
  };
}

export async function queuePosition(eventId, userId) {
  ensureEvent(eventId);
  await waitForDelay();

  const position = demoState.queue.indexOf(userId);
  return {
    position: position === -1 ? -1 : position + 1,
    queueLength: demoState.queue.length,
  };
}

export async function popQueue(eventId) {
  ensureEvent(eventId);
  await waitForDelay();

  const userId = demoState.queue.shift() ?? null;
  return {
    userId,
    queueLength: demoState.queue.length,
    queue: [...demoState.queue],
  };
}

export async function leaveQueue(eventId, userId) {
  ensureEvent(eventId);
  await waitForDelay();

  const previousPosition = demoState.queue.indexOf(userId);
  if (previousPosition >= 0) {
    demoState.queue.splice(previousPosition, 1);
  }

  return {
    removed: previousPosition >= 0,
    previousPosition: previousPosition >= 0 ? previousPosition + 1 : -1,
    queueLength: demoState.queue.length,
    queue: [...demoState.queue],
  };
}

export async function peekQueue(eventId) {
  ensureEvent(eventId);
  await waitForDelay();

  return {
    userId: demoState.queue[0] ?? null,
    queueLength: demoState.queue.length,
  };
}
