export default function UserPanel({
  selectedUser,
  onUserChange,
  users,
  myHeldSeats,
  myConfirmedSeats,
  onConfirm,
  onRelease,
  isBusy,
}) {
  return (
    <section className="card user-panel-card">
      <div className="card-header">
        <div>
          <p className="eyebrow">Current User</p>
          <h2>User state</h2>
        </div>
        <span className="subtle-badge">
          active holds: {myHeldSeats.length}
        </span>
      </div>

      <div className="user-select-group">
        {users.map((userId) => (
          <button
            key={userId}
            type="button"
            className={[
              "user-chip",
              userId === selectedUser ? "user-chip-selected" : "",
            ]
              .filter(Boolean)
              .join(" ")}
            onClick={() => onUserChange(userId)}
          >
            {userId}
          </button>
        ))}
      </div>

      <div className="user-status-columns">
        <div>
          <h3>Seats I currently hold</h3>
          {myHeldSeats.length === 0 ? (
            <div className="empty-state compact">No active holds for this user.</div>
          ) : (
            <div className="user-seat-list">
              {myHeldSeats.map((seat) => (
                <div key={seat.seatId} className="user-seat-item">
                  <div>
                    <strong>{seat.seatId}</strong>
                    <div className="user-seat-meta">ttl {seat.ttl ?? "-"}s</div>
                  </div>
                  <div className="user-seat-actions">
                    <button
                      type="button"
                      className="action-button action-primary compact-button"
                      onClick={() => onConfirm(seat.seatId)}
                      disabled={isBusy}
                    >
                      CONFIRM
                    </button>
                    <button
                      type="button"
                      className="action-button action-secondary compact-button"
                      onClick={() => onRelease(seat.seatId)}
                      disabled={isBusy}
                    >
                      RELEASE
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div>
          <h3>Seats I confirmed</h3>
          {myConfirmedSeats.length === 0 ? (
            <div className="empty-state compact">No confirmed seats yet.</div>
          ) : (
            <div className="confirmed-seat-list">
              {myConfirmedSeats.map((seat) => (
                <div key={seat.seatId} className="confirmed-seat-pill">
                  {seat.seatId}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
