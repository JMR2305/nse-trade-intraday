# NSE Trading System — ChatGPT Research Briefing

*Upload this single file to ChatGPT for a full system briefing.*

---

## System Context

```
System:    NSE Algorithmic Paper Trading (research only)
Capital:   ₹5,000
Universe:  NIFTY 50 (50 stocks)
Style:     Long-only, daily candles
No real money — paper trading simulation only
```

**Report date:** 2026-07-13 21:13:41  
**Git commit:** `451fe2df83f5` — Add a new phase to expand out-of-sample evidence for analysis  
**Model version:** 0

---

## What This System Does

- Scans all 50 NIFTY stocks daily using a rule-based + ML-enhanced decision engine
- Generates BUY/WATCH/AVOID recommendations with confidence scores
- Runs walk-forward validation: rolling train→test windows on historical data
  (training never sees test data; no lookahead)
- 5 model variants compared: base technical (A), pattern+similarity (B),
  full model (C), gated (D), strict-gate (E)
- Calibration re-fits per window using only prior completed trades
- Phase 3A.5 assesses evidence quality (target: 300+ OOS trades, 8+ windows)

## Walk-Forward Validation Results

**Overall Verdict:** INSUFFICIENT DATA
**Evidence Quality (3A.5):** None

> Only 29 completed out-of-sample trades across 2 test window(s) — at least 100 trades and 2 windows are required for a reliable verdict.

### Full Model Performance (Variant C)

```
OOS Trades:       29
Windows:          2
Total Return:     -3.42%
Net P&L:          ₹-1,712
Win Rate:         34.50%
Profit Factor:    0.70
Expectancy:       ₹-59/trade
Sharpe Ratio:     -1.04
Max Drawdown:     6.01%
```

### Benchmarks

- Full model compounded: -3.42%
- NIFTY 50 buy & hold:  -5.22%

### Confidence Calibration

```
Brier Score:  —  (lower = better, perfect = 0)
ECE:          —  (lower = better, perfect = 0)
Log Loss:     —  (lower = better)
```

### Phase 3A.5 Evidence Expansion

```
Verdict:              None
OOS Trades:           — / 300 target
Windows:              — / 8 target
Expectancy/trade:     —
Profitable windows:   —%
Median return:        —
Return dispersion:    —
```

### Walk-Forward Windows

| Window | Test Period | Trades | Return | PF |
|--------|-------------|--------|--------|----|
| W1 | 2026-01-12–2026-04-11 | 19 | -0.38% | 0.95 |
| W2 | 2026-04-12–2026-07-11 | 10 | -3.05% | 0.28 |

## Before vs After (vs Previous Package)

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Full Model Return % | -3.42 | -3.42 | = 0.00 |
| Win Rate % | 34.50 | 34.50 | = 0.00 |
| Expectancy (₹) | -59.04 | -59.04 | = 0.00 |
| Sharpe Ratio | -1.04 | -1.04 | = 0.00 |
| Max Drawdown % | 6.01 | 6.01 | = 0.00 |
| Net P&L (₹) | -1712.10 | -1712.10 | = 0.00 |
| Profit Factor | 0.70 | 0.70 | = 0.00 |

## Configuration Snapshot

```json
{
  "train_years": 1,
  "test_months": 3,
  "step_months": 3,
  "start_date": "",
  "end_date": "",
  "initial_capital": 50000.0,
  "universe": [],
  "universe_size": 0,
  "strategy_set": [],
  "cost_model": {
    "slippage_pct": 0.1,
    "spread_pct": 0.05,
    "brokerage_pct": 0.0,
    "brokerage_flat": 0.0,
    "brokerage_max": 20.0,
    "stt_pct": 0.1,
    "exchange_pct": 0.00297,
    "sebi_pct": 0.0001,
    "stamp_pct": 0.015,
    "gst_pct": 18.0,
    "volume_participation_pct": 5.0,
    "allow_partial_fills": true,
    "max_entry_gap_pct": 3.0,
    "entry_timing": "next_day_open"
  },
  "intrabar_rule": "conservative",
  "max_holding_days": 20,
  "min_confidence_execute": 55.0,
  "min_calibrated_prob": 0.3,
  "verdict_criteria": {
    "min_profit_factor": 1.15,
    "max_drawdown_pct": 20,
    "min_trades": 100
  },
  "random_seed": 42
}
```

## Known Limitations

- Only 50 NIFTY stocks tested — no mid/small-cap coverage.
- Daily candles only — intraday gaps and liquidity are approximated.
- Backfill survivorship bias possible if a stock left NIFTY 50 during test period.
- Short positions are not supported (long-only system).
- Capital limit ₹5,000 constrains position sizing and diversification.
- Confidence calibration re-fits per window but requires ≥10 prior completed trades.
- SEBI/GST/STT rates are hardcoded — changes in tax law are not auto-updated.
- Slippage and spread are estimated; actual market-impact costs may differ.
- Adaptive model weights are version-pinned for the whole run — no intra-run updates.
- Phase 3A.5 evidence targets 300+ OOS trades for PASS; small-window runs are INCONCLUSIVE.

## Live Behaviour Change?

**No.** This package contains analysis-only results. No live paper-trading
recommendations, strategy rankings, portfolio positions, or thresholds were
changed by generating this report. All Phase 3A/3A.5 sections are shadow
models — they observe but never influence execution.

## Suggested Questions for ChatGPT

1. Looking at the walk-forward results above, what is your assessment
   of this strategy's edge? Is the evidence statistically meaningful?
2. The evidence expansion shows ____ OOS trades across ____ windows.
   What are the risks of making conclusions from this evidence set?
3. Which market regime is most profitable/risky based on the breakdown above?
4. The profit factor is ____. Is that robust enough for a long-only system
   with a ₹5,000 capital limit?
5. Based on the concentration warnings above, how should I diversify?
6. The calibration ECE is ____. Is that good? What does it mean practically?
7. What would be a reasonable next step to improve evidence quality?

---

*Out-of-sample historical performance does not guarantee future results. Paper trading and research only. No real orders are placed.*