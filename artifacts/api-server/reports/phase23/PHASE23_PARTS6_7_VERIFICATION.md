# Phase 23 Parts 6 & 7 — Verification Report

**Date:** 2026-08-08 · **Verdict:** PASS

## Scope
Part 6 — AI Strategy Optimization Lab (`/optimization-lab`); Part 7 — Institutional Performance Analytics (`/institutional-analytics`). Backend module `src/python/strategy_lab.py`, 13 `lab_*` CLI commands in `main.py`, Express router `src/routes/lab.ts` (13 endpoints under `/api/lab/*`).

## Deliverables A–P
| Part | Deliverable | Where | Status |
|---|---|---|---|
| A | Config comparison | `compare_configs` + What-If card | ✅ |
| B | Multi-run comparison | `compare_runs` + table/overlay chart | ✅ |
| C | Parameter what-if optimizer | `what_if` (filters + exit re-simulation) | ✅ |
| D | Walk-forward validation | `walk_forward` (folds, generalization, overfitting risk) | ✅ |
| E | Monte Carlo | `monte_carlo` (seeded bootstrap, 500 paths, histograms) | ✅ |
| F/G/H | Regime / time / sector analytics | `bucket_analysis` (regime, sector, hour, weekday, month, strategy) | ✅ |
| I | Strategy leaderboard | `leaderboard` | ✅ |
| J | Confidence calibration | `calibration` (reliability curve, Brier; paper embeds phase21 verbatim) | ✅ |
| K | Institutional dashboard | `dashboard` bundle (equity, drawdown, monthly, rolling, heatmap, utilization) | ✅ |
| L | Recommendations | `recommendations` — advisory-only, `auto_apply: false` hardcoded | ✅ |
| M | Run diff | `run_diff` | ✅ |
| N | Export | JSON/CSV/Markdown server-side; PDF via browser print (documented compromise) | ✅ |
| O | Validation | `lab_verify` — see below | ✅ |
| P | Performance | 30–60s route caches + coalescing; heavy endpoints 120–300s timeouts | ✅ |

## Safety guarantees (verified, not asserted)
- **Read-only:** `lab_verify` on real run `BT-85a4febee3` → **PASS**: run record + trade ledger byte-identical after what-if, walk-forward and recommendations; `replay_verify` still PASS; live settings hash unchanged; learning engine untouched.
- **No duplicate math:** metric computation delegates to `expectancy.compute_metrics`; paper calibration embeds `phase21_calibration.run_calibration()`; what-if resimulates exits against the same candle cache the runner used.
- **No auto changes:** recommendations carry `advisory: true` and `auto_apply: false`; UI states "auto-apply is disabled".
- **INSUFFICIENT_EVIDENCE over extrapolation:** MIN_EVIDENCE=5; all analytics return explicit verdicts; UI renders intentional amber states (verified via screenshot on the 1-trade real run).
- **Canonical sources only:** backtest store (`backtest_persistence`), phase20 ledger (BUY rows), candle cache, settings store — no new state written anywhere.

## Review-round fixes applied
- What-if exit re-simulation never retains baseline exits: failed re-sims are excluded from the derived result, listed in `resim_failed`, and the verdict becomes `RESIM_INCOMPLETE`.
- Monte Carlo now compounds portfolio-level returns (realized PnL ÷ actual portfolio capital), not "all-in" per-trade notional returns — risk-of-ruin / survival figures are portfolio-consistent.
- Export download URL fixed (`API_BASE` already includes `/api`).
- Route hardening: run-id/param/config size caps before spawning Python; bounded coalescing cache (max 100 entries, oldest evicted).

## Tests
- `test_backtest_engine.py`: **24/24 pass** including new `TestStrategyLab` (6 tests: metrics/compare, what-if immutability byte-check, walk-forward + deterministic Monte Carlo, buckets/leaderboard/calibration, dashboard/recommendations/diff/export, insufficient-evidence fail-safes).
- Typecheck clean for api-server and trading-dashboard. Both pages screenshot-verified live.
