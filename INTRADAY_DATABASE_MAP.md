# INTRADAY DATABASE MAP

**Audit Date:** 2026-08-23 (Asia/Kolkata)  
**Branch:** phase4a-controlled-paper-entry-framework-disabled  
**Commit:** 891288296f70ec52a917b46b0d906d4230153464  
**Methodology:** Static source inspection of `artifacts/api-server/src/python/*.py` (non-test files only).  
**Runtime Verification Caveat:** ⚠️ NO DATABASE CONNECTION WAS MADE. All tables below are code-defined — their presence or state in any live database cannot be confirmed without runtime access. Tables marked `(Postgres)` require `DATABASE_URL` environment variable; tables marked `(SQLite)` use file-based SQLite in the Python source directory.

---

## Storage Classification

| Storage Type | Files | Condition |
|---|---|---|
| **PostgreSQL** (psycopg2) | 28 Python modules | Requires `DATABASE_URL` env var set |
| **SQLite** (sqlite3) | 14 Python modules | `trade_intelligence.db` in `artifacts/api-server/src/python/` |
| **JSON flat-file** | ~20 Python modules | Cached snapshots in Python source directory |
| **Shared KV (phase20_kv)** | phase20_store.py | Postgres table used as key-value store |

---

## Database Files (Code-Defined)

### SQLite: `trade_intelligence.db`
Path: `artifacts/api-server/src/python/trade_intelligence.db`  
Shared by: trade_intelligence.py, historical_knowledge_builder.py, confidence_calibration.py, hypothesis_engine.py, model_versioning.py, adaptive_adjustments.py, portfolio_manager.py, root_cause_engine.py, similarity_engine.py, strategy_intelligence.py, trade_evaluator.py, phase14_learning.py, predictive_intelligence.py, adaptive_learning.py

### SQLite / Postgres: `trading.db`
Path: `artifacts/api-server/src/python/trading.db`  
Note: File exists at runtime but no `CREATE TABLE` referencing this filename was found in source; likely created by a subsystem not yet traced. **UNKNOWN origin.**

---

## Table Inventory

### Tables in `trade_intelligence.db` (SQLite) — code-defined

| Table | Source File | Key Columns (from CREATE TABLE) | Notes |
|---|---|---|---|
| `trade_intelligence` | trade_intelligence.py:58 | id, symbol, action, quantity, entry_price, exit_price, pnl, pnl_pct, strategy, confidence, timestamp, session_date, status, tags, metadata | Core paper trade ledger |
| `historical_knowledge_trades` | historical_knowledge_builder.py:59 | id, symbol, date, session_date, trade_quality, confidence, entry_price, exit_price, pnl, pnl_pct, strategy, outcome, regime, sector, metadata | Historical knowledge base |
| `proposed_adjustments` | adaptive_adjustments.py:53 | References trade_intelligence.DB_PATH | Adaptive learning parameter proposals |
| `hypotheses` | hypothesis_engine.py:78 | id, symbol, hypothesis, confidence, created_at, tested, outcome | AI hypothesis tracking |
| `model_versions` | model_versioning.py:35 | id, version, champion, challenger, metrics, created_at, status | ML model version registry |
| `prediction_snapshots` | trade_evaluator.py:33 | id, symbol, predicted_action, actual_action, confidence, timestamp, session_date | Pre-trade prediction snapshots |
| `trade_evaluations` | trade_evaluator.py:70 | id, symbol, trade_id, evaluation_score, factors, timestamp | Post-trade evaluation scores |
| `feature_importance_snapshots` | root_cause_engine.py:417 | id, session_date, features_json, created_at | Feature importance at scan time |
| `feature_weights` | root_cause_engine.py:426 | feature, weight, last_updated | Active feature weight store |

### Tables in PostgreSQL (`DATABASE_URL`) — code-defined

| Table | Source File | Key Columns | Notes |
|---|---|---|---|
| `signals_cache` | signals_store.py:61 | id, symbol, signal_type, confidence, price, timestamp, session_date, metadata | Live signal cache |
| `signal_snapshots` | signals_store.py:70 | id, scan_id, symbols_json, timestamp | Per-scan signal snapshots |
| `scan_state` | scan_state_store.py:63 | id, scan_id, status, started_at, completed_at, symbols_scanned, signals_found, metadata | Scan run state |
| `scan_lock` | scan_state_store.py:85 | lock_name, locked_by, locked_at, expires_at | Distributed scan lock |
| `phase20_settings` | phase20_store.py:209 | id, key, value, updated_at | Phase 20 operator settings |
| `phase20_scan_runs` | phase20_store.py:218 | id, scan_id, started_at, completed_at, status, symbols, signals_found, metadata | Phase 20 scan run log |
| `phase20_scheduler_state` | phase20_store.py:239 | id, state, last_scan_at, next_scan_due, metadata | Scheduler heartbeat state |
| `phase20_notifications` | phase20_store.py:275 | id, type, title, message, data_json, created_at, read, delivered | System notifications |
| `phase20_kv` | phase20_store.py:1048+ | key, value, updated_at | General-purpose key-value store (multiple tables; same schema) |
| `paper_portfolio` | paper_trader.py / portfolio_store.py | id, symbol, qty, entry_price, current_price, pnl, pnl_pct, stop_loss, target, status, created_at, updated_at | Live paper positions |
| `paper_trades` | paper_trader.py | id, symbol, action, quantity, price, status, created_at, closed_at, pnl, metadata | Paper trade records |
| `phase11_capital_topups` | phase11_autonomous.py:49 | id, amount, reason, timestamp, balance_after | Phase 11 capital injection log |
| `phase11_price_snapshots` | phase11_autonomous.py:75 | id, symbol, price, timestamp, session_date | Phase 11 price capture |
| `phase20_eod_outcomes` | phase20_eod_outcomes.py:61 | id, symbol, trade_id, outcome, pnl, exit_price, exit_timestamp, reason, metadata | EOD position exit outcomes |
| `phase20_paper_trades` | phase20_executor.py:67 | id, symbol, action, quantity, entry_price, stop_loss, target, confidence, strategy, session_date, status, created_at | Phase 20 canonical paper trades |
| `portfolio_config_overrides` | portfolio_config_overrides.py | key, value, updated_at | Operator-set portfolio config overrides |
| `portfolio_decisions` | portfolio_manager.py (SQLite) | id, symbol, decision, confidence, price, timestamp | Portfolio manager decision log |
| `experimental_paper_trades` | paper_exploration_engine.py:72 | id, symbol, action, quantity, price, confidence, strategy, session_date, status, created_at | Exploration mode paper trades |
| `nifty50_company_master` | nifty50_company_master_store.py:49 | symbol, company_name, sector, industry, isin, market_cap, last_updated | NIFTY 50 company reference data |
| `custom_universe_membership_history` | custom_universe_store.py:83 | id, symbol, action, operator, reason, timestamp | Custom universe change audit |
| `{TABLE}` (custom_universe) | custom_universe_store.py:52 | symbol, sector, exchange, added_by, added_at, active, metadata | Custom trading universe (table name is runtime-configured constant) |
| `daily_ohlcv_cache` | ohlcv_cache_store.py:82 | symbol, date, open, high, low, close, volume, source, cached_at | Daily OHLCV price cache |
| `daily_ohlcv_refresh_state` | ohlcv_cache_store.py:99 | id, last_refresh_date, status, symbols_count, updated_at | OHLCV cache refresh state |
| `broker_reconciliation_runs` | eod_reconciliation.py:55 | id, run_id, status, started_at, completed_at, discrepancies_found, metadata | Broker reconciliation run log |
| `broker_reconciliation_discrepancies` | eod_reconciliation.py:69 | id, run_id, symbol, type, expected, actual, status, resolved_at, resolution_note | Individual discrepancy records |
| `certification_runs` | certification_engine.py:74 | id, domain, run_id, status, result, started_at, completed_at, metadata | System certification run results |
| `pipeline_events` | pipeline_events.py | id, event_type, data_json, timestamp, session_date | System pipeline event log |

### Pre-open Tables (PostgreSQL) — code-defined

| Table | Source File | Purpose |
|---|---|---|
| `preopen_sessions` | preopen_db.py | Pre-open analysis session records |
| `preopen_snapshots` | preopen_db.py | Pre-open market snapshot per symbol |
| `preopen_rankings` | preopen_db.py | Pre-open symbol ranking results |
| `preopen_watchlists` | preopen_db.py:128 | Watchlist snapshots at pre-open |
| `preopen_provider_health` | preopen_db.py:145 | Data provider health at pre-open |
| `preopen_reconciliation` | preopen_db.py:165 | Pre-open data reconciliation results |
| `preopen_validation_sessions` | preopen_validation_db.py:44 | Pre-open validation run metadata |
| `preopen_candidate_outcomes` | preopen_validation_db.py:67 | Per-symbol pre-open prediction outcomes |
| `preopen_score_band_metrics` | preopen_validation_db.py:128 | Accuracy metrics by confidence band |
| `preopen_factor_metrics` | preopen_validation_db.py:154 | Factor-level accuracy metrics |
| `preopen_daily_reports` | preopen_validation_db.py:175 | Daily pre-open accuracy reports |

### Signal Validation Tables (PostgreSQL) — code-defined

| Table | Source File | Purpose |
|---|---|---|
| `signal_validation_sessions` | signal_validation_db.py:44 | Signal validation run sessions |
| `signal_validation_records` | signal_validation_db.py:65 | Per-signal validation records |
| `signal_lifecycle_events` | signal_validation_db.py:149 | Signal lifecycle event log |
| `signal_price_checkpoints` | signal_validation_db.py:166 | Price checkpoints for signal outcome |
| `signal_strategy_metrics` | signal_validation_db.py:180 | Per-strategy signal metrics |
| `signal_ai_metrics` | signal_validation_db.py:214 | AI confidence metrics per signal |
| `signal_preopen_metrics` | signal_validation_db.py:235 | Pre-open correlation metrics |
| `signal_risk_metrics` | signal_validation_db.py:253 | Risk metrics per signal |
| `signal_regime_metrics` | signal_validation_db.py:275 | Regime metrics per signal |
| `signal_daily_reports` | signal_validation_db.py:298 | Daily signal validation reports |

### Phase 22-26 Tables (PostgreSQL) — code-defined

| Table | Source File | Purpose |
|---|---|---|
| `phase22_evidence` | phase22_evidence.py:61 | Phase 22 live-readiness evidence |
| `phase24_trade_intelligence` | phase24_store.py:63 | Phase 24 trade intelligence records |
| `phase24_missed_opps` | phase24_store.py | Missed opportunity records |
| `phase24_recommendations` | phase24_store.py | Generated recommendations |
| `phase24_reports` | phase24_store.py | Phase 24 report records |
| `phase26c_results` | phase26c_store.py | Phase 26C validation results |
| `phase26_validation_runs` | phase26_store.py | Phase 26 validation run records |
| `phase26_live_snapshots` | phase26_live_store.py | Phase 26 live data snapshots |
| `phase26_issues` | phase26_store.py | Phase 26 issue tracking |
| `phase26_daily_reports` | phase26_reports.py | Phase 26 daily reports |

### Simulation / Validation-V2 Tables (SQLite) — code-defined

| Table | Source File | Purpose |
|---|---|---|
| `sim_scenarios` | simulation_lab.py:71 | Simulation scenario definitions |
| `sim_runs` | simulation_lab.py:82 | Simulation run results |
| `validation_v2_runs` | validation_v2_engine.py:79 | Validation v2 backtest run metadata |
| `validation_v2_decisions` | validation_v2_engine.py:99 | Per-decision records in v2 validation |
| `validation_v2_trades` | validation_v2_engine.py:117 | Trade records in v2 validation |
| `validation_v2_missed` | validation_v2_engine.py:141 | Missed opportunity records in v2 validation |
| `validation_v2_optimizer_runs` | validation_v2_engine.py:155 | Optimizer run results |
| `alert_deliveries` | alert_queue.py:42 | Push notification delivery records |
| `session_archives` | session_archive.py:59 | Archived scan session records |

### Notification / Alert Tables (PostgreSQL) — code-defined

| Table | Source File | Purpose |
|---|---|---|
| `phase20_notifications` | phase20_store.py:275 | System notification feed |

---

## JSON Flat-File Stores (Code-Defined)

| File | Purpose |
|---|---|
| `signals_cache.json` | Current signal snapshot (memory-mapped cache) |
| `market_context_cache.json` | Market context snapshot cache |
| `intelligence_cache.json` | Market intelligence cache |
| `strategy_weights.json` | Strategy weighting coefficients |
| `signal_weights.json` | Signal weighting coefficients |
| `historical_knowledge_status.json` | Knowledge build status |
| `calibration_state.json` | AI calibration state |

---

## Summary Counts

| Category | Count |
|---|---|
| Unique code-defined table names (non-test Python) | 77 (excluding runtime-named `{table}` / `{TABLE}`) |
| SQLite database files | 1 confirmed (`trade_intelligence.db`) + 1 unknown (`trading.db`) |
| PostgreSQL table groups | ~50 tables across 28 modules using `DATABASE_URL` |
| JSON flat-file stores | ~20 files |

**⚠️ Runtime-Verification Caveat:** No database queries were executed. Table existence, row counts, and schema fidelity cannot be confirmed without direct database access. Postgres tables exist only when `DATABASE_URL` is set and `CREATE TABLE IF NOT EXISTS` has executed at least once.
