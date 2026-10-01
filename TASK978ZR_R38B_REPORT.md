# TASK978ZR-R38B — FINAL REPORT

## HISTORICAL DATA AUTHORITY + INTRADAY RESOLUTION + COST/SLIPPAGE PINNING + BACKTEST HARNESS DESIGN

- **Repository:** JMR2305/nse-trade-intraday
- **Branch:** task967-migration-guard-hardening
- **BASE_HEAD:** `5251da2dac0fbb1622f1533bb3f631df1ffa961a` (verified — matches EXPECTED_HEAD)
- **Predecessor:** TASK978ZR-R38A = PASS
- **Report generated:** 2026-10-01
- **Mode:** READ-ONLY audit + external official-document research + backtest methodology design. No source/test/CI/config edits. No DB access. No network calls to the trading stack. No backfill/backtest/replay runs.

---

## PHASE 0 — IDENTITY

```
git rev-parse HEAD  →  5251da2dac0fbb1622f1533bb3f631df1ffa961a  (matches EXPECTED_HEAD)
git status --short  →  clean of tracked changes
                       untracked only: __pycache__/ dirs, TASK_969_IDENTITY.json
R38B_BASE_HEAD       = 5251da2dac0fbb1622f1533bb3f631df1ffa961a
R38B_BRANCH          = task967-migration-guard-hardening
R38B_WORKTREE_STATUS = CLEAN (tracked); untracked artifacts pre-existing, untouched
```

---

## PHASE 1 — HISTORICAL MARKET-DATA STORES FOUND

| STORE_NAME | SOURCE_FILE | TABLE_OR_FILE | PK / key fields | Interval? | Source-provider field | Universe provenance |
|---|---|---|---|---|---|---|
| daily_ohlcv_cache | ohlcv_cache_store.py | PG `daily_ohlcv_cache` | PK (symbol, trading_date) | DAILY only (trading_date, no ts) | `source` (default 'yfinance') | YES (`data_quality`, freshness enum) — no universe column |
| daily_ohlcv_refresh_state | ohlcv_cache_store.py | PG `daily_ohlcv_refresh_state` | append-only log (symbol, trading_date) | daily | yes | no |
| backtest_candles | historical_data_engine.py | PG `backtest_candles` | PK (symbol, interval, ts TIMESTAMPTZ) | YES (interval in PK) | `source` (mock-guard) | no |
| backtest_candle_meta | historical_data_engine.py | PG `backtest_candle_meta` | (symbol, interval) coverage ranges | YES | yes | no |
| backtest_corporate_actions | historical_data_engine.py | PG `backtest_corporate_actions` | (symbol, date) SPLIT\|DIVIDEND | per-date event | yes | no |
| backtest_candle_cache | historical_data_engine.py | file `backtest_candle_cache/*.json` | symbol+interval JSON | YES | yes | no |
| scan/preopen/pipeline snapshot stores | phase20_store, preopen engine, pipeline events | PG tables (run-claimed, append-style) | run_id, ts | n/a | yes | YES (run-scoped) |
| historical_universe_resolution | custom_universe_store / backtest_runner | HISTORICAL_SNAPSHOT per target_date | session date | n/a | n/a | **YES (as-of)** |

No tick store. No quote store. No 1-minute store anywhere.

---

## PHASE 2 — OHLCV CACHE SCHEMA AUDIT

- **OHLCV_STORAGE_IMPLEMENTATION** = PostgreSQL dual-store: `daily_ohlcv_cache` (daily, yfinance primary + READ-ONLY Kite daily fallback `_fetch_single_kite_historical`, gated on ZERODHA_API_KEY + kite_token_store) + `backtest_candles` (intraday/daily candles via historical_data_engine `ensure_candles`, yfinance download, file fallback `backtest_candle_cache/*.json`).
- **OHLCV_STORAGE_TABLES** = `daily_ohlcv_cache`, `daily_ohlcv_refresh_state`, `backtest_candles`, `backtest_candle_meta`, `backtest_corporate_actions` (+ JSON file cache).
- **OHLCV_INTERVALS_SUPPORTED** = **5m, 10m (resampled from 5m), 15m, 1d**. **1m NOT supported anywhere.**
- **OHLCV_RETENTION_RULE** = no pruning found; append/upsert. Daily freshness: LIVE ≤3d, NEAR_LIVE ≤5d, STALE ≤14d; **MIN_BARS_REQUIRED = 120** (~6 months daily per symbol).
- **OHLCV_PRIMARY_TIMEZONE** = Asia/Kolkata (session-anchored dates; intraday ts TIMESTAMPTZ).
- **OHLCV_TIMESTAMP_SEMANTICS** = daily bar keyed by `trading_date` (bar-open semantics); intraday keyed by bar-open ts.
- **OHLCV_SOURCE_PROVIDER** = yfinance primary; Kite historical READ-ONLY fallback (daily only); mock sources exist and are flagged in `source` column with propagation guard through 10m resample.
- **OHLCV_WRITE_PATH** = yf download → upsert; refresh_state append.
- **OHLCV_READ_PATH** = `read_symbol_from_cache(..., end_date=)` as-of read (trading_date ≤ end_date, age vs end_date); `hde.ensure_candles` for candles.
- **OHLCV_DEDUP_RULE** = PK upsert (symbol+date / symbol+interval+ts).
- **OHLCV_FRESHNESS_RULE** = LIVE/NEAR_LIVE/STALE by age thresholds above.
- **OHLCV_READY_RULE** = ≥ MIN_BARS_REQUIRED (120) daily bars per symbol.
- **1-minute data exists**: **NO**.
- Mixed resolution exists across stores; within a store, interval is explicit.

---

## PHASE 3 — AVAILABLE HISTORICAL COVERAGE

**HISTORICAL_COVERAGE_NOT_MEASURABLE = YES.**

Reason: per-symbol `first/last_timestamp`, `bar_count`, gap, duplicate, and data_quality distributions live in the production PostgreSQL database (`daily_ohlcv_cache`, `backtest_candles`, `backtest_candle_meta`). Connecting to production DB requires DATABASE_URL / production credentials, which this task's safety rules prohibit (NO production DB connection, NO production SQL). Schema and code paths are fully audited; actual row counts are not inspectable. No counts are fabricated.

What the schema guarantees:

- Daily: only for symbols that have been backfilled; readiness gate requires ≥120 daily bars.
- Intraday 5m: only for symbols previously fetched via `ensure_candles`; bounded by **INTRADAY_MAX_DAYS = 55** (yfinance limit — intraday history older than ~55 sessions is refused at fetch time).
- Coverage therefore depends on what was downloaded in the past — not statically determinable.

**CURRENT_UNIVERSE_SYMBOLS** = 23 (BANKBARODA, BANKINDIA, CANBK, FEDERALBNK, IDFCFIRSTB, KTKBANK, MAHABANK, PNB, UNIONBANK, COALINDIA, GAIL, HUDCO, IRCON, IRFC, MRPL, NBCC, NMDC, NTPC, PFC, RECLTD, RVNL, SAIL, WIPRO — sectors BANK=9, INFRA=13, IT=1).

---

## PHASE 4 — INTRADAY RESEARCH FITNESS

| Req | Classification | Min resolution needed | Basis |
|---|---|---|---|
| A stock-in-play/RVOL | **PARTIALLY_SUPPORTED** | 5m bars + same-time-of-day cumulative volume across prior sessions | backtest_runner `_time_of_day_volume_ratio` implements exactly this; needs ≥5 prior sessions (VOL_CURVE_MIN_DAYS=5) |
| B opening-range breakout | PARTIALLY_SUPPORTED | 5m bars, first 15–30 min | 5m available ≤55 sessions |
| C VWAP pullback | PARTIALLY_SUPPORTED | 5m (VWAP cumulative from session open) | derivable from 5m OHLCV |
| D mean reversion | PARTIALLY_SUPPORTED | 5m | same |
| E precise entry confirmation | PARTIALLY_SUPPORTED | 5m (entry timing quantized to 5-min bar) | no 1m/tick |
| F structure-based stop | PARTIALLY_SUPPORTED | 5m swing pivots | 5m swing depth limited to ~55 sessions |
| G T1/T2 path ordering | PARTIAL (5m) / NOT from daily | 5m path; 1d bars → PATH_ORDER_UNKNOWN | see policy below |
| H intraday MFE | PARTIALLY_SUPPORTED | 5m bars after entry | extractable (spec in Phase 12) |
| I intraday MAE | PARTIALLY_SUPPORTED | 5m | same |
| J time_to_T1 | PARTIALLY_SUPPORTED | 5m | quantized to bar timestamp |
| K time_to_T2 | PARTIALLY_SUPPORTED | 5m | same |
| L time_to_stop | PARTIALLY_SUPPORTED | 5m | same |
| M trailing stops | PARTIALLY_SUPPORTED | 5m path replay | supported over ≤55-session window |
| N time-stop research | PARTIALLY_SUPPORTED | 5m | same |
| O late-entry feasibility | PARTIALLY_SUPPORTED | 5m with entry ts | same |
| P EOD square-off analysis | PARTIALLY_SUPPORTED | 5m to 15:20/15:30 | session clock defined |

**PATH_ORDER_UNKNOWN policy (mandatory):** for any daily-bar evaluation where `high ≥ target` AND `low ≤ stop`, the observation is marked `PATH_ORDER_UNKNOWN` and scored conservatively as **stop-first (loss)** — never counted as a win, never assigned arbitrary ordering. Where both target and stop are within the same 5m bar (intrabar collision), mark `INTRABAR_ORDER_AMBIGUOUS` → **stop-first conservative**.

---

## PHASE 5 — LOOK-AHEAD / DATA-LEAKAGE AUDIT

| LEAK_ID | FILE | FUNCTION | DESCRIPTION | SEVERITY | AFFECTS_V1_BASELINE | AFFECTS_V2_RESEARCH | REQUIRED_HARNESS_GUARD |
|---|---|---|---|---|---|---|---|
| L1 | market_replay.py | as-of filter | 23h59m as-of tolerance means a signal at time T can see the prior session's full-day bar as "same day" — minor boundary leak | LOW | NO (not in backtest_runner path) | YES | harness must use strict `ts ≤ T` with session-date anchoring, no tolerance window |
| L2 | ohlcv_cache_store.py | freshness/fallback | daily cache may hold a bar refreshed after session close; age measured vs end_date — acceptable, but full-day bar available only post-close; any intraday signal reading today's daily row = leak | MEDIUM | NO (backtest_runner uses build_asof_df, daily bars ≤ ts) | YES | FEATURE_AS_OF contract (Phase 14): daily row for session D usable only at T ≥ session close |
| L3 | paper_trader.py | estimate_broker_charges | delivery-rate charge model (STT 0.1% both sides, stamp 0.015%) — wrong model class, distorts net P&L | HIGH (correctness) | YES (paper path only; backtest uses phase20_executor) | YES | R38C must use phase20_executor model; V2 must use pinned official intraday model |
| L4 | historical_data_engine.py | 10m resample | mock-source candles propagate conservatively through resample — mock contamination risk if mock data ever enters DB | LOW | NO (mock guard `_has_mock` rejects) | YES | retain mock-source rejection at harness entry |
| L5 | config.NIFTY_50 / research-only consumers | resolve_universe | static today-membership lists risk survivorship (today's members back-projected) | MEDIUM | NO (backtest_runner fail-closed) | YES | universe as-of only; current-membership fallback requires explicit opt-in flag |
| L6 | market_replay.py | ticker.history | full-day OHLCV fetched per-day, then as-of filtered — if filter windows shift, post-decision bars can enter indicators | LOW | NO | YES | strict per-bar ts ≤ T filter at indicator input |

Guarded already (verified, no action): `build_asof_df` (daily bars ≤ ts; intraday prior days + partial today bar up to ts); `_time_of_day_volume_ratio` uses only session-so-far volume; scan snapshots run-scoped; historical universe fail-closed.

---

## PHASE 6 — HISTORICAL UNIVERSE / AS-OF AUTHORITY (verified in source)

- **HISTORICAL_UNIVERSE_SUPPORT** = YES. `backtest_runner.resolve_universe(cfg)`: custom → `get_historical_universe_resolution(target_date)` (HISTORICAL_SNAPSHOT); nifty50 → config.NIFTY_50; else DEFAULT_WATCHLIST.
- **HISTORICAL_UNIVERSE_STORAGE** = custom_universe_store historical snapshot resolution per session date, carrying universe_id/key/version/enabled_symbols/symbol_count/exact_set_hash/effective_from/effective_session.
- **AS_OF_RESOLUTION_AVAILABLE** = YES.
- **LOOKAHEAD_UNIVERSE_RISK** = LOW in backtest_runner (fail-closed `HISTORICAL_SNAPSHOT_UNAVAILABLE`); current-membership substitution only behind explicit `allow_current_universe_fallback=True`. MEDIUM in research-only consumers (L5) and divergent production consumers identified in R38A (preopen_provider, kite_preopen_provider, nse_preopen_provider, stock_monitoring_agent 3-tier fallback, market_context SECTOR_MAP breadth, post_market_data_refresh) — unchanged by R38B per scope.
- **FAIL_CLOSED_DESIGN** = YES. Exact error: **`HISTORICAL_UNIVERSE_UNAVAILABLE`** — abort the session backtest; never substitute today's 23 symbols / NIFTY_50 / DEFAULT_WATCHLIST silently.

Universe authority **unchanged**: `runtime_universe.resolve_active_universe()`; production CUSTOM_LOW_PRICE_SECTOR id=3 v1, 23 symbols, hash `22e5751f25686718f5572041834ce998b7c5ce9844d3b573bc3841749fe77016`.

---

## PHASE 7 — CURRENT V1 COST MODEL AUDIT (verified exact from source)

| Model | Source | Exact current behavior | Classification |
|---|---|---|---|
| CURRENT_BROKERAGE_MODEL | paper_trader.py L32-52 | ₹0 | PARTIAL (Zerodha min(0.03%, ₹20) not applied — ₹0 understates) |
| CURRENT_STT_MODEL | paper_trader.py | 0.1% both sides — **delivery rate** | **INCORRECT_FOR_INTRADAY** (intraday = 0.025% sell only) |
| CURRENT_EXCHANGE_TXN_MODEL | paper_trader.py | 0.00297% | PARTIAL — correct for Oct-2024–mid-2025; official page now shows 0.00307% (stale by one revision) |
| CURRENT_SEBI_MODEL | paper_trader.py | ₹10/crore = 0.0001% | CORRECT_FOR_INTRADAY |
| CURRENT_STAMP_DUTY_MODEL | paper_trader.py | 0.015% buy — **delivery rate** | **INCORRECT_FOR_INTRADAY** (intraday = 0.003% buy) |
| CURRENT_GST_MODEL | paper_trader.py | 18% on (exch + SEBI) | PARTIAL — official base is (brokerage + txn + SEBI); with ₹0 brokerage currently equivalent |
| CURRENT_SLIPPAGE_MODEL (execution) | phase20_executor.py L731-753 `compute_fill` | LAST_TRADED_PRICE(slip 0) / NEXT_QUOTE(0.5×slip_pct) / SLIPPAGE_ADJUSTED(full slip_pct); default SLIPPAGE_ADJUSTED, slippage_pct 0.15%, against trade direction | PARTIAL — flat %, no components |
| CURRENT_SLIPPAGE_MODEL (research sim) | paper_trader.py | flat 0.05% | PARTIAL |
| CURRENT_TOTAL_COST_MODEL (execution/backtest) | phase20_executor.py `compute_charges` | turnover × charges_pct (default 0.12) / 100 — flat all-in approximation | PARTIAL — roughly right magnitude, not component-accurate |
| CURRENT_TOTAL_COST_MODEL (paper) | paper_trader.py `estimate_broker_charges` | component model with delivery STT/stamp rates | **INCORRECT_FOR_INTRADAY** |

---

## PHASE 8 — OFFICIAL COST MODEL (equity INTRADAY, NSE, Zerodha retail)

Pinned from primary official source (retrieved **2026-10-01**):

| Component | Official intraday model | Side | Source |
|---|---|---|---|
| BROKERAGE | 0.03% or ₹20 per executed order, **whichever is lower** | per order (buy and sell) | zerodha.com/charges |
| STT | 0.025% of turnover | **sell side only** | zerodha.com/charges + support.zerodha.com STT article |
| NSE_TRANSACTION_CHARGES | **0.00307%** (₹307/crore) | both sides | zerodha.com/charges (current page value) |
| SEBI_CHARGES | ₹10/crore = 0.0001% | both sides | zerodha.com/charges |
| STAMP_DUTY | 0.003% (₹300/crore) | **buy side only** | zerodha.com/charges; NSE stamp-duty page; z-connect uniform stamp duty (0.003% intraday equity buy) |
| GST | 18% on (brokerage + transaction charges + SEBI charges) | on those components | zerodha.com/charges |
| (minor) IPFT | ₹0.01/crore + GST — negligible, note only | both sides | zerodha.com/charges |

Notes: NSE txn charge was 0.00297% from 2024-10-01 (z-connect revision note); the current official page shows 0.00307% — the repo's 0.00297% is stale by one revision. All percentages are on turnover (price × qty). Rounding: broker applies statutory levies "at actuals"; harness should compute exact percentages and round at the paisa level, documenting that production contract notes may differ by rounding.

Formulas (turnover_T = price×qty per side; brokerage_B = min(0.0003×turnover, 20)):

```
BUY_COST(turnout, qty, price) =
    B
  + stamp_duty = 0.00003 × turnover_buy
  + txn = 0.0000307 × turnover_buy
  + sebi = 0.000001 × turnover_buy
  + gst = 0.18 × (B + txn + sebi)
  (no STT on buy)

SELL_COST(turnout_s, price_s, qty) =
    B
  + STT = 0.00025 × turnover_sell
  + txn = 0.0000307 × turnover_sell
  + sebi = 0.000001 × turnover_sell
  + gst = 0.18 × (B + txn + sebi)
  (no stamp duty on sell)

ROUND_TRIP_COST = BUY_COST + SELL_COST
```

**OFFICIAL_INTRADAY_COST_MODEL_PINNED = YES** (SEBI fee basis confirmed at ₹10/crore; if operator wants regulator-primary confirmation beyond the broker's official page, mark SEBI ₹10/crore as REQUIRES_OPERATOR_CONFIRMATION — low impact).

---

## PHASE 9 — SLIPPAGE MODEL DESIGN (V2 research)

Current: flat `SLIPPAGE_ADJUSTED` at 0.15% (execution) / 0.05% (paper sim). Not component-aware.

**V2 conceptual form (coefficients NOT frozen in R38B):**

```
slippage_bps = spread_component
             + volatility_component
             + participation_component
             + fast_market_component
             (+ execution_delay_component, modeled as drift to next-bar price)
```

1. **spread_component** — half-spread proxy. Data needed: level-1 bid/ask history (NOT available). Proxy hierarchy (explicitly tagged at every row):
   - T0 `ACTUAL_SPREAD` — historical L1 quotes (unavailable today)
   - T1 `CONTEMPORARY_SAMPLE` — live spread samples per liquidity bucket, recorded going forward, applied to same-bucket historical symbols
   - T2 `OHLCV_PROXY` — empirical proxy from intraday bars (e.g., Corwin-Schultz-style high-low estimator on 5m bars)
   - T3 `CONSERVATIVE_FIXED` — fixed bps by liquidity bucket (e.g., tiered 5/10/20 bps) — last resort
2. **volatility_component** — proportional to realized 5m ATR% at decision time. Data: existing 5m candles. Estimable.
3. **participation_component** — order size ÷ bar volume (or ÷ time-of-day volume curve). Data: 5m volume — available. Small for research-size orders; likely near-zero coefficient.
4. **fast_market_component** — penalty when |bar-to-bar return| exceeds threshold or in first/last 15 min. Data: 5m candles — available.
5. **execution_delay_component** — fill at next bar open instead of signal bar close; measured, not coefficient-frozen.

Every fallback used in any run must be recorded per-observation with its tag (T0/T1/T2/T3); no hidden fallback. Coefficients are estimated in R38D/R38E and frozen only with a `slippage_model_version` bump.

---

## PHASE 10 — CORPORATE ACTION / PRICE ADJUSTMENT AUDIT

- **PRICE_ADJUSTMENT_MODEL** = MIXED: yfinance `download()` default returns auto-adjusted (back-adjusted) daily history; intraday `ensure_candles` uses yfinance history where adjustment depends on call parameters; Kite fallback returns raw. Daily cache stores both raw OHLC and `adjusted_close` column.
- **CORPORATE_ACTION_DATA_AVAILABLE** = PARTIAL: `backtest_corporate_actions` table exists (SPLIT|DIVIDEND per symbol+date) but population depends on whether it was ever filled — not inspectable without DB.
- **SPLIT_HANDLING** = back-adjusted via provider auto-adjust where applied; raw series + split rows otherwise → MIXED.
- **DIVIDEND_HANDLING** = `adjusted_close` present in daily cache; intraday bars not dividend-adjusted (immaterial intraday).
- **SYMBOL_RENAME_HANDLING** = none found — NOT_SUPPORTED (symbol-change/merger continuity absent).
- **CORPORATE_ACTION_RESEARCH_RISK** = MEDIUM: mixed adjusted/raw across stores and providers can create internal inconsistency for a historical session. Harness rule: **for any historical session, resolve a single adjustment basis per symbol per session and record it in run metadata; reject cross-basis comparisons.** For the ≤55-session intraday window the practical risk is low, but every run must record adjustment basis.

---

## PHASE 11 — SESSION / CALENDAR MODEL

- **SESSION_MODEL**: Timezone **Asia/Kolkata**. SESSION_DATE = IST trading date. SESSION_OPEN = 09:15 IST; pre-open 09:00–09:15 IST (production universe pins at 09:00 session boundary). SESSION_CLOSE = 15:30 IST. ENTRY_CUTOFF and FORCED_EXIT_TIME remain research parameters (production EOD square-off reference exists at 15:20 IST via eod-status endpoint) — for R38C, V1's actual behavior (square_off_before_close = False in DEFAULT_SETTINGS) is captured faithfully.
- **MARKET_CALENDAR_SOURCE**: no authoritative NSE holiday calendar is bundled. Research design must source sessions from observed data (dates present in daily cache / backtest_candle_meta coverage ranges) rather than a hardcoded calendar; weekends/holidays treated as absent sessions. Special/shortened sessions: no existing handling — harness must detect sessions whose bar span deviates from 09:15–15:30 and tag them `SPECIAL_SESSION`; missing bars: handled by coverage ranges + VOL_CURVE_MIN_DAYS-style validity checks.

---

## PHASE 12 — MFE / MAE EXTRACTION SPEC — COMPLETE

For a LONG candidate with entry E at fill time F, on 5m bars where bar_ts > F and bar_ts ≤ exit_or_cutoff:

```
MFE = max(high_t) − E          over the window
MAE = E − min(low_t)           over the window
MFE_PCT = MFE / E ;  MAE_PCT = MAE / E
MFE_R = MFE / (E − stop) ;  MAE_R = MAE / (E − stop)
```

Timing fields persisted per candidate:
`candidate_selected_at, entry_triggered_at, entry_fill_time, time_to_first_progress, time_to_MFE, time_to_MAE, time_to_T1, time_to_T2, time_to_stop, holding_duration, max_reachable_price_before_exit`

Rules:

- Window is strictly `(entry_fill_time, exit_time]` — bars before entry or after lifecycle end are never inspected.
- 5m quantization: times are the first bar ts at which the extremum/threshold is observed.
- Intrabar collisions (bar where high ≥ T1 AND low ≤ stop): mark **INTRABAR_ORDER_AMBIGUOUS**; conservative policy = **stop-first (loss)** for win/loss accounting, and additionally record the optimistic variant separately so R38E can bound the uncertainty. Never claim precision the bars cannot support.
- PATH_ORDER_UNKNOWN from daily bars: never scored as win; conservative stop-first, flagged.

---

## PHASE 13 — TIME-ADJUSTED RVOL DESIGN

RVOL(t) = today's cumulative session volume at t ÷ median of cumulative volume at the same aligned time t across comparable prior sessions.

- LOOKBACK_SESSION_COUNT = 20 prior sessions (provisional; backtest_runner's existing VOL_CURVE_MIN_DAYS=5 is the hard floor; R38D may tune 10–20 with the harness).
- MIN_VALID_SESSION_COUNT = 5 (matches existing authoritative VOL_CURVE_MIN_DAYS=5 rule; below that → RVOL undefined, rule returns ok=False, never fabricates).
- SAME_TIME_ALIGNMENT = align on 5m bar index within session (bar ts clock time, IST), cumulative sum from 09:15.
- MISSING_BAR_HANDLING = a prior session with missing bars at slot t is excluded from the median for that slot only; if valid sessions < MIN, RVOL = UNDEFINED (never substitute final daily volume).
- HOLIDAY_HANDLING = sessions sourced from observed trading dates in data (Phase 11), so holidays are naturally absent.
- OUTLIER_POLICY = median (not mean) at each aligned slot; additionally exclude prior sessions flagged SPECIAL_SESSION.
- **Invariant: only information with ts ≤ t enters RVOL. Final daily volume is never used intraday.**

---

## PHASE 14 — FEATURE AS-OF CONTRACT — COMPLETE

`FEATURE_AS_OF(symbol, T)`: every feature uses only records with `data_timestamp ≤ T`.

| Feature | Prior-session input | Same-session input |
|---|---|---|
| VWAP | no | cumulative from 09:15 to T |
| ATR (daily) | yes (≥14 prior closes) | no |
| ATR (intraday, 5m) | yes | yes (session-so-far) |
| EMA | yes (warmup) | yes (session-so-far) |
| market breadth | yes (prior session closes) | yes (advancers to T) |
| sector breadth | yes | yes |
| gap | yes (prior close) | yes (09:15 open) |
| opening range | yes (none) | yes (first N bars only) |
| RVOL | yes (volume curve, Phase 13) | yes (cum vol ≤ T) |
| relative strength | yes | yes (to T) |
| index direction | yes | yes (to T) |
| volatility regime | yes | yes |

Hard rule: the daily row for session D (its full-day OHLCV, final volume) is only admissible at T ≥ session close of D (closes leak L2).

---

## PHASE 15 — TRAIN / VALIDATION / OOS / WALK-FORWARD DESIGN

Mandatory order: TRAIN → VALIDATION → OOS → WALK-FORWARD. No random splits. No leakage of later universe membership into earlier dates (universe as-of per Phase 6).

**Split boundaries are computed AFTER actual coverage is observed in R38C's coverage step — not invented now.** Given known constraints (~55 sessions max intraday 5m; ≥120 daily bars per ready symbol), the provisional structure is:

- TRAIN: earliest contiguous intraday-eligible sessions, ~60% of intraday window — fit thresholds/weights only here.
- VALIDATION: next ~20% — choose among TRAIN-generated alternatives only.
- OOS: final ~20% — untouched until rules frozen; one pass.
- WALK-FORWARD: rolling 20-session train / 5-session test stepping forward across the full eligible window; reports temporal stability (parameter drift, metric dispersion).
- Because ~55 intraday sessions is thin, the **daily-baseline** V1 backtest (which can span the full daily-cache history, ≥120 sessions) runs the long-horizon split, while intraday-feature research (RVOL curve, MFE/MAE paths) is restricted to the 5m window and must state its n explicitly.
- If coverage turns out shorter than assumed, boundaries shift — never pad with ineligible data.

---

## PHASE 16 — SAMPLE-SIZE POLICY

Outputs per strategy × regime × entry-time bucket: SAMPLE_SIZE, WIN_RATE, CONFIDENCE_INTERVAL (Wilson score interval, not naive normal), T1_HIT_RATE, T2_HIT_RATE, STOP_RATE, EXPECTANCY (mean net R), PROFIT_FACTOR.

Research minimums (provisional, to be confirmed against actual coverage): n ≥ 30 per bucket for descriptive stats; n ≥ 100 for promotion consideration; CIs reported for every rate. A 70% win rate at n=10 is reported as 70% [Wilson CI ~ 39%–89%] — wide, and explicitly not comparable to n=500.

**INSUFFICIENT_SAMPLE behavior:** any cell below minimum is marked `INSUFFICIENT_SAMPLE`, excluded from rule promotion, and cannot advance to production recommendation. No exceptions, no pooling across regimes to inflate n without labeling `POOLED`.

---

## PHASE 17 — R38C V1 BASELINE DEFINITION — COMPLETE

Capture from source (verified):

- Universe: `resolve_universe` custom → historical snapshot as-of; fail-closed `HISTORICAL_SNAPSHOT_UNAVAILABLE`.
- Candidate gates (scan layer): RR ≥ 1.5 scan gate, confidence ≥ 60 (as observed in production scan logic).
- Execution gates (phase20_store DEFAULT_SETTINGS L55-94): **min_risk_reward = 2.0** (execution layer stricter than scan 1.5 — R38C must faithfully capture BOTH layers), risk_per_trade_pct 1.0, per_stock_exposure_cap_pct 25, sector cap 40, deployed cap 80, max_trades_per_day 3, cooldown 30 min, max_holding_days 10, **square_off_before_close = False**.
- Entry: `compute_fill` — fill_model SLIPPAGE_ADJUSTED (default), slippage_pct 0.15% against trade direction; NEXT_QUOTE = 0.5×slip; LAST_TRADED_PRICE = slip 0.
- Stop / target: verified target = **entry + 1.5 × (entry − stop)** (formula confirmed in source; consistent with CANBK reference 119.53 / 116.04 / 124.76).
- Exit: V1 fixed target/stop, no trailing, square-off-before-close disabled.
- Costs: `compute_charges` = turnover × 0.12% (flat). Slippage: flat 0.15%.
- Replay: candle-by-candle through the PRODUCTION pipeline (`_scan_one`, `derive_symbol_events`, `_try_enter` with phase20_executor compute_fill/compute_charges); isolated backtest ledger, atomic run claiming PENDING→RUNNING; `_has_mock` rejection; VOL_CURVE_MIN_DAYS=5 for the volume curve.

V1 is reproduced flaws included — no improvements, no parameter changes.

---

## PHASE 18 — R38C RUN MATRIX — COMPLETE

Per-trade record dimensions: date, symbol, universe_version (id/key/version/exact_set_hash), strategy, signal_time, entry_time, entry_price, stop, target, quantity, costs, slippage, exit_time, exit_price, exit_reason, gross_pnl, net_pnl, MFE, MAE, time_to_MFE, time_to_MAE.

Aggregate metrics: CANDIDATES, TRADES, WIN_RATE (+CI), PROFIT_FACTOR, EXPECTANCY, AVG_WIN, AVG_LOSS, MEDIAN_TRADE, MAX_DRAWDOWN, T1_HIT_RATE (where 5m path data exists; otherwise PATH_ORDER_UNKNOWN count), STOP_RATE, LATE_ENTRY_COUNT, HOLDING_TIME, MFE/MAE distributions, TRANSACTION_COST_DRAG (Σ costs / Σ turnover), SLIPPAGE_DRAG (Σ slippage / Σ turnover).

Not executed in R38B.

---

## PHASE 19 — R38D/R38E DATA SUFFICIENCY MATRIX

| Test | Available? | Reason |
|---|---|---|
| time-adjusted RVOL | PARTIAL | machinery exists (time-of-day volume ratio, min 5 sessions); needs ≥10-20 valid prior 5m sessions per symbol |
| opening range | PARTIAL | 5m first 30 min available ≤55 sessions |
| VWAP | AVAILABLE | derivable from 5m |
| intraday relative strength | PARTIAL | needs index 5m history — not confirmed present |
| market breadth | PARTIAL | daily adv/decl from daily cache possible; intraday breadth needs multi-symbol 5m alignment |
| sector breadth | PARTIAL | same, restricted to 23-symbol sectors |
| ATR | AVAILABLE | daily + 5m |
| swing structure | PARTIAL | 5m pivots ≤55 sessions |
| breakout confirmation | PARTIAL | 5m |
| retest confirmation | PARTIAL | 5m |
| volume expansion | PARTIAL | 5m ≤55 sessions |
| MFE/MAE | PARTIAL→AVAILABLE on 5m window | spec complete; requires 5m coverage for the test window |
| T1/T2 ladder | PARTIAL | 5m path; daily → PATH_ORDER_UNKNOWN |
| partial exits | PARTIAL | 5m path replay |
| ATR trailing | PARTIAL | 5m ≤55 sessions |
| swing trailing | PARTIAL | same |
| VWAP trailing | PARTIAL | same |
| EMA trailing | PARTIAL | same |
| time stops | PARTIAL | 5m |
| late-entry buckets | PARTIAL | 5m with entry ts |

---

## PHASE 20 — DATA-GAP ACQUISITION PLAN

**MUST_HAVE: none downloadable now.** The V1 daily-baseline backtest is supportable with the existing daily cache schema (≥120 bars/symbol readiness gate) plus the ≤55-session 5m window for intraday metrics. Nothing may be downloaded in R38B, and nothing blocks R38C's daily baseline.

**NICE_TO_HAVE (acquire only with separate operator approval; not now):**

| DATASET | SYMBOL_COUNT | INTERVAL | DATE_RANGE | ESTIMATED_ROWS | PREFERRED_PROVIDER | ALTERNATE_PROVIDER | LICENSE/API_CONSTRAINT | WHY_REQUIRED |
|---|---|---|---|---|---|---|---|---|
| 1-minute OHLCV | 23 | 1m | ≥60 sessions | ~2.7M (23×375 bars×~315 sessions) | Kite historical API (read-only) | yfinance (1m limited to ~7-30 days) | Kite: per-call rate limits; data-license for redistribution — internal research only | precise entry timing, tighter MFE/MAE, path-order disambiguation |
| longer 5m history | 23 | 5m | 12 months | ~4M | Kite historical API (read-only) | — | same as above | statistically meaningful intraday samples beyond 55 sessions |
| index 5m history | 1 (NIFTY 50) | 5m | matching 5m window | ~4.5k/55 sessions | Kite / yfinance | — | same | intraday relative strength + market direction features |
| L1 bid/ask samples | 23 | tick/1s snapshots | going forward, rolling | ops-dependent | Kite WS (read-only capture) | — | recording infra | kills the T2/T3 spread-proxy fallbacks in the slippage model |

Smallest-first principle: do NOT collect because more is possible; collect only when a specific R38D/R38E research question is blocked.

---

## PHASE 21 — STORAGE / REPRODUCIBILITY CONTRACT — COMPLETE

Every future backtest run pins: `code_sha, dataset_id, dataset_hash, universe_revision, universe_hash, cost_model_version, slippage_model_version, strategy_version, parameter_set_hash, train_window, validation_window, oos_window, walk_forward_window, run_id, created_at` — plus `adjustment_basis` per symbol-session (Phase 10) and `spread_proxy_tag` per observation (Phase 9). Dataset semantics immutable: a `dataset_id` refers to a frozen snapshot (hash-pinned); later data additions create a new dataset_id, never mutate an old one. No implementation in R38B.

---

## PHASE 22 — ACCEPTANCE DECISION

- Historical universe/as-of semantics defined and fail-closed: ✔
- Intraday path data adequate for **V1 daily-baseline**: ✔ (daily cache + 5m ≤55 sessions for intraday metrics)
- Transaction cost model pinned from official sources: ✔
- Slippage methodology defined (components + tagged fallback hierarchy, coefficients deferred): ✔
- Leakage controls defined: ✔
- Chronological validation design complete: ✔

But per-symbol coverage is NOT measurable without production DB access, and intraday history is hard-capped at ~55 sessions with no 1m data — so a **small defined data gap (longer intraday history) must be filled before full intraday research depth**.

### R38B_ACCEPTANCE_CLASSIFICATION = **B** — DATA PARTIALLY READY; SMALL DEFINED DATA GAP MUST BE FILLED FIRST

---

# FINAL REPORT

```
TASK978ZR_R38B_RESULT = PASS

BASE_HEAD = 5251da2dac0fbb1622f1533bb3f631df1ffa961a
BRANCH = task967-migration-guard-hardening
WORKTREE_STATUS = CLEAN (tracked); pre-existing untracked __pycache__/ + TASK_969_IDENTITY.json untouched

HISTORICAL_STORES_FOUND = daily_ohlcv_cache, daily_ohlcv_refresh_state, backtest_candles,
  backtest_candle_meta, backtest_corporate_actions, backtest_candle_cache/*.json,
  run-scoped scan/preopen/pipeline snapshot stores, historical_universe_resolution (as-of snapshots)
OHLCV_STORAGE_IMPLEMENTATION = PostgreSQL dual-store: daily_ohlcv_cache (daily,
  yfinance primary + read-only Kite daily fallback) + backtest_candles/backtest_candle_meta
  (5m/10m/15m/1d via historical_data_engine) + file fallback backtest_candle_cache/*.json
OHLCV_INTERVALS_SUPPORTED = 5m, 10m (resampled from 5m), 15m, 1d — 1m NOT supported anywhere
OHLCV_PRIMARY_TIMEZONE = Asia/Kolkata
OHLCV_PROVIDER_PROVENANCE = yfinance primary; Kite historical READ-ONLY daily fallback
  (ZERODHA_API_KEY + kite_token_store); mock sources flagged in source column, rejected by _has_mock

CURRENT_UNIVERSE_COUNT = 23
CURRENT_UNIVERSE_SYMBOLS = BANKBARODA, BANKINDIA, CANBK, FEDERALBNK, IDFCFIRSTB, KTKBANK,
  MAHABANK, PNB, UNIONBANK, COALINDIA, GAIL, HUDCO, IRCON, IRFC, MRPL, NBCC, NMDC, NTPC,
  PFC, RECLTD, RVNL, SAIL, WIPRO

SYMBOLS_WITH_ANY_HISTORY = NOT_MEASURABLE (production DB off-limits per safety rules)
SYMBOLS_WITH_INTRADAY_HISTORY = NOT_MEASURABLE (schema supports 5m/10m/15m ≤55 sessions
  for symbols previously fetched via ensure_candles; actual rows not inspectable)
SYMBOLS_WITH_1M_HISTORY = 0 (1m unsupported in code; no 1m store exists)
SYMBOLS_WITH_5M_HISTORY = NOT_MEASURABLE
SYMBOLS_WITH_DAILY_ONLY = NOT_MEASURABLE

EARLIEST_COMMON_DATE = NOT_MEASURABLE
LATEST_COMMON_DATE = NOT_MEASURABLE
COMMON_TRADING_DAYS = NOT_MEASURABLE

HISTORICAL_COVERAGE_MEASURABLE = NO
HISTORICAL_DATA_QUALITY = schema-level fields exist (source, data_quality, coverage
  ranges, freshness LIVE≤3d/NEAR_LIVE≤5d/STALE≤14d, MIN_BARS_REQUIRED=120); actual
  distributions NOT_MEASURABLE without production DB

INTRADAY_MFE_MAE_SUPPORTED = PARTIAL (5m bars, ≤55-session window; spec complete)
PATH_ORDER_DETERMINABLE = PARTIAL (5m path yes; daily bars → PATH_ORDER_UNKNOWN,
  conservative stop-first policy defined)
TIME_TO_TARGET_SUPPORTED = PARTIAL (5m quantization)
TRAILING_STOP_RESEARCH_SUPPORTED = PARTIAL (5m path replay ≤55 sessions)
TIME_FEASIBILITY_RESEARCH_SUPPORTED = PARTIAL (5m; entry timing quantized to 5 min)

LOOKAHEAD_RISKS_FOUND = 6 (L1 market_replay 23h59m as-of tolerance; L2 daily-row
  intraday admissibility boundary; L3 paper_trader delivery-rate cost model;
  L4 mock-candle propagation risk; L5 static-universe survivorship in research-only
  consumers; L6 market_replay full-day fetch filter boundary). build_asof_df,
  time-of-day volume ratio, run-scoped snapshots, and historical-universe fail-closed
  verified as properly guarded.
SURVIVORSHIP_RISK = MEDIUM in research-only paths (config.NIFTY_50 static membership);
  LOW in backtest_runner (historical snapshot as-of, fail-closed)
UNIVERSE_AS_OF_SUPPORT = YES (get_historical_universe_resolution per session date;
  universe_id/key/version/enabled_symbols/symbol_count/exact_set_hash/effective_from/effective_session)
HISTORICAL_UNIVERSE_FAIL_CLOSED = YES (HISTORICAL_SNAPSHOT_UNAVAILABLE /
  HISTORICAL_UNIVERSE_UNAVAILABLE; no silent substitution)

CURRENT_COST_MODEL_STATUS = MIXED — phase20_executor flat model (slippage 0.15%,
  charges 0.12%) roughly correct in magnitude but not component-accurate;
  paper_trader model INCORRECT_FOR_INTRADAY (delivery STT 0.1% both sides,
  delivery stamp 0.015%); NSE txn 0.00297% stale (official now 0.00307%)
OFFICIAL_INTRADAY_COST_MODEL_PINNED = YES

BROKERAGE_MODEL = min(0.03% of turnover, ₹20) per executed order, both sides
  [zerodha.com/charges]
STT_MODEL = 0.025% of sell-side turnover only [zerodha.com/charges + support.zerodha.com]
EXCHANGE_TRANSACTION_CHARGE_MODEL = 0.00307% (₹307/crore) both sides, NSE equity
  [zerodha.com/charges; was 0.00297% per Oct-2024 z-connect revision — current page value used]
SEBI_CHARGE_MODEL = ₹10/crore = 0.0001% both sides [zerodha.com/charges;
  REQUIRES_OPERATOR_CONFIRMATION against SEBI primary doc if regulator-level proof needed]
STAMP_DUTY_MODEL = 0.003% (₹300/crore) buy side only [zerodha.com/charges + NSE
  stamp-duty page + z-connect uniform stamp duty]
GST_MODEL = 18% on (brokerage + transaction charges + SEBI charges)
  [zerodha.com/charges]

OFFICIAL_COST_SOURCES = https://zerodha.com/charges/ ;
  https://zerodha.com/brokerage-calculator/ ;
  https://support.zerodha.com (STT calculation article) ;
  https://zerodha.com/z-connect/business-updates/revision-in-exchange-transaction-charges-and-securities-transaction-tax-from-october-1-2024 ;
  https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies ;
  https://www.nseindia.com/static/invest/first-time-investor-stamp-duty-charges-taxes
COST_MODEL_RETRIEVED_AT = 2026-10-01

SLIPPAGE_MODEL_CURRENT = phase20_executor compute_fill: fill_model SLIPPAGE_ADJUSTED
  (default), slippage_pct 0.15% against trade direction (alternatives LAST_TRADED_PRICE
  slip 0 / NEXT_QUOTE 0.5×slip); paper_trader flat 0.05%; backtest charges flat 0.12%
SLIPPAGE_MODEL_V2_RESEARCH_DESIGN = component model: spread_component +
  volatility_component + participation_component + fast_market_component
  (+ execution_delay as next-bar-open fill); spread proxy hierarchy
  ACTUAL_SPREAD → CONTEMPORARY_SAMPLE → OHLCV_PROXY → CONSERVATIVE_FIXED,
  every fallback explicitly tagged per observation; coefficients estimated in
  R38D/R38E, frozen only via slippage_model_version bump
SLIPPAGE_PARAMETERS_FROZEN = NO

PRICE_ADJUSTMENT_MODEL = MIXED (yfinance auto-adjusted daily + raw OHLC +
  adjusted_close column + raw Kite fallback; intraday not dividend-adjusted)
CORPORATE_ACTION_RISK = MEDIUM (backtest_corporate_actions table exists, population
  unverified; no symbol-rename/merger continuity; harness must resolve a single
  adjustment basis per symbol-session and record it)

SESSION_MODEL = Asia/Kolkata; SESSION_DATE = IST trading date; SESSION_OPEN 09:15 IST
  (pre-open 09:00–09:15; universe pins 09:00); SESSION_CLOSE 15:30 IST; ENTRY_CUTOFF
  and FORCED_EXIT_TIME = research parameters for R38E, not fixed here; production
  EOD square-off reference 15:20 IST (eod-status); V1 square_off_before_close = False
MARKET_CALENDAR_SOURCE = observed trading dates from data stores (no bundled NSE
  holiday calendar); SPECIAL_SESSION tagging for deviant sessions; weekends/holidays
  absent by construction

MFE_MAE_EXTRACTION_DESIGN = COMPLETE
RVOL_AS_OF_DESIGN = COMPLETE
FEATURE_AS_OF_CONTRACT = COMPLETE

TRAIN_WINDOW = computed after actual coverage observed (provisional: earliest ~60%
  of eligible sessions; long-horizon split on daily baseline, intraday-feature
  research restricted to 5m window with explicit n)
VALIDATION_WINDOW = next ~20% of eligible sessions (provisional; chooses among
  TRAIN-generated alternatives only)
OOS_WINDOW = final ~20% of eligible sessions (provisional; untouched until frozen,
  single pass)
WALK_FORWARD_DESIGN = rolling 20-session train / 5-session test, stepped forward
  across full eligible window; reports parameter drift + metric dispersion;
  chronological only, no random splits, no OOS tuning, universe as-of per split

SAMPLE_SIZE_POLICY = per strategy × regime × entry-time bucket; n ≥ 30 descriptive
  (provisional), n ≥ 100 promotion consideration; Wilson score CIs on every rate;
  outputs SAMPLE_SIZE, WIN_RATE, CONFIDENCE_INTERVAL, T1_HIT_RATE, T2_HIT_RATE,
  STOP_RATE, EXPECTANCY, PROFIT_FACTOR
INSUFFICIENT_SAMPLE_BEHAVIOR = cell marked INSUFFICIENT_SAMPLE, excluded from rule
  promotion, cannot reach production recommendation; pooling only with POOLED label

V1_BASELINE_DEFINITION = COMPLETE (universe resolve_universe as-of fail-closed;
  scan gate RR ≥ 1.5 + conf ≥ 60; execution gate min_risk_reward 2.0 — both layers
  captured; sizing 1.0% risk, caps 25/40/80, max 3 trades/day, 30-min cooldown,
  max_holding_days 10, square_off_before_close False; fill SLIPPAGE_ADJUSTED 0.15%;
  charges flat 0.12%; target = entry + 1.5 × (entry − stop) verified in source;
  production-pipeline replay via _scan_one/derive_symbol_events/_try_enter;
  isolated ledger, atomic run claiming, _has_mock rejection, VOL_CURVE_MIN_DAYS=5)
R38C_RUN_MATRIX = COMPLETE (per-trade + aggregate metric set defined; not executed)

R38D_DATA_SUFFICIENCY = PARTIAL — time-adjusted RVOL PARTIAL; opening range PARTIAL;
  VWAP AVAILABLE; intraday RS PARTIAL (index 5m unconfirmed); market/sector breadth
  PARTIAL; ATR AVAILABLE; swing structure PARTIAL; breakout/retest confirmation
  PARTIAL; volume expansion PARTIAL — all bounded by 5m ≤55 sessions
R38E_DATA_SUFFICIENCY = PARTIAL — MFE/MAE, T1/T2 ladder, partial exits, ATR/swing/
  VWAP/EMA trailing, time stops, late-entry buckets: all PARTIAL on 5m ≤55-session
  window (PATH_ORDER_UNKNOWN policy for daily; INTRABAR_ORDER_AMBIGUOUS stop-first)

MISSING_REQUIRED_DATASETS = none blocking R38C daily baseline. Nice-to-have:
  1m OHLCV (23 syms), longer 5m history (12mo), index 5m, L1 bid/ask capture
DATA_ACQUISITION_REQUIRED = NO (for R38C daily baseline); YES later (for full
  intraday research depth — separate operator approval required, nothing downloaded now)

REPRODUCIBILITY_CONTRACT = COMPLETE (code_sha, dataset_id/hash, universe_revision/
  hash, cost_model_version, slippage_model_version, strategy_version,
  parameter_set_hash, train/validation/oos/walk_forward windows, run_id, created_at,
  + per-symbol-session adjustment_basis + per-observation spread_proxy_tag;
  immutable dataset semantics)

ROOT_FINDINGS =
1. Data exists in two well-schemad stores but actual per-symbol coverage is not
   verifiable without production DB access (prohibited) — R38C must open with a
   coverage observation step and split boundaries are computed then, not now.
2. Intraday research is hard-capped: 5m/10m/15m only, ≤55 sessions (INTRADAY_MAX_DAYS,
   yfinance limit), no 1m anywhere — MFE/MAE/trailing/time studies are PARTIAL and
   statistically thin; daily-baseline V1 backtest is fully supportable.
3. The paper_trader charge model is wrong for intraday (delivery STT 0.1% both sides,
   delivery stamp 0.015%); official intraday model is pinned: brokerage min(0.03%, ₹20),
   STT 0.025% sell, NSE txn 0.00307%, SEBI 0.0001%, stamp 0.003% buy, GST 18% on
   (brokerage+txn+SEBI) — V2 must switch to this; repo's NSE 0.00297% is one
   revision stale.
4. No-lookahead machinery is genuinely strong in the backtest path (build_asof_df,
   as-of universe fail-closed, time-of-day volume, mock rejection) — but 6 leak
   findings are documented (highest-impact: market_replay 23h59m tolerance and the
   daily-row intraday admissibility boundary) with required harness guards defined.
5. Slippage and validation methodology are now fully specified but intentionally
   unfrozen: component slippage with tagged fallback hierarchy, chronological
   TRAIN→VALIDATION→OOS→WALK-FORWARD with boundaries computed from observed
   coverage, INSUFFICIENT_SAMPLE gating — nothing gets promoted on thin evidence.

R38B_ACCEPTANCE_CLASSIFICATION = B
READY_FOR_R38C_V1_BASELINE = YES (daily baseline; coverage observation step first)
READY_FOR_R38D_V2_SELECTION_RESEARCH = YES (within 5m ≤55-session window; thin samples
  gated by INSUFFICIENT_SAMPLE policy; longer intraday history is the defined gap)
READY_FOR_R38E_ENTRY_EXIT_RESEARCH = YES (same 5m window caveat; PATH_ORDER_UNKNOWN +
  INTRABAR_ORDER_AMBIGUOUS stop-first policy mandatory)
READY_FOR_V2_IMPLEMENTATION = NO
READY_FOR_LIVE_ORDER_OPERATION = NO

SOURCE_FILES_MODIFIED = 0
TEST_FILES_MODIFIED = 0
CI_FILES_MODIFIED = 0
WORKFLOW_FILES_MODIFIED = 0
DATABASE_FILES_MODIFIED = 0

STAGED_FILES = 0
COMMITS_CREATED = 0
PUSH = 0
BRANCH_REF_UPDATES = 0
CI_RERUNS = 0
ZEABUR_DEPLOYMENTS = 0
ZEABUR_ENV_CHANGES = 0

MANUAL_PRODUCTION_DB_CONNECTIONS = 0
MANUAL_SQL = 0
MANUAL_DB_WRITES = 0
MANUAL_SCANS = 0
MANUAL_PREOPEN_RUNS = 0
BACKTEST_RUNS = 0
REPLAY_BACKFILL = 0
BROKER_ORDERS = 0
PAPER_TRADE_MUTATIONS = 0
```

---

## APPENDIX TABLES

### 1. HISTORICAL DATA COVERAGE TABLE

| Store | Interval | Window | Quality/provenance | Measurable now? |
|---|---|---|---|---|
| daily_ohlcv_cache | 1d | ≥120 bars/symbol required for "ready"; as-of reads | source, data_quality, freshness tiers | NO (DB off-limits) |
| backtest_candles | 5m, 10m (resampled), 15m, 1d | intraday ≤55 sessions (INTRADAY_MAX_DAYS) | source (mock-guarded) | NO (DB off-limits) |
| backtest_candle_meta | — | per (symbol, interval) coverage ranges | — | NO |
| backtest_corporate_actions | event | SPLIT/DIVIDEND per symbol+date | — | NO |
| backtest_candle_cache/*.json | per file | file fallback | yes | YES (files visible) but contents not enumerated |
| universe snapshots | — | per session date | universe_id/key/version/hash | YES (code path verified) |

### 2. INTRADAY RESEARCH FITNESS TABLE

See Phase 4 — 16 requirements: 0 full SUPPORTED, 16 PARTIALLY_SUPPORTED on the 5m ≤55-session window, with the mandatory PATH_ORDER_UNKNOWN / INTRABAR_ORDER_AMBIGUOUS stop-first conservative policies.

### 3. LOOK-AHEAD / LEAKAGE FINDINGS TABLE

See Phase 5 — L1–L6 with severities, baseline/V2 impact, and required harness guards.

### 4. OFFICIAL COST MODEL TABLE WITH SOURCES

See Phase 8 — all six components pinned with URLs and retrieval date 2026-10-01; formulas BUY_COST / SELL_COST / ROUND_TRIP_COST given; SEBI ₹10/crore flagged REQUIRES_OPERATOR_CONFIRMATION only if regulator-primary proof demanded.

### 5. SLIPPAGE RESEARCH MODEL

See Phase 9 — 4 components + delay model, proxy hierarchy T0→T3, per-observation tags, coefficients deferred.

### 6. MFE/MAE EXTRACTION SPEC

See Phase 12 — window `(entry_fill_time, exit_time]`, normalized MFE_PCT/MAE_PCT/MFE_R/MAE_R, 11 timing fields, stop-first ambiguity policy.

### 7. TRAIN/VALIDATION/OOS/WALK-FORWARD DESIGN

See Phase 15 — chronological, boundaries computed post-coverage-observation, 60/20/20 provisional only, walk-forward 20/5 rolling.

### 8. DATA-GAP ACQUISITION PLAN

See Phase 20 — no MUST_HAVE blocking R38C; 4 NICE_TO_HAVE datasets (1m, longer 5m, index 5m, L1 quotes) requiring separate operator approval.

### 9. EXACT R38C EXECUTION PLAN

**R38C = execute the V1 baseline backtest faithfully (no improvements).**

| Step | Action | Guard |
|---|---|---|
| 0 | Verify HEAD/branch; record run metadata (Phase 21 contract fields) | read-only start |
| 1 | **Coverage observation**: read `backtest_candle_meta` + daily cache readiness per 23 symbols (read-only DB queries authorized in R38C) → emit actual coverage table | no writes beyond run ledger |
| 2 | Freeze dataset_id + dataset_hash from observed coverage; compute TRAIN/VALIDATION/OOS boundaries per Phase 15 from actual data | boundaries recorded in run metadata |
| 3 | Resolve universe per session date via historical snapshot; FAIL CLOSED `HISTORICAL_SNAPSHOT_UNAVAILABLE` if missing — never substitute today's 23 symbols | universe_hash per session recorded |
| 4 | Run V1 baseline via backtest_runner through the PRODUCTION pipeline (`_scan_one` → `derive_symbol_events` → `_try_enter`), exactly as configured: scan gate RR ≥ 1.5 / conf ≥ 60, execution gate RR 2.0, fill SLIPPAGE_ADJUSTED 0.15%, charges flat 0.12%, target = entry + 1.5×(entry−stop), max 3 trades/day, cooldown 30 min, caps 25/40/80, square_off_before_close False | no parameter changes, mock candles rejected |
| 5 | Run matrix: daily-baseline over the full eligible daily window + intraday-metric pass (MFE/MAE/time fields) on the 5m window only, tagged with 5m window bounds | PATH_ORDER_UNKNOWN / INTRABAR_ORDER_AMBIGUOUS → stop-first |
| 6 | Emit metrics per Phase 18 with Wilson CIs; cells below Phase 16 minimums marked INSUFFICIENT_SAMPLE | no promotion decisions |
| 7 | Emit report with Phase 21 contract + counters; classify V1 baseline health | no activation claims |

R38C does NOT touch entry/stop/target logic, thresholds, universe consumers, execution, or any production behavior.

---

**R38B COMPLETE.** No files modified by the audit, no DB/network access to the trading stack, no backtest executed. All acceptance counters are 0.

*(This report file itself is the only new file created, at operator request for download.)*
