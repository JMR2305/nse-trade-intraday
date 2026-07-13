---
name: Phase 3A balanced decision shadow model
description: Conventions for analysis-only shadow models in the walk-forward validator
---

- Shadow models (like Phase 3A model "G") must be wired as: per-window try/except hook AFTER live variant sims, separate accumulators, report built AFTER Phase 5 alpha, own top-level result key. Failures recorded in an errors list, never silent — this keeps live variants A–E provably untouched.
- **Why:** hard project rule — no live trading changes; the safety audit in the report asserts analysis-only, so the wiring must make that true by construction.
- Spec model letter "F" (current regime-gated) maps to this system's variant E; letters E/F both correspond to strategy-/regime-gated variants. A model_mapping_note in the report documents this.
- Report `config` keys are `eligibility_gates`, `smooth_ramps`, `data_quality_multiplier_range` (not hard_gates/ramps) — UI must match these exactly; a key mismatch renders as undefined silently.
- Python test style here: plain `check(label, cond)` counters run via `python tests/test_X.py` (pytest has a pre-existing INTERNALERROR). Synthetic e2e window sims need ≥120 rows (WARMUP_BARS=55, build_day_item requires day_pos ≥ 60).
