"""
Deterministic tests for the Expectancy Engine (Sprint 4).
Run: python tests/test_expectancy.py  (from src/python)
Pure arithmetic checks — no data or network required.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from expectancy import (
    compute_metrics, expectancy_rating,
    expectancy_score, profit_factor_score, risk_score,
)


def _t(ret, days=4, exit_date=""):
    return {"return_percent": ret, "holding_days": days, "exit_date": exit_date}


def test_empty():
    m = compute_metrics([])
    assert m["trades"] == 0 and m["expectancy"] == 0.0
    assert m["expectancy_rating"] == "Neutral"


def test_core_metrics():
    # 2 wins (+4, +2), 2 losses (−1, −3), in date order
    trades = [_t(4.0, 3, "2025-01-01"), _t(-1.0, 2, "2025-01-02"),
              _t(2.0, 5, "2025-01-03"), _t(-3.0, 6, "2025-01-04")]
    m = compute_metrics(trades)
    assert m["trades"] == 4 and m["wins"] == 2 and m["losses"] == 2
    assert m["win_rate"] == 50.0 and m["loss_rate"] == 50.0
    assert m["avg_win"] == 3.0, m
    assert m["avg_loss"] == 2.0, m           # magnitude
    # expectancy = 0.5*3 − 0.5*2 = 0.5
    assert m["expectancy"] == 0.5, m
    assert m["expected_value"] == 0.5, m     # mean return
    assert m["profit_factor"] == 1.5, m      # 6 / 4
    # Kelly: W − (1−W)/R = 0.5 − 0.5/1.5 = 0.1667 → 16.7%
    assert abs(m["kelly_percent"] - 16.7) < 0.05, m
    assert m["avg_holding_days"] == 4.0, m
    assert m["expectancy_rating"] == "Good", m


def test_all_wins_and_all_losses():
    m = compute_metrics([_t(2.0), _t(3.0)])
    assert m["losses"] == 0 and m["avg_loss"] == 0.0
    assert m["profit_factor"] == 999.0       # capped
    assert m["kelly_percent"] == 100.0       # W=1, no losses
    assert m["max_drawdown"] == 0.0
    assert m["sortino"] == 99.0              # capped, no downside

    m = compute_metrics([_t(-2.0), _t(-3.0)])
    assert m["wins"] == 0 and m["profit_factor"] == 0.0
    assert m["kelly_percent"] == 0.0
    assert m["expectancy"] < 0 and m["expectancy_rating"] == "Negative"


def test_drawdown_and_recovery():
    # +10% then −20% then +30% (compounded, exit-date order)
    trades = [_t(10.0, 1, "2025-01-01"), _t(-20.0, 1, "2025-01-02"),
              _t(30.0, 1, "2025-01-03")]
    m = compute_metrics(trades)
    assert m["max_drawdown"] == 20.0, m
    # total return = 1.1*0.8*1.3 − 1 = 14.4%; recovery = 14.4/20 = 0.72
    assert abs(m["recovery_factor"] - 0.72) < 0.01, m


def test_ratings():
    assert expectancy_rating(1.5) == "Excellent"
    assert expectancy_rating(0.5) == "Good"
    assert expectancy_rating(0.0) == "Neutral"
    assert expectancy_rating(-0.2) == "Neutral"
    assert expectancy_rating(-0.21) == "Poor"
    assert expectancy_rating(-1.01) == "Negative"


def test_score_mappers():
    assert expectancy_score(0.0) == 50.0
    assert expectancy_score(2.5) == 100.0
    assert expectancy_score(-2.5) == 0.0
    assert profit_factor_score(3.0) == 100.0
    assert profit_factor_score(1.5) == 50.0
    assert risk_score(0.0) == 100.0
    assert risk_score(25.0) == 0.0


def test_sharpe_sortino_sign():
    trades = [_t(2.0), _t(1.0), _t(3.0), _t(-1.0)]
    m = compute_metrics(trades)
    assert m["sharpe"] > 0 and m["sortino"] > 0
    assert m["sortino"] >= m["sharpe"]       # single small loss → milder downside dev


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test groups passed")
