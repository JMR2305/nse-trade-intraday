---
name: Phase 8.4 Advanced Risk Validation Framework
description: Architecture, test patterns, and wiring for the read-only risk validation module.
---

# Phase 8.4 — Advanced Risk Validation Framework

## Feature Flag
`RISK_VALIDATION_ENABLED=true`

## Module location
`artifacts/api-server/src/python/risk_validation/`  
Files: `__init__.py`, `models.py`, `portfolio.py`, `sector.py`, `correlation.py`, `stress.py`, `tail_risk.py`, `execution.py`, `market_risk.py`, `drift.py`, `shared_services.py`, `api.py`

## Weights (must sum 1.0)
portfolio=0.30, sector=0.15, correlation=0.10, stress=0.10, tail_risk=0.10, execution=0.10, market_risk=0.10, drift=0.05

## Key design rules
- All validators use `_safe(fn, default)` wrappers — never crash when upstream data is absent
- Unavailable domains return `unavailable_result()` (available=False, score=0) and are **skipped** (not zeroed) in weighted score
- `_weighted_score()` iterates `_WEIGHTS` — pass ALL 8 domains in test dicts or missing ones default to available=True + score=0
- Each validator imports upstream modules (`portfolio_store`, `paper_analytics`, `market_intelligence_hub`, `macro_intelligence`, `risk_optimisation`) lazily inside the function — ImportError is caught by `_safe`

## Routes
Express: `artifacts/api-server/src/routes/risk-validation.ts` — uses locally-defined `runPython` (same inline pattern as phase18.ts / data-quality.ts, NOT a shared import)
Commands: `rv_summary`, `rv_portfolio`, `rv_sector`, `rv_correlation`, `rv_stress`, `rv_tail`, `rv_execution`, `rv_market`, `rv_drift`, `rv_alerts`, `rv_snapshot`, `rv_export_json`, `rv_export_csv`

## React page
`artifacts/trading-dashboard/src/pages/RiskValidation.tsx`  
12 tabs: overview, portfolio, positions, sectors, correlation, stress, tail, execution, market, drift, alerts, export  
Route: `/risk-validation` (App.tsx + AppLayout.tsx Analytics group)

## Test patterns
- Python: patch ALL domain loaders via `patch.multiple("risk_validation.shared_services", _load_portfolio=..., ...)` to avoid real data dependencies
- React: use `queryAllByText(...).length > 0` (not `queryByText`) when text appears in multiple DOM nodes (e.g. "IT" in domain table + sectors, "NEUTRAL" in market cards, "ADVISORY-ONLY" in multiple banners)
- `data-testid` on `<Card>` is not forwarded — test against `rv-issues-table` (from IssuesTable component) instead of card-level testid

## Tail risk
Uses parametric VaR/CVaR with India VIX → daily vol conversion (VIX/100/√252). Default daily vol = 1.2% when no VIX data.

**Why:** READ-ONLY · ADVISORY-ONLY — must never modify positions, strategies, or orders. All downstream phases (8.5, 8.6, 8.7, 8.8) can read via `get_risk_validation_snapshot()`.
