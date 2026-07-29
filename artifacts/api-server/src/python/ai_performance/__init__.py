"""
ai_performance — Phase 5D.4: AI Performance Intelligence.

READ-ONLY analytics module evaluating how well the AI performs over time
using historical paper-trading data.

Architecture: This module is a consumer of Phase 5D.3 strategy_intelligence.
shared_services. It NEVER recalculates metrics already computed by:
  • Phase 5C  — Signal Validation
  • Phase 5D.1 — Execution Quality
  • Phase 5D.2 — Portfolio Performance
  • Phase 5D.3 — Strategy Intelligence

New analytics added here:
  • Confidence analysis (bucketed, cross-correlated with outcome)
  • Calibration analysis (ECE, reliability, overconfidence / underconfidence)
  • Prediction analysis (precision, recall, F1, MCC, balanced accuracy)
  • Recommendation analysis (accepted / rejected success rates)
  • Learning analysis (daily/weekly/monthly accuracy trends)
  • AI Health Score (0–100 composite)

Controlled by AI_PERFORMANCE_ENABLED=true.

Phase 5D.5 (Executive Dashboard) reuses this module via ai_performance.shared_services.
"""
