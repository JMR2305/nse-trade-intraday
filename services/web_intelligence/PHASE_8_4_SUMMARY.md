# Phase 8.4 — Advanced Risk Validation Framework

**Type:** Read-only · Advisory-only  
**Feature Flag:** `RISK_VALIDATION_ENABLED=true`

---

## Overview

Phase 8.4 adds a multi-domain risk validation layer that scores the current paper portfolio across 8 independent risk dimensions and surfaces actionable alerts — without ever modifying positions, strategies, or orders.

---

## Architecture

### Python Module
`artifacts/api-server/src/python/risk_validation/`

| File | Responsibility |
|------|---------------|
| `models.py` | Pydantic models — `DomainResult`, `RiskValidationSnapshot`, `RiskAlert` |
| `shared_services.py` | Lazy data loaders with `_safe()` wrappers; `get_risk_validation_snapshot()` for downstream phases |
| `portfolio.py` | Position concentration, leverage, margin usage |
| `sector.py` | Sector exposure HHI, over-weight detection |
| `correlation.py` | Pairwise symbol correlation, cluster risk |
| `stress.py` | Historical scenario stress-testing (2008, COVID, Taper, etc.) |
| `tail_risk.py` | Parametric VaR / CVaR using India VIX → daily vol conversion |
| `execution.py` | Fill-quality, slippage, order rejection rate |
| `market_risk.py` | Regime-gated risk multipliers from market intelligence hub |
| `drift.py` | Portfolio drift from target allocation over time |
| `api.py` | CLI entry points (`rv_summary`, `rv_snapshot`, `rv_alerts`, etc.) |

### Express Routes
`artifacts/api-server/src/routes/risk-validation.ts`

Each route uses a locally-defined `runPython` inline — same pattern as `phase18.ts` / `data-quality.ts`. **Not** a shared import.

Commands exposed:
`rv_summary`, `rv_portfolio`, `rv_sector`, `rv_correlation`, `rv_stress`, `rv_tail`, `rv_execution`, `rv_market`, `rv_drift`, `rv_alerts`, `rv_snapshot`, `rv_export_json`, `rv_export_csv`

### React Page
`artifacts/trading-dashboard/src/pages/RiskValidation.tsx`

12 tabs: Overview · Portfolio · Positions · Sectors · Correlation · Stress · Tail Risk · Execution · Market · Drift · Alerts · Export

Route: `/risk-validation` (registered in `App.tsx` + `AppLayout.tsx` under the Analytics group)

---

## Domain Weights

All 8 domains contribute to a single composite Risk Validation Score. Weights sum to exactly **1.0**:

| Domain | Weight |
|--------|--------|
| Portfolio | 0.30 |
| Sector | 0.15 |
| Correlation | 0.10 |
| Stress | 0.10 |
| Tail Risk | 0.10 |
| Execution | 0.10 |
| Market Risk | 0.10 |
| Drift | 0.05 |

---

## Key Design Rules

1. **Never crash on missing data.** Every validator wraps upstream calls in `_safe(fn, default)`. If a domain's data source is unavailable, it returns `unavailable_result()` (`available=False`, `score=0`) and is **skipped** (not zeroed) in the weighted composite — so a missing upstream module does not drag the overall score to zero.

2. **Lazy imports everywhere.** Each domain validator imports its upstream module (`portfolio_store`, `paper_analytics`, `market_intelligence_hub`, `macro_intelligence`, `risk_optimisation`) inside the function body. `ImportError` is caught by `_safe`. This means the module loads even when upstream phases are not deployed.

3. **Weighted score requires all 8 domains.** `_weighted_score()` iterates `_WEIGHTS` dict. In tests, supply all 8 domains explicitly or missing ones default to `available=True, score=0` and silently lower the composite.

4. **Advisory-only.** The module has no write path. All downstream phases (8.5, 8.6, 8.7, 8.8) read via `get_risk_validation_snapshot()` — they never call individual domain validators directly.

---

## Tail Risk Methodology

- **Model:** Parametric VaR / CVaR
- **Volatility source:** India VIX → daily vol conversion: `VIX / 100 / √252`
- **Fallback:** daily vol = **1.2%** when no VIX data is available
- **Confidence levels:** 95% VaR, 99% CVaR

---

## Test Patterns

### Python
Patch all domain loaders together to avoid real data dependencies:

```python
with patch.multiple(
    "risk_validation.shared_services",
    _load_portfolio=...,
    _load_paper_analytics=...,
    _load_market_intelligence=...,
    # ... all 8 loaders
):
    result = get_risk_validation_snapshot()
```

### React
- Use `queryAllByText(...).length > 0` (not `queryByText`) when text appears in multiple DOM nodes — e.g. `"IT"` appears in both the domain table and the sectors panel; `"NEUTRAL"` appears in multiple market cards; `"ADVISORY-ONLY"` appears in multiple banners.
- Do **not** test against Card-level `data-testid` — `<Card>` does not forward the prop. Use `rv-issues-table` (from `IssuesTable` component) instead.

---

## Downstream Consumers

| Phase | Reads via |
|-------|-----------|
| 8.5 | `get_risk_validation_snapshot()` |
| 8.6 | `get_risk_validation_snapshot()` |
| 8.7 | `get_risk_validation_snapshot()` |
| 8.8 | `get_risk_validation_snapshot()` |

---

## Summary

Phase 8.4 is a fully read-only, advisory-only risk scoring engine. It ingests data from five upstream modules (portfolio store, paper analytics, market intelligence, macro intelligence, risk optimisation), produces a weighted composite score across 8 domains, and surfaces prioritised alerts — all without touching any position, strategy, or order. Downstream phases consume a single `get_risk_validation_snapshot()` call.
