---
name: Phase 14 learning & governance
description: Safety invariants for adaptive paper-trade learning, calibration, and model governance
---

**Rule:** Any safety state (learning freeze, IGNORE-lock) must be enforced at decision time by reading the authoritative state file directly — never trust cached/derived artifacts (e.g. `phase14_adjustments.json`) to reflect current safety state.

**Why:** A drift-triggered freeze flipped the state file but decision paths read stale positive adjustments from cache, silently violating the "freeze suppresses positive learning" invariant (caught in architect review; regression test T32b now guards it).

**How to apply:** When adding new consumers of learning adjustments or freeze state, call `learning_frozen()` inside the decision path and filter positive contributions there; also recompute cached artifacts whenever the freeze flips (see `compute_drift`).

Other Phase 14 invariants: learn only from completed trades with per-row no-look-ahead audit; caps ±5/source ±10 total; reliability INSUFFICIENT<30/LOW/MODERATE≥50/STRONG≥100/HIGH≥250; no auto-promotion — checklist (≥100 OOS trades etc.) AND explicit human approval both required; calibrators versioned with OOS fallback to identity; exports secret-masked. Tests: `test_phase14.py` (41), regressions phase12/13 all pass.
