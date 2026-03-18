# Mini Redis Ticketing Demo Frontend

This React single-page app visualizes the Mini Redis ticketing demo.

What it shows clearly:

- `AVAILABLE / HELD / CONFIRMED` seat states
- per-seat TTL countdown for held seats
- duplicate hold failures on the same seat
- queue join / leave / peek / pop
- newest-first live log feed
- scripted multi-user simulation
- a `20 x 20` seat map (`400` seats total)

## Structure

```text
frontend/
|- index.html
|- package.json
|- vite.config.js
`- src/
   |- App.jsx
   |- index.css
   |- components/
   |- demo/
   `- services/
```

## Run

Node.js and npm are required.

```bash
cd frontend
npm install
npm run dev
```

Default mode is `mock`, so the demo works immediately even without backend connectivity.

## Mock Mode

Default behavior:

- seats and queue live entirely in browser memory
- TTL decreases through 1-second polling
- auto-simulation creates intentional collisions
- full queue demo including `POP_QUEUE`

No extra setup is needed.

## Real API Mode

Example `.env.local`:

```bash
VITE_API_MODE=real
VITE_APP_SERVER_BASE_URL=/api
VITE_DB_API_BASE_URL=/db-api
VITE_POLL_INTERVAL_MS=1000
VITE_DEFAULT_HOLD_SECONDS=15
```

Required servers before starting the frontend:

1. Mini Redis server
2. Ticketing DB API
3. Ticketing App Server

Example:

```bash
py -3.12 server/server.py --db-path data/mini_redis.db --snapshot-interval 5
py -3.12 -m uvicorn ticketing_api.app:app --host 127.0.0.1 --port 8001
py -3.12 -m uvicorn app_server.app:app --host 127.0.0.1 --port 8000
```

Then run the frontend:

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server uses these proxies:

- `/api` -> `http://127.0.0.1:8000`
- `/db-api` -> `http://127.0.0.1:8001`

## Real API Integration Points

Actual backend calls live in `src/services/api.js`.

Currently wired:

- seat fetch / hold / confirm / release
- queue join / leave / position / peek
- confirmed seat lookup

Still marked with `TODO`:

- `POP_QUEUE` in real API mode
- payload cleanup if hold or release endpoints change
- unifying confirmed seat lookup behind app server

## Demo Flow

1. Click `Start booking`
2. Switch between `user-1`, `user-2`, `user-3`
3. Click the same seat with multiple users to show collisions
4. Watch TTL count down on held seats
5. Use `CONFIRM` and `RELEASE`
6. Use `JOIN_QUEUE`, `PEEK_QUEUE`, `POP_QUEUE`
7. Run `Run simulation` for a full scripted demo

## High-Contention Backend Test

This repo also includes a Redis contention test for `400` seats and `20,000` total
seat-hold attempts (`50` contenders per seat):

```bash
py -3.12 -m pytest tests/test_high_contention.py -q -s
```
