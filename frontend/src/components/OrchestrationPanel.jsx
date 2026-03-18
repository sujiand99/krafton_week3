function formatAge(timestamp) {
  const delta = Math.max(
    0,
    Math.floor((Date.now() - new Date(timestamp).getTime()) / 1000),
  );
  return `${delta}s ago`;
}

export default function OrchestrationPanel({
  entries,
  onClear,
  isClearing = false,
}) {
  const sortedEntries = [...entries].sort(
    (left, right) =>
      new Date(right.timestamp).getTime() - new Date(left.timestamp).getTime(),
  );

  return (
    <section className="card orchestration-panel-card">
      <div className="card-header">
        <div>
          <p className="eyebrow">Service Flow</p>
          <h2>Redis / DB 오케스트레이션</h2>
          <p className="card-description">
            앱 서버가 Redis와 DB를 어떤 순서로 호출했는지 보여줍니다.
          </p>
        </div>
        <div className="worker-badges">
          <span className="subtle-badge">{sortedEntries.length} entries</span>
          <button
            type="button"
            className="action-button action-secondary compact-button"
            onClick={onClear}
            disabled={isClearing}
          >
            Clear flow
          </button>
        </div>
      </div>

      <div className="orchestration-list">
        {sortedEntries.length === 0 ? (
          <div className="empty-state">아직 오케스트레이션 로그가 없습니다.</div>
        ) : (
          sortedEntries.map((entry) => (
            <div
              key={`${entry.timestamp}-${entry.action}-${entry.seatId ?? "na"}`}
              className={`orchestration-entry orchestration-${String(entry.status).toLowerCase()}`}
            >
              <div className="orchestration-top">
                <strong>
                  {entry.source} -&gt; {entry.target} {entry.action}
                </strong>
                <span className="orchestration-status-pill">{entry.status}</span>
              </div>
              <div className="orchestration-meta">
                <span>
                  {entry.userId ?? "-"} / {entry.seatId ?? "-"}
                </span>
                <span>{formatAge(entry.timestamp)}</span>
              </div>
              {entry.detail ? (
                <div className="orchestration-detail">{entry.detail}</div>
              ) : null}
            </div>
          ))
        )}
      </div>
    </section>
  );
}
