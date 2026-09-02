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
    "test_event_intelligence",
    "test_macro_intelligence",
    "test_explainable_ai",
    "test_research_lab",
    "portfolio_performance.test_portfolio_performance",
    "tests.buy_audit_test",
    "tests.test_eod_reconciliation",
    "tests.test_phase20_startup_overnight_check",
    "tests.unit.test_size_reduced_to_cap",
])
def test_dependency_stubs_restore_and_consumers_import(producer):
    # A fresh interpreter makes the regression independent of the outer suite's
    # imports; this is a regression experiment, not a replacement for broad CI.
    program = r'''
import importlib
import sys
watched = ("market_scanner", "market_hours", "phase20_executor", "phase20_store",
           "scan_state_store", "config", "signals_store", "pipeline_events")
original = {name: sys.modules.get(name) for name in watched}
producer = importlib.import_module(sys.argv[1])
for name, previous in original.items():
    module = sys.modules.get(name)
    if previous is not None:
        assert module is previous, (name, "collection replaced a module")
    elif module is not None:
        assert vars(module).get("__file__"), (name, "collection installed a stub")
names = watched
missing = object()
for iteration in range(2):
    module_snapshot = dict(sys.modules)
    before = {name: sys.modules.get(name, missing) for name in names}
    fixture = producer._isolated_dependencies.__wrapped__()
    next(fixture)
    try:
        if sys.argv[1] == "tests.buy_audit_test":
            assert sys.modules["phase20_executor"].get_ledger() == []
            assert sys.modules["market_hours"].market_state() == "CLOSED"
        elif sys.argv[1] == "tests.test_eod_reconciliation":
            assert sys.modules["phase20_store"].get_settings()["execution_mode"] == "LIVE_ASSISTED"
            assert sys.modules["scan_state_store"].db_available() is False
        elif sys.argv[1] == "tests.test_phase20_startup_overnight_check":
            assert sys.modules["phase20_executor"].get_all_open_trades() == []
            assert sys.modules["phase20_store"].get_settings()["auto_paper_entries"] is False
        elif sys.argv[1] == "tests.unit.test_size_reduced_to_cap":
            assert sys.modules["portfolio_store"].load_state()["cash_available"] == 500_000
            assert sys.modules["market_hours"].market_status()["state"] == "CLOSED"
        elif "market_scanner" in producer._stub_modules():
            assert sys.modules["market_scanner"]._sector_of("INFY") == "IT"
            if "execution_quality.metrics" in producer._stub_modules():
                assert sys.modules["execution_quality.metrics"].build_execution_records() == []
        elif "phase20_executor" in producer._stub_modules():
            assert sys.modules["market_hours"].market_status() == {"state": "OPEN"}
            assert sys.modules["phase20_executor"].get_ledger() == []
        elif "config" in producer._stub_modules():
            assert "RELIANCE" in sys.modules["config"].DEFAULT_WATCHLIST
        else:
            assert sys.modules["signals_store"].load_signals()[0]["symbol"] == "RELIANCE"
    finally:
        fixture.close()
    assert all(sys.modules.get(name, missing) is previous for name, previous in before.items())
    assert sys.modules.keys() == module_snapshot.keys()
    assert all(sys.modules[name] is module for name, module in module_snapshot.items())
    if sys.argv[1].startswith("tests."):
        consumers = {"phase20_store": "operating_universe_verification",
                     "phase20_executor": "run_bootstrap_auto_entry",
                     "market_hours": "market_state"}
    elif "market_scanner" in producer._stub_modules():
        consumers = {"market_scanner": "_final_action"}
    elif "phase20_executor" in producer._stub_modules():
        consumers = {"market_hours": "market_state", "paper_trader": "get_trades",
                     "phase20_executor": "compute_fill"}
    else:
        config = importlib.import_module("config")
        assert isinstance(config.INITIAL_CAPITAL, (int, float))
        consumers = {"paper_trader": "get_trades"}
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
