"""
tests/test_eod_reconciliation.py — Unit tests for eod_reconciliation._check_discrepancies()
and the per-day KV guard in run_eod_reconciliation().

Tests are fully self-contained: no DB, no broker API, no phase20_store required.
"""

from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Minimal stubs so the module can be imported without real dependencies
# ---------------------------------------------------------------------------

def _make_stub(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


def _stub_dependencies() -> None:
    """Install lightweight stubs for every import used by eod_reconciliation."""

    # phase20_store
    store_mod = _make_stub("phase20_store")
    _kv: dict = {}

    def kv_get(key):
        return _kv.get(key)

    def kv_set(key, value):
        _kv[key] = value

    def get_settings():
        # Return LIVE_ASSISTED so the live-mode branch is exercised
        return {"execution_mode": "LIVE_ASSISTED"}

    def add_notification(*a, **kw):
        pass

    store_mod.kv_get = kv_get
    store_mod.kv_set = kv_set
    store_mod.get_settings = get_settings
    store_mod.add_notification = add_notification
    store_mod._kv = _kv   # expose for test resets

    # scan_state_store — only referenced in run_eod_reconciliation's DB path
    sss_mod = _make_stub("scan_state_store")
    sss_mod._connect = MagicMock(side_effect=RuntimeError("no db in tests"))
    sss_mod.db_available = MagicMock(return_value=False)

    # email_alerts
    ea_mod = _make_stub("email_alerts")
    ea_mod.maybe_send_alert_email = MagicMock(return_value={"sent": False, "reason": "STUB"})

    # broker_client — used in run_eod_reconciliation live path
    bc_mod = _make_stub("broker_client")
    bc_mod.get_broker_client = MagicMock(side_effect=RuntimeError("no broker in tests"))


_stub_dependencies()

# Now safe to import
import importlib
import eod_reconciliation as recon


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------

def _local(
    id_: int = 1,
    broker_order_id: str = "B001",
    symbol: str = "RELIANCE",
    status: str = "OPEN",
    quantity: int = 10,
    price: float = 2500.0,
) -> dict:
    return {
        "id": id_,
        "broker_order_id": broker_order_id,
        "symbol": symbol,
        "status": status,
        "quantity": quantity,
        "price": price,
        "created_at": "2024-01-15T09:30:00Z",
    }


def _broker(
    order_id: str = "B001",
    symbol: str = "RELIANCE",
    status: str = "OPEN",
    filled_quantity: int = 0,
) -> dict:
    """Broker order as a plain dict (also exercised as attr-style object via _BObj)."""
    return {
        "order_id": order_id,
        "symbol": symbol,
        "status": status,
        "filled_quantity": filled_quantity,
    }


class _BObj:
    """Attribute-style broker order object (mirrors KiteConnect response objects)."""

    def __init__(self, order_id, symbol="RELIANCE", status="OPEN", filled_quantity=0):
        self.order_id = order_id
        self.tradingsymbol = symbol
        self.symbol = symbol
        self.status = status
        self.filled_quantity = filled_quantity


# ---------------------------------------------------------------------------
# Tests for _check_discrepancies()
# ---------------------------------------------------------------------------

class TestCheckDiscrepanciesCleanRun(unittest.TestCase):

    def test_no_orders_returns_empty(self):
        result = recon._check_discrepancies([], [])
        self.assertEqual(result, [])

    def test_matching_open_orders_no_discrepancy(self):
        local = [_local(id_=1, broker_order_id="B001", status="OPEN")]
        broker = [_broker(order_id="B001", status="OPEN")]
        result = recon._check_discrepancies(local, broker)
        self.assertEqual(result, [])

    def test_both_terminal_no_discrepancy(self):
        """Both COMPLETE locally and at broker → no mismatch."""
        local = [_local(id_=1, broker_order_id="B001", status="COMPLETE")]
        broker = [_broker(order_id="B001", status="COMPLETE", filled_quantity=10)]
        result = recon._check_discrepancies(local, broker)
        self.assertEqual(result, [])

    def test_terminal_orders_absent_from_broker_no_discrepancy(self):
        """A locally CANCELLED order absent from broker should NOT be LOCAL_ONLY."""
        local = [_local(id_=1, broker_order_id="B999", status="CANCELLED")]
        broker = []
        result = recon._check_discrepancies(local, broker)
        self.assertEqual(result, [])

    def test_terminal_broker_order_absent_locally_no_discrepancy(self):
        """A CANCELLED broker order with no local counterpart is not BROKER_ONLY."""
        local = []
        broker = [_broker(order_id="B999", status="CANCELLED")]
        result = recon._check_discrepancies(local, broker)
        self.assertEqual(result, [])

    def test_multiple_matched_orders_no_discrepancy(self):
        local = [
            _local(id_=1, broker_order_id="B001", symbol="RELIANCE", status="COMPLETE"),
            _local(id_=2, broker_order_id="B002", symbol="TCS", status="OPEN"),
        ]
        broker = [
            _broker(order_id="B001", symbol="RELIANCE", status="COMPLETE", filled_quantity=10),
            _broker(order_id="B002", symbol="TCS", status="OPEN"),
        ]
        result = recon._check_discrepancies(local, broker)
        self.assertEqual(result, [])


class TestLocalOnly(unittest.TestCase):

    def test_local_open_order_missing_from_broker(self):
        local = [_local(id_=1, broker_order_id="B001", status="OPEN")]
        broker = []  # broker has nothing
        result = recon._check_discrepancies(local, broker)
        self.assertEqual(len(result), 1)
        d = result[0]
        self.assertEqual(d["discrepancy_type"], "LOCAL_ONLY")
        self.assertEqual(d["broker_order_id"], "B001")
        self.assertTrue(d["requires_manual_review"])

    def test_local_only_captures_symbol(self):
        local = [_local(id_=2, broker_order_id="B002", symbol="INFY", status="PENDING")]
        broker = []
        result = recon._check_discrepancies(local, broker)
        self.assertEqual(result[0]["trading_symbol"], "INFY")

    def test_local_terminal_not_flagged_as_local_only(self):
        for status in ("COMPLETE", "CANCELLED", "REJECTED"):
            with self.subTest(status=status):
                local = [_local(id_=1, broker_order_id="B001", status=status)]
                result = recon._check_discrepancies(local, [])
                types_ = [d["discrepancy_type"] for d in result]
                self.assertNotIn("LOCAL_ONLY", types_)


class TestBrokerOnly(unittest.TestCase):

    def test_broker_open_order_missing_locally(self):
        local = []
        broker = [_broker(order_id="B099", symbol="HDFC", status="OPEN")]
        result = recon._check_discrepancies(local, broker)
        self.assertEqual(len(result), 1)
        d = result[0]
        self.assertEqual(d["discrepancy_type"], "BROKER_ONLY")
        self.assertEqual(d["broker_order_id"], "B099")
        self.assertTrue(d["requires_manual_review"])

    def test_broker_only_captures_symbol_from_dict(self):
        broker = [_broker(order_id="B099", symbol="HDFC", status="OPEN")]
        result = recon._check_discrepancies([], broker)
        self.assertEqual(result[0]["trading_symbol"], "HDFC")

    def test_broker_only_captures_symbol_from_obj(self):
        broker = [_BObj(order_id="B099", symbol="HDFC", status="OPEN")]
        result = recon._check_discrepancies([], broker)
        self.assertEqual(result[0]["trading_symbol"], "HDFC")

    def test_broker_terminal_not_flagged_as_broker_only(self):
        for status in ("COMPLETE", "CANCELLED", "REJECTED"):
            with self.subTest(status=status):
                broker = [_broker(order_id="B001", status=status)]
                result = recon._check_discrepancies([], broker)
                types_ = [d["discrepancy_type"] for d in result]
                self.assertNotIn("BROKER_ONLY", types_)


class TestStateMismatch(unittest.TestCase):

    def test_local_terminal_broker_active(self):
        """Local says COMPLETE, broker says OPEN → STATE_MISMATCH."""
        local = [_local(id_=1, broker_order_id="B001", status="COMPLETE")]
        broker = [_broker(order_id="B001", status="OPEN")]
        result = recon._check_discrepancies(local, broker)
        d = next(x for x in result if x["discrepancy_type"] == "STATE_MISMATCH")
        self.assertEqual(d["local_value"], "COMPLETE")
        self.assertEqual(d["broker_value"], "OPEN")
        self.assertTrue(d["requires_manual_review"])

    def test_local_active_broker_terminal(self):
        """Local says OPEN, broker says CANCELLED → STATE_MISMATCH."""
        local = [_local(id_=2, broker_order_id="B002", status="OPEN")]
        broker = [_broker(order_id="B002", status="CANCELLED")]
        result = recon._check_discrepancies(local, broker)
        d = next(x for x in result if x["discrepancy_type"] == "STATE_MISMATCH")
        self.assertTrue(d["requires_manual_review"])
        self.assertEqual(d["broker_value"], "CANCELLED")

    def test_state_mismatch_with_obj_broker(self):
        """Broker order as attribute-style object still detected."""
        local = [_local(id_=3, broker_order_id="B003", status="COMPLETE")]
        broker = [_BObj(order_id="B003", status="OPEN")]
        result = recon._check_discrepancies(local, broker)
        types_ = [d["discrepancy_type"] for d in result]
        self.assertIn("STATE_MISMATCH", types_)

    def test_both_non_terminal_no_state_mismatch(self):
        local = [_local(id_=1, broker_order_id="B001", status="OPEN")]
        broker = [_broker(order_id="B001", status="PENDING")]
        result = recon._check_discrepancies(local, broker)
        types_ = [d["discrepancy_type"] for d in result]
        self.assertNotIn("STATE_MISMATCH", types_)


class TestFillMismatch(unittest.TestCase):

    def test_broker_complete_but_zero_filled(self):
        """Broker COMPLETE with filled_quantity=0 → FILL_MISMATCH."""
        local = [_local(id_=1, broker_order_id="B001", status="COMPLETE")]
        broker = [_broker(order_id="B001", status="COMPLETE", filled_quantity=0)]
        result = recon._check_discrepancies(local, broker)
        d = next(x for x in result if x["discrepancy_type"] == "FILL_MISMATCH")
        self.assertTrue(d["requires_manual_review"])
        self.assertEqual(d["broker_value"], "0")

    def test_broker_complete_with_filled_no_mismatch(self):
        """Broker COMPLETE with filled_quantity > 0 → no FILL_MISMATCH."""
        local = [_local(id_=1, broker_order_id="B001", status="COMPLETE")]
        broker = [_broker(order_id="B001", status="COMPLETE", filled_quantity=10)]
        result = recon._check_discrepancies(local, broker)
        types_ = [d["discrepancy_type"] for d in result]
        self.assertNotIn("FILL_MISMATCH", types_)

    def test_fill_mismatch_with_obj_broker(self):
        local = [_local(id_=1, broker_order_id="B001", status="COMPLETE")]
        broker = [_BObj(order_id="B001", status="COMPLETE", filled_quantity=0)]
        result = recon._check_discrepancies(local, broker)
        types_ = [d["discrepancy_type"] for d in result]
        self.assertIn("FILL_MISMATCH", types_)

    def test_non_complete_broker_no_fill_mismatch(self):
        local = [_local(id_=1, broker_order_id="B001", status="OPEN")]
        broker = [_broker(order_id="B001", status="OPEN", filled_quantity=0)]
        result = recon._check_discrepancies(local, broker)
        types_ = [d["discrepancy_type"] for d in result]
        self.assertNotIn("FILL_MISMATCH", types_)


class TestDuplicateOrder(unittest.TestCase):

    def test_two_local_rows_same_broker_id(self):
        local = [
            _local(id_=1, broker_order_id="B001", status="OPEN"),
            _local(id_=2, broker_order_id="B001", status="OPEN"),
        ]
        broker = [_broker(order_id="B001", status="OPEN")]
        result = recon._check_discrepancies(local, broker)
        d = next(x for x in result if x["discrepancy_type"] == "DUPLICATE_ORDER")
        self.assertEqual(d["broker_order_id"], "B001")
        self.assertEqual(d["local_value"], "2")
        # DUPLICATE_ORDER is flagged requires_manual_review
        self.assertTrue(d["requires_manual_review"])

    def test_three_local_rows_same_broker_id(self):
        local = [_local(id_=i, broker_order_id="B001") for i in range(1, 4)]
        broker = [_broker(order_id="B001")]
        result = recon._check_discrepancies(local, broker)
        d = next(x for x in result if x["discrepancy_type"] == "DUPLICATE_ORDER")
        self.assertEqual(d["local_value"], "3")

    def test_unique_broker_ids_no_duplicate(self):
        local = [
            _local(id_=1, broker_order_id="B001"),
            _local(id_=2, broker_order_id="B002"),
        ]
        broker = [
            _broker(order_id="B001"),
            _broker(order_id="B002"),
        ]
        result = recon._check_discrepancies(local, broker)
        types_ = [d["discrepancy_type"] for d in result]
        self.assertNotIn("DUPLICATE_ORDER", types_)


class TestRequiresManualReview(unittest.TestCase):
    """Verify requires_manual_review flag is set correctly for each type."""

    def _types_map(self, local, broker):
        """Return {discrepancy_type: requires_manual_review} from the result list."""
        result = recon._check_discrepancies(local, broker)
        return {d["discrepancy_type"]: d["requires_manual_review"] for d in result}

    def test_local_only_requires_review(self):
        local = [_local(broker_order_id="BX", status="OPEN")]
        m = self._types_map(local, [])
        self.assertTrue(m.get("LOCAL_ONLY"))

    def test_broker_only_requires_review(self):
        broker = [_broker(order_id="BX", status="OPEN")]
        m = self._types_map([], broker)
        self.assertTrue(m.get("BROKER_ONLY"))

    def test_state_mismatch_requires_review(self):
        local = [_local(broker_order_id="BX", status="COMPLETE")]
        broker = [_broker(order_id="BX", status="OPEN")]
        m = self._types_map(local, broker)
        self.assertTrue(m.get("STATE_MISMATCH"))

    def test_fill_mismatch_requires_review(self):
        local = [_local(broker_order_id="BX", status="COMPLETE")]
        broker = [_broker(order_id="BX", status="COMPLETE", filled_quantity=0)]
        m = self._types_map(local, broker)
        self.assertTrue(m.get("FILL_MISMATCH"))

    def test_duplicate_order_requires_review(self):
        local = [
            _local(id_=1, broker_order_id="BX"),
            _local(id_=2, broker_order_id="BX"),
        ]
        broker = [_broker(order_id="BX")]
        m = self._types_map(local, broker)
        self.assertTrue(m.get("DUPLICATE_ORDER"))


# ---------------------------------------------------------------------------
# Tests for the per-day KV guard in run_eod_reconciliation()
# ---------------------------------------------------------------------------

class TestKvGuard(unittest.TestCase):
    """Per-day guard: second call on the same day is skipped without force=True."""

    def setUp(self):
        # Clear the KV store before each test
        import sys
        store_mod = sys.modules["phase20_store"]
        store_mod._kv.clear()

    def _patch_today(self, date_str: str = "2024-01-15"):
        """Patch _today_ist() and _is_eod_window() so the guard logic runs."""
        return patch.multiple(
            recon,
            _today_ist=MagicMock(return_value=date_str),
            _is_eod_window=MagicMock(return_value=True),
        )

    def test_first_call_not_skipped(self):
        """First call on a fresh day should NOT return skipped=True."""
        with self._patch_today("2024-01-15"):
            result = recon.run_eod_reconciliation(trigger="manual", force=True)
        # force=True bypasses the guard; check we got a real run attempt
        self.assertFalse(result.get("skipped", False))

    def test_second_call_same_day_is_skipped(self):
        """Second call on the same calendar day should be skipped."""
        import sys
        store_mod = sys.modules["phase20_store"]
        # Simulate the KV already set for today
        store_mod._kv["eod_reconcil_date"] = "2024-01-15"

        with self._patch_today("2024-01-15"):
            result = recon.run_eod_reconciliation(trigger="eod", force=False)

        self.assertTrue(result.get("skipped"))
        self.assertIn("2024-01-15", result.get("reason", ""))

    def test_force_bypasses_kv_guard(self):
        """force=True should ignore the KV date and run anyway."""
        import sys
        store_mod = sys.modules["phase20_store"]
        store_mod._kv["eod_reconcil_date"] = "2024-01-15"

        with self._patch_today("2024-01-15"):
            result = recon.run_eod_reconciliation(trigger="manual", force=True)

        self.assertFalse(result.get("skipped", False))

    def test_different_day_not_skipped(self):
        """If KV holds yesterday's date, today's run proceeds."""
        import sys
        store_mod = sys.modules["phase20_store"]
        store_mod._kv["eod_reconcil_date"] = "2024-01-14"  # yesterday

        with self._patch_today("2024-01-15"):
            result = recon.run_eod_reconciliation(trigger="eod", force=False)

        self.assertFalse(result.get("skipped", False))

    def test_outside_eod_window_skipped(self):
        """If not in the EOD window and force=False, the run is skipped."""
        import sys
        store_mod = sys.modules["phase20_store"]
        store_mod._kv.clear()

        with patch.multiple(
            recon,
            _today_ist=MagicMock(return_value="2024-01-15"),
            _is_eod_window=MagicMock(return_value=False),
        ):
            result = recon.run_eod_reconciliation(trigger="eod", force=False)

        self.assertTrue(result.get("skipped"))
        self.assertIn("EOD window", result.get("reason", ""))


# ---------------------------------------------------------------------------
# Edge-case / integration-style tests
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_order_without_broker_order_id_skipped(self):
        """Local orders with no broker_order_id should not trigger LOCAL_ONLY."""
        local = [_local(id_=1, broker_order_id=None, status="OPEN")]
        local[0]["broker_order_id"] = None
        result = recon._check_discrepancies(local, [])
        types_ = [d["discrepancy_type"] for d in result]
        self.assertNotIn("LOCAL_ONLY", types_)

    def test_broker_order_id_type_coercion(self):
        """Integer broker_order_id from local DB matches string broker key."""
        local = [_local(id_=1, broker_order_id=12345, status="OPEN")]
        broker = [_broker(order_id="12345", status="OPEN")]
        result = recon._check_discrepancies(local, broker)
        self.assertEqual(result, [])

    def test_multiple_discrepancy_types_in_one_run(self):
        """A single comparison can surface multiple distinct discrepancy types."""
        local = [
            _local(id_=1, broker_order_id="B001", status="OPEN"),   # LOCAL_ONLY (B001 missing from broker)
            _local(id_=2, broker_order_id="B002", status="COMPLETE"), # STATE_MISMATCH (broker=OPEN)
            _local(id_=3, broker_order_id="B003", status="COMPLETE"), # FILL_MISMATCH
            _local(id_=4, broker_order_id="B004", status="OPEN"),   # duplicate
            _local(id_=5, broker_order_id="B004", status="OPEN"),   # duplicate
        ]
        broker = [
            # B001 absent → LOCAL_ONLY
            _broker(order_id="B002", status="OPEN"),                  # STATE_MISMATCH
            _broker(order_id="B003", status="COMPLETE", filled_quantity=0),  # FILL_MISMATCH
            _broker(order_id="B004", status="OPEN"),                  # triggers DUPLICATE
            _broker(order_id="B099", status="OPEN"),                  # BROKER_ONLY
        ]
        result = recon._check_discrepancies(local, broker)
        found = {d["discrepancy_type"] for d in result}
        self.assertIn("LOCAL_ONLY", found)
        self.assertIn("STATE_MISMATCH", found)
        self.assertIn("FILL_MISMATCH", found)
        self.assertIn("DUPLICATE_ORDER", found)
        self.assertIn("BROKER_ONLY", found)

    def test_all_five_types_all_require_manual_review(self):
        """Every discrepancy type in the combined run must require manual review."""
        local = [
            _local(id_=1, broker_order_id="B001", status="OPEN"),
            _local(id_=2, broker_order_id="B002", status="COMPLETE"),
            _local(id_=3, broker_order_id="B003", status="COMPLETE"),
            _local(id_=4, broker_order_id="B004", status="OPEN"),
            _local(id_=5, broker_order_id="B004", status="OPEN"),
        ]
        broker = [
            _broker(order_id="B002", status="OPEN"),
            _broker(order_id="B003", status="COMPLETE", filled_quantity=0),
            _broker(order_id="B004", status="OPEN"),
            _broker(order_id="B099", status="OPEN"),
        ]
        result = recon._check_discrepancies(local, broker)
        for d in result:
            with self.subTest(dtype=d["discrepancy_type"]):
                self.assertTrue(
                    d["requires_manual_review"],
                    f"{d['discrepancy_type']} should set requires_manual_review=True",
                )


if __name__ == "__main__":
    unittest.main()
