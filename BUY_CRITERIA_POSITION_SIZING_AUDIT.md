# BUY Criteria + Position Sizing Audit — GLAND

**Date:** 11 Aug 2026 · **Scope:** PAPER / RESEARCH ONLY · **No strategy, threshold, or gate changes were made.** Recommendations only (Task 5).

Data sources: intraday run `BT-22f70ec360` (₹1L) and `BT-9fcaea6b12`* (₹50k), 2,780 5m ticks, 23,209 pipeline events, ledger trades, and the live gate code paths (the backtest replays the real `_scan_one`).
*₹50k trades were persisted under ledger run `BT-c86fa8a381` (its paired launch); identical signals, smaller size.

---

## TASK 1 — Current BUY criteria map

GLAND values are from the canonical event store at a representative BUY tick (`…T00243`) and the executed entries.

| # | Rule | Stage | Current threshold | GLAND actual | Pass? | Effect on decision |
|---|---|---|---|---|---|---|
| 1 | Price validity | Scan (`live_scan_engine`) | price > 0 and ≥ ₹1 | ₹2,230–2,640 | ✅ | Hard block → IGNORE |
| 2 | Minimum history | Scan | ≥ 30 indicator bars | 187 bars | ✅ | Hard block → IGNORE |
| 3 | Data quality | Scan | STALE caps BUY→WATCH; UNAVAILABLE→IGNORE | LIVE | ✅ | Downgrade cap |
| 4 | Scan freshness (`scan_fresh`) | Live pipeline only | current-session scan required | n/a in backtest (as-of data is "current" by construction) | ✅ | Hard block (live) |
| 5 | Market open | Phase20 entry (live) | state = OPEN | n/a in backtest (replay ticks are session candles) | ✅ | Hard block (live) |
| 6 | Trend / momentum | Strategy `check_entry` (MACD Cross et al.) | strategy-specific live signal | live MACD cross signal, above EMA20 & EMA50, ADX 31.2 | ✅ | No signal → no BUY-class action |
| 7 | Strategy score | Scan (`market_scanner`) | formula: WR×0.35 + PF×0.30 + P&L×0.20 + Sharpe×0.15, × reliability `0.35+0.65·min(1,trades/4)` | technical score 76.7 (WR 100%, PF capped, but `low_evidence: 3 trades`) | ✅ | Feeds confidence/opportunity |
| 8 | Market regime | Strategy selection | strategy must be regime-eligible (`strategy_regime_eligible`) | Trending (momentum) — eligible | ✅ | Hard block via `all_gates_passed` |
| 9 | Confidence | Scan → Phase20 gate | scanner: informational; **Phase20 entry: ≥ 60** | 72.5–73.1 at entries | ✅ | Hard block (Phase20) |
| 10 | Opportunity score → action | Scan classification | **STRONG BUY ≥ 90, BUY ≥ 75, WATCH ≥ 60** (config.py); Phase20 entry min ≥ 60 | 69.6 at entries → *below the BUY-75 line; entries happened because opportunity is classified per-strategy at scan time and the acting ticks scored ≥ BUY line; median WATCH opp = 69.6* | mixed | **This is the WATCH/BUY boundary** |
| 11 | Trade quality (technical score) | Phase20 gate | ≥ 50 | 76.7 | ✅ | Hard block (Phase20) |
| 12 | Risk/Reward | Scan gate + Phase20 gate | scan: **RR ≥ 1.5** (fail ⇒ BUY→WATCH); Phase20: **RR ≥ 2.0** | 2.5 | ✅ | Downgrade (scan) / hard block (Phase20) |
| 13 | **Volume ratio** | Scan gate | **≥ 0.30** for BUY-class (fail ⇒ BUY→WATCH) | 0.73 at entry ticks; **0.00–0.28 on 1,184 morning/quiet ticks** | mixed | **Downgrade BUY→WATCH — the dominant intraday rejector** |
| 14 | Liquidity (avg volume) | Phase20 gate | `min_liquidity_filter = 0.0` → **disabled** | n/a | — | Off |
| 15 | Volatility cap | Phase20 gate | `max_volatility_filter = 0.0` → **disabled** | n/a | — | Off |
| 16 | Stop validity | Phase20 gate / backtest entry | 0 < stop < entry | valid (₹2,076 / ₹2,487) | ✅ | Hard block |
| 17 | Risk-per-trade sizing | Entry (`_try_enter`) | **1% of cash** / stop distance | see Task 2 | ✅ | Caps quantity (not a block) |
| 18 | Per-stock cap | Entry | **25% of cash** (backtest const; Phase20 setting also 25%) | never binding (1% risk binds first) | ✅ | Caps quantity |
| 19 | Cash sufficiency | Entry | cost ≤ cash | ✅ | ✅ | Hard block |
| 20 | **One open position per symbol** | Ledger (`open_trade`) | 1 | **blocked 1,590 approved BUYs** | ❌ mostly | **Hard block — the single biggest P&L limiter** |
| 21 | Max open positions | Phase20 (live paper) | 5 concurrent | n/a in backtest (not enforced there) | — | Hard block (live) |
| 22 | Daily max trades | Phase20 (live paper) | 3/day | n/a in backtest | — | Hard block (live) |
| 23 | Cooldown | Phase20 (live paper) | 30 min per symbol | n/a in backtest | — | Hard block (live) |
| 24 | Portfolio deployed cap | Phase20 (live paper) | 80% | n/a in backtest | — | Hard block (live) |
| 25 | Daily loss limit | Phase20 (live paper) | 3% | n/a | — | Hard block (live) |
| 26 | Provider / circuit breaker / research mode | Phase20 global | Zerodha or LIVE quality; breaker clear; `research_failure_mode=fail_open` | n/a in backtest | — | Hard block (live) |

Event-flow reality check for the ₹1L run: 2,780 scans → 1,592 BUY-class approvals → **2 executed**, 1,590 cancelled ("Open backtest position already exists"); 1,184 BUY-class downgraded to WATCH by the volume gate alone; 1,188 WATCH decisions total.

## TASK 2 — Position sizing audit (all executed GLAND trades)

Formula in `_try_enter`: `qty = floor( (cash × 1%) / (entry − stop) )`, capped by `floor(cash × 25% / entry)`; fill = NEXT_QUOTE + 0.15% slippage; charges 0.12%.

| | ₹1L trade 1 | ₹1L trade 2 | ₹50k trade 1 | ₹50k trade 2 |
|---|---|---|---|---|
| Signal ts (UTC) | 18 Jun 04:20 | 10 Aug 04:40 | 18 Jun 04:20 | 10 Aug 04:40 |
| Capital / available cash | 100,000.00 | 102,109.71 | 50,000.00 | 50,843.88 |
| Risk-per-trade (1% of cash) | ₹1,000.00 | ₹1,021.10 | ₹500.00 | ₹508.44 |
| Entry / stop | 2,246.80 / 2,076.27 | 2,638.00 / 2,487.43 | 2,246.80 / 2,076.27 | 2,638.00 / 2,487.43 |
| Stop distance | ₹170.53 (7.6%) | ₹150.57 (5.7%) | ₹170.53 | ₹150.57 |
| Target | 2,673.13 | 3,089.71 | 2,673.13 | 3,089.71 |
| Qty before rounding | 5.86 | 6.78 | 2.93 | 3.38 |
| 25% cap qty (never binding) | 11.13 | 9.68 | 5.56 | 4.82 |
| **Final qty** | **5** | **6** | **2** | **3** |
| Fill price (incl. slippage) | 2,248.49 | 2,639.98 | 2,248.49 | 2,639.98 |
| Charges / slippage per share | ₹13.49 / ₹1.69 | ₹19.01 / ₹1.98 | ₹5.40 / ₹1.69 | ₹9.50 / ₹1.98 |
| Capital deployed | ₹11,242 (11.2%) | ₹15,840 (15.5%) | ₹4,497 (9.0%) | ₹7,920 (15.6%) |
| Unused capital | ₹88,758 | ₹86,270 | ₹45,503 | ₹42,924 |
| Result | TARGET +₹2,123.20 | EOB +₹1,971.72 | TARGET +₹849.28 | EOB +₹985.86 |

**Why quantities are small — two compounding causes:**
1. **1% risk with wide stops.** Stops sit 5.7–7.6% below entry, so the 1% risk budget buys only 5–6 shares of a ₹2,200+ stock. The 25% per-stock cap never engaged — sizing is entirely risk-budget-bound.
2. **One open position per symbol, single-symbol run.** Once the 18 Jun position opened, **all 1,590 subsequent approved BUY signals were cancelled** until the target hit on 10 Aug. In a one-symbol backtest, this means ~85–90% of capital sat idle for the entire 8 weeks. Capital was never fully used because *no rule exists to scale in, pyramid, or redeploy* while a position is open.

## TASK 3 — WATCH-to-BUY audit

1,188 GLAND WATCH decisions. Confidence: min 48.5 / median 72.5 / max 96.7. Opportunity: min 50.3 / median 69.6 / max 89.6 (BUY line = 75). 328 WATCHes had opportunity ≥ 70; 140 ≥ 72.

Forward performance (next 10 × 5m bars, point-in-time safe, analysis-only): 593 of 1,188 (49.9%) were profitable; **median 10-bar return ≈ 0.0%**. Top near-misses:

| Scan | Confidence | Opportunity | Peak +10 bars | Return @ +10 bars | Blocked by one rule? | Near-miss? |
|---|---|---|---|---|---|---|
| T02178–T02182 (4 Aug) | 96.7 | 89.6 | +0.3…+0.7% | **−1.0…−2.7%** | Yes — volume only | **No** — gate was right |
| T02413 | 73.0 | 73.2 | +1.0% | +0.9% | opportunity < 75 | Marginal |
| T02625–T02627 | 73.0 | 73.2 | +0.3…+0.7% | −0.4…+0.2% | opportunity < 75 | No |

**Honest finding:** on the 5m timeframe, WATCH decisions were coin-flips over the next 10 bars (49.9% profitable, ~0 median). The spectacular "missed" WATCHes from the *daily* audit (+24–26%) were multi-week holds in Mar–May — a horizon question, not a threshold question. Even the highest-conviction WATCHes (96.7 confidence!) went *down* after the signal. **There is no evidence here that lowering the WATCH→BUY line would have added profit** — and every one of those 1,590 approved BUYs was cancelled by the one-position rule anyway, so a looser threshold would have changed nothing in this run.

## TASK 4 — Volume gate audit

- **1,184 of 1,184 RISK_REJECTED events failed *only* the volume gate** (zero multi-gate failures). Every one was a BUY-class signal downgraded to WATCH.
- **How many later became profitable:** 593 of 1,184 (50.1%) positive at +10 bars, median +0.01% — i.e. collectively a coin-flip, *not* a pile of missed winners at intraday horizon.
- **Time-of-day skew confirms the structural bias:** rejects by IST hour — 09:00 → 323, 10:00 → 307 (53% in the first two hours), 11:00 → 216, 12:00 → 152, 13:00 → 111, 14:00 → 59, 15:00 → 16. Session-to-date volume vs full-day average makes the ratio ~0 at the open by construction, exactly as suspected.
- **Should volume be time-of-day normalized? Yes** — compare session-to-date volume against the *average session-to-date volume at the same time of day* (or an intraday volume curve). The current form makes the gate mean "late in the day" rather than "liquid". But note: normalizing it would mostly convert morning WATCHes into BUYs that the one-position rule cancels anyway; fix ordering matters (see below).

## TASK 5 — Recommendations (NOT implemented)

1. **Current BUY criteria:** mapped in Task 1 — 26 rules across scan, Phase20 entry, and ledger stages.
2. **Too restrictive:**
   - **One-open-position-per-symbol with no scale-in** — cancelled 1,590 approved BUYs and left ~88% of capital idle for 8 weeks. *The* dominant P&L limiter.
   - **1% risk with strategy stops 6–8% wide** — deploys only 9–16% of capital per trade; the 25% cap is dead code in practice.
   - **Volume ratio <0.30 on partial-session volume** — structurally biased against the first two hours (630 of 1,184 rejects before 11:00 IST).
3. **Working correctly:** RR gate (2.5 vs 1.5/2.0), price validity, data-quality caps, regime eligibility, stop validity, point-in-time freshness — and, on the evidence, the volume gate's *outcomes* were neutral-to-protective at 10-bar horizon (the 96.7-confidence rejects went down).
4. **Is position sizing too conservative? Yes, demonstrably** — but via the *combination* of 1% risk × wide stops × no re-entry/scale-in, not any single number. Both runs earned ~4% while risking ≤1% per trade with ≥84% cash idle at all times.
5. **Time-normalize volume? Yes** (intraday contexts only; keep the daily/live gate unchanged). Expected effect is mostly earlier entries, not more winners, unless #6/#2 change too.
6. **Review WATCH→BUY threshold? Not on this evidence.** 5m WATCHes were 50/50 at short horizon. The threshold question only matters at swing horizon (the daily-run Mar–May WATCHes) — review it there, with daily-horizon forward returns, not intraday ones.
7. **Proposed changes (for future approval, in priority order):**
   1. Allow capital redeployment while a position is open: either scale-in tranches on fresh signals (respecting total per-stock cap) or multi-symbol universes in research runs, so one open trade doesn't idle the book.
   2. Make risk-per-trade and per-stock cap settings-driven in the backtest (they're hardcoded 1%/25% constants there, diverging from config.py's 20% and Phase20's settings) so sizing experiments don't require code edits.
   3. Time-of-day-normalized volume ratio for intraday scans (backtest + live intraday only; daily unchanged).
   4. Re-audit the BUY line at daily horizon with forward-return evidence before touching any threshold.

*Report complete. No trading logic, thresholds, or gates were changed.*
