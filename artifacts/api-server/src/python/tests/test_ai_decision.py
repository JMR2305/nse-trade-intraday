"""
Deterministic tests for AI decision downgrade logic (bullish AND bearish).
Run: python tests/test_ai_decision.py  (from src/python)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_decision import make_ai_decision


def _signal(signal="BUY", confidence=80.0, price=100.0, stop_loss=95.0,
            target=115.0, regime="TRENDING_UP", timeframe_alignment=4,
            risk_level="MEDIUM", stock="TEST"):
    return {
        "stock": stock, "signal": signal, "confidence": confidence,
        "price": price, "stop_loss": stop_loss, "target": target,
        "regime": regime, "timeframe_alignment": timeframe_alignment,
        "risk_level": risk_level,
    }


def test_buy_downgraded_on_poor_rr():
    # RR = 5/5 = 1:1 < 2:1 → confidence capped at 68 → WATCH
    d = make_ai_decision(_signal(signal="BUY", confidence=85.0,
                                 price=100.0, stop_loss=95.0, target=105.0))
    assert d["decision"] == "WATCH", d["decision"]
    assert d["downgrade_reasons"], "expected a downgrade reason"


def test_sell_downgraded_on_poor_rr():
    # Bearish: entry 100, stop 105, target 95 → RR 1:1 → must downgrade to WATCH
    d = make_ai_decision(_signal(signal="SELL", confidence=85.0,
                                 price=100.0, stop_loss=105.0, target=95.0,
                                 regime="TRENDING_DOWN"))
    assert d["decision"] == "WATCH", f"bearish downgrade failed: {d['decision']}"
    assert d["downgrade_reasons"]


def test_strong_sell_downgraded_on_low_tf_alignment():
    # Only 1/4 timeframes agree → cap 70 → WATCH (not kept as STRONG_SELL)
    d = make_ai_decision(_signal(signal="STRONG_SELL", confidence=92.0,
                                 price=100.0, stop_loss=104.0, target=88.0,
                                 regime="TRENDING_DOWN", timeframe_alignment=1))
    assert d["decision"] == "WATCH", f"expected WATCH, got {d['decision']}"


def test_sell_high_volatility_low_confidence():
    d = make_ai_decision(_signal(signal="SELL", confidence=65.0,
                                 price=100.0, stop_loss=104.0, target=88.0,
                                 regime="HIGH_VOLATILITY"))
    assert d["decision"] in ("WATCH", "NO_TRADE"), d["decision"]


def test_downgrade_never_upgrades():
    # WATCH stays WATCH even if adjusted confidence would classify higher
    d = make_ai_decision(_signal(signal="WATCH", confidence=74.0,
                                 price=100.0, stop_loss=96.0, target=112.0))
    assert d["decision"] in ("WATCH", "NO_TRADE"), d["decision"]


def test_good_buy_passes():
    # RR 3:1, 4/4 alignment, supportive regime → stays actionable
    d = make_ai_decision(_signal(signal="BUY", confidence=80.0,
                                 price=100.0, stop_loss=95.0, target=115.0,
                                 regime="TRENDING_UP", timeframe_alignment=4))
    assert d["decision"] in ("BUY", "STRONG_BUY"), d["decision"]
    assert not d["downgrade_reasons"]


def test_good_sell_passes():
    d = make_ai_decision(_signal(signal="SELL", confidence=80.0,
                                 price=100.0, stop_loss=105.0, target=85.0,
                                 regime="TRENDING_DOWN", timeframe_alignment=4))
    assert d["decision"] in ("SELL", "STRONG_SELL"), d["decision"]
    assert not d["downgrade_reasons"]


def test_insufficient_capital():
    d = make_ai_decision(_signal(signal="BUY", confidence=90.0,
                                 price=10000.0, stop_loss=9500.0, target=11500.0),
                         available_cash=5000.0)
    assert d["decision"] == "NO_TRADE", d["decision"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
