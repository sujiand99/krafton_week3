import { useEffect, useRef, useState } from "react";
import LogPanel from "./components/LogPanel";
import OrchestrationPanel from "./components/OrchestrationPanel";
import RedisWorkerPanel from "./components/RedisWorkerPanel";
import SeatGrid from "./components/SeatGrid";
import UserPanel from "./components/UserPanel";
import {
  apiCapabilities,
  apiMode,
  clearOrchestrationLogs,
  confirmSeat,
  fetchConfirmedSeats,
  fetchOrchestrationLogs,
  fetchSeats,
  getSeatIdPool,
  releaseSeat,
  reserveSeat,
  resetDemo,
} from "./services/api";
import {
  BURST_REQUEST_MULTIPLIER,
  DEFAULT_HOLD_SECONDS,
  DEMO_EVENT_ID,
  DEMO_USERS,
  POLL_INTERVAL_MS,
  TOTAL_BURST_REQUESTS,
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

function buildBurstAttempts(seatIdPool) {
  const attempts = seatIdPool.flatMap((seatId) =>
    Array.from({ length: BURST_REQUEST_MULTIPLIER }, (_, index) => ({
      seatId,
      userId: `load-user-${seatId}-${String(index + 1).padStart(2, "0")}`,
    })),
  );

  for (let index = attempts.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(Math.random() * (index + 1));
    const nextValue = attempts[swapIndex];
    attempts[swapIndex] = attempts[index];
    attempts[index] = nextValue;
  }

  return attempts;
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
  "66 seats on screen, 1,980 reserve attempts in the crowd burst, with Redis worker backlog and DB orchestration flow.";
const BURST_LOG_INTERVAL = 250;
const BURST_RENDER_INTERVAL = 50;
const REDIS_RECENT_OPERATION_LIMIT = 18;

function createWorkerOperation({ userId, command, seatId, status, note = "" }) {
  return {
    id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    userId,
    command,
    seatId,
    status,
    note,
    updatedAt: new Date().toISOString(),
  };
}

export default function App() {
  const seatIdPool = getSeatIdPool();
  const [selectedUser, setSelectedUser] = useState(DEMO_USERS[0]);
  const [seats, setSeats] = useState(createSeatSkeletons());
  const [logs, setLogs] = useState([
    createLogEntry(`frontend ready (${apiMode.toUpperCase()} mode)`),
  ]);
  const [bookingStarted, setBookingStarted] = useState(false);
  const [busySeatId, setBusySeatId] = useState("");
  const [userActionBusy, setUserActionBusy] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isSimulating, setIsSimulating] = useState(false);
  const [lastRefreshAt, setLastRefreshAt] = useState(null);
  const [confirmedSeats, setConfirmedSeats] = useState([]);
  const [orchestrationLogs, setOrchestrationLogs] = useState([]);
  const [isClearingOrchestration, setIsClearingOrchestration] = useState(false);
  const [burstStats, setBurstStats] = useState({
    total: TOTAL_BURST_REQUESTS,
    completed: 0,
    successes: 0,
    failures: 0,
    lastSeatId: "-",
  });
  const [redisWorker, setRedisWorker] = useState({
    queued: 0,
    inFlight: 0,
    completed: 0,
    successes: 0,
    failures: 0,
    peakInFlight: 0,
    recentOperations: [],
  });

  const previousSeatsRef = useRef([]);
  const simulationTimeoutsRef = useRef([]);
  const dashboardRequestRef = useRef(0);

  function pushLogs(nextEntries) {
    setLogs((currentLogs) => [...nextEntries, ...currentLogs].slice(0, 180));
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

  function resetRedisWorker() {
    setRedisWorker({
      queued: 0,
      inFlight: 0,
      completed: 0,
      successes: 0,
      failures: 0,
      peakInFlight: 0,
      recentOperations: [],
    });
  }

  function enqueueRedisOperation(userId, command, seatId) {
    const operation = createWorkerOperation({
      userId,
      command,
      seatId,
      status: "queued",
    });

    setRedisWorker((current) => ({
      ...current,
      queued: current.queued + 1,
      recentOperations: [operation, ...current.recentOperations].slice(
        0,
        REDIS_RECENT_OPERATION_LIMIT,
      ),
    }));

    return operation.id;
  }

  function startRedisOperation(operationId) {
    setRedisWorker((current) => {
      const nextInFlight = current.inFlight + 1;

      return {
        ...current,
        queued: Math.max(0, current.queued - 1),
        inFlight: nextInFlight,
        peakInFlight: Math.max(current.peakInFlight, nextInFlight),
        recentOperations: current.recentOperations.map((operation) =>
          operation.id === operationId
            ? {
                ...operation,
                status: "running",
                updatedAt: new Date().toISOString(),
              }
            : operation,
        ),
      };
    });
  }

  function finishRedisOperation(operationId, status, note = "") {
    setRedisWorker((current) => ({
      ...current,
      inFlight: Math.max(0, current.inFlight - 1),
      completed: current.completed + 1,
      successes: current.successes + (status === "success" ? 1 : 0),
      failures: current.failures + (status === "fail" ? 1 : 0),
      recentOperations: current.recentOperations.map((operation) =>
        operation.id === operationId
          ? {
              ...operation,
              status,
              note,
              updatedAt: new Date().toISOString(),
            }
          : operation,
      ),
    }));
  }

  function primeRedisQueue(totalCount) {
    setRedisWorker((current) => ({
      ...current,
      queued: current.queued + totalCount,
    }));
  }

  function startPrimedRedisOperation(userId, command, seatId) {
    const operation = createWorkerOperation({
      userId,
      command,
      seatId,
      status: "running",
    });

    setRedisWorker((current) => {
      const nextInFlight = current.inFlight + 1;

      return {
        ...current,
        queued: Math.max(0, current.queued - 1),
        inFlight: nextInFlight,
        peakInFlight: Math.max(current.peakInFlight, nextInFlight),
        recentOperations: [operation, ...current.recentOperations].slice(
          0,
          REDIS_RECENT_OPERATION_LIMIT,
        ),
      };
    });

    return operation.id;
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
    const requestId = dashboardRequestRef.current + 1;
    dashboardRequestRef.current = requestId;

    if (!silent) {
      setIsRefreshing(true);
    }

    try {
      const [nextSeats, nextConfirmedSeats, nextOrchestrationLogs] = await Promise.all([
        fetchSeats(DEMO_EVENT_ID),
        fetchConfirmedSeats(DEMO_EVENT_ID),
        fetchOrchestrationLogs(32),
      ]);

      if (requestId !== dashboardRequestRef.current) {
        return;
      }

      detectSeatExpiryLogs(previousSeatsRef.current, nextSeats);
      previousSeatsRef.current = nextSeats;
      setSeats(nextSeats);
      setConfirmedSeats(nextConfirmedSeats);
      setOrchestrationLogs(nextOrchestrationLogs);
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
    const operationId = enqueueRedisOperation(userId, "RESERVE_SEAT", seatId);
    startRedisOperation(operationId);
    setBusySeatId(seatId);
    try {
      await reserveSeat(DEMO_EVENT_ID, seatId, userId, DEFAULT_HOLD_SECONDS);
      finishRedisOperation(operationId, "success");
      addLog(`${userId} RESERVE_SEAT ${seatId} -> SUCCESS`, "success");
    } catch (error) {
      finishRedisOperation(operationId, "fail", error.message);
      addLog(`${userId} RESERVE_SEAT ${seatId} -> FAIL (${error.message})`, "error");
    } finally {
      setBusySeatId("");
      await refreshDashboard({ silent: true });
    }
  }

  async function confirmSeatForUser(userId, seatId) {
    const operationId = enqueueRedisOperation(userId, "CONFIRM_SEAT", seatId);
    startRedisOperation(operationId);
    setUserActionBusy(true);
    try {
      await confirmSeat(DEMO_EVENT_ID, seatId, userId);
      finishRedisOperation(operationId, "success");
      addLog(`${userId} CONFIRM_SEAT ${seatId} -> SUCCESS`, "success");
    } catch (error) {
      finishRedisOperation(operationId, "fail", error.message);
      addLog(`${userId} CONFIRM_SEAT ${seatId} -> FAIL (${error.message})`, "error");
    } finally {
      setUserActionBusy(false);
      await refreshDashboard({ silent: true });
    }
  }

  async function releaseSeatForUser(userId, seatId) {
    const operationId = enqueueRedisOperation(userId, "RELEASE_SEAT", seatId);
    startRedisOperation(operationId);
    setUserActionBusy(true);
    try {
      await releaseSeat(DEMO_EVENT_ID, seatId, userId);
      finishRedisOperation(operationId, "success");
      addLog(`${userId} RELEASE_SEAT ${seatId} -> SUCCESS`, "warning");
    } catch (error) {
      finishRedisOperation(operationId, "fail", error.message);
      addLog(`${userId} RELEASE_SEAT ${seatId} -> FAIL (${error.message})`, "error");
    } finally {
      setUserActionBusy(false);
      await refreshDashboard({ silent: true });
    }
  }

  async function handleClearOrchestration() {
    setIsClearingOrchestration(true);
    dashboardRequestRef.current += 1;
    try {
      await clearOrchestrationLogs();
      setOrchestrationLogs([]);
      addLog("ORCHESTRATION_CLEAR -> SUCCESS", "info");
    } catch (error) {
      addLog(`ORCHESTRATION_CLEAR -> FAIL (${error.message})`, "error");
    } finally {
      setIsClearingOrchestration(false);
    }
  }

  async function handleStartBooking() {
    clearSimulationTimeouts();
    setIsSimulating(false);
    setBookingStarted(true);
    resetRedisWorker();
    setBurstStats({
      total: TOTAL_BURST_REQUESTS,
      completed: 0,
      successes: 0,
      failures: 0,
      lastSeatId: "-",
    });

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

    const conflictSeat = randomFrom(seatIdPool);
    const alternateSeat =
      seatIdPool.find((seatId) => seatId !== conflictSeat) ?? "B1";
    const releaseSeatId =
      seatIdPool.find(
        (seatId) => seatId !== conflictSeat && seatId !== alternateSeat,
      ) ?? alternateSeat;

    try {
      const steps = [
        scheduleStep(120, () => reserveSeatForUser("user-1", conflictSeat)),
        scheduleStep(180, () => reserveSeatForUser("user-2", conflictSeat)),
        scheduleStep(320, () => reserveSeatForUser("user-3", alternateSeat)),
        scheduleStep(760, () => confirmSeatForUser("user-1", conflictSeat)),
        scheduleStep(980, () => reserveSeatForUser("user-2", alternateSeat)),
        scheduleStep(1240, () => reserveSeatForUser("user-3", releaseSeatId)),
        scheduleStep(1620, () => releaseSeatForUser("user-3", releaseSeatId)),
      ];
      await Promise.all(steps);
      addLog("SIMULATION_END", "success");
    } finally {
      clearSimulationTimeouts();
      setIsSimulating(false);
      await refreshDashboard({ silent: true });
    }
  }

  async function handleBurstSimulation() {
    if (isSimulating) {
      return;
    }

    if (!bookingStarted) {
      await handleStartBooking();
    }

    setIsSimulating(true);
    setBurstStats({
      total: TOTAL_BURST_REQUESTS,
      completed: 0,
      successes: 0,
      failures: 0,
      lastSeatId: "-",
    });
    addLog(
      `BURST_START -> ${TOTAL_BURST_REQUESTS.toLocaleString("en-US")} reserve attempts across ${seatIdPool.length} seats`,
      "warning",
    );

    const attempts = buildBurstAttempts(seatIdPool);
    primeRedisQueue(attempts.length);
    const concurrency = apiMode === "real" ? 24 : 40;
    let nextIndex = 0;
    let nextLogAt = BURST_LOG_INTERVAL;
    const stats = {
      total: attempts.length,
      completed: 0,
      successes: 0,
      failures: 0,
      lastSeatId: "-",
    };

    async function worker() {
      while (true) {
        const attempt = attempts[nextIndex];
        nextIndex += 1;

        if (!attempt) {
          return;
        }

        const operationId = startPrimedRedisOperation(
          attempt.userId,
          "RESERVE_SEAT",
          attempt.seatId,
        );

        try {
          await reserveSeat(DEMO_EVENT_ID, attempt.seatId, attempt.userId, DEFAULT_HOLD_SECONDS);
          finishRedisOperation(operationId, "success");
          stats.successes += 1;
        } catch (error) {
          finishRedisOperation(operationId, "fail", error.message);
          stats.failures += 1;
        }

        stats.completed += 1;
        stats.lastSeatId = attempt.seatId;

        if (
          stats.completed % BURST_RENDER_INTERVAL === 0 ||
          stats.completed === stats.total
        ) {
          setBurstStats({ ...stats });
        }

        if (stats.completed >= nextLogAt || stats.completed === stats.total) {
          addLog(
            `BURST_PROGRESS -> ${stats.completed.toLocaleString("en-US")}/${stats.total.toLocaleString("en-US")} (success ${stats.successes}, fail ${stats.failures})`,
            "info",
          );
          nextLogAt += BURST_LOG_INTERVAL;
        }
      }
    }

    try {
      await Promise.all(
        Array.from({ length: concurrency }, () => worker()),
      );
      addLog(
        `BURST_END -> success ${stats.successes}, fail ${stats.failures}, last seat ${stats.lastSeatId}`,
        "success",
      );
    } finally {
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
          <span className="subtle-badge">{seatIdPool.length} seats</span>
          <span className="subtle-badge">
            burst {TOTAL_BURST_REQUESTS.toLocaleString("en-US")} requests
          </span>
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
          <div className="control-status">
            <span>
              burst {burstStats.completed.toLocaleString("en-US")}/
              {burstStats.total.toLocaleString("en-US")}
            </span>
            <span>
              ok {burstStats.successes} / fail {burstStats.failures}
            </span>
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
            Run scripted demo
          </button>
          <button
            type="button"
            className="action-button action-secondary"
            onClick={handleBurstSimulation}
            disabled={isSimulating}
          >
            Run crowd burst
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
            onConfirm={(seatId) => confirmSeatForUser(selectedUser, seatId)}
            onRelease={(seatId) => releaseSeatForUser(selectedUser, seatId)}
            isBusy={userActionBusy}
          />
        </div>

        <div className="side-column">
          <LogPanel logs={logs} />
          <OrchestrationPanel
            entries={orchestrationLogs}
            onClear={handleClearOrchestration}
            isClearing={isClearingOrchestration}
          />
          <RedisWorkerPanel
            queuedCount={redisWorker.queued}
            inFlightCount={redisWorker.inFlight}
            completedCount={redisWorker.completed}
            successCount={redisWorker.successes}
            failureCount={redisWorker.failures}
            peakInFlight={redisWorker.peakInFlight}
            recentOperations={redisWorker.recentOperations}
          />
        </div>
      </main>
    </div>
  );
}
