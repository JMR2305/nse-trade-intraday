"""Phase 26C unit tests — recovery grading, performance thresholds, and
trading-quality metrics. All inputs injected fixtures; no DB, no network."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

os.environ.pop("DATABASE_URL", None)   # force file fallbacks everywhere

import phase26c_store as store                              # noqa: E402
import phase26_live_store as live_store                     # noqa: E402
from phase26_recovery import (build_recovery_report,        # noqa: E402
                              run_recovery_validation)
from phase26_performance import (build_performance_report,  # noqa: E402
                                 THRESHOLDS)
from phase26_quality import (build_quality_report,          # noqa: E402
                             run_quality_validation, MIN_EVIDENCE)

NOW = datetime(2026, 8, 7, 6, 0, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.isoformat()


def grades(report, key="scenarios", name_key="scenario"):
    return {s[name_key]: s["grade"] for s in report[key]}


# ── Recovery fixtures ─────────────────────────────────────────────────────────

def healthy_recovery_inputs(**over):
    scan_ts = iso(NOW - timedelta(minutes=3))
    inp = {
        "db_durable": True,
        "market_state": "OPEN",
        "scan_meta": {"scan_id": "scan-1", "status": "SUCCESS",
                      "error": None, "snapshot_ts": scan_ts},
        "snapshot": {"scan_id": "scan-1", "snapshot_ts": scan_ts,
                     "provider": "zerodha_kite",
                     "symbols_requested": 15, "symbols_succeeded": 15},
        "portfolio": {"cash": 40_000.0, "equity": 50_000.0,
                      "positions": [{"symbol": "INFY", "quantity": 10,
                                     "current_value": 10_000.0}]},
        "ledger_open_rows": [{"symbol": "INFY", "status": "OPEN"}],
        "broker": {"connection_state": "CONNECTED",
                   "token_status": "VALID", "probe_source": "live"},
        "scheduler": {"heartbeat_at": iso(NOW - timedelta(seconds=45)),
                      "status": "OK", "owner": "host:1"},
        "scan_runs": [
            {"status": "SUCCESS", "scan_id": "scan-1",
             "completed_at": scan_ts, "duration_s": 45.0},
            {"status": "FAILED", "scan_id": None,
             "completed_at": iso(NOW - timedelta(minutes=20))},
        ],
    }
    inp.update(over)
    return inp


class TestRecoveryGrading(unittest.TestCase):
    def test_healthy_state_all_pass(self):
        rep = build_recovery_report(healthy_recovery_inputs(), now=NOW)
        g = grades(rep)
        self.assertEqual(rep["verdict"], "PASS", g)
        self.assertTrue(all(v == "PASS" for v in g.values()), g)
        self.assertTrue(rep["fully_evaluated"])

    def test_meta_snapshot_scan_id_mismatch_fails_api_restart(self):
        rep = build_recovery_report(healthy_recovery_inputs(
            scan_meta={"scan_id": "scan-0", "status": "SUCCESS",
                       "error": None}), now=NOW)
        self.assertEqual(grades(rep)["api_restart"], "FAIL")
        self.assertEqual(rep["verdict"], "FAIL")

    def test_file_only_snapshot_is_warn_not_pass(self):
        rep = build_recovery_report(healthy_recovery_inputs(
            db_durable=False), now=NOW)
        self.assertEqual(grades(rep)["api_restart"], "WARN")

    def test_failed_scan_with_lost_snapshot_breaks_invariant(self):
        rep = build_recovery_report(healthy_recovery_inputs(
            scan_meta={"scan_id": "scan-1", "status": "FAILED",
                       "error": "boom"},
            snapshot=None), now=NOW)
        g = grades(rep)
        self.assertEqual(g["database_restart"], "FAIL")

    def test_first_run_failed_scan_no_snapshot_is_warn(self):
        rep = build_recovery_report(healthy_recovery_inputs(
            scan_meta={"scan_id": None, "status": "FAILED", "error": "boom"},
            snapshot=None), now=NOW)
        self.assertEqual(grades(rep)["database_restart"], "WARN")

    def test_portfolio_equity_mismatch_fails(self):
        rep = build_recovery_report(healthy_recovery_inputs(
            portfolio={"cash": 40_000.0, "equity": 60_000.0,
                       "positions": [{"symbol": "INFY", "quantity": 10,
                                      "current_value": 10_000.0}]}), now=NOW)
        self.assertEqual(grades(rep)["portfolio_recovery"], "FAIL")

    def test_ledger_position_symbol_mismatch_fails(self):
        rep = build_recovery_report(healthy_recovery_inputs(
            ledger_open_rows=[{"symbol": "TCS", "status": "OPEN"}]), now=NOW)
        self.assertEqual(grades(rep)["portfolio_recovery"], "FAIL")

    def test_broker_states(self):
        for state, expected in (("CONNECTED", "PASS"),
                                ("LOGIN_REQUIRED", "WARN"),
                                ("TOKEN_EXPIRED", "WARN"),
                                ("API_ERROR", "FAIL"),
                                ("AUTH_FAILED", "FAIL")):
            rep = build_recovery_report(healthy_recovery_inputs(
                broker={"connection_state": state}), now=NOW)
            self.assertEqual(grades(rep)["broker_reconnect"], expected, state)

    def test_fault_without_later_success_is_warn(self):
        rep = build_recovery_report(healthy_recovery_inputs(
            scan_runs=[{"status": "FAILED", "scan_id": None,
                        "completed_at": iso(NOW - timedelta(minutes=2))}]),
            now=NOW)
        self.assertEqual(grades(rep)["network_interruption"], "WARN")

    def test_fault_followed_by_success_is_pass(self):
        rep = build_recovery_report(healthy_recovery_inputs(scan_runs=[
            {"status": "SUCCESS", "scan_id": "scan-2",
             "completed_at": iso(NOW - timedelta(minutes=1))},
            {"status": "FAILED", "scan_id": None,
             "completed_at": iso(NOW - timedelta(minutes=6))},
        ]), now=NOW)
        self.assertEqual(grades(rep)["network_interruption"], "PASS")

    def test_skipped_concurrency_outcome_is_not_a_fault(self):
        rep = build_recovery_report(healthy_recovery_inputs(scan_runs=[
            {"status": "SKIPPED_ACTIVE_SCAN", "scan_id": None,
             "completed_at": iso(NOW - timedelta(minutes=2))},
        ]), now=NOW)
        self.assertEqual(grades(rep)["network_interruption"], "PASS")

    def test_exit_pending_position_matches_ledger(self):
        rep = build_recovery_report(healthy_recovery_inputs(
            portfolio={"cash": 40_000.0, "equity": 50_000.0,
                       "positions": [{"symbol": "INFY", "quantity": 10,
                                      "market_value": 10_000.0}]},
            ledger_open_rows=[{"symbol": "INFY",
                               "status": "EXIT_PENDING"}]), now=NOW)
        self.assertEqual(grades(rep)["portfolio_recovery"], "PASS")

    def test_stuck_scan_lock_fails_database_restart(self):
        rep = build_recovery_report(healthy_recovery_inputs(
            scheduler={"heartbeat_at": iso(NOW - timedelta(seconds=45)),
                       "lock": {"holder": "host:1",
                                "acquired_at": iso(NOW - timedelta(hours=1)),
                                "expires_at": iso(NOW + timedelta(minutes=2))
                                }}), now=NOW)
        self.assertEqual(grades(rep)["database_restart"], "FAIL")

    def test_expired_lease_still_present_is_warn(self):
        rep = build_recovery_report(healthy_recovery_inputs(
            scheduler={"heartbeat_at": iso(NOW - timedelta(seconds=45)),
                       "lock": {"holder": "host:1",
                                "acquired_at": iso(NOW - timedelta(minutes=6)),
                                "expires_at": iso(NOW - timedelta(minutes=1))
                                }}), now=NOW)
        self.assertEqual(grades(rep)["database_restart"], "WARN")

    def test_fresh_held_lock_passes(self):
        rep = build_recovery_report(healthy_recovery_inputs(
            scheduler={"heartbeat_at": iso(NOW - timedelta(seconds=45)),
                       "lock": {"holder": "host:1",
                                "acquired_at": iso(NOW - timedelta(minutes=1)),
                                "expires_at": iso(NOW + timedelta(minutes=4))
                                }}), now=NOW)
        self.assertEqual(grades(rep)["database_restart"], "PASS")

    def test_zero_symbols_fails_provider_failover(self):
        rep = build_recovery_report(healthy_recovery_inputs(
            snapshot={"scan_id": "scan-1", "snapshot_ts": iso(NOW),
                      "provider": "yahoo", "symbols_requested": 15,
                      "symbols_succeeded": 0}), now=NOW)
        self.assertEqual(grades(rep)["provider_failover"], "FAIL")

    def test_partial_coverage_is_warn(self):
        rep = build_recovery_report(healthy_recovery_inputs(
            snapshot={"scan_id": "scan-1", "snapshot_ts": iso(NOW),
                      "provider": "yahoo", "symbols_requested": 15,
                      "symbols_succeeded": 10}), now=NOW)
        self.assertEqual(grades(rep)["provider_failover"], "WARN")

    def test_stale_heartbeat_in_session_fails_worker_restart(self):
        rep = build_recovery_report(healthy_recovery_inputs(
            scheduler={"heartbeat_at": iso(NOW - timedelta(minutes=20)),
                       "status": "OK"}), now=NOW)
        self.assertEqual(grades(rep)["worker_restart"], "FAIL")

    def test_stale_heartbeat_off_session_passes(self):
        rep = build_recovery_report(healthy_recovery_inputs(
            market_state="WEEKEND",
            scheduler={"heartbeat_at": iso(NOW - timedelta(hours=30)),
                       "status": "IDLE"}), now=NOW)
        self.assertEqual(grades(rep)["worker_restart"], "PASS")

    def test_unavailable_source_is_insufficient_never_fail(self):
        rep = build_recovery_report(healthy_recovery_inputs(
            broker=None, scheduler=None), now=NOW)
        g = grades(rep)
        self.assertEqual(g["broker_reconnect"], "INSUFFICIENT")
        self.assertEqual(g["worker_restart"], "INSUFFICIENT")
        self.assertEqual(rep["verdict"], "WARN")     # never FAIL on outage
        self.assertFalse(rep["fully_evaluated"])


# ── Performance fixtures ──────────────────────────────────────────────────────

def perf_inputs(**over):
    scan_ts = NOW - timedelta(minutes=3)
    stages = [
        {"stage": "SCANNER", "last_ts": iso(scan_ts)},
        {"stage": "AI_DECISION", "last_ts": iso(scan_ts + timedelta(seconds=20))},
        {"stage": "EXECUTION", "last_ts": iso(scan_ts + timedelta(seconds=25))},
    ]
    inp = {
        "scan_runs": [{"status": "SUCCESS", "duration_s": 45.0}],
        "stage_summary": {"stages": stages},
        "replay_latency_ms": 800.0,
        "db_query_ms": 120.0,
        "memory_mb": 400.0,
        "cpu_load_1m": 1.2,
    }
    inp.update(over)
    return inp


class TestPerformanceThresholds(unittest.TestCase):
    def metric(self, rep, name):
        return next(m for m in rep["metrics"] if m["metric"] == name)

    def test_all_healthy_passes(self):
        rep = build_performance_report(perf_inputs())
        self.assertEqual(rep["verdict"], "PASS", rep["metrics"])
        self.assertTrue(rep["fully_evaluated"])

    def test_thresholds_grade_warn_and_fail(self):
        warn, fail, _ = THRESHOLDS["scan_duration_s"]
        rep = build_performance_report(perf_inputs(
            scan_runs=[{"status": "SUCCESS", "duration_s": warn + 1}]))
        self.assertEqual(self.metric(rep, "scan_duration_s")["grade"], "WARN")
        self.assertEqual(rep["verdict"], "WARN")
        rep = build_performance_report(perf_inputs(
            scan_runs=[{"status": "SUCCESS", "duration_s": fail + 1}]))
        self.assertEqual(self.metric(rep, "scan_duration_s")["grade"], "FAIL")
        self.assertEqual(rep["verdict"], "FAIL")

    def test_boundary_value_is_pass(self):
        warn, _, _ = THRESHOLDS["db_query_ms"]
        rep = build_performance_report(perf_inputs(db_query_ms=warn))
        self.assertEqual(self.metric(rep, "db_query_ms")["grade"], "PASS")

    def test_stage_gaps_derived_from_last_ts(self):
        rep = build_performance_report(perf_inputs())
        self.assertEqual(self.metric(rep, "decision_latency_s")["value"], 20.0)
        self.assertEqual(self.metric(rep, "execution_latency_s")["value"], 5.0)

    def test_missing_source_is_insufficient_not_fail(self):
        rep = build_performance_report(perf_inputs(
            stage_summary=None, replay_latency_ms=None))
        self.assertEqual(self.metric(rep, "decision_latency_s")["grade"],
                         "INSUFFICIENT")
        self.assertEqual(self.metric(rep, "replay_latency_ms")["grade"],
                         "INSUFFICIENT")
        self.assertEqual(rep["verdict"], "WARN")
        self.assertFalse(rep["fully_evaluated"])

    def test_failed_only_scan_runs_is_insufficient(self):
        rep = build_performance_report(perf_inputs(
            scan_runs=[{"status": "FAILED", "duration_s": 500.0}]))
        self.assertEqual(self.metric(rep, "scan_duration_s")["grade"],
                         "INSUFFICIENT")


# ── Quality fixtures ──────────────────────────────────────────────────────────

def quality_inputs(**over):
    def sig(et, sym):
        return {"event_type": et, "symbol": sym, "scan_id": "scan-1"}
    inp = {
        "scan_id": "scan-1",
        "stage_summary": {"stages": [
            {"stage": "SCANNER", "completed": 15, "rejected": 3},
            {"stage": "RESEARCH", "completed": 12, "rejected": 0},
            {"stage": "RISK", "completed": 4, "rejected": 2},
        ]},
        "signal_events": [
            sig("BUY_GENERATED", "INFY"), sig("BUY_GENERATED", "TCS"),
            sig("SELL_GENERATED", "WIPRO"), sig("WATCH_GENERATED", "HDFC"),
            sig("RISK_REJECTED", "SBIN"), sig("IGNORE_GENERATED", "ITC"),
        ],
        "ledger_rows": [
            {"scan_id": "scan-1", "symbol": "INFY", "status": "OPEN",
             "fill_price": 1000.0},
            {"scan_id": "scan-0", "symbol": "TCS", "status": "CLOSED",
             "fill_price": 500.0},
            {"scan_id": "scan-1", "symbol": "TCS", "status": "REJECTED"},
        ],
        "analytics": {"available": True, "total_trades": 12,
                      "win_rate": 58.3, "profit_factor": 1.6,
                      "expectancy": 45.2, "total_pnl": 542.0,
                      "avg_hold_seconds": 5400.0},
    }
    inp.update(over)
    return inp


class TestQualityReport(unittest.TestCase):
    def test_funnel_counts(self):
        rep = build_quality_report(quality_inputs())
        f = rep["funnel"]
        self.assertEqual(f["scanned"], 15)
        self.assertEqual(f["analysed"], 12)
        self.assertEqual(f["risk_approved"], 4)
        self.assertEqual(f["risk_rejected"], 2)
        self.assertEqual(f["signals"], {"buy": 2, "sell": 1, "watch": 1,
                                        "ignore": 1})
        # only the FILLED scan-1 row counts as executed
        self.assertEqual(f["executed_trades"], 1)
        self.assertEqual(rep["verdict"], "PASS")

    def test_missed_opportunities_from_watch_and_rejected(self):
        rep = build_quality_report(quality_inputs())
        missed = rep["funnel"]["missed_opportunities"]
        self.assertEqual({m["symbol"] for m in missed}, {"HDFC", "SBIN"})
        reasons = {m["symbol"]: m["reason"] for m in missed}
        self.assertEqual(reasons["SBIN"], "RISK_REJECTED")

    def test_low_evidence_reports_insufficient_not_graded(self):
        rep = build_quality_report(quality_inputs(
            analytics={"available": True,
                       "total_trades": MIN_EVIDENCE - 1,
                       "win_rate": 100.0, "profit_factor": 99.0,
                       "expectancy": 500.0, "total_pnl": 100.0,
                       "avg_hold_seconds": 60.0}))
        self.assertEqual(rep["evidence"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(rep["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertIn("note", rep["quality_stats"])

    def test_conservation_break_is_fail_with_issue(self):
        rep = build_quality_report(quality_inputs(signal_events=[
            {"event_type": "SELL_GENERATED", "symbol": "WIPRO",
             "scan_id": "scan-1"}]))     # 0 BUYs but 1 executed trade
        self.assertEqual(rep["verdict"], "FAIL")
        self.assertTrue(rep["_issues"])
        self.assertIn("funnel_conservation", rep["_issues"][0][0])

    def test_analytics_snapshot_contract_real_shape(self):
        """Integration contract: build against the REAL shared-services
        snapshot shape (safe-default payload — no DB/network) so a renamed
        upstream field breaks this test, not production."""
        from paper_analytics.shared_services import (
            get_paper_analytics_snapshot)
        snap = get_paper_analytics_snapshot()
        # The canonical flat-KPI contract this module maps from:
        for key in ("available", "total_trades", "win_rate",
                    "profit_factor", "expectancy", "total_pnl",
                    "avg_hold_seconds"):
            self.assertIn(key, snap, key)
        rep = build_quality_report(quality_inputs(
            analytics=dict(snap, available=True, total_trades=12)))
        self.assertTrue(rep["quality_stats"]["available"])
        self.assertIsNotNone(rep["quality_stats"]["avg_hold_seconds"])

    def test_legacy_avg_holding_seconds_key_tolerated(self):
        analytics = {"available": True, "total_trades": 12,
                     "win_rate": 50.0, "profit_factor": 1.2,
                     "expectancy": 10.0, "total_pnl": 120.0,
                     "avg_holding_seconds": 3600.0}
        rep = build_quality_report(quality_inputs(analytics=analytics))
        self.assertEqual(rep["quality_stats"]["avg_hold_seconds"], 3600.0)

    def test_quality_stats_scope_is_explicit(self):
        rep = build_quality_report(quality_inputs())
        self.assertEqual(rep["quality_stats"]["scope"],
                         "all_time_portfolio")

    def test_missing_events_is_insufficient(self):
        rep = build_quality_report(quality_inputs(signal_events=None))
        self.assertIsNone(rep["funnel"])
        self.assertEqual(rep["verdict"], "INSUFFICIENT")
        self.assertFalse(rep["fully_evaluated"])


# ── Persistence & issue feed ──────────────────────────────────────────────────

def live_recovery_inputs(**over):
    """run_recovery_validation grades against the REAL clock — keep the
    scheduler heartbeat fresh relative to it."""
    inp = healthy_recovery_inputs(
        scheduler={"heartbeat_at": iso(datetime.now(timezone.utc)),
                   "status": "OK", "owner": "host:1"})
    inp.update(over)
    return inp


class TestPersistenceAndIssues(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old_results = store.RESULTS_FILE
        self._old_issues = live_store.ISSUES_FILE
        store.RESULTS_FILE = os.path.join(self.tmp.name, "results.json")
        live_store.ISSUES_FILE = os.path.join(self.tmp.name, "issues.json")

    def tearDown(self):
        store.RESULTS_FILE = self._old_results
        live_store.ISSUES_FILE = self._old_issues
        self.tmp.cleanup()

    def test_results_append_only_with_returned_id(self):
        r1 = run_recovery_validation(persist=True,
                                     inputs=live_recovery_inputs())
        r2 = run_recovery_validation(persist=True,
                                     inputs=live_recovery_inputs())
        self.assertTrue(r1.get("result_id"))
        self.assertNotEqual(r1["result_id"], r2["result_id"])
        runs = store.list_results("RECOVERY", limit=10)
        self.assertEqual(len(runs), 2)
        self.assertEqual(store.latest_result("RECOVERY")["result_id"],
                         r2["result_id"])

    def test_fail_scenarios_feed_and_resolve_issues(self):
        bad = live_recovery_inputs(
            broker={"connection_state": "API_ERROR"})
        run_recovery_validation(persist=True, inputs=bad)
        open_issues = live_store.list_issues(status="OPEN",
                                             category="RECOVERY")
        self.assertEqual([i["key"] for i in open_issues],
                         ["broker_reconnect"])
        # recovery clears the issue on the next fully-evaluated run
        run_recovery_validation(persist=True,
                                inputs=live_recovery_inputs())
        self.assertEqual(live_store.list_issues(status="OPEN",
                                                category="RECOVERY"), [])

    def test_partial_run_never_resolves_issues(self):
        run_recovery_validation(persist=True, inputs=live_recovery_inputs(
            broker={"connection_state": "API_ERROR"}))
        # scheduler outage → INSUFFICIENT → partial cycle: issue must survive
        run_recovery_validation(persist=True, inputs=live_recovery_inputs(
            scheduler=None))
        open_issues = live_store.list_issues(status="OPEN",
                                             category="RECOVERY")
        self.assertEqual([i["key"] for i in open_issues],
                         ["broker_reconnect"])

    def test_quality_run_persists_and_feeds_issues(self):
        rep = run_quality_validation(persist=True, inputs=quality_inputs(
            signal_events=[{"event_type": "SELL_GENERATED",
                            "symbol": "WIPRO", "scan_id": "scan-1"}]))
        self.assertTrue(rep.get("result_id"))
        self.assertNotIn("_issues", rep)      # internal key stripped
        open_issues = live_store.list_issues(status="OPEN",
                                             category="QUALITY")
        self.assertEqual(len(open_issues), 1)
        self.assertIn("funnel_conservation", open_issues[0]["key"])

    def test_unknown_area_rejected(self):
        with self.assertRaises(ValueError):
            store.append_result("BOGUS", {"verdict": "PASS"})


if __name__ == "__main__":
    unittest.main()
