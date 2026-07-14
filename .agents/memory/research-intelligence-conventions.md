---
name: Research intelligence conventions
description: Rules for the Phase 5 cross-experiment intelligence engine
---
Rules for the AI Research Intelligence engine (cross-experiment insights, trade diagnostics, compare, health scores):

- Honest N/A: stored trades (wf_trades.csv) carry no indicator values (MACD/RSI/EMA/ATR). Diagnostics must state "Not available — not stored", never fabricate. Counterfactuals only from other variants matching symbol+entry_date+window.
- Advisory only: every payload carries research_only/auto_applied:false flags; UI shows disclaimers; nothing feeds live/paper trading.
- Coerce numerics with `pd.to_numeric(errors="coerce")`, not `astype(float)` — historical CSVs can contain dirty values and astype raises, turning the whole endpoint into a 500.
- Route ordering: `/experiments/compare` must be registered before `/experiments/:id`.

**Why:** Core project guarantee is research integrity (no fabricated data, no trading impact); architect review flagged astype fragility.
**How to apply:** Any extension of research_intelligence.py or its routes/UI must keep these invariants.
