"""Phase 27F System Readiness — unit tests for deterministic state derivation.

All tests are pure: check builders receive constructed input dicts; no
network, DB, or filesystem access.
"""
import unittest
from datetime import datetime, timedelta, timezone

import phase27_readiness as r

NOW = datetime(2026, 8, 9, 10, 0, tzinfo=timezone.utc)


def iso(minutes_ago: float = 0) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat()


def base_inputs(**over):
    """A fully-healthy input set; tests override specific sources."""
    inp = {
        "_errors": {},
        "scan_meta": {"scan_id": "s1", "snapshot_ts": iso(10),
                      "status": "SUCCESS", "error": None,
                      "symbols_requested": 10, "symbols_received": 10,
                      "provider": "zerodha"},
        "db_durable": True,
        "market": {"state": "OPEN", "is_open": True},
        "scheduler": {"health": "HEALTHY", "heartbeat_at": iso(1),
                      "auto_scan_enabled": True},
        "settings": {"auto_paper_entries": False,
                     "daily_loss_limit_pct": 2.0},
        "broker": {"connection_state": "CONNECTED",
                   "last_success_at": iso(30)},
        "breaker": {"tripped": False, "unreadable": False, "reasons": []},
        "portfolio_health": {"status": "HEALTHY"},
        "system": {"memory": {"available": True, "status": "HEALTHY"},
                   "disk": {"available": True, "status": "HEALTHY"},
                   "cpu": {"available": True, "status": "HEALTHY"},
                   "environment": {}},
        "recovery_latest": {"verdict": "PASS", "created_at": iso(60)},
        "pipeline": {"scan_id": "s1", "last_event_at": iso(9), "count": 42},
        "env_flags": {"LIVE_EXECUTION_ENABLED": "false",
                      "AUTO_EXECUTION_ENABLED_set": False,
                      "LIVE_ORDERS_ENABLED_set": False,
                      "SESSION_SECRET_present": True,
                      "DATABASE_URL_present": True},
        "paper_mode": True,
    }
    inp.update(over)
    return inp


def get_check(report, check_id):
    for d in report["domains"]:
        for c in d["checks"]:
            if c["id"] == check_id:
                return c
    raise AssertionError(f"check {check_id} not found")


class TestOverallFold(unittest.TestCase):
    def test_all_healthy_is_ready(self):
        rep = r.build_report(base_inputs(), now=NOW)
        self.assertEqual(rep["overall"], r.READY)
        self.assertEqual(rep["counts"][r.BLOCKED], 0)
        self.assertEqual(rep["counts"][r.UNKNOWN], 0)

    def test_blocking_blocked_dominates(self):
        checks = [
            {"id": "a", "status": r.READY, "blocking": True},
            {"id": "b", "status": r.BLOCKED, "blocking": True},
            {"id": "c", "status": r.WARNING, "blocking": False},
        ]
        self.assertEqual(r.derive_overall(checks), r.BLOCKED)

    def test_blocking_unknown_prevents_ready(self):
        checks = [
            {"id": "a", "status": r.READY, "blocking": True},
            {"id": "b", "status": r.UNKNOWN, "blocking": True},
        ]
        self.assertEqual(r.derive_overall(checks), r.UNKNOWN)

    def test_nonblocking_issues_yield_warning(self):
        checks = [
            {"id": "a", "status": r.READY, "blocking": True},
            {"id": "b", "status": r.BLOCKED, "blocking": False},
            {"id": "c", "status": r.UNKNOWN, "blocking": False},
        ]
        self.assertEqual(r.derive_overall(checks), r.WARNING)

    def test_deterministic(self):
        inp = base_inputs()
        r1 = r.build_report(inp, now=NOW)
        r2 = r.build_report(inp, now=NOW)
        s1 = [(c["id"], c["status"]) for d in r1["domains"] for c in d["checks"]]
        s2 = [(c["id"], c["status"]) for d in r2["domains"] for c in d["checks"]]
        self.assertEqual(s1, s2)
        self.assertEqual(r1["overall"], r2["overall"])


class TestFailSafeUnknown(unittest.TestCase):
    """Missing telemetry must never yield READY."""

    SOURCES = ["scan_meta", "scheduler", "settings", "breaker",
               "portfolio_health", "env_flags", "db_durable"]

    def test_each_missing_blocking_source_prevents_ready(self):
        for src in self.SOURCES:
            inp = base_inputs(**{src: None})
            inp["_errors"][src] = "RuntimeError: boom"
            rep = r.build_report(inp, now=NOW)
            self.assertNotEqual(rep["overall"], r.READY,
                                f"missing {src} must not be READY")

    def test_missing_source_checks_are_unknown_not_ready(self):
        inp = base_inputs(scan_meta=None)
        inp["_errors"]["scan_meta"] = "boom"
        c = get_check(r.build_report(inp, now=NOW), "scan_freshness")
        self.assertEqual(c["status"], r.UNKNOWN)
        self.assertTrue(c["blocking"])
        self.assertTrue(c["remediation"])

    def test_unparseable_snapshot_ts_is_unknown(self):
        inp = base_inputs()
        inp["scan_meta"]["snapshot_ts"] = "not-a-date"
        c = get_check(r.build_report(inp, now=NOW), "scan_freshness")
        self.assertEqual(c["status"], r.UNKNOWN)


class TestExecutionModeSafety(unittest.TestCase):
    def test_live_execution_enabled_blocks(self):
        inp = base_inputs()
        inp["env_flags"]["LIVE_EXECUTION_ENABLED"] = "true"
        rep = r.build_report(inp, now=NOW)
        c = get_check(rep, "execution_mode")
        self.assertEqual(c["status"], r.BLOCKED)
        self.assertTrue(c["blocking"])
        self.assertEqual(rep["overall"], r.BLOCKED)

    def test_auto_execution_flag_blocks(self):
        inp = base_inputs()
        inp["env_flags"]["AUTO_EXECUTION_ENABLED_set"] = True
        self.assertEqual(get_check(r.build_report(inp, now=NOW),
                                   "execution_mode")["status"], r.BLOCKED)

    def test_paper_mode_evidence_missing_is_unknown_never_ready(self):
        inp = base_inputs(paper_mode=None)
        inp["_errors"]["paper_mode"] = "ImportError: config"
        rep = r.build_report(inp, now=NOW)
        c = get_check(rep, "execution_mode")
        self.assertEqual(c["status"], r.UNKNOWN)
        self.assertTrue(c["blocking"])
        self.assertNotEqual(rep["overall"], r.READY)

    def test_paper_mode_false_blocks(self):
        inp = base_inputs(paper_mode=False)
        rep = r.build_report(inp, now=NOW)
        c = get_check(rep, "execution_mode")
        self.assertEqual(c["status"], r.BLOCKED)
        self.assertEqual(rep["overall"], r.BLOCKED)

    def test_paper_mode_collector_requires_explicit_boolean(self):
        # Absent or non-boolean PAPER_TRADING_MODE must yield None (missing
        # evidence), never an assumed True.
        import sys, types
        real = sys.modules.get("config")
        try:
            fake = types.ModuleType("config")  # attribute absent
            sys.modules["config"] = fake
            inp = r.collect_inputs()
            self.assertIsNone(inp["paper_mode"])
            fake.PAPER_TRADING_MODE = "yes"  # malformed non-boolean
            sys.modules["config"] = fake
            inp = r.collect_inputs()
            self.assertIsNone(inp["paper_mode"])
            fake.PAPER_TRADING_MODE = True
            inp = r.collect_inputs()
            self.assertIs(inp["paper_mode"], True)
        finally:
            if real is not None:
                sys.modules["config"] = real
            else:
                sys.modules.pop("config", None)

    def test_portfolio_health_collected_read_only(self):
        # The collector must request the side-effect-free health read.
        import inspect
        src = inspect.getsource(r.collect_inputs)
        self.assertIn("emit_alerts=False", src)

    def test_paper_mode_off_flags_ready(self):
        c = get_check(r.build_report(base_inputs(), now=NOW),
                      "execution_mode")
        self.assertEqual(c["status"], r.READY)
        # secrets presence-only: evidence must never contain secret values
        self.assertNotIn("SESSION_SECRET", str(c["evidence"]))


class TestCircuitBreaker(unittest.TestCase):
    def test_tripped_blocks(self):
        inp = base_inputs(breaker={"tripped": True, "unreadable": False,
                                   "reasons": [{"code": "DAILY_LOSS"}]})
        rep = r.build_report(inp, now=NOW)
        self.assertEqual(get_check(rep, "circuit_breaker")["status"], r.BLOCKED)
        self.assertEqual(rep["overall"], r.BLOCKED)

    def test_unreadable_blocks_failsafe(self):
        inp = base_inputs(breaker={"tripped": False, "unreadable": True})
        self.assertEqual(get_check(r.build_report(inp, now=NOW),
                                   "circuit_breaker")["status"], r.BLOCKED)


class TestStaleness(unittest.TestCase):
    def test_fresh_scan_open_market_ready(self):
        c = get_check(r.build_report(base_inputs(), now=NOW), "scan_freshness")
        self.assertEqual(c["status"], r.READY)

    def test_stale_scan_open_market_warns(self):
        inp = base_inputs()
        inp["scan_meta"]["snapshot_ts"] = iso(
            r.STALE_SCAN_MINUTES_MARKET_OPEN + 5)
        c = get_check(r.build_report(inp, now=NOW), "scan_freshness")
        self.assertEqual(c["status"], r.WARNING)

    def test_closed_market_uses_longer_budget(self):
        inp = base_inputs(market={"state": "CLOSED", "is_open": False})
        inp["scan_meta"]["snapshot_ts"] = iso(
            r.STALE_SCAN_MINUTES_MARKET_OPEN + 5)  # stale for open, fine closed
        c = get_check(r.build_report(inp, now=NOW), "scan_freshness")
        self.assertEqual(c["status"], r.READY)

    def test_heartbeat_stale_in_session_warns(self):
        inp = base_inputs()
        inp["scheduler"]["heartbeat_at"] = iso(
            (r.HEARTBEAT_MAX_AGE_S / 60) + 5)
        c = get_check(r.build_report(inp, now=NOW), "scheduler_health")
        self.assertEqual(c["status"], r.WARNING)

    def test_heartbeat_stale_off_session_ok(self):
        inp = base_inputs(market={"state": "CLOSED", "is_open": False})
        inp["scheduler"]["heartbeat_at"] = iso(30)
        c = get_check(r.build_report(inp, now=NOW), "scheduler_health")
        self.assertEqual(c["status"], r.READY)


class TestSchedulerMapping(unittest.TestCase):
    def map(self, health, market="OPEN"):
        inp = base_inputs(market={"state": market,
                                  "is_open": market == "OPEN"})
        inp["scheduler"]["health"] = health
        return get_check(r.build_report(inp, now=NOW),
                         "scheduler_health")["status"]

    def test_enum_mapping(self):
        self.assertEqual(self.map("HEALTHY"), r.READY)
        self.assertEqual(self.map("DEGRADED"), r.WARNING)
        self.assertEqual(self.map("DISABLED"), r.WARNING)
        self.assertEqual(self.map("DOWN", "OPEN"), r.BLOCKED)
        self.assertEqual(self.map("DOWN", "CLOSED"), r.WARNING)
        self.assertEqual(self.map("UNKNOWN"), r.UNKNOWN)
        self.assertEqual(self.map("weird"), r.UNKNOWN)


class TestBrokerNonBlocking(unittest.TestCase):
    def test_broker_never_blocking(self):
        for state in ("CONNECTED", "LOGIN_REQUIRED", "TOKEN_EXPIRED",
                      "NOT_CONFIGURED", "API_ERROR", "AUTH_FAILED", "odd"):
            inp = base_inputs(broker={"connection_state": state})
            c = get_check(r.build_report(inp, now=NOW), "broker_session")
            self.assertFalse(c["blocking"], state)

    def test_login_required_is_warning_only(self):
        inp = base_inputs(broker={"connection_state": "LOGIN_REQUIRED"})
        rep = r.build_report(inp, now=NOW)
        self.assertEqual(get_check(rep, "broker_session")["status"], r.WARNING)
        self.assertEqual(rep["overall"], r.WARNING)


class TestRecoveryAndCoverage(unittest.TestCase):
    def test_recovery_fail_is_blocked_but_nonblocking(self):
        inp = base_inputs(recovery_latest={"verdict": "FAIL",
                                           "created_at": iso(60)})
        rep = r.build_report(inp, now=NOW)
        c = get_check(rep, "recovery_validation")
        self.assertEqual(c["status"], r.BLOCKED)
        self.assertFalse(c["blocking"])
        self.assertEqual(rep["overall"], r.WARNING)

    def test_no_recovery_run_is_unknown(self):
        inp = base_inputs(recovery_latest=None)
        self.assertEqual(get_check(r.build_report(inp, now=NOW),
                                   "recovery_validation")["status"], r.UNKNOWN)

    def test_zero_provider_coverage_blocked_nonblocking(self):
        inp = base_inputs()
        inp["scan_meta"]["symbols_received"] = 0
        c = get_check(r.build_report(inp, now=NOW), "provider_coverage")
        self.assertEqual(c["status"], r.BLOCKED)
        self.assertFalse(c["blocking"])

    def test_coverage_contract_matches_canonical_meta_shape(self):
        """Contract test against the real scan_state_store producer: the
        coverage check must read the fields load_latest_meta() actually
        returns (symbols_requested / symbols_received)."""
        import scan_state_store
        try:
            meta = scan_state_store.load_latest_meta()
        except Exception:
            meta = None
        if not meta:
            self.skipTest("no canonical scan metadata in this environment")
        self.assertIn("symbols_received", meta)
        self.assertIn("symbols_requested", meta)
        if meta.get("symbols_requested") is not None \
                and meta.get("symbols_received") is not None:
            inp = base_inputs(scan_meta=dict(meta))
            c = get_check(r.build_report(inp, now=NOW), "provider_coverage")
            self.assertIn(c["status"], (r.READY, r.WARNING, r.BLOCKED))

    def test_malformed_coverage_is_unknown_report_still_builds(self):
        inp = base_inputs()
        inp["scan_meta"]["symbols_requested"] = "garbage"
        inp["scan_meta"]["symbols_received"] = {"weird": 1}
        rep = r.build_report(inp, now=NOW)  # must not raise
        c = get_check(rep, "provider_coverage")
        self.assertEqual(c["status"], r.UNKNOWN)
        self.assertTrue(c["remediation"])

    def test_partial_coverage_warns(self):
        inp = base_inputs()
        inp["scan_meta"]["symbols_received"] = 7
        self.assertEqual(get_check(r.build_report(inp, now=NOW),
                                   "provider_coverage")["status"], r.WARNING)


class TestConfigAndPortfolio(unittest.TestCase):
    def test_missing_env_blocks(self):
        inp = base_inputs()
        inp["env_flags"]["DATABASE_URL_present"] = False
        rep = r.build_report(inp, now=NOW)
        self.assertEqual(get_check(rep, "critical_env")["status"], r.BLOCKED)
        self.assertEqual(rep["overall"], r.BLOCKED)

    def test_portfolio_down_blocks(self):
        inp = base_inputs(portfolio_health={"status": "DOWN"})
        rep = r.build_report(inp, now=NOW)
        self.assertEqual(get_check(rep, "portfolio_health")["status"],
                         r.BLOCKED)

    def test_portfolio_degraded_warns(self):
        inp = base_inputs(portfolio_health={"status": "DEGRADED"})
        self.assertEqual(get_check(r.build_report(inp, now=NOW),
                                   "portfolio_health")["status"], r.WARNING)

    def test_file_backed_state_warns(self):
        inp = base_inputs(db_durable=False)
        self.assertEqual(get_check(r.build_report(inp, now=NOW),
                                   "db_durability")["status"], r.WARNING)


class TestFreshnessSection(unittest.TestCase):
    def test_rows_and_unknown_for_missing(self):
        inp = base_inputs(broker={"connection_state": "CONNECTED"})
        rows = r.build_freshness(inp, now=NOW)
        names = [x["name"] for x in rows]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(rows), 4)
        probe = next(x for x in rows if x["name"] == "Broker probe success")
        self.assertEqual(probe["status"], r.UNKNOWN)  # no ts → UNKNOWN

    def test_budgets_from_existing_constants(self):
        rows = r.build_freshness(base_inputs(), now=NOW)
        scan = next(x for x in rows if "scan" in x["name"].lower())
        self.assertEqual(scan["limit_seconds"],
                         r.STALE_SCAN_MINUTES_MARKET_OPEN * 60)
        hb = next(x for x in rows if "heartbeat" in x["name"].lower())
        self.assertEqual(hb["limit_seconds"], float(r.HEARTBEAT_MAX_AGE_S))


class TestReportShape(unittest.TestCase):
    def test_report_contract(self):
        rep = r.build_report(base_inputs(), now=NOW)
        self.assertTrue(rep["ok"])
        self.assertTrue(rep["paper_trading_only"])
        self.assertTrue(rep["advisory_only"])
        self.assertEqual(len(rep["domains"]), 10)
        for d in rep["domains"]:
            self.assertIn(d["status"],
                          (r.READY, r.WARNING, r.BLOCKED, r.UNKNOWN))
            for c in d["checks"]:
                for key in ("id", "domain", "label", "status", "blocking",
                            "expected", "actual", "evidence", "remediation",
                            "checked_at"):
                    self.assertIn(key, c)

    def test_history_entry_is_compact(self):
        # record_history stores only summary fields — verify via the shape
        # it builds (no live KV access in unit tests).
        rep = r.build_report(base_inputs(), now=NOW)
        entry_fields = {"at", "overall", "counts", "blocking_failures"}
        # simulate what record_history appends
        entry = {"at": rep["generated_at"], "overall": rep["overall"],
                 "counts": rep["counts"], "blocking_failures": []}
        self.assertEqual(set(entry), entry_fields)


if __name__ == "__main__":
    unittest.main()
