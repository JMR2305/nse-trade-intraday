"""
executive_dashboard — Phase 5D.5 Executive Dashboard.

READ-ONLY aggregator. Consumes shared_services from:
  - Phase 5D.3 (strategy_intelligence.shared_services)
  - Phase 5D.4 (ai_performance.shared_services)
  - Phase 5D.1 (execution_quality.api)
  - Phase 5D.2 (portfolio_performance.api)
  - preopen_engine
  - phase11_risk
  - signal_validation_engine

NEVER modifies: trading engine, orders, portfolio, risk engine,
strategy execution, signals, or paper trading engine.
PAPER TRADING / ADVISORY ONLY.
"""
