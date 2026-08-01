"""
test_operations_center.py — Phase 8.5
Unit tests for the Operational Control Centre.

Tests cover:
  - Feature flag gate
  - Snapshot aggregation
  - Dashboard summary
  - Alert aggregation
  - Checklist generation
  - Timeline construction
  - Jobs status
  - Feature flags enumeration
  - Shared services (upstream mocking)
  - API command wrappers
  - Export (JSON + CSV)
"""
from __future__ import annotations

import os
import pytest
from unittest.mock import patch, MagicMock

# ── Helpers ────────────────────────────────────────────────────────────────────

def _obs(score=75, available=True):
    return {
        "available": available,
        "observability_score": score,
        "grade": "B",
        "system_status": "HEALTHY",
        "trend": "STABLE",
    }

def _dq(score=80, available=True, critical=0, warning=2):
    return {
        "available": available,
        "quality_score": score,
        "grade": "B",
        "critical_count": critical,
        "warning_count": warning,
        "total_issues": critical + warning,
    }

def _rv(score=70, available=True):
    return {
        "available": available,
        "validation_score": score,
        "grade": "B",
        "alerts": [],
    }

def _sched(status="HEALTHY", available=True):
    return {"available": available, "status": status}

def _mi(available=True):
    return {
        "available": available,
        "regime": "TRENDING",
        "vix": 14.5,
        "data_provider": "KITE",
    }

_ALL_LOADERS = dict(
    _load_observability=lambda: _obs(),
    _load_data_quality=lambda: _dq(),
    _load_risk_validation=lambda: _rv(),
    _load_market_intelligence=lambda: _mi(),
    _load_paper_analytics=lambda: {"available": True, "trades_today": 3},
    _load_portfolio=lambda: {"cash": 50000, "total_value": 100000, "total_pnl": 500, "positions": []},
    _load_scheduler_health=lambda: _sched(),
    _load_recent_scan_runs=lambda limit=20: [],
    _load_notifications=lambda limit=50: [],
    _load_observability_alerts=lambda: [],
    _load_data_quality_issues=lambda: [],
    _load_risk_alerts=lambda: [],
)

MOD = "operations_center.shared_services"


# ── Feature flag ───────────────────────────────────────────────────────────────

class TestFeatureFlag:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("OPERATIONS_CENTER_ENABLED", raising=False)
        from operations_center.models import is_enabled
        assert is_enabled() is False

    def test_enabled_true(self, monkeypatch):
        monkeypatch.setenv("OPERATIONS_CENTER_ENABLED", "true")
        from operations_center.models import is_enabled
        assert is_enabled() is True

    def test_enabled_1(self, monkeypatch):
        monkeypatch.setenv("OPERATIONS_CENTER_ENABLED", "1")
        from operations_center.models import is_enabled
        assert is_enabled() is True

    def test_disabled_returns_status(self, monkeypatch):
        monkeypatch.delenv("OPERATIONS_CENTER_ENABLED", raising=False)
        from operations_center.shared_services import get_summary
        result = get_summary()
        assert result["status"] == "DISABLED"
        assert result["available"] is False

    def test_disabled_all_endpoints(self, monkeypatch):
        monkeypatch.delenv("OPERATIONS_CENTER_ENABLED", raising=False)
        from operations_center.shared_services import (
            get_market, get_risk, get_data_quality,
            get_observability, get_jobs, get_alerts,
            get_checklist, get_timeline, get_feature_flags,
            get_operations_snapshot,
        )
        for fn in [get_market, get_risk, get_data_quality,
                   get_observability, get_jobs, get_alerts,
                   get_checklist, get_timeline, get_feature_flags]:
            r = fn()
            assert r["available"] is False, f"{fn.__name__} should be disabled"
        snap = get_operations_snapshot()
        assert snap["available"] is False


# ── Snapshot aggregation / ops score ──────────────────────────────────────────

class TestSnapshotAggregation:
    def setup_method(self):
        os.environ["OPERATIONS_CENTER_ENABLED"] = "true"

    def teardown_method(self):
        os.environ.pop("OPERATIONS_CENTER_ENABLED", None)

    def test_ops_score_all_available(self):
        from operations_center.shared_services import _ops_score
        score = _ops_score(_obs(75), _dq(80), _rv(70), _sched())
        # 75*0.25 + 80*0.30 + 70*0.30 + 100*0.15 = 18.75+24+21+15 = 78.75
        assert 70 < score < 90

    def test_ops_score_unavailable_modules(self):
        from operations_center.shared_services import _ops_score
        score = _ops_score(
            {"available": False, "observability_score": 0},
            {"available": False, "quality_score": 0},
            {"available": False, "validation_score": 0},
            {"available": False, "status": "UNKNOWN"},
        )
        assert 0 <= score <= 50  # degraded when all unavailable

    def test_ops_score_clamped(self):
        from operations_center.shared_services import _ops_score
        score = _ops_score(_obs(100), _dq(100), _rv(100), _sched())
        assert score <= 100.0

    def test_platform_status_operational(self):
        from operations_center.shared_services import _platform_status
        status = _platform_status(85, _obs(85), _dq(80, critical=0))
        assert status == "OPERATIONAL"

    def test_platform_status_degraded(self):
        from operations_center.shared_services import _platform_status
        status = _platform_status(60, _obs(60), _dq(60, critical=1))
        assert status == "DEGRADED"

    def test_platform_status_down(self):
        from operations_center.shared_services import _platform_status
        status = _platform_status(30, _obs(30, available=False), _dq(30, critical=10))
        assert status == "DOWN"

    def test_get_operations_snapshot_keys(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import get_operations_snapshot
            snap = get_operations_snapshot()
        assert snap["available"] is True
        for key in ("operations_score", "grade", "platform_status", "generated_at"):
            assert key in snap

    def test_snapshot_advisory_only(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import get_operations_snapshot
            snap = get_operations_snapshot()
        assert snap["advisory_only"] is True


# ── Summary ────────────────────────────────────────────────────────────────────

class TestSummary:
    def setup_method(self):
        os.environ["OPERATIONS_CENTER_ENABLED"] = "true"

    def teardown_method(self):
        os.environ.pop("OPERATIONS_CENTER_ENABLED", None)

    def test_summary_keys(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import get_summary
            result = get_summary()
        required = [
            "operations_score", "grade", "platform_status",
            "market_open", "trading_session", "system_health",
            "risk_level", "data_quality_grade", "outstanding_alerts",
            "active_modules", "generated_at", "available", "advisory_only",
        ]
        for k in required:
            assert k in result, f"Missing key: {k}"

    def test_summary_available(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import get_summary
            result = get_summary()
        assert result["available"] is True
        assert result["advisory_only"] is True

    def test_summary_active_modules(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import get_summary
            result = get_summary()
        assert isinstance(result["active_modules"], list)

    def test_summary_grade_valid(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import get_summary
            result = get_summary()
        assert result["grade"] in ("A+", "A", "B", "C", "D")


# ── Market ─────────────────────────────────────────────────────────────────────

class TestMarket:
    def setup_method(self):
        os.environ["OPERATIONS_CENTER_ENABLED"] = "true"

    def teardown_method(self):
        os.environ.pop("OPERATIONS_CENTER_ENABLED", None)

    def test_market_keys(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import get_market
            result = get_market()
        for k in ("market_open", "session", "regime", "ist_time", "available"):
            assert k in result

    def test_market_advisory_only(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import get_market
            result = get_market()
        assert result["advisory_only"] is True

    def test_market_open_bool(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import get_market
            result = get_market()
        assert isinstance(result["market_open"], bool)


# ── Alerts ─────────────────────────────────────────────────────────────────────

class TestAlerts:
    def setup_method(self):
        os.environ["OPERATIONS_CENTER_ENABLED"] = "true"

    def teardown_method(self):
        os.environ.pop("OPERATIONS_CENTER_ENABLED", None)

    def test_alerts_keys(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import get_alerts
            result = get_alerts()
        for k in ("total", "critical", "warnings", "info", "critical_count", "warning_count"):
            assert k in result

    def test_alerts_with_observability_alerts(self):
        loaders = {**_ALL_LOADERS, "_load_observability_alerts": lambda: [
            {"alert_id": "a1", "severity": "CRITICAL", "source": "SYSTEM",
             "title": "DB Down", "detail": "DB unreachable", "acknowledged": False, "resolved": False}
        ]}
        with patch.multiple(MOD, **loaders):
            from operations_center.shared_services import get_alerts
            result = get_alerts()
        assert result["critical_count"] >= 1

    def test_alerts_with_dq_issues(self):
        loaders = {**_ALL_LOADERS, "_load_data_quality_issues": lambda: [
            {"check_id": "dq1", "severity": "WARNING", "title": "Stale data", "detail": "10min stale"}
        ]}
        with patch.multiple(MOD, **loaders):
            from operations_center.shared_services import get_alerts
            result = get_alerts()
        assert result["warning_count"] >= 1

    def test_alerts_counts_consistent(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import get_alerts
            result = get_alerts()
        assert result["critical_count"] == len(result["critical"])
        assert result["warning_count"] == len(result["warnings"])


# ── Checklist ──────────────────────────────────────────────────────────────────

class TestChecklist:
    def setup_method(self):
        os.environ["OPERATIONS_CENTER_ENABLED"] = "true"

    def teardown_method(self):
        os.environ.pop("OPERATIONS_CENTER_ENABLED", None)

    def test_checklist_keys(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import get_checklist
            result = get_checklist()
        for k in ("phase", "items", "ok_count", "warning_count", "total", "completion_pct"):
            assert k in result

    def test_checklist_items_are_dicts(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import get_checklist
            result = get_checklist()
        for item in result["items"]:
            assert "item_id" in item
            assert "title" in item
            assert "status" in item

    def test_checklist_phase_is_string(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import get_checklist
            result = get_checklist()
        assert isinstance(result["phase"], str)
        assert len(result["phase"]) > 0

    def test_checklist_completion_pct_valid(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import get_checklist
            result = get_checklist()
        assert 0 <= result["completion_pct"] <= 100

    def test_checklist_advisory_only(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import get_checklist
            result = get_checklist()
        assert result["advisory_only"] is True


# ── Timeline ───────────────────────────────────────────────────────────────────

class TestTimeline:
    def setup_method(self):
        os.environ["OPERATIONS_CENTER_ENABLED"] = "true"

    def teardown_method(self):
        os.environ.pop("OPERATIONS_CENTER_ENABLED", None)

    def test_timeline_keys(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import get_timeline
            result = get_timeline()
        assert "events" in result
        assert "total" in result

    def test_timeline_events_list(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import get_timeline
            result = get_timeline()
        assert isinstance(result["events"], list)

    def test_timeline_with_scan_runs(self):
        loaders = {**_ALL_LOADERS, "_load_recent_scan_runs": lambda limit=20: [
            {"run_id": "r1", "status": "SUCCESS", "started_at": "2024-01-15T10:00:00",
             "duration_seconds": 45, "symbols_scanned": 50},
        ]}
        with patch.multiple(MOD, **loaders):
            from operations_center.shared_services import get_timeline
            result = get_timeline()
        scan_events = [e for e in result["events"] if e["category"] == "SCHEDULER"]
        assert len(scan_events) >= 1

    def test_timeline_event_fields(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import get_timeline
            result = get_timeline()
        for event in result["events"]:
            for field in ("event_id", "category", "title", "timestamp"):
                assert field in event


# ── Jobs ───────────────────────────────────────────────────────────────────────

class TestJobs:
    def setup_method(self):
        os.environ["OPERATIONS_CENTER_ENABLED"] = "true"

    def teardown_method(self):
        os.environ.pop("OPERATIONS_CENTER_ENABLED", None)

    def test_jobs_keys(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import get_jobs
            result = get_jobs()
        for k in ("scheduler_status", "current_jobs", "upcoming_jobs", "failed_jobs", "recent_jobs"):
            assert k in result

    def test_jobs_with_failed_run(self):
        loaders = {**_ALL_LOADERS, "_load_recent_scan_runs": lambda limit=20: [
            {"run_id": "f1", "status": "FAILED", "started_at": "2024-01-15T09:30:00",
             "duration_seconds": 5, "run_type": "SCAN"},
        ]}
        with patch.multiple(MOD, **loaders):
            from operations_center.shared_services import get_jobs
            result = get_jobs()
        assert len(result["failed_jobs"]) >= 1

    def test_jobs_advisory_only(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import get_jobs
            result = get_jobs()
        assert result["advisory_only"] is True


# ── Feature Flags ──────────────────────────────────────────────────────────────

class TestFeatureFlags:
    def setup_method(self):
        os.environ["OPERATIONS_CENTER_ENABLED"] = "true"

    def teardown_method(self):
        os.environ.pop("OPERATIONS_CENTER_ENABLED", None)

    def test_flags_keys(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import get_feature_flags
            result = get_feature_flags()
        for k in ("flags", "enabled", "disabled", "total", "read_only"):
            assert k in result

    def test_flags_read_only(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import get_feature_flags
            result = get_feature_flags()
        assert result["read_only"] is True

    def test_flags_contains_operations_flag(self):
        os.environ["OPERATIONS_CENTER_ENABLED"] = "true"
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import get_feature_flags
            result = get_feature_flags()
        names = [f["name"] for f in result["flags"]]
        assert "OPERATIONS_CENTER_ENABLED" in names

    def test_flags_enabled_list_matches_env(self):
        os.environ["OPERATIONS_CENTER_ENABLED"] = "true"
        os.environ["DATA_QUALITY_ENABLED"] = "true"
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import get_feature_flags
            result = get_feature_flags()
        enabled_names = [f["name"] for f in result["enabled"]]
        assert "OPERATIONS_CENTER_ENABLED" in enabled_names
        os.environ.pop("DATA_QUALITY_ENABLED", None)

    def test_flags_each_has_required_fields(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import get_feature_flags
            result = get_feature_flags()
        for flag in result["flags"]:
            for field in ("name", "category", "description", "enabled"):
                assert field in flag


# ── Export ─────────────────────────────────────────────────────────────────────

class TestExport:
    def setup_method(self):
        os.environ["OPERATIONS_CENTER_ENABLED"] = "true"

    def teardown_method(self):
        os.environ.pop("OPERATIONS_CENTER_ENABLED", None)

    def test_export_json_keys(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import export_json
            result = export_json()
        for k in ("summary", "market", "risk", "data_quality", "observability",
                   "feature_flags", "jobs", "alerts", "checklist", "timeline", "exported_at"):
            assert k in result

    def test_export_json_advisory_only(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import export_json
            result = export_json()
        assert result["advisory_only"] is True

    def test_export_csv_has_csv_key(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import export_csv
            result = export_csv()
        assert "csv" in result
        assert "operations_score" in result["csv"]
        assert "generated_at" in result["csv"]

    def test_export_csv_is_valid_csv(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.shared_services import export_csv
            result = export_csv()
        lines = result["csv"].strip().split("\n")
        assert lines[0] == "metric,value"
        assert len(lines) > 5


# ── API command wrappers ───────────────────────────────────────────────────────

class TestApiCommands:
    def setup_method(self):
        os.environ["OPERATIONS_CENTER_ENABLED"] = "true"

    def teardown_method(self):
        os.environ.pop("OPERATIONS_CENTER_ENABLED", None)

    def test_all_commands_return_dicts(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.api import (
                cmd_summary, cmd_market, cmd_risk, cmd_paper,
                cmd_data_quality, cmd_observability, cmd_flags,
                cmd_jobs, cmd_alerts, cmd_checklist, cmd_timeline,
                cmd_snapshot, cmd_export_json, cmd_export_csv,
            )
            for fn in [cmd_summary, cmd_market, cmd_risk, cmd_paper,
                       cmd_data_quality, cmd_observability, cmd_flags,
                       cmd_jobs, cmd_alerts, cmd_checklist, cmd_timeline,
                       cmd_snapshot, cmd_export_json, cmd_export_csv]:
                result = fn()
                assert isinstance(result, dict), f"{fn.__name__} should return dict"

    def test_cmd_snapshot_available(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from operations_center.api import cmd_snapshot
            result = cmd_snapshot()
        assert result["available"] is True


# ── Grade / trend helpers ──────────────────────────────────────────────────────

class TestGradeHelpers:
    def test_grade_a_plus(self):
        from operations_center.models import ops_grade
        assert ops_grade(95) == "A+"

    def test_grade_a(self):
        from operations_center.models import ops_grade
        assert ops_grade(85) == "A"

    def test_grade_b(self):
        from operations_center.models import ops_grade
        assert ops_grade(70) == "B"

    def test_grade_c(self):
        from operations_center.models import ops_grade
        assert ops_grade(55) == "C"

    def test_grade_d(self):
        from operations_center.models import ops_grade
        assert ops_grade(40) == "D"

    def test_trend_improving(self):
        from operations_center.models import trend_label
        assert trend_label(85, 80) == "IMPROVING"

    def test_trend_degrading(self):
        from operations_center.models import trend_label
        assert trend_label(75, 80) == "DEGRADING"

    def test_trend_stable(self):
        from operations_center.models import trend_label
        assert trend_label(80, 80) == "STABLE"


# ── Checklist phase helper ─────────────────────────────────────────────────────

class TestChecklistPhase:
    def test_known_flags_count(self):
        from operations_center.models import KNOWN_FLAGS
        assert len(KNOWN_FLAGS) >= 15

    def test_known_flags_structure(self):
        from operations_center.models import KNOWN_FLAGS
        for flag in KNOWN_FLAGS:
            assert "name" in flag
            assert "category" in flag
            assert "description" in flag
