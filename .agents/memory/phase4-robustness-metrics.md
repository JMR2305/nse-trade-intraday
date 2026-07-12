---
name: Phase 4 Robustness Metrics
description: How _metrics() in macd_robustness.py computes expectancy and drawdown, and why.
---

## Rule
`_metrics()` in `macd_robustness.py` computes:
- `expectancy_pct` = `avg(return_pct)` across all trades (same as Phase 3's `avg_return_per_trade_pct`)
- `max_drawdown_pct` uses a sequential equity curve starting at `capital`, with equity **clamped to 0** at ruin, so drawdown is always ≤ 100%

## Why
Early versions used `avg(net_pnl) / capital * 100` for expectancy, which gave 4.658% vs Phase 3's 0.242% for the same 179 trades — confusing and inconsistent.
Drawdown without ruin-clamping produced values like 363% and 1134% (equity went negative since the sequential audit doesn't cap total deployment to ₹5000).

## How to Apply
- When adding new stress tests or breakdown metrics, use `_metrics(trades, capital)` directly — don't reimplement.
- The `top5_share_of_profit_pct` in `_stress_top5_removed` uses **gross profit** (sum of winning trade net_pnl) as denominator, NOT net total PnL, to keep the value ≤ 100% and consistent with `_concentration_summary`.
- Verdict threshold `V_MAX_DRAWDOWN_PCT = 40.0` is calibrated for the ruin-clamped sequential metric. The real-world portfolio drawdown from Phase 3 (~72–133%) also exceeds this, so RESTRICT verdict for drawdown is correct.
