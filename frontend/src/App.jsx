import { useEffect, useRef, useState } from "react";
import LogPanel from "./components/LogPanel";
import QueuePanel from "./components/QueuePanel";
import SeatGrid from "./components/SeatGrid";
import UserPanel from "./components/UserPanel";
import {
  apiCapabilities,
  apiMode,
  confirmSeat,
  fetchConfirmedSeats,
  fetchQueueSnapshot,
  fetchSeats,
  getSeatIdPool,
  joinQueue,
  leaveQueue,
  peekQueue,
  popQueue,
  releaseSeat,
  reserveSeat,
  resetDemo,
} from "./services/api";
import {
  DEFAULT_HOLD_SECONDS,
  DEMO_EVENT_ID,
  DEMO_USERS,
  POLL_INTERVAL_MS,
  createSeatSkeletons,
} from "./demo/constants";

function formatTimestamp(date = new Date()) {
  return date.toLocaleTimeString("ko-KR", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function createLogEntry(message, kind = "info") {
  return {
    id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    kind,
    message: `[${formatTimestamp()}] ${message}`,
  };
}

function randomFrom(list) {
  return list[Math.floor(Math.random() * list.length)];
}

function countSeatStates(seats) {
  return seats.reduce(
    (summary, seat) => {
      summary[seat.status] += 1;
      return summary;
    },
    { available: 0, held: 0, confirmed: 0 },
  );
}

const PAGE_TITLE = "Redis \uAE30\uBC18 \uC2E4\uC2DC\uAC04 \uC88C\uC11D \uC120\uC810 \uB370\uBAA8";
const PAGE_DESCRIPTION =
  "Seat holds, TTL expiry, duplicate hold failures, queue flow, and live logs on one screen.";

export default function App() {
  const [selectedUser, setSelectedUser] = useState(DEMO_USERS[0]);
  const [seats, setSeats] = useState(createSeatSkeletons());
  const [queueEntries, setQueueEntries] = useState([]);
  const [queueFrontUserId, setQueueFrontUserId] = useState(null);
  const [logs, setLogs] = useState([
    createLogEntry(`frontend ready (${apiMode.toUpperCase()} mode)`),
  ]);
  const [bookingStarted, setBookingStarted] = useState(false);
  const [busySeatId, setBusySeatId] = useState("");
  const [queueBusy, setQueueBusy] = useState(false);
  const [userActionBusy, setUserActionBusy] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isSimulating, setIsSimulating] = useState(false);
  const [lastRefreshAt, setLastRefreshAt] = useState(null);
  const [confirmedSeats, setConfirmedSeats] = useState([]);

  const previousSeatsRef = useRef([]);
  const simulationTimeoutsRef = useRef([]);

  function pushLogs(nextEntries) {
    setLogs((currentLogs) => [...nextEntries, ...currentLogs].slice(0, 120));
  }

  function addLog(message, kind = "info") {
    pushLogs([createLogEntry(message, kind)]);
  }

  function clearSimulationTimeouts() {
    simulationTimeoutsRef.current.forEach((timeoutId) => {
      window.clearTimeout(timeoutId);
    });
    simulationTimeoutsRef.current = [];
  }

  function detectSeatExpiryLogs(previousSeats, nextSeats) {
    if (!previousSeats.length) {
      return;
    }

    const previousBySeatId = new Map(
      previousSeats.map((seat) => [seat.seatId, seat]),
    );
    const expiryLogs = [];

    nextSeats.forEach((nextSeat) => {
      const previousSeat = previousBySeatId.get(nextSeat.seatId);
      if (!previousSeat) {
        return;
      }

      if (
        previousSeat.status === "held" &&
        nextSeat.status === "available" &&
        previousSeat.userId
      ) {
        expiryLogs.push(
          createLogEntry(
            `${previousSeat.userId} TTL_EXPIRED ${nextSeat.seatId} -> AVAILABLE`,
            "warning",
          ),
        );
      }
    });

    if (expiryLogs.length > 0) {
      pushLogs(expiryLogs);
    }
  }

  async function refreshDashboard({ silent = false } = {}) {
    if (!silent) {
      setIsRefreshing(true);
    }

    try {
      const [nextSeats, queueSnapshot, nextConfirmedSeats] = await Promise.all([
        fetchSeats(DEMO_EVENT_ID),
        fetchQueueSnapshot(DEMO_EVENT_ID),
        fetchConfirmedSeats(DEMO_EVENT_ID),
      ]);

      detectSeatExpiryLogs(previousSeatsRef.current, nextSeats);
      previousSeatsRef.current = nextSeats;
      setSeats(nextSeats);
      setQueueEntries(queueSnapshot.queue);
      setQueueFrontUserId(queueSnapshot.frontUserId);
      setConfirmedSeats(nextConfirmedSeats);
      setLastRefreshAt(new Date());

      if (!silent) {
        const counts = countSeatStates(nextSeats);
        addLog(
          `REFRESH -> available ${counts.available}, held ${counts.held}, confirmed ${counts.confirmed}`,
        );
      }
    } catch (error) {
      addLog(`REFRESH -> FAIL (${error.message})`, "error");
    } finally {
      if (!silent) {
        setIsRefreshing(false);
      }
    }
  }

  async function reserveSeatForUser(userId, seatId) {
    setBusySeatId(seatId);
    try {
      await reserveSeat(DEMO_EVENT_ID, seatId, userId, DEFAULT_HOLD_SECONDS);
      addLog(`${userId} RESERVE_SEAT ${seatId} -> SUCCESS`, "success");
    } catch (error) {
      addLog(`${userId} RESERVE_SEAT ${seatId} -> FAIL (${error.message})`, "error");
    } finally {
      setBusySeatId("");
      await refreshDashboard({ silent: true });
    }
  }

  async function confirmSeatForUser(userId, seatId) {
    setUserActionBusy(true);
    try {
      await confirmSeat(DEMO_EVENT_ID, seatId, userId);
      addLog(`${userId} CONFIRM_SEAT ${seatId} -> SUCCESS`, "success");
    } catch (error) {
      addLog(`${userId} CONFIRM_SEAT ${seatId} -> FAIL (${error.message})`, "error");
    } finally {
      setUserActionBusy(false);
      await refreshDashboard({ silent: true });
    }
  }

  async function releaseSeatForUser(userId, seatId) {
    setUserActionBusy(true);
    try {
      await releaseSeat(DEMO_EVENT_ID, seatId, userId);
      addLog(`${userId} RELEASE_SEAT ${seatId} -> SUCCESS`, "warning");
    } catch (error) {
      addLog(`${userId} RELEASE_SEAT ${seatId} -> FAIL (${error.message})`, "error");
    } finally {
      setUserActionBusy(false);
      await refreshDashboard({ silent: true });
    }
  }

  async function joinQueueForUser(userId) {
    setQueueBusy(true);
    try {
      const result = await joinQueue(DEMO_EVENT_ID, userId);
      const outcome = result.joined ? "JOIN_QUEUE" : "JOIN_QUEUE (duplicate)";
      addLog(`${userId} ${outcome} -> position ${result.position}`, "info");
    } catch (error) {
      addLog(`${userId} JOIN_QUEUE -> FAIL (${error.message})`, "error");
    } finally {
      setQueueBusy(false);
      await refreshDashboard({ silent: true });
    }
  }

  async function leaveQueueForUser(userId) {
    setQueueBusy(true);
    try {
      const result = await leaveQueue(DEMO_EVENT_ID, userId);
      const outcome = result.removed
        ? `removed from position ${result.previousPosition}`
        : "not in queue";
      addLog(`${userId} LEAVE_QUEUE -> ${outcome}`, result.removed ? "warning" : "info");
    } catch (error) {
      addLog(`${userId} LEAVE_QUEUE -> FAIL (${error.message})`, "error");
    } finally {
      setQueueBusy(false);
      await refreshDashboard({ silent: true });
    }
  }

  async function popQueueFront() {
    setQueueBusy(true);
    try {
      const result = await popQueue(DEMO_EVENT_ID);
      addLog(
        `POP_QUEUE -> ${result.userId ?? "empty"} / remaining ${result.queueLength}`,
        result.userId ? "warning" : "info",
      );
    } catch (error) {
      addLog(`POP_QUEUE -> FAIL (${error.message})`, "error");
    } finally {
      setQueueBusy(false);
      await refreshDashboard({ silent: true });
    }
  }

  async function peekQueueFront() {
    setQueueBusy(true);
    try {
      const result = await peekQueue(DEMO_EVENT_ID);
      addLog(`PEEK_QUEUE -> ${result.userId ?? "empty"}`, "info");
    } catch (error) {
      addLog(`PEEK_QUEUE -> FAIL (${error.message})`, "error");
    } finally {
      setQueueBusy(false);
      await refreshDashboard({ silent: true });
    }
  }

  async function handleStartBooking() {
    clearSimulationTimeouts();
    setIsSimulating(false);
    setBookingStarted(true);

    if (apiCapabilities.supportsResetDemo) {
      await resetDemo(DEMO_EVENT_ID);
      previousSeatsRef.current = [];
      setLogs([
        createLogEntry(`BOOKING_START -> reset demo state for ${DEMO_EVENT_ID}`, "success"),
      ]);
    } else {
      setLogs([
        createLogEntry(
          `BOOKING_START -> reading live backend state for ${DEMO_EVENT_ID}`,
          "success",
        ),
      ]);
    }

    await refreshDashboard({ silent: true });
  }

  function scheduleStep(delayMs, action) {
    return new Promise((resolve) => {
      const timeoutId = window.setTimeout(async () => {
        try {
          await action();
        } finally {
          resolve();
        }
      }, delayMs);

      simulationTimeoutsRef.current.push(timeoutId);
    });
  }

  async function handleSimulation() {
    if (isSimulating) {
      return;
    }

    if (!bookingStarted) {
      await handleStartBooking();
    }

    setIsSimulating(true);
    addLog("SIMULATION_START", "info");

    const seatIdPool = getSeatIdPool();
    const conflictSeat = randomFrom(seatIdPool);
    const alternateSeat =
      seatIdPool.find((seatId) => seatId !== conflictSeat) ?? "B1";

    try {
      const steps = [
        scheduleStep(100, () => joinQueueForUser("user-1")),
        scheduleStep(180, () => joinQueueForUser("user-2")),
        scheduleStep(260, () => joinQueueForUser("user-3")),
        scheduleStep(520, () => reserveSeatForUser("user-1", conflictSeat)),
        scheduleStep(560, () => reserveSeatForUser("user-2", conflictSeat)),
        scheduleStep(700, () => reserveSeatForUser("user-3", alternateSeat)),
        scheduleStep(1120, () => confirmSeatForUser("user-1", conflictSeat)),
        scheduleStep(1480, () => releaseSeatForUser("user-3", alternateSeat)),
      ];

      if (apiCapabilities.supportsPopQueue) {
        steps.push(scheduleStep(1850, () => popQueueFront()));
      }

      steps.push(scheduleStep(2100, () => peekQueueFront()));
      await Promise.all(steps);
      addLog("SIMULATION_END", "success");
    } finally {
      clearSimulationTimeouts();
      setIsSimulating(false);
      await refreshDashboard({ silent: true });
    }
  }

  useEffect(() => {
    refreshDashboard({ silent: true });

    const intervalId = window.setInterval(() => {
      refreshDashboard({ silent: true });
    }, POLL_INTERVAL_MS);

    return () => {
      window.clearInterval(intervalId);
      clearSimulationTimeouts();
    };
  }, []);

  const counts = countSeatStates(seats);
  const myHeldSeats = seats.filter(
    (seat) => seat.status === "held" && seat.userId === selectedUser,
  );
  const myConfirmedSeats = confirmedSeats.filter(
    (seat) => seat.userId === selectedUser,
  );
  const selectedUserQueueEntry = queueEntries.find(
    (entry) => entry.userId === selectedUser,
  );

  return (
    <div className="page-shell">
      <header className="card hero-card">
        <div>
          <p className="eyebrow">Mini Redis Demo Frontend</p>
          <h1>{PAGE_TITLE}</h1>
          <p className="hero-description">{PAGE_DESCRIPTION}</p>
        </div>
        <div className="hero-meta">
          <span className={`mode-badge mode-${apiMode}`}>
            {apiMode === "mock" ? "MOCK MODE" : "REAL API MODE"}
          </span>
          <span className="event-badge">{DEMO_EVENT_ID}</span>
          <span className="subtle-badge">
            last refresh: {lastRefreshAt ? formatTimestamp(lastRefreshAt) : "-"}
          </span>
        </div>
      </header>

      <section className="card control-bar">
        <div className="control-left">
          <div className="control-block">
            <label htmlFor="selected-user">Current user</label>
            <select
              id="selected-user"
              value={selectedUser}
              onChange={(event) => setSelectedUser(event.target.value)}
            >
              {DEMO_USERS.map((userId) => (
                <option key={userId} value={userId}>
                  {userId}
                </option>
              ))}
            </select>
          </div>

          <div className="control-status">
            <span className={bookingStarted ? "live-dot live" : "live-dot"} />
            <span>{bookingStarted ? "Booking live" : "Waiting"}</span>
          </div>
        </div>

        <div className="control-actions">
          <button
            type="button"
            className="action-button action-primary"
            onClick={handleStartBooking}
          >
            Start booking
          </button>
          <button
            type="button"
            className="action-button action-secondary"
            onClick={handleSimulation}
            disabled={isSimulating}
          >
            Run simulation
          </button>
          <button
            type="button"
            className="action-button action-secondary"
            onClick={() => refreshDashboard()}
            disabled={isRefreshing}
          >
            Refresh state
          </button>
        </div>
      </section>

      <main className="dashboard-layout">
        <div className="main-column">
          <SeatGrid
            seats={seats}
            counts={counts}
            selectedUser={selectedUser}
            onSeatClick={(seat) => {
              if (!bookingStarted) {
                addLog(
                  `${selectedUser} RESERVE_SEAT ${seat.seatId} -> BLOCKED (booking not started)`,
                  "warning",
                );
                return;
              }

              reserveSeatForUser(selectedUser, seat.seatId);
            }}
            busySeatId={busySeatId}
            bookingStarted={bookingStarted}
          />

          <UserPanel
            selectedUser={selectedUser}
            onUserChange={setSelectedUser}
            users={DEMO_USERS}
            myHeldSeats={myHeldSeats}
            myConfirmedSeats={myConfirmedSeats}
            queuePosition={selectedUserQueueEntry?.position ?? -1}
            onConfirm={(seatId) => confirmSeatForUser(selectedUser, seatId)}
            onRelease={(seatId) => releaseSeatForUser(selectedUser, seatId)}
            isBusy={userActionBusy}
          />
        </div>

        <div className="side-column">
          <LogPanel logs={logs} />
          <QueuePanel
            queueEntries={queueEntries}
            queueLength={queueEntries.length}
            frontUserId={queueFrontUserId}
            selectedUser={selectedUser}
            isBusy={queueBusy}
            onJoin={() => joinQueueForUser(selectedUser)}
            onPop={popQueueFront}
            onLeave={() => leaveQueueForUser(selectedUser)}
            onPeek={peekQueueFront}
            canPop={apiCapabilities.supportsPopQueue}
          />
        </div>
      </main>
    </div>
  );
}
