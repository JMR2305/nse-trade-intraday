"""Regression: scoped dependency doubles must not poison later real imports."""
import os
from pathlib import Path
import subprocess
import sys

import pytest
from task974_test_isolation import isolated_imports


def test_isolated_imports_restores_existing_child_module_namespace():
    """A reload mutates a cached child object; its namespace must be restored."""
    import types

    package = types.ModuleType("task974_synthetic")
    package.__path__ = []
    package.__file__ = __file__
    child = types.ModuleType("task974_synthetic.shared_services")
    child.__file__ = __file__
    child.answer = "real"
    package.shared_services = child
    sys.modules[package.__name__] = package
    sys.modules[child.__name__] = child
    try:
        with isolated_imports({}, target_packages=(package.__name__,)):
            sys.modules[package.__name__] = package
            sys.modules[child.__name__] = child
            package.shared_services = child
            child.answer = "stub-bound"
        assert sys.modules[child.__name__] is child
        assert child.answer == "real"
        assert package.shared_services is child
    finally:
        sys.modules.pop(child.__name__, None)
        sys.modules.pop(package.__name__, None)


@pytest.mark.parametrize("producer,fixture_name", [
    ("test_consecutive_blocks", "_isolated_dependencies"),
    ("test_analytics_30plus_integration", "_isolated_dependencies"),
    ("ai_performance.test_ai_performance", "_isolated_dependencies"),
    ("strategy_intelligence.test_strategy_intelligence", "_isolated_dependencies"),
    ("test_event_intelligence", "_isolated_dependencies"),
    ("test_macro_intelligence", "_isolated_dependencies"),
    ("test_explainable_ai", "_isolated_dependencies"),
    ("test_research_lab", "_isolated_dependencies"),
    ("portfolio_performance.test_portfolio_performance", "_isolated_dependencies"),
    ("tests.buy_audit_test", "_isolated_dependencies"),
    ("tests.test_eod_reconciliation", "_isolated_dependencies"),
    ("tests.test_phase20_startup_overnight_check", "_isolated_dependencies"),
    ("tests.unit.test_size_reduced_to_cap", "_isolated_dependencies"),
    ("tests.test_ohlcv_cold_start_check", "_isolated_scheduler_import"),
    ("tests.unit.test_bootstrap_paper_trade", "_isolated_executor_import"),
])
def test_dependency_stubs_restore_and_consumers_import(producer, fixture_name):
    # A fresh interpreter makes the regression independent of the outer suite's
    # imports; this is a regression experiment, not a replacement for broad CI.
    program = r'''
import importlib
import sys
watched = ("market_scanner", "market_hours", "phase20_executor", "phase20_store",
           "scan_state_store", "config", "signals_store", "pipeline_events")
original = {name: sys.modules.get(name) for name in watched}
producer = importlib.import_module(sys.argv[1])
fixture_name = sys.argv[2]
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
    fixture = getattr(producer, fixture_name).__wrapped__()
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
        elif sys.argv[1] == "tests.test_ohlcv_cold_start_check":
            assert callable(sys.modules["phase20_store"].kv_claim_once)
            assert producer.sched.__name__ == "phase20_scheduler"
        elif sys.argv[1] == "tests.unit.test_bootstrap_paper_trade":
            assert callable(producer.run_bootstrap_auto_entry)
            assert callable(sys.modules["phase20_store"].kv_claim_once)
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
    result = subprocess.run([sys.executable, "-c", program, producer, fixture_name],
                            cwd=Path(__file__).resolve().parent,
                            env=os.environ.copy(), text=True,
                            capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
