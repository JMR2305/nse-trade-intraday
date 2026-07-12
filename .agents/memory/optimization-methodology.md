---
name: Optimization report methodology rules
description: Constraints that keep the walk-forward optimization/audit reports honest (no lookahead, no selection bias overstatement).
---

- Individual variation verdicts are valid OOS only if parameters are chosen on TRAIN windows and judged on TEST windows; entry filters may only REMOVE baseline entries, exit tests must re-walk IDENTICAL entries.
- **Combined/stacked configurations carry second-stage selection bias**: components are accepted on the same test windows the combined result is judged on. Any "combined beats baseline" claim must be labeled PROVISIONAL/exploratory (see `COMBINED_CAVEAT` in the MACD optimizer) — never presented as independent OOS validation. This was an architect-review finding; keep the pattern for future phases.
- **Why:** the user is non-technical and paper-trades on these reports; overstating OOS validity is the main harm to avoid (spec: "reject anything not improving OOS", never touch live pipeline).
- **How to apply:** any future optimizer/report that stacks accepted variations needs either a fresh holdout slice or an explicit exploratory caveat in payload + UI.
- Gotcha: `strategy_audit._walk_partial`/`build_trade_record` require `entry_date` inside the fill dict — synthetic fills must include it.
