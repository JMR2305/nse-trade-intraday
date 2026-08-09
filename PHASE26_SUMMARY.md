# Phase 26 — End-to-End Validation & Production Readiness: Summary

**Status:** ✅ All four sub-phases (26A–26D) implemented, verified, and merged — August 2026
**Scope principle:** Phase 26 is *validation and presentation only*. No new business logic, no duplicated calculations — every check consumes the existing canonical stores (pipeline event store, replay engine, phase20 paper-trade ledger, canonical portfolio, scan state store, learning engine outputs).

---

## Phase 26A — Pre-Check Visibility + End-to-End Validation Engine

### Portfolio Pre-Check Visibility (Task #520)
Made the Portfolio Pre-Check gate fully observable across the pipeline without changing any gating logic:

- **Events with exact engine reasons** — every BUY candidate evaluated emits `PRECHECK_APPROVED` / `PRECHECK_REJECTED` at the true decision point in `execute_buy`, carrying the Portfolio Engine's exact reason list (insufficient cash, sector exposure, max open positions, duplicate symbol, daily-loss lock, drawdown lock, …). Emission is fail-safe, append-only, and attributed to the canonical scan id.
- **New `PORTFOLIO_PRECHECK` stage** between Strategy and Risk in the 11-stage vocabulary — reflected in the pipeline summary API, replay stage list, Ops Centre trace, Mission Control funnel, Live Command Centre rejection views, Ops V2/V3, and the AI Investigation Centre.
- **Honest counts** — `approved_count` (event-derived only), `evaluated_count`, and `not_evaluated` reported separately; pass-through symbols are never labeled "approved"; conservation `in = out + rejected` holds; downstream stages are marked SKIPPED when pre-check blocked a symbol.
- **Replay from events alone** — decisions reconstructed purely from stored events, never re-evaluated.
- ~24 backend tests + 45+ frontend tests; verification report at `artifacts/api-server/src/python/PHASE26A_PRECHECK_VISIBILITY.md`.

### End-to-End Validation Engine (`phase26_validation.py`, `phase26_store.py`)
Validates every trading cycle across the full canonical pipeline (Market Data → Scanner → Research → MI → Monitoring → Strategy → Pre-Check → Risk → AI Decision → Execution → Paper Trade → Portfolio → P&L → Replay → Mission Control → Learning):

- Validators are **read-only and injectable**: pipeline counts come only from `replay_engine.build_replay()`; portfolio checks only via the canonical validation engines.
- **Execution-chain semantics** — a paper-eligible BUY with no ledger row is a BLOCKED chain (WARN, never ERROR); ERRORs are reserved for executed trades with missing links (ledger↔position linkage, CLOSED without realized P&L, missing learning record, missing replay events).
- Per-trade portfolio linkage matched by trade_id/symbol (aggregates can pass while an individual trade's position is missing).
- Fixed a replay-engine bug: BUY classification now normalises "STRONG BUY" variants (previously misclassified as execution orphans → false FAIL every run).
- **Append-only run store** — Postgres authoritative; flock-serialized JSON fallback for local dev; runs are permanent records, never overwritten.

## Phase 26B — Live Validation & Cross-Page Consistency

- **Live subsystem-liveness monitor** (`phase26_live_monitor.py`) — every 5 minutes during NSE sessions (scheduler-hooked, KV-guarded for exactly-once across processes), judges each subsystem (scanner, research, MI, monitoring, strategy, risk, decision, execution, portfolio, P&L, replay, learning) from **canonical store timestamps only** — never derived caches. Quiet off-session: IST calendar rules prevent weekend/after-hours false alarms.
- **Cross-page consistency validator** (`phase26_consistency.py`) — derives the canonical value set once per scan_id and compares the data backing Mission Control, AI Operations Centre, Replay, Investigation Centre, Portfolio, Broker, Performance, Learning Centre, and the Validation Dashboard against it; every mismatch is reported with source, field, expected vs actual. Composes the existing phase15 checker rather than re-implementing it.
- **Issue store** (`phase26_live_store.py`) — structured issues with severity, category, first/last-seen, deduplicated by (category, key); re-detections update the same row; category sweeps auto-resolve cleared issues. Snapshots are append-only.

## Phase 26C — Recovery, Performance & Trading-Quality Validation

- **Recovery suite** (`phase26_recovery.py`) — validates healing after API restart, DB restart, broker reconnect, network interruption, historical-provider failure, and worker restart. **No destructive fault injection**: each scenario validates the recovery code paths against recorded durable state (durable scan snapshot/lock integrity, portfolio recovered from ledger, token/session validity probes, scheduler resumption). PASS/FAIL per scenario.
- **Performance validation** (`phase26_performance.py`) — aggregates latency the platform already records (scan-run durations, stage timestamps, timed replay build, timed DB health query, process resource counters) into a graded report: PASS/WARN/FAIL against explicit thresholds, or INSUFFICIENT when a source has no data — never extrapolated. No new profiling infrastructure.
- **Trading quality** (`phase26_quality.py`) — per-session funnel (scanned → analysed → risk approved/rejected → BUY/SELL/WATCH → executed) counted from the event store + phase20 ledger, plus win rate, profit factor, expectancy, and holding time via the shared paper-analytics services (FIFO matching reused, never re-implemented), and a missed-opportunity view from rejected/watch signals. INSUFFICIENT_EVIDENCE preferred over extrapolation on low trade counts.
- **Append-only storage** (`phase26c_store.py`) — one `phase26c_results` table with an area column (RECOVERY | PERFORMANCE | QUALITY); all three areas feed the Phase 26 issue store and reports.

## Phase 26D — Reports & Readiness Dashboard (Task #555)

Presentation/aggregation only (`phase26_reports.py`) — never recalculates:

- **Daily Validation Report** — one per IST trading day covering System / Trading / AI / Portfolio / Execution / Replay / Learning health plus Validation Score, Certification Score, outstanding issues, and rule-based recommendations. Auto-generated post-close by the Phase 20 scheduler (idempotent per day), persisted append-only, historically retrievable.
- **Five-Day Acceptance tracker** — for the last 5 consecutive live trading days, shows whether each day passed with zero pipeline/portfolio/replay/execution/mission-control mismatches and zero critical errors, with an overall PASS/PENDING/FAIL verdict (IST calendar-day windowing).
- **Trading Quality dashboard page** in the trading web app — session funnel, quality metrics, performance grades, and open issues, following the standard freshness-bar contract with long timeouts for slow aggregate endpoints.
- **Final Production Readiness Report** — on-demand, combining the five-day result, latest certification run, and outstanding issues into a single verdict document, exportable via the existing export engine (JSON/CSV/MD/PDF).
- All pages reachable from navigation; unit tests cover report assembly, five-day windowing, and verdict logic.

---

## Cross-cutting guarantees

| Guarantee | How it's enforced |
|---|---|
| Single source of truth | Counts only from `build_replay()` / pipeline events; portfolio only from the canonical ledger-backed store |
| No recalculation | Validators/reports consume persisted engine outputs; shared analytics (FIFO) reused, never duplicated |
| Append-only evidence | Runs, snapshots, issues, and reports are insert-only; re-detections dedupe, never overwrite |
| Honesty over optimism | INSUFFICIENT_EVIDENCE instead of extrapolation; WARN vs ERROR semantics keep routine runs from false-failing |
| Session awareness | IST calendar rules gate live monitoring and daily/five-day windowing; quiet off-session |
| Paper-trading only | All Phase 26 layers are advisory/validation for the paper-trading research platform |
