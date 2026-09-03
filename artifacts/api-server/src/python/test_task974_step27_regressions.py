"""Focused regressions for collection leakage and late-running freshness tests."""
from pathlib import Path
import subprocess
import sys


def _run(program):
    result = subprocess.run([sys.executable, "-c", program], text=True,
                            capture_output=True, cwd=Path(__file__).parent,
                            timeout=70)
    assert result.returncode == 0, result.stdout + result.stderr


def test_observability_stubs_restore_before_real_timeline():
    _run(r'''
import importlib
import sys
from unittest.mock import patch
watched = ("market_intelligence_hub.shared_services", "event_intelligence.shared_services",
           "macro_intelligence.shared_services", "explainable_ai.shared_services",
           "research_lab.shared_services", "scan_state_store")
before = {name: sys.modules.get(name) for name in watched}
producer = importlib.import_module("test_observability_center")
assert {name: sys.modules.get(name) for name in watched} == before, "collection installed stubs"
for _ in range(2):
    scope = producer._scoped_snapshot_dependencies.__wrapped__()
    next(scope)
    try:
        assert sys.modules[watched[0]].get_market_intelligence_snapshot()["score"] == 65.0
        producer.TestFeatureFlag().test_enabled_returns_true()
    finally:
        try:
            next(scope)
        except StopIteration:
            pass
    assert {name: sys.modules.get(name) for name in watched} == before
from test_analysis_agents import TestAnalysisLayer
with patch("market_regime.get_regime", return_value={}):
    TestAnalysisLayer().test_timeline_no_buy_sell()
''')


def test_fresh_portfolio_fixtures_survive_collection_age():
    _run(r'''
from datetime import datetime, timedelta, timezone
import pytest
class AgeCollectedFixtures:
    def pytest_collection_modifyitems(self, items):
        for item in items:
            item.module._NOW = datetime.now(timezone.utc) - timedelta(seconds=120)
nodes = [
 "tests/unit/portfolio/test_exposure.py::TestCalculateExposure::test_stale_prices_false_when_fresh",
 "tests/unit/portfolio/test_freeze_patch_coverage.py::TestHealthMonitorBranches::test_stale_broker_triggers_degraded",
 "tests/unit/portfolio/test_freeze_patch_coverage.py::TestHealthMonitorBranches::test_unresolved_discrepancies_prevents_readiness",
 "tests/unit/portfolio/test_freeze_patch_coverage.py::TestHealthMonitorBranches::test_ready_no_issues_is_healthy",
 "tests/unit/portfolio/test_freeze_patch_coverage.py::TestHealthMonitorBranches::test_compute_health_via_monitor",
 "tests/unit/portfolio/test_reconciliation.py::TestStalenessKeyFormats::test_fresh_snapshot_at_key_not_flagged",
 "tests/unit/portfolio/test_reconciliation.py::TestStalenessKeyFormats::test_snapshot_at_takes_precedence_over_as_of",
]
raise SystemExit(pytest.main([*nodes, "-q", "--tb=short"], plugins=[AgeCollectedFixtures()]))
''')


def test_open_session_fixture_ignores_wall_clock_and_restores_it():
    _run(r'''
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch
from test_daily_session_and_pipeline_e2e import TestRunTickOpenAlertE2E
import market_hours
for hour in (0, 16):
    instant = datetime(2026, 9, 3, hour, 10, tzinfo=ZoneInfo("Asia/Kolkata"))
    with patch("market_hours.now_ist", return_value=instant) as ambient:
        result = TestRunTickOpenAlertE2E("test_open_retry_success_emits_no_alert").run()
        assert result.wasSuccessful(), (result.errors, result.failures)
        assert market_hours.now_ist is ambient
        assert market_hours.now_ist() == instant
''')
