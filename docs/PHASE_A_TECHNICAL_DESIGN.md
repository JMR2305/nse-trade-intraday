# NSE Trader Intraday — Phase A Technical Design

**Version:** 1.0  
**Date:** 2026-07-18  
**Status:** Documentation Only — No code modified  
**Prerequisite:** Phase 0 Isolation Checklist fully signed off  

---

## Phase A Objective

Build the infrastructure foundation that all later phases depend on. After Phase A:

- The intraday database schema exists and is seeded.
- A persistent Python FastAPI engine receives live Kite WebSocket ticks.
- One-minute bars are built in real time and persisted to PostgreSQL immediately.
- A Node.js WebSocket server pushes real-time updates to the dashboard.
- A health-check system reports the state of every component.
- A recovery manager restores full session state after any restart.
- A watchdog foundation monitors the engine and escalates failures.
- A reconciliation framework detects fill gaps across restarts.
- All hot-path intraday state is in PostgreSQL — no JSON flat files.

Phase A contains **no signal generation, no strategy logic, and no paper trading**. It is exclusively infrastructure.

---

## Document Conventions

| Marker | Meaning |
|---|---|
| `[OBSERVED]` | Directly confirmed by reading existing code |
| `[PROPOSED]` | Design decision — not yet implemented |
| `[ABSENT]` | Confirmed absent from existing codebase |
| `[REUSE]` | Existing module can be reused as-is |
| `[MODIFY]` | Existing module must be modified for intraday use |
| `[NEW]` | New module — does not exist anywhere in the codebase |

---

## Phase A Task Breakdown

### Task A-1: Database Schema

**Description:** Create the PostgreSQL schema for all Phase A tables. Later phases extend this schema without modifying Phase A tables.

**Dependencies:** Phase 0 isolation checklist complete; intraday PostgreSQL database accessible.

**Tables to create in Phase A:**

| Table | Phase A Use |
|---|---|
| `intraday_sessions` | Session management and recovery anchor |
| `minute_ohlcv_cache` | Persisted 1-min bars — primary bar history |
| `intraday_tick_summaries` | Per-second tick snapshots (7-day rolling) |
| `system_heartbeats` | Watchdog and component health records |
| `reconciliation_events` | Fill-gap and position mismatch records |
| `intraday_incidents` | Incident records (square-off failures, watchdog failures) |
| `intraday_alert_deliveries` | Alert queue (idempotent, retry-capable) |
| `intraday_audit_logs` | Append-only audit trail |
| `intraday_kite_tokens` | Kite access token storage (separate from Swing) |

**Tables deferred to later phases:**

`feature_snapshots`, `intraday_signals`, `strategy_decisions`, `intraday_paper_orders`, `intraday_paper_fills`, `intraday_positions`, `position_monitor_events`, `risk_snapshots`, `model_predictions`, `calibration_predictions`, `intraday_push_subscriptions`, `intraday_incidents` (extended in Phase D).

**Schema definitions** (for implementation — do not create until Phase A begins):

```sql
-- intraday_sessions
CREATE TABLE intraday_sessions (
    session_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date         DATE NOT NULL UNIQUE,
    status       TEXT NOT NULL DEFAULT 'PRE_OPEN'
                   CHECK (status IN ('PRE_OPEN','OPEN','CLOSED','INCIDENT')),
    open_ts      TIMESTAMPTZ,
    close_ts     TIMESTAMPTZ,
    regime       TEXT,
    session_capital  NUMERIC(15,2) NOT NULL DEFAULT 0,
    realized_pnl     NUMERIC(15,2) NOT NULL DEFAULT 0,
    risk_used_pct    NUMERIC(5,4) NOT NULL DEFAULT 0,
    square_off_completed BOOLEAN NOT NULL DEFAULT false,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON intraday_sessions (status);

-- minute_ohlcv_cache
CREATE TABLE minute_ohlcv_cache (
    id           BIGSERIAL PRIMARY KEY,
    session_id   UUID NOT NULL REFERENCES intraday_sessions(session_id),
    symbol       TEXT NOT NULL,
    bar_ts       TIMESTAMPTZ NOT NULL,
    open         NUMERIC(10,2) NOT NULL,
    high         NUMERIC(10,2) NOT NULL,
    low          NUMERIC(10,2) NOT NULL,
    close        NUMERIC(10,2) NOT NULL,
    volume       BIGINT NOT NULL DEFAULT 0,
    vwap         NUMERIC(10,4),
    is_gap_bar   BOOLEAN NOT NULL DEFAULT false,
    UNIQUE (session_id, symbol, bar_ts)
);
CREATE INDEX ON minute_ohlcv_cache (symbol, bar_ts DESC);

-- intraday_tick_summaries
CREATE TABLE intraday_tick_summaries (
    id           BIGSERIAL PRIMARY KEY,
    session_id   UUID NOT NULL REFERENCES intraday_sessions(session_id),
    symbol       TEXT NOT NULL,
    ts           TIMESTAMPTZ NOT NULL,
    ltp          NUMERIC(10,2),
    bid          NUMERIC(10,2),
    ask          NUMERIC(10,2),
    volume_traded BIGINT
);
CREATE INDEX ON intraday_tick_summaries (session_id, symbol, ts);

-- system_heartbeats
CREATE TABLE system_heartbeats (
    id           BIGSERIAL PRIMARY KEY,
    component    TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('HEALTHY','DEGRADED','DOWN')),
    details      JSONB,
    ts           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON system_heartbeats (component, ts DESC);

-- reconciliation_events
CREATE TABLE reconciliation_events (
    id           BIGSERIAL PRIMARY KEY,
    session_id   UUID NOT NULL REFERENCES intraday_sessions(session_id),
    position_id  UUID,  -- FK added in Phase D when intraday_positions exists
    event_type   TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'NEEDS_REVIEW'
                   CHECK (status IN ('NEEDS_REVIEW','RESOLVED_AUTO','RESOLVED_MANUAL')),
    details      JSONB,
    detected_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at  TIMESTAMPTZ
);
CREATE INDEX ON reconciliation_events (session_id, status);

-- intraday_incidents
CREATE TABLE intraday_incidents (
    incident_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id   UUID NOT NULL REFERENCES intraday_sessions(session_id),
    kind         TEXT NOT NULL,
    severity     TEXT NOT NULL DEFAULT 'INCIDENT',
    description  TEXT NOT NULL,
    auto_action_taken TEXT,
    status       TEXT NOT NULL DEFAULT 'OPEN'
                   CHECK (status IN ('OPEN','ACKNOWLEDGED','RESOLVED')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at  TIMESTAMPTZ
);
CREATE INDEX ON intraday_incidents (session_id, status);

-- intraday_alert_deliveries
CREATE TABLE intraday_alert_deliveries (
    id               BIGSERIAL PRIMARY KEY,
    idempotency_key  TEXT NOT NULL UNIQUE,
    session_id       UUID REFERENCES intraday_sessions(session_id),
    kind             TEXT NOT NULL,
    severity         TEXT NOT NULL CHECK (severity IN ('INFO','WARNING','CRITICAL','INCIDENT')),
    symbol           TEXT,
    message          TEXT NOT NULL,
    channel          TEXT NOT NULL CHECK (channel IN ('PUSH','EMAIL','LOG')),
    status           TEXT NOT NULL DEFAULT 'PENDING'
                       CHECK (status IN ('PENDING','DELIVERED','FAILED','DEAD_LETTER')),
    attempts         INT NOT NULL DEFAULT 0,
    next_retry_at    TIMESTAMPTZ,
    delivered_at     TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON intraday_alert_deliveries (status, next_retry_at);
CREATE INDEX ON intraday_alert_deliveries (session_id);

-- intraday_audit_logs (append-only)
CREATE TABLE intraday_audit_logs (
    id           BIGSERIAL PRIMARY KEY,
    session_id   UUID REFERENCES intraday_sessions(session_id),
    event_type   TEXT NOT NULL,
    actor        TEXT NOT NULL DEFAULT 'system',
    entity_type  TEXT,
    entity_id    TEXT,
    payload      JSONB NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON intraday_audit_logs (session_id, created_at DESC);
CREATE INDEX ON intraday_audit_logs (entity_type, entity_id);

-- intraday_kite_tokens
CREATE TABLE intraday_kite_tokens (
    id              BIGSERIAL PRIMARY KEY,
    access_token    TEXT NOT NULL,
    api_key         TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ,
    is_valid        BOOLEAN NOT NULL DEFAULT true,
    validated_at    TIMESTAMPTZ
);
CREATE INDEX ON intraday_kite_tokens (is_valid, created_at DESC);
```

**Acceptance tests:**

- All tables created without errors on a fresh intraday database.
- `UNIQUE (date)` on `intraday_sessions` prevents duplicate session creation.
- `UNIQUE (session_id, symbol, bar_ts)` on `minute_ohlcv_cache` prevents duplicate bars.
- `UNIQUE (idempotency_key)` on `intraday_alert_deliveries` prevents duplicate alerts.
- All foreign keys enforce referential integrity.
- `CHECK` constraints reject invalid status values.

**Failure tests:**

- Attempt to insert a second `intraday_sessions` row with the same `date` — must fail with UNIQUE constraint.
- Attempt to insert a duplicate bar — must fail.
- Attempt to insert an `intraday_alert_deliveries` row with `severity = 'UNKNOWN'` — must fail with CHECK constraint.

**Completion gate:** All tables exist in the intraday database; all acceptance and failure tests pass; no Swing tables have been modified.

**Estimated effort:** 1–2 days

---

### Task A-2: Persistent Python FastAPI Engine

**Description:** Replace the per-request `child_process.spawn` pattern `[OBSERVED]` with a long-running FastAPI process for the intraday engine. The swing platform's per-request Python spawn must remain completely untouched.

**Dependencies:** Task A-1 (database must exist for startup checks).

**New module:** `intraday_engine/main.py`

**Architecture:**

```
artifacts/api-server/
├── src/
│   ├── routes/                      ← existing Swing routes (untouched)
│   └── intraday/
│       └── routes/                  ← NEW: Intraday Node.js routes
│           ├── health.ts
│           ├── session.ts
│           └── ws.ts
│
└── intraday_engine/                 ← NEW: Persistent Python FastAPI process
    ├── main.py                      ← FastAPI app entry point
    ├── config.py                    ← Intraday configuration (separate from Swing config.py)
    ├── db.py                        ← Intraday DB connection (uses INTRADAY_DATABASE_URL)
    ├── session_store.py             ← Layer 5: Session management
    ├── ws_ingestion.py              ← Layer 2: KiteTicker ingestion (Phase A stub)
    ├── tick_normalizer.py           ← Layer 3: Tick normalization (Phase A stub)
    ├── bar_builder.py               ← Layer 4: 1-min bar construction
    ├── recovery_manager.py          ← Mid-session recovery (§4 of MASTER_ARCHITECTURE.md)
    ├── watchdog.py                  ← Layer 20: Watchdog foundation
    ├── reconciliation.py            ← Reconciliation framework
    ├── alert_manager.py             ← Layer 21: Alert creation
    └── audit.py                     ← Layer 22: Audit log writer
```

**Key design decisions:**

1. **Port:** The FastAPI engine binds to `localhost:8001` (not exposed externally). The Node.js API proxies relevant endpoints.
2. **Database connection:** Reads `INTRADAY_DATABASE_URL` exclusively. Never reads `DATABASE_URL`.
3. **Config separation:** `intraday_engine/config.py` is a new file. It must not import from or reference `artifacts/api-server/src/python/config.py` (the Swing config).
4. **Startup check:** On startup, the engine verifies that its database URL is different from the Swing `DATABASE_URL` (if both are visible in the environment) and logs a warning if they match.

**FastAPI app structure (proposed):**

```python
# intraday_engine/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
import asyncio

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await db.connect()
    await session_store.load_or_create_today()
    await recovery_manager.run()
    asyncio.create_task(watchdog.run())
    asyncio.create_task(bar_builder.run())
    # WebSocket ingestion starts as a background task (Phase A: stub)
    asyncio.create_task(ws_ingestion.run())
    yield
    # Shutdown
    await ws_ingestion.disconnect()
    await db.close()

app = FastAPI(lifespan=lifespan)

@app.get("/health")
async def health():
    return await watchdog.get_health_snapshot()

@app.get("/session")
async def get_session():
    return await session_store.get_current_session()

@app.get("/bars/{symbol}")
async def get_bars(symbol: str, limit: int = 50):
    return await bar_builder.get_latest_bars(symbol, limit)
```

**Node.js integration (proposed):**

The Node.js API server adds a new route file `src/intraday/routes/session.ts` that proxies requests to `http://localhost:8001/`. This route is separate from all existing Swing routes.

```typescript
// src/intraday/routes/session.ts  (NEW FILE)
import { Router } from "express";
const INTRADAY_ENGINE_URL = "http://localhost:8001";

export const intradaySessionRouter = Router();

intradaySessionRouter.get("/health", async (req, res) => {
  const resp = await fetch(`${INTRADAY_ENGINE_URL}/health`);
  res.json(await resp.json());
});
```

**Process management:**

The FastAPI process is started as a separate Replit workflow:

```toml
# In artifact.toml (Intraday repl only — not the Swing repl)
[workflows.intraday-engine]
name = "Intraday Engine"
command = "cd intraday_engine && uvicorn main:app --host 127.0.0.1 --port 8001 --reload"
```

**Acceptance tests:**

- `GET http://localhost:8001/health` returns `{"status": "HEALTHY"}` within 5s of startup.
- The engine logs `"connected to intraday database"` on startup (not the Swing DB).
- The engine creates an `intraday_sessions` row for today if one does not exist.
- The engine loads the existing `intraday_sessions` row if today's session already exists.
- Node.js `GET /intraday/api/v1/health` proxies to FastAPI and returns the same health response.

**Failure tests:**

- Start the engine with `INTRADAY_DATABASE_URL` pointing to an invalid host — engine must not start; must log a clear error and exit with a non-zero code.
- Stop the FastAPI process — Node.js health endpoint must return `{"status": "ENGINE_UNREACHABLE"}` within 10s, not a 500 error.

**Completion gate:** FastAPI process starts cleanly; health endpoints respond; database connection is confirmed to the intraday database; no Swing code has been touched.

**Estimated effort:** 3–4 days

---

### Task A-3: Kite WebSocket Ingestion

**Description:** Implement a persistent `KiteTicker` WebSocket connection within the FastAPI engine. In Phase A, this is a data ingestion layer only — no signals are generated from ticks.

**Dependencies:** Task A-2 (FastAPI engine running); intraday Kite token available in `intraday_kite_tokens` table.

**New module:** `intraday_engine/ws_ingestion.py`

**Key design decisions:**

1. **Single connection:** One KiteTicker instance per engine process. All symbol subscriptions share the same WebSocket connection.
2. **Token source:** The WS ingestion reads access tokens from `intraday_kite_tokens` only. It never touches the Swing `kite_token_store.py` `[OBSERVED]`.
3. **Subscription list:** Phase A subscribes to a hardcoded test symbol list (e.g., `["RELIANCE", "INFY", "TCS"]`) to validate the pipeline. Configurable subscription management is a Phase B concern.
4. **Reconnect behavior:** Exponential backoff (1s, 2s, 4s, 8s … cap 60s). After 20 consecutive reconnect failures in one session, escalate to INCIDENT.
5. **Tick queue:** Normalized ticks are placed in a bounded `asyncio.Queue(maxsize=10000)`. If the queue is full, the oldest tick is dropped and a counter is incremented.

**Implementation outline:**

```python
# intraday_engine/ws_ingestion.py
from kiteconnect import KiteTicker
import asyncio

class WsIngestionService:
    def __init__(self, token_store, tick_queue: asyncio.Queue):
        self.token_store = token_store
        self.tick_queue = tick_queue
        self.ticker: KiteTicker | None = None
        self.reconnect_count = 0
        self.is_connected = False

    async def run(self):
        """Background task — runs for the lifetime of the session."""
        while True:
            try:
                await self._connect()
            except Exception as e:
                self.is_connected = False
                delay = min(2 ** self.reconnect_count, 60)
                self.reconnect_count += 1
                if self.reconnect_count > 20:
                    await alert_manager.emit_incident("WS_RECONNECT_LIMIT", str(e))
                    return
                await asyncio.sleep(delay)

    def _on_ticks(self, ws, ticks):
        """Called by KiteTicker in a thread — must be thread-safe."""
        for tick in ticks:
            try:
                self.tick_queue.put_nowait(tick)
            except asyncio.QueueFull:
                # Drop oldest tick
                self.tick_queue.get_nowait()
                self.tick_queue.put_nowait(tick)

    async def get_status(self) -> dict:
        return {
            "connected": self.is_connected,
            "reconnect_count": self.reconnect_count,
            "queue_depth": self.tick_queue.qsize(),
        }
```

**Acceptance tests:**

- On startup with a valid Kite access token, the WebSocket connects and `is_connected` becomes `True` within 10s.
- On receiving ticks, the tick queue depth increases.
- The health endpoint reports `ws_state: "CONNECTED"` with `last_tick_age_ms` ≤ 5000 during market hours.
- The watchdog emits a WARNING if no tick is received within 30s for a subscribed symbol.

**Failure tests:**

- Start with an expired access token — the engine must emit a WARNING and enter SAFE_MODE (not crash).
- Simulate a network drop (disconnect KiteTicker manually) — the engine must attempt reconnect with backoff; health endpoint must report `ws_state: "RECONNECTING"`.
- Fill the tick queue to capacity — the engine must drop the oldest tick (not crash) and increment a `ticks_dropped` counter visible in the health response.
- After 20 reconnect failures, the engine must emit an INCIDENT and stop reconnect attempts.

**Completion gate:** WS ingestion connects to Kite during market hours; ticks flow into the queue; reconnect logic verified with a simulated disconnect; watchdog reports WS state correctly.

**Estimated effort:** 3–4 days

---

### Task A-4: One-Minute Bar Builder

**Description:** Consume ticks from the WS ingestion queue. Aggregate them into 1-minute OHLCV bars per symbol. Persist each completed bar to `minute_ohlcv_cache` immediately upon completion. Reset all state at 09:15:00 IST at the start of each session.

**Dependencies:** Task A-3 (tick queue available); Task A-1 (database table exists).

**New module:** `intraday_engine/bar_builder.py`

**Key design decisions:**

1. **Bar boundary:** Each bar covers `[bar_ts, bar_ts + 60s)`. The first bar of the session starts at 09:15:00 IST exactly.
2. **Persistence timing:** A completed bar is written to `minute_ohlcv_cache` within the same async iteration that closes the bar. Not batched.
3. **Session reset:** At 09:15:00 IST, all in-progress bar accumulators are discarded and the VWAP numerator/denominator reset to 0. Any partial bar accumulated before 09:15 is discarded.
4. **Gap bar handling:** If no tick is received for a symbol within a 1-minute window during market hours, a `GAP_BAR` is synthesized using the last known close as OHLC, with `volume = 0` and `is_gap_bar = true`.
5. **VWAP accumulation:** The bar builder maintains a running session VWAP numerator and denominator per symbol. Each completed bar's `vwap` field reflects the session VWAP at bar close (not the bar's own VWAP).
6. **Recovery hook:** On startup, the bar builder reads the last complete bar per symbol from `minute_ohlcv_cache` for the current session and resumes from there.

**Tick processing loop:**

```python
async def run(self):
    """Consumes ticks and emits completed bars."""
    while True:
        tick = await self.tick_queue.get()
        normalized = self.normalizer.normalize(tick)
        if normalized is None:
            continue
        
        bar = self.accumulators[normalized.symbol]
        bar.update(normalized)
        
        if bar.is_complete(now=normalized.timestamp):
            completed = bar.finalize()
            await self.db.persist_bar(completed)
            self.completed_bar_queue.put_nowait(completed)
            bar.reset(next_bar_ts=completed.bar_ts + timedelta(minutes=1))
```

**Acceptance tests:**

- After receiving 5+ ticks for a symbol within a 1-minute window, a completed bar is written to `minute_ohlcv_cache` at bar close.
- The bar's `open`, `high`, `low`, `close`, `volume` correctly reflect the ticks received.
- The bar's `vwap` reflects the session-cumulative VWAP (not just the bar's own VWAP).
- On session start (09:15:00 IST), all VWAP accumulators reset to 0.
- A symbol that receives no ticks in a 1-minute window during market hours generates a `GAP_BAR` row.
- On engine restart mid-session, the bar builder correctly identifies the last complete bar from `minute_ohlcv_cache` and does not duplicate it.

**Failure tests:**

- Receive a tick with an unrecognised instrument token — must log a warning and skip; must not crash.
- Receive a tick with a timestamp before the session start — must discard.
- Receive a tick with an out-of-order timestamp (older than current bar) — must include in current bar if within same minute; discard otherwise.
- Database write fails for one bar — must log the error, continue processing subsequent ticks, and retry the failed write on the next bar.

**Completion gate:** Bars flow from ticks to `minute_ohlcv_cache` within 1 minute of bar close; session reset verified at 09:15; gap bar generation verified; restart recovery verified.

**Estimated effort:** 3–4 days

---

### Task A-5: Immediate Persistence Guarantee

**Description:** Ensure that every completed bar is written to PostgreSQL before the bar's data is used by any downstream consumer. This is the enforcement mechanism for the "no JSON flat files" requirement.

**Dependencies:** Task A-4 (bar builder); Task A-1 (database).

**Design:**

1. **Write-before-publish:** The bar builder writes the bar to `minute_ohlcv_cache` and awaits the database write before placing the bar on the `completed_bar_queue` for downstream consumers.
2. **Write confirmation:** Use `INSERT … ON CONFLICT DO NOTHING RETURNING id`. If `id` is returned, the write succeeded. If no row returned (conflict), the bar was already persisted (idempotent on restart).
3. **Retry on transient failure:** If the DB write raises a transient error (connection drop), retry up to 3 times with 100ms backoff. If all 3 retries fail, emit a WARNING alert and continue (do not block the bar pipeline — accept the data loss and log it).
4. **No JSON state:** No `paper_portfolio.json`, `watchlist.json`, or other flat-file fallback may be created by the intraday engine. Any module that uses these patterns in the Swing engine must not be imported.

**Acceptance tests:**

- Kill the engine process immediately after a bar completes but before it is consumed downstream — on restart, the bar must be present in `minute_ohlcv_cache`.
- Verify `ON CONFLICT DO NOTHING` prevents duplicate bars on restart recovery.

**Failure tests:**

- Simulate a database connection drop during a bar write — the retry logic must attempt 3 retries; after 3 failures, a WARNING alert must be emitted.

**Completion gate:** Bar data survives an engine restart without loss; no JSON files are written by the intraday engine.

**Estimated effort:** 1 day (integrated with A-4)

---

### Task A-6: Node.js WebSocket Server

**Description:** Add a WebSocket server to the Node.js API to push real-time updates from the FastAPI engine to connected dashboard clients.

**Dependencies:** Task A-2 (FastAPI engine running and exposing an SSE or WebSocket stream).

**New files:**
- `src/intraday/ws-server.ts` — WebSocket server setup
- `src/intraday/engine-bridge.ts` — Polls or subscribes to FastAPI for state changes

**Design:**

1. **Transport (v1):** The Node.js WebSocket server polls the FastAPI engine's internal state endpoints every 1–5 seconds (polling interval depends on data type) and broadcasts updates to connected clients. This is simpler than a Redis pub/sub bridge and sufficient for v1.
2. **Client endpoint:** `ws://[host]/intraday/ws`
3. **Message types:**

| Event Type | Source | Rate |
|---|---|---|
| `session_update` | FastAPI `/session` | Every 5s |
| `health_update` | FastAPI `/health` | Every 5s |
| `bar_update` | FastAPI `/bars/{symbol}` | On bar completion (1 min) |
| `ws_state_update` | FastAPI `/health` | Every 1s during WS reconnect |

4. **Client reconnect:** Dashboard clients reconnect with exponential backoff if the WebSocket closes. A stale-data indicator appears if no message is received for > 5s.
5. **Authentication:** In Phase A, WebSocket connections are not authenticated (internal use only). Authentication is added in Phase G.

**Acceptance tests:**

- A WebSocket client connects to `/intraday/ws` and receives a `session_update` message within 10s of connection.
- When a new bar is completed, a `bar_update` message is broadcast to all connected clients within 2s.
- When the FastAPI engine is stopped, all WebSocket clients receive a `health_update` with `engine_status: "UNREACHABLE"` within 10s.
- Multiple simultaneous WebSocket clients all receive the same messages.

**Failure tests:**

- Stop the FastAPI engine — Node.js WebSocket server must continue running; clients must receive degraded health status (not disconnect).
- Client disconnects unexpectedly — server must clean up the client without crashing.
- Client sends an unexpected message — server must ignore it and continue.

**Completion gate:** WebSocket server starts with the Node.js process; clients receive session and health updates; bar updates are broadcast on completion.

**Estimated effort:** 2–3 days

---

### Task A-7: Health-Check System

**Description:** Define and implement health-check endpoints for every component introduced in Phase A.

**Dependencies:** Tasks A-2, A-3, A-4, A-6.

**Health endpoint specifications:**

#### FastAPI: `GET http://localhost:8001/health`

```json
{
  "status": "HEALTHY | DEGRADED | DOWN",
  "session_id": "uuid",
  "session_status": "OPEN | CLOSED | PRE_OPEN",
  "ws": {
    "state": "CONNECTED | DISCONNECTED | RECONNECTING",
    "reconnect_count": 0,
    "last_tick_age_ms": 1234,
    "queue_depth": 42,
    "ticks_dropped": 0
  },
  "bar_builder": {
    "last_bar_age_s": 45,
    "bars_persisted_today": 3456,
    "active_symbols": 3
  },
  "db": {
    "connected": true,
    "latency_ms": 5
  },
  "watchdog": {
    "last_heartbeat_age_s": 12
  },
  "latency_p95_ms": {
    "tick_to_normalize": 8,
    "bar_to_persist": 45
  }
}
```

**Status aggregation rules:**
- `HEALTHY`: All components reporting normally; last tick age < 30s; last bar age < 90s
- `DEGRADED`: Any component in warning state; last tick age 30–120s
- `DOWN`: DB disconnected; WS disconnected for > 120s; bar builder stopped

#### Node.js: `GET /intraday/api/v1/health`

Proxies to FastAPI health endpoint. On FastAPI unreachability, returns:

```json
{
  "status": "ENGINE_UNREACHABLE",
  "node_api": "HEALTHY",
  "engine": null,
  "error": "FastAPI engine did not respond within 5s"
}
```

**Acceptance tests:**

- During normal operation (market hours, WS connected, bars flowing), both health endpoints return `status: "HEALTHY"`.
- Disconnect the WS — health status transitions to `DEGRADED` within 30s.
- Stop the FastAPI engine — Node.js health endpoint returns `ENGINE_UNREACHABLE` within 10s.
- The `latency_p95_ms` fields update every minute with rolling P95 values.

**Failure tests:**

- The FastAPI health endpoint must respond even if the WS ingestion task is crashed (it must not depend on WS being healthy to return a response).
- The Node.js health endpoint must not propagate exceptions from FastAPI — it must return a safe error response.

**Completion gate:** Health endpoints respond at all times (even during partial failures); status transitions correctly with component state changes.

**Estimated effort:** 1–2 days (integrated with A-2 and A-3)

---

### Task A-8: Recovery Manager

**Description:** Implement the mid-session recovery procedure defined in §4 of MASTER_ARCHITECTURE.md. The recovery manager runs once on every FastAPI startup and restores full session context from PostgreSQL.

**Dependencies:** Tasks A-1, A-2 (database and FastAPI engine).

**New module:** `intraday_engine/recovery_manager.py`

**Recovery flow:**

```python
async def run(self):
    """
    Runs once at startup. Restores session state from PostgreSQL.
    """
    # Step 1: Load session
    session = await session_store.get_today()
    if session is None:
        if market_hours.is_market_hours():
            await alert_manager.emit_warning(
                "RECOVERY_NO_SESSION",
                "Engine started during market hours with no existing session"
            )
        session = await session_store.create_today()
    
    if session.status == 'INCIDENT':
        await self._enter_safe_mode("Session in INCIDENT status")
        return

    # Step 2: Restore bar builder state
    latest_bars = await db.get_latest_bars_per_symbol(session.session_id)
    await bar_builder.restore(latest_bars)

    # Step 3: Reconciliation (Phase A: checks for stale bars during downtime)
    await self._reconcile_downtime_gaps(session)

    # Step 4: Emit recovery audit event
    await audit.log("ENGINE_RECOVERED", {
        "session_id": str(session.session_id),
        "bars_restored": len(latest_bars),
    })
```

**Phase A reconciliation scope:**

In Phase A, the reconciliation framework only needs to handle bar gaps (missing bars during downtime). Position and order reconciliation is added in Phase D when `intraday_positions` and `intraday_paper_orders` exist.

**Gap detection logic:**

```
If engine is restarting during market hours:
  expected_bars_since_session_start = (now - 09:15) / 60 minutes
  actual_bars_in_db (per symbol) = COUNT from minute_ohlcv_cache
  if actual_bars_in_db < expected_bars_since_session_start - 2:
    emit WARNING: "Bar gap detected: expected {N}, found {M} for {symbol}"
    write reconciliation_event with event_type = 'BAR_GAP_DETECTED'
```

**Acceptance tests:**

- On a clean startup with no existing session, a new session row is created in `intraday_sessions`.
- On a startup with an existing session for today, the session is loaded (not a new one created).
- On a startup mid-session, the bar builder is initialized with the latest bars from `minute_ohlcv_cache`.
- If bars are missing (gap during downtime), a `reconciliation_events` row is written.
- If the session status is `INCIDENT`, the engine enters SAFE_MODE and does not create new sessions.

**Failure tests:**

- Startup with a corrupted `intraday_sessions` row (missing required fields) — engine must emit CRITICAL alert and enter SAFE_MODE; must not crash.
- Startup with an unreachable database — engine must not start; must log a clear error and exit.

**Completion gate:** Recovery manager runs on every startup; session context restored from DB; bar state reloaded; gap detection working; no Swing database access.

**Estimated effort:** 2–3 days

---

### Task A-9: Watchdog Foundation

**Description:** Implement the watchdog background task that monitors engine component health, writes heartbeats to `system_heartbeats`, and escalates failures.

**Dependencies:** Tasks A-2, A-3, A-4, A-7 (engine components to monitor).

**New module:** `intraday_engine/watchdog.py`

**Phase A scope:**

| Monitored dimension | Threshold | Escalation |
|---|---|---|
| Bar builder last bar age | WARNING > 90s; CRITICAL > 180s | Alert + health status |
| WS ingestion state | WARNING = RECONNECTING; CRITICAL = DISCONNECTED > 60s | Alert + health status |
| Last tick age (any subscribed symbol) | WARNING > 30s; CRITICAL > 120s | Alert per symbol |
| DB health probe (`SELECT 1`) | CRITICAL if fails | Alert + block entries |
| Watchdog's own heartbeat gap | INCIDENT > 45s gap in `system_heartbeats` | External process must detect this |
| FastAPI memory usage | WARNING > 500MB RSS | Alert |

**Heartbeat loop:**

```python
async def run(self):
    """Writes a heartbeat every 15s and checks all components."""
    while True:
        health = await self._check_all()
        await db.write_heartbeat("watchdog", health.status, health.details)
        
        for alert in health.alerts_to_emit:
            await alert_manager.emit(alert)
        
        await asyncio.sleep(15)
```

**Acceptance tests:**

- A `system_heartbeats` row with `component = "watchdog"` is written every 15 seconds during normal operation.
- When WS disconnects, the watchdog emits a WARNING alert within 30s and CRITICAL within 60s.
- When no bar is produced for 180s during market hours, the watchdog emits a CRITICAL alert.
- The `GET /health` endpoint reflects the watchdog's last assessment.

**Failure tests:**

- Simulate a DB connection drop — the watchdog must detect it within 30s (it will fail to write the heartbeat AND detect the health check failure); alert must be emitted.
- Crash the bar builder asyncio task — the watchdog must detect the absence of bar updates within 2 minutes and escalate.

**Completion gate:** Watchdog writes heartbeats every 15s; alerting verified for WS disconnect and bar stall; health endpoint reflects watchdog state.

**Estimated effort:** 2 days

---

### Task A-10: Reconciliation Framework

**Description:** Establish the reconciliation framework that detects and records state discrepancies. Phase A scope covers bar gaps and session state consistency. Position and order reconciliation is added in Phase D.

**Dependencies:** Tasks A-1, A-8 (recovery manager, database).

**New module:** `intraday_engine/reconciliation.py`

**Phase A reconciliation types:**

| Event Type | Trigger | Action |
|---|---|---|
| `BAR_GAP_DETECTED` | Missing bars during downtime | Write `reconciliation_events` row; emit WARNING |
| `SESSION_STATE_MISMATCH` | Session status in DB doesn't match computed state | Write row; emit CRITICAL; enter SAFE_MODE |
| `DB_CONNECTIVITY_RESTORED` | DB reconnected after failure | Write row; emit INFO; resume normal operation |

**Operator resolution flow:**

1. `NEEDS_REVIEW` items appear in the dashboard reconciliation panel.
2. Operator reviews each item and clicks Acknowledge or Resolve.
3. A PATCH to `/intraday/api/v1/reconciliation/{id}` updates `status` to `RESOLVED_MANUAL`.
4. Once all `NEEDS_REVIEW` items are resolved, the operator can exit SAFE_MODE.

**Acceptance tests:**

- Simulate a 5-minute engine downtime mid-session — on restart, `reconciliation_events` rows are written for each symbol with a bar gap.
- Verify `status` starts as `NEEDS_REVIEW` for all detected gaps.
- Update a reconciliation event to `RESOLVED_MANUAL` via the API — verify the DB row is updated.

**Failure tests:**

- Reconciliation query fails (DB error) — engine must enter SAFE_MODE; must not claim reconciliation is complete when it could not run.

**Completion gate:** Bar gap detection working; reconciliation events written on restart; API endpoint to resolve events; SAFE_MODE correctly entered when NEEDS_REVIEW items exist.

**Estimated effort:** 2 days

---

### Task A-11: Remove Intraday Hot-Path JSON State

**Description:** Ensure the Intraday engine never uses JSON flat files for state that is needed for recovery or decision-making. Audit and document any JSON file usage.

**Dependencies:** Task A-2 (engine structure established).

**Action:**

1. Confirm that `intraday_engine/` contains NO code that writes to:
   - `paper_portfolio.json`
   - `watchlist.json`
   - `phase11_kill_switch.json`
   - Any session or scan state JSON file

2. Confirm that `intraday_engine/config.py` does NOT reference the default watchlist from the Swing `config.py` `[OBSERVED]`.

3. For development convenience, a `symbols.json` configuration file for the test watchlist (Phase A hardcoded symbols) is acceptable, but it must be read-only (not written to at runtime) and must not be used as a recovery source.

4. Write a startup assertion in `intraday_engine/main.py`:

```python
import os
FORBIDDEN_STATE_FILES = [
    "paper_portfolio.json",
    "watchlist.json",
    "phase11_kill_switch.json",
]
for f in FORBIDDEN_STATE_FILES:
    if os.path.exists(f):
        logger.warning(f"Forbidden JSON state file found: {f} — intraday engine does not use this file")
```

**Acceptance tests:**

- Run the engine through a full test session — no JSON state files are created.
- The startup assertion logs a warning if any forbidden file exists in the working directory.

**Completion gate:** No JSON hot-path state files created by the intraday engine; startup assertion in place.

**Estimated effort:** 0.5 days (integrated with A-2)

---

## Phase A Dependency Graph

```
A-1 (Database Schema)
  └─ required by: A-2, A-4, A-6, A-8, A-9, A-10

A-2 (FastAPI Engine)
  └─ requires: A-1
  └─ required by: A-3, A-4, A-6, A-7, A-8, A-9, A-10, A-11

A-3 (Kite WS Ingestion)
  └─ requires: A-2
  └─ required by: A-4, A-7, A-9

A-4 (Bar Builder)
  └─ requires: A-2, A-3
  └─ required by: A-5, A-7, A-9

A-5 (Immediate Persistence)
  └─ requires: A-4 (integrated)
  └─ required by: A-8

A-6 (Node.js WebSocket Server)
  └─ requires: A-2
  └─ required by: A-7 (health broadcast)

A-7 (Health-Check System)
  └─ requires: A-2, A-3, A-4, A-6
  └─ required by: A-9

A-8 (Recovery Manager)
  └─ requires: A-1, A-2, A-5
  └─ required by: A-10

A-9 (Watchdog Foundation)
  └─ requires: A-2, A-3, A-4, A-7
  └─ required by: A-10

A-10 (Reconciliation Framework)
  └─ requires: A-1, A-8, A-9

A-11 (No JSON State)
  └─ requires: A-2 (integrated constraint)
```

**Recommended build order:** A-1 → A-2 → A-11 (constraint) → A-3 → A-4+A-5 → A-7 → A-6 → A-8 → A-9 → A-10

---

## Phase A Effort Summary

| Task | Description | Effort |
|---|---|---|
| A-1 | Database schema | 1–2 days |
| A-2 | FastAPI engine | 3–4 days |
| A-3 | Kite WS ingestion | 3–4 days |
| A-4 + A-5 | Bar builder + persistence | 3–4 days |
| A-6 | Node.js WebSocket server | 2–3 days |
| A-7 | Health-check system | 1–2 days |
| A-8 | Recovery manager | 2–3 days |
| A-9 | Watchdog foundation | 2 days |
| A-10 | Reconciliation framework | 2 days |
| A-11 | No JSON state constraint | 0.5 days |
| **Total** | | **19–26 days** |

---

## Phase A Completion Gate

Phase A is complete when ALL of the following are true:

1. All Phase A database tables exist in the intraday database with correct constraints and indexes.
2. The FastAPI engine starts cleanly; `GET /health` returns `HEALTHY` during market hours.
3. The Node.js WebSocket server starts and broadcasts updates to connected clients.
4. Kite WebSocket connection established; ticks flow to the bar builder for at least one live market session.
5. 1-minute bars are present in `minute_ohlcv_cache` for at least one full session.
6. Engine restart mid-session correctly restores session context and bar state from PostgreSQL.
7. Watchdog writes heartbeats every 15 seconds; alerts are emitted on WS disconnect.
8. Reconciliation framework detects and records bar gaps on restart.
9. No JSON hot-path state files created by the intraday engine.
10. No Swing source files have been modified (verify with `git diff` on the Swing branch).
11. No Swing database tables have been written (verify by comparing row counts before and after Phase A).
12. Phase 0 isolation checklist items 3.3.1, 4.1.3, 5.1.2 are now verifiable and pass.

---

## Phase A Risk Register

| Risk | Severity | Mitigation |
|---|---|---|
| Kite access token unavailable for testing during Phase A | High | Set up manual OAuth flow early (A-3 first task); test with a valid session token |
| yfinance 7-day limit means no historical 1-min bars for backtesting the bar builder | Medium | Use a short live test session during Phase A; bar correctness verified from live ticks |
| FastAPI asyncio and KiteTicker threading model conflict | High | KiteTicker runs on its own thread and communicates via `asyncio.Queue`; avoid shared mutable state |
| Node.js WebSocket polling frequency too aggressive | Medium | Start with 5s polling; profile after first live session |
| Recovery manager creates duplicate sessions on restart | High | `UNIQUE (date)` constraint on `intraday_sessions` prevents this; test explicitly |
| Phase A takes longer than estimated, blocking Phase B | Medium | Phase B (indicators) can begin in parallel with A-9 and A-10 if A-1 through A-5 are complete |

---

## Phase A Unresolved Items

| Item | Decision Needed | Owner |
|---|---|---|
| Kite account for intraday testing | Can the same Zerodha account be used for Phase A testing while the Swing platform is running? | Project owner |
| FastAPI Python version | Confirm Python version compatibility with `kiteconnect` SDK and `uvicorn` | Architecture |
| Node.js WebSocket library | `ws` library (already used in other Replit projects) vs. native Node.js `WebSocketServer` | Architecture |
| SSE vs. polling for FastAPI → Node.js bridge | Polling is simpler for Phase A; SSE reduces latency; decision can wait until A-6 | Architecture |
| Alert delivery channel in Phase A | Email requires API key setup; Phase A alerts can be log-only + push; full delivery in Phase G | Architecture |

---

*End of Phase A Technical Design*  
*Version 1.0 — July 18, 2026 — Documentation only. No code was modified.*
