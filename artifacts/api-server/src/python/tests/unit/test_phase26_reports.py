"""
Phase 26D — Reports & Readiness Dashboard unit tests.

Covers: daily report assembly (pure, fixture-driven), verdict logic,
acceptance criteria, five-day IST windowing (weekends + holidays),
five-day verdict logic, readiness verdict logic, the append-only daily
report store (file fallback), and the Phase 23.9 "readiness" export.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone, date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import phase26_reports as pr  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))

# Friday 2026-08-07 18:00 IST (post-close on a trading day).
NOW = datetime(2026, 8, 7, 12, 30, tzinfo=timezone.utc)


def weekdays_only(d: date) -> bool:
    return d.weekday() < 5


CERT = {
    "cert_id": "CERT-abc", "created_at": "2026-08-07T11:00:00Z",
    "certification_pct": 87.5, "verdict": "NOT_READY",
    "blockers": ["replay: WARN"],
    "domains": {
        "ai_decision": {"verdict": "PASS"},
        "portfolio": {"verdict": "PASS"},
        "replay": {"verdict": "WARN"},
        "learning": {"verdict": "PASS"},
    },
}

INPUTS_HEALTHY = {
    "live": {"verdict": "OK", "generated_at": "2026-08-07T09:00:00Z",
             "subsystem_counts": {"ACTIVE": 6}},
    "open_issues": [],
    "e2e": {"run_id": "e2e-1", "scan_id": "scan-1", "verdict": "PASS",
            "created_at": "2026-08-07T09:30:00Z"},
    "recovery": {"verdict": "PASS", "generated_at": "2026-08-07T10:00:00Z"},
    "performance": {"verdict": "PASS", "generated_at": "2026-08-07T10:00:00Z",
                    "grade_counts": {"PASS": 7, "WARN": 0, "FAIL": 0,
                                     "INSUFFICIENT": 0},
                    "metrics": [{"metric": "scan_duration_s", "value": 60,
                                 "grade": "PASS", "detail": "ok"}]},
    "quality": {"verdict": "PASS", "scan_id": "scan-1",
                "generated_at": "2026-08-07T10:00:00Z"},
    "certification": {**CERT, "verdict": "READY", "blockers": [],
                      "domains": {k: {"verdict": "PASS"}
                                  for k in CERT["domains"]}},
}


def daily(passed=True, verdict="PASS", d="2026-08-07", critical=0,
          failed_sections=None):
    return {"report_date": d, "verdict": verdict,
            "acceptance": {"passed": passed,
                           "critical_open_issues": critical,
                           "failed_sections": failed_sections or []}}


class TestDailyReportAssembly(unittest.TestCase):
    def test_all_healthy(self):
        r = pr.build_daily_report(INPUTS_HEALTHY, now=NOW)
        self.assertEqual(r["verdict"], "PASS")
        self.assertEqual(r["report_date"], "2026-08-07")
        self.assertEqual(set(r["sections"]), set(pr.SECTIONS))
        for s in r["sections"].values():
            self.assertEqual(s["status"], "PASS")
        self.assertEqual(r["validation_score"], 100.0)
        self.assertTrue(r["acceptance"]["passed"])
        self.assertEqual(r["open_issues"]["critical"], 0)
        self.assertTrue(r["advisory_only"])

    def test_fail_section_and_critical_issue(self):
        inputs = dict(INPUTS_HEALTHY)
        inputs["quality"] = {"verdict": "FAIL", "scan_id": "scan-1",
                             "generated_at": "2026-08-07T10:00:00Z"}
        inputs["open_issues"] = [
            {"severity": "CRITICAL", "category": "CONSISTENCY",
             "key": "k", "title": "mismatch"},
            {"severity": "WARNING", "category": "SYSTEM",
             "key": "w", "title": "warn"},
        ]
        r = pr.build_daily_report(inputs, now=NOW)
        self.assertEqual(r["verdict"], "FAIL")
        self.assertEqual(r["sections"]["trading"]["status"], "FAIL")
        self.assertFalse(r["acceptance"]["passed"])
        self.assertEqual(r["acceptance"]["critical_open_issues"], 1)
        self.assertIn("trading", r["acceptance"]["failed_sections"])
        self.assertTrue(any("trading" in x for x in r["recommendations"]))
        self.assertTrue(any("CRITICAL" in x for x in r["recommendations"]))

    def test_missing_evidence_is_warn_never_pass(self):
        r = pr.build_daily_report({}, now=NOW)
        self.assertEqual(r["verdict"], "WARN")
        for s in r["sections"].values():
            self.assertEqual(s["status"], "INSUFFICIENT_EVIDENCE")
        self.assertIsNone(r["validation_score"])
        self.assertEqual(r["sections_evaluated"], 0)
        # FAIL-SAFE: missing evidence can NEVER pass the acceptance day.
        self.assertFalse(r["acceptance"]["passed"])
        self.assertFalse(r["acceptance"]["evidence_complete"])
        self.assertEqual(sorted(r["acceptance"]["insufficient_sections"]),
                         sorted(pr.SECTIONS))
        self.assertTrue(any("No persisted evidence" in x
                            for x in r["recommendations"]))

    def test_stale_evidence_is_insufficient(self):
        # All inputs healthy but dated the PREVIOUS day — prior-day PASSes
        # must never count as today's evidence.
        stale = json.loads(json.dumps(INPUTS_HEALTHY))
        for k in ("live", "e2e", "recovery", "performance", "quality"):
            key = "created_at" if k == "e2e" else "generated_at"
            stale[k][key] = "2026-08-06T10:00:00Z"
        stale["certification"]["created_at"] = "2026-08-06T11:00:00Z"
        r = pr.build_daily_report(stale, now=NOW)
        for name, s in r["sections"].items():
            self.assertEqual(s["status"], "INSUFFICIENT_EVIDENCE", name)
            self.assertTrue(s["stale"], name)
        self.assertFalse(r["acceptance"]["passed"])

    def test_five_unknown_days_never_yield_pass_or_ready(self):
        # Regression: five WARN reports built from empty inputs must hold
        # the five-day window at PENDING and readiness below READY.
        dates = ["2026-08-03", "2026-08-04", "2026-08-05",
                 "2026-08-06", "2026-08-07"]
        reports = {d: pr.build_daily_report({}, report_date=d, now=NOW)
                   for d in dates}
        fd = pr.build_five_day_acceptance(now=NOW, reports=reports,
                                          trading_day_fn=weekdays_only)
        self.assertEqual(fd["verdict"], "PENDING")
        self.assertEqual(fd["days_passed"], 0)
        r = pr.build_readiness_report(
            now=NOW, five_day=fd,
            certification={"cert_id": "c", "verdict": "READY",
                           "certification_pct": 100.0},
            performance={"verdict": "PASS"}, open_issues=[])
        self.assertNotEqual(r["verdict"], "READY")
        self.assertFalse(r["ready"])

    def test_warn_sections_pass_acceptance(self):
        inputs = dict(INPUTS_HEALTHY)
        inputs["certification"] = CERT  # replay WARN
        r = pr.build_daily_report(inputs, now=NOW)
        self.assertEqual(r["verdict"], "WARN")
        self.assertEqual(r["sections"]["replay"]["status"], "WARN")
        self.assertTrue(r["acceptance"]["passed"])
        self.assertEqual(r["validation_score"],
                         round((6 * 100 + 50) / 7, 1))

    def test_norm_verdict_unknown_is_insufficient(self):
        self.assertEqual(pr._norm_verdict("SOMETHING_ELSE"),
                         "INSUFFICIENT_EVIDENCE")
        self.assertEqual(pr._norm_verdict(None), "INSUFFICIENT_EVIDENCE")
        self.assertEqual(pr._norm_verdict("DEGRADED"), "WARN")
        self.assertEqual(pr._norm_verdict("DOWN"), "FAIL")
        self.assertEqual(pr._norm_verdict("HEALTHY"), "PASS")


class TestFiveDayWindowing(unittest.TestCase):
    def test_weekend_skipped(self):
        # Friday post-close → window ends Friday, skips prior weekend.
        days = pr.last_trading_days(5, now=NOW, trading_day_fn=weekdays_only)
        self.assertEqual(days, ["2026-08-03", "2026-08-04", "2026-08-05",
                                "2026-08-06", "2026-08-07"])

    def test_before_close_excludes_today(self):
        # Friday 10:00 IST (in-session) → today's report can't exist yet.
        now = datetime(2026, 8, 7, 4, 30, tzinfo=timezone.utc)
        days = pr.last_trading_days(5, now=now, trading_day_fn=weekdays_only)
        self.assertEqual(days[-1], "2026-08-06")
        self.assertEqual(days[0], "2026-07-31")  # previous Friday

    def test_weekend_now_ends_on_friday(self):
        # Sunday → last completed session is Friday.
        now = datetime(2026, 8, 9, 10, 0, tzinfo=timezone.utc)
        days = pr.last_trading_days(5, now=now, trading_day_fn=weekdays_only)
        self.assertEqual(days[-1], "2026-08-07")

    def test_holiday_skipped(self):
        holidays = {"2026-08-05"}

        def td(d):
            return d.weekday() < 5 and d.isoformat() not in holidays

        days = pr.last_trading_days(5, now=NOW, trading_day_fn=td)
        self.assertEqual(days, ["2026-07-31", "2026-08-03", "2026-08-04",
                                "2026-08-06", "2026-08-07"])
        self.assertNotIn("2026-08-05", days)

    def test_naive_now_treated_as_utc(self):
        days = pr.last_trading_days(
            5, now=NOW.replace(tzinfo=None), trading_day_fn=weekdays_only)
        self.assertEqual(days[-1], "2026-08-07")


class TestFiveDayVerdicts(unittest.TestCase):
    def _run(self, reports):
        return pr.build_five_day_acceptance(
            now=NOW, reports=reports, trading_day_fn=weekdays_only)

    def test_all_pass(self):
        reports = {d: daily(d=d) for d in
                   ["2026-08-03", "2026-08-04", "2026-08-05",
                    "2026-08-06", "2026-08-07"]}
        fd = self._run(reports)
        self.assertEqual(fd["verdict"], "PASS")
        self.assertEqual(fd["days_passed"], 5)
        self.assertEqual([r["status"] for r in fd["days"]], ["PASS"] * 5)

    def test_missing_day_is_pending(self):
        reports = {d: daily(d=d) for d in
                   ["2026-08-03", "2026-08-04", "2026-08-06", "2026-08-07"]}
        fd = self._run(reports)
        self.assertEqual(fd["verdict"], "PENDING")
        self.assertEqual(fd["days_pending"], 1)
        pend = [r for r in fd["days"] if r["status"] == "PENDING"]
        self.assertEqual(pend[0]["date"], "2026-08-05")

    def test_incomplete_evidence_day_is_pending_not_pass(self):
        rep = daily(passed=False, verdict="WARN", d="2026-08-04")
        rep["acceptance"]["evidence_complete"] = False
        rep["acceptance"]["insufficient_sections"] = ["ai", "replay"]
        fd = self._run({"2026-08-04": rep})
        row = [r for r in fd["days"] if r["date"] == "2026-08-04"][0]
        self.assertEqual(row["status"], "PENDING")
        self.assertIn("incomplete validation evidence", row["detail"])
        self.assertEqual(fd["verdict"], "PENDING")

    def test_failed_day_beats_pending(self):
        reports = {"2026-08-04": daily(passed=False, verdict="FAIL",
                                       d="2026-08-04", critical=2,
                                       failed_sections=["portfolio"])}
        fd = self._run(reports)
        self.assertEqual(fd["verdict"], "FAIL")
        failed = [r for r in fd["days"] if r["status"] == "FAIL"][0]
        self.assertEqual(failed["critical_open_issues"], 2)
        self.assertEqual(failed["failed_sections"], ["portfolio"])


class TestReadinessVerdicts(unittest.TestCase):
    FD_PASS = {"verdict": "PASS", "days_passed": 5, "days_failed": 0,
               "days_pending": 0, "days": []}
    FD_PENDING = {"verdict": "PENDING", "days_passed": 3, "days_failed": 0,
                  "days_pending": 2, "days": []}
    FD_FAIL = {"verdict": "FAIL", "days_passed": 3, "days_failed": 2,
               "days_pending": 0, "days": []}
    CERT_READY = {"cert_id": "c", "verdict": "READY",
                  "certification_pct": 100.0}
    PERF = {"verdict": "PASS", "grade_counts": {"PASS": 7}, "metrics": []}

    def test_ready(self):
        r = pr.build_readiness_report(now=NOW, five_day=self.FD_PASS,
                                      certification=self.CERT_READY,
                                      performance=self.PERF, open_issues=[])
        self.assertEqual(r["verdict"], "READY")
        self.assertTrue(r["ready"])
        self.assertEqual(r["blockers"], [])

    def test_pending_five_day(self):
        r = pr.build_readiness_report(now=NOW, five_day=self.FD_PENDING,
                                      certification=self.CERT_READY,
                                      performance=self.PERF, open_issues=[])
        self.assertEqual(r["verdict"], "PENDING")
        self.assertFalse(r["ready"])

    def test_not_ready_on_cert_not_ready(self):
        r = pr.build_readiness_report(
            now=NOW, five_day=self.FD_PASS,
            certification={**self.CERT_READY, "verdict": "NOT_READY",
                           "certification_pct": 70.0},
            performance=self.PERF, open_issues=[])
        self.assertEqual(r["verdict"], "NOT_READY")

    def test_not_ready_on_critical_issues(self):
        r = pr.build_readiness_report(
            now=NOW, five_day=self.FD_PASS, certification=self.CERT_READY,
            performance=self.PERF,
            open_issues=[{"severity": "CRITICAL", "title": "x"}])
        self.assertEqual(r["verdict"], "NOT_READY")
        self.assertTrue(any("CRITICAL" in b for b in r["blockers"]))

    def test_pending_when_no_cert(self):
        r = pr.build_readiness_report(now=NOW, five_day=self.FD_PASS,
                                      certification=None,
                                      performance=self.PERF, open_issues=[])
        self.assertEqual(r["verdict"], "PENDING")
        self.assertIsNone(r["certification"])

    def test_five_day_fail_blocks(self):
        r = pr.build_readiness_report(now=NOW, five_day=self.FD_FAIL,
                                      certification=self.CERT_READY,
                                      performance=self.PERF, open_issues=[])
        self.assertEqual(r["verdict"], "NOT_READY")


class TestDailyReportStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_file = pr.REPORTS_FILE
        self._orig_db = os.environ.pop("DATABASE_URL", None)
        pr.REPORTS_FILE = os.path.join(self._tmp.name, "daily.json")

    def tearDown(self):
        pr.REPORTS_FILE = self._orig_file
        if self._orig_db is not None:
            os.environ["DATABASE_URL"] = self._orig_db
        self._tmp.cleanup()

    def test_append_get_latest_history(self):
        r1 = pr.build_daily_report(INPUTS_HEALTHY, report_date="2026-08-06",
                                   now=NOW - timedelta(days=1))
        r2 = pr.build_daily_report(INPUTS_HEALTHY, report_date="2026-08-07",
                                   now=NOW)
        pr.append_daily_report(r1)
        pr.append_daily_report(r2)
        got = pr.get_daily_report("2026-08-06")
        self.assertEqual(got["report_date"], "2026-08-06")
        latest = pr.latest_daily_report()
        self.assertEqual(latest["report_date"], "2026-08-07")
        hist = pr.list_daily_reports()
        self.assertEqual([h["report_date"] for h in hist],
                         ["2026-08-07", "2026-08-06"])
        self.assertIn("acceptance", hist[0])

    def test_append_only_rerun_same_day_newest_wins(self):
        r1 = pr.build_daily_report({}, report_date="2026-08-07",
                                   now=NOW - timedelta(hours=1))
        r2 = pr.build_daily_report(INPUTS_HEALTHY, report_date="2026-08-07",
                                   now=NOW)
        pr.append_daily_report(r1)
        pr.append_daily_report(r2)
        rows = json.load(open(pr.REPORTS_FILE))
        self.assertEqual(len(rows), 2)  # append-only: both retained
        self.assertEqual(pr.get_daily_report("2026-08-07")["verdict"],
                         "PASS")  # newest wins for readers

    def test_run_daily_report_persists_and_returns_id(self):
        rep = pr.run_daily_report(persist=True, inputs=INPUTS_HEALTHY)
        self.assertTrue(rep["persisted"])
        self.assertTrue(rep["report_id"].startswith("dr-"))
        self.assertIsNotNone(pr.get_daily_report(rep["report_date"]))

    def test_claim_released_on_persist_failure_then_retry(self):
        # Regression: append failing AFTER the kv claim must release the
        # claim so the next scheduler tick can retry (never skip the day).
        import types
        import sys as _sys
        claimed: set = set()
        fake_store = types.SimpleNamespace(
            kv_claim_once=lambda k: (False if k in claimed
                                     else (claimed.add(k) or True)),
            kv_release=lambda k: claimed.discard(k))
        real_store = _sys.modules.get("phase20_store")
        _sys.modules["phase20_store"] = fake_store
        orig_collect = pr.collect_daily_inputs
        orig_append = pr.append_daily_report
        pr.collect_daily_inputs = lambda: dict(INPUTS_HEALTHY)
        remaining_failures = {"n": 1}

        def flaky_append(report):
            if remaining_failures["n"]:
                remaining_failures["n"] -= 1
                raise RuntimeError("db down")
            return orig_append(report)

        pr.append_daily_report = flaky_append
        try:
            r1 = pr.maybe_generate_daily_report("CLOSED")
            self.assertFalse(r1["generated"])
            self.assertIn("db down", r1["error"])
            self.assertEqual(claimed, set())        # claim was released
            r2 = pr.maybe_generate_daily_report("CLOSED")
            self.assertTrue(r2["generated"])        # retry succeeded
            self.assertEqual(len(claimed), 1)
        finally:
            pr.collect_daily_inputs = orig_collect
            pr.append_daily_report = orig_append
            if real_store is not None:
                _sys.modules["phase20_store"] = real_store
            else:
                _sys.modules.pop("phase20_store", None)

    def _fake_store(self):
        import types
        kv: dict = {}
        return types.SimpleNamespace(
            kv_claim_once=lambda k: (False if k in kv
                                     else kv.__setitem__(k, True) or True),
            kv_release=lambda k: kv.pop(k, None),
            kv_set=lambda k, v: kv.__setitem__(k, v),
            kv_get=lambda k, d=None: kv.get(k, d),
        ), kv

    def test_status_not_expected_on_weekend(self):
        # Saturday 2026-08-08
        sat = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
        st = pr.today_report_status(now=sat, trading_day_fn=weekdays_only)
        self.assertEqual(st["status"], "NOT_EXPECTED")

    def test_status_not_due_before_close(self):
        # Friday 2026-08-07 11:00 IST (pre-close)
        pre = datetime(2026, 8, 7, 5, 30, tzinfo=timezone.utc)
        st = pr.today_report_status(now=pre, trading_day_fn=weekdays_only)
        self.assertEqual(st["status"], "NOT_DUE")

    def test_status_pending_then_error_then_generated(self):
        import sys as _sys
        fake, kv = self._fake_store()
        real = _sys.modules.get("phase20_store")
        _sys.modules["phase20_store"] = fake
        orig_collect = pr.collect_daily_inputs
        try:
            # Post-close, no report yet, no recorded error → PENDING
            st = pr.today_report_status(now=NOW,
                                        trading_day_fn=weekdays_only)
            self.assertEqual(st["status"], "PENDING")

            # A failed automatic attempt records an error → ERROR
            def boom():
                raise RuntimeError("inputs unreadable")
            pr.collect_daily_inputs = boom
            out = pr.maybe_generate_daily_report("CLOSED")
            self.assertFalse(out["generated"])
            # Simulate: the failure happened today (test NOW is a fixed
            # past date, the error key is keyed by the real current day).
            today_key = pr._gen_error_key(
                NOW.astimezone(IST).date().isoformat())
            kv[today_key] = {"error": "inputs unreadable",
                             "at": "2026-08-07T10:01:00Z"}
            st = pr.today_report_status(now=NOW,
                                        trading_day_fn=weekdays_only)
            self.assertEqual(st["status"], "ERROR")
            self.assertIn("inputs unreadable", st["detail"])

            # Scheduler success → GENERATED with mode "scheduler"
            pr.collect_daily_inputs = lambda: dict(INPUTS_HEALTHY)
            out = pr.maybe_generate_daily_report("CLOSED")
            self.assertTrue(out["generated"])
            today = datetime.now(IST).date().isoformat()
            rep = pr.get_daily_report(today)
            self.assertEqual(rep.get("generated_by"), "scheduler")
            st = pr.today_report_status(
                now=datetime.now(timezone.utc),
                trading_day_fn=lambda d: True)
            self.assertEqual(st["status"], "GENERATED")
            self.assertEqual(st["mode"], "scheduler")
        finally:
            pr.collect_daily_inputs = orig_collect
            if real is not None:
                _sys.modules["phase20_store"] = real
            else:
                _sys.modules.pop("phase20_store", None)

    def test_status_stale_error_from_previous_day_never_masks_today(self):
        """Task: a generation error recorded on an EARLIER IST day must not
        surface as today's ERROR — status stays PENDING with a stale note."""
        import sys as _sys
        fake, kv = self._fake_store()
        real = _sys.modules.get("phase20_store")
        _sys.modules["phase20_store"] = fake
        try:
            today = NOW.astimezone(IST).date().isoformat()
            # Stale entry under today's key, but timestamped YESTERDAY
            # (e.g. written by a midnight-crossing tick under the old keying).
            kv[pr._gen_error_key(today)] = {
                "error": "old boom", "at": "2026-08-06T10:00:00+00:00"}
            st = pr.today_report_status(now=NOW,
                                        trading_day_fn=weekdays_only)
            self.assertEqual(st["status"], "PENDING")
            self.assertEqual(st["stale_error"]["error"], "old boom")
            self.assertIn("stale", st["detail"])

            # A fresh error from TODAY still surfaces as ERROR.
            kv[pr._gen_error_key(today)] = {
                "error": "fresh boom", "at": "2026-08-07T10:05:00+00:00"}
            st = pr.today_report_status(now=NOW,
                                        trading_day_fn=weekdays_only)
            self.assertEqual(st["status"], "ERROR")
            self.assertIn("fresh boom", st["detail"])

            # IST midnight edge: a UTC timestamp late on the PREVIOUS UTC
            # day that lands on TODAY in IST counts as fresh → ERROR.
            kv[pr._gen_error_key(today)] = {
                "error": "midnight boom", "at": "2026-08-06T19:30:00+00:00"}
            st = pr.today_report_status(now=NOW,
                                        trading_day_fn=weekdays_only)
            self.assertEqual(st["status"], "ERROR")

            # Unparseable timestamp → fail-safe: still surfaced as ERROR.
            kv[pr._gen_error_key(today)] = {"error": "no ts", "at": None}
            st = pr.today_report_status(now=NOW,
                                        trading_day_fn=weekdays_only)
            self.assertEqual(st["status"], "ERROR")
        finally:
            if real is not None:
                _sys.modules["phase20_store"] = real
            else:
                _sys.modules.pop("phase20_store", None)

    def test_generation_error_recorded_under_target_day(self):
        """maybe_generate_daily_report must key failures by the day whose
        report it attempted (computed once up front), never a later "now"."""
        import sys as _sys
        fake, kv = self._fake_store()
        real = _sys.modules.get("phase20_store")
        _sys.modules["phase20_store"] = fake
        orig_collect = pr.collect_daily_inputs
        try:
            def boom():
                raise RuntimeError("inputs unreadable")
            pr.collect_daily_inputs = boom
            out = pr.maybe_generate_daily_report("CLOSED")
            self.assertFalse(out["generated"])
            from datetime import datetime as _dt, timezone as _tz
            real_today = _dt.now(_tz.utc).astimezone(IST).date().isoformat()
            self.assertIn(pr._gen_error_key(real_today), kv)
        finally:
            pr.collect_daily_inputs = orig_collect
            if real is not None:
                _sys.modules["phase20_store"] = real
            else:
                _sys.modules.pop("phase20_store", None)

    def test_status_generated_manual_mode(self):
        import sys as _sys
        fake, _kv = self._fake_store()
        real = _sys.modules.get("phase20_store")
        _sys.modules["phase20_store"] = fake
        try:
            today = datetime.now(IST).date().isoformat()
            pr.run_daily_report(persist=True, inputs=INPUTS_HEALTHY,
                                report_date=today)
            st = pr.today_report_status(now=datetime.now(timezone.utc),
                                        trading_day_fn=lambda d: True)
            self.assertEqual(st["status"], "GENERATED")
            self.assertEqual(st["mode"], "manual")
        finally:
            if real is not None:
                _sys.modules["phase20_store"] = real
            else:
                _sys.modules.pop("phase20_store", None)

    def _seed(self, report_date: str, created_at: str) -> str:
        rid = f"dr-{report_date}-{created_at[-8:].replace(':', '')}"
        with open(pr.REPORTS_FILE + ".seedless", "w"):
            pass  # ensure tmp dir usable
        rows = []
        if os.path.exists(pr.REPORTS_FILE):
            rows = json.load(open(pr.REPORTS_FILE))
        rows.append({"report_id": rid, "report_date": report_date,
                     "created_at": created_at, "verdict": "PASS",
                     "report": {"report_id": rid,
                                "report_date": report_date}})
        json.dump(rows, open(pr.REPORTS_FILE, "w"))
        return rid

    def test_prune_removes_old_rows_only(self):
        today = datetime.now(timezone.utc).astimezone(IST).date()
        old = (today - timedelta(days=200)).isoformat()
        recent = (today - timedelta(days=2)).isoformat()
        for i in range(5):
            self._seed(old, f"2026-01-01T00:00:0{i}Z")
        self._seed(recent, "2026-08-07T10:00:00Z")
        out = pr.prune_daily_reports(days=90, keep_min=2)
        # keep_min=2 protects the recent row + newest old row; the other
        # 4 old rows are pruned.
        self.assertEqual(out["deleted"], 4)
        rows = json.load(open(pr.REPORTS_FILE))
        dates = sorted(r["report_date"] for r in rows)
        self.assertEqual(len(rows), 2)
        self.assertIn(recent, dates)

    def test_prune_never_deletes_rows_inside_retention_window(self):
        today = datetime.now(timezone.utc).astimezone(IST).date()
        in_window = [(today - timedelta(days=d)).isoformat()
                     for d in (0, 1, 30, 89)]
        for i, d in enumerate(in_window):
            self._seed(d, f"2026-08-07T10:00:0{i}Z")
        out = pr.prune_daily_reports(days=90, keep_min=1)
        self.assertEqual(out["deleted"], 0)
        rows = json.load(open(pr.REPORTS_FILE))
        self.assertEqual(sorted(r["report_date"] for r in rows),
                         sorted(in_window))

    def test_prune_keep_min_protects_old_rows(self):
        today = datetime.now(timezone.utc).astimezone(IST).date()
        old = (today - timedelta(days=300)).isoformat()
        for i in range(4):
            self._seed(old, f"2026-01-01T00:00:0{i}Z")
        out = pr.prune_daily_reports(days=90, keep_min=10)
        self.assertEqual(out["deleted"], 0)
        self.assertEqual(len(json.load(open(pr.REPORTS_FILE))), 4)

    def test_append_triggers_on_write_prune(self):
        today = datetime.now(timezone.utc).astimezone(IST).date()
        old = (today - timedelta(days=200)).isoformat()
        for i in range(pr.RETENTION_MIN_KEEP + 5):
            self._seed(old, f"2026-01-01T00:00:{i:02d}Z")
        rep = pr.build_daily_report(INPUTS_HEALTHY, report_date="2026-08-07",
                                    now=NOW)
        pr.append_daily_report(rep)
        rows = json.load(open(pr.REPORTS_FILE))
        # bounded to the keep_min floor (incl. the new row); new row survives
        self.assertEqual(len(rows), pr.RETENTION_MIN_KEEP)
        self.assertIsNotNone(pr.get_daily_report("2026-08-07"))

    def test_five_day_tracker_works_after_prune(self):
        # Seed reports for the 5 trading days ending Fri 2026-08-07 plus
        # a very old row; prune; the tracker must still see all 5 days.
        days = ["2026-08-03", "2026-08-04", "2026-08-05",
                "2026-08-06", "2026-08-07"]
        for d in days:
            rep = pr.build_daily_report(
                INPUTS_HEALTHY if d == "2026-08-07" else {
                    k: (v if not isinstance(v, dict) else
                        {**v, "generated_at": f"{d}T09:00:00Z",
                         "created_at": f"{d}T09:00:00Z"})
                    for k, v in INPUTS_HEALTHY.items()},
                report_date=d, now=NOW)
            pr.append_daily_report(rep)
        self._seed("2020-01-01", "2020-01-01T00:00:00Z")
        pr.prune_daily_reports(days=90, keep_min=1)
        for d in days:
            self.assertIsNotNone(pr.get_daily_report(d))
        tracker = pr.build_five_day_acceptance(now=NOW)
        self.assertEqual(len(tracker["days"]), 5)

    def test_prune_never_raises_on_corrupt_file(self):
        with open(pr.REPORTS_FILE, "w") as f:
            f.write("{corrupt")
        out = pr.prune_daily_reports()
        self.assertEqual(out["deleted"], 0)

    def test_run_without_persist(self):
        rep = pr.run_daily_report(persist=False, inputs=INPUTS_HEALTHY,
                                  report_date="2026-08-07")
        self.assertFalse(rep["persisted"])
        self.assertIsNone(pr.get_daily_report("2026-08-07"))


class TestReadinessExport(unittest.TestCase):
    def test_export_readiness_all_formats(self):
        import phase239_reports as p239
        self.assertIn("readiness", p239.REPORTS)
        data = pr.build_readiness_report(
            now=NOW, five_day=TestReadinessVerdicts.FD_PASS,
            certification=TestReadinessVerdicts.CERT_READY,
            performance=TestReadinessVerdicts.PERF, open_issues=[])
        for fmt in ("json", "csv", "md"):
            out = p239.export_report("readiness", fmt, data=data)
            self.assertTrue(out["ok"], out)
            self.assertIn("readiness", out["filename"])
            self.assertIn("READY", out["content"])
        pdf = p239.export_report("readiness", "pdf", data=data)
        self.assertTrue(pdf["ok"])


if __name__ == "__main__":
    unittest.main()
