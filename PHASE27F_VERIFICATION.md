# Phase 27F — Verification Report

Date: 2026-08-09 (Sunday — market closed; stale-scan warnings are the
environmentally correct behaviour, not defects).

## 1. Unit tests
```
cd artifacts/api-server/src/python && python -m pytest test_phase27_readiness.py -q
33 passed in 0.62s
```
Coverage highlights:
- Fold determinism: identical inputs → identical statuses and overall.
- Fail-safe: for each blocking source (`scan_meta`, `scheduler`,
  `settings`, `breaker`, `portfolio_health`, `env_flags`, `db_durable`),
  a collection failure yields UNKNOWN and the overall verdict is never
  READY.
- `LIVE_EXECUTION_ENABLED=true` or AUTO_EXECUTION/LIVE_ORDERS flags set →
  execution_mode BLOCKED (blocking) → overall BLOCKED.
- Circuit breaker tripped or unreadable → BLOCKED (matches executor
  fail-safe semantics).
- Scan staleness uses the market-open budget (90m) when open and the
  closed budget (720m) when closed — imported constants, not new ones.
- Scheduler enum mapping incl. DOWN → BLOCKED in session, WARNING off
  session; heartbeat budget (300s) enforced in session only.
- Broker checks are never blocking (paper trading needs no broker).
- Secrets presence-only: evidence contains no secret values.

## 2. Typecheck
`pnpm --filter trading-dashboard exec tsc --noEmit` and
`pnpm exec tsc -b lib/... artifacts/api-server` — both clean.

## 3. Live API verification (after api-server restart)
```
GET /api/system-readiness/report
overall=WARNING counts={READY:11, WARNING:3, BLOCKED:0, UNKNOWN:1}
domains: Market&Data WARNING (scan 24h old — weekend, closed budget
  exceeded), Broker WARNING (LOGIN_REQUIRED — expected on weekend),
  Pipeline READY, Strategy&Risk READY, Execution READY, Portfolio READY,
  Persistence&Recovery WARNING (recovery verdict), Scheduling READY,
  Safety Controls READY (paper mode, breaker clear), Configuration READY.

GET /api/system-readiness/history → ok, compact entries with
overall/counts/blocking_failures, newest first.
```
`?force=true` bypasses the 30s route cache and re-records history
(verified — second history entry appeared after forced run).

## 4. Browser verification
Screenshot of `/system-readiness`: overall WARNING banner with counts and
"Run readiness check" button; Market & Data card shows scan freshness
WARNING with BLOCKING tag, expected/actual/fix lines; provider coverage
UNKNOWN (older snapshot predates coverage fields — correct fail-safe);
Broker card WARNING with remediation; Pipeline/Strategy & Risk READY.
Nav entry appears in the Operations Agent group.

## 5. Regression
- Phase 27E operator analytics tests still pass (module untouched).
- Existing `/api/readiness/*` (Phase 6.5) routes untouched.
- No new thresholds, probes, or persistence subsystems introduced.

Verdict: Phase 27F requirements met. PAPER TRADING / RESEARCH ONLY.
