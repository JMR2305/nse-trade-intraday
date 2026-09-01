"""
test_daily_session_and_pipeline_e2e.py — Task: AI Paper Trader session crash
and execution-blocker visibility.

Covers:
1. Daily session init records structured errors (state=ERROR + last_error KV)
   instead of crashing silently, and clears the error on a clean init.
2. get_session_status exposes market_state + last_error so the UI can
   distinguish "market closed" from a real failure.
3. main.py dispatch for daily_session_init parses its JSON payload from argv
   (regression guard for the NameError that made the route return
   "Python exited with code 1").
4. pipeline_stats gate_summary: total BUYs + per-gate blocked counts, with
   scan_stale / market_closed flags.
5. Full simulated end-to-end path with market OPEN + fresh scan:
   BUY signal → global+per-candidate gates pass → paper order created →
   position opened → exit recorded with correct P&L. All external state is
   mocked — PAPER ONLY, no scans, no DB writes, no network.
"""

import ast
import os
import unittest
from unittest.mock import patch

import phase20_store as store
from phase20_store import DEFAULT_SETTINGS
from universe_version_store import exact_set_hash

HERE = os.path.dirname(os.path.abspath(__file__))


# ── Shared gate-evaluation harness (same pattern as test_phase20.TestGates) ──

def _universe_context():
    return {
        "natural_session": "2026-08-31", "universe_key": "TEST_ONLY",
        "universe_id": 1, "version": 1,
        "exact_set_hash": exact_set_hash(["TCS"]), "symbol_count": 1,
    }


def _ctx(**overrides):
    sym = {
        "symbol": "TCS", "sector": "IT", "final_action": "BUY",
        "entry_price": 100.0, "stop_loss": 95.0, "target_price": 112.0,
        "rr_ratio": 2.4, "confidence": 80.0, "opportunity_score": 75.0,
        "technical_score": 70.0, "data_quality": "LIVE",
        "all_gates_passed": True, "strategy_id": "s1",
        "strategy_name": "Trend", "regime": "Bullish", "error": None,
        "expected_holding_days": 5,
        "universe_context": _universe_context(),
    }
    sym.update(overrides.pop("symbol_overrides", {}))
    ctx = {"available": True, "scan_id": "abc123", "snapshot_ts": "t",
           "stale": False, "scan_age_seconds": 60,
           "stale_after_seconds": 5400, "symbols": {"TCS": sym}}
    ctx.update(overrides)
    return ctx


def _evaluate(ctx=None, market_state="OPEN", provider="Zerodha Kite Connect",
              settings_overrides=None, portfolio=None, state=None):
    import phase20_gates as g
    ctx = ctx or _ctx()
    settings = dict(DEFAULT_SETTINGS)
    settings["config_hash"] = "h"
    settings.update(settings_overrides or {})
    pf = portfolio or {"cash": 5000.0, "total_value": 5000.0,
                       "invested_value": 0.0, "positions": []}
    st = state or {"trades": [], "positions": {}}
    with patch.object(g.store, "get_settings", return_value=settings), \
         patch.object(g.store, "kv_set", lambda *a, **k: None), \
         patch.object(g.store, "kv_get", return_value={}), \
         patch("phase15_scan_context.build_scan_context", return_value=ctx), \
         patch("market_hours.market_status", return_value={"state": market_state}), \
         patch("scan_state_store.load_latest_meta",
               return_value={"scan_id": ctx.get("scan_id"), "provider": provider,
                             "universe_context": _universe_context()}), \
         patch("scan_state_store.load_latest_snapshot",
               return_value={"scan_id": ctx.get("scan_id"),
                             "safety": {"kite_connected": True,
                                        "data_provider": provider}}), \
         patch("paper_trader._load_state", return_value=st), \
         patch("paper_trader.get_portfolio", return_value=pf), \
         patch("phase20_executor.get_ledger", return_value=[]):
        return g.evaluate_entries(), settings


# ── 1+2. Daily session error persistence & status ────────────────────────────

class TestDailySessionErrorReporting(unittest.TestCase):
    def _run_init(self, kv, portfolio_reset_fails=False,
                  agents_result=None, topup_result=None):
        import daily_session_manager as dsm

        def kv_get(key, default=None):
            return kv.get(key, default)

        def kv_set(key, value):
            kv[key] = value

        def boom():
            raise RuntimeError("simulated portfolio store outage")

        patches = [
            patch.object(dsm, "_kv_get", side_effect=kv_get),
            patch.object(dsm, "_kv_set", side_effect=kv_set),
            patch.object(dsm, "_notify", lambda *a, **k: None),
            patch.object(dsm, "verify_agents",
                         return_value=agents_result or
                         {"agents": {}, "healthy": 0, "total": 0}),
        ]
        import paper_trader
        import phase20_store as p20
        patches.append(patch.object(
            paper_trader, "reset_portfolio",
            side_effect=boom if portfolio_reset_fails else (lambda: None)))
        patches.append(patch.object(p20, "update_settings",
                                    lambda *a, **k: {}))
        with patch("phase11_autonomous.check_and_apply_topup",
                   return_value=topup_result or {"applied": False}):
            ctxs = [p.__enter__() for p in patches]
            try:
                return dsm.initialize_daily_session(force=True)
            finally:
                for p in reversed(patches):
                    p.__exit__(None, None, None)

    def test_step_error_recorded_as_error_state(self):
        kv = {}
        result = self._run_init(kv, portfolio_reset_fails=True)
        self.assertFalse(result["success"])
        self.assertIn("portfolio_reset", result["errors"])
        self.assertEqual(kv["daily_session_state"], "ERROR")
        err = kv["daily_session_last_error"]
        self.assertEqual(err["source"], "session_init_steps")
        self.assertIn("portfolio_reset", err["detail"])
        self.assertIn("simulated portfolio store outage",
                      err["detail"]["portfolio_reset"])

    def test_agent_warmup_failure_marks_error(self):
        kv = {}
        result = self._run_init(kv, agents_result={
            "agents": {"risk": "ERROR: import failed", "strategy": "OK"},
            "healthy": 1, "total": 2})
        self.assertFalse(result["success"])
        self.assertIn("agents", result["errors"])
        self.assertEqual(kv["daily_session_state"], "ERROR")
        detail = kv["daily_session_last_error"]["detail"]["agents"]
        self.assertIn("risk", detail["failed_agents"])

    def test_topup_failure_marks_error(self):
        kv = {}
        result = self._run_init(kv, topup_result={
            "applied": False, "error": "topup store unavailable"})
        self.assertFalse(result["success"])
        self.assertIn("topup", result["errors"])
        self.assertEqual(kv["daily_session_state"], "ERROR")
        self.assertEqual(
            kv["daily_session_last_error"]["detail"]["topup"]["error"],
            "topup store unavailable")

    def test_clean_init_clears_error(self):
        kv = {"daily_session_last_error": {"source": "old"}}
        result = self._run_init(kv, portfolio_reset_fails=False)
        self.assertTrue(result["success"])
        self.assertEqual(kv["daily_session_state"], "INITIALISED")
        self.assertIsNone(kv["daily_session_last_error"])

    def test_status_includes_market_state_and_error(self):
        import daily_session_manager as dsm
        kv = {
            "daily_session_date": dsm._today_ist(),
            "daily_session_initialized_at": "2026-08-10T03:30:00Z",
            "daily_session_state": "ERROR",
            "daily_session_last_error": {"at": "x", "source": "session_init_steps",
                                         "detail": {"portfolio_reset": "ERROR: boom"}},
        }
        with patch.object(dsm, "_kv_get",
                          side_effect=lambda k, d=None: kv.get(k, d)), \
             patch("market_hours.market_state", return_value="CLOSED"):
            status = dsm.get_session_status()
        self.assertEqual(status["market_state"], "CLOSED")
        self.assertEqual(status["session_state"], "ERROR")
        self.assertIsNotNone(status["last_error"])
        self.assertEqual(status["last_error"]["source"], "session_init_steps")

    def test_status_no_error_when_initialised_cleanly(self):
        import daily_session_manager as dsm
        kv = {
            "daily_session_date": dsm._today_ist(),
            "daily_session_state": "INITIALISED",
            "daily_session_last_error": None,
        }
        with patch.object(dsm, "_kv_get",
                          side_effect=lambda k, d=None: kv.get(k, d)), \
             patch("market_hours.market_state", return_value="OPEN"):
            status = dsm.get_session_status()
        self.assertEqual(status["session_state"], "INITIALISED")
        self.assertIsNone(status["last_error"])


class TestOpenAlert(unittest.TestCase):
    """check_open_alert: CRITICAL notification when session is not
    INITIALISED at market OPEN, deduped once per day via kv_claim_once."""

    def _run(self, kv, mstate="OPEN", claim_result=True):
        import daily_session_manager as dsm
        notifications = []

        def add_notification(kind, title, body="", severity="INFO",
                             context=None):
            notifications.append({"kind": kind, "title": title,
                                  "body": body, "severity": severity,
                                  "context": context})

        import phase20_store as p20
        with patch.object(dsm, "_kv_get",
                          side_effect=lambda k, d=None: kv.get(k, d)), \
             patch.object(p20, "kv_claim_once",
                          return_value=claim_result) as claim, \
             patch.object(p20, "add_notification",
                          side_effect=add_notification):
            out = dsm.check_open_alert(mstate)
        return out, notifications, claim

    def test_no_alert_when_market_not_open(self):
        out, notes, _ = self._run({}, mstate="PRE_OPEN")
        self.assertIsNone(out)
        self.assertEqual(notes, [])

    def test_no_alert_when_initialised_today(self):
        import daily_session_manager as dsm
        kv = {"daily_session_date": dsm._today_ist(),
              "daily_session_state": "INITIALISED"}
        out, notes, _ = self._run(kv)
        self.assertIsNone(out)
        self.assertEqual(notes, [])

    def test_alert_when_not_initialized(self):
        out, notes, claim = self._run({})
        self.assertTrue(out["alerted"])
        self.assertEqual(out["state"], "NOT_INITIALIZED")
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["kind"], "SESSION_INIT_FAILED")
        self.assertEqual(notes[0]["severity"], "CRITICAL")
        import daily_session_manager as dsm
        claim.assert_called_once_with(
            f"session_init_open_alert:{dsm._today_ist()}")

    def test_alert_when_error_state_includes_last_error(self):
        import daily_session_manager as dsm
        kv = {"daily_session_date": dsm._today_ist(),
              "daily_session_state": "ERROR",
              "daily_session_last_error": {
                  "at": "2026-08-10T03:20:00Z",
                  "source": "session_init_steps",
                  "detail": {"portfolio_reset": "ERROR: store outage"}}}
        out, notes, _ = self._run(kv)
        self.assertTrue(out["alerted"])
        self.assertEqual(out["state"], "ERROR")
        self.assertIn("store outage", notes[0]["body"])
        self.assertIn("session_init_steps", notes[0]["body"])
        self.assertEqual(
            notes[0]["context"]["last_error"]["source"],
            "session_init_steps")

    def test_deduped_when_already_claimed(self):
        out, notes, _ = self._run({}, claim_result=False)
        self.assertFalse(out["alerted"])
        self.assertEqual(out["reason"], "already alerted today")
        self.assertEqual(notes, [])

    def test_never_raises(self):
        import daily_session_manager as dsm
        with patch.object(dsm, "_kv_get",
                          side_effect=RuntimeError("kv down")):
            out = dsm.check_open_alert("OPEN")
        self.assertFalse(out["alerted"])
        self.assertIn("kv down", out["error"])

    def test_session_init_failed_is_email_kind(self):
        from email_alerts import EMAIL_KINDS
        self.assertIn("SESSION_INIT_FAILED", EMAIL_KINDS)

    def test_run_tick_alerts_even_when_auto_scan_disabled(self):
        """Scheduler regression: OPEN + auto_scan_enabled=False + session
        uninitialised must STILL emit the SESSION_INIT_FAILED CRITICAL alert
        (the disabled early-return previously skipped it entirely)."""
        import daily_session_manager as dsm
        import phase20_scheduler as sched
        import phase20_store as p20
        notifications = []
        settings = dict(DEFAULT_SETTINGS)
        settings["auto_scan_enabled"] = False

        with patch.object(p20, "get_settings", return_value=settings), \
             patch.object(p20, "update_scheduler_state",
                          lambda *a, **k: None), \
             patch("market_hours.market_status",
                   return_value={"state": "OPEN"}), \
             patch.object(dsm, "_kv_get",
                          side_effect=lambda k, d=None: None), \
             patch.object(p20, "kv_claim_once",
                          return_value=True) as claim, \
             patch.object(p20, "add_notification",
                          side_effect=lambda kind, title, body="",
                          severity="INFO", context=None:
                          notifications.append((kind, severity))):
            out = sched.run_tick()

        self.assertFalse(out["ran_scan"])
        self.assertEqual(out["reason"], "Auto scan disabled")
        self.assertTrue(out["session_alert"]["alerted"])
        self.assertEqual(notifications,
                         [("SESSION_INIT_FAILED", "CRITICAL")])
        alert_key = f"session_init_open_alert:{dsm._today_ist()}"
        claimed_keys = [
            call.args[0] for call in claim.call_args_list
            if call.args
        ]
        self.assertIn(alert_key, claimed_keys)
        self.assertTrue(any(
            str(key).startswith("system_heartbeat:")
            for key in claimed_keys
        ))

    def test_run_tick_disabled_no_alert_when_initialised(self):
        """OPEN + disabled scans + session INITIALISED today → no alert."""
        import daily_session_manager as dsm
        import phase20_scheduler as sched
        import phase20_store as p20
        kv = {"daily_session_date": dsm._today_ist(),
              "daily_session_state": "INITIALISED"}
        settings = dict(DEFAULT_SETTINGS)
        settings["auto_scan_enabled"] = False

        with patch.object(p20, "get_settings", return_value=settings), \
             patch.object(p20, "update_scheduler_state",
                          lambda *a, **k: None), \
             patch("market_hours.market_status",
                   return_value={"state": "OPEN"}), \
             patch.object(dsm, "_kv_get",
                          side_effect=lambda k, d=None: kv.get(k, d)), \
             patch.object(p20, "add_notification") as notify:
            out = sched.run_tick()

        self.assertNotIn("session_alert", out)
        notify.assert_not_called()


class TestRecoveryNotice(unittest.TestCase):
    """initialize_daily_session emits a one-time INFO SESSION_INIT_RECOVERED
    notification when today's open-alert claim exists and init succeeds."""

    def _init(self, kv, claims, notes, fail=False):
        import daily_session_manager as dsm
        import paper_trader
        import phase20_store as p20

        def kv_claim_once(key):
            if key in claims:
                return False
            claims.add(key)
            return True

        def boom():
            raise RuntimeError("still broken")

        with patch.object(dsm, "_kv_get",
                          side_effect=lambda k, d=None: kv.get(k, d)), \
             patch.object(dsm, "_kv_set",
                          side_effect=lambda k, v: kv.__setitem__(k, v)), \
             patch.object(dsm, "_notify", lambda *a, **k: None), \
             patch.object(dsm, "verify_agents",
                          return_value={"agents": {}, "healthy": 0,
                                        "total": 0}), \
             patch.object(paper_trader, "reset_portfolio",
                          side_effect=boom if fail else (lambda: None)), \
             patch.object(p20, "update_settings", lambda *a, **k: {}), \
             patch.object(p20, "kv_claim_once", side_effect=kv_claim_once), \
             patch.object(p20, "add_notification",
                          side_effect=lambda kind, title, body="",
                          severity="INFO", context=None:
                          notes.append({"kind": kind, "severity": severity,
                                        "context": context})), \
             patch("phase11_autonomous.check_and_apply_topup",
                   return_value={"applied": False}):
            return dsm.initialize_daily_session(force=True)

    def test_recovery_emitted_once_when_alert_fired(self):
        import daily_session_manager as dsm
        today = dsm._today_ist()
        kv = {f"session_init_open_alert:{today}": True}   # alert already fired
        claims, notes = set(), []

        result = self._init(kv, claims, notes)
        self.assertTrue(result["success"])
        self.assertEqual(result["recovery_notice"], {"emitted": True})
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["kind"], "SESSION_INIT_RECOVERED")
        self.assertEqual(notes[0]["severity"], "INFO")
        # Open-alert claim must remain untouched (read-only check).
        self.assertNotIn(f"session_init_open_alert:{today}", claims)
        # Durable recovery stamp for the dashboard session card.
        self.assertEqual(kv["daily_session_recovered"]["date"], today)

        # Second successful init the same day → no duplicate.
        result2 = self._init(kv, claims, notes)
        self.assertEqual(result2["recovery_notice"]["emitted"], False)
        self.assertEqual(len(notes), 1)

    def test_no_recovery_when_no_alert_was_raised(self):
        kv = {}                                            # alert never fired
        claims, notes = set(), []
        result = self._init(kv, claims, notes)
        self.assertTrue(result["success"])
        self.assertNotIn("recovery_notice", result)
        self.assertEqual(notes, [])
        self.assertEqual(claims, set())

    def test_status_exposes_recovered_at_only_when_initialised_today(self):
        import daily_session_manager as dsm
        today = dsm._today_ist()
        base = {
            "daily_session_date": today,
            "daily_session_state": "INITIALISED",
            "daily_session_recovered": {"date": today,
                                        "at": "2026-08-10T04:05:00Z"},
        }

        def status(kv):
            with patch.object(dsm, "_kv_get",
                              side_effect=lambda k, d=None: kv.get(k, d)), \
                 patch("market_hours.market_state", return_value="OPEN"):
                return dsm.get_session_status()

        self.assertEqual(status(dict(base))["recovered_at"],
                         "2026-08-10T04:05:00Z")
        # Stale stamp from a previous day → hidden.
        stale = dict(base)
        stale["daily_session_recovered"] = {"date": "2020-01-01", "at": "x"}
        self.assertIsNone(status(stale)["recovered_at"])
        # Session back in ERROR → hidden (failure display wins).
        err = dict(base)
        err["daily_session_state"] = "ERROR"
        self.assertIsNone(status(err)["recovered_at"])
        # No stamp at all → hidden.
        clean = dict(base)
        del clean["daily_session_recovered"]
        self.assertIsNone(status(clean)["recovered_at"])

    def test_no_recovery_when_init_still_failing(self):
        import daily_session_manager as dsm
        today = dsm._today_ist()
        kv = {f"session_init_open_alert:{today}": True}
        claims, notes = set(), []
        result = self._init(kv, claims, notes, fail=True)
        self.assertFalse(result["success"])
        self.assertNotIn("recovery_notice", result)
        self.assertEqual(notes, [])


class TestRunTickOpenAlertE2E(unittest.TestCase):
    """End-to-end through a real phase20_scheduler.run_tick(): market OPEN,
    session init in a failed/uninitialised state → exactly one CRITICAL
    SESSION_INIT_FAILED notification across consecutive ticks, and no alert
    when the OPEN retry succeeds. Exercises the FRESH branch (scan_age small)
    so the session_alert key must survive into the tick result."""

    def _tick(self, sched, kv, claims, notifications):
        """Run one real run_tick() with a shared KV/claim/notification world."""
        import daily_session_manager as dsm
        import phase20_store as p20

        def kv_claim_once(key):
            if key in claims:
                return False
            claims.add(key)
            return True

        def add_notification(kind, title, body="", severity="INFO",
                             context=None):
            notifications.append({"kind": kind, "severity": severity,
                                  "body": body, "context": context})

        settings = dict(DEFAULT_SETTINGS)
        settings["auto_scan_enabled"] = True

        with patch.object(p20, "get_settings", return_value=settings), \
             patch.object(p20, "update_scheduler_state", lambda *a, **k: None), \
             patch("market_hours.market_status",
                   return_value={"state": "OPEN"}), \
             patch.object(dsm, "_kv_get",
                          side_effect=lambda k, d=None: kv.get(k, d)), \
             patch.object(dsm, "_kv_set",
                          side_effect=lambda k, v: kv.__setitem__(k, v)), \
             patch.object(p20, "kv_claim_once", side_effect=kv_claim_once), \
             patch.object(p20, "add_notification",
                          side_effect=add_notification), \
             patch("phase15_scan_context.scan_age_seconds", return_value=10), \
             patch.object(sched, "_manage_paper",
                          return_value={"managed": False}), \
             patch.object(sched, "_maybe_alert_low_coverage",
                          return_value=None), \
             patch.object(sched, "_maybe_run_live_validation",
                          return_value=None), \
             patch.object(sched, "_maybe_run_phase26c_validation",
                          return_value=None):
            return sched.run_tick()

    def test_failed_init_alerts_exactly_once_across_two_ticks(self):
        import daily_session_manager as dsm
        import phase20_scheduler as sched
        # Init already ran today but ended in ERROR (persisted last_error).
        kv = {"daily_session_date": dsm._today_ist(),
              "daily_session_state": "ERROR",
              "daily_session_last_error": {
                  "at": "2026-08-10T03:20:00Z",
                  "source": "session_init_steps",
                  "detail": {"portfolio_reset": "ERROR: store outage"}}}
        claims, notes = set(), []

        out1 = self._tick(sched, kv, claims, notes)
        self.assertTrue(out1["success"])
        self.assertFalse(out1["ran_scan"])          # FRESH branch
        self.assertIn("Snapshot fresh", out1["reason"])
        self.assertTrue(out1["session_alert"]["alerted"])
        self.assertEqual(out1["session_alert"]["state"], "ERROR")
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["kind"], "SESSION_INIT_FAILED")
        self.assertEqual(notes[0]["severity"], "CRITICAL")
        self.assertIn("store outage", notes[0]["body"])

        out2 = self._tick(sched, kv, claims, notes)  # next minute, same day
        self.assertIn("session_alert", out2)
        self.assertFalse(out2["session_alert"]["alerted"])
        self.assertEqual(out2["session_alert"]["reason"],
                         "already alerted today")
        self.assertEqual(len(notes), 1)              # still exactly one

    def test_open_retry_success_emits_no_alert(self):
        """Init never ran today (yesterday's ERROR state lingers), the OPEN
        tick retries it via check_and_maybe_initialize and it succeeds →
        session_alert must not fire and no notification is added."""
        import daily_session_manager as dsm
        import phase20_scheduler as sched
        kv = {"daily_session_date": "2020-01-01",     # stale — not today
              "daily_session_state": "ERROR"}
        claims, notes = set(), []

        def fake_init(force=False):
            kv["daily_session_date"] = dsm._today_ist()
            kv["daily_session_state"] = "INITIALISED"
            kv["daily_session_last_error"] = None
            return {"success": True, "errors": {}}

        with patch.object(dsm, "initialize_daily_session",
                          side_effect=fake_init):
            out = self._tick(sched, kv, claims, notes)

        self.assertTrue(out["success"])
        self.assertEqual(kv["daily_session_state"], "INITIALISED")
        self.assertNotIn("session_alert", out)       # check_open_alert → None
        self.assertEqual(notes, [])
        self.assertEqual(claims, set())              # no claim consumed

    def test_busy_branch_still_carries_session_alert(self):
        """Stale snapshot + scan lock busy → BUSY branch must still surface
        the session alert in the tick result."""
        import daily_session_manager as dsm
        import phase20_scheduler as sched
        import phase20_store as p20
        kv = {"daily_session_date": dsm._today_ist(),
              "daily_session_state": "ERROR"}
        claims, notes = set(), []

        def kv_claim_once(key):
            if key in claims:
                return False
            claims.add(key)
            return True

        settings = dict(DEFAULT_SETTINGS)
        settings["auto_scan_enabled"] = True

        with patch.object(p20, "get_settings", return_value=settings), \
             patch.object(p20, "update_scheduler_state", lambda *a, **k: None), \
             patch.object(p20, "record_scan_run", lambda *a, **k: None), \
             patch.object(p20, "kv_set", lambda *a, **k: None), \
             patch.object(p20, "kv_get", return_value=0), \
             patch("market_hours.market_status",
                   return_value={"state": "OPEN"}), \
             patch.object(dsm, "_kv_get",
                          side_effect=lambda k, d=None: kv.get(k, d)), \
             patch.object(p20, "kv_claim_once", side_effect=kv_claim_once), \
             patch.object(p20, "add_notification",
                          side_effect=lambda kind, *a, **k:
                          notes.append(kind)), \
             patch("phase15_scan_context.scan_age_seconds",
                   return_value=10_000), \
             patch("live_scan_engine.get_or_run_scan",
                   return_value={"_scan_lock_busy": True}), \
             patch.object(sched, "_maybe_alert_low_coverage",
                          return_value=None), \
             patch.object(sched, "_maybe_run_live_validation",
                          return_value=None), \
             patch.object(sched, "_maybe_run_phase26c_validation",
                          return_value=None):
            out = sched.run_tick()

        self.assertFalse(out["ran_scan"])
        self.assertIn("SKIPPED_ACTIVE_SCAN", out["reason"])
        self.assertTrue(out["session_alert"]["alerted"])
        self.assertEqual(notes, ["SESSION_INIT_FAILED"])


# ── 3. main.py dispatch regression guard ─────────────────────────────────────

class TestMainDispatchParsesPayload(unittest.TestCase):
    """The daily_session_init branch must parse its payload from args, never
    reference an undefined `data` variable (the crash behind
    'Python exited with code 1')."""

    def test_no_bare_data_reference_in_session_branch(self):
        src = open(os.path.join(HERE, "main.py")).read()
        tree = ast.parse(src)
        main_fn = next(n for n in ast.walk(tree)
                       if isinstance(n, ast.FunctionDef) and n.name == "main")
        assigned = set()
        for node in ast.walk(main_fn):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                assigned.add(node.id)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for a in node.args.args:
                    assigned.add(a.arg)
        loaded = {n.id for n in ast.walk(main_fn)
                  if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        import builtins
        undefined = {n for n in loaded - assigned
                     if not hasattr(builtins, n)
                     and n not in dir(__import__("sys").modules.get("main", object()))}
        # `data` specifically must never be referenced without assignment.
        self.assertNotIn("data", undefined - assigned,
                         "main() references `data` without assigning it")
        self.assertIn("daily_session_init", src)


# ── 4. Gate summary in pipeline stats ────────────────────────────────────────

class TestGateSummary(unittest.TestCase):
    def test_gate_summary_counts_global_and_candidate_blocks(self):
        import pipeline_stats as ps
        ev = {
            "global_pass": False,
            "global_gates": [
                {"gate": "scan_fresh", "passed": False, "reason": "stale"},
                {"gate": "market_open", "passed": False, "reason": "CLOSED"},
                {"gate": "provider_zerodha", "passed": True, "reason": "ok"},
            ],
            "eligible_count": 0,
            "candidates": [
                {"symbol": "A", "eligible": False,
                 "failed_gates": ["min_confidence", "min_risk_reward"],
                 "opportunity_score": 70, "confidence": 50},
                {"symbol": "B", "eligible": False,
                 "failed_gates": ["min_risk_reward", "per_stock_cap"],
                 "opportunity_score": 72, "confidence": 80},
            ],
        }
        ctx = {"available": True, "scan_id": "s1", "snapshot_ts": "t",
               "symbols": {
                   "A": {"final_action": "BUY", "data_quality": "LIVE",
                         "opportunity_score": 70, "confidence": 50},
                   "B": {"final_action": "STRONG BUY", "data_quality": "LIVE",
                         "opportunity_score": 72, "confidence": 80},
               }}
        with patch("phase15_scan_context.build_scan_context", return_value=ctx), \
             patch("phase20_gates.evaluate_entries", return_value=ev), \
             patch("phase20_executor.get_ledger", return_value=[]), \
             patch("phase20_executor.get_open_trades", return_value=[]), \
             patch("phase20_store.get_settings", return_value=dict(DEFAULT_SETTINGS)):
            stats = ps.get_pipeline_stats()

        gs = stats["gate_summary"]
        self.assertEqual(gs["total_buy_signals"], 2)
        self.assertTrue(gs["scan_stale"])
        self.assertTrue(gs["market_closed"])
        self.assertEqual(gs["global_blocked_counts"]["scan_fresh"], 2)
        self.assertEqual(gs["global_blocked_counts"]["market_open"], 2)
        self.assertEqual(gs["candidate_blocked_counts"]["min_risk_reward"], 2)
        self.assertEqual(gs["candidate_blocked_counts"]["min_confidence"], 1)
        self.assertEqual(gs["candidate_blocked_counts"]["per_stock_cap"], 1)

    def test_gate_summary_clean_when_flowing(self):
        import pipeline_stats as ps
        ev = {"global_pass": True, "global_gates": [
                  {"gate": "scan_fresh", "passed": True, "reason": "ok"},
                  {"gate": "market_open", "passed": True, "reason": "OPEN"}],
              "eligible_count": 1,
              "candidates": [{"symbol": "A", "eligible": True, "failed_gates": [],
                              "opportunity_score": 75, "confidence": 82}]}
        ctx = {"available": True, "scan_id": "s1", "snapshot_ts": "t",
               "symbols": {"A": {"final_action": "BUY", "data_quality": "LIVE",
                                 "opportunity_score": 75, "confidence": 82}}}
        with patch("phase15_scan_context.build_scan_context", return_value=ctx), \
             patch("phase20_gates.evaluate_entries", return_value=ev), \
             patch("phase20_executor.get_ledger", return_value=[]), \
             patch("phase20_executor.get_open_trades", return_value=[]), \
             patch("phase20_store.get_settings", return_value=dict(DEFAULT_SETTINGS)):
            stats = ps.get_pipeline_stats()
        gs = stats["gate_summary"]
        self.assertFalse(gs["scan_stale"])
        self.assertFalse(gs["market_closed"])
        self.assertEqual(gs["global_blocked_counts"], {})
        self.assertEqual(gs["candidate_blocked_counts"], {})


# ── 5. End-to-end: market open + fresh scan → BUY → order → position → P&L ──

class _FakeRV:
    verdict = "APPROVED"
    issues = []
    reason = ""
    def to_dict(self):
        return {"verdict": "APPROVED", "approved": True}


class TestEndToEndPaperFlow(unittest.TestCase):
    def test_buy_flows_through_gates_to_position_and_pnl(self):
        # Step 1 — market OPEN + fresh scan → candidate passes all gates.
        ev, settings = _evaluate(market_state="OPEN")
        self.assertTrue(all(g["passed"] for g in ev["global_gates"]),
                        [g for g in ev["global_gates"] if not g["passed"]])
        self.assertEqual(ev["eligible_count"], 1)
        cand = ev["candidates"][0]
        self.assertEqual(cand["universe_context"], _universe_context())
        self.assertTrue(cand["eligible"])
        self.assertEqual(cand["failed_gates"], [])
        qty = int(cand["sizing"]["quantity"])
        self.assertGreaterEqual(qty, 1)

        # Step 2 — eligible candidate → paper order + position (mocked stores).
        import phase20_executor as px
        ledger_rows = {}
        buys = []

        def fake_insert(row):
            ledger_rows[row["trade_id"]] = dict(row)

        def fake_update(trade_id, fields):
            ledger_rows[trade_id].update(fields)

        def fake_get_trade(trade_id):
            return ledger_rows.get(trade_id)

        def fake_execute_buy(sym, q, price, **kw):
            buys.append((sym, q, price))
            return True, "ok"

        with patch.object(px, "_insert_row", side_effect=fake_insert), \
             patch.object(px, "_update_row", side_effect=fake_update), \
             patch.object(px, "get_trade", side_effect=fake_get_trade), \
             patch("paper_trader.get_portfolio",
                   return_value={"cash": 5000.0, "total_value": 5000.0,
                                 "invested_value": 0.0, "positions": []}), \
             patch("paper_trader.execute_buy", side_effect=fake_execute_buy), \
             patch("risk_validation.pre_trade.validate_pre_trade",
                   return_value=_FakeRV()), \
             patch("pipeline_events.emit", lambda *a, **k: None), \
             patch.object(px.store, "add_notification", lambda *a, **k: None):
            created = px.create_paper_entry(cand, settings, "abc123", "t",
                                            trigger_source="TEST")
            self.assertTrue(created["created"], created)
            trade_id = created["trade_id"]
            self.assertEqual(ledger_rows[trade_id]["evidence"]["universe"], _universe_context())
            self.assertEqual(created["symbol"], "TCS")
            self.assertEqual(len(buys), 1)          # position opened
            self.assertEqual(buys[0][0], "TCS")
            fill_price = float(created["fill_price"])
            self.assertGreater(fill_price, 0)
            self.assertEqual(ledger_rows[trade_id]["status"], "OPEN")

            # Step 3 — exit at target → P&L recorded on the ledger row.
            exit_price = 112.0
            px.record_exit(trade_id, exit_price, "TARGET_HIT", "abc124",
                           status="CLOSED")
            row = ledger_rows[trade_id]
            self.assertEqual(row["status"], "CLOSED")
            expected_pnl = round((exit_price - fill_price) * qty, 2)
            self.assertEqual(row["realized_pnl"], expected_pnl)
            self.assertGreater(row["realized_pnl"], 0)

    def test_stale_scan_blocks_and_market_closed_blocks(self):
        ev, _ = _evaluate(ctx=_ctx(stale=True))
        self.assertIn("scan_fresh",
                      [g["gate"] for g in ev["global_gates"] if not g["passed"]])
        ev2, _ = _evaluate(market_state="CLOSED")
        self.assertIn("market_open",
                      [g["gate"] for g in ev2["global_gates"] if not g["passed"]])


if __name__ == "__main__":
    unittest.main()
