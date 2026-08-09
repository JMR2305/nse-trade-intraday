# Phase 27.1 Verification Report

Date: 2026-08-09 (weekend session — stale-scan/LOGIN_REQUIRED warnings are
environmental, expected outside market hours)

## Automated tests
- `test_phase27_1_operational_intelligence.py`: **19/19 PASS** (pure unit,
  constructed inputs, no I/O).
- `test_phase27_readiness.py`: **39/39 PASS** (unchanged behaviour after
  history-entry enrichment).
- Typecheck: `tsc -b lib/... artifacts/api-server` + trading-dashboard
  `tsc --noEmit` — clean.

## Live verification (dev server)
- `GET /api/operational-intelligence/report` → `ok: true`; all 5 sources
  available; executive readiness WARNING (stale weekend scan — correct);
  health score 85–88/100 with 19 components (10 readiness domains + 9
  pipeline stages).
- Checklist: 13 items; Market Data/Scanner/Portfolio/Broker Session WARNING
  with honest reasons + remediation; rest PASS; overall WARNING.
- Session comparison: today 48 stocks / 6 signals / 22.9s duration;
  yesterday + previous day show em-dashes for metadata the historical
  snapshots don't carry (never fabricated).
- Timeline: 6 evaluations recorded, 1 transition this session; pre-27.1
  entries lack `issues` so show "no issue detail recorded" (honest).
- Screenshot of `/operational-intelligence` verified: all 8 sections render,
  shortcuts row present on summary + timeline detail, responsive grid.

## Read-only / integrity checks
- Source-level test asserts the module never references mutators
  (`kv_set`, `add_notification`, `execute_buy/sell`, `place_order`,
  `run_scan`).
- Each source loader is fail-soft; `sources` block + UI banner surface
  unavailability instead of zeroing.
- Health score is a fixed fold (READY=100/WARNING=60/UNKNOWN=40/BLOCKED=0)
  of canonical statuses — no recalculation of any underlying metric.
- History windows report `insufficient_data` when < 5 evaluations.

## Code-review fixes applied
- Health score: pipeline stages absent from the stage summary now emit
  UNKNOWN components (score 40) instead of being silently omitted — a
  missing stage summary can never inflate the composite.
- Session comparison: labels derive from actual IST calendar dates (a
  historical day is never relabelled "today"); an empty today row is
  always present when no session ran today.
- Comparison metrics: risk rejections, execution success %, and pipeline
  latency (avg symbol ms) now come from the canonical stage summary for
  the day owning the latest scan; prior days honestly show — (per-day
  history of those metrics is not stored).
- Tests updated: 21/21 PASS after fixes; readiness suite 39/39 unchanged.

## Known limitations (by design, disclosed in UI)
- 90-day statistics fill up gradually as the enriched history log grows
  (cap raised 50 → 500 entries).
- Historical replay-session rows from `signal_snapshots` carry limited
  metadata; comparison shows — for those fields.
- Per-day pipeline latency uses the day's canonical scan duration; stage
  timing detail remains on Operator Analytics (no duplication).
