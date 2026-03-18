export default function LogPanel({ logs }) {
  return (
    <section className="card log-panel-card">
      <div className="card-header">
        <div>
          <p className="eyebrow">Activity Feed</p>
          <h2>Live log</h2>
        </div>
        <span className="subtle-badge">{logs.length} entries</span>
      </div>

      <div className="log-panel">
        {logs.length === 0 ? (
          <div className="empty-state">No log entries yet.</div>
        ) : (
          logs.map((log) => (
            <div key={log.id} className={`log-entry log-${log.kind}`}>
              {log.message}
            </div>
          ))
        )}
      </div>
    </section>
  );
}
