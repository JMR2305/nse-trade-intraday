---
name: Confidence calibration (Phase 1)
description: How prediction confidence is calibrated to real win probabilities and where the calibrated values gate/size trades.
---

# Confidence calibration design

- The raw model confidence is heavily overconfident vs reality: knowledge-base win rate ~38%; raw 90% confidence maps to roughly a 0.6-0.75 true win probability after isotonic fitting. Never treat raw confidence as a probability.
- Every prediction carries 5 fields: `raw_confidence`, `calibrated_probability` (0-1), `calibrated_confidence` (0-100), `calibration_method`, `calibration_version`. Downstream consumers must prefer calibrated values when present and fall back to raw ones when absent (identity fallback keeps the system working with no calibrator).
- **Why per-window calibrators in walk-forward:** fitting one global calibrator would leak future outcomes into past test windows. Each window fits only from knowledge trades that exited before its `test_start` — same no-lookahead rule as the pattern/similarity layers. Calibration applies to variant C only, so A/B stay as honest baselines.
- Auto method selection: isotonic ≥100 samples, Platt ≥30, else identity. Pure-python implementations (no sklearn in the environment).
- Calibrated execution floor is 0.30 win probability (`MIN_CALIBRATED_PROB` / `cfg.min_calibrated_prob`); the raw-confidence floor still applies on top of it. Portfolio "exceptional" slot uses calibrated prob ≥0.60 instead of raw conf ≥90.
- **How to apply:** any new component that filters or sizes on confidence must use the calibrated fields (via `_effective_confidence`-style preference), and any offline evaluation must fit its calibrator with an `as_of` cutoff.
- Watch-out: since calibrated confidences are much lower than raw ones, quality-score thresholds tuned for raw confidence (e.g. MIN_QUALITY_SCORE=55) can over-filter; verify trade counts after any threshold change.
