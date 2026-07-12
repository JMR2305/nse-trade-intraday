---
name: Strategy intelligence (Phase 2 adaptive selection)
description: Design decisions and gotchas for the adaptive strategy selection / dynamic allocation layer
---

# Adaptive strategy selection (Phase 2)

- **Rule**: strategy enable/disable is decided by two independent gates — a regime-agnostic rolling profit factor (last 25 trades, disable < 0.90) checked FIRST, then a per-regime profit factor (disable < 0.75, needs ≥10 trades in that regime). A diversification floor always keeps ≥2 strategies enabled, and per-strategy allocation is capped at 40% (relaxing to 1/n when fewer than 3 enabled so weights still sum to 1).
- **Why:** a recent losing streak should stop a strategy everywhere, not just in one regime; the floor prevents an empty book; the cap prevents one hot strategy dominating ₹5,000.
- **How to apply:** any test or synthetic scenario for regime-specific disabling must interleave regime losses among other-regime wins by exit date, or the rolling gate fires first and masks the regime gate.
- Synthetic price series with constant daily returns have ~zero close-to-close volatility and classify as "Low Volatility" — the classifier checks volatility before trend. Add ±0.7%-ish alternating noise when constructing trend fixtures.
- Learning is strictly from completed out-of-sample trades: walk-forward builds per-window intelligence as of each test window start and feeds closed trades back during simulation; the live pipeline uses a short-cached singleton. Never feed open positions.
- Any position-size multiplier (confidence tilt, strategy tilt, etc.) must be re-clamped against per-stock and per-sector caps AFTER it is applied — a >1 factor applied post-clamp silently breaks portfolio limits. Caught by architect review in Phase 2.
