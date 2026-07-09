---
name: Signal filter calibration
description: Realistic score ranges for the NSE scanner and how strict trade gates should treat action labels.
---
The rule: strict trade eligibility must gate on `filter_passed` (all quality gates), not on the BUY/WATCH action label. Labels are just opportunity-score bins (BUY ~>=60), while genuinely strong real-world setups score opp ~50-60, conf ~50-55.

**Why:** With label-based gating plus 60+ floors, the improved model returned zero trades on every date, including bullish days — the user complained. Diagnostics (July 2026) showed the best setups (e.g. SBIN opp 56.5/conf 54.5/RR 3.0, all gates passing) were labeled WATCH and excluded.

**How to apply:** Keep strict defaults at 50/50/2.0 and volume gate at >= 0.75x 20-day average. If tightening thresholds, first histogram `filter_reasons` across a full-universe replay day to see what real setups score. Zero trades on weak/bearish days is correct behavior, not a bug.
