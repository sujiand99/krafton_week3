function SeatTile({ seat, onClick, isBusy, isSelectedUser }) {
  return (
    <button
      type="button"
      className={[
        "seat-tile",
        `seat-${seat.status}`,
        isSelectedUser ? "seat-owned" : "",
        isBusy ? "seat-busy" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      onClick={() => onClick(seat)}
      disabled={isBusy}
    >
      <div className="seat-tile-header">
        <strong>{seat.seatId}</strong>
        {seat.status === "held" && seat.ttl !== null ? (
          <span className="seat-ttl-badge">{seat.ttl}s</span>
        ) : null}
      </div>
      <div className="seat-tile-body">
        <span className="seat-status-label">{seat.status.toUpperCase()}</span>
        <span className="seat-owner-label">
          {seat.userId ? seat.userId : "open"}
        </span>
      </div>
    </button>
  );
}

function StatusLegend({ counts }) {
  return (
    <div className="seat-legend">
      <div className="legend-item">
        <span className="legend-swatch legend-available" />
        <span>Available {counts.available}</span>
      </div>
      <div className="legend-item">
        <span className="legend-swatch legend-held" />
        <span>Held {counts.held}</span>
      </div>
      <div className="legend-item">
        <span className="legend-swatch legend-confirmed" />
        <span>Confirmed {counts.confirmed}</span>
      </div>
    </div>
  );
}

export default function SeatGrid({
  seats,
  counts,
  selectedUser,
  onSeatClick,
  busySeatId,
  bookingStarted,
}) {
  const groupedSeats = seats.reduce((rows, seat) => {
    if (!rows[seat.rowLabel]) {
      rows[seat.rowLabel] = [];
    }

    rows[seat.rowLabel].push(seat);
    return rows;
  }, {});

  return (
    <section className="card seat-grid-card">
      <div className="card-header">
        <div>
          <p className="eyebrow">Seat Map</p>
          <h2>Seat hold status</h2>
        </div>
        <StatusLegend counts={counts} />
      </div>

      <p className="card-description">
        Clicking a seat sends `RESERVE_SEAT` for the selected user.
        {bookingStarted
          ? " Duplicate seat holds will fail and appear in the log."
          : " Before booking starts, clicks are blocked for demo clarity."}
      </p>

      <div className="seat-grid-rows">
        {Object.entries(groupedSeats).map(([rowLabel, rowSeats]) => (
          <div key={rowLabel} className="seat-row">
            <div className="seat-row-label">{rowLabel} ROW</div>
            <div className="seat-grid-scroll">
              <div
                className="seat-grid"
                style={{ "--seat-columns": rowSeats.length }}
              >
                {[...rowSeats]
                  .sort((left, right) => left.seatNumber - right.seatNumber)
                  .map((seat) => (
                    <SeatTile
                      key={seat.seatId}
                      seat={seat}
                      onClick={onSeatClick}
                      isBusy={busySeatId === seat.seatId}
                      isSelectedUser={seat.userId === selectedUser}
                    />
                  ))}
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
