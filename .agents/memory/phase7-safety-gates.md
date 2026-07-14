---
name: Phase 7 safety gates
description: Where data-quality caps and RR/volume gates are enforced
---
All safety gates are in live_scan_engine.py, NOT in market_scanner.py:
- _apply_quality_gate(action, quality): STALE→WATCH, UNAVAILABLE→IGNORE
- _rr_gate(rr_ratio, action): RR < 1.5 on BUY/STRONG BUY → downgrade to WATCH
- _volume_gate(volume_ratio, action): volume_ratio < 0.3 on BUY → downgrade to WATCH
- _price_gate(price, symbol): price ≤ 0 or < 1 → fail (IGNORE)

Meta-Learning NEVER affects live decisions (test_meta_learning_isolation confirms meta_learning.py has no import of live_scan_engine, paper_trader, or live_data_provider).

Paper eligibility: action ∈ {STRONG BUY, BUY} AND quality ∈ {LIVE, NEAR_LIVE} AND all_gates_passed.

**Why:** Safety must be in one place, tested explicitly. market_scanner.py is a standalone engine that should not grow safety responsibilities.
