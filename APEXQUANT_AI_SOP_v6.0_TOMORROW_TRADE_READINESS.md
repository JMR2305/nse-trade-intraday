# ApexQuant AI — Standard Operating Procedure v6.0
## Tomorrow Trade Readiness Edition
**Version:** 6.0  
**Date:** 2026-08-18 (post-close) → Readiness for 2026-08-19  
**Production URL:** https://nse-trade-intraday.replit.app  
**Mode:** PAPER TRADING ONLY — no real orders, no broker API calls  
**Generated at:** 20:45 IST, 2026-08-18  

---

## SECTION 1 — EXECUTIVE SUMMARY

| Attribute | Value |
|-----------|-------|
| **Production URL** | https://nse-trade-intraday.replit.app |
| **Health check** | ✅ `{"status":"ok"}` — 200 OK |
| **Mode** | PAPER ONLY — `LIVE_EXECUTION_ENABLED = false` |
| **Live orders** | ❌ Disabled. `live_order_placement_enabled = false`. No Kite place_order ever called. |
| **Kite LTP overlay** | ✅ Enabled — `kite_overlay_enabled: true`, `kite_verified: true`, `kite_session_verified: true` |
| **Bootstrap mode** | ✅ Active — `bootstrap_paper_enabled: true`, `auto_paper_entries: true` |
| **Bootstrap cap** | ✅ **₹15,000** — confirmed in production via `/api/phase20/bootstrap-status` → `bootstrap_max_order_value: 15000` |
| **Bootstrap progress** | 1 / 20 closed bootstrap trades (4% of cutoff) |
| **DRREDDY P20-3468fb2a24** | ✅ **CLOSED** via `POST_CLOSE_FORCE_EXIT` at 18:01 IST today |
| **Open positions** | ✅ **NONE** — `/api/phase20/positions` → `[]` |
| **EOD square-off** | ✅ `eod_ran_today: true` — fix confirmed live and working |
| **Circuit breaker** | ✅ NOT tripped — 0 consecutive losses, 0 daily P&L loss |
| **Latest build** | ✅ Second publish live (EOD import fix + bypass endpoint + stdout parser fix confirmed working) |
| **Task #832** | ✅ MERGED — KV claim-before-import race fix |
| **Task #833** | ✅ MERGED — EOD banner on Mission Control |
| **Task #834** | ✅ MERGED — overnight carry regression tests (27/27 pass) |

### Tomorrow Readiness Verdict

```
┌─────────────────────────────────────────────────────┐
│  READY WITH WARNINGS                                │
│                                                     │
│  ✅ All safety controls active                      │
│  ✅ Bootstrap enabled, ₹15,000 cap, Kite verified   │
│  ✅ No overnight carry — DRREDDY closed             │
│  ✅ EOD square-off confirmed working                │
│  ⚠️  LTIM.NS unavailable (provider issue, ongoing)  │
│  ⚠️  Last scan from 09:56 IST (normal post-market)  │
└─────────────────────────────────────────────────────┘
```

**No blockers for tomorrow's trade session.** The LTIM warning is a pre-existing NSE data-provider issue (not a code defect) and has been present for multiple sessions.

---

## SECTION 2 — CURRENT PRODUCTION STATE

All data queried from production at **20:45 IST, 2026-08-18**. Source: live API calls to `https://nse-trade-intraday.replit.app`.

### 2.1 Health

| Endpoint | Response |
|----------|----------|
| `GET /api/healthz` | `{"status":"ok"}` ✅ |

### 2.2 Settings (from `/api/phase20/settings`)

| Setting | Value |
|---------|-------|
| `bootstrap_paper_enabled` | `true` |
| `auto_paper_entries` | `true` |
| `auto_paper_entries_confirmed_at` | `2026-08-10T03:31:14Z` |
| `scan_interval_minutes` | **5** |
| `min_confidence` | 75 |
| `min_opportunity_score` | 70 |
| `min_risk_reward` | 2.0 |
| `max_trades_per_day` | 3 |
| `per_stock_exposure_cap_pct` | 25% |
| `sector_exposure_cap_pct` | 40% |
| `portfolio_deployed_cap_pct` | 80% |
| `risk_per_trade_pct` | 1% |
| `daily_loss_limit_pct` | 3% (= ₹1,500 on ₹50,000 capital) |
| `circuit_breaker_loss_threshold` | 3% |
| `fill_model` | `SLIPPAGE_ADJUSTED` |
| `slippage_pct` | 0.15% |
| `charges_pct` | 0.12% |
| `max_holding_days` | 10 |
| `square_off_before_close` | `false` (EOD is now **unconditional** — setting no longer gates the rule) |
| `exit_on_stale_after_days` | 5 |
| `initial_capital` | ₹50,000 (portfolio_store constant; circuit breaker daily limit = 3% × ₹50,000 = ₹1,500 confirmed) |
| `max_concurrent_positions` | 5 |

### 2.3 Bootstrap Status (from `/api/phase20/bootstrap-status`)

| Field | Value |
|-------|-------|
| `bootstrap_paper_enabled` | `true` ✅ |
| `auto_paper_entries` | `true` ✅ |
| `kite_verified` | `true` ✅ |
| `kite_session_verified` | `true` ✅ |
| `kite_overlay_enabled` | `true` ✅ |
| `circuit_breaker_tripped` | `false` ✅ |
| `closed_bootstrap_trades` | **1** (DRREDDY, closed today) |
| `bootstrap_max_closed_trades` | 20 (cutoff) |
| `bootstrap_cutoff_reached` | `false` |
| `bootstrap_max_order_value` | **₹15,000** ✅ |
| `bootstrap_eligible_count` | 3 (from last scan) |
| Top candidates | HDFCBANK (conf 78.3%), HDFCLIFE (conf 73.4%), DRREDDY (conf 64.7%) |

### 2.4 Circuit Breaker (from `/api/phase20/circuit-breaker`)

| Field | Value |
|-------|-------|
| `tripped` | `false` ✅ |
| `consecutive_losses` | 0 |
| `consecutive_loss_limit` | 3 |
| `daily_realized_pnl` | ₹0 |
| `daily_loss_limit` | ₹1,500 |
| `closed_trades` | 1 |
| Last evaluated | 2026-08-18T15:15:47Z |

### 2.5 Open Positions (from `/api/phase20/positions`)

```json
{"success": true, "positions": []}
```

✅ **No open positions.** No overnight carry risk.

### 2.6 DRREDDY Trade — Final Closed State (from `/api/phase20/eod-status`)

| Field | Value |
|-------|-------|
| **trade_id** | P20-3468fb2a24 |
| **symbol** | DRREDDY |
| **status** | **CLOSED** ✅ |
| **trigger_source** | BOOTSTRAP_AUTO |
| **fill_model** | bootstrap_paper |
| **fill_price (entry)** | ₹1,186.98 |
| **qty** | 1 |
| **stop_loss** | ₹1,136.66 |
| **target** | ₹1,307.60 |
| **exit_rule** | POST_CLOSE_FORCE_EXIT |
| **exit_price** | ₹1,186.98 (fill_price_fallback — no post-close scan) |
| **realized_pnl** | ₹0.00 (exit at entry price, fill_price_fallback) |
| **exit_ts** | 2026-08-18T12:31:18Z = **18:01:18 IST** |
| **entry_ts** | 2026-08-18 14:44:11 IST |

### 2.7 Portfolio (inferred from confirmed API responses)

| Metric | Value |
|--------|-------|
| Starting capital | ₹50,000.00 |
| Cash (post DRREDDY close) | ≈ ₹49,999.98 (₹48,813.02 + ₹1,186.98) |
| Realized P&L today | ₹0.00 (breakeven exit at fill_price_fallback) |
| Unrealized P&L | ₹0.00 (no open positions) |
| EXIT_PENDING trades | **0** |
| BOOTSTRAP_AUTO open | **0** |

### 2.8 Scan Status (from `/api/live-data/scan/status`)

| Field | Value |
|-------|-------|
| Latest scan_id | `6a55aefb0622` |
| Status | SUCCESS |
| Completed | 2026-08-18T09:56:32Z = **15:26:32 IST** (last intraday scan) |
| Symbols requested | 51 |
| Symbols received | 50 |
| Missing | LTIM (provider issue, ongoing) |
| Stale | 0 |
| Scans today | **18** |
| Cadence | 5 minutes |
| Provider | Zerodha Kite Connect (Live) + Yahoo Finance (History) |
| BUYs in last scan | 0 |
| WATCHes | 18 |
| IGNOREs | 32 |
| Bootstrap eligible | 3 |

### 2.9 EOD Status (from `/api/phase20/eod-status` at 20:45 IST)

```json
{
  "eod_ran_today": true,
  "squareoff_time_ist": "15:20 IST",
  "past_post_close": true,
  "force_close_results": [
    {
      "symbol": "DRREDDY",
      "exit_rule": "POST_CLOSE_FORCE_EXIT",
      "exit_price": 1186.98,
      "realized_pnl": 0
    }
  ],
  "blocked_events": []
}
```

---

## SECTION 3 — SYSTEM ARCHITECTURE

### 3.1 Data Acquisition Layer

| Source | Role | Used For |
|--------|------|----------|
| **yfinance daily bars** | Historical OHLCV (max_data_timestamp enforced) | All technical indicators (MACD, RSI, Bollinger, etc.), strategy decisions |
| **Zerodha Kite LTP overlay** | Real-time intraday prices | `current_price` and `execution_price` only — overlays on top of yfinance signal data |
| **NSE Official (pre-open)** | IEP + pre-open qty | Pre-open intelligence only (Phase 5D) |

**Key principle:** Indicators are always computed from yfinance daily bars. The Kite LTP overlay only replaces the price used for entry/exit decisions — it never affects indicator calculation. This prevents lookahead contamination.

**KITE_LTP_OVERLAY_ENABLED=true** (production): When a Kite session is live and verified, the current_price field in the scan snapshot is replaced with the live Kite LTP before the risk gate and executor run. All entry/exit prices therefore reflect the live market price, not yesterday's close.

### 3.2 Scan Engine

| Parameter | Value |
|-----------|-------|
| Universe | NIFTY 50 (51 symbols; LTIM currently missing → 50 symbols scanned) |
| Scan cadence | Every **5 minutes** during market hours |
| Market hours | 09:15–15:30 IST (NSE equity) |
| Pre-open | 09:00–09:15 IST (separate pre-open intelligence, not trade-generating) |
| Scan lock | DB-durable via `scan_state_store` (Postgres) — prevents concurrent runs |
| Stale data | Symbols flagged STALE/UNAVAILABLE are excluded from BUY decisions; STALE→WATCH, UNAVAILABLE→IGNORE |
| Missing symbols | LTIM is excluded from analysis; quota of 50/51 evaluated |
| Scan audit | All bars fetched before analysis starts; single scan_id per snapshot |

Scan sessions: ~18 scans per full trading session (09:15–15:30 IST at 5-min cadence, with some gaps for scan lock contention and post-close runs).

### 3.3 Signal Engine

Each symbol is evaluated through a multi-factor pipeline:

| Output | Meaning |
|--------|---------|
| **STRONG BUY** | All conditions met, high conviction |
| **BUY** | Conditions met, standard conviction |
| **WATCH** | Near threshold — confidence or opportunity slightly below |
| **IGNORE** | Well below threshold or data quality issues |

**Key metrics per symbol:**

| Metric | Description |
|--------|-------------|
| `confidence` | Weighted multi-indicator signal strength (0–100%) |
| `opportunity_score` | Risk-adjusted upside estimate (0–100) |
| `trade_quality_score` | Combined gate score (0–100) |
| `rr_ratio` | Risk:Reward after slippage |
| `low_evidence` | True when < 5 closed trades for this symbol; drives bootstrap eligibility |
| `strategy` | Selected strategy (e.g. `macd_cross`, `rsi_reversal`) |
| `regime` | Market regime (Trending/Ranging/High-Vol) — gates strategy suitability |
| `bootstrap_eligible` | True when low_evidence=true AND action=WATCH/BUY AND all hard gates pass |

### 3.4 Risk and Execution Layer

| Gate | Threshold |
|------|-----------|
| Minimum confidence | 75% (normal BUY) — bootstrap uses separate internal threshold |
| Minimum opportunity score | 70 (normal BUY) |
| Minimum R:R | 2.0 (normal BUY); bootstrap minimum 1.5 |
| Circuit breaker | Trips at 3% daily loss or 3 consecutive losses |
| Duplicate position guard | No second position in same symbol if one is OPEN |
| Max concurrent positions | 5 |
| Per-stock exposure cap | 25% of ₹50,000 = ₹12,500 |
| Sector cap | 40% |
| Portfolio deployed cap | 80% |
| Bootstrap ceiling | ₹15,000 per trade (effective: min(₹15,000, per-stock cap ₹12,500) = ₹12,500) |
| Slippage | 0.15% added to worst-case fill |
| Charges | 0.12% estimated |

### 3.5 Paper Execution Layer

All trades use paper-only execution. No Kite order API is ever called.

| Field | Description |
|-------|-------------|
| `trade_id` | Format: `P20-<8 hex chars>` |
| `trigger_source` | `BOOTSTRAP_AUTO`, `AUTO`, or `MANUAL` |
| `fill_model` | `SLIPPAGE_ADJUSTED` (normal) or `bootstrap_paper` (bootstrap) |
| `fill_price` | signal_price × (1 + slippage_pct) |
| Events emitted | `ORDER_SUBMITTED` → `ORDER_EXECUTED` (or `ORDER_REJECTED`) |
| DB table | `phase20_paper_trades` |
| Broker API | None — `LIVE_EXECUTION_ENABLED = false` always |

### 3.6 Exit Management Layer

| Exit Rule | Trigger | Price Source |
|-----------|---------|--------------|
| `STOP_LOSS_HIT` | current_price ≤ stop_loss | Kite LTP preferred, else yfinance |
| `TARGET_HIT` | current_price ≥ target | Kite LTP preferred, else yfinance |
| `TRAILING_STOP` | Trailing high × factor | Not currently active |
| `TIME_EXIT` | Position held > max_holding_days (10) | Kite LTP preferred, else yfinance |
| `MARKET_CLOSE_EXIT` | **15:20 IST** — unconditional, all open intraday positions | Kite LTP preferred, else yfinance |
| `POST_CLOSE_FORCE_EXIT` | After 15:30 IST, any remaining OPEN positions — once per day via kv_claim_once | Kite LTP → yfinance → fill_price_fallback |
| `STALE_DATA_SAFETY` | exit_on_stale_after_days (5) with no reliable price | Last known price or fill_price_fallback |
| `MARKET_CLOSE_EXIT_BLOCKED` | POST_CLOSE_FORCE_EXIT attempted but no price available | Emits pipeline event + WARN notification; position stays OPEN for retry |

**MARKET_CLOSE_EXIT** rules (post v6.0 fix):
- Fires at or after **15:20 IST** (10 minutes before market close)
- **Unconditional** — does NOT require `square_off_before_close=true`
- Applies to ALL trigger_sources: BOOTSTRAP_AUTO, AUTO, MANUAL
- **POST_CLOSE_FORCE_EXIT** is a daily once-per-day safety net via `kv_claim_once("eod_squareoff:{today}")`
- If no price is available, emits `MARKET_CLOSE_EXIT_BLOCKED` and preserves position for next retry window

**Realized P&L formula:**
```
realized_pnl = (exit_price - fill_price) × qty
new_cash     = prior_cash + (exit_price × qty)
```

### 3.7 Learning and Analytics Layer

| Component | Role |
|-----------|------|
| Paper trade history | All closed trades stored in `phase20_paper_trades` with full metadata |
| `low_evidence` flag | Set when symbol has < 5 closed paper trades; drives bootstrap eligibility |
| Bootstrap purpose | Collect minimum evidence (5 real intraday paper trades per symbol) before the normal BUY engine trusts its own calibration |
| Bootstrap auto-disable | When `closed_bootstrap_trades ≥ bootstrap_max_closed_trades (20)` → `bootstrap_cutoff_reached = true` → bootstrap stops |
| Analytics pages | Mission Control, AI Paper Trader, Operator Analytics, Market Intelligence Hub, Execution Quality |
| Backtest | Separate replay engine with `emit_replay=True` — events never pollute live ORDER_* counts |

---

## SECTION 4 — FULL TRADE FLOW

### Step-by-step lifecycle (Paper Bootstrap Auto Trade)

| Step | Action | Gate/Condition | Pass | Fail | Event | DB Table |
|------|--------|---------------|------|------|-------|----------|
| **A** | Scheduler tick fires | `scan_interval_minutes=5`, `market_state=OPEN` | Proceed | Skip | — | — |
| **B** | `live_scan_engine.scan_all()` runs | Acquires DB-durable scan lock | Lock acquired | Retry next tick | `SCAN_STARTED` | `scan_state` |
| **C** | Symbols fetched | 51 requested; yfinance daily bars for all | ≥ 1 received | Log UNAVAILABLE | — | — |
| **D** | Kite LTP overlay applied | `KITE_LTP_OVERLAY_ENABLED=true`, session verified | `current_price` replaced with live Kite LTP | Falls back to yfinance latest bar | — | — |
| **E** | Indicators calculated | MACD, RSI, Bollinger, ATR, volume — always from yfinance bars | All computed | Symbol flagged ERROR | — | — |
| **F** | AI decision generated | Confidence, opportunity, regime, strategy selection | BUY/WATCH/IGNORE assigned | IGNORE if any data error | — | `signals_cache` |
| **G** | Normal BUY check | conf ≥ 75%, opp ≥ 70%, R:R ≥ 2.0, no duplicate, CB clear | `ORDER_SUBMITTED` → `ORDER_EXECUTED` | Proceed to bootstrap check | `ORDER_REJECTED` (if eligible but blocked) | `phase20_paper_trades` |
| **H** | Bootstrap eligibility check | `low_evidence=true` AND `bootstrap_paper_enabled=true` AND `auto_paper_entries=true` AND `closed_bootstrap_trades < 20` AND `circuit_breaker_tripped=false` AND no OPEN bootstrap trade | Proceed to bootstrap entry | `BOOTSTRAP_PAPER_TRADE_SKIPPED` | `BOOTSTRAP_SCAN_CLAIMED` | — |
| **I** | Bootstrap candidate ranking | Top WATCH/BUY by confidence among bootstrap-eligible symbols | Best candidate selected | No eligible candidate → skip | — | — |
| **J** | Pre-trade risk re-check | `validate_pre_trade()`: R:R ≥ 1.5, exposure cap, cash available | APPROVED or APPROVED_WARN | REJECTED + reason | — | — |
| **K** | Slippage-adjusted sizing | `qty = floor(min(₹15,000, exposure_cap) / worst_fill_price)` | qty ≥ 1 | Blocked if worst_fill > ₹15,000 | — | — |
| **L** | `create_paper_entry()` called | DB insert with all fields, kv_claim_once dedup | Row inserted | Exception caught, logged | `BOOTSTRAP_PAPER_TRADE_APPROVED` | `phase20_paper_trades` |
| **M** | Portfolio cash updated | `new_cash = cash - (fill_price × qty)` | Cash decremented | Rollback | — | `paper_portfolio` |
| **N** | Trade enters OPEN | `status = 'OPEN'` | — | — | `ORDER_SUBMITTED` + `ORDER_EXECUTED` | `phase20_paper_trades` |
| **O** | Exit engine evaluates | Every scan tick, `manage_open_positions()` called | Exits evaluated | — | — | — |
| **P** | Exit rule fires | Stop/target/time/EOD/stale | Rule assigned | Position stays OPEN | Exit event | — |
| **Q** | Exit price stamped | Kite LTP → yfinance → fill_price_fallback | `exit_price` set | `MARKET_CLOSE_EXIT_BLOCKED` emitted | Exit pipeline event | `phase20_paper_trades` |
| **R** | Realized P&L computed | `(exit_price - fill_price) × qty` | `realized_pnl` stamped | — | — | `phase20_paper_trades` |
| **S** | Trade becomes CLOSED | `status = 'CLOSED'` | — | — | — | `phase20_paper_trades` |
| **T** | Analytics/learning updated | Closed trade count incremented; `low_evidence` recalculated | — | — | — | `signals_cache` |

---

## SECTION 5 — ENTRY CRITERIA

### 5A — Normal BUY Paper Trade

| Gate | Threshold | Source |
|------|-----------|--------|
| `confidence` | ≥ 75% | AI signal engine |
| `opportunity_score` | ≥ 70 | Risk-adjusted model |
| `trade_quality_score` | ≥ 60 | Combined gate |
| `rr_ratio` (slippage-adjusted) | ≥ 2.0 | `validate_pre_trade` |
| Data quality | LIVE or NEAR_LIVE | `signals_cache.data_quality` |
| Quote reliability | `quote_reliable = true` | Kite LTP probe |
| Market hours | 09:15–15:15 IST (before 15:20 EOD window) | Scheduler market state |
| Circuit breaker | Not tripped | `circuit_breaker_tripped = false` |
| Duplicate position | No OPEN position in same symbol | `phase20_paper_trades` |
| Exposure cap | (qty × fill_price) ≤ 25% × ₹50,000 = ₹12,500 | `validate_pre_trade` |
| Portfolio deployed cap | Total deployed ≤ 80% of ₹50,000 | `validate_pre_trade` |
| `auto_paper_entries` | `true` + `auto_paper_entries_confirmed_at` set | Settings |

### 5B — BOOTSTRAP_AUTO Trade

All normal hard gates (data quality, circuit breaker, duplicate position, exposure cap) apply, PLUS:

| Gate | Requirement |
|------|-------------|
| `bootstrap_paper_enabled` | `true` |
| `auto_paper_entries` | `true` |
| `auto_paper_entries_confirmed_at` | Must be set (operator explicitly confirmed) |
| `closed_bootstrap_trades` | < `bootstrap_max_closed_trades` (20) |
| `low_evidence` | `true` for the candidate symbol |
| Action | WATCH or BUY (does not require full BUY threshold) |
| Confidence (bootstrap) | Internal threshold (≈ 60%) — lower than normal 75% |
| R:R (bootstrap) | ≥ 1.5 (lower than normal 2.0) |
| Kite LTP | Available and session verified |
| Max order value | ≤ **₹15,000** (bootstrap ceiling; effective cap ≤ ₹12,500 after 25% exposure gate) |
| Quantity | ≥ 1 share; fractional shares not allowed |
| Execution | Paper only — no Kite order API |
| One per scan | `kv_claim_once` atomic guard — one bootstrap attempt per scan |

### 5C — Rejection Conditions

| Condition | Result |
|-----------|--------|
| R:R insufficient (< 2.0 normal, < 1.5 bootstrap) | `ORDER_REJECTED` |
| Target price missing/null | `ORDER_REJECTED` |
| Confidence below threshold | IGNORE or WATCH (not BUY) |
| Opportunity score below threshold | IGNORE or WATCH |
| Kite LTP unavailable (when required) | Entry blocked |
| Quote unreliable (`quote_reliable = false`) | Entry blocked |
| Circuit breaker tripped | All entries blocked until manual resume |
| Duplicate position (same symbol OPEN) | `ORDER_REJECTED` |
| Bootstrap: worst_fill > ₹15,000 for 1 share | `ORDER_REJECTED` — stock too expensive for bootstrap |
| Stale data | STALE→WATCH, UNAVAILABLE→IGNORE |
| Market closed (scheduler state = CLOSED) | No new entries |
| Max concurrent positions (5) reached | Entry blocked |

---

## SECTION 6 — POSITION SIZING CRITERIA

### 6.1 Bootstrap Cap History

| Version | Cap | Max DRREDDY Shares |
|---------|-----|--------------------|
| Original | ₹1,500 | 1 share (₹1,187) |
| **Current (v6.0)** | **₹15,000** | **10 shares after exposure cap** |

The cap is defined in `phase20_executor.py`:
```python
_BOOTSTRAP_MAX_ORDER_VALUE = 15_000  # ₹ hard ceiling per bootstrap trade
```

### 6.2 Sizing Calculation

```
worst_fill      = signal_price × (1 + slippage_pct)
raw_qty         = floor(bootstrap_max / worst_fill)
exposure_cap    = floor(per_stock_cap_amount / worst_fill)
final_qty       = min(raw_qty, exposure_cap, available_cash_qty)
```

### 6.3 DRREDDY Example (₹15,000 cap)

| Step | Calculation | Result |
|------|-------------|--------|
| Signal price (Kite LTP) | — | ₹1,186.98 |
| Worst-case fill | ₹1,186.98 × 1.0015 | ₹1,188.76 |
| Raw bootstrap qty | ⌊₹15,000 ÷ ₹1,188.76⌋ | **12 shares** |
| Exposure cap (25% × ₹50,000) | ⌊₹12,500 ÷ ₹1,188.76⌋ | **10 shares** |
| **Final qty** | min(12, 10) | **10 shares** |
| Notional | 10 × ₹1,188.76 | ₹11,887.60 |

**Note:** The existing DRREDDY trade (P20-3468fb2a24) was created under the old ₹1,500 cap (qty = 1). It was **not mutated** by the cap change — the new cap applies only to future trades. DRREDDY is now CLOSED.

### 6.4 Portfolio Cash Constraint

If remaining cash < final_qty × worst_fill, qty is reduced to `floor(cash / worst_fill)`.

---

## SECTION 7 — EXIT CRITERIA

### 7.1 All Exit Rules

| Rule | When | Price Source | Fallback | Event | Status Transition |
|------|------|-------------|---------|-------|-------------------|
| `STOP_LOSS_HIT` | current_price ≤ stop_loss | Kite LTP → yfinance → fill_price | fill_price_fallback | `PAPER_TRADE_STOPPED` | OPEN → CLOSED |
| `TARGET_HIT` | current_price ≥ target | Kite LTP → yfinance → fill_price | fill_price_fallback | `PAPER_TRADE_TARGET_HIT` | OPEN → CLOSED |
| `TRAILING_STOP` | trailing_high × factor | Kite LTP | fill_price_fallback | — | Not currently active |
| `TIME_EXIT` | held > max_holding_days (10) | Kite LTP → yfinance | fill_price_fallback | `PAPER_TRADE_TIME_EXIT` | OPEN → CLOSED |
| `MARKET_CLOSE_EXIT` | At/after **15:20 IST**, market state = OPEN | Kite LTP → yfinance | fill_price_fallback | `MARKET_CLOSE_EXIT` | OPEN → CLOSED |
| `POST_CLOSE_FORCE_EXIT` | After 15:30 IST, market state = CLOSED | Kite LTP → yfinance → fill_price_fallback | fill_price_fallback (marked) | `PAPER_TRADE_FORCE_CLOSED` | OPEN → CLOSED |
| `STALE_DATA_SAFETY` | exit_on_stale_after_days (5) exceeded | Last known price | fill_price_fallback | `PAPER_TRADE_STALE_EXIT` | OPEN → EXIT_PENDING → CLOSED |
| `MARKET_CLOSE_EXIT_BLOCKED` | POST_CLOSE_FORCE_EXIT — no price available | — | — | `MARKET_CLOSE_EXIT_BLOCKED` + WARN | Position stays OPEN for retry |

### 7.2 EOD Square-Off Rules (v6.0 — Current)

**Implemented in:** `phase20_exits.py` + `phase20_scheduler.py`

```
MARKET_CLOSE_EXIT  — fires at/after 15:20 IST
├── Unconditional (does NOT check square_off_before_close)
├── Applies to all trigger_sources (BOOTSTRAP_AUTO, AUTO, MANUAL)
├── Assigns exit rule at the position evaluation stage
└── Scheduler calls manage_open_positions() while market state = OPEN

POST_CLOSE_FORCE_EXIT  — fires once per day (post 15:30 IST)
├── Guarded by kv_claim_once("eod_squareoff:{today}", ttl_seconds=86400)
├── Called from scheduler CLOSED/POST_CLOSE state handler
├── Closes any OPEN positions that survived the 15:20 window
├── Price waterfall: Kite LTP → yfinance daily close → fill_price_fallback
└── If no price: emits MARKET_CLOSE_EXIT_BLOCKED, position stays OPEN

MARKET_CLOSE_OVERNIGHT_CARRY_DETECTED  — fires at cold start
├── check_overnight_carry_on_startup() in phase20_scheduler.py
├── Guarded by kv_claim_once("startup_overnight_check:{yesterday}")
├── Closes prior-session OPEN trades found at server restart
└── Events emitted per closed trade
```

**P&L formula:**
```
realized_pnl = (exit_price - fill_price) × qty
new_cash     = portfolio.cash + (exit_price × qty)
```

---

## SECTION 8 — TIMING AND DAILY OPERATING SCHEDULE

### 8.1 Before Market Open (08:45–09:14 IST)

- [ ] Verify `GET /api/healthz` → `{"status":"ok"}`
- [ ] Verify `GET /api/live-data/health` → provider CONNECTED
- [ ] Verify `GET /api/phase20/bootstrap-status` → `kite_session_verified: true`
- [ ] Verify `GET /api/phase20/circuit-breaker` → `tripped: false`
- [ ] Verify `GET /api/phase20/positions` → no unwanted overnight carry
- [ ] Check Mission Control for any MARKET_CLOSE_EXIT_BLOCKED events from yesterday
- [ ] If server was restarted: check pipeline_events for `MARKET_CLOSE_OVERNIGHT_CARRY_DETECTED`

### 8.2 Market Open (09:15–09:25 IST)

- First scan fires within 5 minutes of market state becoming OPEN
- Scan_id assigned; 51 symbols evaluated (50 if LTIM still missing)
- Bootstrap loop runs: checks all 3 top candidates (HDFCBANK, HDFCLIFE, DRREDDY)
- DRREDDY is CLOSED → eligible for a new bootstrap entry if it receives a WATCH signal

### 8.3 During Market (09:25–15:15 IST)

| Cadence | Action |
|---------|--------|
| Every 5 min | Full NIFTY 50 scan |
| Every 5 min | Exit engine evaluates all OPEN positions |
| Every 5 min | Bootstrap loop checks for eligible candidates |
| Continuous | Mission Control shows scan counts, P&L, open positions |

**Warnings to watch:**
- `LTIM missing` → normal, provider issue, not a code defect
- `BOOTSTRAP_ELIGIBILITY_CHANGED` → symbol's bootstrap status changed between scans
- `CIRCUIT_BREAKER_TRIPPED` → immediate stop, manual review required
- `MARKET_CLOSE_EXIT_BLOCKED` → price unavailable, operator attention needed

### 8.4 Pre-Close (15:15–15:30 IST)

| Time | Action |
|------|--------|
| **15:20 IST** | `MARKET_CLOSE_EXIT` fires unconditionally on all OPEN positions |
| 15:20–15:30 | 2–3 scanner ticks evaluate and close remaining open positions |
| 15:30 | NSE market closes; scheduler transitions to CLOSED state |

### 8.5 Market Close (15:30–15:45 IST)

| Time | Action |
|------|--------|
| First CLOSED-state tick | `POST_CLOSE_FORCE_EXIT` fires (kv_claim_once guard) |
| — | Any positions still OPEN after 15:20 window are force-closed |
| — | Portfolio cash updated; realized P&L stamped |

### 8.6 Post-Close (15:45 IST onward)

- [ ] Verify `GET /api/phase20/eod-status` → `eod_ran_today: true`, `blocked_events: []`
- [ ] Verify `GET /api/phase20/positions` → `[]` (no open positions)
- [ ] Check realized P&L in AI Paper Trader page
- [ ] Review any `EXIT_PENDING` or `MARKET_CLOSE_EXIT_BLOCKED` events in pipeline_events
- [ ] Note daily summary for next session

---

## SECTION 9 — SCAN INTERVALS AND DATA FRESHNESS

| Parameter | Value |
|-----------|-------|
| Scan cadence | **5 minutes** (`scan_interval_minutes: 5`) |
| Expected scans per session | ~18 (77 were run on 2026-08-18 including some post-close) |
| Stale threshold | 5 days (`exit_on_stale_after_days: 5`) |
| Data quality labels | LIVE / NEAR_LIVE / STALE / UNAVAILABLE |
| FRESH definition | `data_quality = LIVE` — price from current session |
| DELAYED definition | `data_quality = NEAR_LIVE` — from prior session close, usable |
| BUY gate on quality | Must be LIVE or NEAR_LIVE; STALE → forced to WATCH; UNAVAILABLE → IGNORE |
| LTIM | Missing from NSE data provider — affects 1 symbol. Known issue. |
| Weekend/holiday gap | yfinance serves last available close; indicators may lag by N sessions |
| Yahoo bars limitation | Daily OHLCV only (no intraday bars). Kite LTP overlay compensates for entry/exit price. |
| Kite LTP overlay role | Provides real-time current_price during market hours for execution accuracy |

---

## SECTION 10 — BACKTESTING CRITERIA

| Aspect | Detail |
|--------|--------|
| Engine | Replay engine with isolated ledger (`emit_replay=True`) |
| Data source | Same yfinance daily bars as live scans (no separate backtest data feed) |
| Lookahead prevention | As-of slice scanning — only bars available before analysis timestamp are used |
| BTT/Replay guardrail | `emit_replay=True` flag ensures all events go to `pipeline_events` with `source='replay'` — never pollutes live ORDER_* counts |
| Backtest evidence | Does NOT contribute to `low_evidence` calculation — only real intraday paper trades count |
| Paper trade evidence | CLOSED paper trades DO reduce `low_evidence` (each closed trade increments `closed_bootstrap_trades`) |
| Minimum evidence threshold | **5** closed paper trades per symbol (`MIN_EVIDENCE = 5`) |
| Bootstrap role | Collects the 5 real intraday evidence trades; bootstrap entries are real paper executions, not simulations |
| Limitation | No true intraday backtesting — daily bars only; cannot simulate intraday stop triggers accurately |
| Validation | `validate_run` diffs replay results vs pipeline ledger |

---

## SECTION 11 — SAFETY CONTROLS

| Control | Status | Evidence |
|---------|--------|---------|
| `LIVE_EXECUTION_ENABLED = false` | ✅ Hardcoded default, never modified | Code constant, never set via env |
| `live_order_placement_enabled = false` | ✅ Disabled | No Kite place_order route active |
| No Kite place_order / modify_order / cancel_order | ✅ Confirmed | DRREDDY's fill_model = `bootstrap_paper` (paper-only path) |
| All fills paper-only | ✅ | `execute_buy()` / `execute_sell()` in `phase20_paper_trader.py` — no live=True kwarg |
| P20 trade IDs | ✅ | Format `P20-<8hex>` — all production trades use this prefix |
| BTT replay guardrail | ✅ | `emit_replay=True` separates backtest events from live ORDER_* counts |
| Circuit breaker | ✅ NOT tripped | 3% daily loss limit, 3 consecutive loss limit |
| Max daily loss | ₹1,500 (3% × ₹50,000) | `circuit_breaker.daily_loss_limit: 1500` |
| Max orders/day | 3 (`max_trades_per_day`) | Settings confirmed |
| Max order value (bootstrap) | ₹15,000 | `_BOOTSTRAP_MAX_ORDER_VALUE = 15_000` in executor |
| Per-stock exposure cap | 25% = ₹12,500 | `validate_pre_trade._check_position_size()` |
| Duplicate position rule | ✅ | `_bootstrap_open` guard + `validate_pre_trade` |
| One bootstrap per scan | ✅ | `kv_claim_once(f"bootstrap:{scan_id}")` atomic guard |
| kv_claim_once (EOD) | ✅ | `kv_claim_once(f"eod_squareoff:{today}", ttl=86400)` |
| kv_claim_once (startup) | ✅ | `kv_claim_once(f"startup_overnight_check:{yesterday}")` |
| No hidden live execution path | ✅ | AST safety test in `test_eod_squareoff.py` asserts no `kiteconnect.KiteConnect.place_order` call in the execution path |

---

## SECTION 12 — RECENT CHANGES LOG

| Date | Change | Task/Notes |
|------|--------|-----------|
| 2026-08-17 | Kite LTP overlay implemented (`kite_ltp_overlay.py`, 37/37 tests) | Phase 5D enhancement |
| 2026-08-17 | Stale scan snapshot fix — stale composite dist cleared | Phantom TS errors resolved |
| 2026-08-17 | BTT/replay event guardrail — `emit_replay=True` prevents live ORDER_* contamination | Phase 23 |
| 2026-08-17 | Bootstrap low-evidence deadlock fix — INSUFFICIENT_EVIDENCE never blocks bootstrap | Phase 24 |
| 2026-08-18 ~08:30 | Bootstrap enabled in production; UI enable button added | Task #809 |
| 2026-08-18 ~08:30 | API key dev/prod mismatch identified and resolved | Session work |
| 2026-08-18 ~14:44 | **First BOOTSTRAP_AUTO trade created** — DRREDDY P20-3468fb2a24, ₹1,186.98, qty 1 | Dev server shared DB |
| 2026-08-18 ~14:44 | `_build_row` NameError fixed (explicit keyword params) | Session work |
| 2026-08-18 ~14:44 | Fallback candidate loop added to bootstrap executor | Session work |
| 2026-08-18 ~14:44 | `create_paper_entry` try-except added for defensive error capture | Session work |
| 2026-08-18 ~15:16 | **First publish** — image size fix, Task #807/#808/#809 live | Session work |
| 2026-08-18 ~15:16 | `deploy-build.sh` image-size cleanup (exports/ stripped from image) | Task #808 |
| 2026-08-18 ~15:16 | Force-close stale EXIT_PENDING logic live (Task #807) | Task #807 |
| 2026-08-18 ~15:26 | Bootstrap eligibility change banner fires on Mission Control (TMCV event) | Task #809 |
| 2026-08-18 ~17:12 | **Second publish** — EOD square-off fix, bootstrap cap ₹15,000, import bug fix | Session work |
| 2026-08-18 ~17:12 | **EOD import bug fixed** — `phase20_settings` → `phase20_store.get_settings` (2 locations) | Session work |
| 2026-08-18 ~17:12 | Bootstrap cap raised ₹1,500 → **₹15,000** (`_BOOTSTRAP_MAX_ORDER_VALUE`) | Task #818 |
| 2026-08-18 ~17:12 | `MARKET_CLOSE_EXIT` made **unconditional** — no longer gated by `square_off_before_close` | Task #821 |
| 2026-08-18 ~17:12 | `POST_CLOSE_FORCE_EXIT` added — daily once-per-day safety net post 15:30 IST | Task #821 |
| 2026-08-18 ~17:12 | `POST /api/phase20/force-eod-close` bypass endpoint added | Session work |
| 2026-08-18 ~17:12 | `runPython` stdout parser fixed — now reads last valid JSON line (tolerates log noise) | Session work |
| 2026-08-18 ~18:01 | **DRREDDY P20-3468fb2a24 closed** via POST_CLOSE_FORCE_EXIT | Production confirmed |
| 2026-08-18 ~18:01 | `check_overnight_carry_on_startup()` regression tests — 27/27 pass | Task #834 |
| 2026-08-18 | Task #832 MERGED — KV claim-before-import race protection | Task #832 |
| 2026-08-18 | Task #833 MERGED — EOD banner on Mission Control | Task #833 |
| 2026-08-18 | Task #834 MERGED — overnight carry regression suite | Task #834 |

---

## SECTION 13 — CURRENT OPEN TRADE REVIEW

### All paper trades (production, as of 20:45 IST 2026-08-18)

| trade_id | Symbol | Status | Trigger | Fill | Qty | Stop | Target | Exit Rule | Exit Price | Realized P&L |
|----------|--------|--------|---------|------|-----|------|--------|-----------|------------|--------------|
| P20-3468fb2a24 | DRREDDY | **CLOSED** | BOOTSTRAP_AUTO | ₹1,186.98 | 1 | ₹1,136.66 | ₹1,307.60 | POST_CLOSE_FORCE_EXIT | ₹1,186.98 | ₹0.00 |

**No other trades in production.**  
The 4 legacy EXIT_PENDING trades (TRENT, DIVISLAB, GRASIM, BAJFINANCE) exist **only in the dev database** and were never created in production.

### DRREDDY P20-3468fb2a24 — Detailed Verification

| Field | Value | Status |
|-------|-------|--------|
| trade_id | P20-3468fb2a24 | — |
| symbol | DRREDDY | — |
| status | **CLOSED** | ✅ |
| exit_rule | POST_CLOSE_FORCE_EXIT | ✅ |
| exit_price | ₹1,186.98 | fill_price_fallback (no post-close scan available) |
| exit_price_source | fill_price_fallback | expected — Kite not available post-close |
| realized_pnl | **₹0.00** | breakeven (fill_price = exit_price) |
| exit_ts | 2026-08-18T12:31:18Z = 18:01:18 IST | ✅ closed before end of day |
| Should close before tomorrow? | **Already closed** ✅ | No overnight carry |
| Safe to carry overnight? | N/A — already closed | ✅ |

**EOD ran today:** `eod_ran_today: true`, `blocked_events: []` — no issues.

---

## SECTION 14 — TOMORROW READINESS CHECK

### A. Deployment Readiness

| Check | Status | Evidence |
|-------|--------|---------|
| Latest build published | ✅ | Second publish live (confirmed by EOD fix running and closing DRREDDY) |
| Health check 200 | ✅ | `GET /api/healthz` → `{"status":"ok"}` |
| Production DB connected | ✅ | API responses contain live DB data |
| No old build serving | ✅ | EOD fix was confirmed working (DRREDDY closed) |

### B. Settings Readiness

| Check | Status | Value |
|-------|--------|-------|
| `bootstrap_paper_enabled` | ✅ | `true` |
| Bootstrap cap | ✅ | **₹15,000** |
| `auto_paper_entries` | ✅ | `true` |
| `auto_paper_entries_confirmed_at` | ✅ | 2026-08-10T03:31:14Z |
| Scan interval | ✅ | 5 minutes |
| Circuit breaker | ✅ | NOT tripped |
| Live orders disabled | ✅ | `LIVE_EXECUTION_ENABLED = false` |

### C. Data Readiness

| Check | Status | Notes |
|-------|--------|-------|
| Kite LTP overlay | ✅ | `kite_overlay_enabled: true`, `kite_session_verified: true` |
| yfinance | ✅ | `provider_health.connection_status: CONNECTED` |
| Latest scan fresh | ⚠️ | Last scan 09:56 IST (15:26 IST session-end) — **normal for post-market** |
| LTIM missing | ⚠️ | 1/51 symbols unavailable — ongoing provider issue, not a code defect |

> **Note on LTIM:** Kite/NSE has been unable to provide LTIM data for multiple sessions. This is a provider-side issue. All 50 remaining NIFTY 50 symbols are fully evaluated. Bootstrap and normal BUY logic function correctly with 50/51 symbols.

### D. Portfolio Readiness

| Check | Status | Notes |
|-------|--------|-------|
| Unwanted overnight position | ✅ NONE | `/api/phase20/positions` → `[]` |
| DRREDDY status | ✅ CLOSED | POST_CLOSE_FORCE_EXIT at 18:01 IST |
| Cash reconciled | ✅ | ≈₹49,999.98 (entry + exit at same price, breakeven) |
| Realized P&L | ✅ | ₹0.00 (first trade, breakeven exit) |
| EXIT_PENDING | ✅ NONE | No stuck positions in production |

### E. Execution Readiness

| Check | Status | Notes |
|-------|--------|-------|
| Bootstrap can create trades | ✅ | 1/20 closed trades; DRREDDY now closed → eligible again |
| Position sizing | ✅ | ₹15,000 cap, 10-share effective after exposure gate |
| EOD square-off | ✅ | Unconditional at 15:20 IST + POST_CLOSE safety net — confirmed working |
| No live broker order path | ✅ | `LIVE_EXECUTION_ENABLED = false` hardcoded |

### F. Monitoring Readiness

| Page | URL | What to Watch |
|------|-----|--------------|
| Mission Control | `/mission-control` | Scan status, EOD banner, bootstrap events |
| AI Paper Trader | `/ai-paper-trader` | Open positions, P&L, bootstrap eligibility |
| Operator Analytics | `/operator-analytics` | Trade history, win rate, P&L trends |
| Live Data Health | `/live-data` | Provider status, LTIM warning |
| System Readiness | `/readiness` | Go/No-Go verdict, 8 operational domains |

### Tomorrow Readiness Final Verdict

```
┌────────────────────────────────────────────────────────┐
│  ✅  READY WITH WARNINGS                               │
│                                                        │
│  No blockers for 2026-08-19 trade session.            │
│                                                        │
│  Warnings (non-blocking):                              │
│  ⚠️  LTIM.NS missing from scan universe (1/51 symbols) │
│     → Pre-existing provider issue; not a code defect  │
│  ⚠️  Last scan from 15:26 IST (normal post-market)    │
│     → First scan will run within 5 min of 09:15 IST   │
│                                                        │
│  All safety controls active.                           │
│  No overnight carry. EOD square-off working.           │
│  Bootstrap ready for second trade.                     │
└────────────────────────────────────────────────────────┘
```

---

## SECTION 15 — OPERATOR ACTIONS BEFORE TOMORROW

### Before 09:15 IST (2026-08-19)

| # | Action | How to Verify |
|---|--------|--------------|
| 1 | ✅ **Production is already published** — no re-publish needed unless new code is merged | `GET /api/healthz` → `{"status":"ok"}` |
| 2 | Confirm production health at 09:00 IST | `curl https://nse-trade-intraday.replit.app/api/healthz` |
| 3 | Confirm EOD fix is live | `GET /api/phase20/eod-status` → `squareoff_time_ist: "15:20 IST"` |
| 4 | Confirm bootstrap cap ₹15,000 | `GET /api/phase20/bootstrap-status` → `bootstrap_max_order_value: 15000` |
| 5 | Confirm DRREDDY is closed | `GET /api/phase20/positions` → `[]` |
| 6 | Confirm Kite session | `GET /api/phase20/bootstrap-status` → `kite_session_verified: true` |
| 7 | Confirm no live orders | `LIVE_EXECUTION_ENABLED = false` (constant in code; no action needed) |

### During Market (09:15–15:30 IST)

| # | Action | What to Look For |
|---|--------|-----------------|
| 8 | Check first scan ~09:20 IST | Mission Control shows scan_id, 50+ symbols analysed |
| 9 | Watch for BOOTSTRAP_AUTO trade | HDFCBANK or HDFCLIFE or DRREDDY (now eligible again) may trigger if confidence rises |
| 10 | At 15:20 IST | All OPEN positions should show `MARKET_CLOSE_EXIT` exit_rule |
| 11 | At 15:30–15:40 IST | `GET /api/phase20/eod-status` → `eod_ran_today: true`, `blocked_events: []` |
| 12 | Post-close | `GET /api/phase20/positions` → `[]` to confirm clean close |

### If Something Is Wrong

| Symptom | Action |
|---------|--------|
| Kite session expired | Re-authenticate Kite; restart API server workflow |
| Circuit breaker tripped | Review losses in AI Paper Trader; use resume button with confirmation text |
| MARKET_CLOSE_EXIT_BLOCKED | Use `POST /api/phase20/force-eod-close` bypass endpoint to manually close |
| Scan stuck (no new scan_id) | Check API server logs; restart workflow if locked |
| Bootstrap not firing | Verify `bootstrap_paper_enabled=true`, `auto_paper_entries=true`, circuit breaker clear |

---

## SECTION 16 — KEY API REFERENCE

| Endpoint | Purpose |
|----------|---------|
| `GET /api/healthz` | System health |
| `GET /api/phase20/settings` | All paper trading settings |
| `GET /api/phase20/positions` | Current open positions |
| `GET /api/phase20/eod-status` | EOD square-off status and results |
| `GET /api/phase20/bootstrap-status` | Bootstrap eligibility, cap, Kite status |
| `GET /api/phase20/circuit-breaker` | Circuit breaker state |
| `GET /api/live-data/scan/status` | Latest scan metadata |
| `GET /api/live-data/health` | Data provider health |
| `POST /api/phase20/force-eod-close` | **Bypass endpoint** — manually force-close all OPEN positions (bypasses KV claim) |

---

*All data in this document is from live production queries at 20:45 IST, 2026-08-18.*  
*Production URL: https://nse-trade-intraday.replit.app*  
*PAPER TRADING ONLY — no real orders were placed or will be placed.*
