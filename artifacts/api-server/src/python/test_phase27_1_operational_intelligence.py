"""Phase 27.1 Operational Intelligence — pure unit tests.

All builders are exercised with constructed inputs; no network, DB, or
filesystem access.
"""
import unittest
from datetime import datetime, timedelta, timezone

import phase27_1_operational_intelligence as oi

NOW = datetime(2026, 8, 9, 10, 0, tzinfo=timezone.utc)


def iso(minutes_ago: float = 0) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat()


def entry(minutes_ago, overall, failures=None, issues=None):
    return {"at": iso(minutes_ago), "overall": overall,
            "counts": {}, "blocking_failures": failures or [],
            "issues": issues or []}


def readiness_report(overall="READY", domains=None):
    return {"ok": True, "overall": overall, "domains": domains or []}


def domain(name, status="READY", checks=None):
    return {"domain": name, "status": status, "checks": checks or []}


def check(cid, status="READY", blocking=True, label=None, actual="ok",
          remediation=""):
    return {"id": cid, "domain": "X", "label": label or cid,
            "status": status, "blocking": blocking, "expected": "e",
            "actual": actual, "evidence": {}, "remediation": remediation,
            "checked_at": iso(0)}


class TestTimeline(unittest.TestCase):
    def test_transitions_and_recovery_time(self):
        entries = [entry(60, "READY"), entry(50, "WARNING",
                                             issues=[{"id": "x", "domain": "D",
                                                      "status": "WARNING",
                                                      "actual": "bad"}]),
                   entry(48, "WARNING"), entry(40, "READY"),
                   entry(10, "BLOCKED")]
        t = oi.build_timeline(entries, NOW)
        self.assertEqual(t["current_status"], "BLOCKED")
        # consecutive identical states are collapsed
        transitions = [(e["from"], e["to"]) for e in reversed(t["events"])]
        self.assertEqual(transitions, [(None, "READY"), ("READY", "WARNING"),
                                       ("WARNING", "READY"),
                                       ("READY", "BLOCKED")])
        warn = next(e for e in t["events"] if e["to"] == "WARNING")
        self.assertEqual(warn["recovery_minutes"], 10.0)  # 50m→40m ago
        self.assertEqual(warn["components"], ["D"])
        self.assertEqual(warn["reason"], "bad")
        blocked = next(e for e in t["events"] if e["to"] == "BLOCKED")
        self.assertIsNone(blocked["recovery_minutes"])  # unresolved
        self.assertTrue(blocked["operator_action"])

    def test_empty_history(self):
        t = oi.build_timeline([], NOW)
        self.assertEqual(t["current_status"], "UNKNOWN")
        self.assertEqual(t["events"], [])


class TestHistoryStats(unittest.TestCase):
    def test_window_counts_and_streak(self):
        entries = [entry(300, "READY"), entry(240, "READY"),
                   entry(180, "WARNING", failures=["scan_freshness"]),
                   entry(120, "READY"), entry(60, "READY"),
                   entry(30, "BLOCKED", failures=["circuit_breaker"]),
                   entry(5, "READY")]
        s = oi.build_history_stats(entries, NOW)["7d"]
        self.assertEqual(s["evaluations"], 7)
        self.assertEqual(s["ready"], 5)
        self.assertEqual(s["warning"], 1)
        self.assertEqual(s["blocked"], 1)
        self.assertEqual(s["longest_ready_streak"], 2)
        self.assertIn(s["most_common_failure"],
                      ("scan_freshness", "circuit_breaker"))
        self.assertIsNotNone(s["avg_recovery_minutes"])
        self.assertGreater(len(s["trend"]), 0)

    def test_insufficient_data_flag(self):
        s = oi.build_history_stats([entry(10, "READY")], NOW)["7d"]
        self.assertTrue(s["insufficient_data"])

    def test_windows_are_cumulative(self):
        entries = [entry(60 * 24 * 20, "BLOCKED"), entry(10, "READY")]
        s = oi.build_history_stats(entries, NOW)
        self.assertEqual(s["7d"]["evaluations"], 1)
        self.assertEqual(s["30d"]["evaluations"], 2)
        self.assertEqual(s["90d"]["evaluations"], 2)


class TestChecklist(unittest.TestCase):
    def make_readiness(self):
        return readiness_report(domains=[
            domain("A", checks=[
                check("scan_freshness", "READY"),
                check("provider_coverage", "WARNING", blocking=False,
                      remediation="rerun"),
                check("last_scan_outcome", "READY"),
                check("risk_config", "READY"),
                check("portfolio_health", "READY"),
                check("pipeline_events", "READY"),
                check("db_durability", "READY"),
                check("execution_mode", "BLOCKED",
                      remediation="unset live flags"),
                check("broker_session", "WARNING", blocking=False),
                check("scheduler_health", "READY"),
                check("system_resources", "READY"),
            ])])

    def test_statuses_and_remediation(self):
        stages = {"SCANNER": {"events": 50, "errors": 0},
                  "RESEARCH": {"events": 50, "errors": 0},
                  "MARKET_INTELLIGENCE": {"events": 50, "errors": 2},
                  "RISK": {"events": 50, "errors": 0},
                  "PORTFOLIO": {"events": 0, "errors": 0},
                  "AI_DECISION": {"events": 50, "errors": 0}}
        cl = oi.build_checklist(self.make_readiness(), {"stages": stages})
        by = {i["item"]: i for i in cl["items"]}
        self.assertEqual(len(cl["items"]), 13)
        self.assertEqual(by["Paper Mode"]["status"], "FAIL")
        self.assertTrue(by["Paper Mode"]["remediation"])
        self.assertEqual(by["Market Data"]["status"], "WARNING")  # coverage
        self.assertEqual(by["Market Intelligence"]["status"], "WARNING")
        self.assertEqual(by["Research"]["status"], "PASS")
        self.assertEqual(by["Portfolio"]["status"], "WARNING")  # 0 events
        self.assertEqual(by["Scheduler"]["status"], "PASS")
        self.assertEqual(cl["overall"], "FAIL")

    def test_no_evidence_is_warning_not_pass(self):
        cl = oi.build_checklist(None, None)
        self.assertTrue(all(i["status"] != "PASS" for i in cl["items"]))
        self.assertEqual(cl["counts"]["PASS"], 0)


class TestSessionComparison(unittest.TestCase):
    def sessions(self):
        return [
            {"scan_id": "s-today", "snapshot_ts": iso(30), "is_latest": True,
             "universe_size": 50, "symbols_processed": 48,
             "buy_signals": 5, "paper_orders": 2, "duration_s": 900.0,
             "source": "scan_state"},
            {"scan_id": "s-yday", "snapshot_ts": iso(60 * 24), "is_latest": False,
             "universe_size": 50, "symbols_processed": 40,
             "buy_signals": 8, "paper_orders": 3, "duration_s": 800.0,
             "source": "scan_state"},
            {"scan_id": "s-old", "snapshot_ts": iso(60 * 48),
             "universe_size": None, "symbols_processed": None,
             "buy_signals": None, "paper_orders": None, "duration_s": None,
             "source": "signal_snapshots"},
        ]

    def trades(self):
        return [
            {"action": "BUY", "timestamp": iso(20), "realized_pnl": None},
            {"action": "SELL", "timestamp": iso(10), "realized_pnl": 150.0},
            {"action": "SELL", "timestamp": iso(60 * 24 - 30),
             "realized_pnl": -80.0},
        ]

    def test_grouping_and_metrics(self):
        stage_summary = {"scan_id": "s-today", "stages": [
            {"stage": "RISK", "events": 10, "rejected": 3},
            {"stage": "EXECUTION", "events": 4, "completed": 3,
             "avg_symbol_ms": 120.5}]}
        cmp_ = oi.build_session_comparison(self.sessions(), self.trades(),
                                           NOW, stage_summary=stage_summary)
        days = cmp_["days"]
        self.assertEqual(len(days), 3)
        self.assertEqual(days[0]["label"], "today")
        self.assertTrue(days[0]["is_today"])
        self.assertEqual(days[0]["stocks_scanned"], 48)
        self.assertEqual(days[0]["trades"], 2)
        self.assertEqual(days[0]["win_rate_pct"], 100.0)
        self.assertEqual(days[0]["pnl"], 150.0)
        # canonical stage metrics attach only to the day owning the scan
        self.assertEqual(days[0]["risk_rejections"], 3)
        self.assertEqual(days[0]["execution_success_pct"], 75.0)
        self.assertEqual(days[0]["pipeline_latency_ms"], 120.5)
        self.assertIsNone(days[1]["risk_rejections"])
        self.assertEqual(days[1]["label"], "yesterday")
        self.assertEqual(days[1]["win_rate_pct"], 0.0)
        # limited historical row keeps None, never fabricated
        self.assertIsNone(days[2]["stocks_scanned"])
        self.assertTrue(days[2]["label"].startswith("previous session ("))

    def test_no_data_today_is_never_relabelled(self):
        # only historical sessions — the newest must NOT be called "today"
        old = [{"scan_id": "s-old", "snapshot_ts": iso(60 * 24 * 3),
                "universe_size": 50, "symbols_processed": 45,
                "buy_signals": 2, "paper_orders": 1, "duration_s": 500.0,
                "source": "scan_state"}]
        cmp_ = oi.build_session_comparison(old, [], NOW)
        days = cmp_["days"]
        self.assertEqual(days[0]["label"], "today")
        self.assertIsNone(days[0]["stocks_scanned"])  # empty today row
        self.assertFalse(days[1]["is_today"])
        self.assertNotEqual(days[1]["label"], "today")
        self.assertEqual(days[1]["stocks_scanned"], 45)

    def test_empty_sources(self):
        cmp_ = oi.build_session_comparison([], [], NOW)
        self.assertEqual(len(cmp_["days"]), 1)  # empty today row only
        self.assertTrue(cmp_["days"][0]["is_today"])
        self.assertIsNone(cmp_["days"][0]["stocks_scanned"])


class TestInsights(unittest.TestCase):
    def test_deltas_generate_advisory_insights(self):
        comparison = {"days": [
            {"stocks_scanned": 40, "signals": 4, "trades": 2, "pnl": 100.0,
             "scan_duration_s": 700.0},
            {"stocks_scanned": 50, "signals": 8, "trades": 2, "pnl": -50.0,
             "scan_duration_s": 900.0},
        ]}
        ins = oi.build_insights(comparison, None, {})
        texts = " | ".join(i["text"] for i in ins)
        self.assertIn("fewer stocks", texts)
        self.assertIn("down", texts)
        self.assertIn("improved", texts)  # PnL and latency
        self.assertTrue(all(i["advisory_only"] for i in ins))

    def test_blocked_checks_surface_critical(self):
        rep = readiness_report("BLOCKED", domains=[
            domain("Safety Controls", "BLOCKED", [
                check("circuit_breaker", "BLOCKED", label="Breaker",
                      actual="TRIPPED")])])
        ins = oi.build_insights({"days": []}, rep, {})
        crit = [i for i in ins if i["severity"] == "CRITICAL"]
        self.assertEqual(len(crit), 1)
        self.assertIn("TRIPPED", crit[0]["text"])

    def test_no_data_yields_neutral_insight(self):
        ins = oi.build_insights({"days": []}, None, {})
        self.assertEqual(len(ins), 1)
        self.assertEqual(ins[0]["severity"], "INFO")


class TestHealthScore(unittest.TestCase):
    def test_scores_fold_canonical_statuses(self):
        rep = readiness_report(domains=[domain("A", "READY"),
                                        domain("B", "WARNING"),
                                        domain("C", "BLOCKED")])
        stages = {"SCANNER": {"events": 10, "errors": 0},
                  "RISK": {"events": 10, "errors": 1},
                  "EXECUTION": {"events": 0, "errors": 0}}
        h = oi.build_health_score(rep, {"stages": stages}, [])
        by = {(c["component"], c["kind"]): c for c in h["components"]}
        self.assertEqual(by[("A", "readiness")]["score"], 100)
        self.assertEqual(by[("B", "readiness")]["score"], 60)
        self.assertEqual(by[("C", "readiness")]["score"], 0)
        self.assertEqual(by[("Scanner", "stage")]["status"], "READY")
        self.assertEqual(by[("Risk", "stage")]["status"], "WARNING")
        self.assertEqual(by[("Execution", "stage")]["status"], "UNKNOWN")
        # stages absent from the summary must appear as UNKNOWN, not vanish
        self.assertEqual(by[("Research", "stage")]["status"], "UNKNOWN")
        self.assertEqual(len([c for c in h["components"]
                              if c["kind"] == "stage"]),
                         len(oi.HEALTH_COMPONENTS))
        self.assertIsNotNone(h["overall_score"])

    def test_missing_stage_summary_never_inflates_score(self):
        rep = readiness_report(domains=[domain("A", "READY")])
        h = oi.build_health_score(rep, None, [])
        # 1 READY domain + all-UNKNOWN stages → well below 100
        self.assertLess(h["overall_score"], 60)

    def test_trend_detection(self):
        entries = [entry(100, "BLOCKED"), entry(90, "BLOCKED"),
                   entry(20, "READY"), entry(10, "READY")]
        h = oi.build_health_score(None, None, entries)
        self.assertEqual(h["trend"], "IMPROVING")

    def test_empty_inputs(self):
        h = oi.build_health_score(None, None, [])
        # no evidence at all → every stage component UNKNOWN, score = 40
        self.assertEqual(h["overall_score"], 40.0)
        self.assertTrue(all(c["status"] == "UNKNOWN"
                            for c in h["components"]))
        self.assertIsNone(h["trend"])


class TestExecutiveSummary(unittest.TestCase):
    def test_composition(self):
        rep = readiness_report("WARNING", domains=[
            domain("Pipeline", "READY"),
            domain("Execution", "READY"),
            domain("Portfolio", "WARNING"),
            domain("Configuration", "READY"),
            domain("Safety Controls", "BLOCKED", [
                check("circuit_breaker", "BLOCKED", label="Breaker",
                      actual="TRIPPED", remediation="review")])])
        checklist = {"counts": {"PASS": 10, "WARNING": 2, "FAIL": 1}}
        health = {"overall_score": 77.0}
        insights = [{"severity": "CRITICAL", "text": "bad"},
                    {"severity": "INFO", "text": "info"}]
        comparison = {"days": [{"is_today": True, "date": "2026-08-09"}]}
        ex = oi.build_executive_summary(rep, checklist, health, insights,
                                        comparison)
        self.assertEqual(ex["readiness"], "WARNING")
        self.assertEqual(ex["ai_health"], "READY")
        self.assertEqual(ex["portfolio_health"], "WARNING")
        self.assertEqual(ex["pipeline_health_score"], 77.0)
        self.assertEqual(len(ex["operator_alerts"]), 1)
        self.assertEqual(ex["recommendations"], ["info"])
        self.assertEqual(len(ex["outstanding_issues"]), 1)
        self.assertTrue(ex["today"]["is_today"])

    def test_missing_readiness_is_unknown(self):
        ex = oi.build_executive_summary(None, {"counts": {}}, {}, [],
                                        {"days": []})
        self.assertEqual(ex["readiness"], "UNKNOWN")
        self.assertEqual(ex["ai_health"], "UNKNOWN")


class TestReadOnlyContract(unittest.TestCase):
    def test_module_never_imports_trading_mutators(self):
        import inspect
        src = inspect.getsource(oi)
        for forbidden in ("execute_buy", "execute_sell", "place_order",
                          "kv_set", "add_notification", "run_scan"):
            self.assertNotIn(forbidden, src,
                             f"read-only module must not reference {forbidden}")

    def test_shortcuts_are_static_metadata(self):
        self.assertEqual(len(oi.SHORTCUTS), 6)
        for s in oi.SHORTCUTS:
            self.assertTrue(s["href"].startswith("/"))


if __name__ == "__main__":
    unittest.main()
