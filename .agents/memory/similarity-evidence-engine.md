---
name: Similarity evidence engine conventions
description: Design rules for the v2.1 evidence-based research engine (similarity matching vs historical trades)
---

- Match universe vs stats sample are distinct: `match_count` and reliability tiering use the FULL eligible match set (top-50 with similarity ≥65%), while performance stats (win rate, expectancy, PF, drawdown) are computed only over the top-20 primary sample.
  **Why:** Tiering from the truncated stats sample capped effective counts at 20, making the HIGH tier (50+ matches) unreachable — caught in architect review.
  **How to apply:** Any new consumer of similarity evidence must not conflate `stats["matches"]` (≤20) with `match_count` (≤50).
- Confidence adjustment order in decision_service: base → pattern → learning → model_adj → sim_adj, then clamp 5-95. Low/very-low reliability can never increase confidence; negative adjustments don't require high reliability.
- No lookahead: only historical trades with `exit_date < as_of` are eligible; duplicates are deduped before scoring.

## v2.2 Root Cause Intelligence
- Root cause NARRATES the existing bounded sim_adj — it must never emit a second adjustment (a test asserts no "adjustment" key in its output). Gates: ≥5 winners AND ≥5 losers among matches; loser-shared factors need ≥60% loser prevalence and lift ≤ -10; lift is shrunk by min(nW,nL)/(min+20).
  **Why:** double-counting evidence would silently compound confidence changes.
- Dynamic weights: baseline snapshot stores STATIC weights and must report `weights_dynamic: false` until a genuine ≥50-new-trade rebalance ran (check `weights_updated=1` snapshots, not mere table presence) — caught in architect review.
- Feature `direction` must compare best (winner-side) lift vs |worst (loser-side) lift|; deriving it from best-lift sign alone makes HARMFUL unreachable since best lift is max-positive by construction — caught in architect review.
- Weight updates are gradual by design: 0.8*prev + 0.2*target blend, ±15% relative per-feature cap, renormalized to total 100.
- root_cause_fn is dependency-injected into evidence annotation to avoid a circular import (root_cause_engine imports similarity_engine).
- Old feature-importance snapshots may lack newer fields; the report layer backfills defaults (setdefault) for backwards compatibility.
