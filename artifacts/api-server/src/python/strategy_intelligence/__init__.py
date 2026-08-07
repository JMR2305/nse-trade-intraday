"""
strategy_intelligence — Phase 5D.3: Strategy Intelligence.

READ-ONLY analytics module. Designed as a shared analytics service:
  → strategy_intelligence.shared_services is the stable interface for
    Phase 5D.4 (AI Performance Intelligence) and Phase 5D.5 (Executive Dashboard).

Never modifies: trading engine, paper trading engine, orders, portfolio,
                risk engine, signal engine, or strategy execution.

Controlled by STRATEGY_INTELLIGENCE_ENABLED=true.

Compatibility shim
------------------
This package shadows the top-level legacy module `strategy_intelligence.py`
(Phase 2: adaptive strategy selection). Importers such as
walk_forward_validator and decision_service expect that module's names
(StrategyIntelligence, classify_regime, trades_from_knowledge, ...) to be
importable from `strategy_intelligence`. We load the sibling file explicitly
and re-export its public names so both APIs keep working.
"""

import importlib.util as _ilu
import os as _os
import sys as _sys

_legacy_path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                             "strategy_intelligence.py")

if _os.path.exists(_legacy_path):
    _spec = _ilu.spec_from_file_location("_strategy_intelligence_legacy", _legacy_path)
    _legacy = _ilu.module_from_spec(_spec)
    _sys.modules["_strategy_intelligence_legacy"] = _legacy
    _spec.loader.exec_module(_legacy)
    for _name in dir(_legacy):
        if not _name.startswith("_"):
            globals()[_name] = getattr(_legacy, _name)
