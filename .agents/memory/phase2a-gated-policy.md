---
name: Phase 2A gated ranking policy
description: Status and conventions of the analysis-only corrected ranking/allocation policy (walk-forward variants D/E) vs the live legacy policy (C).
---

# Phase 2A gated ranking policy (analysis only)

The rule: the live decision pipeline runs the **legacy** strategy-ranking policy (walk-forward variant C). The corrected Phase 2A policy (hard eligibility gates, Bayesian shrinkage, edge-proportional allocation with cash remainder) exists only as analysis variants D (GATES_DEFAULT) and E (GATES_STRICT) inside the walk-forward validator, plus a parallel `gated` report in strategy intelligence. Deploying D requires an explicit, separate change — never wire it into live decisions as a side effect.

**Why:** User mandate — spec said ANALYSIS ONLY; verdict logic must keep being computed from variant C so results stay comparable across runs. First comparable run (Jul 2026, default config, 2 windows): C = +0.68% net; D and E took 0 trades (100% cash — every strategy failed the gates after shrinkage); 312 D-rejections, gate precision 61.9% (rejections that saved money). Recommendation logged: keep C live, re-evaluate D after more completed trades.

**How to apply:** Any future work touching strategy ranking/allocation must keep the legacy path bit-identical unless the user explicitly asks to promote D. Old walk-forward result payloads lack `phase2a` / `strategy_intelligence.gated` — UI must keep those sections conditionally rendered.

Operational notes:
- Full walk-forward run (default config, Full NIFTY 50) takes ~5–9 min; trigger via POST /api/walk-forward/run, poll /api/walk-forward/status.
- Python tests run from `artifacts/api-server/src/python`: `python3 tests/test_strategy_intelligence.py`.
- Restart the API Server workflow after Python changes before a validation run.
