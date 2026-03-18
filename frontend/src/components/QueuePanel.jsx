export default function QueuePanel({
  queueEntries,
  queueLength,
  frontUserId,
  selectedUser,
  isBusy,
  onJoin,
  onPop,
  onLeave,
  onPeek,
  canPop,
}) {
  return (
    <section className="card queue-panel-card">
      <div className="card-header">
        <div>
          <p className="eyebrow">Queue</p>
          <h2>Queue panel</h2>
        </div>
        <div className="queue-badges">
          <span className="subtle-badge">front: {frontUserId ?? "-"}</span>
          <span className="subtle-badge">length: {queueLength}</span>
        </div>
      </div>

      <div className="queue-actions">
        <button
          type="button"
          className="action-button action-secondary"
          onClick={onJoin}
          disabled={isBusy}
        >
          JOIN_QUEUE
        </button>
        <button
          type="button"
          className="action-button action-secondary"
          onClick={onLeave}
          disabled={isBusy}
        >
          LEAVE_QUEUE
        </button>
        <button
          type="button"
          className="action-button action-secondary"
          onClick={onPeek}
          disabled={isBusy}
        >
          PEEK_QUEUE
        </button>
        <button
          type="button"
          className="action-button action-danger"
          onClick={onPop}
          disabled={isBusy || !canPop}
          title={
            canPop
              ? "Remove the current front user"
              : "Real API mode does not expose a pop endpoint yet"
          }
        >
          POP_QUEUE
        </button>
      </div>

      <div className="queue-note">
        Selected user: <strong>{selectedUser}</strong>
      </div>

      <div className="queue-list">
        {queueEntries.length === 0 ? (
          <div className="empty-state">Queue is empty.</div>
        ) : (
          queueEntries.map((entry) => (
            <div
              key={entry.userId}
              className={[
                "queue-entry",
                entry.userId === selectedUser ? "queue-entry-selected" : "",
              ]
                .filter(Boolean)
                .join(" ")}
            >
              <div>
                <strong>{entry.userId}</strong>
                <div className="queue-entry-subtext">
                  position {entry.position} / {entry.queueLength}
                </div>
              </div>
              <span className="queue-position-pill">#{entry.position}</span>
            </div>
          ))
        )}
      </div>

      {!canPop ? (
        <p className="queue-warning">
          `POP_QUEUE` is currently available only in mock mode. Real API mode
          still needs the backend endpoint.
        </p>
      ) : null}
    </section>
  );
}
