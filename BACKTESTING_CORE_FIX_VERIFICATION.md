# BACKTESTING CORE FIX — VERIFICATION REPORT

Date: 2026-08-10 · Scope: labels, first-run UX, background-failure handling, session-init error visibility.
**No new pages. No new dashboards. No trading-strategy logic changed. No risk thresholds changed. PAPER / RESEARCH ONLY.**

## 1. No new pages added — CONFIRMED
All changes were made to existing pages/routes only:
- `artifacts/trading-dashboard/src/pages/InvestigationCenter.tsx` (existing `/investigation-center`)
- `artifacts/trading-dashboard/src/pages/AIValidationV2Page.tsx` (existing `/validation-v2`)
- `artifacts/trading-dashboard/src/pages/Backtest.tsx` (existing `/backtest`)
- `artifacts/api-server/src/routes/validation-v2.ts`, `routes/phase11.ts`
- `artifacts/api-server/src/python/validation_v2_engine.py`, `daily_session_manager.py`, `main.py`
No route entries were added to `App.tsx`.

## 2. No trading logic changed — CONFIRMED
- No edits to strategy code, gates (`scan_fresh`, `market_open` untouched), risk thresholds, or executor decision logic.
- All engine changes are error-*reporting*/persistence only (status transitions RUNNING→FAILED, error text columns, heartbeat timestamps).
- `test_phase20.py` (40 tests) still passes unchanged.

## 3. Canonical production-pipeline backtest labelling — CONFIRMED (with one important correction)
**Codebase reality check:** the page at URL `/backtest` (`Backtest.tsx`) is a *legacy single-strategy simulator* (POST `/api/backtest` in `trading.ts`). The Phase 23 production-pipeline backtester (POST `/api/backtest/run`, `backtest_runs`/`backtest_trades`, `pipeline_events mode=BACKTEST`) is surfaced by the **Investigation Center** page (`/investigation-center`). Labelling `/backtest` "Production Logic" would have been false. Labels were therefore applied to match reality:

- **/investigation-center** — banner **"Pipeline Backtest — Production Logic"** + description "Replays the real ApexQuant AI production pipeline using historical data. This is the canonical backtest page…" + cross-link **"Open Strategy Validation Centre"** → `/validation-v2`.
- **/backtest** — retitled **"Backtest Engine — Single-Strategy Research"** with an explicit amber banner: *"NOT the canonical production-pipeline backtest"* + cross-link **"Open Production Pipeline Backtest"** → `/investigation-center`.

## 4. /validation-v2 labelled research harness — CONFIRMED
Header now reads **"Strategy Validation — Research Models"** with description "Uses simplified validation and optimizer models for research. This is not the canonical production-pipeline backtest." plus cross-link **"Open Production Pipeline Backtest"** → `/investigation-center`. Verified in browser screenshot.

## 5. Canonical /backtest (pipeline) smoke run — PASSED
- Run id: **BT-e0b06d2d0c**
- Status: **COMPLETED** (progress 65/65 ticks, phase DONE)
- Symbols: RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK
- Interval: 1d · Period: 2026-05-10 → 2026-08-10 (3 months) · Capital: ₹50,000
- `backtest_runs` populated (status/config/progress/metrics verified via GET `/api/backtest/run/BT-e0b06d2d0c`)
- `backtest_trades`: 1 trade (TCS, realized P&L ₹255.99, net return +0.49%)
- `pipeline_events` with `mode=BACKTEST&run_id=…`: 2000+ events (SCAN_STARTED, RISK_APPROVED, PORTFOLIO_UPDATED, …)
- Results render on the Investigation Center page; **latest run auto-selects** (verified in browser — Performance Summary, Backtest Portfolio, runs list all populated; no blank page).
- No-trades case: trade list now shows **"Backtest completed — no trades met entry criteria."** when a COMPLETED run has zero trades.
- First-run UX: empty runs list now shows "No pipeline backtest runs yet…" + **"Run First Pipeline Backtest"** CTA pre-configured with the safe defaults above; launch errors render inline instead of a blank screen.

## 6. Validation V2 silent background failures — FIXED & TESTED
- Background executor stdout/stderr now captured to `/tmp/v2_backtest_<runId>.log`; non-zero exit (or spawn failure) marks the run **FAILED** with the log tail (`validation-v2.ts spawnBackground` + new `validation_v2_mark_failed` command).
- New `error` + `last_progress_at` columns on `validation_v2_runs` (auto-migrated); crash wrapper `execute_backtest_pipeline` marks FAILED with traceback on any uncaught exception; COMPLETED clears error.
- Stuck-run watchdog: RUNNING runs with no progress for **30+ minutes** are lazily marked FAILED with a remediation message on every list/get.
- UI: FAILED/ERROR runs show in rose with the persisted error text; polling stops and the runner surfaces the error instead of endless RUNNING.
- Watchdog safety (post-review hardening): the executor heartbeats `last_progress_at` per symbol **and per strategy** so long single-symbol replays are not falsely failed; the terminal COMPLETED update is guarded by `status = 'RUNNING'` so a watchdog-FAILED run can never be silently resurrected to COMPLETED.
- Tests: `test_validation_v2_failure_handling.py` — **7/7 passed** (crash marks FAILED, error persisted, COMPLETED never downgraded, stuck-run watchdog, FAILED never overwritten by late completion, error surfaced via list/get).

## 7. AI Paper Trader session-init error persistence — FIXED & TESTED
- Root-cause crash (undefined `data` in `daily_session_init` dispatch) fixed earlier; additionally:
- New `daily_session_record_error` command persists crash-level failures (timestamp, command, error, recovery hint) to the `daily_session_last_error` KV; `/phase11/session/init` route records it automatically if the Python process dies.
- Step-level failures (including agent warm-up and top-up dict errors) set state ERROR with structured detail; clean init clears it.
- UI: INIT FAILED (rose, exact persisted error + Retry button); market-closed shows **STANDBY — "Market closed — auto-initializes at pre-open (08:43 IST)"** (the "expected until next session init" case); NOT INIT (amber) otherwise.
- Tests: `test_daily_session_and_pipeline_e2e.py` — **11/11 passed**.
- Gates untouched: `market_open` / `scan_fresh` never bypassed; no trades forced after close.

## 8. Result-location separation — CONFIRMED
- `/investigation-center` reads only `/backtest/*` + `pipeline/events?mode=BACKTEST` (pipeline runs, isolated ledger trades, missed opportunities, replay/story).
- `/validation-v2` reads only `/validation-v2/*` (validation runs, simplified-model trades, optimizer results, model comparison).
- No query in either page crosses to the other run type.

## Remaining blockers / notes
- The legacy `/backtest` page still exists as a third, simplified engine. It is now clearly labelled non-canonical; retiring or merging it is a product decision left open.
- V2 stuck-run watchdog is lazy (fires on list/get access). A run stuck while nobody looks at the page is marked the next time anyone loads it — acceptable for an operator-facing page.
- Full checks: dashboard + api-server typecheck clean; python suites 40+11+6 tests passing; api-server restarted and endpoints verified live.
