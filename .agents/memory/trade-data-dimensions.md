---
name: OOS trade data dimensions
description: Which analysis dimensions exist in stored out-of-sample trade records and which must be reported NOT AVAILABLE.
---
Available per-trade fields: strategy_name, market_regime, sector, symbol, calibrated_confidence/probability, holding_days, exit_reason, gap_pct, mae/mfe_pct, gross/net_pnl, total_costs, return_pct, invested, window, entry/exit_date, max_data_timestamp.

NOT recorded (must be surfaced as NOT AVAILABLE, never fabricated): ADX, ATR percentile, RSI, MACD state, EMA alignment, trend direction, volume ratio, volatility regime, entry subtype.

**Why:** The research platform's credibility rests on honest N/A reporting; spec requests indicator-level analysis the data cannot support.

**How to apply:** Any new analytics module should list unavailable dimensions explicitly (see meta_learning.UNAVAILABLE_DIMENSIONS) and use max_data_timestamp <= entry_date as the no-lookahead audit.
