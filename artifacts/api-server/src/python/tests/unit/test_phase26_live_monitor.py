"""Phase 26B unit tests — live subsystem monitor, cross-page consistency,
and the deduplicated issue store. All inputs injected; no DB, no network."""
import os
import sys
import unittest
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

os.environ.pop("DATABASE_URL", None)   # force file fallbacks everywhere

import phase26_live_monitor as mon                     # noqa: E402
import phase26_live_store as live_store               # noqa: E402
from phase26_consistency import run_cross_page_consistency  # noqa: E402

NOW = datetime(2026, 8, 7, 6, 0, 0, tzinfo=timezone.utc)  # 11:30 IST Friday
SESSION_START_UTC = datetime(2026, 8, 7, 3, 30, tzinfo=timezone.utc)  # 09:00 IST


def iso(dt: datetime) -> str:
    return dt.isoformat()


def base_inputs(**over):
    """Healthy in-session inputs; override per test."""
    scan_ts = iso(NOW - timedelta(minutes=3))
    stages = []
    for st in ("SCANNER", "RESEARCH", "MARKET_INTELLIGENCE", "MONITORING",
               "STRATEGY", "RISK", "AI_DECISION", "EXECUTION", "PORTFOLIO"):
        stages.append({"stage": st, "events": 5, "last_ts": scan_ts})
    inp = {
        "collection_errors": {},
        "market": {"state": "OPEN",
                   "session_start_utc": iso(SESSION_START_UTC),
                   "market_open_utc":
                       iso(SESSION_START_UTC + timedelta(minutes=15))},
        "scan_interval_min": 5,
        "scan_meta": {"scan_id": "scan-1", "completed_at": scan_ts,
                      "snapshot_ts": scan_ts},
        "stage_events": {"total_events": 45, "stages": stages},
        "execution_events": [],
        "replay": {"error": None, "scan_id": "scan-1",
                   "snapshot_ts": scan_ts},
        "ledger_rows": [],
        "learning_trade_ids": [],
    }
    inp.update(over)
    return inp


def statuses(snap):
    return {s["subsystem"]: s["status"] for s in snap["subsystems"]}


class TestSessionGating(unittest.TestCase):
    def test_market_open_grace_no_scan_is_idle_not_down(self):
        open_utc = SESSION_START_UTC + timedelta(minutes=15)   # 09:15 IST
        just_after_open = open_utc + timedelta(minutes=6)      # inside grace
        snap = mon.build_liveness_snapshot(base_inputs(
            scan_meta={}, stage_events={"total_events": 0, "stages": []},
            replay={"error": "no scan yet"}), now=just_after_open)
        st = statuses(snap)
        self.assertEqual(st["scanner"], "IDLE")
        self.assertEqual(st["research"], "IDLE")
        self.assertEqual(st["mission_control"], "IDLE")
        self.assertEqual(st["replay"], "IDLE")
        self.assertEqual(snap["verdict"], "PASS")
        self.assertEqual(snap["issues"], [])
        # past the grace window the same picture IS an outage
        later = open_utc + timedelta(minutes=30)
        snap = mon.build_liveness_snapshot(base_inputs(
            scan_meta={}, stage_events={"total_events": 0, "stages": []},
            replay={"error": "no scan yet"}), now=later)
        self.assertEqual(statuses(snap)["scanner"], "DOWN")
        self.assertEqual(snap["verdict"], "FAIL")

    def test_unavailable_source_is_unknown_not_down(self):
        inp = base_inputs()
        inp["scan_meta"] = {}
        inp["collection_errors"] = {"scan_meta": "db timeout"}
        snap = mon.build_liveness_snapshot(inp, now=NOW)
        self.assertEqual(statuses(snap)["scanner"], "UNKNOWN")
        self.assertEqual(snap["verdict"], "WARN")
        self.assertEqual(snap["issues"], [])   # never a false CRITICAL

        inp = base_inputs()
        inp["stage_events"] = {}
        inp["collection_errors"] = {"stage_events": "event store down"}
        snap = mon.build_liveness_snapshot(inp, now=NOW)
        st = statuses(snap)
        self.assertEqual(st["research"], "UNKNOWN")
        self.assertEqual(st["mission_control"], "UNKNOWN")
        self.assertEqual(st["execution"], "UNKNOWN")
        self.assertEqual(snap["issues"], [])

    def test_off_session_is_quiet(self):
        for state in ("WEEKEND", "HOLIDAY", "CLOSED", "POST_CLOSE",
                      "PRE_OPEN"):
            snap = mon.build_liveness_snapshot(
                base_inputs(market={"state": state,
                                    "session_start_utc": None}), now=NOW)
            self.assertFalse(snap["in_session"], state)
            self.assertEqual(snap["verdict"], "PASS", state)
            self.assertEqual(snap["issues"], [], state)
            self.assertTrue(all(v == "OFF_SESSION"
                                for v in statuses(snap).values()), state)

    def test_scheduler_hook_skips_when_not_open(self):
        self.assertIsNone(mon.maybe_run_live_validation("CLOSED"))
        self.assertIsNone(mon.maybe_run_live_validation("WEEKEND"))

    def test_bucket_key_floors_to_5_minutes(self):
        t = datetime(2026, 8, 7, 11, 37, tzinfo=timezone.utc)
        self.assertEqual(mon._bucket_key(t),
                         "live_validation:2026-08-07:1135")
        self.assertEqual(mon._bucket_key(t.replace(minute=39)),
                         mon._bucket_key(t))
        self.assertNotEqual(mon._bucket_key(t.replace(minute=40)),
                            mon._bucket_key(t))


class TestStaleness(unittest.TestCase):
    def test_all_healthy_passes(self):
        snap = mon.build_liveness_snapshot(base_inputs(), now=NOW)
        st = statuses(snap)
        self.assertEqual(snap["verdict"], "PASS")
        self.assertEqual(st["scanner"], "ACTIVE")
        self.assertEqual(st["research"], "ACTIVE")
        self.assertEqual(st["execution"], "IDLE")   # no trades → idle ok
        self.assertEqual(st["learning"], "IDLE")
        self.assertEqual(snap["issues"], [])

    def test_stale_scan_is_stale_then_down(self):
        old = iso(NOW - timedelta(minutes=12))       # > 2×5m interval
        snap = mon.build_liveness_snapshot(base_inputs(
            scan_meta={"scan_id": "scan-1", "completed_at": old}), now=NOW)
        self.assertEqual(statuses(snap)["scanner"], "STALE")
        self.assertEqual(snap["verdict"], "WARN")

        older = iso(NOW - timedelta(minutes=45))     # > 6×5m interval
        snap = mon.build_liveness_snapshot(base_inputs(
            scan_meta={"scan_id": "scan-1", "completed_at": older}), now=NOW)
        self.assertEqual(statuses(snap)["scanner"], "DOWN")
        self.assertEqual(snap["verdict"], "FAIL")

    def test_previous_session_scan_never_confirms_today(self):
        yesterday = iso(SESSION_START_UTC - timedelta(hours=18))
        snap = mon.build_liveness_snapshot(base_inputs(
            scan_meta={"scan_id": "scan-old", "completed_at": yesterday}),
            now=NOW)
        self.assertEqual(statuses(snap)["scanner"], "DOWN")

    def test_missing_stage_events_is_down_with_issue(self):
        inp = base_inputs()
        inp["stage_events"] = {
            "total_events": 5,
            "stages": [{"stage": "SCANNER", "events": 5,
                        "last_ts": inp["scan_meta"]["completed_at"]}]}
        snap = mon.build_liveness_snapshot(inp, now=NOW)
        st = statuses(snap)
        self.assertEqual(st["risk"], "DOWN")
        self.assertEqual(st["decision"], "DOWN")
        keys = {i["key"] for i in snap["issues"]}
        self.assertIn("risk", keys)

    def test_stage_gap_blamed_on_stale_scanner_root_cause(self):
        old = iso(NOW - timedelta(minutes=45))
        inp = base_inputs(
            scan_meta={"scan_id": "scan-1", "completed_at": old},
            stage_events={"total_events": 0, "stages": []})
        snap = mon.build_liveness_snapshot(inp, now=NOW)
        st = statuses(snap)
        self.assertEqual(st["scanner"], "DOWN")
        self.assertEqual(st["research"], "STALE")   # root cause is scanner

    def test_execution_without_portfolio_update_is_down(self):
        ts = iso(NOW - timedelta(minutes=2))
        inp = base_inputs(execution_events=[
            {"event_type": "ORDER_EXECUTED", "symbol": "INFY", "ts": ts}])
        # remove PORTFOLIO stage events
        inp["stage_events"]["stages"] = [
            s for s in inp["stage_events"]["stages"]
            if s["stage"] != "PORTFOLIO"]
        snap = mon.build_liveness_snapshot(inp, now=NOW)
        st = statuses(snap)
        self.assertEqual(st["execution"], "ACTIVE")
        self.assertEqual(st["portfolio"], "DOWN")
        self.assertEqual(st["pnl"], "DOWN")
        self.assertEqual(snap["verdict"], "FAIL")

    def test_replay_scan_mismatch_is_stale(self):
        snap = mon.build_liveness_snapshot(base_inputs(
            replay={"error": None, "scan_id": "scan-0",
                    "snapshot_ts": iso(NOW - timedelta(hours=1))}), now=NOW)
        self.assertEqual(statuses(snap)["replay"], "STALE")

    def test_learning_overdue_after_grace(self):
        closed_at = iso(NOW - timedelta(minutes=45))  # > 30 min grace
        snap = mon.build_liveness_snapshot(base_inputs(
            ledger_rows=[{"status": "CLOSED", "trade_id": "t1",
                          "exit_ts": closed_at, "symbol": "INFY"}]), now=NOW)
        self.assertEqual(statuses(snap)["learning"], "DOWN")
        # within grace → still ACTIVE-pending, no alarm
        recent = iso(NOW - timedelta(minutes=10))
        snap = mon.build_liveness_snapshot(base_inputs(
            ledger_rows=[{"status": "CLOSED", "trade_id": "t1",
                          "exit_ts": recent, "symbol": "INFY"}]), now=NOW)
        self.assertEqual(statuses(snap)["learning"], "ACTIVE")
        # with a learning record → ACTIVE
        snap = mon.build_liveness_snapshot(base_inputs(
            ledger_rows=[{"status": "CLOSED", "trade_id": "t1",
                          "exit_ts": closed_at, "symbol": "INFY"}],
            learning_trade_ids=["t1"]), now=NOW)
        self.assertEqual(statuses(snap)["learning"], "ACTIVE")


class TestConsistency(unittest.TestCase):
    def canonical(self, **over):
        scan_ts = iso(NOW - timedelta(minutes=3))
        kw = dict(
            scan_meta={"scan_id": "scan-1", "completed_at": scan_ts},
            replay={"scan_id": "scan-1", "snapshot_ts": scan_ts,
                    "execution_trades": [{"trade_id": "t1",
                                          "symbol": "INFY"}]},
            portfolio={"cash": 40_000.0, "equity": 50_000.0,
                       "realized_pnl": 100.0,
                       "positions": [{"symbol": "INFY", "quantity": 10,
                                      "current_value": 10_000.0,
                                      "trade_id": "t1"}]},
            ledger_rows=[
                {"scan_id": "scan-1", "symbol": "INFY", "trade_id": "t1",
                 "status": "OPEN", "fill_price": 1000.0},
                {"scan_id": "scan-0", "symbol": "TCS", "trade_id": "t0",
                 "status": "CLOSED", "realized_pnl": 100.0,
                 "fill_price": 500.0}],
            stage_events={"total_events": 10, "stages": []},
            scan_events=[{"event_type": "ORDER_EXECUTED",
                               "symbol": "INFY", "ts": scan_ts}],
            learning_trade_ids=["t0"],
            phase15_report={"available": True, "mismatches": []},
            e2e_runs=[{"run_id": "r1", "scan_id": "scan-1"}],
        )
        kw.update(over)
        return kw

    def test_consistent_state_passes(self):
        rep = run_cross_page_consistency(**self.canonical())
        self.assertTrue(rep["available"])
        self.assertEqual(rep["verdict"], "PASS", rep["mismatches"])
        self.assertEqual(rep["mismatch_count"], 0)

    def test_replay_scan_mismatch_reported_with_expected_actual(self):
        rep = run_cross_page_consistency(**self.canonical(
            replay={"scan_id": "scan-0", "snapshot_ts": "x",
                    "pipeline_counts": {}}))
        m = [m for m in rep["mismatches"]
             if m["source"] == "replay" and m["field"] == "scan_id"]
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0]["expected"], "scan-1")
        self.assertEqual(m[0]["actual"], "scan-0")
        self.assertEqual(rep["verdict"], "FAIL")

    def test_missing_required_field_is_error_never_skipped(self):
        rep = run_cross_page_consistency(**self.canonical(
            replay={"snapshot_ts": "x"}))     # no scan_id at all
        m = [m for m in rep["mismatches"] if m["source"] == "replay"]
        self.assertTrue(m and m[0]["severity"] == "ERROR")
        rep = run_cross_page_consistency(**self.canonical(
            portfolio={"positions": []}))     # no cash
        m = [m for m in rep["mismatches"]
             if m["source"] == "portfolio" and m["field"] == "cash"]
        self.assertTrue(m and m[0]["severity"] == "ERROR")

    def test_event_ledger_disagreement_flagged(self):
        rep = run_cross_page_consistency(**self.canonical(
            scan_events=[]))                  # ledger has 1 row, 0 events
        m = [m for m in rep["mismatches"]
             if m["source"] == "mission_control"]
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0]["expected"], 1)
        self.assertEqual(m[0]["actual"], 0)

    def test_duplicate_one_shot_events_flagged(self):
        ev = {"event_type": "ORDER_EXECUTED", "symbol": "INFY", "ts": "t"}
        rep = run_cross_page_consistency(**self.canonical(
            scan_events=[ev, dict(ev)],
            ledger_rows=[{"scan_id": "scan-1", "symbol": "INFY",
                          "trade_id": "t1", "status": "OPEN",
                          "fill_price": 1000.0}],
            portfolio={"cash": 40_000.0, "equity": 50_000.0,
                       "positions": [{"symbol": "INFY", "quantity": 10,
                                      "current_value": 10_000.0}]}))
        dupes = [m for m in rep["mismatches"]
                 if m["field"] == "duplicate_event"]
        self.assertEqual(len(dupes), 1)
        # 2 events vs 1 ledger row also trips the mission_control check
        self.assertEqual(rep["verdict"], "FAIL")

    def test_missing_execution_trades_is_error_not_skipped(self):
        rep = run_cross_page_consistency(**self.canonical(
            replay={"scan_id": "scan-1", "snapshot_ts": "x"}))
        m = [m for m in rep["mismatches"]
             if m["field"] == "execution_trades"]
        self.assertTrue(m and m[0]["severity"] == "ERROR")

    def test_empty_execution_trades_still_compared(self):
        rep = run_cross_page_consistency(**self.canonical(
            replay={"scan_id": "scan-1", "snapshot_ts": "x",
                    "execution_trades": []}))
        m = [m for m in rep["mismatches"]
             if m["source"] == "broker"]     # ledger has 1 filled scan row
        self.assertEqual(len(m), 1)

    def test_duplicate_portfolio_stage_event_detected(self):
        # canonical query_events shape: metadata under `payload`
        ev = {"event_type": "POSITION_OPENED", "symbol": "INFY",
              "stage": "PORTFOLIO", "payload": {"trade_id": "t1"}}
        rep = run_cross_page_consistency(**self.canonical(
            scan_events=[
                {"event_type": "ORDER_EXECUTED", "symbol": "INFY",
                 "ts": "t", "payload": {"trade_id": "t1"}}, ev, dict(ev)]))
        dupes = [m for m in rep["mismatches"]
                 if m["field"] == "duplicate_event"]
        self.assertEqual(len(dupes), 1)
        self.assertIn("POSITION_OPENED:t1", dupes[0]["note"])

    def test_two_legit_same_symbol_trades_are_not_duplicates(self):
        # Two valid executions of the same symbol with DISTINCT trade IDs in
        # payload must never trip the one-shot duplicate check.
        evs = [
            {"event_type": "ORDER_EXECUTED", "symbol": "INFY", "ts": "t1",
             "stage": "EXECUTION", "payload": {"trade_id": "t1"}},
            {"event_type": "ORDER_EXECUTED", "symbol": "INFY", "ts": "t2",
             "stage": "EXECUTION", "payload": {"trade_id": "t2"}},
            {"event_type": "POSITION_OPENED", "symbol": "INFY", "ts": "t1",
             "stage": "PORTFOLIO", "payload": {"trade_id": "t1"}},
            {"event_type": "POSITION_OPENED", "symbol": "INFY", "ts": "t2",
             "stage": "PORTFOLIO", "payload": {"trade_id": "t2"}},
        ]
        rep = run_cross_page_consistency(**self.canonical(
            scan_events=evs,
            ledger_rows=[
                {"scan_id": "scan-1", "symbol": "INFY", "trade_id": "t1",
                 "status": "OPEN", "fill_price": 1000.0},
                {"scan_id": "scan-1", "symbol": "INFY", "trade_id": "t2",
                 "status": "OPEN", "fill_price": 1001.0}],
            replay={"scan_id": "scan-1", "snapshot_ts": "x",
                    "execution_trades": [{"trade_id": "t1"},
                                         {"trade_id": "t2"}]},
            portfolio={"cash": 30_000.0, "equity": 50_000.0,
                       "positions": [
                           {"symbol": "INFY", "quantity": 10,
                            "current_value": 10_000.0, "trade_id": "t1"},
                           {"symbol": "INFY", "quantity": 10,
                            "current_value": 10_000.0, "trade_id": "t2"}]}))
        self.assertEqual(
            [m for m in rep["mismatches"]
             if m["field"] == "duplicate_event"], [])
        self.assertEqual(rep["verdict"], "PASS", rep["mismatches"])

    def test_rejected_or_pending_ledger_rows_do_not_break_parity(self):
        # A rejected + a pending row for the scan must be excluded from
        # executed-trade parity (only the executed row counts).
        rep = run_cross_page_consistency(**self.canonical(
            ledger_rows=[
                {"scan_id": "scan-1", "symbol": "INFY", "trade_id": "t1",
                 "status": "OPEN", "fill_ts": "t"},
                {"scan_id": "scan-1", "symbol": "TCS", "trade_id": "t2",
                 "status": "REJECTED"},
                {"scan_id": "scan-1", "symbol": "WIPRO", "trade_id": "t3",
                 "status": "PENDING"},
                {"scan_id": "scan-0", "symbol": "TCS", "trade_id": "t0",
                 "status": "CLOSED", "realized_pnl": 100.0,
                 "fill_price": 500.0}]))
        self.assertEqual(
            [m for m in rep["mismatches"]
             if m["source"] in ("broker", "mission_control")], [])
        self.assertEqual(rep["verdict"], "PASS", rep["mismatches"])

    def test_exit_pending_row_counts_as_executed(self):
        # EXIT_PENDING is a REAL execution awaiting exit — it keeps its fill
        # and replay's execution_trades include it, so parity must count it
        # (regression: it was once excluded, raising a false CRITICAL
        # broker mismatch).
        rep = run_cross_page_consistency(**self.canonical(
            ledger_rows=[
                {"scan_id": "scan-1", "symbol": "INFY", "trade_id": "t1",
                 "status": "EXIT_PENDING", "fill_price": 1000.0},
                {"scan_id": "scan-0", "symbol": "TCS", "trade_id": "t0",
                 "status": "CLOSED", "realized_pnl": 100.0,
                 "fill_price": 500.0}]))
        self.assertEqual(
            [m for m in rep["mismatches"]
             if m["source"] in ("broker", "mission_control")], [])
        self.assertEqual(rep["verdict"], "PASS", rep["mismatches"])

    def test_unfilled_open_row_not_counted_as_executed(self):
        # An OPEN row with NO fill (no fill_price/fill_ts) is not a real
        # execution and must not be counted — parity is fill-based.
        rep = run_cross_page_consistency(**self.canonical(
            ledger_rows=[
                {"scan_id": "scan-1", "symbol": "INFY", "trade_id": "t1",
                 "status": "OPEN", "fill_price": 1000.0},
                {"scan_id": "scan-1", "symbol": "TCS", "trade_id": "t9",
                 "status": "OPEN"}]))          # unfilled
        self.assertEqual(
            [m for m in rep["mismatches"]
             if m["source"] in ("broker", "mission_control")], [],
            rep["mismatches"])

    def test_closing_prior_scan_trade_does_not_break_parity(self):
        # Closing a position opened in an earlier scan emits
        # POSITION_CLOSED (not ORDER_EXECUTED) in the current scan and its
        # ledger row keeps its ORIGINAL scan_id — neither side of the
        # current-scan parity may count it.
        scan_ts = iso(NOW - timedelta(minutes=3))
        rep = run_cross_page_consistency(**self.canonical(
            scan_events=[
                {"event_type": "ORDER_EXECUTED", "symbol": "INFY",
                 "ts": scan_ts, "payload": {"trade_id": "t1"}},
                {"event_type": "POSITION_CLOSED", "symbol": "TCS",
                 "stage": "PORTFOLIO", "ts": scan_ts,
                 "payload": {"trade_id": "t0"}}]))
        self.assertEqual(
            [m for m in rep["mismatches"]
             if m["source"] in ("broker", "mission_control",
                                "investigation")], [],
            rep["mismatches"])
        self.assertEqual(rep["verdict"], "PASS", rep["mismatches"])

    def test_missing_learning_record_is_warning(self):
        rep = run_cross_page_consistency(**self.canonical(
            learning_trade_ids=[]))
        m = [m for m in rep["mismatches"] if m["source"] == "learning"]
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0]["severity"], "WARNING")

    def test_phase15_mismatches_folded_in(self):
        rep = run_cross_page_consistency(**self.canonical(
            phase15_report={"available": True, "mismatches": [
                {"source": "ai_decision", "symbol": "INFY",
                 "field": "entry_price", "canonical_value": 100,
                 "source_value": 99, "severity": "ERROR", "note": "x"}]}))
        m = [m for m in rep["mismatches"]
             if m["source"] == "ai_ops:ai_decision"]
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0]["severity"], "ERROR")

    def test_no_scan_is_insufficient_not_fail(self):
        rep = run_cross_page_consistency(scan_meta={})
        self.assertFalse(rep["available"])
        self.assertEqual(rep["verdict"], "INSUFFICIENT")


class TestIssueStore(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self._old_issues = live_store.ISSUES_FILE
        self._old_snaps = live_store.SNAPSHOTS_FILE
        live_store.ISSUES_FILE = os.path.join(self.tmp.name, "issues.json")
        live_store.SNAPSHOTS_FILE = os.path.join(self.tmp.name, "snaps.json")

    def tearDown(self):
        live_store.ISSUES_FILE = self._old_issues
        live_store.SNAPSHOTS_FILE = self._old_snaps
        self.tmp.cleanup()

    def test_dedup_by_category_and_key(self):
        live_store.report_issue("SUBSYSTEM", "scanner", "WARNING", "t1", "d1")
        live_store.report_issue("SUBSYSTEM", "scanner", "WARNING", "t2", "d2")
        issues = live_store.list_issues()
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["count"], 2)
        self.assertEqual(issues[0]["title"], "t2")
        self.assertEqual(issues[0]["status"], "OPEN")

    def test_severity_escalates_never_downgrades_while_open(self):
        live_store.report_issue("SUBSYSTEM", "risk", "CRITICAL", "t", "d")
        live_store.report_issue("SUBSYSTEM", "risk", "WARNING", "t", "d")
        self.assertEqual(live_store.list_issues()[0]["severity"], "CRITICAL")

    def test_resolve_and_reopen_preserves_first_seen(self):
        live_store.report_issue("SUBSYSTEM", "replay", "WARNING", "t", "d")
        first = live_store.list_issues()[0]["first_seen"]
        self.assertTrue(live_store.resolve_issue("SUBSYSTEM", "replay"))
        self.assertEqual(live_store.list_issues(status="OPEN"), [])
        self.assertFalse(live_store.resolve_issue("SUBSYSTEM", "replay"))
        live_store.report_issue("SUBSYSTEM", "replay", "WARNING", "t", "d")
        row = live_store.list_issues(status="OPEN")[0]
        self.assertEqual(row["first_seen"], first)
        self.assertEqual(row["count"], 2)
        self.assertIsNone(row["resolved_at"])

    def test_sweep_resolves_only_inactive_keys_in_category(self):
        live_store.report_issue("SUBSYSTEM", "scanner", "WARNING", "t", "d")
        live_store.report_issue("SUBSYSTEM", "risk", "CRITICAL", "t", "d")
        live_store.report_issue("CONSISTENCY", "replay:scan_id",
                                "CRITICAL", "t", "d")
        out = live_store.sweep_category("SUBSYSTEM", ["risk"])
        self.assertEqual(out["resolved"], 1)
        open_now = live_store.list_issues(status="OPEN")
        keys = {(i["category"], i["key"]) for i in open_now}
        self.assertIn(("SUBSYSTEM", "risk"), keys)
        self.assertIn(("CONSISTENCY", "replay:scan_id"), keys)
        self.assertNotIn(("SUBSYSTEM", "scanner"), keys)

    def test_snapshots_append_only(self):
        r1 = live_store.append_snapshot({"verdict": "PASS",
                                         "in_session": True})
        r2 = live_store.append_snapshot({"verdict": "FAIL",
                                         "in_session": True})
        self.assertNotEqual(r1["snapshot_id"], r2["snapshot_id"])
        # same snapshot_id is never overwritten
        live_store.append_snapshot({"snapshot_id": r1["snapshot_id"],
                                    "verdict": "FAIL"})
        snaps = live_store.list_snapshots()
        self.assertEqual(len(snaps), 2)
        latest = live_store.latest_snapshot()
        self.assertEqual(latest["snapshot_id"], r2["snapshot_id"])

    def test_run_live_validation_files_and_sweeps_issues(self):
        # run_live_validation judges against real wall-clock time, so build
        # inputs relative to now.
        rn = datetime.now(timezone.utc)

        def live_inputs(**over):
            inp = base_inputs(**over)
            fresh = iso(rn - timedelta(minutes=3))
            inp["market"]["session_start_utc"] = iso(rn - timedelta(hours=2))
            if "scan_meta" not in over:
                inp["scan_meta"] = {"scan_id": "scan-1",
                                    "completed_at": fresh}
            for s in inp["stage_events"]["stages"]:
                s["last_ts"] = fresh
            inp["replay"]["snapshot_ts"] = fresh
            return inp

        inp = live_inputs(scan_meta={"scan_id": "scan-1",
                                     "completed_at":
                                         iso(rn - timedelta(minutes=45))})
        snap = mon.run_live_validation(
            persist=True, inputs=inp,
            consistency={"available": True, "verdict": "PASS",
                         "mismatch_count": 0, "hard_mismatch_count": 0,
                         "issues": []})
        self.assertEqual(snap["verdict"], "FAIL")
        # the returned snapshot must carry the PERSISTED snapshot id so a
        # scheduler tick can be correlated with the stored record
        self.assertTrue(snap.get("snapshot_id"))
        self.assertEqual(live_store.latest_snapshot()["snapshot_id"],
                         snap["snapshot_id"])
        open_issues = live_store.list_issues(status="OPEN")
        self.assertTrue(any(i["key"] == "scanner" for i in open_issues))
        # recovery cycle: healthy inputs → subsystem issues auto-resolve
        snap2 = mon.run_live_validation(
            persist=True, inputs=live_inputs(),
            consistency={"available": True, "verdict": "PASS",
                         "mismatch_count": 0, "hard_mismatch_count": 0,
                         "issues": []})
        self.assertEqual(snap2["verdict"], "PASS")
        self.assertEqual([i for i in live_store.list_issues(status="OPEN")
                          if i["category"] == "SUBSYSTEM"], [])
        resolved = live_store.list_issues(status="RESOLVED")
        self.assertTrue(any(i["key"] == "scanner" for i in resolved))


class TestFailAlerts(unittest.TestCase):
    """Task: alert operators the moment live validation turns FAIL."""

    def setUp(self):
        import tempfile
        from unittest import mock
        self.tmp = tempfile.TemporaryDirectory()
        self._old_issues = live_store.ISSUES_FILE
        self._old_snaps = live_store.SNAPSHOTS_FILE
        live_store.ISSUES_FILE = os.path.join(self.tmp.name, "issues.json")
        live_store.SNAPSHOTS_FILE = os.path.join(self.tmp.name, "snaps.json")
        import phase20_store
        self.notifications = []
        self._patch = mock.patch.object(
            phase20_store, "add_notification",
            side_effect=lambda kind, title, body="", severity="INFO",
            context=None: self.notifications.append(
                {"kind": kind, "title": title, "severity": severity}))
        self._patch.start()
        self.rn = datetime.now(timezone.utc)

    def tearDown(self):
        self._patch.stop()
        live_store.ISSUES_FILE = self._old_issues
        live_store.SNAPSHOTS_FILE = self._old_snaps
        self.tmp.cleanup()

    def _inputs(self, healthy=True):
        inp = base_inputs()
        fresh = iso(self.rn - timedelta(minutes=3))
        inp["market"]["session_start_utc"] = iso(self.rn - timedelta(hours=2))
        inp["scan_meta"] = {"scan_id": "scan-1",
                            "completed_at": fresh if healthy
                            else iso(self.rn - timedelta(minutes=45))}
        for s in inp["stage_events"]["stages"]:
            s["last_ts"] = fresh
        inp["replay"]["snapshot_ts"] = fresh
        return inp

    _PASS_CONS = {"available": True, "verdict": "PASS",
                  "mismatch_count": 0, "hard_mismatch_count": 0, "issues": []}

    def _run(self, healthy=True):
        return mon.run_live_validation(persist=True,
                                       inputs=self._inputs(healthy),
                                       consistency=self._PASS_CONS)

    def kinds(self):
        return [n["kind"] for n in self.notifications]

    def test_fail_alerts_once_then_stays_quiet_then_all_clear(self):
        snap = self._run(healthy=False)
        self.assertEqual(snap["verdict"], "FAIL")
        self.assertIn("LIVE_VALIDATION_FAIL", self.kinds())
        # scanner DOWN is a CRITICAL issue → per-issue alert too
        self.assertIn("LIVE_VALIDATION_ISSUE", self.kinds())
        first_count = len(self.notifications)

        # second FAIL cycle: same issues still open → NO new alerts
        self._run(healthy=False)
        self.assertEqual(len(self.notifications), first_count)

        # recovery: issues auto-resolve → single all-clear info note
        snap = self._run(healthy=True)
        self.assertEqual(snap["verdict"], "PASS")
        self.assertEqual(self.kinds().count("LIVE_VALIDATION_RECOVERED"), 1)
        recovered = [n for n in self.notifications
                     if n["kind"] == "LIVE_VALIDATION_RECOVERED"]
        self.assertEqual(recovered[0]["severity"], "INFO")

        # healthy again: quiet
        n = len(self.notifications)
        self._run(healthy=True)
        self.assertEqual(len(self.notifications), n)

    def test_partial_warn_cycle_never_clears_open_fail(self):
        # FAIL → partial cycle (collection errors, WARN) → confirmed PASS.
        # The partial cycle must neither resolve the open FAIL issue nor
        # send a false all-clear; only the confirmed PASS recovers.
        self._run(healthy=False)
        n = len(self.notifications)

        inp = self._inputs(healthy=True)
        inp["scan_meta"] = {}
        inp["collection_errors"] = {"scan_meta": "db timeout"}
        snap = mon.run_live_validation(persist=True, inputs=inp,
                                       consistency=self._PASS_CONS)
        self.assertEqual(snap["verdict"], "WARN")
        self.assertNotIn("LIVE_VALIDATION_RECOVERED", self.kinds())
        self.assertEqual(len(self.notifications), n)
        open_verdict = [i for i in live_store.list_issues(status="OPEN")
                        if i["category"] == "VERDICT"]
        self.assertEqual(len(open_verdict), 1)

        snap = self._run(healthy=True)
        self.assertEqual(snap["verdict"], "PASS")
        self.assertEqual(self.kinds().count("LIVE_VALIDATION_RECOVERED"), 1)
        self.assertEqual([i for i in live_store.list_issues(status="OPEN")
                          if i["category"] == "VERDICT"], [])

    def test_consistency_unavailable_never_clears_open_fail(self):
        # FAIL → liveness-healthy cycle whose consistency validator is
        # unavailable/errored → confirmed PASS. The unavailable-consistency
        # cycle is PARTIAL: it must not resolve the open FAIL nor send an
        # all-clear, even though the liveness verdict alone is PASS.
        self._run(healthy=False)
        n = len(self.notifications)

        snap = mon.run_live_validation(
            persist=True, inputs=self._inputs(healthy=True),
            consistency={"available": False, "error": "consistency crashed"})
        self.assertNotIn("LIVE_VALIDATION_RECOVERED", self.kinds())
        self.assertEqual(len(self.notifications), n)
        open_verdict = [i for i in live_store.list_issues(status="OPEN")
                        if i["category"] == "VERDICT"]
        self.assertEqual(len(open_verdict), 1, snap)

        snap = self._run(healthy=True)
        self.assertEqual(snap["verdict"], "PASS")
        self.assertEqual(self.kinds().count("LIVE_VALIDATION_RECOVERED"), 1)
        self.assertEqual([i for i in live_store.list_issues(status="OPEN")
                          if i["category"] == "VERDICT"], [])

    def test_refail_after_recovery_alerts_again(self):
        self._run(healthy=False)
        self._run(healthy=True)
        n_fail = self.kinds().count("LIVE_VALIDATION_FAIL")
        self._run(healthy=False)
        self.assertEqual(self.kinds().count("LIVE_VALIDATION_FAIL"),
                         n_fail + 1)

    def test_healthy_pass_cycle_raises_nothing(self):
        snap = self._run(healthy=True)
        self.assertEqual(snap["verdict"], "PASS")
        self.assertEqual(self.notifications, [])

    def test_off_session_is_quiet_even_after_open_fail(self):
        self._run(healthy=False)
        n = len(self.notifications)
        snap = mon.run_live_validation(
            persist=True,
            inputs=base_inputs(market={"state": "CLOSED",
                                       "session_start_utc": None}))
        self.assertFalse(snap["in_session"])
        self.assertEqual(len(self.notifications), n)

    def test_alert_kinds_are_emailed_critical_kinds(self):
        import email_alerts
        self.assertIn("LIVE_VALIDATION_FAIL", email_alerts.EMAIL_KINDS)
        self.assertIn("LIVE_VALIDATION_ISSUE", email_alerts.EMAIL_KINDS)

    def test_report_issue_transitions(self):
        r = live_store.report_issue("SUBSYSTEM", "risk", "CRITICAL", "t", "d")
        self.assertEqual(r["transition"], "OPENED")
        r = live_store.report_issue("SUBSYSTEM", "risk", "CRITICAL", "t", "d")
        self.assertEqual(r["transition"], "STILL_OPEN")
        live_store.resolve_issue("SUBSYSTEM", "risk")
        r = live_store.report_issue("SUBSYSTEM", "risk", "CRITICAL", "t", "d")
        self.assertEqual(r["transition"], "OPENED")

    def test_reconcile_returns_opened_and_resolved_keys(self):
        out = live_store.reconcile_category("SUBSYSTEM", [
            {"key": "scanner", "severity": "CRITICAL", "title": "t"}])
        self.assertEqual([o["key"] for o in out["opened"]], ["scanner"])
        self.assertEqual(out["resolved_keys"], [])
        # same issue again → not opened again
        out = live_store.reconcile_category("SUBSYSTEM", [
            {"key": "scanner", "severity": "CRITICAL", "title": "t"}])
        self.assertEqual(out["opened"], [])
        # cycle without it → resolved_keys reports it
        out = live_store.reconcile_category("SUBSYSTEM", [])
        self.assertEqual(out["resolved_keys"], ["scanner"])


if __name__ == "__main__":
    unittest.main()
