"""
test_paper_analytics_integration.py — Task: Paper Analytics real-data smoke test.

Unlike test_paper_analytics.py (all upstream services mocked), this suite runs
the FULL cmd_summary() / cmd_trades() pipeline end-to-end against the REAL dev
database — no mocks. It catches regressions (blank widgets, ERROR statuses,
broken FIFO matching) before an operator notices.

Behaviour:
  • Always asserts the pipeline is healthy — status ENABLED, no "ERROR",
    analytics_score within 0–100 — even on an empty dataset.
  • Once at least one CLOSED paper trade exists (a SELL row FIFO-matches a
    BUY in paper_trades), additionally asserts total_trades > 0 and win_rate
    is a float within 0–100. Until then those assertions are skipped with a
    clear message — the DB currently holding only open BUY lots is a valid
    state, not a failure.

Run:  cd artifacts/api-server/src/python && \
      PAPER_ANALYTICS_ENABLED=true python -m pytest paper_analytics/test_paper_analytics_integration.py -v
"""
import os
import unittest

import pytest

os.environ["PAPER_ANALYTICS_ENABLED"] = "true"

pytestmark = pytest.mark.integration


def _closed_trade_count() -> int:
    """Count closed trades exactly the way the pipeline does — via the
    portfolio_performance FIFO BUY→SELL matcher over the real DB."""
    from portfolio_performance.performance_engine import load_performance_data
    return len(load_performance_data().get("closed_trades", []))


def _db_reachable() -> bool:
    try:
        import psycopg2
        psycopg2.connect(os.environ["DATABASE_URL"]).close()
        return True
    except Exception:
        return False


@unittest.skipUnless(os.environ.get("DATABASE_URL"), "DATABASE_URL not set")
class TestPaperAnalyticsRealDb(unittest.TestCase):
    """End-to-end pipeline over the real dev DB — no mocked upstreams."""

    @classmethod
    def setUpClass(cls):
        if not _db_reachable():
            raise unittest.SkipTest("dev database unreachable")
        cls.closed_count = _closed_trade_count()

    # ── Always-on health assertions (valid even with zero closed trades) ──

    def test_summary_pipeline_healthy(self):
        from paper_analytics.api import cmd_summary
        s = cmd_summary()
        self.assertIsInstance(s, dict)
        self.assertNotEqual(s.get("status"), "ERROR",
                            f"summary pipeline returned ERROR: {s.get('error')}")
        self.assertEqual(s.get("status"), "ENABLED")
        self.assertTrue(s.get("available"))
        self.assertTrue(s.get("advisory_only"))
        score = s.get("analytics_score")
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)
        self.assertIsInstance(s.get("total_trades"), int)
        self.assertGreaterEqual(s["total_trades"], 0)

    def test_trades_pipeline_healthy(self):
        from paper_analytics.api import cmd_trades
        t = cmd_trades()
        self.assertNotEqual(t.get("status"), "ERROR",
                            f"trades pipeline returned ERROR: {t.get('error')}")
        self.assertEqual(t.get("status"), "ENABLED")
        self.assertIsInstance(t.get("total_trades"), int)

    def test_all_tab_commands_never_error(self):
        """Every dashboard tab's command must return a non-ERROR dict against
        the real DB — a blank widget regression shows up here first."""
        from paper_analytics import api
        for name in ("cmd_summary", "cmd_trades", "cmd_strategies", "cmd_risk",
                     "cmd_preopen", "cmd_portfolio", "cmd_learning",
                     "cmd_snapshot", "cmd_export_json"):
            with self.subTest(command=name):
                r = getattr(api, name)()
                self.assertIsInstance(r, dict)
                self.assertNotEqual(r.get("status"), "ERROR",
                                    f"{name} returned ERROR: {r.get('error')}")

    # ── Real-trade assertions (gated on at least one closed trade) ────────

    def test_summary_reflects_real_closed_trades(self):
        if self.closed_count == 0:
            self.skipTest("no closed paper trades in dev DB yet "
                          "(only open BUY lots) — assertions gated until the "
                          "auto-paper module records a SELL")
        from paper_analytics.api import cmd_summary
        s = cmd_summary()
        self.assertGreater(s["total_trades"], 0)
        self.assertEqual(s["total_trades"], self.closed_count,
                         "summary total_trades must match the FIFO-matched "
                         "closed-trade count from the canonical ledger")
        wr = s["win_rate"]
        self.assertIsInstance(wr, float)
        self.assertGreaterEqual(wr, 0.0)
        self.assertLessEqual(wr, 100.0)

    def test_trades_tab_lists_real_closed_trades(self):
        if self.closed_count == 0:
            self.skipTest("no closed paper trades in dev DB yet")
        from paper_analytics.api import cmd_trades
        t = cmd_trades()
        self.assertGreater(t["total_trades"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
