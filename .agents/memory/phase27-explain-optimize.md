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

- phase24 `rejected_by_gates` holds phase20 ENTRY gate names (`min_risk_reward`, `no_fallback_data`, `min_confidence`…), NOT scan-gate keys — map via explicit `GATE_ALIASES` only where defensible and surface the rest in `entry_gate_outcomes`; substring matching silently matches nothing.
- Daily-report generation errors are keyed per IST day; record failures under the day whose report was attempted (computed up front), and the status endpoint ignores error entries whose `at` timestamp is from an earlier IST day (stale → PENDING + stale_error note; unparseable ts → fail-safe ERROR).

**Why:** honesty rules — INSUFFICIENT_EVIDENCE over extrapolation; factors the pipeline doesn't compute (MACD/VWAP/ATR/news/corp actions) are `evaluated: false`, never fabricated.
**How to apply:** any future consumer of scan gates, phase24 missed-opps, or the ops journey must use these shapes; curl/inspect real store rows before typing interfaces.

Phase 27E operator analytics additions:
- Rejection accounting must separate rejected EVENTS from reason-code OCCURRENCES (one RISK_REJECTED can fail several gates); % labelled as share of occurrences, never of events.
- Every canonical reader returns a source state (`available/error/truncated`); bounded fetches hitting the limit are PARTIAL evidence; distinguish SOURCE_UNAVAILABLE vs VERIFIED_EMPTY — a swallowed exception rendered as "no data" is a lie.
- `get_replay_sessions()` fabricates a synthetic `demo` session when no DB scan exists — filter `source == "demo"` before treating sessions as evidence.
- JSX gotcha: `PRECHECK_*/` inside a block comment terminates the comment (`*/`).
