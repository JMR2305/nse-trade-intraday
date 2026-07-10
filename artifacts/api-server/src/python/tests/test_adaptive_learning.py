"""
Deterministic tests for the Adaptive Learning Layer.
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


def _stats(trades, win_rate, profit_factor, average_return=1.0, expectancy=0.5):
    return {
        "trades": trades, "wins": 0, "losses": 0,
        "win_rate": win_rate, "average_return": average_return,
        "profit_factor": profit_factor, "expectancy": expectancy,
    }


def test_confidence_adjustment_rules():
    # <30 trades → 0, low-confidence note (spec rule)
    adj, note = confidence_adjustment(_stats(29, 80.0, 3.0))
    assert adj == 0.0 and note == "Low historical confidence", (adj, note)

    # >=30, WR>60, PF>1.5 → boost within +5..+15
    adj, note = confidence_adjustment(_stats(30, 61.0, 1.6))
    assert 5.0 <= adj <= 15.0 and note == "", (adj, note)
    adj, _ = confidence_adjustment(_stats(500, 95.0, 9.0))
    assert adj == 15.0, adj  # capped

    # >=30, WR<45, PF<1.0 → cut within -5..-20
    adj, note = confidence_adjustment(_stats(30, 44.0, 0.9))
    assert -20.0 <= adj <= -5.0 and note == "", (adj, note)
    adj, _ = confidence_adjustment(_stats(500, 5.0, 0.1))
    assert adj == -20.0, adj  # capped

    # >=30 mixed → 0 with explicit mixed-evidence note
    adj, note = confidence_adjustment(_stats(100, 52.0, 1.2))
    assert adj == 0.0 and note == "Mixed historical evidence", (adj, note)

    # Boundary cases are NOT boosts/cuts (strict inequalities)
    adj, _ = confidence_adjustment(_stats(100, 60.0, 2.0))
    assert adj == 0.0, adj
    adj, _ = confidence_adjustment(_stats(100, 45.0, 0.5))
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
    assert abs(s["profit_factor"] - 4.0) < 0.01, s
    assert abs(s["average_return"] - 1.0) < 0.01, s


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
    s = _stats(20, 55.0, 1.2)
    e = build_explanation("Trend Rider", "in BANKING during Bullish markets",
                          s, 0.0, "Low historical confidence")
    assert "only 20 similar historical trades" in e and "Low historical confidence" in e

    s = _stats(142, 68.0, 2.1)
    e = build_explanation("Trend Rider", "in BANKING during Bullish markets", s, 10.0, "")
    assert "Confidence increased" in e and "68% win rate over 142" in e

    s = _stats(97, 31.0, 0.7)
    e = build_explanation("MACD Cross", "during Bearish markets (all sectors)", s, -12.0, "")
    assert "Confidence reduced" in e and "69% of 97" in e

    s = _stats(100, 52.0, 1.2)
    e = build_explanation("EMA Cross", "across all market conditions",
                          s, 0.0, "Mixed historical evidence")
    assert "mixed results" in e and "Mixed historical evidence" in e


def test_blended_opportunity():
    bd = blended_opportunity(technical=80.0, historical=60.0,
                           sector_strength=50.0, regime_strength=40.0)
    # 0.4*80 + 0.3*60 + 0.2*50 + 0.1*40 = 32 + 18 + 10 + 4 = 64
    assert abs(bd["score"] - 64.0) < 0.01, bd
    assert abs(bd["technical_contribution"] - 32.0) < 0.01
    assert abs(bd["historical_contribution"] - 18.0) < 0.01
    assert abs(bd["sector_contribution"] - 10.0) < 0.01
    assert abs(bd["regime_contribution"] - 4.0) < 0.01


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test groups passed")
