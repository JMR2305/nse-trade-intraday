"""Unit tests for compute_rolling_performance in paper_trader."""
import unittest

import paper_trader as pt


def _t(sym: str, exit_time: str, pnl: float, pnl_pct: float) -> dict:
    return {"symbol": sym, "exit_time": exit_time, "pnl": pnl, "pnl_pct": pnl_pct}


class TestRollingPerformance(unittest.TestCase):

    def test_empty_replay(self):
        self.assertEqual(pt.compute_rolling_performance([]), [])

    def test_chronological_ordering(self):
        # replay is newest-first; points must be chronological by exit_time
        replay = [
            _t("C", "2026-07-03", 1, 1.0),
            _t("B", "2026-07-02", -1, -1.0),
            _t("A", "2026-07-01", 2, 2.0),
        ]
        pts = pt.compute_rolling_performance(replay)
        self.assertEqual([p["symbol"] for p in pts], ["A", "B", "C"])
        self.assertEqual([p["trade_no"] for p in pts], [1, 2, 3])

    def test_partial_window_flagged(self):
        replay = [_t(f"S{i}", f"2026-07-{i+1:02d}", 1, 1.0) for i in range(5)]
        pts = pt.compute_rolling_performance(replay, window=10)
        self.assertTrue(all(not p["window_full"] for p in pts))
        self.assertEqual(pts[-1]["window_trades"], 5)

    def test_rolling_math_and_rounding(self):
        pnls = [5, -2, 3, -1, -4, 6, 2, -3, 1, 4, -2, 5]
        replay = [_t(f"S{i}", f"2026-07-{i+1:02d}", p, float(p))
                  for i, p in enumerate(pnls)]
        pts = pt.compute_rolling_performance(list(reversed(replay)), window=10)
        self.assertEqual(len(pts), 12)
        last = pts[-1]
        # trailing 10: [3,-1,-4,6,2,-3,1,4,-2,5] -> 6 wins, sum 11
        self.assertTrue(last["window_full"])
        self.assertEqual(last["rolling_win_rate"], 60.0)
        self.assertEqual(last["rolling_avg_return_pct"], 1.1)
        first = pts[0]
        self.assertEqual(first["rolling_win_rate"], 100.0)
        self.assertEqual(first["rolling_avg_return_pct"], 5.0)

    def test_breakeven_trade_not_a_win(self):
        replay = [_t("A", "2026-07-01", 0, 0.0), _t("B", "2026-07-02", 1, 1.0)]
        pts = pt.compute_rolling_performance(replay)
        self.assertEqual(pts[0]["rolling_win_rate"], 0.0)
        self.assertEqual(pts[1]["rolling_win_rate"], 50.0)

    def test_missing_pnl_pct_defaults_zero(self):
        replay = [{"symbol": "A", "exit_time": "2026-07-01", "pnl": 1,
                   "pnl_pct": None}]
        pts = pt.compute_rolling_performance(replay)
        self.assertEqual(pts[0]["rolling_avg_return_pct"], 0.0)


if __name__ == "__main__":
    res = unittest.main(exit=False).result
    total = res.testsRun
    failed = len(res.failures) + len(res.errors)
    print(f"{total - failed} passed, {failed} failed")
