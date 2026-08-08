---
name: Phase 24 AI Learning Engine
description: Advisory-only learning engine over the phase20 ledger — trade intelligence, missed opps, risk-rule learning, scorecard, recommendations, reports.
---

# Phase 24 AI Learning & Continuous Improvement Engine

- Modules: `phase24_store.py` (Postgres + JSON-fallback, append-only), `phase24_engine.py` (capture/post-trade analysis/missed-opps/risk learning), `phase24_analytics.py` (rankings/time/calibration/scorecard/overview), `phase24_recommendations.py` (recs + 4-period reports + KV-guarded daily tick).
- **Advisory-only invariant** enforced by AST safety tests in `test_phase24.py` (FORBIDDEN_CALLS/IMPORTS lists). Any new phase24 module must be added to `PHASE24_FILES` there. `decide_recommendation()` records intent only and imports nothing.
- **Why:** phase14 governance — learning must never auto-modify thresholds/strategies/gates.
- Append-only: trade records PK trade_id (ON CONFLICT DO NOTHING), missed opps PK scan_id:symbol, reports unique per period+key, recommendation decisions are final (PROPOSED→APPROVED/DISMISSED once).
- Excursions (MFE/MAE) only from real intraday candles — mock-source candles are rejected, fields stay null (`excursion_source: "unavailable"`); never fabricate.
- Scheduler hook: `phase20_scheduler.run_tick()` CLOSED branch calls `maybe_run_daily_learning()` (lazy import, never raises, KV key `phase24_learning_date`, restores prev key on failure so a later tick retries).
- Routes in `src/routes/phase24.ts` (phase21 pattern); overview is slow → 30s route cache + single-flight; dashboard queryFn passes 130s timeout.
- Tests force file-fallback (patch `db_available` → False + 4 *_FILE paths) so the dev DB is untouched.
- **How to apply:** any future learning/enrichment feature should write into phase24_store (append-only, keyed to existing trade/scan IDs) rather than a new parallel store.
