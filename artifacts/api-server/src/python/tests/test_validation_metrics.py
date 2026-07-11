"""
Deterministic tests for v2.4 validation metrics, calibration, outcomes,
stability and the configurable verdict.
Run: python tests/test_validation_metrics.py  (from src/python)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from validation_metrics import (
    compute_performance_metrics, compute_calibration,
    compute_recommendation_outcomes, compute_stability, evaluate_verdict,
    max_drawdown_from_curve, drawdown_series, DEFAULT_VERDICT_CRITERIA,
)


def _t(net, ret=None, win=None, conf=70, days=5, exit_date="2025-06-30",
       invested=1000.0, costs=10.0, **extra):
    d = {
        "net_pnl": net, "return_pct": ret if ret is not None else net / 10.0,
        "win": win if win is not None else net > 0, "confidence": conf,
        "holding_days": days, "exit_date": exit_date, "invested": invested,
        "total_costs": costs, "symbol": extra.pop("symbol", "AAA"),
    }
    d.update(extra)
    return d


# ── Performance metrics ──────────────────────────────────────────────────────

def test_empty_metrics():
    m = compute_performance_metrics([], 5000.0)
    assert m["total_trades"] == 0 and m["net_profit"] == 0.0
    assert m["profit_factor"] == 0.0 and m["win_rate"] == 0.0


def test_core_metrics_arithmetic():
    trades = [_t(300), _t(100), _t(-100), _t(-100)]
    m = compute_performance_metrics(trades, 5000.0, trading_days=252)
    assert m["total_trades"] == 4 and m["winning_trades"] == 2
    assert m["win_rate"] == 50.0
    assert m["gross_profit"] == 400.0 and m["gross_loss"] == -200.0
    assert m["net_profit"] == 200.0
    assert m["expectancy"] == 50.0                 # 200 / 4
    assert m["profit_factor"] == 2.0               # 400 / 200
    assert m["total_return_pct"] == 4.0            # 200 / 5000
    assert m["annualized_return_pct"] == 4.0       # exactly one year
    assert m["avg_win"] == 200.0 and m["avg_loss"] == 100.0
    assert m["total_costs"] == 40.0
    assert m["turnover"] == 0.8                    # 4000 invested / 5000


def test_profit_factor_no_losses():
    m = compute_performance_metrics([_t(100), _t(50)], 5000.0)
    assert m["profit_factor"] == 999.0             # explicit "no losses" cap


def test_drawdown_curve():
    curve = [5000, 5500, 5200, 5600, 4480]
    assert max_drawdown_from_curve(curve) == 20.0  # 5600 → 4480
    dd = drawdown_series(curve)
    assert dd[0] == 0.0 and dd[-1] == 20.0
    m = compute_performance_metrics([_t(100)], 5000.0, equity_curve=curve)
    assert m["max_drawdown_pct"] == 20.0


def test_consecutive_streaks():
    trades = [_t(-10), _t(-10), _t(-10), _t(50), _t(60), _t(-5)]
    m = compute_performance_metrics(trades, 5000.0)
    assert m["max_consecutive_losses"] == 3
    assert m["max_consecutive_wins"] == 2


# ── Calibration ──────────────────────────────────────────────────────────────

def test_calibration_bands_and_flags():
    # 20 trades in the 70-80 band: 15 winners → actual 75% ≈ predicted 75 → OK
    good = [_t(10, win=True, conf=75) for _ in range(15)] + \
           [_t(-10, win=False, conf=75) for _ in range(5)]
    # 20 trades in the 80-90 band but only 25% winners → overconfident
    bad = [_t(10, win=True, conf=85) for _ in range(5)] + \
          [_t(-10, win=False, conf=85) for _ in range(15)]
    cal = compute_calibration(good + bad)
    row70 = next(r for r in cal if r["band"] == "70-79")
    row80 = next(r for r in cal if r["band"] == "80-89")
    row50 = next(r for r in cal if r["band"] == "50-59")
    assert row70["trades"] == 20 and row70["actual_success_rate"] == 75.0
    assert row70["flag"] == "Well calibrated"
    assert row80["flag"] == "Overconfident" and row80["calibration_gap"] < 0
    assert row50["flag"] == "Insufficient sample" and row50["trades"] == 0


# ── Recommendation outcomes ──────────────────────────────────────────────────

def test_outcomes_buy_and_avoid():
    recs = (
        [{"recommendation": "BUY",
          "forward_returns": {"1": 1.0, "3": 2.0, "5": 3.0, "10": 4.0, "20": 5.0},
          "mae_pct": -1.0, "mfe_pct": 4.0}] * 3 +
        [{"recommendation": "BUY",
          "forward_returns": {"1": -1.0, "3": -1.0, "5": -1.0, "10": -1.0, "20": -1.0},
          "mae_pct": -3.0, "mfe_pct": 1.0}] +
        [{"recommendation": "AVOID",
          "forward_returns": {"1": -0.5, "3": -1.0, "5": -2.0, "10": -2.0, "20": -3.0},
          "mae_pct": -4.0, "mfe_pct": 0.5}] * 2
    )
    out = compute_recommendation_outcomes(recs)
    buy = next(r for r in out if r["recommendation"] == "BUY")
    avoid = next(r for r in out if r["recommendation"] == "AVOID")
    assert buy["issued"] == 4 and buy["win_rate"] == 75.0     # 3 of 4 rose at 5d
    assert buy["fwd_return_5d"] == 2.0                        # (3+3+3-1)/4
    assert buy["losses_prevented"] is None                    # N/A for BUY
    assert avoid["issued"] == 2 and avoid["win_rate"] == 100.0
    assert avoid["losses_prevented"] == 2
    assert avoid["loss_prevention_rate"] == 100.0
    strong = next(r for r in out if r["recommendation"] == "STRONG BUY")
    assert strong["issued"] == 0 and strong["fwd_return_5d"] is None


# ── Stability ────────────────────────────────────────────────────────────────

def test_stability_grouping_and_concentration():
    trades = (
        [_t(500, symbol="WINNER", market_regime="Bullish", strategy_id="s1",
            exit_date="2025-03-01")] +
        [_t(20, symbol=f"S{i}", market_regime="Bearish", strategy_id="s2",
            exit_date="2024-11-01") for i in range(5)]
    )
    st = compute_stability(trades)
    assert any("WINNER" in f for f in st["concentration_flags"])  # 500/600 > 50%
    years = {g["group"] for g in st["by_year"]}
    assert years == {"2024", "2025"}
    bull = next(g for g in st["bull_bear"] if g["group"] == "Bullish period")
    assert bull["trades"] == 1 and bull["net_pnl"] == 500.0
    # Balanced profits across stocks, sectors, months and strategies → no flags
    st2 = compute_stability([
        _t(50, symbol=f"S{i}", sector=f"Sector{i % 4}",
           strategy_id=f"strat{i % 3}", exit_date=f"2025-{(i % 6) + 1:02d}-01")
        for i in range(12)
    ])
    assert st2["concentration_flags"] == []


# ── Verdict ──────────────────────────────────────────────────────────────────

def _metrics(**over):
    base = {"total_trades": 150, "expectancy": 5.0, "profit_factor": 1.4,
            "max_drawdown_pct": 12.0, "total_return_pct": 10.0,
            "net_profit": 500.0}
    base.update(over)
    return base


def _windows(n=4, profitable=4):
    return [{"full_metrics": {"net_profit": 100.0 if i < profitable else -50.0}}
            for i in range(n)]


def test_verdict_passed():
    v = evaluate_verdict(_metrics(), _metrics(total_return_pct=6.0),
                         {"concentration_flags": []}, _windows())
    assert v["verdict"] == "PASSED"
    assert all(c["passed"] for c in v["checks"])


def test_verdict_insufficient_data():
    v = evaluate_verdict(_metrics(total_trades=10), _metrics(),
                         {"concentration_flags": []}, _windows(1, 1))
    assert v["verdict"] == "INSUFFICIENT DATA"
    assert "10" in v["summary"]


def test_verdict_hard_fail_profit_factor():
    v = evaluate_verdict(_metrics(profit_factor=1.0),
                         _metrics(total_return_pct=6.0),
                         {"concentration_flags": []}, _windows())
    assert v["verdict"] == "FAILED"
    assert "Profit factor" in v["summary"]


def test_verdict_soft_fail_concentration_and_base():
    v = evaluate_verdict(_metrics(total_return_pct=5.0),
                         _metrics(total_return_pct=6.0),   # base beats full
                         {"concentration_flags": ["60% from one stock: X"]},
                         _windows())
    assert v["verdict"] == "PASSED WITH CAUTION"


def test_verdict_configurable_criteria():
    # Stricter PF requirement flips PASSED → FAILED
    v = evaluate_verdict(_metrics(profit_factor=1.4),
                         _metrics(total_return_pct=6.0),
                         {"concentration_flags": []}, _windows(),
                         criteria={"min_profit_factor": 2.0})
    assert v["verdict"] == "FAILED"
    assert v["criteria"]["min_profit_factor"] == 2.0
    # Looser min_trades accepts a small sample
    v2 = evaluate_verdict(_metrics(total_trades=30),
                          _metrics(total_return_pct=6.0),
                          {"concentration_flags": []}, _windows(),
                          criteria={"min_trades": 20})
    assert v2["verdict"] == "PASSED"
    # Defaults never mutated
    assert DEFAULT_VERDICT_CRITERIA["min_trades"] == 100


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test groups passed")
