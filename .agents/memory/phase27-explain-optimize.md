---
name: Phase 27C/27D explainability & strategy optimization
description: Read-only aggregators over canonical stores; the store-shape pitfalls that broke the first pass.
---

- 27C = "Why (27C)" tab on ExplainableAI (`/api/explain/symbol/:symbol`, `phase27_explainability.py`); 27D = "Historical Optimization" section on StrategyOptimisation (`/api/strategy-optimization/report`, `phase27_strategy_optimization.py`, 30s Node cache + single-flight).

**Store-shape rules (verified live; guessing these failed architect review):**
- Scan-rec gates (`gate_price/rr/volume/data_quality`) are dicts `{passed, reason}`, NOT booleans.
- Canonical portfolio getter is `build_canonical_portfolio()`; positions key `positions`, price field `avg_price`.
- `phase24_store.list_missed_opps()` wraps analysis in `record` (`rejected_by_gates`, `rejection_correct`, `should_have_allowed`).
- Symbols with `error` set trip ALL gates at once — exclude them from per-filter counts or every gate looks like a duplicate rejection set.
- The ops journey can say "Not in universe" for a symbol present in the canonical scan; the scan is authoritative — hide the stale timeline with an explicit note, never display the conflict.

**Why:** honesty rules — INSUFFICIENT_EVIDENCE over extrapolation; factors the pipeline doesn't compute (MACD/VWAP/ATR/news/corp actions) are `evaluated: false`, never fabricated.
**How to apply:** any future consumer of scan gates, phase24 missed-opps, or the ops journey must use these shapes; curl/inspect real store rows before typing interfaces.
