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


# ---------------------------------------------------------------------------
# Tests for check_reconciliation_probe()
# ---------------------------------------------------------------------------

class TestCheckReconciliationProbe(unittest.TestCase):
    """Verify the missed-reconciliation probe fires and stays silent correctly."""

    def setUp(self):
        # Clear KV store before each test
        import sys
        store_mod = sys.modules["phase20_store"]
        store_mod._kv.clear()

        # Stub alert_queue so email calls don't crash
        aq_mod = types.ModuleType("alert_queue")
        _queued: list = []

        def enqueue_email_alert(kind, title, body="", severity="INFO"):
            _queued.append({"kind": kind, "title": title})
            return {"ok": True}

        def process_email_queue():
            return {"delivered": 0, "failed": 0, "retried": 0}

        aq_mod.enqueue_email_alert = enqueue_email_alert
        aq_mod.process_email_queue = process_email_queue
        aq_mod._queued = _queued
        sys.modules["alert_queue"] = aq_mod

    # -- NOT_DUE: weekend ---------------------------------------------------

    def _patch_ist(self, weekday: int, hour: int, today: str = "2024-01-15"):
        """Patch datetime.now inside eod_reconciliation to return a controlled IST-like value."""
        from unittest.mock import patch, MagicMock
        fake_now = MagicMock()
        fake_now.weekday.return_value = weekday
        fake_now.hour = hour

        class _FakeZI:
            pass

        def _fake_now_ist(tz):
            return fake_now

        # Patch both ZoneInfo usage AND _today_ist
        return patch.multiple(
            recon,
            _today_ist=MagicMock(return_value=today),
            _kv_get=MagicMock(side_effect=lambda key: sys.modules["phase20_store"]._kv.get(key)),
            _kv_set=MagicMock(side_effect=lambda key, val: sys.modules["phase20_store"]._kv.update({key: val})),
            _add_notification=MagicMock(),
        )

    def test_weekend_returns_not_due(self):
        """Saturday (weekday=5) → NOT_DUE regardless of hour."""
        import sys
        from unittest.mock import patch, MagicMock
        fake_ist = MagicMock()
        fake_ist.weekday.return_value = 5   # Saturday
        fake_ist.hour = 23

        with patch("eod_reconciliation.datetime") as mock_dt, \
             patch.multiple(recon,
                            _today_ist=MagicMock(return_value="2024-01-20"),
                            _kv_get=MagicMock(return_value=None),
                            _add_notification=MagicMock()):
            mock_dt.now.return_value = fake_ist
            mock_dt.now.side_effect = None
            from zoneinfo import ZoneInfo
            import datetime as _real_dt

            # Directly set the weekday/hour on the module's datetime mock
            # Use a simpler approach: patch just the function that checks IST
            pass

        # Simpler: test by patching the probe function's IST datetime call
        with patch("eod_reconciliation.datetime") as mock_dt, \
             patch.object(recon, "_today_ist", return_value="2024-01-20"), \
             patch.object(recon, "_kv_get", return_value=None), \
             patch.object(recon, "_add_notification"):
            fake = MagicMock()
            fake.weekday.return_value = 5
            fake.hour = 23
            mock_dt.now.return_value = fake
            result = recon.check_reconciliation_probe()

        self.assertEqual(result["status"], "NOT_DUE")
        self.assertIn("Weekend", result["reason"])

    def test_before_2300_returns_not_due(self):
        """Weekday before 23:00 IST → NOT_DUE."""
        from unittest.mock import patch, MagicMock
        with patch("eod_reconciliation.datetime") as mock_dt, \
             patch.object(recon, "_today_ist", return_value="2024-01-15"), \
             patch.object(recon, "_kv_get", return_value=None), \
             patch.object(recon, "_add_notification"):
            fake = MagicMock()
            fake.weekday.return_value = 0   # Monday
            fake.hour = 22                  # 22:xx — not yet 23:00
            mock_dt.now.return_value = fake
            result = recon.check_reconciliation_probe()

        self.assertEqual(result["status"], "NOT_DUE")
        self.assertIn("23:00", result["reason"])

    def test_ran_today_returns_ok(self):
        """Weekday after 23:00, KV guard set for today → OK."""
        import sys
        store_mod = sys.modules["phase20_store"]
        store_mod._kv["eod_reconcil_date"] = "2024-01-15"

        from unittest.mock import patch, MagicMock
        with patch("eod_reconciliation.datetime") as mock_dt, \
             patch.object(recon, "_today_ist", return_value="2024-01-15"), \
             patch.object(recon, "_kv_get",
                          side_effect=lambda k: store_mod._kv.get(k)), \
             patch.object(recon, "_add_notification"):
            fake = MagicMock()
            fake.weekday.return_value = 0   # Monday
            fake.hour = 23
            mock_dt.now.return_value = fake
            result = recon.check_reconciliation_probe()

        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["today"], "2024-01-15")

    def test_missed_fires_notification(self):
        """Weekday after 23:00, KV guard NOT set → MISSED + notification fired."""
        import sys
        store_mod = sys.modules["phase20_store"]
        store_mod._kv.clear()  # No reconcil_date set

        from unittest.mock import patch, MagicMock
        mock_notify = MagicMock()
        with patch("eod_reconciliation.datetime") as mock_dt, \
             patch.object(recon, "_today_ist", return_value="2024-01-15"), \
             patch.object(recon, "_kv_get", return_value=None), \
             patch.object(recon, "_add_notification", mock_notify):
            fake = MagicMock()
            fake.weekday.return_value = 1   # Tuesday
            fake.hour = 23
            mock_dt.now.return_value = fake
            result = recon.check_reconciliation_probe()

        self.assertEqual(result["status"], "MISSED")
        self.assertTrue(result["notification_fired"])
        self.assertIn("2024-01-15", result["reason"])
        mock_notify.assert_called_once()
        call_args = mock_notify.call_args
        self.assertEqual(call_args[0][0], "RECONCILIATION_MISSED")  # kind
        self.assertEqual(call_args[1]["severity"], "ERROR")

    def test_missed_includes_email_result(self):
        """MISSED result includes the email delivery attempt result."""
        from unittest.mock import patch, MagicMock
        with patch("eod_reconciliation.datetime") as mock_dt, \
             patch.object(recon, "_today_ist", return_value="2024-01-15"), \
             patch.object(recon, "_kv_get", return_value=None), \
             patch.object(recon, "_add_notification"):
            fake = MagicMock()
            fake.weekday.return_value = 2   # Wednesday
            fake.hour = 23
            mock_dt.now.return_value = fake
            result = recon.check_reconciliation_probe()

        self.assertEqual(result["status"], "MISSED")
        self.assertIn("email", result)
        # email field must be a dict
        self.assertIsInstance(result["email"], dict)

    def test_ok_does_not_fire_notification(self):
        """When reconciliation ran today, no notification is fired."""
        import sys
        store_mod = sys.modules["phase20_store"]
        store_mod._kv["eod_reconcil_date"] = "2024-01-15"

        from unittest.mock import patch, MagicMock
        mock_notify = MagicMock()
        with patch("eod_reconciliation.datetime") as mock_dt, \
             patch.object(recon, "_today_ist", return_value="2024-01-15"), \
             patch.object(recon, "_kv_get",
                          side_effect=lambda k: store_mod._kv.get(k)), \
             patch.object(recon, "_add_notification", mock_notify):
            fake = MagicMock()
            fake.weekday.return_value = 3   # Thursday
            fake.hour = 23
            mock_dt.now.return_value = fake
            result = recon.check_reconciliation_probe()

        self.assertEqual(result["status"], "OK")
        mock_notify.assert_not_called()

    def test_yesterday_kv_is_treated_as_missed(self):
        """KV guard holding yesterday's date is equivalent to a missed run."""
        import sys
        store_mod = sys.modules["phase20_store"]
        store_mod._kv["eod_reconcil_date"] = "2024-01-14"  # yesterday

        from unittest.mock import patch, MagicMock
        with patch("eod_reconciliation.datetime") as mock_dt, \
             patch.object(recon, "_today_ist", return_value="2024-01-15"), \
             patch.object(recon, "_kv_get",
                          side_effect=lambda k: store_mod._kv.get(k)), \
             patch.object(recon, "_add_notification"):
            fake = MagicMock()
            fake.weekday.return_value = 0   # Monday
            fake.hour = 23
            mock_dt.now.return_value = fake
            result = recon.check_reconciliation_probe()

        self.assertEqual(result["status"], "MISSED")
        self.assertEqual(result["last_ran_date"], "2024-01-14")

    def test_sunday_returns_not_due(self):
        """Sunday (weekday=6) → NOT_DUE."""
        from unittest.mock import patch, MagicMock
        with patch("eod_reconciliation.datetime") as mock_dt, \
             patch.object(recon, "_today_ist", return_value="2024-01-21"), \
             patch.object(recon, "_kv_get", return_value=None), \
             patch.object(recon, "_add_notification"):
            fake = MagicMock()
            fake.weekday.return_value = 6   # Sunday
            fake.hour = 23
            mock_dt.now.return_value = fake
            result = recon.check_reconciliation_probe()

        self.assertEqual(result["status"], "NOT_DUE")


# ---------------------------------------------------------------------------
# Tests for the resolve → reopen → resolve cycle
# ---------------------------------------------------------------------------

class _FakeRow:
    """Minimal discrepancy row stored in memory, mimicking the DB columns."""

    def __init__(self, id_: int):
        self.id = id_
        self.resolved: bool = False
        self.resolved_at = None   # datetime | None
        self.resolved_note = None  # str | None


class _FakeCursor:
    """Thin cursor stub that executes UPDATE … RETURNING against a _FakeRow."""

    def __init__(self, row: _FakeRow):
        self._row = row
        self._last_returning = None   # (id, resolved_at) | (id,) | None

    # context manager protocol
    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def execute(self, sql: str, params: tuple = ()):
        sql_stripped = " ".join(sql.split()).upper()

        if "SET RESOLVED = TRUE" in sql_stripped:
            # resolve_discrepancy: UPDATE … SET resolved=TRUE, resolved_at=NOW(), resolved_note=%s
            note, disc_id = params
            if disc_id != self._row.id:
                self._last_returning = None
                return
            import datetime as _dt
            self._row.resolved = True
            self._row.resolved_at = _dt.datetime.now(_dt.timezone.utc)
            self._row.resolved_note = note
            self._last_returning = (self._row.id, self._row.resolved_at)

        elif "SET RESOLVED = FALSE" in sql_stripped:
            # reopen_discrepancy: UPDATE … SET resolved=FALSE, resolved_at=NULL, resolved_note=NULL
            (disc_id,) = params
            if disc_id != self._row.id:
                self._last_returning = None
                return
            self._row.resolved = False
            self._row.resolved_at = None
            self._row.resolved_note = None
            self._last_returning = (self._row.id,)

        else:
            # _ensure_schema DDL statements — ignore silently
            self._last_returning = None

    def fetchone(self):
        return self._last_returning

    @property
    def description(self):
        return None


class _FakeConn:
    """Fake DB connection backed by a single in-memory _FakeRow."""

    def __init__(self, row: _FakeRow):
        self._row = row
        self._cursor = _FakeCursor(row)
        self.committed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def close(self):
        pass


class TestResolveReopenCycle(unittest.TestCase):
    """
    End-to-end unit test for the full resolve → reopen → resolve transition.

    Covers:
    - Correct DB state (resolved flag, resolved_at, resolved_note) after each step
    - Successful API-level responses (success=True) at each step
    - Latest resolution note is preserved, not the first one
    - No leftover resolved_at / resolved_note after reopen
    """

    def _make_conn(self, disc_id: int = 99) -> tuple:
        """Return (row, conn) for a fresh unresolved discrepancy."""
        row = _FakeRow(disc_id)
        conn = _FakeConn(row)
        return row, conn

    def _patch_connect(self, conn: _FakeConn):
        """Return a context-manager patch that wires _connect() → conn."""
        import sys
        sss = sys.modules["scan_state_store"]
        return patch.object(sss, "_connect", return_value=conn)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _resolve(self, conn: _FakeConn, disc_id: int, note: str | None = None):
        with self._patch_connect(conn):
            return recon.resolve_discrepancy(disc_id, note=note)

    def _reopen(self, conn: _FakeConn, disc_id: int):
        with self._patch_connect(conn):
            return recon.reopen_discrepancy(disc_id)

    # ── tests ─────────────────────────────────────────────────────────────────

    def test_first_resolve_sets_correct_db_state(self):
        """After resolve, resolved=True and resolved_note matches the supplied note."""
        row, conn = self._make_conn(disc_id=1)
        result = self._resolve(conn, disc_id=1, note="Initial fix")

        self.assertTrue(result.get("success"), f"Expected success=True, got: {result}")
        self.assertEqual(result.get("resolved_id"), 1)
        self.assertIn("resolved_at", result)

        # DB state
        self.assertTrue(row.resolved)
        self.assertIsNotNone(row.resolved_at)
        self.assertEqual(row.resolved_note, "Initial fix")

    def test_reopen_clears_resolved_fields(self):
        """After reopen, resolved=False and resolved_at/resolved_note are both NULL."""
        row, conn = self._make_conn(disc_id=2)

        # First: resolve it
        r1 = self._resolve(conn, disc_id=2, note="First note")
        self.assertTrue(r1.get("success"), r1)

        # Then: reopen
        r2 = self._reopen(conn, disc_id=2)
        self.assertTrue(r2.get("success"), f"Expected reopen success=True, got: {r2}")
        self.assertEqual(r2.get("reopened_id"), 2)

        # DB state must be fully cleared
        self.assertFalse(row.resolved)
        self.assertIsNone(row.resolved_at)
        self.assertIsNone(row.resolved_note)

    def test_second_resolve_after_reopen_succeeds(self):
        """resolve → reopen → resolve must complete without errors."""
        row, conn = self._make_conn(disc_id=3)

        r1 = self._resolve(conn, disc_id=3, note="First resolution")
        self.assertTrue(r1.get("success"), r1)

        r2 = self._reopen(conn, disc_id=3)
        self.assertTrue(r2.get("success"), r2)

        r3 = self._resolve(conn, disc_id=3, note="Second resolution")
        self.assertTrue(r3.get("success"), f"Second resolve failed: {r3}")

    def test_second_resolve_stores_latest_note_not_first(self):
        """After resolve → reopen → resolve, the note reflects the second resolution."""
        row, conn = self._make_conn(disc_id=4)

        self._resolve(conn, disc_id=4, note="Original operator note")
        self._reopen(conn, disc_id=4)
        self._resolve(conn, disc_id=4, note="Updated operator note")

        self.assertTrue(row.resolved)
        self.assertEqual(
            row.resolved_note,
            "Updated operator note",
            "resolved_note must reflect the latest resolution, not the first",
        )

    def test_second_resolve_updates_resolved_at(self):
        """resolved_at from the second resolution must be ≥ the first."""
        import time
        row, conn = self._make_conn(disc_id=5)

        self._resolve(conn, disc_id=5, note="first")
        first_resolved_at = row.resolved_at

        # Small sleep so the two timestamps are distinguishable
        time.sleep(0.01)

        self._reopen(conn, disc_id=5)
        self._resolve(conn, disc_id=5, note="second")
        second_resolved_at = row.resolved_at

        self.assertIsNotNone(second_resolved_at)
        self.assertGreaterEqual(
            second_resolved_at,
            first_resolved_at,
            "resolved_at must advance on each new resolution",
        )

    def test_full_cycle_db_state_at_each_step(self):
        """
        Comprehensive state assertion after every transition in the cycle.

        Step 1: resolve    → resolved=T, note="note1"
        Step 2: reopen     → resolved=F, note=None, resolved_at=None
        Step 3: resolve    → resolved=T, note="note2"
        """
        row, conn = self._make_conn(disc_id=6)

        # -- Step 1: resolve --------------------------------------------------
        r1 = self._resolve(conn, disc_id=6, note="note1")
        self.assertTrue(r1.get("success"), f"Step 1 failed: {r1}")
        self.assertTrue(row.resolved, "Step 1: resolved must be True")
        self.assertIsNotNone(row.resolved_at, "Step 1: resolved_at must be set")
        self.assertEqual(row.resolved_note, "note1", "Step 1: note must be 'note1'")
        after_step1_resolved_at = row.resolved_at

        # -- Step 2: reopen ---------------------------------------------------
        r2 = self._reopen(conn, disc_id=6)
        self.assertTrue(r2.get("success"), f"Step 2 failed: {r2}")
        self.assertFalse(row.resolved, "Step 2: resolved must be False after reopen")
        self.assertIsNone(row.resolved_at, "Step 2: resolved_at must be NULL after reopen")
        self.assertIsNone(row.resolved_note, "Step 2: resolved_note must be NULL after reopen")

        # -- Step 3: resolve again --------------------------------------------
        r3 = self._resolve(conn, disc_id=6, note="note2")
        self.assertTrue(r3.get("success"), f"Step 3 failed: {r3}")
        self.assertIn("resolved_at", r3, "Step 3: response must include resolved_at")
        self.assertTrue(row.resolved, "Step 3: resolved must be True again")
        self.assertIsNotNone(row.resolved_at, "Step 3: resolved_at must be set again")
        self.assertEqual(row.resolved_note, "note2", "Step 3: note must be 'note2', not 'note1'")

    def test_resolve_without_note_leaves_note_null(self):
        """Resolving without a note stores NULL, not an empty string."""
        row, conn = self._make_conn(disc_id=7)

        self._resolve(conn, disc_id=7, note="initial note")
        self._reopen(conn, disc_id=7)
        self._resolve(conn, disc_id=7, note=None)  # no note this time

        self.assertTrue(row.resolved)
        self.assertIsNone(row.resolved_note, "resolved_note must be NULL when no note supplied")

    def test_reopen_of_already_open_discrepancy_returns_success(self):
        """Reopening a discrepancy that was never resolved should still succeed (idempotent)."""
        row, conn = self._make_conn(disc_id=8)
        # row is unresolved from the start

        result = self._reopen(conn, disc_id=8)
        self.assertTrue(result.get("success"), f"Unexpected failure: {result}")
        self.assertFalse(row.resolved)
        self.assertIsNone(row.resolved_at)

    def test_wrong_id_returns_failure(self):
        """resolve_discrepancy with a non-matching ID returns success=False."""
        row, conn = self._make_conn(disc_id=10)

        result = self._resolve(conn, disc_id=999, note="wrong")
        self.assertFalse(
            result.get("success"),
            "Resolving a non-existent ID must return success=False",
        )

    def test_reopen_wrong_id_returns_failure(self):
        """reopen_discrepancy with a non-matching ID returns success=False."""
        row, conn = self._make_conn(disc_id=10)

        result = self._reopen(conn, disc_id=888)
        self.assertFalse(
            result.get("success"),
            "Reopening a non-existent ID must return success=False",
        )


if __name__ == "__main__":
    unittest.main()
