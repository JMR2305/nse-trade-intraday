"""
strategy_intelligence — Phase 5D.3: Strategy Intelligence.

READ-ONLY analytics module. Designed as a shared analytics service:
  → strategy_intelligence.shared_services is the stable interface for
    Phase 5D.4 (AI Performance Intelligence) and Phase 5D.5 (Executive Dashboard).

Never modifies: trading engine, paper trading engine, orders, portfolio,
                risk engine, signal engine, or strategy execution.

Controlled by STRATEGY_INTELLIGENCE_ENABLED=true.
"""
