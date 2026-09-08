# INTRADAY DATA QUALITY AUDIT

**Scope:** Static source-code analysis of `artifacts/api-server`, `artifacts/trading-dashboard`, and `intraday-trading-bot`.  
**Date:** 2026-08-23 (Asia/Kolkata)  
**Analyst:** Automated static audit (no runtime execution)  
**Methodology:** `rg`, `grep`, `sqlite3`, direct file reads. No servers were started, no queries executed against live DB, no browser or API calls made. Every claim is backed by a file path and line number.  
**UNKNOWN boundary:** Any finding marked *UNKNOWN* cannot be confirmed without a live deployment (DB contents, environment-variable values, runtime behaviour).

---

## Methodology

1. All source files (`*.py`, `*.ts`, `*.tsx`) were enumerated under `artifacts/api-server/src` and `artifacts/trading-dashboard/src` (excluding `node_modules`, `__pycache__`).  
2. `grep`/`rg` was used to locate hardcoded literals, fallback paths, duplicate definitions, stale JSON caches, polling intervals, and error-handling gaps.  
3. SQLite databases were probed with `sqlite3 .schema`; both returned empty schemas (files exist but are empty on disk).  
4. JSON state files were inspected with `python3 -c "import json…"`.  
5. The intraday-trading-bot (`intraday-trading-bot/src`) was cross-checked against the API server for schema and data-flow mismatches.  
6. Memory files under `.agents/memory/` were consulted for known architectural decisions.

---

## 1. Seeded / Demo / Hardcoded Values

### 1.1 — `_SEED_PRICES` in `market_data_engine.py`
| Field | Value |
|-------|-------|
| **File** | `artifacts/api-server/src/python/market_data_engine.py` L126–130 |
| **Severity** | HIGH |
| **Finding** | A static `dict` named `_SEED_PRICES` holds ten hardcoded price anchors (e.g. `"RELIANCE": 2950.0`, `"TCS": 3800.0`, `"MARUTI": 12500.0`) used to seed the geometric Brownian motion mock data generator. These prices are **not updated from any live feed** and are anchored to approximate mid-2026 values. Any symbol **not** in the dict falls back to `1000.0`. |
| **Impact** | When yfinance fails, mock candles diverge from actual market prices. Signals, risk-reward ratios, and position-sizing calculations downstream use these synthetic prices as if they were live. `trade_evaluator.py` explicitly demotes mock-sourced trades from learning-eligibility, but the UI still shows them without a clear "SYNTHETIC" banner unless the operator reads the `data_source` field. |
| **Audit status** | CONFIRMED (source only) |

### 1.2 — `INITIAL_CAPITAL = 5000.0` in `phase10_analytics.py` and `copilot_engine.py`
| Field | Value |
|-------|-------|
| **Files** | `artifacts/api-server/src/python/phase10_analytics.py` L35; `artifacts/api-server/src/python/copilot_engine.py` L48 |
| **Severity** | HIGH |
| **Finding** | Both modules define `INITIAL_CAPITAL = 5000.0`. The canonical system capital (Phase 20 durable settings + `portfolio_store.py` + `paper_trader.py`) is **₹1,00,000**. The Phase 10 analytics page therefore computes return percentages, equity curves, monthly P&L, and drawdown statistics against a ₹5,000 base rather than ₹1,00,000. The Copilot engine also calculates `realized_pnl = total_value - INITIAL_CAPITAL` using the wrong base. |
| **Impact** | Every analytics panel on the Phase 10 / Copilot path shows return percentages that are **20× inflated** relative to the real capital base (e.g. a ₹200 gain shows as +4% instead of +0.2%). |
| **Audit status** | CONFIRMED (source only) |

### 1.3 — `paper_trader.py` docstring claims ₹5,00,000 (₹500,000) initial capital
| Field | Value |
|-------|-------|
| **File** | `artifacts/api-server/src/python/paper_trader.py` L7, L859 |
| **Severity** | MEDIUM |
| **Finding** | The module-level docstring states `Initial capital: ₹5,00,000`. The `reset_portfolio()` function comment also references `₹5,00,000 cash`. The actual runtime constant defined on L29 is `INITIAL_CAPITAL = 100_000.0` (₹1,00,000), which reads from `portfolio_store.get_initial_capital()`. The docstring and reset comment are stale by a factor of 5×. |
| **Impact** | Documentation misleads operators and developers about reset behaviour; reset actually restores to ₹1,00,000, not ₹5,00,000. |
| **Audit status** | CONFIRMED (source only) |

### 1.4 — `phase8_config.json` `order_value_max = 1500` (stale; live executor uses 15,000)
| Field | Value |
|-------|-------|
| **File** | `artifacts/api-server/src/python/phase8_config.json` (key `safety_controls.order_value_max`) |
| **Severity** | HIGH |
| **Finding** | The JSON file contains `"order_value_max": 1500.0`. Per `APEXQUANT_BOOTSTRAP_CAP_15000_UPDATE_REPORT.md`, the cap was raised to ₹15,000 in `phase20_executor.py` (`_BOOTSTRAP_MAX_ORDER_VALUE = 15_000`). The JSON config file was **not updated**. Any reader that loads `phase8_config.json` directly will enforce a ₹1,500 cap instead of the intended ₹15,000. |
| **Impact** | If any code path reads `phase8_config.json` at runtime to enforce order limits, live bootstrap trades will be blocked at 1/10th the intended value. UNKNOWN: which callers still read this file vs. which call the executor constant. |
| **Audit status** | CONFIRMED (source only); runtime enforcement path UNKNOWN |

### 1.5 — `PaperAnalytics.test.tsx` seeds `initial_capital: 500000`
| Field | Value |
|-------|-------|
| **File** | `artifacts/trading-dashboard/src/pages/PaperAnalytics.test.tsx` L99, L102, L117 |
| **Severity** | LOW |
| **Finding** | Test fixtures use `initial_capital: 500000` (₹5,00,000) while the system canonical value is ₹1,00,000. |
| **Impact** | Tests pass against an unrealistic capital baseline; a ₹100,000 value from the live API would cause percentage/equity curve assertions to fail if the tests were modified to compare absolute amounts. Low severity while tests remain isolated. |
| **Audit status** | CONFIRMED (source only) |

### 1.6 — NSE holiday list duplicated in two places with identical content
| Field | Value |
|-------|-------|
| **Files** | `artifacts/api-server/src/python/nse_holidays.json`; `artifacts/api-server/src/python/market_hours.py` L38–53 (`_DEFAULT_HOLIDAYS` dict) |
| **Severity** | MEDIUM |
| **Finding** | The JSON file and the Python fallback dict contain identical 2026 NSE holiday entries. The code loads the JSON file and falls back to the dict on file-read failure. Both sources contain only **2026 dates**; there is no 2027 or multi-year holiday data. |
| **Impact** | After December 31, 2026 the system will have no holiday data unless the file/dict is updated. Market-hours decisions will treat every day as a trading day. |
| **Audit status** | CONFIRMED (source only); expiry date risk is certain if system remains live past 2026. |

---

## 2. Stale or Fallback Data

### 2.1 — `kite_instruments_cache.json` contains a single instrument from 2026-08-09
| Field | Value |
|-------|-------|
| **File** | `artifacts/api-server/src/python/kite_instruments_cache.json` |
| **Severity** | HIGH |
| **Finding** | The file has `"count": 1`, `"date": "2026-08-09"`, `"fetched_at": "2026-08-09T09:32:09Z"`. Kite instrument tokens are needed for live LTP overlay for all 23 custom universe symbols; only 1 instrument token is cached. |
| **Impact** | All 22 remaining custom-universe symbols will have `instrument_token = null` until a fresh Kite session is established and the cache is hydrated. The Kite LTP overlay will fall back to yfinance close prices for 22/23 symbols. |
| **Audit status** | CONFIRMED (file content) |

### 2.2 — `market_context_cache.json` has no timestamp field; age is UNKNOWN
| Field | Value |
|-------|-------|
| **File** | `artifacts/api-server/src/python/market_context_cache.json` |
| **Severity** | MEDIUM |
| **Finding** | The cache file contains `nifty_price`, `banknifty_price`, `nifty_trend`, etc. but no `timestamp`, `fetched_at`, or `created_at` field. The age of the cached market context cannot be determined by static inspection. |
| **Impact** | Stale market context (e.g. wrong regime classification) could silently affect scanner confidence modifiers, sector strength scores, and AI decision weighting without any operator-visible staleness indicator. |
| **Audit status** | PARTIALLY CONFIRMED (file structure); age UNKNOWN |

### 2.3 — `intelligence_cache.json` has no timestamp; age UNKNOWN
| Field | Value |
|-------|-------|
| **File** | `artifacts/api-server/src/python/intelligence_cache.json` |
| **Severity** | MEDIUM |
| **Finding** | Analogous to 2.2. The intelligence cache (market health score, regime, breadth) lacks a timestamp field. |
| **Audit status** | CONFIRMED (no `timestamp` key present) |

### 2.4 — `phase7_scan_cache.json` lacks a `timestamp` key; only `scan_id` is present
| Field | Value |
|-------|-------|
| **File** | `artifacts/api-server/src/python/phase7_scan_cache.json` |
| **Severity** | MEDIUM |
| **Finding** | File has a `scan_id` (`8ea114ecb962`) but neither `timestamp` nor `ts`. The health readiness probe at `health.ts` L52 checks only that this file is *readable* (`fs.accessSync`), not that its content is recent. |
| **Impact** | A stale scan cache file from a prior session passes the readiness probe unchanged. UNKNOWN: whether the scanner's internal freshness logic (`scan_state_store` DB row) correctly supersedes this file. |
| **Audit status** | CONFIRMED (file content) |

### 2.5 — Economic calendar dates are computed from `_NOW.year` at module import time
| Field | Value |
|-------|-------|
| **File** | `artifacts/api-server/src/python/macro_intelligence/economic_calendar.py` L45, L91, L144, L181, L235, L290, L320 |
| **Severity** | MEDIUM |
| **Finding** | All economic event dates (RBI MPC, CPI, GDP, PMI, US FOMC, ECB) are generated at module-import time using `_NOW = datetime.now(timezone.utc)` and `y = _NOW.year`. RBI MPC and US FOMC dates are approximate (mid-month) and not sourced from any live calendar API. |
| **Impact** | (a) If the module is imported once at process start and cached, all "upcoming/past" classifications are frozen at startup time. (b) The approximated dates diverge from actual announcement dates (e.g. RBI MPC may not fall exactly on Feb-05, Apr-09). |
| **Audit status** | CONFIRMED (source only) |

### 2.6 — Synthetic mock candles have no staleness indicator in UI
| Field | Value |
|-------|-------|
| **Files** | `artifacts/api-server/src/python/market_data_engine.py` L137–181; `artifacts/api-server/src/python/trade_evaluator.py` L394–400 |
| **Severity** | HIGH |
| **Finding** | When yfinance fails, `_generate_mock_candles()` produces synthetic OHLCV data stamped with `datetime.now()` timestamps, making them appear as live data. The `data_source = "mock"` flag is tracked in `_LAST_SOURCES` in-process but this is an in-memory dict that resets on restart. The Signals page and Scanner page do not visibly surface `data_source = "mock"` in the displayed cards. |
| **Impact** | Operators may act on synthetic scanner signals without realising data is generated rather than market-fetched. |
| **Audit status** | CONFIRMED (source only); UI surfacing UNKNOWN without runtime inspection |

---

## 3. Duplicated Calculations / Stores

### 3.1 — Two parallel capital/PnL computation stacks: `paper_trader.py` and `src/portfolio/`
| Field | Value |
|-------|-------|
| **Files** | `artifacts/api-server/src/python/paper_trader.py`; `artifacts/api-server/src/python/portfolio_store.py`; `artifacts/api-server/src/python/src/portfolio/pnl.py`; `artifacts/api-server/src/python/src/portfolio/service.py` |
| **Severity** | HIGH |
| **Finding** | Two completely separate portfolio tracking stacks coexist: (a) the legacy `paper_trader.py` + `portfolio_store.py` (JSON + Postgres `phase20_kv`), used by `main.py` and all live command dispatch; (b) the RC-10C1 `src/portfolio/` package (SQLAlchemy models, `PnLEngine`, `ExposureEngine`, `PortfolioService`) which `main.py` instantiates at startup (L179, L234) but the `main.py` command router still delegates portfolio operations to the legacy `paper_trader`/`portfolio_store` path. |
| **Impact** | Two PnL engines (`portfolio_store.py::get_portfolio_snapshot` and `src/portfolio/pnl.py::PnLEngine`) run in parallel. Portfolio values shown on the Dashboard and PortfolioLive page are sourced from the legacy stack; the RC-10C1 stack may have diverging state. Any discrepancy between the two is silently invisible to operators. |
| **Audit status** | CONFIRMED (source only); runtime DB divergence UNKNOWN |

### 3.2 — `position_sizer.py` duplicated in two locations with different APIs
| Field | Value |
|-------|-------|
| **Files** | `artifacts/api-server/src/python/position_sizer.py`; `artifacts/api-server/src/python/src/portfolio/position_sizer.py` |
| **Severity** | MEDIUM |
| **Finding** | Two `position_sizer` modules exist. The top-level one exposes `compute_position()` and `compute_from_signal()` using `INITIAL_CAPITAL` from `config.py`. The `src/portfolio` one exposes `calculate_size()` (async, `PortfolioConfig`-driven, `PortfolioSizer` class). The two are not wired together. |
| **Impact** | Bootstrap entry sizing uses the top-level sizer; the RC-10C1 framework uses the scoped sizer. If `PortfolioConfig` limits differ from `config.py` limits, the two callers may produce different trade sizes for the same signal. |
| **Audit status** | CONFIRMED (source only) |

### 3.3 — Sector exposure computed in both `portfolio_snapshot.py` and `src/portfolio/exposure.py`
| Field | Value |
|-------|-------|
| **Files** | `artifacts/api-server/src/python/portfolio_snapshot.py` L319–398; `artifacts/api-server/src/python/src/portfolio/exposure.py` L250 (`check_sector_exposure`) |
| **Severity** | MEDIUM |
| **Finding** | Both modules independently derive sector exposure ratios and generate warnings. The UI (`PortfolioLive.tsx`, `LiveCommandCenter.tsx`) reads exclusively from the `portfolio_snapshot` path. The `src/portfolio/exposure.py` exposure engine is invoked by `PortfolioService` (RC-10C1 path) and writes to the RC-10C1 database, not to the legacy Postgres store that the snapshot endpoint reads. |
| **Impact** | Two different breach-detection calculations may emit conflicting CRITICAL/WARNING signals. Only the legacy path is surfaced in the operator UI; the RC-10C1 path's breach events are silently discarded or stored in a table not consumed by any UI endpoint. |
| **Audit status** | CONFIRMED (source only) |

### 3.4 — `INITIAL_CAPITAL` defined in four separate Python modules
| Field | Value |
|-------|-------|
| **Files** | `config.py` L11 (100,000); `portfolio_store.py` L71 (100,000); `paper_trader.py` L29 (100,000); `phase10_analytics.py` L35 (5,000); `copilot_engine.py` L48 (5,000) |
| **Severity** | MEDIUM |
| **Finding** | Five independent definitions of `INITIAL_CAPITAL` exist. The three canonical ones agree on ₹1,00,000 but the two legacy ones use ₹5,000. A future change to the canonical capital will miss the `phase10_analytics` and `copilot_engine` definitions. |
| **Audit status** | CONFIRMED |

### 3.5 — Two SQLite databases with empty schemas on disk
| Field | Value |
|-------|-------|
| **Files** | `artifacts/api-server/src/python/trading.db`; `artifacts/api-server/src/python/trade_intelligence.db` |
| **Severity** | LOW |
| **Finding** | Both SQLite files exist but returned empty `.schema` output. `trade_intelligence.py`, `historical_knowledge_builder.py`, `root_cause_engine.py`, `confidence_calibration.py`, `strategy_intelligence.py`, and `phase14_learning.py` all target `trade_intelligence.db` via `DB_PATH`. `trading.db` has no evident writer. |
| **Impact** | If the process creates schema lazily on first access and the files are empty placeholders, this is benign. However, if production deployments use the Postgres path exclusively, these SQLite files are dead artefacts accumulating. UNKNOWN: whether any hot path actually writes to SQLite at runtime. |
| **Audit status** | CONFIRMED (empty schemas); runtime write activity UNKNOWN |

---

## 4. API Fields with Unclear UI Consumers

### 4.1 — `paper_fallback_count` / `paper_fallback_reasons` in reconciliation publish payload
| Field | Value |
|-------|-------|
| **Files** | `intraday-trading-bot/src/brokers/zerodha/reconciliation_publisher.py` L38–41; `artifacts/api-server/src/routes/reconciliation.ts` L77–115 |
| **Severity** | LOW |
| **Finding** | The reconciliation publish endpoint (`POST /api/broker/reconciliation/publish`) accepts `paper_fallback_count` and `paper_fallback_reasons`. These fields are stored in the reconciliation store but it is UNKNOWN whether `BrokerExecution.tsx` or any other UI page renders these fields. |
| **Audit status** | UNKNOWN (field path not found in dashboard source within search window) |

### 4.2 — `api_build_id` appended to trading data responses
| Field | Value |
|-------|-------|
| **File** | `artifacts/api-server/src/routes/trading.ts` L1341 |
| **Severity** | LOW |
| **Finding** | `api_build_id` is appended to the scan/trade response object. No dashboard component was found to display or log this field. |
| **Audit status** | UNKNOWN (may be for logging/debugging only) |

### 4.3 — `learn_eligible` flag in `trade_evaluator.py` output
| Field | Value |
|-------|-------|
| **File** | `artifacts/api-server/src/python/trade_evaluator.py` L394 |
| **Severity** | LOW |
| **Finding** | The `learn_eligible` integer (0 or 1) is written to every trade evaluation record. No UI panel was found to display this field; it is likely consumed only by the learning engine. If the learning engine is disabled or ignoring the field, learning decisions based on bad mock data could silently proceed. |
| **Audit status** | UNKNOWN |

### 4.4 — `sector_exposures` field in portfolio snapshot available in Phase4A but format differs
| Field | Value |
|-------|-------|
| **Files** | `artifacts/trading-dashboard/src/pages/Phase4ASession.tsx` L481–485, L962–965; `artifacts/trading-dashboard/src/pages/PortfolioLive.tsx` L1470 |
| **Severity** | LOW |
| **Finding** | `Phase4ASession.tsx` treats `sector_exposure` as a `Record<string, number>` (flat object); `PortfolioLive.tsx` treats `sector_exposures` as `SectorExposure[]` (array of objects). The API returns the array form (`portfolio_snapshot.py` L347 returns a list). Any `Phase4ASession` monitoring row that renders `sector_exposure` may receive an unexpected array and silently display nothing or break the iteration. |
| **Audit status** | CONFIRMED mismatch (source only); UI runtime rendering UNKNOWN |

---

## 5. UI Fields with Unknown Sources

### 5.1 — `Phase11` pages call `/phase11/*` routes; source data is paper_trader legacy path
| Field | Value |
|-------|-------|
| **Files** | `artifacts/trading-dashboard/src/pages/Phase11SummaryPage.tsx`; `Phase11PortfolioPage.tsx`; `Phase11ReplayPage.tsx`; `Phase11ReportsPage.tsx`; `Phase11TimelinePage.tsx` |
| **Severity** | MEDIUM |
| **Finding** | Five UI pages render data from `/phase11/calendar`, `/phase11/daily-summary`, `/phase11/portfolio`, `/phase11/open-positions`, `/phase11/closed-positions`, `/phase11/replay`, `/phase11/reports/*`. These all ultimately call `paper_trader._load_state()` or `portfolio_store` through `main.py`. The data returned by these endpoints does **not** include any `data_source` or `snapshot_age` field visible in the route handlers (`phase11.ts`). Operators cannot tell whether the displayed portfolio is fresh or from a pre-restart snapshot. |
| **Audit status** | CONFIRMED (source only); freshness of underlying state UNKNOWN |

### 5.2 — `market_health_score` on Market Intelligence Hub has no documented formula
| Field | Value |
|-------|-------|
| **Files** | `artifacts/api-server/src/python/market_intelligence_hub/intelligence_summary.py`; `artifacts/trading-dashboard/src/pages/MarketIntelligenceHub.tsx` |
| **Severity** | LOW |
| **Finding** | The `market_health_score` field is displayed prominently in the MI Hub but its formula is embedded in `intelligence_summary.py` without a docstring describing the exact composite inputs, weights, or update cadence. |
| **Audit status** | UNKNOWN (computation exists but formula not audited) |

### 5.3 — `CommandCenter.tsx` renders `Phase11Snapshot` from `/phase11/snapshot`; field types not contracted in Zod
| Field | Value |
|-------|-------|
| **Files** | `artifacts/trading-dashboard/src/pages/CommandCenter.tsx` L1000; `artifacts/trading-dashboard/src/pages/PortfolioLive.tsx` L586 |
| **Severity** | LOW |
| **Finding** | Both pages call `apiJson<Phase11Snapshot>("phase11/snapshot")` but the `Phase11Snapshot` type is a local TypeScript interface, not a shared Zod schema. If the Python handler changes the response shape, TypeScript will still compile and no runtime validation error will surface. |
| **Audit status** | CONFIRMED (source only) |

---

## 6. Likely Dead Endpoints / Hooks

### 6.1 — `phase239` acceptance/export routes have only one navigation entry
| Field | Value |
|-------|-------|
| **Files** | `artifacts/api-server/src/routes/phase239.ts`; `artifacts/trading-dashboard/src/components/layout/AgentConfig.ts` L249 |
| **Severity** | LOW |
| **Finding** | The phase239 routes (`/api/phase239/export/:report/:format`, `/api/phase239/acceptance`) are mounted and reachable. The only UI reference is a navigation tag entry (label "Validation Dashboard", tag "phase23.9"). No `useQuery` or `apiJson` call to `phase239/*` was found in the UI. The export functionality is likely invoked only from the Validation Dashboard page (not found explicitly). |
| **Audit status** | UNKNOWN |

### 6.2 — Advisory route always returns 404/DISABLED; no environment flag enables it
| Field | Value |
|-------|-------|
| **Files** | `artifacts/api-server/src/routes/advisory.ts` L22–30; `artifacts/api-server/src/lib/advisoryFlags.ts` |
| **Severity** | LOW |
| **Finding** | The advisory API always returns 404 `{"status": "DISABLED"}` because no environment variable `ADVISORY_BOTS_ENABLED=true` is set in any visible config. The route is mounted and wasted CPU cycles for every 404 request. No UI component in `trading-dashboard/src` references `advisoryBotsEnabled` or `advisoryUiEnabled`. |
| **Audit status** | CONFIRMED (default flags are all `false`); whether any env file enables them in production UNKNOWN |

### 6.3 — `controlledPaperEntry` route; `executionAllowed` is hardcoded `false`
| Field | Value |
|-------|-------|
| **File** | `artifacts/api-server/src/lib/controlledPaperEntryFlags.ts` L43 |
| **Severity** | LOW |
| **Finding** | The `ControlledPaperEntryFlags` type declares `executionAllowed: false` as a literal (never `true`). This ensures no execution ever happens through this path regardless of environment configuration. The route is reachable and may receive POST requests from the UI (`/api/controlled-paper-entry/*`) but will always block execution. Whether this is intentional as a safety gate or accidentally blocks a needed path is UNKNOWN. |
| **Audit status** | CONFIRMED (source only) |

### 6.4 — `phase4a-session` route is registered but Phase 4A session context is superseded by Mission Control
| Field | Value |
|-------|-------|
| **Files** | `artifacts/trading-dashboard/src/App.tsx` L198; `artifacts/trading-dashboard/src/pages/Phase4ASession.tsx` |
| **Severity** | LOW |
| **Finding** | The Phase4A session page still calls `/phase4a/premarket`, `/phase4a/monitor/tick`, `/phase4a/trade-journal`, etc. These routes are alive in `phase4a.ts`. The page is accessible via `/phase4a-session`. Whether operators still use it or it has been superseded by newer monitoring pages (Mission Control, LiveCommandCenter) is UNKNOWN. |
| **Audit status** | UNKNOWN |

---

## 7. Obsolete Tables / Legacy Paths

### 7.1 — 50+ legacy `phase*.json` flat-file state stores alongside Postgres
| Field | Value |
|-------|-------|
| **Directory** | `artifacts/api-server/src/python/` |
| **Severity** | MEDIUM |
| **Finding** | Fifty JSON files matching `phase*.json` exist in the Python directory (e.g. `phase7_scan_cache.json`, `phase8_audit.json`, `phase8_config.json`, `phase9_alerts.json` … through `phase22_evidence.json`). The architecture note in `signals_store.py` states Postgres is authoritative with JSON files as warm caches for local dev. However, many files (e.g. `phase8_config.json`, `phase12_cache.json`, `phase13_proposals.json`) appear to be **write targets** of Python modules that may not have Postgres equivalents. These may accumulate stale data forever after a Postgres migration. |
| **Impact** | If a new Autoscale instance starts fresh (ephemeral disk) it loses any state that was never written to Postgres. Legacy phases that write only to JSON have no durable store on new instances. |
| **Audit status** | CONFIRMED (file existence); Postgres coverage per file UNKNOWN |

### 7.2 — `intraday-trading-bot` uses a separate `INTRADAY_DATABASE_URL` schema that never feeds the dashboard directly
| Field | Value |
|-------|-------|
| **Files** | `intraday-trading-bot/src/core/config.py` L143; `intraday-trading-bot/src/brokers/zerodha/reconciliation_publisher.py` L4 |
| **Severity** | MEDIUM |
| **Finding** | The intraday bot runs against a fully separate Postgres database (`INTRADAY_DATABASE_URL`). The reconciliation publisher is the **only** bridge to the dashboard (`POST /api/broker/reconciliation/publish`). No other bot data (fills, positions, orders, sessions, incidents) is accessible to dashboard operators without a direct DB query. If `RECON_PUBLISH_URL` or `RECON_PUBLISH_TOKEN` are not set, the bot operates in complete silence from the dashboard's perspective. |
| **Impact** | Operators have no visibility into intraday-bot state beyond what the reconciliation probe publishes. Fill confirmations, open positions, kill-switch level changes, and heartbeats are invisible to the dashboard. |
| **Audit status** | CONFIRMED (source only); environment variable values UNKNOWN |

### 7.3 — `copilot_engine.py` writes to a `state.json` file in process working directory
| Field | Value |
|-------|-------|
| **File** | `artifacts/api-server/src/python/copilot_engine.py` L38 (`STATE_FILE = "state.json"`) |
| **Severity** | MEDIUM |
| **Finding** | `copilot_engine.py` resolves its state file as a relative path `"state.json"`, which will resolve to the process working directory. If the API server runs from the workspace root rather than the python directory, this file will be written to an unexpected location (workspace root) and may not be readable on restart. |
| **Audit status** | CONFIRMED (source only); actual cwd at runtime UNKNOWN |

### 7.4 — `trading.db` and `trade_intelligence.db` are empty SQLite files
| Field | Value |
|-------|-------|
| **Files** | `artifacts/api-server/src/python/trading.db`; `artifacts/api-server/src/python/trade_intelligence.db` |
| **Severity** | LOW (see 3.5) |
| **Finding** | Multiple modules reference `trade_intelligence.db` via `DB_PATH`. The files exist on disk with empty schemas, suggesting they were either never written to (production uses Postgres) or were created by migration tests and never populated. No Alembic or schema-init code was found targeting `trading.db`. |
| **Audit status** | CONFIRMED (empty schemas); production write activity UNKNOWN |

---

## 8. Impossible / Negative Data Risks

### 8.1 — `analytics_engine.py` silently replaces `starting_capital <= 0` with `1.0`
| Field | Value |
|-------|-------|
| **File** | `artifacts/api-server/src/python/analytics_engine.py` L64–65 |
| **Severity** | MEDIUM |
| **Finding** | If `starting_capital` is zero or negative (e.g. after a full capital drawdown), the analytics engine silently resets it to `1.0` and continues calculating return percentages. A total-loss scenario would produce `+∞%` return on the equity curve instead of a clear error. |
| **Impact** | Performance analytics displays nonsensical percentage returns instead of surfacing a "capital exhausted" or "invalid capital" condition. |
| **Audit status** | CONFIRMED (source only) |

### 8.2 — `position_sizer.py` allows `qty = 0` without hard rejection
| Field | Value |
|-------|-------|
| **File** | `artifacts/api-server/src/python/position_sizer.py` L82–87 |
| **Severity** | MEDIUM |
| **Finding** | When `stop_distance <= 0` or `entry_price <= 0`, the function sets `qty = 0` and continues. The returned `PositionSizing` object has `suggested_quantity = 0`. Downstream callers check `suggested_quantity > 0` (e.g. `explainability.py` L199) but the path from `opportunity_scanner.py` does not explicitly filter qty=0 trades before appending them to the opportunity list. |
| **Impact** | A qty=0 opportunity could appear in the scanner output and be displayed to operators as a viable entry, with ₹0 investment and 0 units. |
| **Audit status** | CONFIRMED (source only); opportunity list filtering UNKNOWN at runtime |

### 8.3 — Negative PnL accepted in `trade_evaluator.py` with no floor
| Field | Value |
|-------|-------|
| **File** | `artifacts/api-server/src/python/trade_evaluator.py` L325 |
| **Severity** | LOW |
| **Finding** | The trade evaluator allows `exit_price <= 0` to be caught only for data-quality rejection. But an `exit_price` that is legitimately small (e.g. a penny stock exit) would not be caught. More importantly, a negative `entry_price` is only checked at the outer gate; a downstream `net_pnl = (exit - entry) * qty - costs` calculation would produce a numerically impossible positive return for a negative entry_price. |
| **Audit status** | CONFIRMED (source only); whether a negative price can reach this path in practice UNKNOWN |

### 8.4 — Portfolio cash balance can drift below zero without a hard circuit breaker
| Field | Value |
|-------|-------|
| **File** | `artifacts/api-server/src/python/paper_trader.py` L301 |
| **Severity** | MEDIUM |
| **Finding** | `paper_trader.py` checks `cash >= total_cost` before a BUY (`return False, "Insufficient cash: need ₹…"`) but there is no atomic lock preventing two concurrent BUY calls from both passing the check before either reduces the cash balance. On a multi-instance Autoscale deployment, a race window could produce cash < 0. |
| **Impact** | A negative cash balance is not impossible and is not guarded by the `portfolio_deployed_cap_pct` limit alone (that limit only applies to the pre-check). |
| **Audit status** | CONFIRMED (source only); runtime concurrency risk depends on Autoscale deployment, UNKNOWN |

---

## 9. Missing Refresh / Error Handling

### 9.1 — `PortfolioLive.tsx` snapshot polls every 15 s; scan scheduler minimum cadence is 3 min
| Field | Value |
|-------|-------|
| **Files** | `artifacts/trading-dashboard/src/pages/PortfolioLive.tsx` L251 (`REFRESH_INTERVAL = 15_000`); `artifacts/api-server/src/lib/scanScheduler.ts` L18 (`TICK_INTERVAL_MIN = 1`); `artifacts/api-server/src/python/phase20_store.py` (`ALLOWED_INTERVALS = (3, 4, 5, 6, 10, 15)`) |
| **Severity** | MEDIUM |
| **Finding** | The portfolio snapshot is polled every 15 seconds, but the underlying scan data cannot change faster than every 3 minutes (minimum scan interval). Each 15-second poll hits the Python subprocess chain, adding overhead with no new data 99% of the time. More critically, Task #107 (open) notes that operators may see a stale snapshot for up to 15 seconds after the API server restarts; the 15-second poll interval is the maximum staleness window, not a problem, but there is no "snapshot is stale" visual indicator if the most recent scan was >15 minutes ago. |
| **Audit status** | CONFIRMED (source only) |

### 9.2 — `operations.ts`, `security.ts`, and `risk-validation.ts` swallow parse errors silently
| Field | Value |
|-------|-------|
| **Files** | `artifacts/api-server/src/routes/operations.ts` L32; `artifacts/api-server/src/routes/security.ts` L32; `artifacts/api-server/src/routes/risk-validation.ts` L29 |
| **Severity** | MEDIUM |
| **Finding** | All three routes contain `try { const p = JSON.parse(stdout.trim()); if (p.error) return reject(new Error(p.error)); } catch {}`. The empty `catch {}` means a JSON parse failure is silently swallowed; the outer promise continues with `undefined` as the parsed result, which the route then attempts to send to the client, likely causing a 500 or an empty response. |
| **Impact** | Python subprocess failures (malformed output, partial JSON, encoding errors) are invisible in logs from these three routes. Operators see an empty or 500 response with no actionable error message. |
| **Audit status** | CONFIRMED (source only) |

### 9.3 — `pipeline.ts` swallows tick-tail startup errors with `.catch(() => {})`
| Field | Value |
|-------|-------|
| **File** | `artifacts/api-server/src/routes/pipeline.ts` L141 |
| **Severity** | LOW |
| **Finding** | The pipeline tail startup call uses `.catch(() => {})` — any failure in the tail initialization is silently ignored. Operators relying on the pipeline tail for scan progress updates will see no data without any error indication. |
| **Audit status** | CONFIRMED |

### 9.4 — Scan scheduler OHLCV cold-start gate: if Python rejects, scans may never start
| Field | Value |
|-------|-------|
| **File** | `artifacts/api-server/src/lib/scanScheduler.ts` L66–78 |
| **Severity** | MEDIUM |
| **Finding** | `_ohlcvColdStartPending = true` blocks all scheduled scans until a Python process completes the cold-start check. The comment states the gate is cleared in the `.finally()` handler. If the `.finally()` does not execute (e.g. Node.js process crash/restart before promise resolution), the gate would remain `true` forever on that instance, permanently blocking scheduled scans without any operator-visible error. UNKNOWN: whether the `.finally()` is always reachable after a process restart. |
| **Audit status** | CONFIRMED (source only); restart edge case UNKNOWN |

### 9.5 — `health/ready` endpoint: `scanner_coverage_ok = false` does not block readiness
| Field | Value |
|-------|-------|
| **File** | `artifacts/api-server/src/routes/health.ts` L90–100 |
| **Severity** | MEDIUM |
| **Finding** | The readiness endpoint sets `ready = checks["python_runtime"] === true` only; `scanner_coverage_ok = false` produces a warning but does not set `ready = false`. A deployment where scanner coverage has a persistent failure (weekend gap, stale symbols) will still return HTTP 200 "ready", potentially causing load balancers to send traffic to a degraded instance. |
| **Audit status** | CONFIRMED |

### 9.6 — `ConnectivityPanel.tsx` polling uses `setInterval` not React Query; no error boundary
| Field | Value |
|-------|-------|
| **File** | `artifacts/trading-dashboard/src/components/ConnectivityPanel.tsx` L41, L64 |
| **Severity** | LOW |
| **Finding** | Connectivity pings run on a raw `setInterval` (30-second cadence) stored in a `useRef`. If the component unmounts or the ref is garbage-collected, the interval timer reference is lost and cannot be cleared, creating a potential timer leak. No error boundary or retry-count cap was observed in the component. |
| **Audit status** | CONFIRMED (source only) |

---

## 10. Summary Table

| ID | Category | Severity | File / Location | Impact |
|----|----------|----------|-----------------|--------|
| 1.1 | Hardcoded seed prices | HIGH | `market_data_engine.py` L126–130 | Synthetic OHLCV presented as live |
| 1.2 | Wrong INITIAL_CAPITAL | HIGH | `phase10_analytics.py` L35; `copilot_engine.py` L48 | Analytics 20× inflated returns |
| 1.3 | Stale docstring capital | MEDIUM | `paper_trader.py` L7, L859 | Documentation drift: reset to ₹100k, doc says ₹500k |
| 1.4 | Stale JSON order cap | HIGH | `phase8_config.json` (1500 vs 15000) | Live path enforces 1/10th intended cap |
| 1.5 | Test fixture capital mismatch | LOW | `PaperAnalytics.test.tsx` L99 | Test coverage gap |
| 1.6 | Duplicate + expiring holiday data | MEDIUM | `nse_holidays.json`; `market_hours.py` L38–53 | No 2027+ holiday data |
| 2.1 | Stale Kite instruments cache | HIGH | `kite_instruments_cache.json` | 22/23 custom symbols without live LTP |
| 2.2 | Market context cache has no timestamp | MEDIUM | `market_context_cache.json` | Age unknown; silent stale regime |
| 2.3 | Intelligence cache has no timestamp | MEDIUM | `intelligence_cache.json` | Same as 2.2 |
| 2.4 | Scan cache has no timestamp | MEDIUM | `phase7_scan_cache.json` | Readiness probe passes on stale cache |
| 2.5 | Economic calendar uses approximate/static dates | MEDIUM | `economic_calendar.py` L45–320 | MPC/FOMC dates may be wrong |
| 2.6 | Mock candles appear as live data | HIGH | `market_data_engine.py` L137–181 | Operators may trade on synthetic signals |
| 3.1 | Dual portfolio stacks (paper_trader + RC-10C1) | HIGH | `paper_trader.py`; `src/portfolio/service.py` | Diverging PnL state, invisible to operators |
| 3.2 | Dual position sizers | MEDIUM | `position_sizer.py` ×2 | Different sizing results for same signal |
| 3.3 | Dual sector exposure engines | MEDIUM | `portfolio_snapshot.py`; `src/portfolio/exposure.py` | Conflicting CRITICAL breach signals |
| 3.4 | INITIAL_CAPITAL defined 5 times | MEDIUM | Multiple files | Capital drift on future changes |
| 3.5 | Empty SQLite DB files | LOW | `trading.db`; `trade_intelligence.db` | Possible dead artefacts |
| 4.1 | `paper_fallback_count` field unused in UI | LOW | Reconciliation publish endpoint | Visibility gap |
| 4.2 | `api_build_id` in scan response, no UI consumer | LOW | `trading.ts` L1341 | Cosmetic |
| 4.3 | `learn_eligible` field, UI consumer unknown | LOW | `trade_evaluator.py` L394 | Learning pipeline opacity |
| 4.4 | `sector_exposure` type mismatch (object vs array) | LOW | `Phase4ASession.tsx` L481 | Possible silent rendering failure |
| 5.1 | Phase11 pages lack snapshot freshness indicator | MEDIUM | Phase11 page set | Operators see data of unknown age |
| 5.2 | `market_health_score` formula undocumented | LOW | `intelligence_summary.py` | Auditability gap |
| 5.3 | `Phase11Snapshot` type not Zod-validated | LOW | `CommandCenter.tsx` L1000 | No runtime shape guard |
| 6.1 | Phase239 routes with no confirmed UI consumer | LOW | `phase239.ts` | Dead or orphaned endpoints |
| 6.2 | Advisory route always 404/DISABLED | LOW | `advisory.ts`; `advisoryFlags.ts` | Wasted route mount |
| 6.3 | `controlledPaperEntry` executionAllowed hardcoded false | LOW | `controlledPaperEntryFlags.ts` L43 | Permanent execution block |
| 6.4 | Phase4A session page may be superseded | LOW | `Phase4ASession.tsx` | Navigation confusion |
| 7.1 | 50+ legacy phase JSON flat files | MEDIUM | `artifacts/api-server/src/python/` | State loss on Autoscale cold start |
| 7.2 | Intraday bot DB fully isolated; only recon bridge | MEDIUM | Bot reconciliation publisher | Bot state invisible to dashboard |
| 7.3 | `copilot_engine.py` state.json relative path | MEDIUM | `copilot_engine.py` L38 | State file written to wrong dir |
| 7.4 | Empty SQLite files (same as 3.5) | LOW | Both `.db` files | Legacy artefacts |
| 8.1 | `analytics_engine.py` replaces ≤0 capital with 1.0 | MEDIUM | `analytics_engine.py` L64–65 | Infinite/nonsensical returns |
| 8.2 | qty=0 PositionSizing not filtered upstream | MEDIUM | `position_sizer.py` L82–87 | Zero-quantity entry in opportunity list |
| 8.3 | Negative entry_price not floored in evaluator | LOW | `trade_evaluator.py` L325 | Numerical impossibility undetected |
| 8.4 | Cash balance race on Autoscale BUY | MEDIUM | `paper_trader.py` L301 | Potential cash < 0 |
| 9.1 | 15 s poll vs 3 min scan cadence; no staleness badge | MEDIUM | `PortfolioLive.tsx` L251 | No "stale scan" indicator |
| 9.2 | Empty `catch {}` silently swallows parse errors | MEDIUM | `operations.ts`, `security.ts`, `risk-validation.ts` | Invisible Python subprocess failures |
| 9.3 | Pipeline tail startup errors silently swallowed | LOW | `pipeline.ts` L141 | Pipeline offline without notice |
| 9.4 | Cold-start OHLCV gate may never clear on restart | MEDIUM | `scanScheduler.ts` L66–78 | Scans permanently blocked on restart |
| 9.5 | `scanner_coverage_ok=false` does not block readiness | MEDIUM | `health.ts` L90–100 | Degraded instance passes readiness probe |
| 9.6 | Raw setInterval in ConnectivityPanel | LOW | `ConnectivityPanel.tsx` L41 | Timer leak risk |

---

## 11. External System Freshness / Provenance Quality Assessment

| External System | Provider | Cache TTL | Staleness Risk | Notes |
|----------------|----------|-----------|----------------|-------|
| **NSE OHLCV (daily bars)** | yfinance (Yahoo Finance) | Configurable; `LIVE ≤3 days`, `NEAR_LIVE ≤5 days`, `STALE ≤14 days` (`ohlcv_cache_store.py`) | MEDIUM | Daily bars are end-of-day; intraday accuracy requires Kite overlay. yfinance has no SLA and rate-limits silently. |
| **NSE Live LTP (intraday)** | Zerodha Kite Connect | 30 s in-memory cache (`kite_quote_provider.py` L39) | HIGH | Token expires at 06:00 IST daily; only 1 instrument in cache as of 2026-08-09; falls back to yfinance close silently |
| **NSE Pre-Open Auction** | NSE Official API → Kite → Yahoo fallback | 55 s data TTL; session 270 s (`nse_preopen_provider.py`) | MEDIUM | NSE API requires cookie dance; any network block returns UNAVAILABLE silently; fallback chain may serve previous-day data during the pre-open window |
| **Global Indices / Commodities / Currencies** | yfinance `fast_info` | 300 s (5 min) in-memory cache (`global_markets.py`, `commodity_intelligence.py`) | MEDIUM | `fast_info` can return 0 or stale values when Yahoo servers are unavailable; no alerting on fallback to 0 price |
| **RBI MPC / FOMC / Economic Events** | Hardcoded approximate dates (`economic_calendar.py`) | Module-import time (static) | HIGH | Dates are approximate mid-month values; no live calendar API; may be wrong by days; no 2027 events |
| **NSE Holiday Calendar** | Hardcoded JSON file + Python fallback (`nse_holidays.json`) | Static file | HIGH | Covers 2026 only; no auto-update mechanism |
| **Kite Instrument Tokens** | Zerodha Kite Connect instruments API | Daily (`kite_instruments_cache.json`) | HIGH | Cache on disk shows only 1 of 23 symbols as of 2026-08-09; no auto-refresh trigger exists in code |
| **Intraday Bot Fills / Orders** | Zerodha Kite WebSocket / REST | Real-time in bot; published via HTTP to dashboard only at reconciliation time | HIGH | Dashboard has no real-time fill feed; depends entirely on periodic `POST /api/broker/reconciliation/publish` |
| **Paper Portfolio State** | PostgreSQL (Postgres `phase20_kv`) + JSON warm cache | On-write (no TTL) | LOW | Durable on Postgres; JSON file is warm cache only; Autoscale instances may diverge briefly |
| **Macro Intelligence (IMF/Forex)** | yfinance forex tickers | 300 s in-memory | MEDIUM | Same caveats as global indices |

**Overall external-data quality verdict:** The system's primary data path (daily OHLCV via yfinance + Kite LTP overlay) is structurally sound but critically dependent on (a) a valid Kite session being present at market open and (b) the instruments cache being populated for all symbols. Neither of these is auto-triggered; both require manual operator action. The economic calendar and NSE holiday data are the highest-risk static data assets, expiring at end-of-year 2026. The intraday bot's isolation means fill data provenance is opaque to dashboard operators beyond the reconciliation bridge.

---

*End of audit. No code was modified. No runtime environment was interrogated.*
