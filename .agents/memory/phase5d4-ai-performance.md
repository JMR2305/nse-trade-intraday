---
name: Phase 5D.4 AI Performance Intelligence
description: Consumer of 5D.3 strategy_intelligence; adds confidence/calibration/prediction/learning analytics; stable shared_services for 5D.5 reuse.
---

## Key design decisions

**ai_performance.shared_services is the canonical import point for 5D.5.**
`get_ai_snapshot()` is the purpose-built single-call dict for the executive dashboard tile.

**Why:** Prevents 5D.5 from fan-out across 6 endpoints.

## Classification threshold
`CONFIDENCE_THRESHOLD = 0.60` — signals with `signal_confidence >= 0.60` are "positive" predictions (AI predicts win). TP/FP/TN/FN all computable from executed trades only (no counterfactual needed).

## main.py commands
ai_summary, ai_confidence, ai_calibration, ai_predictions, ai_recommendations, ai_learning — added before the phase 5D.3 block.

## Known limitation
`ignored_signals` always 0 — unexecuted signals aren't stored in paper_trades. Requires a separate `signals_log` table to fix.

## Brain icon already imported in AppLayout
`Brain` is imported on line ~30 of AppLayout.tsx. Do NOT add it again — duplicate identifier TS error.

## Tests
32/32 at 0.65s. TN/FN require lower-confidence but still-executed trades as the negative class sample.
