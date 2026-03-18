const summaryGrid = document.getElementById("summary-grid");
const seatGrid = document.getElementById("seat-grid");
const seatFocus = document.getElementById("seat-focus");
const logList = document.getElementById("log-list");
const reservationTable = document.getElementById("reservation-table");
const statusBanner = document.getElementById("status-banner");
const contractText = document.getElementById("contract-text");
const surgeCard = document.getElementById("surge-card");
const seatInput = document.getElementById("seat-id");
const userInput = document.getElementById("user-id");
const holdInput = document.getElementById("hold-seconds");
const surgeUsersInput = document.getElementById("surge-users");
const surgeSeatsInput = document.getElementById("surge-seats");
const runbookItems = Array.from(document.querySelectorAll("#runbook-list li"));
const interactiveButtons = Array.from(document.querySelectorAll("button"));

let selectedSeat = "S0001";
let latestState = null;
let scenarioRunning = false;

const sectionOrder = ["VIP", "R", "S", "A"];
const summaryCards = [
  ["total_seats", "Total seats", "highlight"],
  ["users_online", "Users online", ""],
  ["available", "Available", ""],
  ["held", "Held", ""],
  ["confirmed", "Confirmed", ""],
  ["expired_holds", "Expired holds", ""],
];

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  return response.json();
}

function setInteractiveDisabled(disabled) {
  interactiveButtons.forEach((button) => {
    button.disabled = disabled;
  });
}

function setRunbookStep(index = -1) {
  runbookItems.forEach((item, itemIndex) => {
    item.classList.toggle("active", itemIndex === index);
  });
}

function renderSummary(summary) {
  summaryGrid.innerHTML = summaryCards
    .map(
      ([key, label, extraClass]) => `
        <article class="summary-card ${extraClass}">
          <span class="summary-label">${label}</span>
          <span class="summary-value">${summary[key]}</span>
        </article>
      `,
    )
    .join("");
}

function seatClass(status) {
  switch (status) {
    case "HELD":
      return "held";
    case "CONFIRMED":
      return "confirmed";
    case "EXPIRED":
    case "CANCELLED":
      return "expired";
    default:
      return "available";
  }
}

function seatBadge(status, ttlSeconds) {
  if (status === "HELD" && ttlSeconds != null) {
    return ttlSeconds > 9 ? "H" : String(ttlSeconds);
  }
  if (status === "CONFIRMED") {
    return "C";
  }
  if (status === "EXPIRED" || status === "CANCELLED") {
    return "X";
  }
  return "A";
}

function renderSeatFocus(seat) {
  if (!seat) {
    seatFocus.innerHTML = '<div class="muted">좌석을 선택하면 상세 상태가 보입니다.</div>';
    return;
  }

  const ttl = seat.ttl_seconds != null ? `${seat.ttl_seconds}s` : "-";
  const user = seat.user_id || "없음";
  seatFocus.innerHTML = `
    <div class="seat-focus-head">
      <div>
        <span class="focus-label">선택 좌석</span>
        <strong class="focus-seat">${escapeHtml(seat.seat_id)}</strong>
      </div>
      <span class="focus-state ${seatClass(seat.status)}">${escapeHtml(seat.status)}</span>
    </div>
    <div class="seat-focus-grid">
      <div class="focus-item">
        <span class="focus-label">구역</span>
        <span class="focus-value">${escapeHtml(seat.section)}</span>
      </div>
      <div class="focus-item">
        <span class="focus-label">행 / 번호</span>
        <span class="focus-value">${escapeHtml(seat.row_label)}-${escapeHtml(seat.seat_number)}</span>
      </div>
      <div class="focus-item">
        <span class="focus-label">사용자</span>
        <span class="focus-value">${escapeHtml(user)}</span>
      </div>
      <div class="focus-item">
        <span class="focus-label">TTL / 소스</span>
        <span class="focus-value">${escapeHtml(ttl)} / ${escapeHtml(seat.source)}</span>
      </div>
    </div>
  `;
}

function groupSeats(seats) {
  const groups = new Map();
  sectionOrder.forEach((section) => groups.set(section, []));
  seats.forEach((seat) => {
    const section = seat.section || "OTHER";
    if (!groups.has(section)) {
      groups.set(section, []);
    }
    groups.get(section).push(seat);
  });
  return groups;
}

function renderSeats(seats) {
  const selected = seats.find((seat) => seat.seat_id === selectedSeat) || seats[0] || null;
  if (selected) {
    selectedSeat = selected.seat_id;
    seatInput.value = selected.seat_id;
  }

  renderSeatFocus(selected);

  const grouped = groupSeats(seats);
  seatGrid.innerHTML = Array.from(grouped.entries())
    .filter(([, sectionSeats]) => sectionSeats.length > 0)
    .map(([section, sectionSeats]) => `
      <section class="seat-section">
        <div class="section-head">
          <div>
            <span>Section</span>
            <strong>${escapeHtml(section)}</strong>
          </div>
          <span class="focus-label">${sectionSeats.length} seats on screen</span>
        </div>
        <div class="section-grid">
          ${sectionSeats
            .map((seat) => {
              const cssClass = seatClass(seat.status);
              const selectedClass = seat.seat_id === selectedSeat ? "selected" : "";
              const badge = seatBadge(seat.status, seat.ttl_seconds);
              const title = [
                seat.seat_id,
                `section: ${seat.section}`,
                `row: ${seat.row_label}-${seat.seat_number}`,
                `status: ${seat.status}`,
                `user: ${seat.user_id || "none"}`,
                `ttl: ${seat.ttl_seconds != null ? `${seat.ttl_seconds}s` : "-"}`,
              ].join(" | ");
              return `
                <button
                  class="seat-card ${cssClass} ${selectedClass}"
                  data-seat-id="${seat.seat_id}"
                  title="${escapeHtml(title)}"
                  aria-label="${escapeHtml(title)}"
                >
                  <span class="seat-code">${escapeHtml(seat.seat_id)}</span>
                  <span class="seat-badge">${badge}</span>
                  <span class="seat-sub">${escapeHtml(seat.row_label)}-${escapeHtml(seat.seat_number)}</span>
                </button>
              `;
            })
            .join("")}
        </div>
      </section>
    `)
    .join("");

  for (const button of seatGrid.querySelectorAll(".seat-card")) {
    button.addEventListener("click", () => {
      selectedSeat = button.dataset.seatId;
      seatInput.value = selectedSeat;
      if (latestState) {
        renderSeats(latestState.featured_seats);
      }
    });
  }
}

function renderLogs(logs) {
  logList.innerHTML = logs
    .map(
      (entry) => `
        <article class="log-entry ${entry.level.toLowerCase()}">
          <div class="log-meta">
            <span>${escapeHtml(entry.time)}</span>
            <span>${escapeHtml(entry.source)} / ${escapeHtml(entry.level)}</span>
          </div>
          <div>${escapeHtml(entry.message)}</div>
        </article>
      `,
    )
    .join("");
}

function renderReservations(rows) {
  if (!rows.length) {
    reservationTable.innerHTML = `
      <tr>
        <td colspan="5" class="muted">아직 DB 확정 예약이 없습니다.</td>
      </tr>
    `;
    return;
  }

  reservationTable.innerHTML = rows
    .map(
      (row) => `
        <tr>
          <td>${escapeHtml(row.reservation_id)}</td>
          <td>${escapeHtml(row.seat_id)}</td>
          <td>${escapeHtml(row.user_id)}</td>
          <td>${escapeHtml(row.status)}</td>
          <td>${escapeHtml(row.confirmed_at || "-")}</td>
        </tr>
      `,
    )
    .join("");
}

function renderContractBlock(summary) {
  contractText.textContent =
    `현재 ${summary.held}석은 Redis가 HELD 상태로 관리하고 있고, ` +
    `${summary.confirmed}건은 DB 최종 예약으로 확정돼 있습니다. ` +
    `즉 빠른 경쟁 제어는 Redis가, 최종 예약의 진실은 DB가 담당합니다.`;
}

function renderSurge(surge, summary) {
  surgeCard.innerHTML = `
    <h3>대규모 러시 시뮬레이션</h3>
    <div class="surge-metrics">
      <div class="mini-stat">
        <span class="mini-label">Users raced</span>
        <span class="mini-value">${surge.contenders}</span>
      </div>
      <div class="mini-stat">
        <span class="mini-label">Hot seats</span>
        <span class="mini-value">${surge.focus_seats}</span>
      </div>
      <div class="mini-stat">
        <span class="mini-label">Held</span>
        <span class="mini-value">${surge.held}</span>
      </div>
      <div class="mini-stat">
        <span class="mini-label">Rejected</span>
        <span class="mini-value">${surge.rejected}</span>
      </div>
      <div class="mini-stat">
        <span class="mini-label">Duration</span>
        <span class="mini-value">${surge.duration_ms} ms</span>
      </div>
      <div class="mini-stat">
        <span class="mini-label">Runs</span>
        <span class="mini-value">${summary.surge_runs}</span>
      </div>
    </div>
    <div class="sample-list">
      <strong>샘플 성공</strong>: ${surge.sample_winners.length ? surge.sample_winners.map(escapeHtml).join(", ") : "아직 없음"}
    </div>
    <div class="sample-list">
      <strong>샘플 실패</strong>: ${surge.sample_rejections.length ? surge.sample_rejections.map(escapeHtml).join(", ") : "아직 없음"}
    </div>
  `;
}

function renderState(state) {
  latestState = state;
  renderSummary(state.summary);
  renderSeats(state.featured_seats);
  renderLogs(state.logs);
  renderReservations(state.reservations);
  renderContractBlock(state.summary);
  renderSurge(state.surge, state.summary);
}

function setBanner(message, isError = false) {
  statusBanner.textContent = message;
  statusBanner.style.background = isError
    ? "rgba(227, 101, 91, 0.14)"
    : "rgba(241, 205, 125, 0.12)";
  statusBanner.style.borderColor = isError
    ? "rgba(227, 101, 91, 0.22)"
    : "rgba(241, 205, 125, 0.16)";
}

async function refreshState() {
  try {
    const state = await requestJson("/api/state");
    renderState(state);
    if (!scenarioRunning) {
      setBanner(`${state.event.title} / ${selectedSeat} 기준으로 최신 상태를 반영했습니다.`);
    }
  } catch (error) {
    setBanner("대시보드 상태를 불러오지 못했습니다.", true);
    console.error(error);
  }
}

async function invokeAction(path, payload, successMessage) {
  const result = await requestJson(path, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  setBanner(result.message || successMessage, !result.ok);
  await refreshState();
  return result;
}

async function runAction(path, payload, successMessage) {
  try {
    await invokeAction(path, payload, successMessage);
  } catch (error) {
    setBanner("요청 처리 중 오류가 발생했습니다.", true);
    console.error(error);
  }
}

async function runSurge(contenders, focusSeats) {
  await runAction(
    "/api/actions/simulate",
    {
      contenders,
      focus_seats: focusSeats,
      ttl_seconds: Number(holdInput.value || 10),
    },
    "티켓 오픈 러시를 실행했습니다.",
  );
}

async function playScenario(label, runner) {
  if (scenarioRunning) {
    return;
  }

  scenarioRunning = true;
  setInteractiveDisabled(true);

  try {
    await runner();
    setBanner(`${label} 시연이 끝났습니다. 로그와 좌석 상태를 확인해 주세요.`);
  } catch (error) {
    console.error(error);
    setBanner(`${label} 시연 중 오류가 발생했습니다.`, true);
  } finally {
    scenarioRunning = false;
    setInteractiveDisabled(false);
    setRunbookStep(-1);
    await refreshState();
  }
}

async function performDuelDemo() {
  setRunbookStep(1);
  await invokeAction("/api/reset", {}, "데모 상태를 초기화했습니다.");
  selectedSeat = "S0001";
  seatInput.value = "S0001";
  userInput.value = "user0001";
  holdInput.value = "10";

  setBanner("1단계: user0001이 S0001 좌석을 먼저 홀드합니다.");
  await invokeAction(
    "/api/actions/reserve",
    { seat_id: "S0001", user_id: "user0001", ttl_seconds: 10 },
    "user0001 hold",
  );
  await sleep(700);

  setBanner("2단계: user0002가 같은 좌석을 요청하지만 이미 HELD 상태라 실패합니다.");
  userInput.value = "user0002";
  await invokeAction(
    "/api/actions/reserve",
    { seat_id: "S0001", user_id: "user0002", ttl_seconds: 10 },
    "user0002 retry",
  );
}

async function performFullDemo() {
  setRunbookStep(0);
  await invokeAction("/api/reset", {}, "데모 상태를 초기화했습니다.");
  await sleep(400);

  setRunbookStep(1);
  selectedSeat = "S0001";
  seatInput.value = "S0001";
  userInput.value = "user0001";
  holdInput.value = "10";
  setBanner("1단계: user0001이 S0001 좌석을 홀드합니다.");
  await invokeAction(
    "/api/actions/reserve",
    { seat_id: "S0001", user_id: "user0001", ttl_seconds: 10 },
    "reserve S0001",
  );
  await sleep(800);

  setBanner("2단계: user0002가 같은 좌석을 요청하지만 즉시 거절됩니다.");
  userInput.value = "user0002";
  await invokeAction(
    "/api/actions/reserve",
    { seat_id: "S0001", user_id: "user0002", ttl_seconds: 10 },
    "reject second request",
  );
  await sleep(800);

  setRunbookStep(2);
  setBanner("3단계: 다른 좌석 S0002를 5초 홀드해서 TTL 만료를 보여줍니다.");
  selectedSeat = "S0002";
  seatInput.value = "S0002";
  userInput.value = "user0003";
  await invokeAction(
    "/api/actions/reserve",
    { seat_id: "S0002", user_id: "user0003", ttl_seconds: 5 },
    "reserve S0002",
  );
  await sleep(800);

  setRunbookStep(3);
  setBanner("4단계: S0001은 결제 성공을 가정하고 DB에 최종 예약을 확정합니다.");
  selectedSeat = "S0001";
  seatInput.value = "S0001";
  userInput.value = "user0001";
  await invokeAction(
    "/api/actions/confirm",
    { seat_id: "S0001", user_id: "user0001" },
    "confirm S0001",
  );
  await sleep(1000);

  setRunbookStep(2);
  setBanner("5단계: S0002는 결제가 없으므로 TTL 만료를 기다립니다.");
  for (let remaining = 5; remaining >= 1; remaining -= 1) {
    setBanner(`S0002 홀드 만료 대기 중... ${remaining}초`);
    await sleep(1000);
    await refreshState();
  }

  setRunbookStep(4);
  setBanner("6단계: 10,000명 러시를 실행해 대량 경쟁 제어를 보여줍니다.");
  surgeUsersInput.value = "10000";
  surgeSeatsInput.value = "20";
  await invokeAction(
    "/api/actions/simulate",
    { contenders: 10000, focus_seats: 20, ttl_seconds: Number(holdInput.value || 10) },
    "run rush",
  );
}

document.getElementById("reserve-btn").addEventListener("click", async () => {
  await runAction(
    "/api/actions/reserve",
    {
      seat_id: seatInput.value.trim(),
      user_id: userInput.value.trim(),
      ttl_seconds: Number(holdInput.value || 10),
    },
    "좌석 홀드 요청을 보냈습니다.",
  );
});

document.getElementById("confirm-btn").addEventListener("click", async () => {
  await runAction(
    "/api/actions/confirm",
    {
      seat_id: seatInput.value.trim(),
      user_id: userInput.value.trim(),
    },
    "DB 확정 요청을 보냈습니다.",
  );
});

document.getElementById("release-btn").addEventListener("click", async () => {
  await runAction(
    "/api/actions/release",
    {
      seat_id: seatInput.value.trim(),
      user_id: userInput.value.trim(),
    },
    "홀드 해제 요청을 보냈습니다.",
  );
});

document.getElementById("simulate-btn").addEventListener("click", async () => {
  await runSurge(
    Number(surgeUsersInput.value || 10000),
    Number(surgeSeatsInput.value || 20),
  );
});

document.getElementById("preset-btn").addEventListener("click", async () => {
  surgeUsersInput.value = "10000";
  surgeSeatsInput.value = "20";
  await runSurge(10000, 20);
});

document.getElementById("reset-btn").addEventListener("click", async () => {
  await runAction("/api/reset", {}, "데모 상태를 초기화했습니다.");
});

document.getElementById("duel-demo-btn").addEventListener("click", async () => {
  await playScenario("2인 경합", performDuelDemo);
});

document.getElementById("full-demo-btn").addEventListener("click", async () => {
  await playScenario("발표용 전체", performFullDemo);
});

seatInput.addEventListener("change", () => {
  selectedSeat = seatInput.value.trim() || "S0001";
  if (latestState) {
    renderSeats(latestState.featured_seats);
  }
});

refreshState();
setInterval(() => {
  if (!scenarioRunning) {
    refreshState();
  }
}, 1000);
