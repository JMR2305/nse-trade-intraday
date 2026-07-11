---
name: Similarity evidence engine conventions
description: Design rules for the v2.1 evidence-based research engine (similarity matching vs historical trades)
---

- Match universe vs stats sample are distinct: `match_count` and reliability tiering use the FULL eligible match set (top-50 with similarity ≥65%), while performance stats (win rate, expectancy, PF, drawdown) are computed only over the top-20 primary sample.
  **Why:** Tiering from the truncated stats sample capped effective counts at 20, making the HIGH tier (50+ matches) unreachable — caught in architect review.
  **How to apply:** Any new consumer of similarity evidence must not conflate `stats["matches"]` (≤20) with `match_count` (≤50).
- Confidence adjustment order in decision_service: base → pattern → learning → model_adj → sim_adj, then clamp 5-95. Low/very-low reliability can never increase confidence; negative adjustments don't require high reliability.
- No lookahead: only historical trades with `exit_date < as_of` are eligible; duplicates are deduped before scoring.
