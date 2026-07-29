"""
test_paper_trading_validation.py — Phase 6.1
Tests: zero trades, single trade, multiple trades, corrupted record detection,
duplicate detection, export, dashboard endpoints, feature flag, restart persistence.
"""
import sys, os, json, unittest
from unittest.mock import patch, MagicMock
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Sample data helpers
# ---------------------------------------------------------------------------

def _make_buy(symbol="RELIANCE", price=2500.0, qty=10, ts="2026-07-29T09:15:00+05:30",
              strategy="Momentum", regime="BULLISH", sector="Energy", confidence=0.78,
              ai_rec="BUY", signal_status="VALID", risk_score=0.3):
    return {
        "id": f"buy_{symbol}_{ts}",
        "symbol": symbol,
        "action": "BUY",
        "quantity": qty,
        "price": price,
        "total": price * qty,
        "timestamp": ts,
        "reason": "Signal triggered",
        "metadata": {
            "strategy": strategy,
            "market_regime": regime,
            "sector": sector,
            "ai_confidence": confidence,
            "ai_recommendation": ai_rec,
            "signal_validation_status": signal_status,
            "risk_score": risk_score,
            "portfolio_value_at_entry": 500000.0,
        },
    }


def _make_sell(symbol="RELIANCE", price=2600.0, qty=10, ts="2026-07-29T14:30:00+05:30",
               reason="Target", eq_score=88.0):
    return {
        "id": f"sell_{symbol}_{ts}",
        "symbol": symbol,
        "action": "SELL",
        "quantity": qty,
        "price": price,
        "total": price * qty,
        "timestamp": ts,
        "reason": reason,
        "metadata": {"execution_quality_score": eq_score},
    }


def _patch_trades(trades):
    return patch(
        "paper_trading_validation.validation_collector.portfolio_store",
        load_trades=MagicMock(return_value=trades),
    )


def _patch_load_trades(trades):
    """Patch the import inside validation_collector."""
    mock_module = MagicMock()
    mock_module.load_trades.return_value = trades
    return patch.dict("sys.modules", {"portfolio_store": mock_module})


def _patch_external():
    """Silence all external module calls that may not be installed."""
    patches = [
        patch("paper_trading_validation.validation_collector._get_exec_score_snapshot", return_value=85.0),
        patch("paper_trading_validation.validation_collector._get_executive_snapshot", return_value=72.0),
        patch("paper_trading_validation.validation_collector._get_portfolio_value", return_value=510000.0),
        patch("paper_trading_validation.validation_collector.collect_session_metadata",
              return_value=_make_session()),
    ]
    return patches


def _make_session():
    from paper_trading_validation.validation_models import SessionMetadata
    return SessionMetadata(
        trading_date=date.today().isoformat(),
        session_start="09:15",
        session_end="15:30",
        market_status="OPEN",
        pre_open_summary="Bullish gap-up",
        market_breadth="Advancing",
        nifty=24500.0,
        bank_nifty=52000.0,
        india_vix=13.5,
        leading_sector="Banking",
        top_gap="HDFC +2.1%",
    )


# ---------------------------------------------------------------------------
# TestFeatureFlag
# ---------------------------------------------------------------------------

class TestFeatureFlag(unittest.TestCase):

    def _call_all(self):
        from paper_trading_validation.shared_services import (
            get_session, get_history, get_quality, get_statistics, get_validation_snapshot,
        )
        return [get_session(), get_history(), get_quality(), get_statistics(), get_validation_snapshot()]

    def test_all_disabled_when_flag_off(self):
        with patch.dict(os.environ, {"PAPER_VALIDATION_ENABLED": "false"}):
            for result in self._call_all():
                # get_validation_snapshot returns zeros, not DISABLED
                if "status" in result:
                    self.assertEqual(result["status"], "DISABLED")

    def test_session_disabled(self):
        with patch.dict(os.environ, {"PAPER_VALIDATION_ENABLED": "false"}):
            from paper_trading_validation.shared_services import get_session
            r = get_session()
            self.assertEqual(r["status"], "DISABLED")

    def test_history_disabled(self):
        with patch.dict(os.environ, {"PAPER_VALIDATION_ENABLED": "false"}):
            from paper_trading_validation.shared_services import get_history
            r = get_history()
            self.assertEqual(r["status"], "DISABLED")

    def test_quality_disabled(self):
        with patch.dict(os.environ, {"PAPER_VALIDATION_ENABLED": "false"}):
            from paper_trading_validation.shared_services import get_quality
            r = get_quality()
            self.assertEqual(r["status"], "DISABLED")

    def test_statistics_disabled(self):
        with patch.dict(os.environ, {"PAPER_VALIDATION_ENABLED": "false"}):
            from paper_trading_validation.shared_services import get_statistics
            r = get_statistics()
            self.assertEqual(r["status"], "DISABLED")


# ---------------------------------------------------------------------------
# TestZeroTrades
# ---------------------------------------------------------------------------

class TestZeroTrades(unittest.TestCase):

    def setUp(self):
        os.environ["PAPER_VALIDATION_ENABLED"] = "true"
        self._mods = [
            patch("paper_trading_validation.validation_collector._get_exec_score_snapshot", return_value=None),
            patch("paper_trading_validation.validation_collector._get_executive_snapshot", return_value=None),
            patch("paper_trading_validation.validation_collector._get_portfolio_value", return_value=None),
        ]
        for m in self._mods:
            m.start()

    def tearDown(self):
        for m in self._mods:
            m.stop()

    def test_statistics_zero_trades(self):
        with _patch_load_trades([]):
            from paper_trading_validation.shared_services import get_statistics
            r = get_statistics()
        self.assertEqual(r["status"], "ENABLED")
        self.assertEqual(r["statistics"]["total_trades"], 0)

    def test_quality_zero_trades(self):
        with _patch_load_trades([]):
            from paper_trading_validation.shared_services import get_quality
            r = get_quality()
        self.assertEqual(r["status"], "ENABLED")
        self.assertEqual(r["quality"]["total_records"], 0)
        self.assertEqual(r["quality"]["verdict"], "CLEAN")

    def test_history_zero_trades(self):
        with _patch_load_trades([]):
            from paper_trading_validation.shared_services import get_history
            r = get_history()
        self.assertEqual(r["status"], "ENABLED")
        self.assertEqual(r["total_completed_trades"], 0)
        self.assertEqual(r["history"]["daily"], [])

    def test_session_zero_trades(self):
        session = _make_session()
        with _patch_load_trades([]):
            with patch("paper_trading_validation.validation_collector.collect_session_metadata", return_value=session):
                from paper_trading_validation.shared_services import get_session
                r = get_session()
        self.assertEqual(r["status"], "ENABLED")
        self.assertEqual(r["trade_count_today"], 0)


# ---------------------------------------------------------------------------
# TestSingleTrade
# ---------------------------------------------------------------------------

class TestSingleTrade(unittest.TestCase):

    def setUp(self):
        os.environ["PAPER_VALIDATION_ENABLED"] = "true"
        self.buy = _make_buy()
        self.sell = _make_sell()
        self._mods = _patch_external()
        for m in self._mods:
            m.start()

    def tearDown(self):
        for m in self._mods:
            m.stop()

    def test_single_trade_collected(self):
        with _patch_load_trades([self.buy, self.sell]):
            from paper_trading_validation.validation_collector import collect_all_trade_records
            records = collect_all_trade_records()
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec.symbol, "RELIANCE")
        self.assertEqual(rec.entry_price, 2500.0)
        self.assertEqual(rec.exit_price, 2600.0)
        self.assertEqual(rec.quantity, 10)
        self.assertAlmostEqual(rec.pnl, 1000.0, places=1)

    def test_holding_time_computed(self):
        with _patch_load_trades([self.buy, self.sell]):
            from paper_trading_validation.validation_collector import collect_all_trade_records
            records = collect_all_trade_records()
        rec = records[0]
        # 09:15 → 14:30 = 315 minutes
        self.assertGreater(rec.holding_time_minutes, 300)
        self.assertLess(rec.holding_time_minutes, 330)

    def test_metadata_enriched(self):
        with _patch_load_trades([self.buy, self.sell]):
            from paper_trading_validation.validation_collector import collect_all_trade_records
            records = collect_all_trade_records()
        rec = records[0]
        self.assertEqual(rec.strategy, "Momentum")
        self.assertEqual(rec.market_regime, "BULLISH")
        self.assertEqual(rec.sector, "Energy")
        self.assertAlmostEqual(rec.ai_confidence, 0.78)
        self.assertEqual(rec.ai_recommendation, "BUY")
        self.assertEqual(rec.execution_quality_score, 88.0)
        self.assertEqual(rec.exit_reason, "Target")

    def test_statistics_single_trade_win(self):
        with _patch_load_trades([self.buy, self.sell]):
            from paper_trading_validation.shared_services import get_statistics
            r = get_statistics()
        s = r["statistics"]
        self.assertEqual(s["total_trades"], 1)
        self.assertEqual(s["winning_trades"], 1)
        self.assertEqual(s["win_rate"], 1.0)
        self.assertGreater(s["net_pnl"], 0)


# ---------------------------------------------------------------------------
# TestMultipleTrades
# ---------------------------------------------------------------------------

class TestMultipleTrades(unittest.TestCase):

    def setUp(self):
        os.environ["PAPER_VALIDATION_ENABLED"] = "true"
        self.trades = [
            _make_buy("RELIANCE", 2500, 10, "2026-07-28T09:15:00+05:30"),
            _make_sell("RELIANCE", 2600, 10, "2026-07-28T14:30:00+05:30", "Target"),
            _make_buy("TCS", 3200, 5, "2026-07-28T09:30:00+05:30", strategy="Mean Reversion"),
            _make_sell("TCS", 3150, 5, "2026-07-28T12:00:00+05:30", "Stop Loss"),
            _make_buy("HDFC", 1800, 20, "2026-07-29T09:15:00+05:30"),
            _make_sell("HDFC", 1850, 20, "2026-07-29T14:00:00+05:30", "Target"),
        ]
        self._mods = _patch_external()
        for m in self._mods:
            m.start()

    def tearDown(self):
        for m in self._mods:
            m.stop()

    def test_three_trades_collected(self):
        with _patch_load_trades(self.trades):
            from paper_trading_validation.validation_collector import collect_all_trade_records
            records = collect_all_trade_records()
        self.assertEqual(len(records), 3)

    def test_win_rate_two_of_three(self):
        with _patch_load_trades(self.trades):
            from paper_trading_validation.shared_services import get_statistics
            r = get_statistics()
        s = r["statistics"]
        self.assertEqual(s["total_trades"], 3)
        self.assertEqual(s["winning_trades"], 2)
        self.assertAlmostEqual(s["win_rate"], 2 / 3, places=3)

    def test_history_has_daily_rows(self):
        with _patch_load_trades(self.trades):
            from paper_trading_validation.shared_services import get_history
            r = get_history()
        self.assertGreater(len(r["history"]["daily"]), 0)

    def test_dataset_growth_cumulative(self):
        with _patch_load_trades(self.trades):
            from paper_trading_validation.metrics_engine import compute_dataset_growth
            from paper_trading_validation.validation_collector import collect_all_trade_records
            records = collect_all_trade_records()
        growth = compute_dataset_growth(records)
        final = growth["growth"][-1]
        self.assertEqual(final["cumulative_trades"], 3)

    def test_strategy_breakdown_in_stats(self):
        with _patch_load_trades(self.trades):
            from paper_trading_validation.shared_services import get_statistics
            r = get_statistics()
        strategies = [s["strategy"] for s in r["statistics"]["strategies"]]
        self.assertIn("Momentum", strategies)
        self.assertIn("Mean Reversion", strategies)

    def test_exit_reason_counts(self):
        with _patch_load_trades(self.trades):
            from paper_trading_validation.shared_services import get_statistics
            r = get_statistics()
        exits = r["statistics"]["exit_reasons"]
        self.assertEqual(exits.get("Target"), 2)
        self.assertEqual(exits.get("Stop Loss"), 1)


# ---------------------------------------------------------------------------
# TestCorruptedRecordDetection
# ---------------------------------------------------------------------------

class TestCorruptedRecordDetection(unittest.TestCase):

    def setUp(self):
        os.environ["PAPER_VALIDATION_ENABLED"] = "true"

    def test_pnl_mismatch_flagged(self):
        from paper_trading_validation.validation_models import TradeRecord
        from paper_trading_validation.data_quality import run_quality_checks
        rec = TradeRecord(
            trade_id="bad_pnl", timestamp="2026-07-29T10:00:00+05:30",
            symbol="INFY", strategy="Momentum", market_regime="BULLISH",
            sector="IT", entry_price=1500.0, exit_price=1520.0, quantity=10,
            holding_time_minutes=60.0, pnl=9999.0,  # should be 200
            pnl_pct=1.33, execution_quality_score=None, ai_confidence=None,
            ai_recommendation=None, signal_validation_status=None, risk_score=None,
            portfolio_value_at_entry=None, executive_score_snapshot=None, exit_reason="Target",
        )
        report = run_quality_checks([rec])
        self.assertTrue(any("bad_pnl" in c for c in report.corrupted_records))

    def test_negative_holding_time_flagged(self):
        from paper_trading_validation.validation_models import TradeRecord
        from paper_trading_validation.data_quality import run_quality_checks
        rec = TradeRecord(
            trade_id="neg_hold", timestamp="2026-07-29T10:00:00+05:30",
            symbol="WIPRO", strategy="Breakout", market_regime="BULLISH",
            sector="IT", entry_price=400.0, exit_price=410.0, quantity=5,
            holding_time_minutes=-30.0, pnl=50.0, pnl_pct=2.5,
            execution_quality_score=None, ai_confidence=None, ai_recommendation=None,
            signal_validation_status=None, risk_score=None, portfolio_value_at_entry=None,
            executive_score_snapshot=None, exit_reason="Target",
        )
        report = run_quality_checks([rec])
        self.assertTrue(any("neg_hold" in c for c in report.corrupted_records))


# ---------------------------------------------------------------------------
# TestDuplicateDetection
# ---------------------------------------------------------------------------

class TestDuplicateDetection(unittest.TestCase):

    def setUp(self):
        os.environ["PAPER_VALIDATION_ENABLED"] = "true"

    def test_duplicate_ids_flagged(self):
        from paper_trading_validation.validation_models import TradeRecord
        from paper_trading_validation.data_quality import run_quality_checks

        def _rec(tid):
            return TradeRecord(
                trade_id=tid, timestamp="2026-07-29T10:00:00+05:30",
                symbol="SBIN", strategy="Momentum", market_regime="BULLISH",
                sector="Banking", entry_price=600.0, exit_price=620.0, quantity=10,
                holding_time_minutes=90.0, pnl=200.0, pnl_pct=3.33,
                execution_quality_score=80.0, ai_confidence=0.7, ai_recommendation="BUY",
                signal_validation_status="VALID", risk_score=0.2, portfolio_value_at_entry=500000.0,
                executive_score_snapshot=70.0, exit_reason="Target",
            )

        report = run_quality_checks([_rec("dup_001"), _rec("dup_001")])
        self.assertIn("dup_001", report.duplicate_trades)

    def test_unique_ids_not_flagged(self):
        from paper_trading_validation.validation_models import TradeRecord
        from paper_trading_validation.data_quality import run_quality_checks

        def _rec(tid, symbol):
            return TradeRecord(
                trade_id=tid, timestamp="2026-07-29T10:00:00+05:30",
                symbol=symbol, strategy="Momentum", market_regime="BULLISH",
                sector="Banking", entry_price=600.0, exit_price=620.0, quantity=10,
                holding_time_minutes=90.0, pnl=200.0, pnl_pct=3.33,
                execution_quality_score=80.0, ai_confidence=0.7, ai_recommendation="BUY",
                signal_validation_status="VALID", risk_score=0.2, portfolio_value_at_entry=500000.0,
                executive_score_snapshot=70.0, exit_reason="Target",
            )

        report = run_quality_checks([_rec("t001", "SBIN"), _rec("t002", "HDFC")])
        self.assertEqual(report.duplicate_trades, [])


# ---------------------------------------------------------------------------
# TestExport
# ---------------------------------------------------------------------------

class TestExport(unittest.TestCase):

    def setUp(self):
        os.environ["PAPER_VALIDATION_ENABLED"] = "true"
        self._mods = _patch_external()
        for m in self._mods:
            m.start()

    def tearDown(self):
        for m in self._mods:
            m.stop()

    def test_csv_export_has_headers(self):
        trades = [_make_buy(), _make_sell()]
        with _patch_load_trades(trades):
            from paper_trading_validation.shared_services import export_records_csv
            csv_str = export_records_csv()
        self.assertIn("trade_id", csv_str)
        self.assertIn("symbol", csv_str)
        self.assertIn("pnl", csv_str)
        # One data row
        lines = [l for l in csv_str.splitlines() if l.strip()]
        self.assertEqual(len(lines), 2)  # header + 1 trade

    def test_json_export_is_valid(self):
        trades = [_make_buy(), _make_sell()]
        with _patch_load_trades(trades):
            from paper_trading_validation.shared_services import export_records_json
            json_str = export_records_json()
        data = json.loads(json_str)
        self.assertEqual(len(data), 1)
        self.assertIn("symbol", data[0])
        self.assertIn("pnl", data[0])

    def test_export_disabled_when_flag_off(self):
        with patch.dict(os.environ, {"PAPER_VALIDATION_ENABLED": "false"}):
            from paper_trading_validation.shared_services import export_records_csv, export_records_json
            self.assertEqual(export_records_csv(), "")
            self.assertEqual(export_records_json(), "")

    def test_pdf_stub_returns_metadata(self):
        from paper_trading_validation.export_service import export_pdf_stub
        stub = export_pdf_stub()
        self.assertEqual(stub["status"], "NOT_IMPLEMENTED")
        self.assertIn("future_fields", stub)


# ---------------------------------------------------------------------------
# TestDataQualityChecks
# ---------------------------------------------------------------------------

class TestDataQualityChecks(unittest.TestCase):

    def setUp(self):
        os.environ["PAPER_VALIDATION_ENABLED"] = "true"

    def test_quality_endpoint_returns_report(self):
        from paper_trading_validation.validation_models import TradeRecord
        from paper_trading_validation.data_quality import run_quality_checks

        rec = TradeRecord(
            trade_id="good_001", timestamp="2026-07-29T10:00:00+05:30",
            symbol="RELIANCE", strategy="Momentum", market_regime="BULLISH",
            sector="Energy", entry_price=2500.0, exit_price=2600.0, quantity=10,
            holding_time_minutes=315.0, pnl=1000.0, pnl_pct=4.0,
            execution_quality_score=88.0, ai_confidence=0.78, ai_recommendation="BUY",
            signal_validation_status="VALID", risk_score=0.3, portfolio_value_at_entry=500000.0,
            executive_score_snapshot=72.0, exit_reason="Target",
        )
        report = run_quality_checks([rec])
        self.assertEqual(report.total_records, 1)
        self.assertGreater(report.quality_score, 90)
        self.assertEqual(report.verdict, "CLEAN")

    def test_impossible_price_flagged(self):
        from paper_trading_validation.validation_models import TradeRecord
        from paper_trading_validation.data_quality import run_quality_checks

        rec = TradeRecord(
            trade_id="imp_price", timestamp="2026-07-29T10:00:00+05:30",
            symbol="TEST", strategy="Momentum", market_regime="BULLISH",
            sector="IT", entry_price=100.0, exit_price=5000.0, quantity=10,
            holding_time_minutes=30.0, pnl=48900.0, pnl_pct=4890.0,
            execution_quality_score=None, ai_confidence=None, ai_recommendation=None,
            signal_validation_status=None, risk_score=None, portfolio_value_at_entry=None,
            executive_score_snapshot=None, exit_reason="Target",
        )
        report = run_quality_checks([rec])
        self.assertTrue(any("imp_price" in p for p in report.impossible_prices))


# ---------------------------------------------------------------------------
# TestRestartPersistence
# ---------------------------------------------------------------------------

class TestRestartPersistence(unittest.TestCase):
    """Two sequential calls must return identical results (deterministic)."""

    def setUp(self):
        os.environ["PAPER_VALIDATION_ENABLED"] = "true"
        self._mods = _patch_external()
        for m in self._mods:
            m.start()

    def tearDown(self):
        for m in self._mods:
            m.stop()

    def test_statistics_deterministic(self):
        trades = [_make_buy(), _make_sell()]
        with _patch_load_trades(trades):
            from paper_trading_validation.shared_services import get_statistics
            r1 = get_statistics()
            r2 = get_statistics()
        self.assertEqual(r1["statistics"]["total_trades"], r2["statistics"]["total_trades"])
        self.assertEqual(r1["statistics"]["net_pnl"], r2["statistics"]["net_pnl"])

    def test_quality_deterministic(self):
        trades = [_make_buy(), _make_sell()]
        with _patch_load_trades(trades):
            from paper_trading_validation.shared_services import get_quality
            r1 = get_quality()
            r2 = get_quality()
        self.assertEqual(r1["quality"]["quality_score"], r2["quality"]["quality_score"])
        self.assertEqual(r1["quality"]["verdict"], r2["quality"]["verdict"])


# ---------------------------------------------------------------------------
# TestValidationSnapshot
# ---------------------------------------------------------------------------

class TestValidationSnapshot(unittest.TestCase):

    def setUp(self):
        os.environ["PAPER_VALIDATION_ENABLED"] = "true"
        self._mods = _patch_external()
        for m in self._mods:
            m.start()

    def tearDown(self):
        for m in self._mods:
            m.stop()

    def test_snapshot_has_required_keys(self):
        trades = [_make_buy(), _make_sell()]
        with _patch_load_trades(trades):
            from paper_trading_validation.shared_services import get_validation_snapshot
            snap = get_validation_snapshot()
        required = ["total_validated_trades", "validation_win_rate", "validation_net_pnl",
                    "avg_ai_confidence", "avg_execution_score", "max_drawdown"]
        for key in required:
            self.assertIn(key, snap, f"Missing key: {key}")

    def test_snapshot_returns_zeros_on_no_trades(self):
        with _patch_load_trades([]):
            from paper_trading_validation.shared_services import get_validation_snapshot
            snap = get_validation_snapshot()
        self.assertEqual(snap["total_validated_trades"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
