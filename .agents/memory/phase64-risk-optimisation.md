---
name: Phase 6.4 Risk Optimisation
description: Architecture and key design decisions for the Phase 6.4 Risk Optimisation & Capital Allocation module.
---

# Phase 6.4 Risk Optimisation

## Key Architecture Decisions

**Why:**
Same pattern as Phases 6.2 and 6.3 — read-only over Phase 6.1 TradeRecord stream, no writes.

**How to apply:**
- All analytics read from `paper_trading_validation.validation_collector.collect_all_trade_records()`
- Feature flag: `RISK_OPTIMISATION_ENABLED=true` (set in shared env)
- Module: `artifacts/api-server/src/python/risk_optimisation/`
- Public interface: `risk_optimisation/shared_services.py` only
- Downstream snapshot: `get_risk_optimisation_snapshot()` — never raises

## Health Score Formula

Risk Optimisation Score (0–100) =
  diversification_score × 25
  + (1 − drawdown_severity) × 25
  + capital_efficiency × 20
  + position_sizing_score × 15
  + stop_loss_quality_score × 15

## Capital Defaults

Starting capital defaults to ₹5,00,000 (DEFAULT_CAPITAL). Capital deployed = entry_price × quantity.

## Stop Loss / Target Classification

- SL: exit_reason keyword match on 'stop', 'sl', 'stoploss', 'stop_loss', 'trailing'
- Target: 'target', 'tgt', 'profit', 'take_profit', 'profit_target'

## Monte Carlo Hook

stress_tester.py returns `monte_carlo_simulation.enabled: false` by default. Future engine wires in here without API changes.

## Safety

advisory_only=True hardcoded in RiskRecommendation dataclass. Zero write imports anywhere in the module.
