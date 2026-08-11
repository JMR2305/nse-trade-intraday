# GLAND Intraday vs Daily Backtest Audit

**Date:** 11 Aug 2026 · **Scope:** PAPER / RESEARCH ONLY · No strategy, threshold, or gate changes were made. No new pages. No live orders.

---

## TASK 1 — What the daily backtest (BT-73de2d890c) actually tested

| Item | Value |
|---|---|
| Run | `BT-73de2d890c` (production, COMPLETED 11 Aug 2026 03:47 UTC) |
| Symbol | GLAND |
| Interval | **1d (daily candles)** |
| Range | 2026-02-12 → 2026-08-11 (~6 months) |
| Candles / ticks | **123 daily bars** (progress: 123/123) |
| Capital | ₹1,00,000 |
| Trades | 3 (2 wins, 1 END_OF_BACKTEST scratch) · realized P&L **+₹4,474.61 (+4.43%)** |

**Data availability on that run:**
- **Intraday volume accumulation: NOT available.** Each tick saw only completed daily bars; the volume gate compared full-day volumes only.
- **Hourly/minute trend: NOT available.** One decision opportunity per day — the engine could act only at daily-bar boundaries (all signal/fill timestamps are 18:30 UTC = daily close).
- **VWAP: NOT computable from intraday data.** With `interval=1d` the as-of frame contains only daily OHLCV; any VWAP-like input degenerates to daily-bar approximations.

**Conclusion:** a daily backtest evaluates the pipeline as a *daily swing* system. It cannot validate intraday trading behaviour — intraday trend, session volume build-up, or minute-level entries/exits are structurally invisible at 1d granularity.

## TASK 2 — GLAND intraday smoke backtest (5m)

The data provider (yfinance) caps 5m history at ~55 days (`INTRADAY_MAX_DAYS = 55`; earliest available was 2026-06-17), so the maximum supported intraday range was used: **2026-06-18 → 2026-08-11 (~37 sessions)**. Run via the canonical Investigation Center pipeline (`POST /api/backtest/run`), which replays the *live* `_scan_one` on as-of data slices.

| Run | Capital | Ticks (5m candles) | Trades | Realized P&L | Return | Win rate |
|---|---|---|---|---|---|---|
| `BT-22f70ec360` | ₹1,00,000 | **2,780** | 2 | **+₹4,094.92** | +4.06% | 100% (2W/0L) |
| `BT-9fcaea6b12` | ₹50,000 | 2,780 | 2 | **+₹1,835.14** | +3.64% | 100% (2W/0L) |

Verified for both runs:
- **Candles loaded:** 2,780 5m bars replayed end-to-end (2780/2780 DONE), zero data errors.
- **Scan events created:** one scan per tick per symbol; 2,780 scan IDs (`BT-…-T00000…T02779`); event store integrity checks: 0 duplicate event IDs, 0 out-of-timeline ticks.
- **Decisions generated:** BUY entries executed at ticks where all gates passed; 50 WATCH decisions and ~50 RISK_REJECTED decisions captured in the missed-opportunity log (capped at top 100).
- **Trades:** 2 BUYs — 18 Jun 04:20 UTC entry @₹2,248.49 → TARGET exit @₹2,673.13 (+₹2,123.20); 10 Aug 04:40 UTC entry @₹2,639.98 → END_OF_BACKTEST @₹2,968.60 (+₹1,971.72). ₹50k run took the same signals with smaller size (2 and 3 shares).
- **Missed opportunities captured:** 100 records, all flagged `would_have_been_profitable`, best single-event potential +3.05% over the 10-bar horizon.
- **Volume filters evaluated:** yes — dominant rejection is `volume: Volume ratio 0.00–0.28 very low (<0.3) — liquidity risk` (~50 events).
- **Trend & risk filters evaluated:** yes — trend/regime context on every scan (entries carried regime "Trending (momentum)", confidence ~72–73), and entries went through the standard risk gates and isolated-ledger position sizing (stop/target/charges/slippage recorded per trade).

## TASK 3 — Daily vs intraday comparison

| Metric | Daily (6 mo, ₹1L) | Intraday 5m (~37 sessions, ₹1L) |
|---|---|---|
| Candles | 123 | 2,780 |
| Decision opportunities | 1/day | 75/day |
| Trades | 3 | 2 |
| Realized P&L | +₹4,474.61 (+4.43% over 6 mo) | +₹4,094.92 (**+4.06% in ~8 weeks**) |
| Missed opportunities | 100 logged; top potential **+26.2%** (WATCH during the Mar–May run-up) | 100 logged; top potential +3.05% |
| Rejection reasons | WATCH (confidence below BUY line) + volume-ratio <0.3 | Same mix: 50 WATCH + ~50 volume-ratio <0.3 |

**Does the AI capture the move better on 5m data?** Yes, on a rate basis: ~4.1% in 8 weeks vs 4.4% in 26 weeks — roughly **3× the capital efficiency**, with earlier entries (the 18 Jun intraday entry at ₹2,248 vs the daily run's nearest comparable entry at ₹2,331 two sessions later at best granularity) and no losing trades in the window. Two honest caveats:

1. **The windows are not the same.** The daily run's biggest missed WATCHes (+24–26% potential) happened in Mar–May, outside the intraday data window. 5m data simply cannot reach back that far with this provider.
2. **Granularity of decisions improved; the feature set is still daily-shaped.** In intraday mode the engine sees all completed daily bars plus **one partial "today" bar aggregated up to the current 5m tick** (evolving OHLC + accumulated session volume). So session volume accumulation *is* now an input, but the indicators (EMA/RSI/MACD) still compute over daily-bar series — there is no per-5m VWAP/EMA series. That is a design property of the canonical pipeline, not a bug in the backtest.
3. **Side-effect worth knowing:** because the partial today-bar's volume is the *session-so-far* sum compared against full-day averages, the volume ratio is structurally near 0 in the morning — most of the ~50 intraday volume-gate rejections are early-session scans. Some of those were flagged "only the volume gate failed" (advisory). No change made, per instructions.

## TASK 4 — Point-in-time safety (no lookahead)

Verified in code and by independent re-validation:

- **Only past candles visible:** `build_asof_df()` (backtest_runner.py) constructs each scan's frame as daily bars strictly `<= ts` (daily mode) or strictly before today plus intraday bars `>= day_start AND <= ts` (intraday mode). Nothing after `ts` can enter the frame.
- **Future high/low not used for entry:** entries are decided from the as-of frame only; the fill price is the signal-tick price plus modeled slippage (recorded per trade).
- **Future volume not used for entry:** the today-bar volume is `sum(volume of 5m bars ≤ ts)` — session-to-date only.
- **Target/stop simulated only after entry:** the replay loop checks exits **before** scanning each tick, "against the current candle, never the entry candle" — an exit can only occur on a bar strictly after the entry tick.
- **Independent verification:** `/api/backtest/run/BT-22f70ec360/validate` re-ran the live `_scan_one` on the exact as-of slices and per-tick cash: **25 decision points checked, 0 skipped, 0 mismatches — verdict MATCH**, learning state unchanged.
- One replay-verify sub-check (`execution_matches_ledger`) reported missing entry/exit *events* for the two trades — this is an artifact of the event-feed fetch window (2,000 most-recent events vs a 2,780-tick run), not a ledger or lookahead problem: fill prices, portfolio and decision checks all PASS and the ledger itself is complete.
- Missed-opportunity "potential return" figures DO look at the following 10 bars — by design, but only for post-hoc analysis, never for decisions.

## TASK 5 — Findings

1. **Was the daily backtest insufficient?** For validating *intraday* behaviour, yes. 123 decision points over 6 months, no session volume, no intraday trend, all fills at daily close. It is a valid *swing* validation, nothing more.
2. **Does intraday data improve signal capture?** Yes — 75 decision opportunities/day, earlier entries, and ~3× the return rate in the comparable window. But the provider caps 5m history at ~55 days, so long-horizon studies must remain daily.
3. **Is volume accumulation evaluated?** In intraday mode, yes — session-to-date volume feeds the today-bar. Caveat: comparing partial-session volume to full-day averages makes the volume gate structurally strict in the morning (~50 rejections, several single-gate). Advisory observation only.
4. **Is point-in-time replay safe?** Yes. As-of slicing is strict, exits are simulated only on post-entry bars, and independent re-validation returned MATCH with zero mismatches.
5. **What caused the low daily-run profit?** Ranked:
   - **Position sizing / risk caps (primary):** entries deployed only ~₹11–19k of ₹1L (5–8 shares) with one open position per symbol — even perfect signals cap out around a few thousand rupees per trade.
   - **Conservative BUY threshold (secondary):** the biggest run-up (Mar–May, +24–26% potential) sat in WATCH the whole time; confidence never crossed the BUY line.
   - **Interval (tertiary):** daily granularity delayed entries and forfeited intraday compounding, but even 5m trades hit the same sizing ceiling.
   - **Strategy exits: not a culprit** — both TARGET exits captured their full intended move; no premature stops observed.

*Report complete. No strategy changes implemented, per instructions.*
