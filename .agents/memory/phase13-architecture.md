---
name: Phase 13 architecture
description: 14-factor fusion engine, evidence labelling, regime-aware strategy evolution, OOS audit, API prefix gotcha
---

# Phase 13 Institutional AI & Strategy Evolution

## Core modules (artifacts/api-server/src/python/)
- `phase13_intelligence.py` — 14-factor fusion, regime tracking, calibrated confidence, volatility-aware sizing
- `phase13_strategy_evolution.py` — mutation proposals, human-approval gate, min 20 OOS trades threshold
- `phase13_audit.py` — out-of-sample model comparison (Phase 12 vs Phase 13)
- `phase13_diagnostics.py` — JSON + CSV diagnostic bundle

## Factor weights (sum = 1.0)
trend=0.15, momentum=0.12, volatility=0.06, volume=0.07, relative_strength=0.12,
market_regime=0.10, sector_strength=0.07, liquidity=0.05, hist_expectancy=0.08,
calibration_quality=0.02, data_freshness=0.02, historical_similarity=0.06,
risk_reward=0.05, portfolio_context=0.03

## Evidence labels
AVOID is correct when there are < 20 OOS trades — calibration multiplier 0.55 suppresses premature BUY signals.

## API routes (artifacts/api-server/src/routes/phase13.ts)
`/api/phase13/analysis`, `/api/phase13/regime`, `/api/phase13/sector-rotation`,
`/api/phase13/audit`, `/api/phase13/diagnostics`,
`/api/phase13/evolution`, `/api/phase13/evolution/generate`, `/api/phase13/evolution/review/:id`

## CRITICAL: apiJson prefix rule
`apiJson(path)` in the trading-dashboard already prepends `API_BASE` = `/api`.
So `queryFn: () => apiJson("/phase13/analysis")` → hits `/api/phase13/analysis`. CORRECT.
`apiJson("/api/phase13/analysis")` → hits `/api/api/phase13/analysis`. WRONG (404).
Always use paths WITHOUT the `/api` prefix when calling `apiJson()`.

## Test suite
test_phase13.py: 27 tests (T01–T22 + T14b, T14c, T15b). All must pass.
CRISIS regime has NO eligible strategies (correct by design).
Strategy evolution proposals require minimum 20 OOS trades before being generated.

**Why:** Conservative calibration prevents over-trading on thin evidence. The
system correctly shows AVOID/WATCH until paper trading history accumulates.

**How to apply:** When extending Phase 13 with new factors or strategies, ensure
the eligibility gates (regime-based, min-trades threshold) are preserved and the
14 factor weights still sum to 1.0.
