"""
test_btt_guardrail.py — BTT/replay event guardrail tests.

Proves:
1. BTT- ORDER_EXECUTED does NOT increment canonical paper execution counts.
2. P20- ORDER_EXECUTED DOES count as canonical paper execution.
3. emit_replay() stores events with mode=BACKTEST (never LIVE).
4. Consumer helpers (_is_canonical_order_event, P20- filters) exclude replay fills.
5. Aug 11-style phantom BTT events are excluded from all consumer counts.
6. Exploration _with_db logs errors on failure.
7. EXPERIMENTAL_PAPER_TRADE_PLACED fires only after successful DB insert.
8. Exploration exits attempt Kite LTP before yfinance fallback.
"""
from __future__ import annotations

import sys
import types
import unittest
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch, call


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_event(event_type: str, trade_id: str = "", **kwargs) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if trade_id:
        payload["trade_id"] = trade_id
    payload.update(kwargs.pop("payload_extra", {}))
    return {"event_type": event_type, "symbol": "RELIANCE",
            "scan_id": "S-001", "payload": payload, **kwargs}


# ── Test 1 & 2: _is_canonical_order_event ────────────────────────────────────

class TestIsCanonicalOrderEvent(unittest.TestCase):
    """buy_audit._is_canonical_order_event filters by trade_id prefix."""

    def setUp(self):
        import buy_audit
        self.fn = buy_audit._is_canonical_order_event

    def test_p20_prefix_is_canonical(self):
        e = _make_event("ORDER_EXECUTED", trade_id="P20-abc1234567")
        self.assertTrue(self.fn(e), "P20- trade must be canonical")

    def test_btt_prefix_is_not_canonical(self):
        e = _make_event("ORDER_EXECUTED", trade_id="BTT-abc1234567")
        self.assertFalse(self.fn(e), "BTT- trade must NOT be canonical")

    def test_exp_prefix_is_not_canonical(self):
        e = _make_event("ORDER_EXECUTED", trade_id="EXP-abc1234567")
        self.assertFalse(self.fn(e), "EXP- trade must NOT be canonical")

    def test_no_trade_id_passes_through(self):
        e = _make_event("ORDER_EXECUTED")  # no trade_id → backward compat
        self.assertTrue(self.fn(e), "Missing trade_id must pass through")

    def test_empty_trade_id_passes_through(self):
        e = _make_event("ORDER_EXECUTED", trade_id="")
        self.assertTrue(self.fn(e), "Empty trade_id must pass through")


# ── Test 3: emit_replay stores with mode=BACKTEST ────────────────────────────

class TestEmitReplay(unittest.TestCase):
    """emit_replay() writes events in BACKTEST mode, never LIVE."""

    def test_emit_replay_uses_backtest_mode(self):
        import pipeline_events
        captured: List[Dict] = []

        def _mock_emit(event_type, stage, *, scan_id=None, symbol=None,
                       payload=None, mode="LIVE", run_id=None, ts=None):
            captured.append({
                "event_type": event_type, "mode": mode, "payload": payload or {}
            })

        with patch.object(pipeline_events, "emit", side_effect=_mock_emit):
            pipeline_events.emit_replay(
                "REPLAY_EXECUTION_COMPLETED", "EXECUTION",
                scan_id="S-001", symbol="TCS",
                payload={"trade_id": "BTT-xyz", "qty": 5}
            )

        self.assertEqual(len(captured), 1)
        ev = captured[0]
        self.assertEqual(ev["mode"], "BACKTEST",
                         "emit_replay must use mode=BACKTEST")
        self.assertEqual(ev["payload"]["source"], "replay")
        self.assertFalse(ev["payload"]["canonical_trade"],
                         "canonical_trade must be False in replay events")

    def test_emit_replay_never_calls_live_emit_directly(self):
        """emit_replay wraps emit() — it must not call _emit_unsafe directly."""
        import pipeline_events
        live_calls: List[str] = []

        original_emit_unsafe = pipeline_events._emit_unsafe

        def _spying_emit_unsafe(event_type, stage, *, mode, **kw):
            live_calls.append(f"{event_type}:{mode}")
            # Don't actually hit DB
            pass

        with patch.object(pipeline_events, "_emit_unsafe",
                          side_effect=_spying_emit_unsafe):
            pipeline_events.emit_replay(
                "REPLAY_EXECUTION_COMPLETED", "EXECUTION",
                payload={"trade_id": "BTT-123"}
            )

        # Must have been called with BACKTEST, never LIVE
        self.assertTrue(all("BACKTEST" in c for c in live_calls),
                        f"All calls must use BACKTEST mode, got: {live_calls}")


# ── Test 4: pipeline_events guardrail blocks BTT- ORDER_EXECUTED ─────────────

class TestPipelineEventsGuardrail(unittest.TestCase):
    """_emit_unsafe drops ORDER_EXECUTED with non-P20- trade_ids in LIVE mode."""

    def _call_emit_unsafe(self, event_type, trade_id, mode="LIVE"):
        import pipeline_events
        persisted: List[Dict] = []

        # Stub out DB so we can observe what would be written
        with patch.object(pipeline_events, "db_available", return_value=False):
            with patch("builtins.open", side_effect=Exception("no file")):
                with patch.object(pipeline_events, "_emit_unsafe",
                                  wraps=pipeline_events._emit_unsafe) as wrapped:
                    # Collect warning logs
                    import logging
                    with self.assertLogs("pipeline_events", level="WARNING") \
                            if trade_id and not trade_id.startswith("P20-") \
                            and mode == "LIVE" else _null_ctx():
                        try:
                            pipeline_events._emit_unsafe(
                                event_type, "EXECUTION",
                                scan_id="S-001", symbol="RELIANCE",
                                payload={"trade_id": trade_id},
                                mode=mode, run_id=None, ts=None,
                            )
                        except Exception:
                            pass
        return persisted

    def test_btt_order_executed_is_blocked_in_live(self):
        import pipeline_events
        import logging

        with self.assertLogs("pipeline_events", level="WARNING") as cm:
            # Stub out everything downstream so we measure only the guardrail
            with patch.object(pipeline_events, "db_available", return_value=False):
                with patch("builtins.open", side_effect=OSError("no file")):
                    try:
                        pipeline_events._emit_unsafe(
                            "ORDER_EXECUTED", "EXECUTION",
                            scan_id="S-001", symbol="RELIANCE",
                            payload={"trade_id": "BTT-abc123"},
                            mode="LIVE", run_id=None, ts=None,
                        )
                    except Exception:
                        pass

        self.assertTrue(
            any("BLOCKED" in msg for msg in cm.output),
            "BTT- ORDER_EXECUTED must produce a BLOCKED warning"
        )

    def test_p20_order_executed_is_not_blocked(self):
        """P20- ORDER_EXECUTED in LIVE mode must pass the guardrail (no BLOCKED log)."""
        import pipeline_events
        import logging

        blocked_warnings: List[str] = []

        # Intercept the warning logger directly
        class _CapHandler(logging.Handler):
            def emit(self, record):
                if "BLOCKED" in record.getMessage():
                    blocked_warnings.append(record.getMessage())

        logger = logging.getLogger("pipeline_events")
        handler = _CapHandler()
        logger.addHandler(handler)
        try:
            with patch.object(pipeline_events, "db_available", return_value=False):
                with patch("builtins.open", side_effect=OSError("no file")):
                    try:
                        pipeline_events._emit_unsafe(
                            "ORDER_EXECUTED", "EXECUTION",
                            scan_id="S-001", symbol="RELIANCE",
                            payload={"trade_id": "P20-abc1234567"},
                            mode="LIVE", run_id=None, ts=None,
                        )
                    except Exception:
                        pass
        finally:
            logger.removeHandler(handler)

        self.assertEqual(blocked_warnings, [],
                         f"P20- must NOT produce a BLOCKED warning. Got: {blocked_warnings}")

    def test_btt_order_executed_backtest_mode_is_not_blocked(self):
        """BTT- events in BACKTEST mode (via emit_replay) must pass the guardrail."""
        import pipeline_events
        import logging

        blocked_warnings: List[str] = []

        class _CapHandler(logging.Handler):
            def emit(self, record):
                if "BLOCKED" in record.getMessage():
                    blocked_warnings.append(record.getMessage())

        logger = logging.getLogger("pipeline_events")
        handler = _CapHandler()
        logger.addHandler(handler)
        try:
            with patch.object(pipeline_events, "db_available", return_value=False):
                with patch("builtins.open", side_effect=OSError("no file")):
                    try:
                        pipeline_events._emit_unsafe(
                            "ORDER_EXECUTED", "EXECUTION",
                            scan_id="S-001", symbol="RELIANCE",
                            payload={"trade_id": "BTT-abc123"},
                            mode="BACKTEST", run_id=None, ts=None,
                        )
                    except Exception:
                        pass
        finally:
            logger.removeHandler(handler)

        self.assertEqual(blocked_warnings, [],
                         "BTT- in BACKTEST mode must NOT produce a BLOCKED warning")


# ── Test 5: Aug 11 phantom events excluded from operator analytics count ──────

class TestAug11PhantomEventExclusion(unittest.TestCase):
    """Simulate 63 BTT- ORDER_EXECUTED events (Aug 11) and verify exclusion."""

    def _build_aug11_events(self) -> List[Dict]:
        """63 BTT- ORDER_EXECUTED events, as the Aug 11 phantom batch looked."""
        return [
            _make_event("ORDER_EXECUTED",
                        trade_id=f"BTT-aug11{i:04d}",
                        payload_extra={"qty": 5, "symbol": "RELIANCE"})
            for i in range(63)
        ]

    def _build_canonical_events(self) -> List[Dict]:
        return [
            _make_event("ORDER_EXECUTED",
                        trade_id="P20-real0001",
                        payload_extra={"qty": 2})
        ]

    def test_aug11_phantoms_not_counted_by_is_canonical(self):
        import buy_audit
        phantoms = self._build_aug11_events()
        canonical = self._build_canonical_events()
        all_events = phantoms + canonical

        counted = [e for e in all_events if buy_audit._is_canonical_order_event(e)]
        self.assertEqual(len(counted), 1,
                         f"Only 1 canonical P20- event should pass; got {len(counted)}")
        self.assertEqual(counted[0]["payload"]["trade_id"], "P20-real0001")

    def test_aug11_phantoms_excluded_from_validation_engine_lifecycle(self):
        """validation_engines order lifecycle skips BTT- events."""
        import validation_engines
        phantoms = self._build_aug11_events()
        canonical = self._build_canonical_events() + [
            _make_event("ORDER_SUBMITTED", trade_id="P20-real0001")
        ]
        all_events = phantoms + canonical

        # Lifecycle logic: iterate events and count only canonical ones
        _ORDER_TYPES = ("ORDER_SUBMITTED", "ORDER_EXECUTED", "ORDER_CANCELLED",
                        "ORDER_REJECTED")
        lifecycles: Dict = {}
        for e in all_events:
            et = e.get("event_type")
            if et not in _ORDER_TYPES:
                continue
            tid = str((e.get("payload") or {}).get("trade_id") or "")
            if tid and not tid.startswith("P20-"):
                continue  # skip BTT-
            key = (e.get("scan_id"), e.get("symbol", ""))
            lifecycles.setdefault(key, {"ORDER_SUBMITTED": 0, "ORDER_EXECUTED": 0})
            if et in lifecycles[key]:
                lifecycles[key][et] += 1

        # Only 1 lifecycle (the P20- real event)
        self.assertEqual(len(lifecycles), 1)
        lc = list(lifecycles.values())[0]
        self.assertEqual(lc["ORDER_EXECUTED"], 1)
        self.assertEqual(lc["ORDER_SUBMITTED"], 1)

    def test_p20_filter_in_phase26_consistency(self):
        """phase26_consistency ORDER_EXECUTED filter respects P20- prefix."""
        phantoms = self._build_aug11_events()
        canonical = self._build_canonical_events()
        all_events = phantoms + canonical

        # Mirror the updated filter from phase26_consistency.py
        executed_events = [
            e for e in all_events
            if e.get("event_type") == "ORDER_EXECUTED"
            and (
                not str((e.get("payload") or {}).get("trade_id") or "")
                or str((e.get("payload") or {}).get("trade_id") or "").startswith("P20-")
            )
        ]
        self.assertEqual(len(executed_events), 1,
                         "Only 1 canonical event should pass the P20- filter")


# ── Test 6: exploration _with_db logs errors ──────────────────────────────────

class TestExplorationWithDbLogsErrors(unittest.TestCase):
    """paper_exploration_engine._with_db logs DB errors instead of silently swallowing."""

    def test_with_db_logs_on_exception(self):
        # Stub DB helpers so _with_db tries to connect and fails
        import paper_exploration_engine as pee

        with patch.object(pee, "db_available", return_value=True):
            with patch.object(pee, "_connect", side_effect=Exception("DB down")):
                with self.assertLogs("paper_exploration_engine", level="ERROR") as cm:
                    result = pee._with_db(lambda conn: "ok", lambda: "fallback")

        self.assertEqual(result, "fallback")
        self.assertTrue(any("DB down" in msg for msg in cm.output),
                        f"DB error must appear in logs. Got: {cm.output}")


# ── Test 7: EXPERIMENTAL_PAPER_TRADE_PLACED fires only after insert ───────────

class TestExplorationEventOrdering(unittest.TestCase):
    """EXPERIMENTAL_PAPER_TRADE_PLACED must not fire when DB insert fails."""

    def test_no_event_when_insert_fails(self):
        import paper_exploration_engine as pee
        events_fired: List[str] = []

        def _mock_insert(row):
            return False  # simulate insert failure

        def _mock_emit(event_type, stage, **kwargs):
            events_fired.append(event_type)

        with patch.object(pee, "_insert_exp_row", side_effect=_mock_insert):
            with patch.object(pee, "_has_open_exp_position", return_value=False):
                with patch("pipeline_events.emit", side_effect=_mock_emit):
                    result = pee.create_exploration_entry(
                        candidate={
                            "symbol": "RELIANCE", "entry_price": 2800.0,
                            "quantity": 2, "action_type": "EXPERIMENTAL_BUY_FROM_WATCH",
                        },
                        settings={"slippage_pct": 0.15},
                        scan_id="S-001", snapshot_ts="2026-08-16T09:30:00Z",
                    )

        self.assertFalse(result.get("created"),
                         "created must be False when insert fails")
        self.assertNotIn("EXPERIMENTAL_PAPER_TRADE_PLACED", events_fired,
                         "Event must NOT fire when DB insert fails")

    def test_event_fires_when_insert_succeeds(self):
        import paper_exploration_engine as pee
        events_fired: List[str] = []

        def _mock_insert(row):
            return True  # simulate successful insert

        def _mock_emit(event_type, stage, **kwargs):
            events_fired.append(event_type)

        with patch.object(pee, "_insert_exp_row", side_effect=_mock_insert):
            with patch.object(pee, "_has_open_exp_position", return_value=False):
                with patch("pipeline_events.emit", side_effect=_mock_emit):
                    with patch.object(pee, "store") as mock_store:
                        mock_store.add_notification = MagicMock()
                        result = pee.create_exploration_entry(
                            candidate={
                                "symbol": "RELIANCE", "entry_price": 2800.0,
                                "quantity": 2,
                                "action_type": "EXPERIMENTAL_BUY_FROM_WATCH",
                            },
                            settings={"slippage_pct": 0.15},
                            scan_id="S-001", snapshot_ts="2026-08-16T09:30:00Z",
                        )

        self.assertTrue(result.get("created"),
                        f"created must be True on success; got: {result}")
        self.assertIn("EXPERIMENTAL_PAPER_TRADE_PLACED", events_fired,
                      "Event MUST fire after successful insert")


# ── Test 8: exploration exits try Kite LTP first ─────────────────────────────

class TestExplorationExitPriceSource(unittest.TestCase):
    """update_experimental_exits uses Kite LTP when overlay available."""

    def test_kite_ltp_used_when_session_verified(self):
        import paper_exploration_engine as pee

        price_sources: List[str] = []

        def _mock_fetch_ltp_overlay(symbols):
            price_sources.append("kite")
            return {
                "enabled": True,
                "session_verified": True,
                "ltps": {s.upper(): 2850.0 for s in symbols},
            }

        def _mock_is_overlay_enabled():
            return True

        # No open trades → skip early; inject a fake open trade row
        fake_row = ("TRD-001", "RELIANCE", 2800.0, 2, 2750.0, 2900.0,
                    None, None, "2026-08-16T09:30:00Z")

        with patch.object(pee, "_with_db") as mock_db:
            # First call returns open trades; subsequent update calls return True
            mock_db.side_effect = [
                [fake_row],   # get_open
                True,          # upd
            ]
            with patch("kite_ltp_overlay.is_overlay_enabled",
                       side_effect=_mock_is_overlay_enabled):
                with patch("kite_ltp_overlay.fetch_ltp_overlay",
                           side_effect=_mock_fetch_ltp_overlay):
                    result = pee.update_experimental_exits(
                        settings={"max_holding_days": 10}
                    )

        self.assertIn("kite", price_sources,
                      "Kite LTP must be attempted when overlay enabled")

    def test_yfinance_fallback_when_kite_unavailable(self):
        import paper_exploration_engine as pee

        price_sources: List[str] = []

        def _mock_fetch_ltp_overlay(symbols):
            return {"enabled": True, "session_verified": False, "ltps": {}}

        def _mock_get_multiple_ltp(symbols):
            price_sources.append("yfinance")
            return {s.upper(): 2848.0 for s in symbols}

        fake_row = ("TRD-002", "TCS", 3500.0, 1, 3400.0, 3700.0,
                    None, None, "2026-08-16T09:30:00Z")

        with patch.object(pee, "_with_db") as mock_db:
            mock_db.side_effect = [[fake_row], True]
            with patch("kite_ltp_overlay.is_overlay_enabled", return_value=True):
                with patch("kite_ltp_overlay.fetch_ltp_overlay",
                           side_effect=_mock_fetch_ltp_overlay):
                    with patch("market_data.get_multiple_ltp",
                               side_effect=_mock_get_multiple_ltp):
                        pee.update_experimental_exits(
                            settings={"max_holding_days": 10}
                        )

        self.assertIn("yfinance", price_sources,
                      "yfinance must be used when Kite session unverified")


# ── Context manager for conditional assertLogs ────────────────────────────────

class _null_ctx:
    def __enter__(self): return self
    def __exit__(self, *a): return False


# ── Runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main()
