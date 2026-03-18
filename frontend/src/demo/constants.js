export const DEMO_EVENT_ID = "concert-seoul-2026";
export const DEMO_USERS = ["user-1", "user-2", "user-3"];
export const DEFAULT_HOLD_SECONDS = Number(
  import.meta.env.VITE_DEFAULT_HOLD_SECONDS ?? 15,
);
export const POLL_INTERVAL_MS = Number(
  import.meta.env.VITE_POLL_INTERVAL_MS ?? 1000,
);
export const SEAT_ROWS = Array.from({ length: 20 }, (_, index) =>
  String.fromCharCode(65 + index),
);
export const SEATS_PER_ROW = 20;

export function createSeatIds() {
  return SEAT_ROWS.flatMap((rowLabel) =>
    Array.from({ length: SEATS_PER_ROW }, (_, index) => `${rowLabel}${index + 1}`),
  );
}

export function createSeatSkeletons() {
  return SEAT_ROWS.flatMap((rowLabel) =>
    Array.from({ length: SEATS_PER_ROW }, (_, index) => {
      const seatNumber = index + 1;
      const seatId = `${rowLabel}${seatNumber}`;
      return {
        eventId: DEMO_EVENT_ID,
        seatId,
        seatLabel: seatId,
        section: "FLOOR",
        rowLabel,
        seatNumber,
        price: 120000,
        status: "available",
        userId: null,
        ttl: null,
        createdAt: new Date().toISOString(),
      };
    }),
  );
}
