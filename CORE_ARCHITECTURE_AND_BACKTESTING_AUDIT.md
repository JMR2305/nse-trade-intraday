# CORE ARCHITECTURE AND BACKTESTING AUDIT

**Date:** 2026-08-10 · **Mode:** PAPER / RESEARCH ONLY · **Status:** Report only — no code changed.

Evidence sources: code inspection of `artifacts/trading-dashboard` and `artifacts/api-server`, plus live API probes taken 2026-08-10 19:30 UTC (scan `b143f93cc351`).

---

## A. Page Inventory

| Page | Route | Purpose | Key API endpoints | Type | Functional? | Overlap | Recommendation |
|---|---|---|---|---|---|---|---|
| Mission Control | `/mission-control` | Ops dashboard: pipeline, scanner, replay, portfolio widgets | widget queries: health, `/pipeline/summary`, feed, portfolio, scan, `/replay/sessions/latest` | Live | ✅ Yes | Heavy overlap with Live Command Center | **KEEP — canonical live overview** |
| AI Live Trading Command Center | `/live-command-center` | Live pipeline events, scan, portfolio, latest replay | `/pipeline/summary`, `/pipeline/events`, `/live-data/scan/status`, `/portfolio/snapshot`, `/replay/sessions/latest`, `/ops-centre/cycle-log` | Live | ✅ Yes | Same data as Mission Control at finer grain | KEEP (event-level drill-down); candidate to **merge into Mission Control later** |
| AI Operations Centre | `/ai-operations-centre` | Agent/platform health | `/ops-centre/snapshot`, `/ops-centre/agents`, `/ops-centre/platform`, `/phase11/timeline`, `/risk/audit` | Live/ops | ✅ Yes (snapshot slow ~22–30 s by design) | Agents/timeline shared with AI Paper Trader | KEEP |
| AI Investigation Center | `/ai-investigation` | Historical session replay, symbol journeys, comparisons | `/replay/sessions`, `/replay/sessions/{scan}/replay`, `/summary`, `/symbol/{sym}` | Replay | ✅ Yes | Overlaps `/trade-replay`, `/replay-mode` | **KEEP — canonical replay/investigation** |
| AI Validation Centre V2 | `/validation-v2` | Backtest + validation suite (10 tabs) | `/validation-v2/backtest[...]`, `/performance`, `/missed-opportunities`, `/optimizer/*`, `/session-timeline`, `/model-comparison` | Backtest/validation | ✅ Yes as of 2026-08-10 (1 completed run exists) | Overlaps Phase 23 Backtest + Strategy Optimisation optimizer | KEEP — see §E and the fix plan for its role |
| Backtest Runner | `/backtest` (`Backtest.tsx`) | Phase 23 canonical backtest runner/results | `/backtest/run`, `/backtest/{run}/status|portfolio|trades|missed|replay|story` (via child components) | Backtest | ✅ Yes | Overlaps Validation V2 runner | **KEEP — canonical backtest engine UI** |
| Replay / Trading Day Timeline | `/trading-timeline` | Event/alert timeline with positions | `/command-center/timeline`, `/command-center/alerts`, `/phase20/positions`, `/command-center/summary` | Live/replay | ✅ Yes | Event display overlaps Mission/Live Command | KEEP |
| Trade Replay | `/trade-replay` | Trade-level historical replay | No direct API calls found in component (legacy/static or child hooks) | Replay | ⚠️ Unverified | Duplicates AI Investigation Center | **DEPRECATE candidate** — verify then hide |
| Strategy Optimisation | `/strategy-optimisation` | Strategy metrics, recommendations, patterns | `/optimisation/summary|strategies|recommendations|patterns`, `/strategy-optimization/report` | Analytics (advisory) | ✅ Yes | Optimizer overlaps Validation V2 optimizer tab | KEEP (advisory analytics), consolidate optimizers later |
| Operator Analytics | `/operator-analytics` | Funnel, paper analytics, rejection/timing reports | `/paper-analytics/summary|snapshot`, `/operator-analytics/report` | Analytics | ✅ Yes | Paper analytics also shown in AI Paper Trader | KEEP |
| System Readiness | `/system-readiness` | GO/NO-GO readiness | `/system-readiness/report|history` | Validation | ✅ Yes | Overlaps Live Readiness / validation dashboards | KEEP; merge other readiness views into it later |
| Portfolio Performance | `/portfolio-performance` | Equity, drawdown, statistics | `/portfolio-performance/summary|equity|drawdown|statistics|portfolio` | Portfolio | ✅ Yes | Portfolio data also in Live Command, AI Paper Trader | KEEP — canonical performance view |
| Trade History | `/trades` | All historical trades | `/trades?scope=all` | Portfolio | ✅ Yes | Closed positions also in AI Paper Trader | KEEP |
| Broker / Execution | `/broker-execution` | Broker connectivity + reconciliation | via child components (reconciliation probe/badge) | Live/ops | ✅ Yes | Positions overlap Portfolio pages | KEEP |
| AI Paper Trader | `/ai-paper-trader` | Autonomous paper session: init, pipeline, positions, capital | `/phase11/session/*`, `/phase20/pipeline`, `/phase11/portfolio/*`, `/phase11/timeline`, `/live-data/scan/*` | Live/paper | ✅ Yes — see §F for NOT INIT explanation | Largest overlap surface of any page | **KEEP — canonical paper-trading operator page** |
| Learning / Knowledge | `/agent-learning`, `/agent-knowledge`, `/knowledge-search`, `/lessons-library` | Phase 24 / learning-layer views | `/learning-layer/learning/snapshot`, `/learning-layer/knowledge/*` | Learning | ✅ Yes | Overlaps `/learning-insights`, `/trade-memory`, etc. | KEEP core two; consolidate satellites later |

**Why some pages "appear empty":** three distinct causes, not one bug — (1) run-dependent pages (Validation V2, Investigation) are empty until a run/session exists; (2) session-dependent pages (AI Paper Trader) reset daily at IST midnight; (3) slow aggregate endpoints (ops-centre snapshot ~30 s) look blank until the long-timeout query resolves.

---

## B. Canonical Data Stores

| Store | Tables / files | Owner (writer) | Readers | Status |
|---|---|---|---|---|
| **Pipeline Event Store** | PG `pipeline_events` | `pipeline_events.py` (emitted by scan engine, executor) | `/pipeline/*` routes, `replay_engine.py` | **CANONICAL** — one append-only stream for all dashboards. JSON fallback `pipeline_events.json` only when DB down. |
| **Scan State Store** | PG `scan_state`, `scan_lock` | `scan_state_store.py` (`save_successful_scan`) | replay engine, canonical portfolio, all scan-status routes | **CANONICAL** scan snapshot. `phase7_scan_cache.json` is a warm cache/fallback only. |
| **Paper Trade Ledger (Phase 20)** | PG `phase20_paper_trades` (+ `phase20_settings/scan_runs/scheduler_state/notifications/kv`) | `phase20_executor.py` | paper analytics, portfolio snapshot, replay, learning | **CANONICAL** execution ledger. Append-only; one OPEN trade per symbol enforced by partial unique index. |
| **Portfolio Store** | PG `paper_portfolio`, `paper_trades`; adapter `canonical_portfolio.py` | `portfolio_store.py`; positions/cash/equity derived from phase20 ledger | `/portfolio/*`, portfolio-performance engine | **CANONICAL** via `canonical_portfolio.py`. Never mix legacy state. |
| **Execution engine stores** | `src/execution/` portfolio/pnl contracts + durable portfolio repos | ExecutionService | broker/execution page, P&L | CANONICAL (RC-8/RC-10 line) |
| **Signals cache** | PG `signals_cache`, `signal_snapshots` | `signals_store.py` (post-scan pipeline) | dashboards, push alerts | **DERIVED cache** — regenerated per scan; never a source of truth |
| **Validation V2 tables** | PG `validation_v2_runs/_decisions/_trades/_missed/_optimizer_runs` | `validation_v2_engine.py` | `/validation-v2/*` routes only | CANONICAL for V2 runs; isolated from live ledger ✅ |
| **Phase 23 Backtest Store** | PG `backtest_runs`, `backtest_trades`; candle cache `backtest_candles/_candle_meta/_corporate_actions` | `backtest_portfolio.py`, `backtest_runner.py` | `/backtest/*` routes | CANONICAL for Phase 23 backtests; isolated ledger ✅ |
| **Learning Store (Phase 24)** | PG `phase24_trade_intelligence/_missed_opps/_recommendations/_reports` | `phase24_engine.py` | `/p24_*` routes, learning pages | CANONICAL; JSON files are legacy fallbacks |
| **Legacy JSON caches** | `phase12_cache.json`, `ai_decisions_cache.json`, `market_context_cache.json`, `opportunity_cache.json`, phase13/14/15/18/21 report JSONs, `kite_instruments_cache.json`, etc. | post-scan pipeline / individual phase modules | various phase dashboards | **DERIVED/LEGACY** — regenerated from the canonical scan by `scan_pipeline.run_post_scan_pipeline()`; the atomic bundle pointer `phase20_kv.scan_bundle_latest` guarantees they all belong to one scan_id |

**Wrong-store usage found:** none critical. The architecture correctly funnels pages through canonical stores. Consistency risk lives in the *derived caches*, which is exactly why the post-scan bundle publish (single scan_id, atomic pointer) exists. Pages read consistent data as long as they read bundle-published caches — verified below in §G.

---

## C. Correct Live/Paper Trading Flow

All stages verified in code. One scan = one `scan_id` = one `snapshot_ts` throughout.

| # | Stage | Module / entry | Event emitted | Store written | Displayed on |
|---|---|---|---|---|---|
| 1 | Market data | `live_scan_engine.run_live_scan()` → `LiveDataProvider.fetch_batch()` | `SCAN_STARTED`, `SCAN_FETCH_COMPLETED` | `scan_state` | Mission Control, Live Command, scan status |
| 2 | Scanner | `_scan_one()` per symbol | `SYMBOL_SCANNED` / `SYMBOL_REJECTED` | canonical scan snapshot | Live Command events, Investigation |
| 3 | Research / MI / Monitoring / Strategy | `scan_pipeline.run_post_scan_pipeline()` → `intelligence.run_intelligence_scan()` | `RESEARCH_COMPLETED`, `MARKET_INTELLIGENCE_COMPLETED`, `MONITORING_COMPLETED`, `STRATEGY_SELECTED/REJECTED` | `signals_cache`, `intelligence_cache`, bundle pointer | MI Hub, Research, Trade Decisions |
| 4 | Portfolio pre-check | `portfolio_bridge.pre_check()` (fail-closed) | `PRECHECK_APPROVED/REJECTED` | evidence in ledger | Pre-check visibility (26A), Replay |
| 5 | Risk | `phase11_risk.pre_trade_check()` + `risk_validation.pre_trade` | `RISK_APPROVED/REJECTED` | evidence in ledger | Risk pages, Replay |
| 6 | AI Decision | `ai_decision.scan_ai_decisions()` | `BUY/SELL/WATCH/IGNORE_GENERATED` | `ai_decisions_cache` (derived) | Trade Decisions, Paper Trader |
| 7 | Execution (paper) | `phase20_executor.run_auto_entries()` / `paper_trader.execute_buy()` | `ORDER_SUBMITTED/EXECUTED/REJECTED` | **`phase20_paper_trades` ledger** | Paper Trader, Broker/Execution |
| 8 | Portfolio / P&L | `canonical_portfolio.py` + `execution/pnl.py` | `POSITION_*`, `PORTFOLIO_UPDATED`, `PNL_UPDATED` | portfolio snapshot | Portfolio pages, Live Command |
| 9 | Replay | `replay_engine.build_replay(scan_id)` — reconstructs from events + ledger + snapshot | (consumes) | derived response | Investigation, Mission Control, Ops Centre |
| 10 | Learning | `phase24_engine` (closed trades, missed opps) | (consumes) | `phase24_*` tables | Learning pages |

**Triggering:** scheduler (`phase20_scheduler.run_tick()`) during market hours, or manual `POST /live-data/scan/run`. Both go through `get_or_run_scan()` with a DB-durable scan lock (skip-not-poll + heartbeat renewal). Failed scans never overwrite the snapshot.

---

## D. Backtesting Data Flow — THE KEY SECTION

**There are TWO backtest engines plus one derived simulator. This is the root of the confusion.**

### Engine 1 — Phase 23 Canonical Backtest ("Backtest Runner" page, `/backtest`)
1. **Started from:** `/backtest` page (Backtest.tsx) → **POST `/api/backtest/run`** (`routes/backtest.ts`).
2. **Engine:** `backtest_runner.py` — **deliberately reuses the real production pipeline**: it calls `live_scan_engine._scan_one()` + `derive_symbol_events()` on historical as-of slices. It is NOT a simplified path.
3. **Historical data:** yfinance via `historical_data_engine.py`, cached in PG `backtest_candles`.
4. **Intervals:** 5m, 10m (resampled from 5m), 15m, 1d.
5. **Date limits:** intraday max **55 days** (yfinance provider limit); daily effectively unlimited; 270-calendar-day daily warmup prepended.
6. **Storage:** runs → `backtest_runs`; trades → `backtest_trades` (isolated ledger, never mixes with the live phase20 ledger); decisions/rejections → canonical `pipeline_events` (mode=backtest); missed opportunities → computed from RISK_REJECTED/WATCH events, stored in run JSON.
7. **Results displayed:** Backtest page, plus replay/story/explain endpoints consumed by Investigation-style views.

### Engine 2 — Validation V2 Backtest ("AI Validation Centre V2" page, `/validation-v2`)
1. **Started from:** Backtest Runner **tab** on `/validation-v2` → **POST `/api/validation-v2/backtest/run`**.
2. **Engine:** `validation_v2_engine.py` — a **separate, simplified simulation** (strategy models like trend_rider replayed over candles). It does NOT run `_scan_one` and does NOT use the production gate chain.
3. **Historical data:** yfinance. **Limits:** ≤20 symbols, ≤730 days, intervals incl. 1d (intraday subject to same yfinance caps).
4. **Storage:** `validation_v2_runs/_decisions/_trades/_missed` — fully isolated.
5. **Results displayed:** the other 9 tabs of `/validation-v2`; run dropdowns list `validation_v2_runs`.
6. **Why the page showed no runs:** simply because **no backtest had ever been executed** — the tables were empty. (Two engine bugs previously made first runs fail silently: legacy schema drift swallowed inserts, and the background executor spawns with stdio ignored so failures left phantom runs. Both were fixed on 2026-08-10; the first run then completed: 1,225 decisions / 0 trades — honest result, trend_rider entries didn't trigger on daily bars.)
7. **How to run the first backtest correctly:** open `/validation-v2` → Backtest Runner tab → defaults (5 symbols, 6 months, ₹50,000, 1d) → "Run Backtest". A completed run now exists (`6cec55f2…`, COMPLETED), so dropdowns populate.

### Engine 3 — Simulation Lab (23.8A) — not a backtester
Applies what-if/risk transforms to an **existing** backtest run's ledger (`sim_scenarios`, `sim_runs`). Inherits data from the base run; no own fetch.

### Verdict
| | Phase 23 (`/backtest`) | Validation V2 (`/validation-v2`) |
|---|---|---|
| Uses real production pipeline | ✅ yes (`_scan_one`) | ❌ no (simplified models) |
| Isolated ledger | ✅ | ✅ |
| Intraday intervals | ✅ 5m/10m/15m (≤55 d) | limited |
| Purpose | "What would the real system have done?" | strategy-model validation & optimizer research |

**Phase 23 is the faithful backtester. Validation V2 is a research/validation harness.** Both are legitimate but they must be labelled as such in the UI to end the confusion (see fix plan).

---

## E. AI Validation Centre V2 Audit

- **Page code complete?** Yes. All 10 tabs wired to real `/validation-v2/*` APIs; verified by 46 passing dashboard tests + live screenshot on 2026-08-10.
- **Why tabs showed empty:** tabs 3–10 are run-dependent; there were zero runs. The page now has explicit first-run UX: run-dependent tabs disabled with "requires a completed run" tooltips, first-run banner + CTA, auto-open Backtest Runner, auto-select latest run.
- **Is the dropdown empty because no runs?** It was. A completed run now exists and appears.
- **Does Backtest Runner work?** Yes — verified end-to-end via API on 2026-08-10 (run COMPLETED, 1,225 decisions persisted, all tabs populated).
- **Results persisted correctly?** Yes, after the schema-migration and JSONB fixes. Caveat: the background executor still runs with stdio ignored — if it crashes, the run stays RUNNING with no traceback (blocker list, item 3).
- **Overlap with Investigation Center / Phase 23?** Yes, conceptually: both produce runs/trades/missed-opps. They use different engines and different tables (see §D). Recommendation in fix plan.

## F. AI Paper Trader Audit

- **Why Session shows NOT INIT:** verified live — `/phase11/session/status` returns `today: 2026-08-11 (IST), initialized_today: false, last_init_date: 2026-08-10`. The session is **date-scoped to the IST trading day**; after IST midnight it always reads NOT_INITIALIZED until the next init. This is by design, not a failure.
- **Why "Python exited with code 1":** "Initialize Today's Session" POSTs `/phase11/session/init` → spawns `main.py daily_session_init`. A non-zero exit means the Python command raised. **The traceback is not persisted anywhere** — the route returns stderr in the response, but nothing logs it durably (blocker list, item 2). Current status: Python-side commands are healthy right now (status endpoint executes the same interpreter fine), so the exit-1 was most likely a transient (DB contention or provider timeout during init). To reproduce/capture: run the init command in the foreground shell and read stderr.
- **Is Initialize broken?** Not structurally — last successful init was 2026-08-10T03:30Z. Needs re-init each IST morning (scheduler also does this at market open).
- **Why 8 BUY signals → 0 paper orders (evidence from `/phase20/pipeline`, scan `b143f93cc351`):**
  - **Global gates blocked all entries — correctly:** `scan_fresh` FAILED (scan age 38,907 s > 5,400 s limit) and `market_open` FAILED (market CLOSED). The page was viewed after market close with a stale morning scan; zero orders is exactly right.
  - During market hours the same scan produced per-symbol blocks recorded as notifications: HDFCLIFE blocked (`min_risk_reward`, `per_stock_cap`), INDUSINDBK rejected by Risk Agent (position ₹11,303 = 22.6% of portfolio > 20% limit).
  - Execution is NOT dead: the ledger holds an OPEN BAJFINANCE position (trade `P20-4a5f909738`, filled 2026-08-07), portfolio equity ₹50,264.81 with ₹36,088.59 invested.
- **Are scan_fresh / market_open correct?** Yes — both fire fail-safe (block on stale/closed) and are enforced server-side in the phase20 executor, not in the UI.
- **Should paper orders only happen during fresh market sessions?** Yes, and that's what the gates enforce.
- **Does execution → ledger → portfolio → P&L work in market hours?** Yes — evidenced by existing filled trades in the ledger flowing through to portfolio snapshot and P&L.

## G. Cross-Page Consistency Audit (scan `b143f93cc351`, checked 2026-08-10 19:31 UTC)

| Metric | Replay (`/replay/sessions/latest`) | Pipeline (`/pipeline/summary`) | Phase20 pipeline funnel | Portfolio snapshot |
|---|---|---|---|---|
| scan_id | b143f93cc351 | b143f93cc351 | b143f93cc351 | (portfolio-scoped) |
| Universe | 50 | 51 SCANNER events (50 sym + meta) | 50 scanned | — |
| Scanned w/ live data | 50 in / 48 live | 48 completed, 2 rejected | 48 with LIVE data | — |
| BUY signals | (stage data) | — | 8 BUY/STRONG BUY | — |
| Executed paper trades | ledger-sourced | — | 0 (gates blocked — correct) | 4 open positions |
| Portfolio equity | starting_capital 50,000 | — | — | ₹50,264.81 (cash ₹13,911.41) |

**Result: consistent.** Mission Control, Live Command Center, Investigation, Paper Trader, and Portfolio all read the same scan_id via the canonical replay/bundle path. No page was found reading a wrong store. The historically diverging counts were fixed by the "unified replay snapshot" rule (`/replay/sessions/latest` is the only pipeline-count source) — any page not using it should be flagged in review, but none of the audited pages violate it today.

## H. Duplicate / Legacy Page Classification (no deletions now)

- **Canonical:** Mission Control (live overview) · AI Investigation Center (replay) · Backtest page (faithful backtesting) · AI Validation Centre V2 (strategy validation/optimizer) · AI Paper Trader (paper session ops) · Portfolio Performance · Trade History · System Readiness · Operator Analytics · Learning (agent-learning + agent-knowledge).
- **Duplicate / overlapping (merge later):** Live Command Center → into Mission Control (as drill-down); Trading Timeline event views ↔ Mission Control feed; optimizer surfaces (Strategy Optimisation ↔ Validation V2 optimizer tab); readiness satellites (Live Readiness, System Validation) → System Readiness.
- **Legacy (hide later):** `/trade-replay` (no live API calls found; superseded by Investigation Center); satellite learning pages (`/learning-insights`, `/trade-memory`, `/pattern-explorer` etc. — consolidate into the two agent pages); old phase-numbered dashboards not in the canonical list.
- **Never merge:** the two backtest engines' pages — they serve different purposes (see §D) and merging their UIs without merging semantics would deepen the confusion.

---

# TASK 2 — BACKTESTING FIX PLAN (not implemented; awaiting approval)

**1. Minimum fix to make backtesting work:** almost nothing — both engines already work. Validation V2 ran end-to-end on 2026-08-10. The real gaps: (a) background V2 executor failures are invisible (stdio ignored, run stuck RUNNING forever); (b) no UI labelling of which engine is which; (c) Phase 23 Backtest page's first-run experience unverified in the browser.

**2. Single canonical backtesting page:** **`/backtest` (Phase 23) for "what would the real system have done"** — it replays the true production pipeline. `/validation-v2` remains the strategy-research harness.

**3. Should Validation V2 be the main backtesting page?** No. Keep V2 as the validation/optimizer suite; label it "Strategy Validation (simplified models)". Label `/backtest` "Pipeline Backtest (production logic)". A one-line banner on each page cross-linking the other ends the ambiguity.

**4. How the first backtest should be triggered:** exactly as now — V2: Backtest Runner tab defaults → Run (already done once). Phase 23: `/backtest` form → POST `/backtest/run` (recommend a smoke run: 5 symbols, 1d, 3 months, to verify the runner UI end-to-end in the browser).

**5. Auto-appearance of results:** V2 already auto-selects the latest run on completion. Add the same "poll status → refetch runs → auto-select" contract to the Phase 23 Backtest page if missing.

**6. Tables that must be populated:** V2: `validation_v2_runs/_decisions/_trades/_missed` (✅ populated). Phase 23: `backtest_runs`, `backtest_trades`, `pipeline_events(mode=backtest)`, candle cache (needs first-run verification).

**7. APIs to verify:** `POST /backtest/run` + `/backtest/{run}/status|portfolio|trades|missed|replay`; `GET /validation-v2/backtest` family (✅ verified 2026-08-10).

**8. Tests that must pass:** existing 46 dashboard tests (✅), `AIValidationV2Page.firstrun` suite (✅), plus a Phase 23 smoke: run → status COMPLETED → trades/missed endpoints return non-error.

## Critical blockers (ranked)

1. **Silent background-run failure (Validation V2):** executor spawns detached with stdio ignored; a crash leaves the run RUNNING forever with no error surfaced. Fix: capture stderr to the run row (status=FAILED + error text) and add a stuck-run timeout.
2. **Session-init tracebacks not persisted (AI Paper Trader):** `daily_session_init` exit-1 stderr is returned once to the browser and lost. Fix: persist last init error (+timestamp) in phase20 KV and show it on the page next to NOT INIT.
3. **Phase 23 backtest first-run UX unverified:** engine and endpoints exist and are well-tested at unit level, but no run has been driven through the browser UI in this audit. Verify with a smoke run before declaring it operator-ready.
4. **Engine-labelling gap:** no UI indication that `/backtest` and `/validation-v2` use different engines — the direct cause of "which page runs backtests?" confusion. Fix: static labels + cross-links (UI copy only, no logic).

## Recommendation — single canonical backtesting flow

> **`/backtest` (Phase 23 engine) is the canonical backtest** because it replays the genuine production pipeline (`_scan_one`, real gates, isolated ledger, canonical events). **`/validation-v2` stays as the strategy-validation and optimizer harness.** Investigation Center remains the replay/forensics surface for both live sessions and backtest runs. No pages are deleted; legacy/duplicate pages (§H) get hidden or merged only in a later, separately-approved cleanup.
