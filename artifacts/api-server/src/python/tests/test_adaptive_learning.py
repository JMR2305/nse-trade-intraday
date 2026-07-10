"""
Deterministic tests for the Adaptive Learning Layer (expectancy-based, Sprint 4).
Run: python tests/test_adaptive_learning.py  (from src/python)
No external data or network required — pure logic checks.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adaptive_learning import (
    MIN_TRADES, CONF_FLOOR, CONF_CAP,
    confidence_adjustment, clamp_confidence, pattern_stats,
    find_similar, build_explanation, blended_opportunity,
    historical_component_scores,
)


def _trade(strategy="trend_rider", sector="BANKING", regime="Bullish",
           rsi_band="Strong", adx_band="Trending", ema_align="bullish",
           volume_band="Normal", rr_band="Balanced", return_percent=1.0):
    return {
        "strategy": strategy, "sector": sector, "regime": regime,
        "rsi_band": rsi_band, "adx_band": adx_band, "ema_align": ema_align,
        "volume_band": volume_band, "rr_band": rr_band,
        "return_percent": return_percent,
    }


def _stats(trades, expectancy, profit_factor, win_rate=50.0,
           avg_loss=2.0, average_return=1.0):
    return {
        "trades": trades, "wins": 0, "losses": 0,
        "win_rate": win_rate, "loss_rate": 100.0 - win_rate,
        "avg_win": 3.0, "avg_loss": avg_loss,
        "average_return": average_return,
        "profit_factor": profit_factor, "expectancy": expectancy,
        "expected_value": expectancy, "kelly_percent": 10.0,
        "max_drawdown": 5.0, "recovery_factor": 1.0,
        "sharpe": 0.3, "sortino": 0.5, "avg_holding_days": 4.0,
        "expectancy_rating": "Neutral",
    }


def test_confidence_adjustment_rules():
    # <30 trades → 0, low-confidence note
    adj, note = confidence_adjustment(_stats(29, 2.0, 3.0))
    assert adj == 0.0 and note == "Low historical confidence", (adj, note)

    # >=30, expectancy >= +0.5, PF > 1.3 → boost within +5..+15
    adj, note = confidence_adjustment(_stats(30, 0.5, 1.4))
    assert 5.0 <= adj <= 15.0 and note == "", (adj, note)
    adj, _ = confidence_adjustment(_stats(500, 5.0, 9.0))
    assert adj == 15.0, adj  # capped

    # >=30, expectancy <= -0.2 → cut within -5..-20
    adj, note = confidence_adjustment(_stats(30, -0.2, 0.9))
    assert -20.0 <= adj <= -5.0 and note == "", (adj, note)
    adj, _ = confidence_adjustment(_stats(500, -5.0, 0.1))
    assert adj == -20.0, adj  # capped

    # >=30 mixed (small positive expectancy, weak PF) → 0 with explicit note
    adj, note = confidence_adjustment(_stats(100, 0.1, 1.1))
    assert adj == 0.0 and note == "Mixed historical evidence", (adj, note)

    # Good expectancy but weak PF is NOT a boost (needs PF > 1.3)
    adj, _ = confidence_adjustment(_stats(100, 1.0, 1.2))
    assert adj == 0.0, adj


def test_clamp():
    assert clamp_confidence(-10) == CONF_FLOOR
    assert clamp_confidence(200) == CONF_CAP
    assert clamp_confidence(50.04) == 50.0


def test_pattern_stats():
    trades = [_trade(return_percent=2.0), _trade(return_percent=2.0), _trade(return_percent=-1.0)]
    s = pattern_stats(trades)
    assert s["trades"] == 3 and s["wins"] == 2 and s["losses"] == 1
    assert abs(s["win_rate"] - 66.7) < 0.1, s
    assert abs(s["loss_rate"] - 33.3) < 0.1, s
    assert abs(s["profit_factor"] - 4.0) < 0.01, s
    assert abs(s["average_return"] - 1.0) < 0.01, s
    # expectancy = 0.667*2.0 − 0.333*1.0 = 1.0
    assert abs(s["expectancy"] - 1.0) < 0.02, s
    assert s["expectancy_rating"] in ("Good", "Excellent"), s
    assert "kelly_percent" in s and "sharpe" in s and "max_drawdown" in s


def test_find_similar_tiers():
    cand = _trade()

    # Tier 1: exact sector+regime, >=2 tech bands → used when >=MIN_TRADES
    kb = [_trade() for _ in range(MIN_TRADES)]
    similar, ctx = find_similar(cand, kb)
    assert len(similar) == MIN_TRADES and ctx == "in BANKING during Bullish markets", ctx

    # Tier 2: sector differs but regime + >=3 tech bands match
    kb = [_trade(sector="IT") for _ in range(MIN_TRADES)]
    similar, ctx = find_similar(cand, kb)
    assert len(similar) == MIN_TRADES and ctx == "during Bullish markets (all sectors)", ctx

    # Tier 3: regime differs; sector + >=3 tech bands = >=4 of 7 dims
    kb = [_trade(regime="Bearish") for _ in range(MIN_TRADES)]
    similar, ctx = find_similar(cand, kb)
    assert len(similar) == MIN_TRADES and ctx == "across all market conditions", ctx

    # Strategy must always match exactly
    kb = [_trade(strategy="macd_cross") for _ in range(MIN_TRADES)]
    similar, _ = find_similar(cand, kb)
    assert len(similar) == 0

    # Below MIN_TRADES everywhere → largest set returned, stricter tier wins ties
    kb = [_trade() for _ in range(5)]
    similar, ctx = find_similar(cand, kb)
    assert len(similar) == 5 and ctx == "in BANKING during Bullish markets", ctx


def test_explanations():
    s = _stats(20, 0.5, 1.2)
    e = build_explanation("Trend Rider", "in BANKING during Bullish markets",
                          s, 0.0, "Low historical confidence")
    assert "only 20 similar historical trades" in e and "Low historical confidence" in e

    s = _stats(142, 1.72, 2.18, win_rate=68.0)
    e = build_explanation("Trend Rider", "in BANKING during Bullish markets", s, 10.0, "")
    assert "Confidence increased" in e and "+1.72% expectancy" in e and "142" in e

    s = _stats(97, -0.8, 0.7, avg_loss=2.4)
    e = build_explanation("MACD Cross", "during Bearish markets (all sectors)", s, -12.0, "")
    assert "Confidence reduced" in e and "-0.80% expectancy" in e and "-2.40%" in e

    s = _stats(100, 0.1, 1.2)
    e = build_explanation("EMA Cross", "across all market conditions",
                          s, 0.0, "Mixed historical evidence")
    assert "+0.10% expectancy" in e and "Mixed historical evidence" in e


def test_blended_opportunity():
    # Sprint 4 blend: 40% tech + 30% expectancy + 15% PF + 10% risk + 5% sector
    bd = blended_opportunity(80.0, 60.0, 50.0, 40.0, 70.0)
    # 0.40*80 + 0.30*60 + 0.15*50 + 0.10*40 + 0.05*70 = 32+18+7.5+4+3.5 = 65
    assert abs(bd["score"] - 65.0) < 0.01, bd
    assert abs(bd["technical_contribution"] - 32.0) < 0.01
    assert abs(bd["expectancy_contribution"] - 18.0) < 0.01
    assert abs(bd["pf_contribution"] - 7.5) < 0.01
    assert abs(bd["risk_contribution"] - 4.0) < 0.01
    assert abs(bd["sector_contribution"] - 3.5) < 0.01


def test_historical_component_scores():
    # Thin evidence → neutral 50s everywhere
    assert historical_component_scores(_stats(10, 3.0, 5.0)) == (50.0, 50.0, 50.0)
    # Rich evidence → deterministic mapped scores
    e, p, r = historical_component_scores(_stats(100, 1.0, 1.5))
    assert e == 70.0, e          # 50 + 1.0*20
    assert p == 50.0, p          # 1.5/3*100
    assert r == 80.0, r          # 100 − 5*4


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test groups passed")
