function formatAge(timestamp) {
  const delta = Math.max(
    0,
    Math.floor((Date.now() - new Date(timestamp).getTime()) / 1000),
  );
  return `${delta}s ago`;
}

export default function RedisWorkerPanel({
  queuedCount,
  inFlightCount,
  completedCount,
  successCount,
  failureCount,
  peakInFlight,
  recentOperations,
}) {
  const sortedOperations = [...recentOperations].sort(
    (left, right) =>
      new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime(),
  );

  return (
    <section className="card worker-panel-card">
      <div className="card-header">
        <div>
          <p className="eyebrow">Redis Worker</p>
          <h2>Redis 작업 대기</h2>
          <p className="card-description">
            앱 서버가 Redis로 보내는 요청의 대기, 처리중, 완료 상태를 보여줍니다.
          </p>
        </div>
        <div className="worker-badges">
          <span className="subtle-badge">queued: {queuedCount}</span>
          <span className="subtle-badge">in-flight: {inFlightCount}</span>
        </div>
      </div>

      <div className="worker-stat-grid">
        <div className="worker-stat">
          <span className="worker-stat-label">Queued</span>
          <strong>{queuedCount}</strong>
        </div>
        <div className="worker-stat">
          <span className="worker-stat-label">Running</span>
          <strong>{inFlightCount}</strong>
        </div>
        <div className="worker-stat">
          <span className="worker-stat-label">Done</span>
          <strong>{completedCount}</strong>
        </div>
        <div className="worker-stat">
          <span className="worker-stat-label">Success</span>
          <strong>{successCount}</strong>
        </div>
        <div className="worker-stat">
          <span className="worker-stat-label">Fail</span>
          <strong>{failureCount}</strong>
        </div>
        <div className="worker-stat">
          <span className="worker-stat-label">Peak parallel</span>
          <strong>{peakInFlight}</strong>
        </div>
      </div>

      <div className="worker-list">
        {sortedOperations.length === 0 ? (
          <div className="empty-state">아직 Redis 작업 기록이 없습니다.</div>
        ) : (
          sortedOperations.map((operation) => (
            <div
              key={operation.id}
              className={`worker-entry worker-entry-${operation.status}`}
            >
              <div className="worker-entry-top">
                <strong>
                  {operation.userId} {operation.command}
                </strong>
                <span className="worker-status-pill">{operation.status}</span>
              </div>
              <div className="worker-entry-meta">
                <span>{operation.seatId ?? "-"}</span>
                <span>{formatAge(operation.updatedAt)}</span>
              </div>
              {operation.note ? (
                <div className="worker-entry-note">{operation.note}</div>
              ) : null}
            </div>
          ))
        )}
      </div>
    </section>
  );
}
