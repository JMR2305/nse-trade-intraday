"""Regression: scoped dependency doubles must not poison later real imports."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("producer", [
    "test_consecutive_blocks",
    "test_analytics_30plus_integration",
    "ai_performance.test_ai_performance",
    "strategy_intelligence.test_strategy_intelligence",
])
def test_dependency_stubs_restore_and_consumers_import(producer):
    # A fresh interpreter makes the regression independent of the outer suite's
    # imports; this is a regression experiment, not a replacement for broad CI.
    program = r'''
import importlib
import sys
producer = importlib.import_module(sys.argv[1])
names = tuple(producer._stub_modules())
assert all(name not in sys.modules for name in names), "collection installed a stub"
missing = object()
for iteration in range(2):
    before = {name: sys.modules.get(name, missing) for name in names}
    fixture = producer._isolated_dependencies.__wrapped__()
    next(fixture)
    try:
        if "market_scanner" in names:
            assert sys.modules["market_scanner"]._sector_of("INFY") == "IT"
            assert sys.modules["execution_quality.metrics"].build_execution_records() == []
        else:
            assert sys.modules["market_hours"].market_status() == {"state": "OPEN"}
            assert sys.modules["phase20_executor"].get_ledger() == []
    finally:
        fixture.close()
    assert all(sys.modules.get(name, missing) is previous for name, previous in before.items())
    consumers = ({"market_scanner": "_final_action"} if "market_scanner" in names
                 else {"market_hours": "market_state", "paper_trader": "get_trades",
                       "phase20_executor": "compute_fill"})
    for name, attribute in consumers.items():
        module = importlib.import_module(name)
        assert module.__file__, name
        assert callable(getattr(module, attribute)), (name, attribute)
'''
    result = subprocess.run([sys.executable, "-c", program, producer],
                            cwd=Path(__file__).resolve().parent,
                            env=os.environ.copy(), text=True,
                            capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
