---
name: Phase 23.8B validation & certification engines
description: Design rules for the six validation engines, certification aggregation, and long-duration scoring
---
- Six read-only validators in `validation_engines.py` (data/pipeline/portfolio/replay/ai_decision/performance) ORCHESTRATE existing checkers — replay via `backtest_replay.replay_verify`, decision determinism via the STORED validate_run verdict on the run record (never re-run live), metrics via `expectancy.compute_metrics` through strategy_lab helpers.
- Every validator accepts injected fixtures (candles/events/ledger rows/snapshot) so tests are seeded; production callers pass nothing.
- Verdict lattice: any FAIL→FAIL, else any WARN→WARN, else no evaluable checks→INSUFFICIENT_EVIDENCE, else PASS. **Why:** warnings must never be treated as pass (Phase 17 precedent).
- `certification_engine.py`: weighted domains (portfolio 0.20 heaviest; learning + mission_control 0.05 spot checks); READY requires EVERY domain PASS — WARN and INSUFFICIENT both block; WARN earns only half score credit. Runs persist append-only to `certification_runs` (file fallback), same store pattern as sim_runs.
- Long-duration windows (1w…1y) refuse to score unless ≥5 closed trades in window AND ledger history ≥ 0.8×window days — INSUFFICIENT_EVIDENCE over extrapolation.
- CLI: `cert_validate <domain>`, `cert_run`, `cert_history`, `cert_get`, `cert_long_duration`. Route `routes/certification.ts` uses 30s result cache + single-flight; `/certification/:certId` is registered LAST so named routes win.
- AST safety test in `test_validation_certification.py` covers both modules; add any new validation module to VALIDATION_FILES.
