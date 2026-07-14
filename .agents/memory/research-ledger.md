---
name: Research ledger conventions
description: Rules for the Phase 4.2 observational research ledger and strategy analyzer
---

# Research ledger (Phase 4.2)

Rule: any instrumentation added to the walk-forward candidate loop must be a
pure side channel — optional parameter, no effect on entry/exit decisions.
**Why:** the whole framework's validity rests on the ledger being observational;
a prior run's overall metrics must be byte-identical after instrumentation
(verified by rerunning the same experiment and comparing headline metrics).
**How to apply:** after touching `simulate_window_variant` or the ledger,
rerun a completed experiment and diff `status.json` metrics against the prior run.

Key conventions:
- Ledger written only for variant "C"; funnel stages: not_buy_signal →
  rejected_confidence / rejected_confidence_similarity (counterfactual:
  would have passed without the negative similarity adj) /
  rejected_calibrated_prob / rejected_strategy_gate / already_in_position →
  candidate_pool → queued / rejected_no_slot → entered / rejected_fill /
  rejected_allocation_caps / rejected_position_limit.
- The engine has NO volatility or liquidity gates — analyzer reports them as
  absent, never zero-by-measurement; volume sweep is labeled hypothetical.
- Join ledger↔trades on window+symbol+entry_date (overlapping windows can
  repeat symbol+entry_date across windows).
- "Would-have" returns are approximations: stop assumed hit if 20d MAE ≤ stop
  distance, else target if 20d MFE ≥ target distance, else raw forward return.
- No scipy in the environment — Spearman IC = Pearson on ranks.
- Experiment ids must be validated (`^[A-Za-z0-9_-]{1,64}$`) in both the TS
  route and the Python command layer before any path join (traversal risk).
