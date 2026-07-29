---
name: Phase 6.2 Strategy Optimisation
description: Advisory-only strategy analytics module — architecture, underperform detection thresholds, and test patterns.
---

## Architecture
- Data source: `paper_trading_validation.validation_collector.collect_all_trade_records()` — no independent DB reads.
- `shared_services.py` stable API: `get_summary()`, `get_strategies()`, `get_recommendations()`, `get_patterns()`, `get_optimisation_snapshot()`, `export_strategies_csv()`, `export_recommendations_json()`.
- All `ParameterRec` dataclasses enforce `advisory_only=True` at model level.
- Feature flag: `STRATEGY_OPTIMISATION_ENABLED=true`.

## Underperform Detection
5 signals checked in `strategy_analyser._detect_underperforming()`:
1. Falling win rate — requires ≥10 trades; recent_wr < overall_wr − 0.15
2. Increasing drawdown — requires ≥10 trades
3. Poor execution — `avg_execution_score < 60` (no trade count floor)
4. Poor AI confidence — `avg_confidence < 0.5` (no trade count floor)
5. Increasing risk — requires ≥10 trades; recent_risk > avg_risk × 1.3

**Why:** Tests use signals 3 & 4 (eq_score=45, confidence=0.3) to trigger `is_underperforming` on small datasets (< 10 trades). Never rely on falling-win-rate signal in tests with < 10 trades.

## Test pattern
To make a strategy appear underperforming in tests (< 10 trades): set `eq_score=45.0` + `confidence=0.3`.

## Adaptive Learning Lifecycle
- EMERGING: < 5 trades
- ACTIVE: ≥ 5 trades, consistent
- DECLINING: recent_win_rate trending down
- DORMANT: no recent activity

## Route
6 Express endpoints at `/optimisation/*`; 4 commands in main.py (`optimisation_summary`, `_strategies`, `_recommendations`, `_patterns`) + 2 export commands.

## Tests: 39/39 passing
