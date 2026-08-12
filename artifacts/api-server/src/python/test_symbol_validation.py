"""
Priority 3 (#26) — symbol validation tests.

Unit-level only: instrument master is stubbed, no network, no broker.
Run: python3 test_symbol_validation.py
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import symbol_validation as sv


FAKE_MASTER = {
    "RELIANCE": {"tradingsymbol": "RELIANCE", "name": "RELIANCE INDUSTRIES"},
    "TCS": {"tradingsymbol": "TCS", "name": "TATA CONSULTANCY SERVICES"},
    "M&M": {"tradingsymbol": "M&M", "name": "MAHINDRA & MAHINDRA"},
    "BAJAJ-AUTO": {"tradingsymbol": "BAJAJ-AUTO", "name": "BAJAJ AUTO"},
    "TMPV": {"tradingsymbol": "TMPV", "name": "TATA MOTORS PASSENGER VEHICLES"},
    "TMCV": {"tradingsymbol": "TMCV", "name": "TATA MOTORS COMMERCIAL VEHICLES"},
    "TATASTEEL": {"tradingsymbol": "TATASTEEL", "name": "TATA STEEL"},
}


class SymbolValidationTest(unittest.TestCase):
    def setUp(self):
        # Isolate diagnostics log + silence audit notifications
        self._tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._orig_log = sv.DIAG_LOG_FILE
        sv.DIAG_LOG_FILE = self._tmp.name
        os.unlink(self._tmp.name)
        self._patches = [
            mock.patch.object(sv, "_instrument_master", return_value=dict(FAKE_MASTER)),
        ]
        for p in self._patches:
            p.start()
        # keep audit path harmless
        sys.modules.setdefault("phase20_store", mock.MagicMock())

    def tearDown(self):
        for p in self._patches:
            p.stop()
        if os.path.exists(sv.DIAG_LOG_FILE):
            os.unlink(sv.DIAG_LOG_FILE)
        sv.DIAG_LOG_FILE = self._orig_log

    # ── normalization ────────────────────────────────────────────────
    def test_normalize_case_whitespace(self):
        self.assertEqual(sv.normalize("  reliance \n"), ("RELIANCE", None))

    def test_normalize_exchange_prefix(self):
        self.assertEqual(sv.normalize("NSE:TCS"), ("TCS", "NSE"))
        self.assertEqual(sv.normalize("bse:TCS"), ("TCS", "BSE"))

    def test_normalize_unicode_dash(self):
        self.assertEqual(sv.normalize("BAJAJ\u2013AUTO"), ("BAJAJ-AUTO", None))

    # ── acceptance ───────────────────────────────────────────────────
    def test_valid_symbol(self):
        r = sv.validate_symbol(" reliance ", context="test")
        self.assertTrue(r["valid"])
        self.assertEqual(r["symbol"], "RELIANCE")

    def test_valid_special_chars(self):
        for s in ("M&M", "BAJAJ-AUTO"):
            r = sv.validate_symbol(s, context="test")
            self.assertTrue(r["valid"], r)

    def test_nse_prefix_accepted(self):
        r = sv.validate_symbol("NSE:TCS", context="test")
        self.assertTrue(r["valid"])
        self.assertEqual(r["symbol"], "TCS")

    # ── rejections with clear reasons ────────────────────────────────
    def test_blank(self):
        for raw in ("", "   ", None):
            r = sv.validate_symbol(raw, context="test")
            self.assertFalse(r["valid"])
            self.assertIn("Blank", r["reason"])

    def test_malformed(self):
        r = sv.validate_symbol("REL!ANCE", context="test")
        self.assertFalse(r["valid"])
        self.assertIn("Malformed", r["reason"])

    def test_unsupported_exchange(self):
        r = sv.validate_symbol("BSE:RELIANCE", context="test")
        self.assertFalse(r["valid"])
        self.assertIn("Unsupported exchange", r["reason"])

    def test_duplicate(self):
        r = sv.validate_symbol("tcs", context="test", existing=["TCS", "INFY"])
        self.assertFalse(r["valid"])
        self.assertIn("Duplicate", r["reason"])

    def test_delisted_not_in_master(self):
        r = sv.validate_symbol("ZOMBIECO", context="test")
        self.assertFalse(r["valid"])
        self.assertIn("not an active NSE instrument", r["reason"])

    def test_outside_universe(self):
        # In master but not in NIFTY_50? All fake master syms are in NIFTY_50;
        # simulate by extending master with a non-universe symbol.
        master = dict(FAKE_MASTER)
        master["IRCTC"] = {"tradingsymbol": "IRCTC", "name": "INDIAN RAILWAY CATERING"}
        with mock.patch.object(sv, "_instrument_master", return_value=master):
            r = sv.validate_symbol("IRCTC", context="test")
        self.assertFalse(r["valid"])
        self.assertIn("universe", r["reason"])

    def test_universe_not_required(self):
        master = dict(FAKE_MASTER)
        master["IRCTC"] = {"tradingsymbol": "IRCTC", "name": "X"}
        with mock.patch.object(sv, "_instrument_master", return_value=master):
            r = sv.validate_symbol("IRCTC", context="test", require_universe=False)
        self.assertTrue(r["valid"])

    def test_company_name_suggestions(self):
        r = sv.validate_symbol("TATA CONSULTANCY SERVICES", context="test")
        self.assertFalse(r["valid"])
        self.assertTrue(r.get("suggestions"))
        self.assertIn("TCS", [c["symbol"] for c in r["suggestions"]])

    def test_master_unavailable_falls_back_to_universe(self):
        with mock.patch.object(sv, "_instrument_master", return_value=None):
            self.assertTrue(sv.validate_symbol("RELIANCE", context="test")["valid"])
            self.assertFalse(sv.validate_symbol("ZOMBIECO", context="test")["valid"])

    # ── universe filtering (scan resilience) ─────────────────────────
    def test_validate_universe_filters_and_never_raises(self):
        out = sv.validate_universe(
            ["RELIANCE", "", "REL!ANCE", "ZOMBIECO", "tcs", "TCS", None, 42],
            context="scan")
        self.assertEqual(out["valid"], ["RELIANCE", "TCS"])
        self.assertGreaterEqual(len(out["rejected"]), 4)
        for rej in out["rejected"]:
            self.assertTrue(rej["reason"])

    def test_validate_universe_empty_input(self):
        out = sv.validate_universe([], context="scan")
        self.assertEqual(out["valid"], [])
        self.assertEqual(out["rejected"], [])

    # ── diagnostics tracking ─────────────────────────────────────────
    def test_rejections_tracked_in_log(self):
        sv.validate_symbol("REL!ANCE", context="test")
        sv.validate_symbol("RELIANCE", context="test")
        log = sv.get_validation_log()
        self.assertGreaterEqual(len(log), 2)
        rejected = [e for e in log if not e["accepted"]]
        self.assertTrue(rejected)
        self.assertIn("Malformed", rejected[0]["reason"])

    # ── integration: watchlist add path ──────────────────────────────
    def test_watchlist_add_rejects_junk(self):
        import main
        with mock.patch.object(main, "_load_watchlist", return_value=["TCS"]), \
             mock.patch.object(main, "_save_watchlist") as save:
            r = main.cmd_watchlist_add("JUNK!!!")
            self.assertIn("error", r)
            save.assert_not_called()
            r2 = main.cmd_watchlist_add("TCS")
            self.assertIn("error", r2)  # duplicate
            r3 = main.cmd_watchlist_add(" reliance ")
            self.assertEqual(r3["watchlist"], ["TCS", "RELIANCE"])
            save.assert_called_once()

    # ── Priority 9 (#34): company-name / alias search ────────────────
    def test_search_by_exact_ticker(self):
        r = sv.search_symbols("RELIANCE")
        self.assertTrue(r["results"])
        self.assertEqual(r["results"][0]["symbol"], "RELIANCE")
        self.assertEqual(r["results"][0]["exchange"], "NSE")
        self.assertEqual(r["results"][0]["type"], "EQ")

    def test_search_by_company_name(self):
        r = sv.search_symbols("INFOSYS")
        self.assertIn("INFY", [x["symbol"] for x in r["results"]])

    def test_search_by_alias(self):
        r = sv.search_symbols("airtel")
        self.assertEqual(r["results"][0]["symbol"], "BHARTIARTL")
        self.assertFalse(r["ambiguous"])

    def test_search_ambiguous_multiple_matches(self):
        r = sv.search_symbols("TATA")
        syms = [x["symbol"] for x in r["results"]]
        self.assertGreater(len(syms), 1)
        self.assertTrue(r["ambiguous"])
        # TATAMOTORS was deprecated (demerger); TMPV / TMCV are the successors.
        # "TATA" search should still find Tata-family tickers in the universe.
        tata_family = {"TMPV", "TMCV", "TATASTEEL", "TATACONSUM", "TCS"}
        self.assertTrue(tata_family & set(syms),
                        f"Expected at least one Tata-family symbol in {syms}")

    def test_search_only_approved_universe(self):
        import config
        for q in ("TATA", "BANK", "A", "RELIANCE INDUSTRIES"):
            for item in sv.search_symbols(q)["results"]:
                self.assertIn(item["symbol"], config.NIFTY_50)

    def test_search_blank_and_garbage_never_raise(self):
        self.assertEqual(sv.search_symbols("")["results"], [])
        self.assertEqual(sv.search_symbols(None)["results"], [])
        self.assertEqual(sv.search_symbols("ZZZZNOTREAL")["results"], [])

    # ── integration: paper buy path ──────────────────────────────────
    def test_buy_rejects_junk_symbol(self):
        import paper_trader
        ok, msg = paper_trader.execute_buy("ZOMBIECO", 1, 100.0, "test")
        self.assertFalse(ok)
        self.assertIn("Symbol rejected", msg)


if __name__ == "__main__":
    res = unittest.main(exit=False, verbosity=2).result
    total = res.testsRun
    failed = len(res.failures) + len(res.errors)
    print(f"\n{total - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
