# CAPITAL DEPLOYMENT FIX — VERIFICATION REPORT

Date: 2026-08-11 · Scope: backtest/paper research only · **PAPER / RESEARCH ONLY — no live trading logic was touched or enabled.**

---

## 1. What changed

| Area | Change |
|---|---|
| `backtest_runner.py` | Hardcoded `RISK_PER_TRADE_PCT=1` / `MAX_POSITION_PCT=25` replaced by settings-driven `resolve_sizing()` with 9 knobs (`risk_per_trade_pct`, `max_position_cap_pct`, `max_symbol_exposure_pct`, `max_total_exposure_pct`, `scale_in_enabled`, `max_scale_in_count`, `scale_in_min_confidence`, `scale_in_min_rr`, `scale_in_min_unrealized_profit_pct`). Defaults reproduce the old constants exactly. |
| `backtest_runner.py` | Controlled scale-in: when (and only when) `scale_in_enabled=true`, an additional tranche is allowed after 10 guards pass (fresh BUY signal with all market/safety gates already passed, confidence ≥ threshold, RR ≥ threshold, valid stop/target, existing position not below the unrealized-P&L floor, scale-in count below limit, symbol-exposure cap, total-exposure cap, sufficient cash). Every attempt emits `SCALE_IN_APPROVED` / `SCALE_IN_REJECTED` (exact reason stored) and executed tranches emit `SCALE_IN_EXECUTED`. Tranches are separate ledger rows — never merged or hidden. |
| `backtest_portfolio.py` | `tranche` column added (default 0). Unique open-position index became `(run_id, symbol, tranche) WHERE status='OPEN'` — tranche 0 preserves the historical one-open-position rule at the DB level. DDL is serialized with an advisory lock (concurrent workers previously deadlocked). |
| `backtest_runner.py` (Task 4) | Intraday-only, opt-in (`volume_time_normalized=true`) time-of-day volume normalization: session-so-far volume ÷ average session-to-date volume *at the same time-of-day* over prior sessions in the as-of window (no look-ahead). Fewer than 5 prior sessions ⇒ labelled insufficient evidence and the raw full-day ratio is used — nothing is fabricated. |
| `live_scan_engine.py` | Volume gate reads the normalized ratio **only** when the backtest attaches it via `df.attrs`; the gate reason states the basis. LIVE and daily scans never receive attrs ⇒ unchanged. |
| `routes/backtest.ts`, `main.py backtest_start` | Pass-through of optional `sizing` + `volume_time_normalized` in the run config. |
| `pipeline_events.py` | `SCALE_IN_*` added to the canonical event-type list. |
| Tests | `test_backtest_scale_in.py` (20 tests) — see §4/§Safety. Full backtest suite: **44/44 pass** (`test_backtest_engine.py` 24 + new 20). |
| Hardening (post code review) | `resolve_sizing` strictly validates every knob (finite numbers within safe bounds, JSON booleans only — NaN/Inf/negative/string inputs fall back to defaults, so exposure caps can never be bypassed by a malformed payload); the index migration creates the replacement unique index **before** dropping the legacy one; the volume-gate override in `live_scan_engine` is additionally gated on `data_source == "backtest_cache"`, so a live provider dataframe can never activate it. |

## 2. What did NOT change

- Live scan pipeline decisions (strategies, thresholds, BUY threshold, risk gates, market_open/scan_fresh) — untouched.
- Live/paper phase20 executor, ledger, settings — untouched. Backtests remain fully isolated.
- Daily-interval backtests — volume gate and behaviour byte-identical.
- Default backtest behaviour — see §4.
- No new pages.

## 3. Confirmation: no live trading logic enabled

- `_try_enter` / `_scale_in_guards` touch only the isolated backtest ledger (asserted by test `test_live_ledger_untouched`).
- `LIVE_EXECUTION_ENABLED` and all live/paper defaults untouched; no orders of any kind are placed by this work.
- All runs and events are `mode=BACKTEST`, labelled "BACKTEST — SIMULATED, ISOLATED FROM LIVE".

## 4. Confirmation: default behaviour unchanged unless scale-in enabled

- `resolve_sizing({})` returns exactly the historical constants (regression test).
- With defaults, a second BUY for an open symbol emits the same `ORDER_CANCELLED / "Open backtest position already exists"` event and consumes no cash (regression test).
- Default quantity formula reproduces the historical sizing to the share (166 shares in the reference fixture — test).
- Empirical proof: baseline re-run **A** (`BT-1dd403e980`) under the new code reproduced the pre-change run `BT-22f70ec360` exactly — 2 trades, +₹4,094.92, same fills.

## 5. GLAND 5m comparison (2026-06-18 → 2026-08-11, ₹1,00,000, 2,780 ticks)

| Metric | A Baseline (`BT-1dd403e980`) | B Scale-in (`BT-acab5cf232`) | C Sizing 1.5% (`BT-67b265939f`) | D Combined (`BT-0587e32d0b`) |
|---|---|---|---|---|
| Config | defaults | scale-in ON, count 2, risk 1%, sym 25%, total 80% | scale-in OFF, risk 1.5%, cap 25% | scale-in ON, count 2, risk 1.5%, sym 25%, total 80%, vol-normalized |
| Trades executed | 2 | **5** (3 scale-ins) | 2 | 2 |
| BUY approvals | 1,592 | 1,592 | 1,592 | **2,261** |
| Cancelled (position exists) | 1,590 | 0 (→1,587 scale-in rejections, exact reasons) | 1,590 | 0 (→2,259 rejections) |
| Scale-ins approved/executed | — | 3 / 3 | — | 0 / 0 |
| Volume-only risk rejections | 1,184 | 1,184 | 1,184 | **515** (−56%) |
| Peak capital deployed / trade | 11–16% | 11–14% (per tranche; ~22% symbol total) | 18–24% | 18–24% |
| Realized P&L | ₹4,094.92 | ₹5,172.15 | **₹6,354.70** | ₹6,159.31 |
| Net return | 4.06% | 5.11% | 6.30% | 6.11% |
| Max drawdown (realized-equity) | 0% | 0% | 0% | 0% |
| Win rate / largest loss | 100% / none | 100% / none | 100% / none | 100% / none |
| Missed opportunities (top-100 cap) | 100 | 100 | 100 | 100 |
| Risk per trade | 1% | 1% per tranche | 1.5% | 1.5% |

Notes:
- **B**: one same-day scale-in (18 Jun, tranche 1, +₹2,123) plus two late tranches on 11 Aug. Scale-ins after the initial run-up were mostly rejected by the 25% **symbol-exposure cap** (~32–35% would-be exposure) — the cap did its job; the exact reason is stored on all 1,587 rejections.
- **D**: with 1.5% tranches, the first tranche alone sits at ~24% of cash, so *every* scale-in hit the 25% symbol cap → 0 scale-ins. Bigger base sizing and scale-in compete for the same symbol cap.
- **Volume normalization (D)** worked as designed: BUY approvals +42% (2,261 vs 1,592) and volume-only rejections −56% (515 vs 1,184), confirming the morning bias was structural. It did not change executed trades here purely because the one-position/exposure limits bound first.
- Pipeline-parity validation on D: **MATCH, 25/25, 0 mismatches** — the normalized replay still reproduces `_scan_one` exactly.

## 6–9. Answers

6. **Capital utilization improved?** Yes. Per-position deployment rose from 11–16% (A) to 18–24% (C/D); B deployed ~22% in the symbol across tranches on day one. Still bounded by the 25% symbol cap — by design.
7. **P&L improved?** Yes in every variant: B +26%, D +50%, C **+55%** vs baseline.
8. **Drawdown increased?** No. All four runs: 0% realized-equity drawdown, no losing trades, largest loss = none. (Same caveat as prior audits: the equity curve is realized-only, so intratrade MTM dips aren't captured.)
9. **Volume normalization helped?** Directionally yes (it removes the structural morning penalty and roughly doubles gate throughput) but it added no P&L in this single-symbol test because position limits, not the volume gate, were the binding constraint. Its real value should appear in multi-symbol runs.

## 10. Recommendation

**Enable scale-in for wider backtesting — with `risk_per_trade_pct` kept at 1%.** Evidence:
- Simple sizing (C, 1.5%) was the best single lever here (+55% P&L, zero added complexity), but it saturates the 25% symbol cap and starves scale-in (D).
- Scale-in (B) added P&L with per-tranche risk unchanged and every rejection auditable.
- Suggested wider-test config: `scale_in_enabled=true, max_scale_in_count=2, risk_per_trade_pct=1, max_symbol_exposure_pct=25, max_total_exposure_pct=80, volume_time_normalized=true`, on a **multi-symbol** universe where total-exposure and volume normalization actually engage.
- Do **not** change live/paper defaults yet; this remains a backtest-only setting pending those results.

## Safety test matrix (all green — 41/41)

No scale-in when disabled · symbol cap · total cap · cash · stop validity · count limit · confidence · RR · unrealized floor · events + exact reasons recorded · normalization intraday-only · daily unchanged · disabled by default · insufficient-evidence fallback · defaults = historical constants · historical qty formula · live ledger untouched.
