"""
Phase 23.8B — Validation & Certification Engines tests.

Covers the six validation engines (seeded fixtures for pass, fail and
insufficient-evidence paths), the certification aggregation (WARN is never
treated as PASS; READY requires every domain to PASS), append-only
certification persistence via the file fallback, long-duration validation
windows, and the AST safety test proving neither engine has a write path
into live trading state.

All persistence tests run against the FILE FALLBACK store in a temp dir —
the dev database is never touched.
"""
import ast
import os
import re
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import validation_engines as ve  # noqa: E402
import certification_engine as ce  # noqa: E402


# ── fixtures ─────────────────────────────────────────────────────────────────

def _candles(ts_list, closes=None, **overrides):
    rows = []
    for i, ts in enumerate(ts_list):
        c = closes[i] if closes else 100.0
        rows.append({"ts": ts, "open": c, "high": c * 1.01,
                     "low": c * 0.99, "close": c, "volume": 1000})
    for k, v in overrides.items():
        idx, field = k
        rows[idx][field] = v
    return rows


WEEK = ["2026-07-06", "2026-07-07", "2026-07-08", "2026-07-09", "2026-07-10"]


def _event(i, event_type, stage, symbol="RELIANCE", scan_id="S-1",
           payload=None, ts="2026-08-05T04:00:00Z"):
    return {"id": i, "ts": ts, "mode": "LIVE", "scan_id": scan_id,
            "run_id": None, "event_type": event_type, "stage": stage,
            "symbol": symbol, "payload": payload or {}}


def _paper_trade(i, pnl=100.0, status="CLOSED", conf=70.0, price=100.0,
                 qty=10, strategy="MOMO",
                 fill_ts="2026-08-03T04:00:00Z",
                 exit_ts="2026-08-04T04:00:00Z"):
    return {"trade_id": f"T{i}", "symbol": f"SYM{i}", "status": status,
            "side": "BUY", "realized_pnl": pnl if status == "CLOSED" else None,
            "confidence": conf, "fill_price": price, "quantity": qty,
            "strategy_name": strategy, "fill_ts": fill_ts,
            "exit_ts": exit_ts if status == "CLOSED" else None}


# ── Part G: data validation ─────────────────────────────────────────────────

class TestDataValidation(unittest.TestCase):
    def test_clean_candles_pass(self):
        r = ve.validate_data(candles_by_symbol={"RELIANCE": _candles(WEEK)})
        self.assertEqual(r["verdict"], "PASS")

    def test_duplicate_timestamps_fail(self):
        c = _candles(WEEK[:3] + [WEEK[2]])
        r = ve.validate_data(candles_by_symbol={"X": c})
        self.assertEqual(r["verdict"], "FAIL")
        bad = [x for x in r["checks"] if x["check"].endswith("no_duplicate_candles")]
        self.assertEqual(bad[0]["status"], "FAIL")

    def test_out_of_order_fail(self):
        c = _candles([WEEK[1], WEEK[0], WEEK[2]])
        r = ve.validate_data(candles_by_symbol={"X": c})
        self.assertEqual(r["verdict"], "FAIL")

    def test_price_integrity_fail(self):
        c = _candles(WEEK)
        c[2]["high"] = c[2]["low"] - 5   # impossible candle
        r = ve.validate_data(candles_by_symbol={"X": c})
        bad = [x for x in r["checks"] if x["check"].endswith("price_integrity")]
        self.assertEqual(bad[0]["status"], "FAIL")

    def test_negative_volume_fail(self):
        c = _candles(WEEK)
        c[1]["volume"] = -10
        r = ve.validate_data(candles_by_symbol={"X": c})
        bad = [x for x in r["checks"] if x["check"].endswith("volume_integrity")]
        self.assertEqual(bad[0]["status"], "FAIL")

    def test_split_anomaly_warn(self):
        c = _candles(WEEK, closes=[100, 100, 200, 200, 200])  # +100% jump
        r = ve.validate_data(candles_by_symbol={"X": c})
        anom = [x for x in r["checks"]
                if x["check"].endswith("corporate_action_anomalies")]
        self.assertEqual(anom[0]["status"], "WARN")
        self.assertEqual(r["verdict"], "WARN")   # warn never becomes pass

    def test_no_candles_insufficient(self):
        r = ve.validate_data(candles_by_symbol={"X": []})
        self.assertEqual(r["verdict"], "INSUFFICIENT_EVIDENCE")

    def test_partially_missing_symbols_block_domain(self):
        # one clean symbol + one missing symbol must NOT certify as PASS
        r = ve.validate_data(candles_by_symbol={
            "RELIANCE": _candles(WEEK), "TCS": []})
        self.assertEqual(r["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(r["missing_symbols"], ["TCS"])

    def test_hard_fail_dominates_missing_symbols(self):
        c = _candles(WEEK[:3] + [WEEK[2]])          # duplicate ts → FAIL
        r = ve.validate_data(candles_by_symbol={"X": c, "Y": []})
        self.assertEqual(r["verdict"], "FAIL")


# ── Part H: pipeline validation ──────────────────────────────────────────────

def _pipeline_events_ok():
    return [
        _event(1, "SYMBOL_SCANNED", "SCANNER"),
        _event(2, "BUY_GENERATED", "AI_DECISION", payload={"confidence": 72}),
        _event(3, "BUY_GENERATED", "AI_DECISION", symbol="TCS",
               payload={"confidence": 65}),
        _event(4, "ORDER_SUBMITTED", "EXECUTION"),
        _event(5, "ORDER_EXECUTED", "EXECUTION",
               payload={"trade_id": "T1", "fill_price": 100.0}),
        _event(6, "ORDER_SUBMITTED", "EXECUTION", symbol="TCS"),
        _event(7, "ORDER_CANCELLED", "EXECUTION", symbol="TCS"),
        _event(8, "POSITION_OPENED", "PORTFOLIO"),
        _event(9, "POSITION_CLOSED", "PORTFOLIO"),
    ]


class TestPipelineValidation(unittest.TestCase):
    def test_conserved_pipeline_pass(self):
        r = ve.validate_pipeline(events=_pipeline_events_ok())
        self.assertEqual(r["verdict"], "PASS")

    def test_unresolved_order_fail(self):
        ev = [e for e in _pipeline_events_ok()
              if e["event_type"] != "ORDER_CANCELLED"]
        r = ve.validate_pipeline(events=ev)
        self.assertEqual(r["verdict"], "FAIL")
        bad = [c for c in r["checks"] if c["check"] == "order_conservation"]
        self.assertEqual(bad[0]["status"], "FAIL")

    def test_conflicting_decisions_fail(self):
        ev = _pipeline_events_ok() + [
            _event(10, "IGNORE_GENERATED", "AI_DECISION")]  # same scan+symbol
        r = ve.validate_pipeline(events=ev)
        bad = [c for c in r["checks"]
               if c["check"] == "deterministic_decisions"]
        self.assertEqual(bad[0]["status"], "FAIL")

    def test_no_events_insufficient(self):
        r = ve.validate_pipeline(events=[])
        self.assertEqual(r["verdict"], "INSUFFICIENT_EVIDENCE")

    def test_rejected_order_is_valid_terminal_outcome(self):
        ev = _pipeline_events_ok() + [
            _event(10, "ORDER_REJECTED", "EXECUTION", symbol="INFY")]
        r = ve.validate_pipeline(events=ev)
        self.assertEqual(r["verdict"], "PASS")

    def test_swapped_resolutions_fail_despite_equal_totals(self):
        # aggregate counts balance (2 submitted, 2 resolved) but one order is
        # double-resolved and the other never resolves — must FAIL
        ev = [
            _event(1, "ORDER_SUBMITTED", "EXECUTION", symbol="RELIANCE"),
            _event(2, "ORDER_SUBMITTED", "EXECUTION", symbol="TCS"),
            _event(3, "ORDER_EXECUTED", "EXECUTION", symbol="RELIANCE"),
            _event(4, "ORDER_CANCELLED", "EXECUTION", symbol="RELIANCE"),
        ]
        r = ve.validate_pipeline(events=ev)
        bad = [c for c in r["checks"] if c["check"] == "order_conservation"]
        self.assertEqual(bad[0]["status"], "FAIL")

    def test_resolution_without_submission_fail(self):
        ev = [_event(1, "ORDER_EXECUTED", "EXECUTION", symbol="INFY")]
        r = ve.validate_pipeline(events=ev)
        bad = [c for c in r["checks"] if c["check"] == "order_conservation"]
        self.assertEqual(bad[0]["status"], "FAIL")

    def test_uncorrelatable_order_events_fail(self):
        ev = _pipeline_events_ok() + [
            _event(10, "ORDER_SUBMITTED", "EXECUTION", symbol="",
                   scan_id="S-1")]
        r = ve.validate_pipeline(events=ev)
        bad = [c for c in r["checks"]
               if c["check"] == "order_events_correlatable"]
        self.assertEqual(bad[0]["status"], "FAIL")


# ── Part I: portfolio validation ─────────────────────────────────────────────

def _balanced_fixture():
    cap = 50_000.0
    ledger = [_paper_trade(i, pnl=50.0) for i in range(1, 6)]   # realized 250
    ledger.append(_paper_trade(9, status="OPEN"))               # 10 × 100
    snapshot = {
        "initial_capital": cap, "cash": 49_250.0,
        "invested_value": 1_000.0, "realized_pnl": 250.0,
        "unrealized_pnl": 50.0, "equity": 50_300.0,
        "equity_complete": True,
        "open_position_count": 1, "closed_trade_count": 5,
        "portfolio_version": "6:x",
        "positions": [{"symbol": "SYM9", "quantity": 10, "avg_price": 100.0,
                       "cost": 1_000.0, "market_value": 1_050.0,
                       "unrealized_pnl": 50.0}],
        "sector_exposure": {"UNKNOWN": 1_000.0},
    }
    return ledger, snapshot


class TestPortfolioValidation(unittest.TestCase):
    def test_exact_balance_pass(self):
        ledger, snap = _balanced_fixture()
        r = ve.validate_portfolio(ledger_rows=ledger, snapshot=snap)
        self.assertEqual(r["verdict"], "PASS")

    def test_cash_drift_fail(self):
        ledger, snap = _balanced_fixture()
        snap["cash"] = 49_240.0          # ₹10 off — must fail exactly
        r = ve.validate_portfolio(ledger_rows=ledger, snapshot=snap)
        self.assertEqual(r["verdict"], "FAIL")
        bad = [c for c in r["checks"] if c["check"] == "cash_balances"]
        self.assertEqual(bad[0]["status"], "FAIL")

    def test_incomplete_marks_warn_not_pass(self):
        ledger, snap = _balanced_fixture()
        snap["equity_complete"] = False
        r = ve.validate_portfolio(ledger_rows=ledger, snapshot=snap)
        self.assertEqual(r["verdict"], "WARN")


# ── Part J: replay validation ────────────────────────────────────────────────

class TestReplayValidation(unittest.TestCase):
    def test_orchestrates_replay_verify_pass(self):
        vr = {"ok": True, "run_id": "BT-1", "verdict": "PASS",
              "checks": [{"check": "no_duplicate_events", "status": "PASS",
                          "detail": "ok"}]}
        r = ve.validate_replay(run_id="BT-1", verify_result=vr)
        self.assertEqual(r["verdict"], "PASS")

    def test_replay_mismatch_fail(self):
        vr = {"ok": True, "run_id": "BT-1", "verdict": "FAIL",
              "checks": [{"check": "execution_matches_ledger",
                          "status": "FAIL", "detail": "missing exit"}]}
        r = ve.validate_replay(run_id="BT-1", verify_result=vr)
        self.assertEqual(r["verdict"], "FAIL")

    def test_no_runs_insufficient(self):
        with mock.patch("backtest_portfolio.list_runs", return_value=[]):
            r = ve.validate_replay()
        self.assertEqual(r["verdict"], "INSUFFICIENT_EVIDENCE")


# ── Part K: AI decision validation ───────────────────────────────────────────

class TestAIDecisionValidation(unittest.TestCase):
    def _decisions(self):
        return [
            _event(1, "BUY_GENERATED", "AI_DECISION",
                   payload={"confidence": 72.0}),
            _event(2, "WATCH_GENERATED", "AI_DECISION", symbol="TCS",
                   payload={"confidence": 55.0}),
        ]

    def test_deterministic_decisions_pass(self):
        r = ve.validate_ai_decisions(events=self._decisions(),
                                     stored_validation={"verdict": "MATCH"})
        self.assertEqual(r["verdict"], "PASS")

    def test_conflicting_stored_decisions_fail(self):
        ev = self._decisions() + [
            _event(3, "IGNORE_GENERATED", "AI_DECISION",
                   payload={"confidence": 72.0})]   # RELIANCE@S-1 conflict
        r = ve.validate_ai_decisions(events=ev,
                                     stored_validation={"verdict": "MATCH"})
        self.assertEqual(r["verdict"], "FAIL")

    def test_confidence_out_of_bounds_fail(self):
        ev = self._decisions()
        ev[0]["payload"]["confidence"] = 150.0
        r = ve.validate_ai_decisions(events=ev,
                                     stored_validation={"verdict": "MATCH"})
        self.assertEqual(r["verdict"], "FAIL")

    def test_missing_stored_validation_warn_never_pass(self):
        r = ve.validate_ai_decisions(events=self._decisions(),
                                     stored_validation={})
        self.assertEqual(r["verdict"], "WARN")

    def test_stored_mismatch_fail(self):
        r = ve.validate_ai_decisions(
            events=self._decisions(),
            stored_validation={"verdict": "MISMATCH", "mismatches": [{}]})
        self.assertEqual(r["verdict"], "FAIL")

    def test_no_decisions_insufficient(self):
        r = ve.validate_ai_decisions(events=[], stored_validation={})
        self.assertEqual(r["verdict"], "INSUFFICIENT_EVIDENCE")


# ── Part L: performance validation ───────────────────────────────────────────

class TestPerformanceValidation(unittest.TestCase):
    def _trades(self):
        return [
            _paper_trade(1, pnl=200, conf=80),
            _paper_trade(2, pnl=-50, conf=55),
            _paper_trade(3, pnl=120, conf=90),
            _paper_trade(4, pnl=-80, conf=65),
            _paper_trade(5, pnl=150, conf=75),
            _paper_trade(6, pnl=60, conf=72, strategy="MEANREV"),
        ]

    def test_consistent_metrics_pass(self):
        r = ve.validate_performance(trades=self._trades(), capital=50_000.0)
        self.assertEqual(r["verdict"], "PASS")
        self.assertEqual(r["total_pnl"], 400.0)
        strat = [c for c in r["checks"]
                 if c["check"] == "strategy_ranking_conserved"]
        self.assertEqual(strat[0]["status"], "PASS")

    def test_missing_capital_warn(self):
        r = ve.validate_performance(trades=self._trades(), capital=0.0)
        self.assertEqual(r["verdict"], "WARN")

    def test_insufficient_trades(self):
        r = ve.validate_performance(trades=self._trades()[:3],
                                    capital=50_000.0)
        self.assertEqual(r["verdict"], "INSUFFICIENT_EVIDENCE")


# ── Part M: certification aggregation ────────────────────────────────────────

def _domain_results(**overrides):
    out = {d: {"ok": True, "domain": d, "verdict": "PASS", "checks": []}
           for d in ce.DOMAIN_WEIGHTS}
    for d, v in overrides.items():
        out[d] = {"ok": True, "domain": d, "verdict": v, "checks": []}
    return out


class TestCertification(unittest.TestCase):
    def test_all_pass_ready_100(self):
        r = ce.run_certification(validator_results=_domain_results(),
                                 persist=False)
        self.assertEqual(r["verdict"], "READY")
        self.assertEqual(r["certification_pct"], 100.0)
        self.assertTrue(r["ready_for_continuous_paper_trading"])
        self.assertEqual(r["blockers"], [])

    def test_warn_never_treated_as_pass(self):
        r = ce.run_certification(
            validator_results=_domain_results(performance="WARN"),
            persist=False)
        self.assertEqual(r["verdict"], "NOT_READY")
        self.assertFalse(r["ready_for_continuous_paper_trading"])
        self.assertIn("performance: WARN", r["blockers"])
        self.assertEqual(r["certification_pct"], 95.0)   # half credit only

    def test_fail_blocks_ready(self):
        r = ce.run_certification(
            validator_results=_domain_results(portfolio="FAIL"),
            persist=False)
        self.assertEqual(r["verdict"], "NOT_READY")
        self.assertEqual(r["certification_pct"], 80.0)

    def test_insufficient_evidence_blocks_ready(self):
        r = ce.run_certification(
            validator_results=_domain_results(
                replay="INSUFFICIENT_EVIDENCE"),
            persist=False)
        self.assertEqual(r["verdict"], "NOT_READY")
        self.assertIn("replay: INSUFFICIENT_EVIDENCE", r["blockers"])


class TestCertificationPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patches = [
            mock.patch.object(ce, "db_available", lambda: False),
            mock.patch.object(ce, "_CERT_FILE",
                              os.path.join(self.tmp, "certs.json")),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_append_only_history(self):
        r1 = ce.run_certification(validator_results=_domain_results())
        r2 = ce.run_certification(
            validator_results=_domain_results(performance="WARN"))
        hist = ce.list_certifications()
        self.assertEqual(len(hist["items"]), 2)
        got = ce.get_certification(r1["cert_id"])
        self.assertEqual(got["verdict"], "READY")
        # re-running never mutates an earlier row
        self.assertNotEqual(r1["cert_id"], r2["cert_id"])
        again = ce.get_certification(r1["cert_id"])
        self.assertEqual(again["certification_pct"],
                         r1["certification_pct"])

    def test_unknown_cert_id(self):
        r = ce.get_certification("CERT-nope")
        self.assertFalse(r["ok"])

    def test_prune_keeps_newest_runs_regardless_of_age(self):
        """Old rows beyond retention are deleted, but the newest keep_last
        runs are NEVER touched even if they are older than the age cutoff."""
        old_ts = "2020-01-01T00:00:00.000Z"
        rows = [{"cert_id": f"CERT-old-{i}", "created_at": old_ts,
                 "certification_pct": 50.0, "verdict": "NOT_READY",
                 "domains": {}} for i in range(6)]
        for r in rows:
            ce._append_file(ce._CERT_FILE, r)
        out = ce.prune_certifications(days=30, keep_last=3)
        self.assertEqual(out["deleted"], 3)
        remaining = ce._load_file(ce._CERT_FILE)
        self.assertEqual(len(remaining), 3)
        # the newest 3 survive despite being ancient
        self.assertEqual({r["cert_id"] for r in remaining},
                         {"CERT-old-3", "CERT-old-4", "CERT-old-5"})
        # idempotent: a second prune deletes nothing more
        self.assertEqual(ce.prune_certifications(days=30,
                                                 keep_last=3)["deleted"], 0)

    def test_prune_never_deletes_recent_runs(self):
        r1 = ce.run_certification(validator_results=_domain_results())
        out = ce.prune_certifications(days=30, keep_last=1)
        self.assertEqual(out["deleted"], 0)
        self.assertEqual(ce.get_certification(r1["cert_id"])["cert_id"],
                         r1["cert_id"])

    def test_persist_path_invokes_retention(self):
        with mock.patch.object(ce, "prune_certifications") as prune:
            ce.run_certification(validator_results=_domain_results())
            prune.assert_called_once()
        # persist=False must not prune (read-only preview runs)
        with mock.patch.object(ce, "prune_certifications") as prune:
            ce.run_certification(validator_results=_domain_results(),
                                 persist=False)
            prune.assert_not_called()

    def test_prune_never_raises(self):
        with mock.patch.object(ce, "_load_file",
                               side_effect=RuntimeError("boom")):
            out = ce.prune_certifications()
            self.assertTrue(out.get("error"))

    def test_file_fallback_append_prunes_old_but_keeps_fresh(self):
        """Append-time retention uses the SAME rule as the DB path: old rows
        beyond keep_last go, but fresh (within-retention) rows are never
        discarded even when there are more than keep_last of them."""
        fresh_ts = ce._now_iso()
        with mock.patch.object(ce, "RETENTION_KEEP_LAST", 5):
            # 9 ancient rows → capped to the protected newest 5
            for i in range(9):
                ce._append_file(ce._CERT_FILE,
                                {"cert_id": f"OLD{i}",
                                 "created_at": f"2020-01-0{i + 1}"})
            self.assertEqual(len(ce._load_file(ce._CERT_FILE)), 5)
            # 8 fresh rows all survive despite exceeding keep_last
            for i in range(8):
                ce._append_file(ce._CERT_FILE,
                                {"cert_id": f"NEW{i}",
                                 "created_at": fresh_ts})
            rows = ce._load_file(ce._CERT_FILE)
            self.assertEqual(
                sum(1 for r in rows if r["cert_id"].startswith("NEW")), 8)

    def test_env_retention_values_are_clamped(self):
        with mock.patch.dict(os.environ, {"X_DAYS": "0", "X_KEEP": "-3",
                                          "X_BAD": "banana"}):
            self.assertEqual(ce._env_int("X_DAYS", 30), 1)
            self.assertEqual(ce._env_int("X_KEEP", 50), 1)
            self.assertEqual(ce._env_int("X_BAD", 50), 50)
            self.assertEqual(ce._env_int("X_MISSING", 30), 30)


class TestIntegritySpotChecks(unittest.TestCase):
    def test_learning_advisory_only(self):
        r = ce.check_learning_engine()
        self.assertIn(r["verdict"], ("PASS", "FAIL"))

    def test_mission_control_snapshot_identity(self):
        # Wed 2026-08-05 10:00 IST — snapshot from that morning is fresh
        now = datetime(2026, 8, 5, 4, 30, tzinfo=timezone.utc)
        r = ce.check_mission_control(snapshot={
            "scan_id": "S-1", "snapshot_ts": "2026-08-05T04:00:00Z"},
            now=now)
        self.assertEqual(r["verdict"], "PASS")

    def test_mission_control_no_snapshot_insufficient(self):
        r = ce.check_mission_control(snapshot={})
        self.assertEqual(r["verdict"], "INSUFFICIENT_EVIDENCE")

    def test_mission_control_stale_snapshot_warns(self):
        # Sat 2026-08-08 → latest expected session Fri 2026-08-07; a
        # Wednesday snapshot is stale and must WARN (blocks READY)
        now = datetime(2026, 8, 8, 6, 0, tzinfo=timezone.utc)
        r = ce.check_mission_control(snapshot={
            "scan_id": "S-1", "snapshot_ts": "2026-08-05T04:00:00Z"},
            now=now)
        self.assertEqual(r["verdict"], "WARN")
        c = [x for x in r["checks"]
             if x["check"] == "snapshot_session_fresh"][0]
        self.assertEqual(c["status"], "WARN")

    def test_mission_control_friday_snapshot_fresh_on_weekend(self):
        now = datetime(2026, 8, 8, 6, 0, tzinfo=timezone.utc)  # Sat
        r = ce.check_mission_control(snapshot={
            "scan_id": "S-1", "snapshot_ts": "2026-08-07T03:30:00Z"},
            now=now)
        self.assertEqual(r["verdict"], "PASS")

    def test_mission_control_monday_pre_open_accepts_friday(self):
        # Mon 08:00 IST (before the 09:15 publish cutoff) → Friday's
        # snapshot is still the most recent session
        now = datetime(2026, 8, 10, 2, 30, tzinfo=timezone.utc)
        r = ce.check_mission_control(snapshot={
            "scan_id": "S-1", "snapshot_ts": "2026-08-07T03:30:00Z"},
            now=now)
        self.assertEqual(r["verdict"], "PASS")

    def test_mission_control_monday_post_open_warns_on_friday(self):
        # Mon 10:00 IST → today's session snapshot is expected
        now = datetime(2026, 8, 10, 4, 30, tzinfo=timezone.utc)
        r = ce.check_mission_control(snapshot={
            "scan_id": "S-1", "snapshot_ts": "2026-08-07T03:30:00Z"},
            now=now)
        self.assertEqual(r["verdict"], "WARN")

    def test_mission_control_holiday_accepts_previous_session(self):
        # Mon 2026-09-14 is Ganesh Chaturthi (NSE holiday). Midday on the
        # holiday, Friday 2026-09-11's snapshot is the latest real session
        # and must certify as fresh.
        now = datetime(2026, 9, 14, 6, 30, tzinfo=timezone.utc)
        r = ce.check_mission_control(snapshot={
            "scan_id": "S-1", "snapshot_ts": "2026-09-11T03:30:00Z"},
            now=now)
        self.assertEqual(r["verdict"], "PASS")

    def test_mission_control_holiday_still_warns_on_older_snapshot(self):
        now = datetime(2026, 9, 14, 6, 30, tzinfo=timezone.utc)  # holiday
        r = ce.check_mission_control(snapshot={
            "scan_id": "S-1", "snapshot_ts": "2026-09-10T03:30:00Z"},
            now=now)  # Thursday — one session too old
        self.assertEqual(r["verdict"], "WARN")

    def test_mission_control_day_after_holiday_pre_open(self):
        # Tue 2026-09-15 08:00 IST (before publish cutoff, after Monday
        # holiday) → Friday's snapshot is still the most recent session
        now = datetime(2026, 9, 15, 2, 30, tzinfo=timezone.utc)
        r = ce.check_mission_control(snapshot={
            "scan_id": "S-1", "snapshot_ts": "2026-09-11T03:30:00Z"},
            now=now)
        self.assertEqual(r["verdict"], "PASS")

    def test_mission_control_day_after_holiday_post_open(self):
        # Tue 2026-09-15 10:00 IST → today's snapshot is expected
        now = datetime(2026, 9, 15, 4, 30, tzinfo=timezone.utc)
        r = ce.check_mission_control(snapshot={
            "scan_id": "S-1", "snapshot_ts": "2026-09-11T03:30:00Z"},
            now=now)
        self.assertEqual(r["verdict"], "WARN")

    def test_mission_control_unparseable_ts_warns(self):
        r = ce.check_mission_control(snapshot={
            "scan_id": "S-1", "snapshot_ts": "not-a-date"})
        # identity check FAILs? no — ts is truthy so identity PASSes,
        # freshness must WARN because age is unknowable
        self.assertEqual(r["verdict"], "WARN")


class TestBacktestFreshness(unittest.TestCase):
    _VR = {"ok": True, "run_id": "BT-1", "verdict": "PASS",
           "checks": [{"check": "no_duplicate_events", "status": "PASS",
                       "detail": "ok"}]}

    def test_replay_fresh_run_passes(self):
        run = {"completed_at": (datetime.now(timezone.utc)
                                - timedelta(days=1)).isoformat()}
        r = ve.validate_replay(run_id="BT-1", verify_result=self._VR,
                               run=run)
        self.assertEqual(r["verdict"], "PASS")

    def test_replay_stale_run_warns(self):
        run = {"completed_at": (datetime.now(timezone.utc)
                                - timedelta(days=30)).isoformat()}
        r = ve.validate_replay(run_id="BT-1", verify_result=self._VR,
                               run=run)
        self.assertEqual(r["verdict"], "WARN")
        c = [x for x in r["checks"]
             if x["check"] == "backtest_run_fresh"][0]
        self.assertEqual(c["status"], "WARN")

    def test_replay_configurable_age(self):
        run = {"completed_at": (datetime.now(timezone.utc)
                                - timedelta(days=10)).isoformat()}
        stale = ve.validate_replay(run_id="BT-1", verify_result=self._VR,
                                   run=run, max_age_days=7)
        fresh = ve.validate_replay(run_id="BT-1", verify_result=self._VR,
                                   run=run, max_age_days=14)
        self.assertEqual(stale["verdict"], "WARN")
        self.assertEqual(fresh["verdict"], "PASS")

    def test_replay_run_without_timestamp_warns(self):
        r = ve.validate_replay(run_id="BT-1", verify_result=self._VR,
                               run={})
        self.assertEqual(r["verdict"], "WARN")

    def test_replay_no_run_record_skips_freshness(self):
        r = ve.validate_replay(run_id="BT-1", verify_result=self._VR)
        self.assertEqual(r["verdict"], "PASS")
        self.assertFalse([x for x in r["checks"]
                          if x["check"] == "backtest_run_fresh"])

    def test_ai_decisions_stale_run_warns(self):
        events = [
            {"id": 1, "event_type": "BUY_GENERATED", "stage": "AI_DECISION",
             "scan_id": "S-1", "symbol": "RELIANCE",
             "payload": {"confidence": 72.0}}]
        run = {"completed_at": (datetime.now(timezone.utc)
                                - timedelta(days=30)).isoformat()}
        r = ve.validate_ai_decisions(events=events,
                                     stored_validation={"verdict": "MATCH"},
                                     run=run)
        self.assertEqual(r["verdict"], "WARN")

    def test_future_dated_run_warns(self):
        run = {"completed_at": (datetime.now(timezone.utc)
                                + timedelta(days=3)).isoformat()}
        r = ve.validate_replay(run_id="BT-1", verify_result=self._VR,
                               run=run)
        self.assertEqual(r["verdict"], "WARN")

    def test_sub_minute_future_run_warns(self):
        run = {"completed_at": (datetime.now(timezone.utc)
                                + timedelta(seconds=30)).isoformat()}
        r = ve.validate_replay(run_id="BT-1", verify_result=self._VR,
                               run=run)
        self.assertEqual(r["verdict"], "WARN")

    def test_sub_minute_future_snapshot_warns(self):
        now = datetime(2026, 8, 5, 4, 30, tzinfo=timezone.utc)  # Wed
        r = ce.check_mission_control(snapshot={
            "scan_id": "S-1", "snapshot_ts": "2026-08-05T04:30:30Z"},
            now=now)
        self.assertEqual(r["verdict"], "WARN")

    def test_future_dated_snapshot_warns(self):
        now = datetime(2026, 8, 5, 4, 30, tzinfo=timezone.utc)  # Wed
        r = ce.check_mission_control(snapshot={
            "scan_id": "S-1", "snapshot_ts": "2026-08-06T04:00:00Z"},
            now=now)
        self.assertEqual(r["verdict"], "WARN")

    def test_certification_blocks_ready_on_stale_run(self):
        stale = {"run_id": "BT-1", "status": "COMPLETED",
                 "completed_at": (datetime.now(timezone.utc)
                                  - timedelta(days=30)).isoformat()}
        vr = dict(self._VR)
        events = [
            {"id": 1, "event_type": "BUY_GENERATED", "stage": "AI_DECISION",
             "scan_id": "S-1", "symbol": "RELIANCE",
             "payload": {"confidence": 72.0}}]
        results = _domain_results()
        results["replay"] = ve.validate_replay(
            run_id="BT-1", verify_result=vr, run=stale)
        results["ai_decision"] = ve.validate_ai_decisions(
            events=events, stored_validation={"verdict": "MATCH"},
            run=stale)
        r = ce.run_certification(validator_results=results, persist=False)
        self.assertEqual(r["verdict"], "NOT_READY")
        self.assertIn("replay: WARN", r["blockers"])
        self.assertIn("ai_decision: WARN", r["blockers"])

    def test_ai_decisions_fresh_run_passes(self):
        events = [
            {"id": 1, "event_type": "BUY_GENERATED", "stage": "AI_DECISION",
             "scan_id": "S-1", "symbol": "RELIANCE",
             "payload": {"confidence": 72.0}}]
        run = {"completed_at": (datetime.now(timezone.utc)
                                - timedelta(days=1)).isoformat()}
        r = ve.validate_ai_decisions(events=events,
                                     stored_validation={"verdict": "MATCH"},
                                     run=run)
        self.assertEqual(r["verdict"], "PASS")


# ── Part P: long-duration validation ─────────────────────────────────────────

class TestLongDuration(unittest.TestCase):
    NOW = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)

    def _ledger(self, n=6):
        rows = []
        for i in range(1, n + 1):
            rows.append(_paper_trade(
                i, pnl=100.0 if i % 2 else -40.0, conf=70.0,
                fill_ts=f"2026-08-0{min(i, 7)}T04:00:00Z",
                exit_ts=f"2026-08-0{min(i, 7)}T08:00:00Z"))
        rows[0]["fill_ts"] = "2026-08-01T04:00:00Z"   # 7 days of history
        return rows

    def test_scored_window(self):
        scans = ([{"event_type": "SCAN_COMPLETED",
                   "ts": "2026-08-05T04:00:00Z"}] * 9
                 + [{"event_type": "SCAN_FAILED",
                     "ts": "2026-08-05T05:00:00Z"}])
        r = ce.long_duration_validation("1w", ledger_rows=self._ledger(),
                                        scan_events=scans, now=self.NOW)
        self.assertIn(r["verdict"], ("PASS", "WARN"))
        self.assertEqual(r["scores"]["reliability"], 90.0)
        self.assertIsNotNone(r["scores"]["stability"])
        self.assertIn(r["recommendation"],
                      ("CONTINUE_PAPER_TRADING", "MONITOR_CLOSELY",
                       "REVIEW_REQUIRED"))

    def test_insufficient_trades(self):
        r = ce.long_duration_validation("1w", ledger_rows=self._ledger(3),
                                        scan_events=[], now=self.NOW)
        self.assertEqual(r["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertIsNone(r["scores"])

    def test_insufficient_history_never_extrapolates(self):
        r = ce.long_duration_validation("1y", ledger_rows=self._ledger(),
                                        scan_events=[], now=self.NOW)
        self.assertEqual(r["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(r["recommendation"], "INSUFFICIENT_EVIDENCE")

    def test_unknown_window_rejected(self):
        r = ce.long_duration_validation("5y")
        self.assertFalse(r["ok"])


# ── SAFETY (spec Part Q): no write path into live trading state ─────────────

FORBIDDEN_CALLS = {
    "update_settings", "save_settings", "set_settings", "save_state",
    "update_stop_loss", "execute_buy", "execute_sell", "reset_portfolio",
    "create_paper_entry", "record_exit", "record_fill", "run_entries",
    "close_trade", "open_trade",
    "emit", "emit_many", "prune_events",
    "create_run", "update_run", "claim_run", "execute_run",
    "approve_adjustment", "apply_adjustment", "promote_challenger",
    "kv_set",
}
FORBIDDEN_IMPORTS = {"paper_trader", "phase20_exits", "backtest_runner",
                     "live_scan_engine"}
VALIDATION_FILES = ["validation_engines.py", "certification_engine.py"]


class TestNoWritePathSafety(unittest.TestCase):
    """Prove by AST inspection that the validation & certification engines
    never call anything that mutates the live portfolio, paper ledger, event
    store, backtest runs, settings, or strategy config."""

    def _tree(self, filename):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            filename)
        with open(path) as f:
            return ast.parse(f.read(), filename=filename)

    def test_no_forbidden_calls(self):
        for fname in VALIDATION_FILES:
            tree = self._tree(fname)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    name = (func.attr if isinstance(func, ast.Attribute)
                            else func.id if isinstance(func, ast.Name)
                            else None)
                    self.assertNotIn(
                        name, FORBIDDEN_CALLS,
                        f"{fname}: forbidden mutating call '{name}'"
                        f" at line {node.lineno}")

    def test_no_forbidden_imports(self):
        for fname in VALIDATION_FILES:
            tree = self._tree(fname)
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    mods = [node.module or ""]
                for m in mods:
                    self.assertNotIn(
                        m.split(".")[0], FORBIDDEN_IMPORTS,
                        f"{fname}: forbidden import '{m}'"
                        f" at line {node.lineno}")

    def test_sql_writes_limited_to_certification_table(self):
        """Every INSERT targets certification_runs only; no UPDATE/DROP/
        TRUNCATE anywhere. DELETE is permitted ONLY inside
        prune_certifications (the single sanctioned retention path) and only
        against certification_runs — everywhere else history stays
        append-only by construction."""
        for fname in VALIDATION_FILES:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                fname)
            with open(path) as f:
                tree = ast.parse(f.read())
            # Collect string constants inside the sanctioned prune function.
            prune_strings = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) \
                        and node.name == "prune_certifications":
                    for sub in ast.walk(node):
                        if isinstance(sub, ast.Constant) \
                                and isinstance(sub.value, str):
                            prune_strings.add(sub.value)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) \
                        and isinstance(node.value, str):
                    s = node.value.upper()
                    if "INSERT INTO" in s:
                        self.assertIn("CERTIFICATION_RUNS", s,
                                      f"{fname}: INSERT into non-cert "
                                      f"table: {node.value}")
                    if "DELETE FROM" in s:
                        self.assertIn(
                            node.value, prune_strings,
                            f"{fname}: DELETE outside prune_certifications: "
                            f"{node.value[:80]}")
                        self.assertIn("CERTIFICATION_RUNS", s,
                                      f"{fname}: prune DELETE must target "
                                      f"certification_runs: {node.value[:80]}")
                    if re.search(r"\bUPDATE\s+\w+\s+SET\b", s) \
                            or "DROP TABLE" in s or "TRUNCATE " in s:
                        self.fail(f"forbidden SQL verb in {fname}:"
                                  f" {node.value[:80]}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
