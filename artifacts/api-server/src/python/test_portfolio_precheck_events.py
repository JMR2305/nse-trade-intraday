"""
test_portfolio_precheck_events.py — Phase 26A: Portfolio Pre-Check visibility.

Verifies that:
  1. Every BUY candidate evaluated by the Portfolio Pre-Check emits exactly one
     PRECHECK_APPROVED / PRECHECK_REJECTED event with the EXACT reason codes
     returned by the Portfolio Engine (single source of validation logic —
     the emitter copies, never recomputes).
  2. Each rejection rule (allocation + limit gates + fail-closed error path)
     surfaces its exact reason in the event payload.
  3. The canonical stage vocabulary contains PORTFOLIO_PRECHECK between
     STRATEGY and RISK, and stage_summary counts the new events.
  4. Unified replay rebuilds the pre-check stage from events alone:
     pre-check-rejected symbols never reach the Risk stage, and the count
     contract (in = out + rejected + pending + cancelled) holds.

Runs against the pipeline_events file fallback (no DATABASE_URL) so the dev
database is never touched.
"""

import os
import unittest
from unittest import mock

import pipeline_events as pe
import replay_engine


class PrecheckEventsBase(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        os.environ.pop("DATABASE_URL", None)
        self._tmp = pe.FALLBACK_FILE + ".precheck-test"
        self._orig_file = pe.FALLBACK_FILE
        pe.FALLBACK_FILE = self._tmp
        if os.path.exists(self._tmp):
            os.remove(self._tmp)

    def tearDown(self):
        pe.FALLBACK_FILE = self._orig_file
        if os.path.exists(self._tmp):
            os.remove(self._tmp)
        self._env.stop()


def _run_execute_buy(precheck_result, scan_id="scan-t1", symbol="TCS",
                     qty=10, price=100.0):
    """Call paper_trader.execute_buy with the bridge mocked to return
    `precheck_result`. The phase11 risk gate is mocked to block so an
    APPROVED pre-check never mutates portfolio state (hermetic)."""
    import paper_trader
    import portfolio_bridge
    with mock.patch.object(portfolio_bridge, "pre_check",
                           return_value=precheck_result), \
         mock.patch("phase11_risk.pre_trade_check",
                    return_value=(False, "TEST STOP — hermetic")):
        return paper_trader.execute_buy(
            symbol, qty, price, scan_id=scan_id,
            ledger_trade_id="T-TEST", strategy_id="strat_x")


def _precheck_events(scan_id="scan-t1"):
    return [e for e in pe.query_events(scan_id=scan_id, limit=100)
            if e["stage"] == "PORTFOLIO_PRECHECK"]


class TestVocabulary(unittest.TestCase):
    def test_stage_between_strategy_and_risk(self):
        i = pe.STAGES.index
        self.assertEqual(i("PORTFOLIO_PRECHECK"), i("STRATEGY") + 1)
        self.assertEqual(i("RISK"), i("PORTFOLIO_PRECHECK") + 1)

    def test_event_types_registered(self):
        self.assertIn("PRECHECK_APPROVED", pe.EVENT_TYPES)
        self.assertIn("PRECHECK_REJECTED", pe.EVENT_TYPES)
        self.assertIn("PRECHECK_APPROVED", pe.COMPLETED_EVENT_TYPES)
        self.assertIn("PRECHECK_REJECTED", pe.REJECTED_EVENT_TYPES)


class TestEmission(PrecheckEventsBase):
    REJECTION_CASES = [
        # (reason list from the Portfolio Engine, description)
        (["DAILY_LOSS_LIMIT_BREACHED"], "daily loss allocation gate"),
        (["DRAWDOWN_LIMIT_BREACHED"], "drawdown allocation gate"),
        (["INSUFFICIENT_BUYING_POWER"], "buying power allocation gate"),
        (["BELOW_MIN_ORDER_VALUE"], "min order value allocation gate"),
        (["LIMIT_BREACH:max_gross_exposure"], "gross exposure limit"),
        (["LIMIT_BREACH:max_instrument_exposure"], "instrument exposure limit"),
        (["LIMIT_BREACH:max_sector_exposure"], "sector exposure limit"),
        (["LIMIT_BREACH:max_strategy_exposure"], "strategy exposure limit"),
        (["LIMIT_BREACH:max_open_positions"], "open positions limit"),
        (["LIMIT_BREACH:max_pending_orders"], "pending orders limit"),
        (["LIMIT_BREACH:cash_reserve"], "cash reserve limit"),
        (["PORTFOLIO_PRECHECK_ERROR: boom"], "fail-closed internal error"),
        (["INSUFFICIENT_BUYING_POWER", "LIMIT_BREACH:max_open_positions"],
         "multiple reasons preserved in order"),
    ]

    def test_every_rejection_rule_emits_exact_reasons(self):
        for idx, (reasons, desc) in enumerate(self.REJECTION_CASES):
            scan_id = f"scan-rej-{idx}"
            ok, msg = _run_execute_buy(
                {"approved": False, "reasons": reasons,
                 "allocation_status": "REJECTED", "limits_allowed": False,
                 "blocking_limit": None}, scan_id=scan_id)
            self.assertFalse(ok, desc)
            self.assertIn("PORTFOLIO BLOCKED", msg, desc)
            evs = _precheck_events(scan_id)
            self.assertEqual(len(evs), 1, desc)
            e = evs[0]
            self.assertEqual(e["event_type"], "PRECHECK_REJECTED", desc)
            self.assertEqual(e["symbol"], "TCS", desc)
            # EXACT reasons copied from the Portfolio Engine — never recomputed
            self.assertEqual(e["payload"]["reasons"], reasons, desc)
            self.assertFalse(e["payload"]["approved"], desc)

    def test_approved_emits_event_before_downstream_gates(self):
        ok, msg = _run_execute_buy(
            {"approved": True, "reasons": [],
             "allocation_status": "APPROVED", "limits_allowed": True,
             "blocking_limit": None, "approved_capital": 1000.0})
        # Blocked downstream by the (mocked) phase11 gate — no state mutated,
        # but the pre-check APPROVED decision is already on record.
        self.assertFalse(ok)
        self.assertIn("RISK BLOCKED", msg)
        evs = _precheck_events()
        self.assertEqual(len(evs), 1)
        e = evs[0]
        self.assertEqual(e["event_type"], "PRECHECK_APPROVED")
        self.assertTrue(e["payload"]["approved"])
        self.assertEqual(e["payload"]["approved_capital"], 1000.0)
        self.assertEqual(e["payload"]["strategy_id"], "strat_x")
        self.assertEqual(e["payload"]["ledger_trade_id"], "T-TEST")

    def test_disabled_portfolio_is_visible_as_approved_with_reason(self):
        ok, _ = _run_execute_buy(
            {"approved": True, "reasons": ["PORTFOLIO_DISABLED"],
             "allocation_status": "SKIPPED", "limits_allowed": True})
        self.assertFalse(ok)  # mocked phase11 stop
        evs = _precheck_events()
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["payload"]["reasons"], ["PORTFOLIO_DISABLED"])

    def test_emit_failure_never_blocks_trading(self):
        with mock.patch.object(pe, "emit", side_effect=RuntimeError("db down")):
            ok, msg = _run_execute_buy(
                {"approved": False, "reasons": ["INSUFFICIENT_BUYING_POWER"],
                 "allocation_status": "REJECTED", "limits_allowed": False})
        # Decision still enforced even when the event store is unavailable.
        self.assertFalse(ok)
        self.assertIn("PORTFOLIO BLOCKED", msg)

    def test_stage_summary_counts_precheck_events(self):
        pe.emit("PRECHECK_APPROVED", "PORTFOLIO_PRECHECK", scan_id="s9",
                symbol="TCS", payload={"approved": True, "reasons": []})
        pe.emit("PRECHECK_REJECTED", "PORTFOLIO_PRECHECK", scan_id="s9",
                symbol="INFY",
                payload={"approved": False,
                         "reasons": ["LIMIT_BREACH:max_open_positions"]})
        summ = pe.stage_summary(scan_id="s9")
        by = {s["stage"]: s for s in summ["stages"]}
        st = by["PORTFOLIO_PRECHECK"]
        self.assertEqual(st["events"], 2)
        self.assertEqual(st["completed"], 1)
        self.assertEqual(st["rejected"], 1)


def _snapshot(symbols, buy=("AAA",)):
    """Minimal snapshot where all symbols pass every stage up to AI BUY."""
    return {
        "scan_id": "scan-replay",
        "snapshot_ts": "2026-08-09T09:20:00Z",
        "universe_size": len(symbols),
        "recommendations": [
            {"symbol": s, "data_quality": "OK", "strategy_id": "strat_x",
             "all_gates_passed": True,
             "final_action": "BUY" if s in buy else "WATCH",
             "paper_eligible": s in buy}
            for s in symbols
        ],
        "provider_health": {"symbols_requested": len(symbols),
                            "symbols_received": len(symbols)},
        "timings": {},
    }


class TestIntelligencePathAttribution(PrecheckEventsBase):
    """The intelligence._execute_trades production buy path must attribute
    pre-check events to the canonical scan so build_replay(scan_id) sees them."""

    def test_intelligence_buy_path_threads_canonical_scan_id(self):
        import intelligence
        import scan_state_store
        ai_decisions = [{"stock": "TCS", "decision": "STRONG_BUY",
                         "entry_price": 100.0, "confidence": 80.0}]
        enriched = [{"position_sizing": {"suggested_quantity": 5},
                     "explainability": {}}]
        captured = {}

        def _fake_execute_buy(symbol, qty, price, **kw):
            captured["scan_id"] = kw.get("scan_id")
            return False, "hermetic stop"

        with mock.patch.object(scan_state_store, "load_latest_snapshot",
                               return_value={"scan_id": "scan-canon-1"}), \
             mock.patch.object(intelligence, "execute_buy",
                               side_effect=_fake_execute_buy), \
             mock.patch.object(intelligence, "_load_state",
                               return_value={"positions": {}}):
            intelligence._execute_trades(ai_decisions, enriched, 10_000.0)
        self.assertEqual(captured.get("scan_id"), "scan-canon-1")

    def test_intelligence_buy_path_failsafe_without_snapshot(self):
        import intelligence
        import scan_state_store
        ai_decisions = [{"stock": "TCS", "decision": "STRONG_BUY",
                         "entry_price": 100.0, "confidence": 80.0}]
        enriched = [{"position_sizing": {"suggested_quantity": 5},
                     "explainability": {}}]
        captured = {}

        def _fake_execute_buy(symbol, qty, price, **kw):
            captured["scan_id"] = kw.get("scan_id", "MISSING")
            return False, "hermetic stop"

        with mock.patch.object(scan_state_store, "load_latest_snapshot",
                               side_effect=RuntimeError("db down")), \
             mock.patch.object(intelligence, "execute_buy",
                               side_effect=_fake_execute_buy), \
             mock.patch.object(intelligence, "_load_state",
                               return_value={"positions": {}}):
            intelligence._execute_trades(ai_decisions, enriched, 10_000.0)
        self.assertIsNone(captured.get("scan_id", "MISSING"))

    def test_intelligence_path_events_visible_in_scan_replay(self):
        """End-to-end: real execute_buy via intelligence path (bridge mocked to
        reject) emits an event attributed to the canonical scan, and
        _get_precheck_decisions(scan_id) reconstructs it."""
        import intelligence
        import scan_state_store
        import portfolio_bridge
        rejected = {"approved": False, "allocation_status": "OK",
                    "limits_allowed": False,
                    "reasons": ["LIMIT_BREACH:max_open_positions"],
                    "blocking_limit": "max_open_positions"}
        ai_decisions = [{"stock": "TCS", "decision": "STRONG_BUY",
                         "entry_price": 100.0, "confidence": 80.0}]
        enriched = [{"position_sizing": {"suggested_quantity": 5},
                     "explainability": {}}]
        with mock.patch.object(scan_state_store, "load_latest_snapshot",
                               return_value={"scan_id": "scan-canon-2"}), \
             mock.patch.object(portfolio_bridge, "pre_check",
                               return_value=rejected), \
             mock.patch.object(intelligence, "_load_state",
                               return_value={"positions": {}}):
            intelligence._execute_trades(ai_decisions, enriched, 10_000.0)
        decisions = replay_engine._get_precheck_decisions("scan-canon-2")
        self.assertIn("TCS", decisions)
        self.assertFalse(decisions["TCS"]["approved"])
        self.assertEqual(decisions["TCS"]["reasons"],
                         ["LIMIT_BREACH:max_open_positions"])


class TestReplayStage(PrecheckEventsBase):
    SYMS = ["AAA", "BBB", "CCC"]

    def _stages(self, precheck):
        return replay_engine._build_stages_from_snapshot(
            _snapshot(self.SYMS, buy=("AAA", "BBB")),
            precheck_decisions=precheck)

    def test_stage_inserted_between_strategy_and_risk(self):
        stages = self._stages({})
        ids = [s["id"] for s in stages]
        self.assertEqual(ids.index("portfolio_precheck"),
                         ids.index("strategy") + 1)
        self.assertEqual(ids.index("risk"),
                         ids.index("portfolio_precheck") + 1)
        # orders strictly increasing
        self.assertEqual([s["order"] for s in stages],
                         sorted(s["order"] for s in stages))
        self.assertEqual(len(set(s["order"] for s in stages)), len(stages))

    def test_rejected_symbol_never_reaches_risk(self):
        pc = {"AAA": {"approved": False,
                      "reasons": ["LIMIT_BREACH:max_open_positions"]},
              "BBB": {"approved": True, "reasons": []}}
        stages = self._stages(pc)
        by = {s["id"]: s for s in stages}
        p = by["portfolio_precheck"]
        self.assertEqual(p["rejected"], 1)
        self.assertEqual(p["rejected_symbols"], ["AAA"])
        self.assertEqual(p["rejection_reasons"]["AAA"],
                         ["LIMIT_BREACH:max_open_positions"])
        # Chaining: risk input = pre-check output; AAA excluded downstream
        self.assertEqual(by["risk"]["stocks_in"], p["stocks_out"])
        self.assertNotIn("AAA", by["risk"]["stocks"])
        self.assertNotIn("AAA", by["ai_decision"]["stocks"])
        self.assertNotIn("AAA", by["execution"]["stocks"])

    def test_unevaluated_symbols_never_counted_as_approved(self):
        """Strategy symbols with no BUY attempt (WATCH etc.) pass through the
        funnel for conservation but must NOT be reported as approved."""
        snap = _snapshot(["AAA", "BBB", "CCC"])
        decisions = {"AAA": {"approved": True, "reasons": []},
                     "BBB": {"approved": False,
                             "reasons": ["INSUFFICIENT_BUYING_POWER"]}}
        stages = replay_engine._build_stages_from_snapshot(
            snap, precheck_decisions=decisions)
        pcs = next(s for s in stages if s["id"] == "portfolio_precheck")
        self.assertEqual(pcs["evaluated_count"], 2)
        self.assertEqual(pcs["approved_count"], 1)   # only AAA
        self.assertEqual(pcs["rejected"], 1)         # only BBB
        self.assertEqual(pcs["not_evaluated"], 1)    # CCC passes through
        # conservation: in = out + rejected
        self.assertEqual(pcs["stocks_in"],
                         pcs["stocks_out"] + pcs["rejected"])

    def test_conservation_contract_holds(self):
        pc = {"AAA": {"approved": False, "reasons": ["INSUFFICIENT_BUYING_POWER"]}}
        for stages in (self._stages({}), self._stages(pc)):
            for s in stages:
                self.assertEqual(
                    s["stocks_in"],
                    s["stocks_out"] + max(0, s["rejected"]) + s["pending"]
                    + s["cancelled"],
                    f"conservation violated at {s['id']}")

    def test_decisions_replayed_from_events_alone(self):
        # Emit events, then rebuild the decision map purely from the store.
        pe.emit("PRECHECK_REJECTED", "PORTFOLIO_PRECHECK", scan_id="scan-ev",
                symbol="AAA",
                payload={"approved": False,
                         "reasons": ["DRAWDOWN_LIMIT_BREACHED"],
                         "blocking_limit": None})
        pe.emit("PRECHECK_APPROVED", "PORTFOLIO_PRECHECK", scan_id="scan-ev",
                symbol="BBB", payload={"approved": True, "reasons": []})
        dec = replay_engine._get_precheck_decisions("scan-ev")
        self.assertEqual(dec["AAA"]["approved"], False)
        self.assertEqual(dec["AAA"]["reasons"], ["DRAWDOWN_LIMIT_BREACHED"])
        self.assertEqual(dec["BBB"]["approved"], True)

    def test_last_decision_per_symbol_wins(self):
        pe.emit("PRECHECK_REJECTED", "PORTFOLIO_PRECHECK", scan_id="scan-ev2",
                symbol="AAA", payload={"approved": False,
                                       "reasons": ["INSUFFICIENT_BUYING_POWER"]})
        pe.emit("PRECHECK_APPROVED", "PORTFOLIO_PRECHECK", scan_id="scan-ev2",
                symbol="AAA", payload={"approved": True, "reasons": []})
        dec = replay_engine._get_precheck_decisions("scan-ev2")
        self.assertTrue(dec["AAA"]["approved"])

    def test_blocked_symbol_journey_skips_downstream_stages(self):
        rec = _snapshot(["AAA"], buy=("AAA",))["recommendations"][0]
        blocked = {"approved": False,
                   "reasons": ["LIMIT_BREACH:max_open_positions"]}
        journey = replay_engine._build_symbol_journey(
            rec, _snapshot(["AAA"]), precheck=blocked)
        by = {s["stage"]: s for s in journey}
        self.assertEqual(by["portfolio_precheck"]["result"], "BLOCKED")
        for stage in ("risk", "ai_decision", "execution"):
            self.assertEqual(by[stage]["result"], "SKIPPED", stage)
            self.assertIn("LIMIT_BREACH:max_open_positions",
                          by[stage]["reason"], stage)

    def test_approved_symbol_journey_untouched(self):
        rec = _snapshot(["AAA"], buy=("AAA",))["recommendations"][0]
        journey = replay_engine._build_symbol_journey(
            rec, _snapshot(["AAA"]),
            precheck={"approved": True, "reasons": []})
        by = {s["stage"]: s for s in journey}
        self.assertEqual(by["portfolio_precheck"]["result"], "PASS")
        self.assertEqual(by["risk"]["result"], "PASS")

    def test_event_store_failure_is_fail_safe(self):
        with mock.patch.object(pe, "query_events",
                               side_effect=RuntimeError("down")):
            self.assertEqual(replay_engine._get_precheck_decisions("x"), {})


if __name__ == "__main__":
    unittest.main()
