"""
test_command_center.py — Phase 9.1
Tests for the Unified Command Centre.

READ-ONLY. ADVISORY-ONLY.
All upstream dependencies are mocked — zero real I/O.
"""
import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# ── helpers ────────────────────────────────────────────────────────────────────
def _enable():
    os.environ["COMMAND_CENTER_ENABLED"] = "true"

def _disable():
    os.environ.pop("COMMAND_CENTER_ENABLED", None)

# ── stub returns ──────────────────────────────────────────────────────────────
def _market_snap():
    return {
        "available": True, "market_health_score": 72.0, "grade": "B",
        "trend": "IMPROVING", "overall_outlook": "Moderately bullish.",
        "top_opportunity": "RELIANCE",
    }

def _market_overview():
    return {
        "available": True,
        "regime": {
            "regime": "MODERATELY_BULLISH", "sub_regime": "NORMAL",
            "trend_strength": 0.65, "nifty_trend": "UPTREND",
            "banknifty_trend": "UPTREND", "vix_value": 14.2,
            "vix_status": "LOW", "high_volatility": False,
            "nifty_price": 22500.0, "nifty_change_pct": 0.8,
            "banknifty_price": 48000.0, "banknifty_change_pct": 1.1,
        },
        "breadth": {"advancing": 320, "declining": 150, "neutral": 30, "bullish": 318, "bearish": 145},
        "sectors": {
            "strongest_sector": "BANKING", "weakest_sector": "IT",
            "sectors": [{"name": "BANKING", "strength": 80}, {"name": "IT", "strength": 40}],
        },
        "watchlist": {
            "watchlist": [], "top_opportunities": [], "total_symbols": 50,
        },
        "top_gainers": [{"symbol": "RELIANCE", "change_pct": 3.2}],
        "top_losers":  [{"symbol": "INFY", "change_pct": -1.8}],
        "top_volume":  [{"symbol": "TCS", "volume": 1000000}],
    }

def _paper_snap():
    return {
        "available": True, "total_trades": 12, "win_rate": 66.7,
        "profit_factor": 1.8, "expectancy": 250.0, "total_pnl": 3000.0,
        "max_drawdown": 800.0, "sharpe_ratio": 1.4, "best_strategy": "MACD",
        "best_sector": "BANKING", "avg_hold_seconds": 3600.0,
        "analytics_score": 75.0, "grade": "B",
    }

def _executive_snap():
    return {
        "status": "ENABLED", "portfolio_value": 100000.0, "net_pnl": 3000.0,
        "win_rate": 66.7, "open_positions": 3, "execution_score": 82.0,
        "executive_score": 78.0, "executive_label": "Good",
    }

def _ai_snap():
    return {
        "status": "ENABLED", "health_score": 79.5, "health_label": "Good",
        "prediction_accuracy": 68.3, "avg_confidence": 71.2,
        "calibration_quality_label": "GOOD", "trend_direction": "Improving",
        "accuracy_delta": 2.1, "total_signals": 45, "f1_score": 0.71,
        "precision": 72.0, "recall": 69.0,
    }

def _risk_snap():
    return {
        "status": "ENABLED", "advisory_only": True,
        "risk_score": 68.0, "grade": "B",
        "domains": {
            "portfolio":   {"score": 70.0}, "tail_risk": {"score": 65.0},
            "sector":      {"score": 72.0}, "correlation": {"score": 68.0},
        },
    }

def _dq_snap():
    return {
        "available": True, "advisory_only": True,
        "quality_score": 82.0, "grade": "A",
        "critical_count": 0, "warning_count": 2,
    }

def _obs_snap():
    return {
        "available": True, "observability_score": 80.0, "grade": "A",
    }

def _ops_snap():
    return {
        "available": True, "operations_score": 75.0, "grade": "B",
        "critical_alerts": 0,
    }

def _sec_snap():
    return {
        "available": True, "security_score": 78.0, "grade": "B",
        "missing_secrets": 0, "weak_secrets": 0,
    }

def _perf_snap():
    return {
        "available": True, "performance_score": 72.0, "grade": "B",
    }

def _deploy_snap():
    return {
        "available": True, "dr_score": 68.0, "grade": "B",
    }

def _sched_health():
    return {"status": "RUNNING", "available": True}

def _notifications(n=3):
    from datetime import datetime, timezone, timedelta
    return [
        {
            "id": i, "kind": "info", "title": f"Event {i}",
            "body": f"Body {i}", "read": False,
            "created_at": (datetime.now(timezone.utc) - timedelta(minutes=i*10)).isoformat(),
        }
        for i in range(n)
    ]

def _scan_runs(n=5):
    from datetime import datetime, timezone, timedelta
    return [
        {
            "scan_id": f"scan_{i}",
            "snapshot_ts": (datetime.now(timezone.utc) - timedelta(hours=i*2)).isoformat(),
            "status": "completed",
        }
        for i in range(n)
    ]

ALL_PATCHES = [
    ("command_center.shared_services._load_market_snapshot",    _market_snap),
    ("command_center.shared_services._load_market_overview",    _market_overview),
    ("command_center.shared_services._load_paper_analytics",    _paper_snap),
    ("command_center.shared_services._load_executive",          _executive_snap),
    ("command_center.shared_services._load_ai_snapshot",        _ai_snap),
    ("command_center.shared_services._load_risk_snapshot",      _risk_snap),
    ("command_center.shared_services._load_data_quality",       _dq_snap),
    ("command_center.shared_services._load_observability",      _obs_snap),
    ("command_center.shared_services._load_operations",         _ops_snap),
    ("command_center.shared_services._load_security",           _sec_snap),
    ("command_center.shared_services._load_performance",        _perf_snap),
    ("command_center.shared_services._load_deployment",         _deploy_snap),
    ("command_center.shared_services._load_scheduler_health",   _sched_health),
    ("command_center.shared_services._load_notifications",      _notifications),
    ("command_center.shared_services._load_scan_runs",          _scan_runs),
]

def _apply_patches(tc):
    active = [patch(path, return_value=fn()) for path, fn in ALL_PATCHES]
    mocks  = [p.start() for p in active]
    tc.addCleanup(lambda: [p.stop() for p in active])
    return mocks


# ── Feature flag ───────────────────────────────────────────────────────────────
class TestFeatureFlag(unittest.TestCase):
    def tearDown(self):
        _disable()

    def test_disabled_by_default(self):
        _disable()
        from command_center.models import is_enabled
        self.assertFalse(is_enabled())

    def test_enabled_true(self):
        os.environ["COMMAND_CENTER_ENABLED"] = "true"
        from command_center.models import is_enabled
        self.assertTrue(is_enabled())

    def test_enabled_1(self):
        os.environ["COMMAND_CENTER_ENABLED"] = "1"
        from command_center.models import is_enabled
        self.assertTrue(is_enabled())

    def test_enabled_yes(self):
        os.environ["COMMAND_CENTER_ENABLED"] = "yes"
        from command_center.models import is_enabled
        self.assertTrue(is_enabled())

    def test_disabled_response_shape(self):
        _disable()
        from command_center.models import disabled_response
        r = disabled_response()
        self.assertFalse(r["available"])
        self.assertTrue(r["advisory_only"])
        self.assertTrue(r["read_only"])
        self.assertIn("COMMAND_CENTER_ENABLED", r["message"])


# ── Grade / status helpers ─────────────────────────────────────────────────────
class TestGradeHelpers(unittest.TestCase):
    def test_grade_a_plus(self):
        from command_center.models import platform_grade
        self.assertEqual(platform_grade(92), "A+")

    def test_grade_a(self):
        from command_center.models import platform_grade
        self.assertEqual(platform_grade(80), "A")

    def test_grade_b(self):
        from command_center.models import platform_grade
        self.assertEqual(platform_grade(70), "B")

    def test_grade_c(self):
        from command_center.models import platform_grade
        self.assertEqual(platform_grade(55), "C")

    def test_grade_d(self):
        from command_center.models import platform_grade
        self.assertEqual(platform_grade(30), "D")

    def test_status_healthy(self):
        from command_center.models import platform_status
        self.assertEqual(platform_status(85), "HEALTHY")

    def test_status_degraded(self):
        from command_center.models import platform_status
        self.assertEqual(platform_status(65), "DEGRADED")

    def test_status_critical(self):
        from command_center.models import platform_status
        self.assertEqual(platform_status(40), "CRITICAL")


# ── Platform score formula ─────────────────────────────────────────────────────
class TestPlatformScoreFormula(unittest.TestCase):
    def test_weights_sum_to_1(self):
        weights = [0.20, 0.20, 0.20, 0.15, 0.15, 0.10]
        self.assertAlmostEqual(sum(weights), 1.0, places=10)

    def test_all_100_gives_100(self):
        from command_center.shared_services import _compute_platform_score
        full = {"observability_score": 100.0, "operations_score": 100.0,
                "quality_score": 100.0, "security_score": 100.0,
                "performance_score": 100.0, "dr_score": 100.0,
                "available": True, "grade": "A+"}
        self.assertEqual(_compute_platform_score(full, full, full, full, full, full), 100.0)

    def test_all_0_gives_0(self):
        from command_center.shared_services import _compute_platform_score
        empty = {}
        self.assertEqual(_compute_platform_score(empty, empty, empty, empty, empty, empty), 0.0)

    def test_mixed_score_in_range(self):
        from command_center.shared_services import _compute_platform_score
        obs   = {"observability_score": 80.0}
        ops   = {"operations_score": 75.0}
        dq    = {"quality_score": 82.0}
        sec   = {"security_score": 78.0}
        perf  = {"performance_score": 72.0}
        deploy= {"dr_score": 68.0}
        score = _compute_platform_score(obs, ops, dq, sec, perf, deploy)
        self.assertGreater(score, 0)
        self.assertLessEqual(score, 100)


# ── Summary ────────────────────────────────────────────────────────────────────
class TestSummary(unittest.TestCase):
    def setUp(self):
        _enable()
        _apply_patches(self)

    def test_returns_dict(self):
        from command_center.shared_services import get_summary
        r = get_summary()
        self.assertIsInstance(r, dict)

    def test_advisory_flags(self):
        from command_center.shared_services import get_summary
        r = get_summary()
        self.assertTrue(r.get("advisory_only"))
        self.assertTrue(r.get("read_only"))
        self.assertTrue(r.get("available"))

    def test_has_platform_score(self):
        from command_center.shared_services import get_summary
        r = get_summary()
        self.assertIn("platform_score", r)
        self.assertGreaterEqual(r["platform_score"], 0)
        self.assertLessEqual(r["platform_score"], 100)

    def test_has_market_section(self):
        from command_center.shared_services import get_summary
        r = get_summary()
        self.assertIn("market", r)
        m = r["market"]
        self.assertIn("regime", m)
        self.assertIn("nifty50", m)
        self.assertIn("bank_nifty", m)

    def test_has_portfolio_section(self):
        from command_center.shared_services import get_summary
        r = get_summary()
        self.assertIn("portfolio", r)
        p = r["portfolio"]
        self.assertIn("portfolio_value", p)
        self.assertIn("win_rate", p)

    def test_has_trading_section(self):
        from command_center.shared_services import get_summary
        r = get_summary()
        self.assertIn("trading", r)
        t = r["trading"]
        self.assertIn("total_trades", t)
        self.assertEqual(t["execution_mode"], "PAPER_TRADING")

    def test_has_ai_section(self):
        from command_center.shared_services import get_summary
        r = get_summary()
        self.assertIn("ai", r)
        self.assertIn("health_score", r["ai"])

    def test_has_risk_section(self):
        from command_center.shared_services import get_summary
        r = get_summary()
        self.assertIn("risk", r)
        self.assertIn("risk_score", r["risk"])

    def test_has_system_health_section(self):
        from command_center.shared_services import get_summary
        r = get_summary()
        self.assertIn("system_health", r)
        sh = r["system_health"]
        self.assertIn("platform_score", sh)
        self.assertIn("modules", sh)
        self.assertIsInstance(sh["modules"], list)
        self.assertGreater(len(sh["modules"]), 0)

    def test_has_watchlist_section(self):
        from command_center.shared_services import get_summary
        r = get_summary()
        self.assertIn("watchlist", r)

    def test_has_quick_actions(self):
        from command_center.shared_services import get_summary
        r = get_summary()
        self.assertIn("quick_actions", r)
        self.assertIsInstance(r["quick_actions"], list)
        self.assertGreater(len(r["quick_actions"]), 0)

    def test_has_market_intelligence_section(self):
        from command_center.shared_services import get_summary
        r = get_summary()
        self.assertIn("market_intelligence", r)

    def test_disabled_when_flag_off(self):
        _disable()
        from command_center.shared_services import get_summary
        r = get_summary()
        self.assertFalse(r["available"])

    def test_system_health_has_six_modules(self):
        from command_center.shared_services import get_summary
        r = get_summary()
        modules = r["system_health"]["modules"]
        self.assertEqual(len(modules), 6)

    def test_market_section_breadth(self):
        from command_center.shared_services import get_summary
        r = get_summary()
        m = r["market"]
        self.assertIn("advance", m)
        self.assertIn("decline", m)
        self.assertEqual(m["advance"], 320)
        self.assertEqual(m["decline"], 150)

    def test_portfolio_value_from_executive(self):
        from command_center.shared_services import get_summary
        r = get_summary()
        self.assertEqual(r["portfolio"]["portfolio_value"], 100000.0)


# ── Briefing ───────────────────────────────────────────────────────────────────
class TestBriefing(unittest.TestCase):
    def setUp(self):
        _enable()
        _apply_patches(self)

    def test_returns_dict(self):
        from command_center.shared_services import get_briefing
        r = get_briefing()
        self.assertIsInstance(r, dict)

    def test_advisory_flags(self):
        from command_center.shared_services import get_briefing
        r = get_briefing()
        self.assertTrue(r.get("advisory_only"))
        self.assertTrue(r.get("read_only"))

    def test_has_title(self):
        from command_center.shared_services import get_briefing
        r = get_briefing()
        self.assertIn("title", r)

    def test_has_briefing_lines(self):
        from command_center.shared_services import get_briefing
        r = get_briefing()
        self.assertIn("briefing_lines", r)
        self.assertIsInstance(r["briefing_lines"], list)
        self.assertGreater(len(r["briefing_lines"]), 0)

    def test_has_briefing_text(self):
        from command_center.shared_services import get_briefing
        r = get_briefing()
        self.assertIn("briefing_text", r)
        self.assertIsInstance(r["briefing_text"], str)
        self.assertGreater(len(r["briefing_text"]), 0)

    def test_has_market_regime(self):
        from command_center.shared_services import get_briefing
        r = get_briefing()
        self.assertIn("market_regime", r)

    def test_has_risk_grade(self):
        from command_center.shared_services import get_briefing
        r = get_briefing()
        self.assertIn("risk_grade", r)
        self.assertIn(r["risk_grade"], ["A+", "A", "B", "C", "D"])

    def test_briefing_text_contains_market_info(self):
        from command_center.shared_services import get_briefing
        r = get_briefing()
        text = r["briefing_text"].lower()
        self.assertTrue(any(word in text for word in ["market", "bullish", "bearish", "sideways", "volatile"]))

    def test_disabled_when_flag_off(self):
        _disable()
        from command_center.shared_services import get_briefing
        r = get_briefing()
        self.assertFalse(r["available"])

    def test_has_total_signals(self):
        from command_center.shared_services import get_briefing
        r = get_briefing()
        self.assertIn("total_signals", r)
        self.assertEqual(r["total_signals"], 45)


# ── Alerts ─────────────────────────────────────────────────────────────────────
class TestAlerts(unittest.TestCase):
    def setUp(self):
        _enable()
        _apply_patches(self)

    def test_returns_dict(self):
        from command_center.shared_services import get_alerts
        r = get_alerts()
        self.assertIsInstance(r, dict)

    def test_advisory_flags(self):
        from command_center.shared_services import get_alerts
        r = get_alerts()
        self.assertTrue(r.get("advisory_only"))
        self.assertTrue(r.get("read_only"))

    def test_has_alerts_list(self):
        from command_center.shared_services import get_alerts
        r = get_alerts()
        self.assertIn("alerts", r)
        self.assertIsInstance(r["alerts"], list)

    def test_has_counts(self):
        from command_center.shared_services import get_alerts
        r = get_alerts()
        self.assertIn("alert_count", r)
        self.assertIn("critical_count", r)
        self.assertIn("warning_count", r)
        self.assertIn("info_count", r)

    def test_alerts_have_required_fields(self):
        from command_center.shared_services import get_alerts
        r = get_alerts()
        for alert in r["alerts"]:
            self.assertIn("severity", alert)
            self.assertIn("category", alert)
            self.assertIn("title", alert)

    def test_critical_alerts_appear_first(self):
        from command_center.shared_services import get_alerts
        with patch("command_center.shared_services._load_security",
                   return_value={**_sec_snap(), "missing_secrets": 1}):
            r = get_alerts()
            if r["critical_count"] > 0 and len(r["alerts"]) > 1:
                first_sev = r["alerts"][0]["severity"]
                self.assertEqual(first_sev, "CRITICAL")

    def test_low_risk_generates_critical_alert(self):
        with patch("command_center.shared_services._load_risk_snapshot",
                   return_value={**_risk_snap(), "risk_score": 30.0}):
            from command_center.shared_services import get_alerts
            r = get_alerts()
            risk_alerts = [a for a in r["alerts"] if a["category"] == "Risk"]
            critical    = [a for a in risk_alerts if a["severity"] == "CRITICAL"]
            self.assertGreater(len(critical), 0)

    def test_missing_secrets_generates_critical_alert(self):
        with patch("command_center.shared_services._load_security",
                   return_value={**_sec_snap(), "missing_secrets": 2}):
            from command_center.shared_services import get_alerts
            r = get_alerts()
            sec_alerts = [a for a in r["alerts"] if a["category"] == "Security"]
            self.assertGreater(len(sec_alerts), 0)

    def test_disabled_when_flag_off(self):
        _disable()
        from command_center.shared_services import get_alerts
        r = get_alerts()
        self.assertFalse(r["available"])


# ── Timeline ───────────────────────────────────────────────────────────────────
class TestTimeline(unittest.TestCase):
    def setUp(self):
        _enable()
        _apply_patches(self)

    def test_returns_dict(self):
        from command_center.shared_services import get_timeline
        r = get_timeline()
        self.assertIsInstance(r, dict)

    def test_advisory_flags(self):
        from command_center.shared_services import get_timeline
        r = get_timeline()
        self.assertTrue(r.get("advisory_only"))
        self.assertTrue(r.get("read_only"))

    def test_has_events_list(self):
        from command_center.shared_services import get_timeline
        r = get_timeline()
        self.assertIn("events", r)
        self.assertIsInstance(r["events"], list)

    def test_has_event_count(self):
        from command_center.shared_services import get_timeline
        r = get_timeline()
        self.assertIn("event_count", r)
        self.assertGreater(r["event_count"], 0)

    def test_events_have_required_fields(self):
        from command_center.shared_services import get_timeline
        r = get_timeline()
        for ev in r["events"]:
            self.assertIn("time", ev)
            self.assertIn("event", ev)
            self.assertIn("category", ev)
            self.assertIn("status", ev)

    def test_scan_run_events_included(self):
        from command_center.shared_services import get_timeline
        r = get_timeline()
        scan_events = [e for e in r["events"] if e["category"] == "Scan"]
        self.assertGreater(len(scan_events), 0)

    def test_scheduler_event_included(self):
        from command_center.shared_services import get_timeline
        r = get_timeline()
        sys_events = [e for e in r["events"] if e["category"] == "System"]
        self.assertGreater(len(sys_events), 0)

    def test_events_sorted_descending(self):
        from command_center.shared_services import get_timeline
        r = get_timeline()
        events = r["events"]
        for i in range(len(events) - 1):
            if events[i].get("ts_iso") and events[i+1].get("ts_iso"):
                self.assertGreaterEqual(events[i]["ts_iso"], events[i+1]["ts_iso"])

    def test_disabled_when_flag_off(self):
        _disable()
        from command_center.shared_services import get_timeline
        r = get_timeline()
        self.assertFalse(r["available"])


# ── Snapshot ───────────────────────────────────────────────────────────────────
class TestSnapshot(unittest.TestCase):
    def setUp(self):
        _enable()
        _apply_patches(self)

    def test_returns_dict(self):
        from command_center.shared_services import get_command_center_snapshot
        r = get_command_center_snapshot()
        self.assertIsInstance(r, dict)

    def test_advisory_flags(self):
        from command_center.shared_services import get_command_center_snapshot
        r = get_command_center_snapshot()
        self.assertTrue(r.get("advisory_only"))
        self.assertTrue(r.get("read_only"))

    def test_has_platform_score(self):
        from command_center.shared_services import get_command_center_snapshot
        r = get_command_center_snapshot()
        self.assertIn("platform_score", r)

    def test_disabled_returns_unavailable(self):
        _disable()
        from command_center.shared_services import get_command_center_snapshot
        r = get_command_center_snapshot()
        self.assertFalse(r["available"])


# ── Export ─────────────────────────────────────────────────────────────────────
class TestExport(unittest.TestCase):
    def setUp(self):
        _enable()
        _apply_patches(self)

    def test_export_json_returns_dict(self):
        from command_center.shared_services import export_json
        r = export_json()
        self.assertIsInstance(r, dict)
        self.assertTrue(r.get("advisory_only"))
        self.assertTrue(r.get("read_only"))

    def test_export_json_has_sections(self):
        from command_center.shared_services import export_json
        r = export_json()
        for key in ["summary", "briefing", "alerts", "timeline"]:
            self.assertIn(key, r)

    def test_export_csv_returns_dict(self):
        from command_center.shared_services import export_csv
        r = export_csv()
        self.assertIsInstance(r, dict)
        self.assertIn("csv", r)
        self.assertGreater(r.get("row_count", 0), 0)

    def test_export_csv_is_parseable(self):
        import csv as csv_mod, io
        from command_center.shared_services import export_csv
        r = export_csv()
        rows = list(csv_mod.reader(io.StringIO(r["csv"])))
        self.assertGreater(len(rows), 1)
        self.assertEqual(rows[0][0], "section")

    def test_export_json_disabled(self):
        _disable()
        from command_center.shared_services import export_json
        r = export_json()
        self.assertFalse(r["available"])

    def test_export_csv_disabled(self):
        _disable()
        from command_center.shared_services import export_csv
        r = export_csv()
        self.assertFalse(r["available"])


# ── API command layer ──────────────────────────────────────────────────────────
class TestApiCommands(unittest.TestCase):
    def setUp(self):
        _enable()
        _apply_patches(self)

    def test_cmd_summary(self):
        from command_center.api import cmd_summary
        r = cmd_summary()
        self.assertIn("platform_score", r)

    def test_cmd_briefing(self):
        from command_center.api import cmd_briefing
        r = cmd_briefing()
        self.assertIn("briefing_text", r)

    def test_cmd_alerts(self):
        from command_center.api import cmd_alerts
        r = cmd_alerts()
        self.assertIn("alerts", r)

    def test_cmd_timeline(self):
        from command_center.api import cmd_timeline
        r = cmd_timeline()
        self.assertIn("events", r)

    def test_cmd_snapshot(self):
        from command_center.api import cmd_snapshot
        r = cmd_snapshot()
        self.assertIn("platform_score", r)

    def test_cmd_export_json(self):
        from command_center.api import cmd_export_json
        r = cmd_export_json()
        self.assertIn("summary", r)

    def test_cmd_export_csv(self):
        from command_center.api import cmd_export_csv
        r = cmd_export_csv()
        self.assertIn("csv", r)


# ── Read-only / advisory-only guarantee ───────────────────────────────────────
class TestReadOnlyGuarantee(unittest.TestCase):
    def setUp(self):
        _enable()
        _apply_patches(self)

    def test_no_sql_writes_in_source(self):
        import inspect
        from command_center import shared_services
        src = inspect.getsource(shared_services)
        self.assertNotIn("DELETE FROM", src.upper())
        self.assertNotIn("INSERT INTO", src.upper())
        self.assertNotIn("DROP TABLE",  src.upper())
        self.assertNotIn("os.remove(",  src)

    def test_all_responses_have_advisory_flags(self):
        from command_center.shared_services import (
            get_summary, get_briefing, get_alerts, get_timeline,
            get_command_center_snapshot,
        )
        for fn in [get_summary, get_briefing, get_alerts, get_timeline,
                   get_command_center_snapshot]:
            r = fn()
            self.assertTrue(r.get("advisory_only"), f"{fn.__name__} missing advisory_only=True")
            self.assertTrue(r.get("read_only"),      f"{fn.__name__} missing read_only=True")

    def test_execution_mode_is_paper(self):
        from command_center.shared_services import get_summary
        r = get_summary()
        self.assertEqual(r.get("execution_mode"), "PAPER_TRADING")


if __name__ == "__main__":
    unittest.main(verbosity=2)
