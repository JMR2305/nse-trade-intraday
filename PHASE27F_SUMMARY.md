# Phase 27F — System Readiness Dashboard

## Purpose
Answers one operator question deterministically: **"Is the system ready to
safely run the next/current paper trading session?"** — a single read-only
page that folds every canonical health source into a READY / WARNING /
BLOCKED / UNKNOWN verdict with per-check evidence and remediation.

## Components

### Backend — `phase27_readiness.py`
- `collect_inputs()` — fail-soft collection from **existing** canonical
  sources only (no new probes): `scan_state_store` (latest meta + DB
  durability), `market_hours`, `phase20_store` (scheduler health,
  settings, KV), `kite_session_manager` (cached probe,
  `force_probe=False`), `phase20_circuit_breaker`,
  `portfolio_snapshot.get_portfolio_health`, `observability_center`
  system health, `phase26c_store.latest_result("RECOVERY")`,
  `pipeline_events`, presence-only env flags, `config.PAPER_TRADING_MODE`.
  Every source failure is recorded in `_errors` and surfaced.
- Check builders across **10 domains**: Market & Data, Broker & Auth,
  Pipeline, Strategy & Risk, Execution, Portfolio, Persistence &
  Recovery, Scheduling, Safety Controls, Configuration. Each check
  record: `{id, domain, label, status, blocking, expected, actual,
  evidence, remediation, checked_at}`.
- **Deterministic fold** (`derive_overall`): any blocking BLOCKED →
  BLOCKED; else any blocking UNKNOWN → UNKNOWN (fail-safe — missing
  evidence never yields READY); else any non-READY anywhere → WARNING;
  else READY. Same fold applied per-domain.
- **Safety card**: PAPER mode verified; `LIVE_EXECUTION_ENABLED` /
  `AUTO_EXECUTION_ENABLED` / `LIVE_ORDERS_ENABLED` set → blocking
  BLOCKED. Circuit breaker tripped **or unreadable** → blocking BLOCKED
  (matches the executor's fail-safe). Secrets are presence-only.
- **Freshness section** reuses existing thresholds only:
  `phase13_intelligence.STALE_SCAN_MINUTES_MARKET_OPEN/CLOSED` and
  `phase26_recovery.HEARTBEAT_MAX_AGE_S` (heartbeat budget enforced in
  session only). No new thresholds defined.
- **Light history**: compact snapshots (`at/overall/counts/
  blocking_failures`) appended to the phase20 KV store, capped at 50.

### Commands — `main.py`
- `system_readiness_report` — full report (also records history).
- `system_readiness_history [limit]`.

### Routes — `routes/phase27.ts`
- `GET /api/system-readiness/report` — 30s cache + single-flight;
  `?force=true` bypasses the cache (read-only re-evaluation, no new
  probes — the Kite probe stays cached inside the session manager).
- `GET /api/system-readiness/history`.

### Frontend — `SystemReadiness.tsx` at `/system-readiness`
Overall banner (verdict + counts + market state + Run readiness check
button), source-error strip, 10 grouped domain cards with expandable
evidence per check, Data Freshness table, Check History card.
Registered in App.tsx and the Operations Agent nav group.

## Out of scope (respected)
No new probes; no trading actions; no heavy history subsystem; Phase 6.5
`/live-readiness` page untouched (27F is broader and complementary).

## Tests
`test_phase27_readiness.py` — 33 pure unit tests: overall fold rules,
missing-telemetry-never-READY per source, live-execution flag blocking,
breaker tripped/unreadable, staleness budgets open vs closed, scheduler
enum mapping (incl. DOWN in/off session), broker never blocking, recovery
verdict mapping, provider coverage, config/portfolio checks, freshness
budgets sourced from existing constants, report contract shape.

PAPER TRADING / RESEARCH ONLY — advisory, read-only.
