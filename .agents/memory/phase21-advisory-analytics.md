---
name: Phase 21 advisory analytics conventions
description: Durable rules for calibration/threshold/challenger work in the paper-trading research system
---

- Every analytical layer must be advisory-only: outputs carry explicit flags (auto_applied false, requires_human_approval true, auto_promotion disabled) and nothing changes raw confidence, BUY gates, or the champion model automatically.
  **Why:** User mandate — research-only system; regressions here are safety violations, not bugs.
  **How to apply:** Any new optimizer/calibrator/challenger must emit these flags and be tested for them.
- With few completed trades, report INSUFFICIENT_EVIDENCE rather than extrapolating; never fabricate counterfactuals when MAE/MFE excursion history is absent (mark them unscoreable instead).
  **Why:** User values honesty over impressive-looking numbers; earlier phases established this norm.
- Frontend panels must be built against actual Python response shapes, not assumed ones — field names diverged repeatedly (e.g. per_trade vs trades). Verify shapes with a quick python -c dump before wiring UI.
